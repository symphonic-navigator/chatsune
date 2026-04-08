"""Tests for the disconnect-extraction retry buffer and recovery loop (H-003)."""

import json
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from backend.jobs._disconnect_retry import (
    buffer_key,
    buffer_submit_payload,
    dead_key,
    drain_disconnect_retry_buffer,
)


@pytest_asyncio.fixture
async def redis(clean_db):
    from backend.database import connect_db, disconnect_db, get_redis
    await connect_db()
    try:
        yield get_redis()
    finally:
        await disconnect_db()


async def test_retry_loop_happy_path(redis, monkeypatch):
    """First attempt succeeds — submit called once, buffer stays empty."""
    from backend.modules.chat import _orchestrator

    submit_mock = AsyncMock(return_value="job-xyz")
    monkeypatch.setattr(_orchestrator, "submit", submit_mock)

    # Seed the tracking key so trigger_disconnect_extraction has work to do.
    user_id = "user-happy"
    persona_id = "persona-1"
    session_id = "sess-1"
    tracking_key = f"memory:extraction:{user_id}:{persona_id}"
    await redis.hset(
        tracking_key,
        mapping={
            "messages_since_extraction": "2",
            "session_id": session_id,
            "model_unique_id": "ollama_cloud:llama3.2",
        },
    )

    # Stub out the repo and slot acquisition.
    async def fake_list(session_id_arg, limit=20):
        return [
            {"_id": "m1", "content": "hello"},
            {"_id": "m2", "content": "world"},
        ]

    class FakeRepo:
        def __init__(self, db): pass
        async def list_unextracted_user_messages(self, sid, limit=20):
            return await fake_list(sid, limit)

    monkeypatch.setattr(_orchestrator, "ChatRepository", FakeRepo)
    monkeypatch.setattr(_orchestrator, "get_db", lambda: None)

    async def fake_try_acquire(r, key, ttl_seconds):
        return True
    monkeypatch.setattr(_orchestrator, "try_acquire_inflight_slot", fake_try_acquire)

    await _orchestrator.trigger_disconnect_extraction(user_id)

    assert submit_mock.await_count == 1
    assert await redis.zcard(buffer_key(user_id)) == 0


async def test_retry_loop_exhaustion_buffers(redis, monkeypatch):
    """All three attempts fail — payload lands in the zset at score 0.0."""
    from backend.modules.chat import _orchestrator

    submit_mock = AsyncMock(side_effect=RuntimeError("redis timeout"))
    monkeypatch.setattr(_orchestrator, "submit", submit_mock)

    user_id = "user-fail"
    persona_id = "persona-1"
    session_id = "sess-1"
    await redis.hset(
        f"memory:extraction:{user_id}:{persona_id}",
        mapping={
            "messages_since_extraction": "2",
            "session_id": session_id,
            "model_unique_id": "ollama_cloud:llama3.2",
        },
    )

    class FakeRepo:
        def __init__(self, db): pass
        async def list_unextracted_user_messages(self, sid, limit=20):
            return [{"_id": "m1", "content": "hi"}]

    monkeypatch.setattr(_orchestrator, "ChatRepository", FakeRepo)
    monkeypatch.setattr(_orchestrator, "get_db", lambda: None)

    async def fake_try_acquire(r, key, ttl_seconds):
        return True
    monkeypatch.setattr(_orchestrator, "try_acquire_inflight_slot", fake_try_acquire)

    await _orchestrator.trigger_disconnect_extraction(user_id)

    assert submit_mock.await_count == 3
    entries = await redis.zrange(buffer_key(user_id), 0, -1, withscores=True)
    assert len(entries) == 1
    _, score = entries[0]
    assert score == 0.0


async def test_recovery_loop_drains_on_success(redis, monkeypatch):
    """Seed one buffered entry, mock submit to succeed, drain once, assert empty."""
    from backend.jobs import _disconnect_retry

    submit_mock = AsyncMock(return_value="job-ok")
    monkeypatch.setattr(_disconnect_retry, "submit", submit_mock)

    user_id = "user-drain"
    submit_kwargs = {
        "job_type": "memory_extraction",
        "user_id": user_id,
        "model_unique_id": "ollama_cloud:llama3.2",
        "payload": {"persona_id": "p1", "session_id": "s1", "messages": ["hi"], "message_ids": ["m1"]},
    }
    await buffer_submit_payload(redis, user_id, submit_kwargs)
    assert await redis.zcard(buffer_key(user_id)) == 1

    await drain_disconnect_retry_buffer(redis)

    assert submit_mock.await_count == 1
    assert await redis.zcard(buffer_key(user_id)) == 0


async def test_recovery_loop_dead_letters_after_max_attempts(redis, monkeypatch):
    """Entry at score 4 that fails again moves to the dead-letter list."""
    from backend.jobs import _disconnect_retry

    submit_mock = AsyncMock(side_effect=RuntimeError("still down"))
    monkeypatch.setattr(_disconnect_retry, "submit", submit_mock)

    user_id = "user-dead"
    submit_kwargs = {
        "job_type": "memory_extraction",
        "user_id": user_id,
        "model_unique_id": "ollama_cloud:llama3.2",
        "payload": {"persona_id": "p1", "session_id": "s1", "messages": ["hi"], "message_ids": ["m1"]},
    }
    member = json.dumps(submit_kwargs, sort_keys=True, default=str)
    await redis.zadd(buffer_key(user_id), {member: 4.0})

    await drain_disconnect_retry_buffer(redis)

    assert await redis.zcard(buffer_key(user_id)) == 0
    dead_entries = await redis.lrange(dead_key(user_id), 0, -1)
    assert len(dead_entries) == 1
    raw = dead_entries[0]
    if isinstance(raw, bytes):
        raw = raw.decode()
    assert json.loads(raw) == submit_kwargs

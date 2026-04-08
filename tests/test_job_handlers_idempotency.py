"""Tests for Task 12 — execution-token idempotency guard and transaction
atomicity of the memory extraction handler."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest

from backend.jobs._models import JobEntry, JobType


class _FakeRedis:
    """Minimal fake redis capturing SET NX semantics used by the guard."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, bool, int | None]] = []

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None):
        self.set_calls.append((key, value, nx, ex))
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def hset(self, *args, **kwargs):  # pragma: no cover — unused on replay path
        raise AssertionError(
            "hset must not be called when the execution-token guard short-circuits",
        )


class _ExplodingEventBus:
    async def publish(self, *args, **kwargs):  # pragma: no cover — unused on replay path
        raise AssertionError(
            "event_bus.publish must not be called on the replay path",
        )


def _make_job(token: str = "tok-abc") -> JobEntry:
    return JobEntry(
        id="job-1",
        job_type=JobType.MEMORY_EXTRACTION,
        user_id="user-1",
        model_unique_id="ollama_cloud:llama3.2",
        payload={
            "persona_id": "persona-1",
            "session_id": "sess-1",
            "messages": ["hello"],
            "message_ids": ["m1"],
        },
        correlation_id="corr-1",
        created_at=datetime.now(UTC),
        execution_token=token,
    )


@pytest.mark.asyncio
async def test_memory_extraction_replay_skipped():
    """Second invocation with the same execution_token returns immediately."""
    from backend.jobs._registry import JOB_REGISTRY
    from backend.jobs.handlers._memory_extraction import handle_memory_extraction

    redis = _FakeRedis()
    # Pre-populate the token key to simulate a prior run.
    redis.store[f"job:executed:tok-abc"] = "1"

    job = _make_job("tok-abc")
    config = JOB_REGISTRY[JobType.MEMORY_EXTRACTION]

    # Must return without touching the DB or publishing any events —
    # _ExplodingEventBus would raise if touched.
    await handle_memory_extraction(job, config, redis, _ExplodingEventBus())

    # The guard attempted exactly one SET NX call.
    assert len(redis.set_calls) == 1
    key, value, nx, ex = redis.set_calls[0]
    assert key == "job:executed:tok-abc"
    assert value == "1"
    assert nx is True
    assert ex == 48 * 3600


@pytest.mark.asyncio
async def test_title_generation_replay_skipped():
    from backend.jobs._registry import JOB_REGISTRY
    from backend.jobs.handlers._title_generation import handle_title_generation

    redis = _FakeRedis()
    redis.store["job:executed:tok-title"] = "1"

    job = JobEntry(
        id="job-t",
        job_type=JobType.TITLE_GENERATION,
        user_id="user-1",
        model_unique_id="ollama_cloud:llama3.2",
        payload={"session_id": "sess-1", "messages": []},
        correlation_id="corr-1",
        created_at=datetime.now(UTC),
        execution_token="tok-title",
    )
    config = JOB_REGISTRY[JobType.TITLE_GENERATION]

    await handle_title_generation(job, config, redis, _ExplodingEventBus())


@pytest.mark.asyncio
async def test_memory_consolidation_replay_skipped():
    from backend.jobs._registry import JOB_REGISTRY
    from backend.jobs.handlers._memory_consolidation import handle_memory_consolidation

    redis = _FakeRedis()
    redis.store["job:executed:tok-cons"] = "1"

    job = JobEntry(
        id="job-c",
        job_type=JobType.MEMORY_CONSOLIDATION,
        user_id="user-1",
        model_unique_id="ollama_cloud:llama3.2",
        payload={"persona_id": "persona-1"},
        correlation_id="corr-1",
        created_at=datetime.now(UTC),
        execution_token="tok-cons",
    )
    config = JOB_REGISTRY[JobType.MEMORY_CONSOLIDATION]

    await handle_memory_consolidation(job, config, redis, _ExplodingEventBus())


def test_memory_extraction_uses_transaction():
    """Structural guarantee: the handler wraps its writes in a MongoDB
    transaction so partial failures cannot leak journal entries without the
    corresponding mark_messages_extracted update (and vice versa)."""
    from backend.jobs.handlers import _memory_extraction

    src = inspect.getsource(_memory_extraction.handle_memory_extraction)
    assert "start_session()" in src
    assert "start_transaction()" in src
    # Writes must happen inside the transaction with a session kwarg.
    assert "session=mongo_session" in src
    # Events must be published from the post-commit loop, not inline.
    commit_idx = src.index("Transaction committed")
    publish_idx = src.index("event_bus.publish(\n                Topics.MEMORY_ENTRY_CREATED")
    assert publish_idx > commit_idx

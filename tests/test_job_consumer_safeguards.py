"""Safeguard integration tests for backend.jobs._consumer.

Covers Task 9 of the background-jobs hardening plan: safeguard
preconditions raise ``UnrecoverableJobError`` (skipping retries), handler
failures hit the circuit breaker, and the per-user queue cap zset stays
consistent with the stream via ``acknowledge_job_done``.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest_asyncio


@pytest_asyncio.fixture
async def redis(clean_db):
    from backend.database import connect_db, disconnect_db, get_redis
    await connect_db()
    try:
        yield get_redis()
    finally:
        await disconnect_db()


async def _enqueue_job(redis, user_id="user-sg", payload=None,
                       model_unique_id="ollama_cloud:llama3.2"):
    from backend.jobs._models import JobEntry, JobType

    entry = JobEntry(
        id=f"job-{id(payload)}",
        job_type=JobType.TITLE_GENERATION,
        user_id=user_id,
        model_unique_id=model_unique_id,
        payload=payload or {},
        correlation_id="corr-sg",
        created_at=datetime.now(timezone.utc),
    )
    await redis.xadd("jobs:pending", {"data": entry.model_dump_json()})
    return entry


async def test_consumer_rejects_when_emergency_stop(redis, monkeypatch):
    """With kill-switch active, the job must be acked as unrecoverable
    (no retry) and a JOB_FAILED event published."""
    from backend.jobs._consumer import ensure_consumer_group, process_one
    from backend.jobs._models import JobConfig, JobType
    from backend.jobs._registry import JOB_REGISTRY

    monkeypatch.setenv("OLLAMA_CLOUD_EMERGENCY_STOP", "true")

    handler = AsyncMock()
    original = JOB_REGISTRY[JobType.TITLE_GENERATION]
    JOB_REGISTRY[JobType.TITLE_GENERATION] = JobConfig(
        handler=handler,
        max_retries=3,
        retry_delay_seconds=original.retry_delay_seconds,
        queue_timeout_seconds=original.queue_timeout_seconds,
        execution_timeout_seconds=original.execution_timeout_seconds,
        reasoning_enabled=original.reasoning_enabled,
        notify=False,
        notify_error=True,
    )

    try:
        event_bus = AsyncMock()
        await _enqueue_job(redis, payload={"a": 1})
        await ensure_consumer_group(redis)

        result = await process_one(redis, event_bus)
        assert result is True

        # Handler must NOT have been invoked.
        handler.assert_not_awaited()

        topics = [c.args[0] for c in event_bus.publish.call_args_list]
        # Unrecoverable: final failure on first try, no retry event.
        assert "job.failed" in topics
        assert "job.retry" not in topics

        # Stream must be empty.
        remaining = await redis.xrange("jobs:pending")
        assert remaining == []
    finally:
        JOB_REGISTRY[JobType.TITLE_GENERATION] = original


async def test_consumer_records_failure_on_handler_exception(redis, monkeypatch):
    """A handler exception must bump the circuit-breaker failure counter."""
    from backend.jobs._consumer import ensure_consumer_group, process_one
    from backend.jobs._models import JobConfig, JobType
    from backend.jobs._registry import JOB_REGISTRY

    monkeypatch.delenv("OLLAMA_CLOUD_EMERGENCY_STOP", raising=False)

    handler = AsyncMock(side_effect=RuntimeError("boom"))
    original = JOB_REGISTRY[JobType.TITLE_GENERATION]
    JOB_REGISTRY[JobType.TITLE_GENERATION] = JobConfig(
        handler=handler,
        max_retries=1,
        retry_delay_seconds=0.1,
        queue_timeout_seconds=3600.0,
        execution_timeout_seconds=60.0,
        reasoning_enabled=False,
        notify=False,
        notify_error=True,
    )

    try:
        event_bus = AsyncMock()
        await _enqueue_job(redis, user_id="user-cb", payload={"x": 1})
        await ensure_consumer_group(redis)

        # max_retries=1 so first attempt is also final → record_failure runs.
        await process_one(redis, event_bus)

        # Inspect circuit-breaker failure counter directly.
        keys = [k async for k in redis.scan_iter(
            match="safeguard:cb:fail:user-cb:ollama_cloud:llama3.2")]
        assert keys, "Expected a circuit-breaker key after handler failure"
    finally:
        JOB_REGISTRY[JobType.TITLE_GENERATION] = original


async def test_consumer_acknowledge_keeps_queue_zset_consistent(redis, monkeypatch):
    """After a successful job the per-user queue zset must no longer
    reference the processed stream entry."""
    from backend.jobs._consumer import ensure_consumer_group, process_one
    from backend.jobs._models import JobConfig, JobType
    from backend.jobs._registry import JOB_REGISTRY
    from backend.jobs import submit

    monkeypatch.delenv("OLLAMA_CLOUD_EMERGENCY_STOP", raising=False)
    monkeypatch.setenv("JOB_QUEUE_CAP_PER_USER", "10")

    handler = AsyncMock()
    original = JOB_REGISTRY[JobType.TITLE_GENERATION]
    JOB_REGISTRY[JobType.TITLE_GENERATION] = JobConfig(
        handler=handler,
        max_retries=original.max_retries,
        retry_delay_seconds=original.retry_delay_seconds,
        queue_timeout_seconds=original.queue_timeout_seconds,
        execution_timeout_seconds=original.execution_timeout_seconds,
        reasoning_enabled=original.reasoning_enabled,
        notify=False,
        notify_error=False,
    )

    try:
        event_bus = AsyncMock()
        await submit(
            job_type=JobType.TITLE_GENERATION,
            user_id="user-ack",
            model_unique_id="ollama_cloud:llama3.2",
            payload={"session_id": "s"},
        )
        await ensure_consumer_group(redis)

        result = await process_one(redis, event_bus)
        assert result is True
        handler.assert_awaited_once()

        # Queue zset should now be empty for this user.
        card = await redis.zcard("safeguard:queue:user-ack")
        assert card == 0
    finally:
        JOB_REGISTRY[JobType.TITLE_GENERATION] = original

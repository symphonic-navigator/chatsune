import asyncio
from datetime import datetime, timezone, timedelta
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


async def test_retry_state_roundtrip(redis):
    from backend.jobs._retry import set_retry, get_retry, clear_retry

    next_at = datetime(2026, 4, 4, 0, 1, 0, tzinfo=timezone.utc)
    await set_retry(redis, "job-1", attempt=2, next_retry_at=next_at)

    state = await get_retry(redis, "job-1")
    assert state is not None
    assert state["attempt"] == 2
    assert state["next_retry_at"] == next_at

    await clear_retry(redis, "job-1")
    assert await get_retry(redis, "job-1") is None


async def _enqueue_job(redis, job_type="title_generation", user_id="user-1",
                       model_unique_id="ollama_cloud:llama3.2", payload=None,
                       correlation_id="corr-1", created_at=None):
    """Helper to push a job directly into the stream."""
    from backend.jobs._models import JobEntry, JobType

    entry = JobEntry(
        id=f"job-{id(payload)}",
        job_type=JobType(job_type),
        user_id=user_id,
        model_unique_id=model_unique_id,
        payload=payload or {},
        correlation_id=correlation_id,
        created_at=created_at or datetime.now(timezone.utc),
    )
    await redis.xadd("jobs:pending", {"data": entry.model_dump_json()})
    return entry


async def test_consumer_processes_job(redis):
    from backend.jobs._consumer import ensure_consumer_group, process_one
    from backend.jobs._models import JobConfig, JobType
    from backend.jobs._registry import JOB_REGISTRY

    handler = AsyncMock()
    original = JOB_REGISTRY[JobType.TITLE_GENERATION]
    JOB_REGISTRY[JobType.TITLE_GENERATION] = JobConfig(
        handler=handler,
        max_retries=original.max_retries,
        retry_delay_seconds=original.retry_delay_seconds,
        queue_timeout_seconds=original.queue_timeout_seconds,
        execution_timeout_seconds=original.execution_timeout_seconds,
        reasoning_enabled=original.reasoning_enabled,
        notify=original.notify,
        notify_error=original.notify_error,
    )

    try:
        event_bus = AsyncMock()
        entry = await _enqueue_job(redis, payload={"session_id": "sess-1"})
        await ensure_consumer_group(redis)

        processed = await process_one(redis, event_bus)
        assert processed is True
        handler.assert_awaited_once()

        call_kwargs = handler.call_args.kwargs
        assert call_kwargs["job"].user_id == "user-1"
        assert call_kwargs["job"].payload == {"session_id": "sess-1"}
    finally:
        JOB_REGISTRY[JobType.TITLE_GENERATION] = original


async def test_consumer_skips_locked_user(redis):
    from backend.jobs._consumer import ensure_consumer_group, process_one
    from backend.jobs._lock import get_user_lock

    event_bus = AsyncMock()
    entry = await _enqueue_job(redis, payload={"a": 1})
    await ensure_consumer_group(redis)

    lock = get_user_lock("user-1")
    await lock.acquire()

    try:
        processed = await process_one(redis, event_bus)
        assert processed is False  # Skipped because lock is held
    finally:
        lock.release()


async def test_consumer_expires_old_job(redis):
    from backend.jobs._consumer import ensure_consumer_group, process_one

    event_bus = AsyncMock()
    old_time = datetime.now(timezone.utc) - timedelta(hours=2)
    entry = await _enqueue_job(redis, payload={"old": True}, created_at=old_time)
    await ensure_consumer_group(redis)

    processed = await process_one(redis, event_bus)
    assert processed is True  # Processed (expired)

    # Check that a JOB_EXPIRED event was published
    event_bus.publish.assert_called()
    call_args = event_bus.publish.call_args_list
    topics = [c.args[0] for c in call_args]
    assert "job.expired" in topics


async def test_consumer_retries_then_fails(redis):
    from backend.jobs._consumer import ensure_consumer_group, process_one
    from backend.jobs._models import JobConfig, JobType
    from backend.jobs._registry import JOB_REGISTRY

    handler = AsyncMock(side_effect=RuntimeError("Boom"))
    original = JOB_REGISTRY[JobType.TITLE_GENERATION]
    JOB_REGISTRY[JobType.TITLE_GENERATION] = JobConfig(
        handler=handler,
        max_retries=2,
        retry_delay_seconds=0.1,  # Short for testing
        queue_timeout_seconds=3600.0,
        execution_timeout_seconds=60.0,
        reasoning_enabled=False,
        notify=False,
        notify_error=True,
    )

    try:
        event_bus = AsyncMock()
        entry = await _enqueue_job(redis, payload={"retry": True})
        await ensure_consumer_group(redis)

        # First attempt — should schedule retry
        result = await process_one(redis, event_bus)
        assert result is False

        topics = [c.args[0] for c in event_bus.publish.call_args_list]
        assert "job.started" in topics
        assert "job.retry" in topics

        # Wait for retry delay
        await asyncio.sleep(0.2)

        # Second attempt — should fail permanently (max_retries=2)
        event_bus.reset_mock()
        result = await process_one(redis, event_bus)
        assert result is True

        topics = [c.args[0] for c in event_bus.publish.call_args_list]
        assert "job.failed" in topics
    finally:
        JOB_REGISTRY[JobType.TITLE_GENERATION] = original

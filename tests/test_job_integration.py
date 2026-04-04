import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest_asyncio

from backend.jobs._models import JobConfig, JobType


@pytest_asyncio.fixture
async def redis(clean_db):
    from backend.database import connect_db, disconnect_db, get_redis
    await connect_db()
    try:
        yield get_redis()
    finally:
        await disconnect_db()


async def test_submit_and_consume_roundtrip(redis):
    """Submit a job via the public API and verify the consumer processes it."""
    from backend.jobs import submit
    from backend.jobs._consumer import ensure_consumer_group, process_one
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
        notify=True,  # Enable notifications to verify JOB_COMPLETED event
        notify_error=original.notify_error,
    )

    try:
        event_bus = AsyncMock()
        await ensure_consumer_group(redis)

        job_id = await submit(
            job_type=JobType.TITLE_GENERATION,
            user_id="user-1",
            model_unique_id="ollama_cloud:llama3.2",
            payload={"session_id": "sess-1", "messages": []},
            correlation_id="corr-1",
        )

        processed = await process_one(redis, event_bus)
        assert processed is True
        handler.assert_awaited_once()
        assert handler.call_args.kwargs["job"].id == job_id

        # Verify JOB_STARTED and JOB_COMPLETED events were published
        topics = [c.args[0] for c in event_bus.publish.call_args_list]
        assert "job.started" in topics
        assert "job.completed" in topics
    finally:
        JOB_REGISTRY[JobType.TITLE_GENERATION] = original


async def test_retry_on_handler_failure(redis):
    """Verify that a failing handler triggers retry logic."""
    from backend.jobs import submit
    from backend.jobs._consumer import ensure_consumer_group, process_one
    from backend.jobs._registry import JOB_REGISTRY

    handler = AsyncMock(side_effect=RuntimeError("Boom"))
    original = JOB_REGISTRY[JobType.TITLE_GENERATION]
    JOB_REGISTRY[JobType.TITLE_GENERATION] = JobConfig(
        handler=handler,
        max_retries=2,
        retry_delay_seconds=0.1,
        queue_timeout_seconds=3600.0,
        execution_timeout_seconds=60.0,
        reasoning_enabled=False,
        notify=False,
        notify_error=True,
    )

    try:
        event_bus = AsyncMock()
        await ensure_consumer_group(redis)

        await submit(
            job_type=JobType.TITLE_GENERATION,
            user_id="user-retry",
            model_unique_id="ollama_cloud:llama3.2",
            payload={"session_id": "sess-retry"},
        )

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

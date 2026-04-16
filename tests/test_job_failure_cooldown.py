"""Tests for failure-cooldown behaviour of the memory-extraction handler
and for the NameError fix in the consumer's timeout branch.

These cover three regressions:

1. On ``asyncio.TimeoutError`` the consumer must reach the retry-scheduling
   branch; previously it crashed with ``NameError: connection_id`` at the
   ``record_job_failure`` call in the timeout handler (typo of
   ``connection_slug``), which prevented a retry from being scheduled.

2. On ``asyncio.CancelledError`` inside the memory-extraction handler the
   in-flight slot must be shortened to the failure-cooldown TTL (so a
   cancelled extraction does not block the persona's slot for 30 min),
   but the cancellation itself must continue to propagate.

3. On any retryable, non-final failure in ``_on_extraction_failure`` the
   in-flight slot is likewise shortened to the failure-cooldown TTL —
   not released, and not left at the 30-min safety-net TTL.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from backend.jobs._models import JobEntry, JobType


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Minimal fake redis capturing the calls exercised by the handler."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.set_calls: list[tuple[str, str, bool, int | None]] = []
        self.expire_calls: list[tuple[str, int]] = []
        self.deleted: list[str] = []
        self.hset_calls: list[tuple[str, dict]] = []

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None):
        self.set_calls.append((key, value, nx, ex))
        if nx and key in self.store:
            return None
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def expire(self, key: str, ttl: int) -> bool:
        self.expire_calls.append((key, ttl))
        if key in self.store:
            self.ttls[key] = ttl
            return True
        return False

    async def delete(self, key: str) -> int:
        self.deleted.append(key)
        existed = key in self.store
        self.store.pop(key, None)
        self.ttls.pop(key, None)
        return 1 if existed else 0

    async def hset(self, key: str, mapping: dict | None = None, **kwargs):
        self.hset_calls.append((key, mapping or kwargs))
        return 1


class _CapturingBus:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def publish(self, topic, event, **kwargs):
        self.calls.append((topic, event))


# ---------------------------------------------------------------------------
# Bug #1 — consumer timeout path must not NameError
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def redis(clean_db):
    from backend.database import connect_db, disconnect_db, get_redis
    await connect_db()
    try:
        yield get_redis()
    finally:
        await disconnect_db()


async def _enqueue_job(
    redis,
    *,
    job_type: str = "title_generation",
    user_id: str = "user-1",
    model_unique_id: str = "conn-abc:llama3.2",
    payload: dict | None = None,
    correlation_id: str = "corr-1",
    created_at: datetime | None = None,
) -> JobEntry:
    from backend.jobs._models import JobEntry, JobType

    entry = JobEntry(
        id=f"job-{id(payload or {})}",
        job_type=JobType(job_type),
        user_id=user_id,
        model_unique_id=model_unique_id,
        payload=payload or {},
        correlation_id=correlation_id,
        created_at=created_at or datetime.now(timezone.utc),
    )
    await redis.xadd("jobs:pending", {"data": entry.model_dump_json()})
    return entry


async def test_consumer_timeout_does_not_nameerror_and_schedules_retry(
    redis, monkeypatch,
):
    """When a handler hits the execution-timeout, the consumer must call
    record_job_failure with the parsed connection slug and then schedule
    a retry. Previously this branch referenced an undefined
    ``connection_id`` local, crashing with NameError before the retry
    code was reached."""
    from backend.jobs import _consumer
    from backend.jobs._consumer import ensure_consumer_group, process_one
    from backend.jobs._models import JobConfig, JobType
    from backend.jobs._registry import JOB_REGISTRY

    async def _slow_handler(**kwargs):
        # Far exceeds the execution_timeout below, forcing the timeout
        # branch in the consumer.
        await asyncio.sleep(10)

    original = JOB_REGISTRY[JobType.TITLE_GENERATION]
    JOB_REGISTRY[JobType.TITLE_GENERATION] = JobConfig(
        handler=_slow_handler,
        max_retries=3,
        retry_delay_seconds=0.1,
        queue_timeout_seconds=3600.0,
        execution_timeout_seconds=0.1,
        reasoning_enabled=False,
        notify=False,
        notify_error=True,
    )

    record_failure_spy = AsyncMock()
    monkeypatch.setattr(_consumer, "record_job_failure", record_failure_spy)

    try:
        await _enqueue_job(
            redis,
            job_type="title_generation",
            model_unique_id="conn-abc:llama3.2",
            payload={"session_id": "sess-x"},
        )
        await ensure_consumer_group(redis)

        event_bus = AsyncMock()
        # Must not raise NameError — the timeout branch used to reference
        # an undefined local `connection_id`.
        result = await process_one(redis, event_bus)
        assert result is False  # Retry was scheduled, job not yet done.

        # record_job_failure was called with the parsed connection slug.
        record_failure_spy.assert_awaited()
        kwargs = record_failure_spy.await_args.kwargs
        assert kwargs["connection_id"] == "conn-abc"
        assert kwargs["model_slug"] == "llama3.2"

        # A retry event was published.
        topics = [c.args[0] for c in event_bus.publish.call_args_list]
        assert "job.retry" in topics
    finally:
        JOB_REGISTRY[JobType.TITLE_GENERATION] = original


# ---------------------------------------------------------------------------
# Bug #2 / #3 — failure-cooldown TTL in the memory-extraction handler
# ---------------------------------------------------------------------------


def _make_memory_extraction_job(token: str = "tok-cooldown") -> JobEntry:
    return JobEntry(
        id="job-cool",
        job_type=JobType.MEMORY_EXTRACTION,
        user_id="user-1",
        model_unique_id="conn-abc:llama3.2",
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


async def test_cancelled_error_shortens_inflight_slot_and_propagates(
    monkeypatch,
):
    """A CancelledError in the handler's main body must shorten the
    in-flight slot to the failure-cooldown TTL (not release it) and
    re-raise so the cancellation propagates to the consumer."""
    from backend.jobs import _dedup
    from backend.jobs._dedup import memory_extraction_slot_key
    from backend.jobs._registry import JOB_REGISTRY
    from backend.jobs.handlers import _memory_extraction
    from backend.jobs.handlers._memory_extraction import handle_memory_extraction

    assert hasattr(_dedup, "MEMORY_EXTRACTION_FAILURE_TTL_SECONDS")
    cooldown_ttl = _dedup.MEMORY_EXTRACTION_FAILURE_TTL_SECONDS
    assert cooldown_ttl == 600

    redis = _FakeRedis()
    # Pre-occupy the in-flight slot at the long safety-net TTL so we can
    # observe it being shortened.
    slot_key = memory_extraction_slot_key("user-1", "persona-1")
    redis.store[slot_key] = "1"
    redis.ttls[slot_key] = 1800

    job = _make_memory_extraction_job()
    config = JOB_REGISTRY[JobType.MEMORY_EXTRACTION]

    # Force the handler into the main try-body and then cancel it from
    # within. We patch a function that is awaited after the execution
    # token guard but before any external dependency — the published
    # "started" event.
    async def _raise_cancelled(*args, **kwargs):
        raise asyncio.CancelledError()

    bus = _CapturingBus()
    bus.publish = _raise_cancelled  # type: ignore[assignment]

    with pytest.raises(asyncio.CancelledError):
        await handle_memory_extraction(job, config, redis, bus)

    # Slot was neither released nor left at the long TTL — it was
    # shortened to the failure-cooldown TTL.
    assert slot_key not in redis.deleted
    assert (slot_key, cooldown_ttl) in redis.expire_calls


async def test_retryable_non_final_failure_shortens_inflight_slot():
    """In ``_on_extraction_failure``, a retryable failure that is not on
    the last attempt must shorten the in-flight slot to the failure-
    cooldown TTL (previously: left at full 30-min safety-net TTL)."""
    from backend.jobs import _dedup
    from backend.jobs._dedup import memory_extraction_slot_key
    from backend.jobs._models import JobConfig
    from backend.jobs.handlers._memory_extraction import _on_extraction_failure

    cooldown_ttl = _dedup.MEMORY_EXTRACTION_FAILURE_TTL_SECONDS

    redis = _FakeRedis()
    slot_key = memory_extraction_slot_key("user-1", "persona-1")
    redis.store[slot_key] = "1"
    redis.ttls[slot_key] = 1800

    job = _make_memory_extraction_job()
    # attempt=0 + max_retries=3 → not the last attempt → retryable branch.
    config = JobConfig(
        handler=AsyncMock(),
        max_retries=3,
        retry_delay_seconds=0.1,
        queue_timeout_seconds=3600.0,
        execution_timeout_seconds=60.0,
    )

    await _on_extraction_failure(
        exc=RuntimeError("transient"),
        job=job,
        config=config,
        redis=redis,
        event_bus=_CapturingBus(),
        persona_id="persona-1",
        session_id="sess-1",
        message_ids=["m1"],
        inflight_key=slot_key,
    )

    # Slot not released and not left at the long TTL.
    assert slot_key not in redis.deleted
    assert (slot_key, cooldown_ttl) in redis.expire_calls

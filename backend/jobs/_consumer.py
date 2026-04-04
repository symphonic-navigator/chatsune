import asyncio
import logging
from datetime import datetime, timezone, timedelta

from redis.asyncio import Redis

from backend.jobs._lock import get_user_lock
from backend.jobs._models import JobEntry
from backend.jobs._registry import JOB_REGISTRY
from backend.jobs._retry import set_retry, get_retry, clear_retry
from shared.events.jobs import (
    JobCompletedEvent, JobExpiredEvent, JobFailedEvent,
    JobRetryEvent, JobStartedEvent,
)
from shared.topics import Topics

_log = logging.getLogger(__name__)

_STREAM = "jobs:pending"
_GROUP = "workers"
_CONSUMER_NAME = "consumer-1"


async def ensure_consumer_group(redis: Redis) -> None:
    """Create the consumer group if it does not already exist."""
    try:
        await redis.xgroup_create(_STREAM, _GROUP, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" in str(exc):
            pass  # Group already exists
        else:
            raise


async def process_one(redis: Redis, event_bus) -> bool:
    """Read and process a single job from the stream.

    Returns True if a job was processed (success, failure, or expiry).
    Returns False if no job was available or the job was skipped (locked user).
    """
    # First check pending entries (retries, previously unacked)
    entries = await redis.xreadgroup(
        _GROUP, _CONSUMER_NAME, {_STREAM: "0"}, count=1,
    )

    if not entries or not entries[0][1]:
        # No pending — read new entries
        entries = await redis.xreadgroup(
            _GROUP, _CONSUMER_NAME, {_STREAM: ">"}, count=1, block=5000,
        )

    if not entries or not entries[0][1]:
        return False

    stream_id, fields = entries[0][1][0]
    job = JobEntry.model_validate_json(fields["data"])

    config = JOB_REGISTRY.get(job.job_type)
    if config is None:
        _log.error("Unknown job type: %s — acknowledging and discarding", job.job_type)
        await redis.xack(_STREAM, _GROUP, stream_id)
        return True

    now = datetime.now(timezone.utc)

    # Check queue timeout
    if (now - job.created_at).total_seconds() > config.queue_timeout_seconds:
        await event_bus.publish(
            Topics.JOB_EXPIRED,
            JobExpiredEvent(
                job_id=job.id,
                job_type=job.job_type,
                correlation_id=job.correlation_id,
                waited_seconds=(now - job.created_at).total_seconds(),
                timestamp=now,
            ),
            target_user_ids=[job.user_id],
            correlation_id=job.correlation_id,
        )
        await clear_retry(redis, job.id)
        await redis.xack(_STREAM, _GROUP, stream_id)
        return True

    # Check retry timing
    retry_state = await get_retry(redis, job.id)
    if retry_state and retry_state["next_retry_at"] > now:
        return False  # Not yet time — leave unacked

    # Update attempt from retry state if available
    if retry_state:
        job.attempt = retry_state["attempt"]

    # Check per-user lock (non-blocking)
    lock = get_user_lock(job.user_id)
    if lock.locked():
        return False  # User busy — leave unacked for next iteration

    # Execute the job
    try:
        async with asyncio.timeout(config.execution_timeout_seconds):
            async with lock:
                await event_bus.publish(
                    Topics.JOB_STARTED,
                    JobStartedEvent(
                        job_id=job.id,
                        job_type=job.job_type,
                        correlation_id=job.correlation_id,
                        timestamp=now,
                    ),
                    target_user_ids=[job.user_id],
                    correlation_id=job.correlation_id,
                )
                await config.handler(
                    job=job,
                    config=config,
                    redis=redis,
                    event_bus=event_bus,
                )

        # Success
        if config.notify:
            await event_bus.publish(
                Topics.JOB_COMPLETED,
                JobCompletedEvent(
                    job_id=job.id,
                    job_type=job.job_type,
                    correlation_id=job.correlation_id,
                    timestamp=datetime.now(timezone.utc),
                ),
                target_user_ids=[job.user_id],
                correlation_id=job.correlation_id,
            )
        await clear_retry(redis, job.id)
        await redis.xack(_STREAM, _GROUP, stream_id)
        return True

    except TimeoutError:
        error_message = f"Execution timed out after {config.execution_timeout_seconds}s"
    except Exception as exc:
        error_message = str(exc)

    # Retry / failure logic (shared between TimeoutError and Exception)
    attempt = job.attempt + 1
    now = datetime.now(timezone.utc)

    if attempt >= config.max_retries:
        # Final failure
        should_notify = config.notify or config.notify_error
        if should_notify:
            await event_bus.publish(
                Topics.JOB_FAILED,
                JobFailedEvent(
                    job_id=job.id,
                    job_type=job.job_type,
                    correlation_id=job.correlation_id,
                    attempt=attempt,
                    max_retries=config.max_retries,
                    error_message=error_message,
                    recoverable=False,
                    timestamp=now,
                ),
                target_user_ids=[job.user_id],
                correlation_id=job.correlation_id,
            )
        await clear_retry(redis, job.id)
        await redis.xack(_STREAM, _GROUP, stream_id)
        _log.warning("Job %s failed after %d attempts: %s", job.id, attempt, error_message)
        return True
    else:
        # Schedule retry
        next_retry_at = now + timedelta(seconds=config.retry_delay_seconds)
        await set_retry(redis, job.id, attempt=attempt, next_retry_at=next_retry_at)
        await event_bus.publish(
            Topics.JOB_RETRY,
            JobRetryEvent(
                job_id=job.id,
                job_type=job.job_type,
                correlation_id=job.correlation_id,
                attempt=attempt,
                next_retry_at=next_retry_at,
                timestamp=now,
            ),
            target_user_ids=[job.user_id],
            correlation_id=job.correlation_id,
        )
        _log.info("Job %s retry %d/%d scheduled at %s", job.id, attempt, config.max_retries, next_retry_at)
        return False


async def consumer_loop(redis: Redis, event_bus) -> None:
    """Main consumer loop — runs indefinitely as a background task."""
    await ensure_consumer_group(redis)
    _log.info("Job consumer started")

    while True:
        try:
            processed = await process_one(redis, event_bus)
            if not processed:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            _log.info("Job consumer shutting down")
            break
        except Exception:
            _log.exception("Unexpected error in job consumer loop")
            await asyncio.sleep(1)

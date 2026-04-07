import asyncio
import logging
from datetime import datetime, timezone, timedelta

from redis.asyncio import Redis

from backend.jobs._lock import get_job_lock
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


def _is_actionable(job: JobEntry, retry_state: dict | None) -> bool:
    """Return True if a pending job can be executed in this iteration.

    A pending entry is *not* actionable when its retry timer is still in
    the future, or when another background job for the same user is
    currently running. We must skip such entries instead of blocking on
    them, otherwise one stuck job halts the entire stream.
    """
    if retry_state and retry_state["next_retry_at"] > datetime.now(timezone.utc):
        return False
    if get_job_lock(job.user_id).locked():
        return False
    return True


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
    # First, scan pending entries (retries, previously unacked) for an
    # actionable one. We read a batch instead of count=1 because a single
    # stuck pending entry (locked user, retry timer in the future) must
    # not block the rest of the queue — we have to be able to step over
    # it and still pick up new work in the same iteration.
    pending = await redis.xreadgroup(
        _GROUP, _CONSUMER_NAME, {_STREAM: "0"}, count=32,
    )
    pending_entries = pending[0][1] if pending and pending[0][1] else []

    stream_id: str | None = None
    job: JobEntry | None = None
    for entry_id, fields in pending_entries:
        candidate = JobEntry.model_validate_json(fields["data"])
        retry_state = await get_retry(redis, candidate.id)
        if _is_actionable(candidate, retry_state):
            if retry_state:
                candidate.attempt = retry_state["attempt"]
            stream_id, job = entry_id, candidate
            break

    # No actionable pending entry — try to fetch a new one. If even that
    # is empty, we genuinely have nothing to do; block briefly so the
    # outer loop does not spin when the queue is fully drained.
    if job is None:
        new_entries = await redis.xreadgroup(
            _GROUP, _CONSUMER_NAME, {_STREAM: ">"}, count=1, block=5000,
        )
        if not new_entries or not new_entries[0][1]:
            return False
        stream_id, fields = new_entries[0][1][0]
        job = JobEntry.model_validate_json(fields["data"])

    config = JOB_REGISTRY.get(job.job_type)
    if config is None:
        _log.error("Unknown job type: %s — acknowledging and discarding", job.job_type)
        await redis.xack(_STREAM, _GROUP, stream_id)
        return True

    _log.info(
        "Picked up job %s (type=%s, model=%s, user=%s, attempt=%d)",
        job.id, job.job_type.value, job.model_unique_id, job.user_id, job.attempt,
    )

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

    # Retry timing and per-user lock were already checked in the
    # actionable scan above; we hold no flag for them here. The job-level
    # lock is taken below to serialise concurrent jobs for the same user.
    lock = get_job_lock(job.user_id)

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
        _log.error("Job %s timed out after %ds", job.id, config.execution_timeout_seconds)
    except Exception as exc:
        error_message = str(exc)
        _log.exception("Job %s raised an exception", job.id)

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
            # process_one already blocks up to 5s in xreadgroup when idle, so
            # there is no need for an additional sleep on the no-work path.
            await process_one(redis, event_bus)
        except asyncio.CancelledError:
            _log.info("Job consumer shutting down")
            break
        except Exception:
            _log.exception("Unexpected error in job consumer loop")
            await asyncio.sleep(1)

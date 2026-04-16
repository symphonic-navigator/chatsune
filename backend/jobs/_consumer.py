import asyncio
import uuid
import structlog
from datetime import datetime, timezone, timedelta

from redis.asyncio import Redis

from backend.jobs._errors import UnrecoverableJobError
from backend.jobs._lock import get_job_lock
from backend.jobs._log import append_job_log_entry
from backend.jobs._models import JobEntry
from backend.jobs._registry import JOB_REGISTRY
from backend.jobs._retry import set_retry, get_retry, clear_retry, compute_backoff
from shared.dtos.jobs import JobLogEntryDto, JobLogStatus
from backend.modules.safeguards import (
    BudgetExceededError,
    CircuitOpenError,
    EmergencyStoppedError,
    RateLimitExceededError,
    SafeguardConfig,
    acknowledge_job_done,
    check_job_preconditions,
    record_job_failure,
    record_job_success,
)
from shared.events.jobs import (
    JobCompletedEvent, JobExpiredEvent, JobFailedEvent,
    JobRetryEvent, JobStartedEvent,
)
from shared.topics import Topics

_log = structlog.get_logger("chatsune.jobs.consumer")

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


async def _log_job_transition(
    redis: Redis,
    *,
    user_id: str,
    job: JobEntry,
    status: JobLogStatus,
    silent: bool,
    ts: datetime,
    attempt: int = 0,
    duration_ms: int | None = None,
    error_message: str | None = None,
) -> None:
    entry = JobLogEntryDto(
        entry_id=str(uuid.uuid4()),
        job_id=job.id,
        job_type=job.job_type,
        persona_id=job.payload.get("persona_id"),
        status=status,
        attempt=attempt,
        silent=silent,
        ts=ts,
        duration_ms=duration_ms,
        error_message=error_message,
    )
    await append_job_log_entry(redis, user_id=user_id, entry=entry)


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
        # Zombie PEL entry: the stream entry was deleted (e.g. the whole
        # ``jobs:pending`` stream was manually flushed) but the consumer
        # group still has a dangling reference to this ID. XREADGROUP then
        # returns an empty fields dict. Ack it so it disappears from the
        # PEL and move on.
        if "data" not in fields:
            _log.warning("job.pel.zombie_dropped", entry_id=entry_id)
            await redis.xack(_STREAM, _GROUP, entry_id)
            continue
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
        _log.error("job.unknown_type", job_type=job.job_type, job_id=job.id)
        await redis.xack(_STREAM, _GROUP, stream_id)
        await redis.xdel(_STREAM, stream_id)
        return True

    _log.info(
        "job.received",
        job_id=job.id,
        job_type=job.job_type.value,
        model_unique_id=job.model_unique_id,
        user_id=job.user_id,
        attempt=job.attempt,
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
        await redis.xdel(_STREAM, stream_id)
        await acknowledge_job_done(redis, job.user_id, stream_id)
        return True

    # Retry timing and per-user lock were already checked in the
    # actionable scan above; we hold no flag for them here. The job-level
    # lock is taken below to serialise concurrent jobs for the same user.
    lock = get_job_lock(job.user_id)

    # Re-read safeguard config per job so env-driven toggles (kill-switch)
    # take effect without a restart.
    sg_config = SafeguardConfig.from_env()
    connection_slug, _, model_slug = job.model_unique_id.partition(":")

    # Bind job context so all log lines within this execution block carry
    # job_id, job_type, and attempt automatically.
    structlog.contextvars.bind_contextvars(
        job_id=job.id,
        job_type=job.job_type.value,
        attempt=job.attempt,
    )
    execution_started_at: datetime | None = None
    try:
        # Execute the job
        try:
            try:
                await check_job_preconditions(
                    redis,
                    sg_config,
                    user_id=job.user_id,
                    connection_id=connection_slug,
                    model_slug=model_slug,
                    # TODO(Task 17): pass real estimated tokens
                    estimated_input_tokens=0,
                )
            except (
                EmergencyStoppedError,
                RateLimitExceededError,
                BudgetExceededError,
                CircuitOpenError,
            ) as exc:
                raise UnrecoverableJobError(str(exc)) from exc

            async with asyncio.timeout(config.execution_timeout_seconds):
                async with lock:
                    execution_started_at = datetime.now(timezone.utc)
                    await event_bus.publish(
                        Topics.JOB_STARTED,
                        JobStartedEvent(
                            job_id=job.id,
                            job_type=job.job_type,
                            correlation_id=job.correlation_id,
                            timestamp=now,
                            notify=config.notify,
                            persona_id=job.payload.get("persona_id"),
                        ),
                        target_user_ids=[job.user_id],
                        correlation_id=job.correlation_id,
                    )
                    await _log_job_transition(
                        redis,
                        user_id=job.user_id,
                        job=job,
                        status="started",
                        silent=not config.notify,
                        ts=execution_started_at,
                    )
                    try:
                        await config.handler(
                            job=job,
                            config=config,
                            redis=redis,
                            event_bus=event_bus,
                        )
                    except Exception:
                        await record_job_failure(
                            redis,
                            sg_config,
                            user_id=job.user_id,
                            connection_id=connection_slug,
                            model_slug=model_slug,
                        )
                        raise
                    else:
                        await record_job_success(
                            redis,
                            sg_config,
                            user_id=job.user_id,
                            connection_id=connection_slug,
                            model_slug=model_slug,
                            # TODO(Task 17): pass real tokens spent
                            tokens_spent=0,
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
            completed_at = datetime.now(timezone.utc)
            duration_ms = (
                int((completed_at - execution_started_at).total_seconds() * 1000)
                if execution_started_at is not None
                else None
            )
            await _log_job_transition(
                redis,
                user_id=job.user_id,
                job=job,
                status="completed",
                silent=not config.notify,
                ts=completed_at,
                duration_ms=duration_ms,
            )
            await clear_retry(redis, job.id)
            await redis.xack(_STREAM, _GROUP, stream_id)
            await redis.xdel(_STREAM, stream_id)
            await acknowledge_job_done(redis, job.user_id, stream_id)
            return True

        except TimeoutError:
            error_message = f"Execution timed out after {config.execution_timeout_seconds}s"
            unrecoverable = False
            _log.error("job.timeout", timeout_seconds=config.execution_timeout_seconds)
            await record_job_failure(
                redis,
                sg_config,
                user_id=job.user_id,
                connection_id=connection_slug,
                model_slug=model_slug,
            )
        except UnrecoverableJobError as exc:
            error_message = str(exc)
            unrecoverable = True
            _log.warning("job.failed.unrecoverable", error=error_message)
        except Exception as exc:
            error_message = str(exc)
            unrecoverable = False
            _log.exception("job.exception")

        # Retry / failure logic (shared between TimeoutError and Exception)
        attempt = job.attempt + 1
        now = datetime.now(timezone.utc)

        if unrecoverable or attempt >= config.max_retries:
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
            failed_at = datetime.now(timezone.utc)
            failure_duration_ms = (
                int((failed_at - execution_started_at).total_seconds() * 1000)
                if execution_started_at is not None
                else None
            )
            await _log_job_transition(
                redis,
                user_id=job.user_id,
                job=job,
                status="failed",
                silent=not (config.notify or config.notify_error),
                ts=failed_at,
                attempt=attempt,
                duration_ms=failure_duration_ms,
                error_message=error_message,
            )
            await clear_retry(redis, job.id)
            await redis.xack(_STREAM, _GROUP, stream_id)
            await redis.xdel(_STREAM, stream_id)
            await acknowledge_job_done(redis, job.user_id, stream_id)
            _log.warning("job.failed.final", attempt=attempt, error=error_message)
            return True
        else:
            # Schedule retry
            delay_seconds = compute_backoff(
                attempt, base=config.retry_delay_seconds, cap=300,
            )
            next_retry_at = now + timedelta(seconds=delay_seconds)
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
                    notify=config.notify,
                ),
                target_user_ids=[job.user_id],
                correlation_id=job.correlation_id,
            )
            await _log_job_transition(
                redis,
                user_id=job.user_id,
                job=job,
                status="retry",
                silent=not config.notify,
                ts=now,
                attempt=attempt,
                error_message=error_message,
            )
            _log.info("job.retry.scheduled", attempt=attempt, max_retries=config.max_retries, next_retry_at=next_retry_at.isoformat())
            return False
    finally:
        structlog.contextvars.clear_contextvars()


async def consumer_loop(redis: Redis, event_bus) -> None:
    """Main consumer loop — runs indefinitely as a background task."""
    await ensure_consumer_group(redis)
    _log.info("job.consumer.started")

    while True:
        try:
            # process_one already blocks up to 5s in xreadgroup when idle, so
            # there is no need for an additional sleep on the no-work path.
            await process_one(redis, event_bus)
        except asyncio.CancelledError:
            _log.info("job.consumer.shutdown")
            break
        except Exception:
            _log.exception("job.consumer.loop_error")
            await asyncio.sleep(1)

"""Job handler — memory extraction from conversation messages.

Extracts facts, preferences, and corrections from user messages and
creates journal entries in the memory module.

The actual extraction pipeline (prompt build → LLM stream → parse →
dedup → persist + per-entry events + 50-cap enforcement + Redis tracking
reset) lives in :func:`backend.modules.memory.extract_and_store_messages`
so the ChatGPT-import batch handler can reuse it. This handler keeps the
job-system housekeeping: execution-token dedup, in-flight slot, lifecycle
events (started / completed / failed / skipped), and terminal-failure
semantics.
"""

import asyncio
import structlog
from datetime import UTC, datetime

from backend.jobs._dedup import (
    MEMORY_EXTRACTION_FAILURE_TTL_SECONDS,
    memory_extraction_slot_key,
    release_inflight_slot,
)
from backend.jobs._errors import ProviderUnavailableError, UnrecoverableJobError
from backend.jobs._models import JobConfig, JobEntry
from shared.events.memory import (
    MemoryExtractionCompletedEvent,
    MemoryExtractionFailedEvent,
    MemoryExtractionSkippedEvent,
    MemoryExtractionStartedEvent,
)
from shared.topics import Topics

_log = structlog.get_logger(__name__)


async def handle_memory_extraction(
    job: JobEntry,
    config: JobConfig,
    redis,
    event_bus,
) -> None:
    """Extract memorable facts from conversation messages into journal entries."""
    # Deferred imports to avoid circular dependency.
    from backend.database import get_db
    from backend.modules.memory import extract_and_store_messages

    token_key = f"job:executed:{job.execution_token}"
    already = await redis.set(token_key, "1", nx=True, ex=48 * 3600)
    if already is None:
        _log.info(
            "job.duplicate_skip token=%s job_id=%s", job.execution_token, job.id,
        )
        return

    persona_id = job.payload["persona_id"]
    session_id = job.payload["session_id"]
    messages_raw: list[str] = job.payload.get("messages", [])
    message_ids: list[str] = job.payload.get("message_ids", [])

    _log.info(
        "Starting memory extraction: persona=%s session=%s msg_count=%d msg_ids=%s model_unique_id=%s",
        persona_id, session_id, len(messages_raw), message_ids, job.model_unique_id,
    )

    # Compute the in-flight key up front so the finally block can release
    # it no matter where the handler fails — including before the first
    # event publish below.
    inflight_key = memory_extraction_slot_key(job.user_id, persona_id)
    success = False
    try:
        # Publish started event.
        await event_bus.publish(
            Topics.MEMORY_EXTRACTION_STARTED,
            MemoryExtractionStartedEvent(
                persona_id=persona_id,
                correlation_id=job.correlation_id,
                timestamp=datetime.now(UTC),
            ),
            scope=f"persona:{persona_id}",
            target_user_ids=[job.user_id],
            correlation_id=job.correlation_id,
        )

        # Delegate the actual extraction pipeline to the reusable core.
        # Errors propagate so the except blocks below handle them — the
        # function itself raises ProviderUnavailableError for genuinely
        # unreachable providers and RuntimeError for other stream errors.
        result = await extract_and_store_messages(
            user_id=job.user_id,
            persona_id=persona_id,
            session_id=session_id,
            model_unique_id=job.model_unique_id,
            messages=messages_raw,
            message_ids=message_ids,
            correlation_id=job.correlation_id,
            redis=redis,
            db=get_db(),
            event_bus=event_bus,
            skip_budget_reserve=False,
        )

        # Publish completed event. This fires for both the "no extractable
        # content after filtering" short-circuit (entries_created=0) and
        # the regular path, matching the previous behaviour.
        await event_bus.publish(
            Topics.MEMORY_EXTRACTION_COMPLETED,
            MemoryExtractionCompletedEvent(
                persona_id=persona_id,
                entries_created=result.entries_created,
                correlation_id=job.correlation_id,
                timestamp=datetime.now(UTC),
            ),
            scope=f"persona:{persona_id}",
            target_user_ids=[job.user_id],
            correlation_id=job.correlation_id,
        )

        _log.info(
            "Extraction completed: persona=%s session=%s entries_created=%d source_msgs=%d",
            persona_id, session_id, result.entries_created, len(messages_raw),
        )
        success = True

    except asyncio.CancelledError:
        # The consumer's execution-timeout (asyncio.timeout) aborts the
        # handler by raising CancelledError at the current await. That
        # does not derive from Exception, so the broader handler below
        # would not see it — and without special handling the in-flight
        # slot would stay held at the full 30-minute safety-net TTL,
        # blocking any retry or fresh submission for the persona.
        # Shorten the slot to the failure cooldown, then let the
        # cancellation propagate so the consumer can record the failure
        # and schedule a retry.
        try:
            await redis.expire(
                inflight_key, MEMORY_EXTRACTION_FAILURE_TTL_SECONDS,
            )
        except Exception:
            _log.exception(
                "job.extraction.cooldown_refresh_failed", key=inflight_key,
            )
        _log.info(
            "job.extraction.cancellation_cooldown",
            persona_id=persona_id,
            cooldown_seconds=MEMORY_EXTRACTION_FAILURE_TTL_SECONDS,
        )
        raise
    except Exception as exc:
        _log.error(
            "Memory extraction failed for persona %s, session %s: %s",
            persona_id, session_id, exc,
        )
        await event_bus.publish(
            Topics.MEMORY_EXTRACTION_FAILED,
            MemoryExtractionFailedEvent(
                persona_id=persona_id,
                error_message=str(exc),
                correlation_id=job.correlation_id,
                timestamp=datetime.now(UTC),
            ),
            scope=f"persona:{persona_id}",
            target_user_ids=[job.user_id],
            correlation_id=job.correlation_id,
        )
        await _on_extraction_failure(
            exc=exc,
            job=job,
            config=config,
            redis=redis,
            event_bus=event_bus,
            persona_id=persona_id,
            session_id=session_id,
            message_ids=message_ids,
            inflight_key=inflight_key,
        )
        raise
    finally:
        if success:
            await release_inflight_slot(redis, inflight_key)


# Cooldown applied to the in-flight slot when the upstream provider is
# definitively down. Kept deliberately short — the provider usually
# recovers within minutes, and a longer window would strand the user's
# memory extraction for no reason.
_UPSTREAM_COOLDOWN_SECONDS = 900  # 15 minutes


async def _on_extraction_failure(
    *,
    exc: Exception,
    job: JobEntry,
    config: JobConfig,
    redis,
    event_bus,
    persona_id: str,
    session_id: str,
    message_ids: list[str],
    inflight_key: str,
) -> None:
    """Apply the correct terminal-failure semantics.

    Three cases:

    - **Provider unavailable** (``ProviderUnavailableError``): the job
      is terminal, but retrying *later* will work. Refresh the inflight
      slot to a short cooldown TTL and leave it held so fresh
      submissions are skipped during the cooldown window. Do NOT mark
      the source messages — they should be picked up again once the
      provider is back.

    - **Other unrecoverable / last retry attempt exhausted**: the job
      is terminal and replaying the same input would fail again. Mark
      the source messages as ``extracted`` so they stop looping through
      the queue, release the inflight slot, and emit a skipped event so
      the UI can surface a banner.

    - **Retryable exception, not yet on last attempt**: leave the slot
      held (the TTL safety net covers the whole retry chain) and do
      nothing else — the consumer will retry, and a later attempt will
      either succeed (release on success path) or hit the terminal
      branch above.
    """
    if isinstance(exc, ProviderUnavailableError):
        try:
            await redis.expire(inflight_key, _UPSTREAM_COOLDOWN_SECONDS)
        except Exception:
            _log.exception("job.extraction.cooldown_refresh_failed", key=inflight_key)
        _log.info(
            "job.extraction.provider_cooldown",
            persona_id=persona_id,
            cooldown_seconds=_UPSTREAM_COOLDOWN_SECONDS,
        )
        return

    is_unrecoverable = isinstance(exc, UnrecoverableJobError)
    is_last_attempt = (job.attempt + 1) >= config.max_retries
    is_terminal = is_unrecoverable or is_last_attempt
    if not is_terminal:
        # Non-final retryable failure — consumer will retry this job.
        # Shorten the slot's TTL to the failure cooldown rather than
        # leaving it at the full 30-minute safety-net TTL. That way a
        # truly abandoned job (e.g. the handler crashed in a way that
        # prevents the consumer from retrying) frees the scope after
        # 10 minutes instead of half an hour, but there is still plenty
        # of headroom for the normal retry chain to run to completion.
        try:
            await redis.expire(
                inflight_key, MEMORY_EXTRACTION_FAILURE_TTL_SECONDS,
            )
        except Exception:
            _log.exception(
                "job.extraction.cooldown_refresh_failed", key=inflight_key,
            )
        return

    # Terminal non-provider failure: mark source messages as extracted
    # so they stop being re-submitted, publish a user-visible skipped
    # event, and release the slot so the next trigger can proceed.
    reason = str(exc) or type(exc).__name__
    _log.warning(
        "job.extraction.terminal_failure",
        persona_id=persona_id,
        session_id=session_id,
        message_count=len(message_ids),
        reason=reason,
    )

    if message_ids:
        try:
            from backend.modules.chat import mark_messages_extracted
            await mark_messages_extracted(message_ids)
        except Exception:
            _log.exception(
                "job.extraction.mark_extracted_failed",
                persona_id=persona_id,
                message_ids=message_ids,
            )

    # Reset the per-scope tracking counter so the fallback loop does
    # not immediately re-submit another extraction for the same scope.
    try:
        tracking_key = f"memory:extraction:{job.user_id}:{persona_id}"
        await redis.hset(tracking_key, mapping={
            "last_extraction_at": datetime.now(UTC).isoformat(),
            "messages_since_extraction": "0",
        })
    except Exception:
        _log.exception(
            "job.extraction.tracking_reset_failed", persona_id=persona_id,
        )

    try:
        await event_bus.publish(
            Topics.MEMORY_EXTRACTION_SKIPPED,
            MemoryExtractionSkippedEvent(
                persona_id=persona_id,
                skipped_message_count=len(message_ids),
                reason=reason,
                user_message=(
                    "Memory extraction failed and has been skipped for "
                    f"{len(message_ids)} message(s). You can trigger a "
                    "manual extraction from the persona menu if you "
                    "want to try again."
                ),
                correlation_id=job.correlation_id,
                timestamp=datetime.now(UTC),
            ),
            scope=f"persona:{persona_id}",
            target_user_ids=[job.user_id],
            correlation_id=job.correlation_id,
        )
    except Exception:
        _log.exception(
            "job.extraction.skipped_event_failed", persona_id=persona_id,
        )

    await release_inflight_slot(redis, inflight_key)

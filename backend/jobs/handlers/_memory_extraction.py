"""Job handler — memory extraction from conversation messages.

Extracts facts, preferences, and corrections from user messages and
creates journal entries in the memory module.
"""

import structlog
from datetime import UTC, datetime

from backend.jobs._dedup import (
    memory_extraction_slot_key,
    release_inflight_slot,
)
from backend.jobs._errors import ProviderUnavailableError, UnrecoverableJobError
from backend.jobs._models import JobConfig, JobEntry
from backend.jobs.handlers._budget_helpers import (
    check_and_reserve_budget,
    record_handler_tokens,
)
from backend.modules.llm import ContentDelta, StreamDone, StreamError
from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart
from shared.events.memory import (
    MemoryEntriesDiscardedEvent,
    MemoryEntryCreatedEvent,
    MemoryExtractionCompletedEvent,
    MemoryExtractionFailedEvent,
    MemoryExtractionSkippedEvent,
    MemoryExtractionStartedEvent,
)
from shared.dtos.memory import JournalEntryDto
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
    from backend.modules.llm import stream_completion as llm_stream_completion
    from backend.modules.llm import get_model_supports_reasoning
    from backend.modules.memory._extraction import (
        build_extraction_prompt,
        strip_technical_content,
    )
    from backend.modules.memory._parser import parse_extraction_output
    from backend.modules.memory._repository import MemoryRepository

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
    _, model_slug = job.model_unique_id.split(":", 1)

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
        # Filter technical content from messages.
        filtered = [strip_technical_content(m) for m in messages_raw]
        filtered = [m for m in filtered if m.strip()]

        if not filtered:
            _log.info(
                "No extractable content after filtering for persona %s, session %s",
                persona_id, session_id,
            )
            # Mark the source messages as extracted and reset the Redis
            # tracking counter. Without this, the same non-extractable
            # messages (e.g. pure code blocks) would be picked up by the
            # periodic fallback loop forever and re-submitted every cycle.
            if message_ids:
                from backend.modules.chat import mark_messages_extracted
                await mark_messages_extracted(message_ids)
            tracking_key = f"memory:extraction:{job.user_id}:{persona_id}"
            await redis.hset(tracking_key, mapping={
                "last_extraction_at": datetime.now(UTC).isoformat(),
                "messages_since_extraction": "0",
            })
            await event_bus.publish(
                Topics.MEMORY_EXTRACTION_COMPLETED,
                MemoryExtractionCompletedEvent(
                    persona_id=persona_id,
                    entries_created=0,
                    correlation_id=job.correlation_id,
                    timestamp=datetime.now(UTC),
                ),
                scope=f"persona:{persona_id}",
                target_user_ids=[job.user_id],
                correlation_id=job.correlation_id,
            )
            success = True
            return

        db = get_db()
        repo = MemoryRepository(db)

        # Load existing memory body and journal entries for context.
        body_doc = await repo.get_current_memory_body(job.user_id, persona_id)
        memory_body = body_doc["content"] if body_doc else None

        existing_entries = await repo.list_journal_entries(
            job.user_id, persona_id,
        )
        journal_contents = [e["content"] for e in existing_entries]

        # Build extraction prompt.
        system_prompt = build_extraction_prompt(
            memory_body=memory_body,
            journal_entries=journal_contents,
            messages=filtered,
        )

        supports_reasoning = await get_model_supports_reasoning(
            job.user_id, job.model_unique_id,
        )

        request = CompletionRequest(
            model=model_slug,
            messages=[
                CompletionMessage(
                    role="user",
                    content=[ContentPart(type="text", text=system_prompt)],
                ),
            ],
            temperature=0.3,
            reasoning_enabled=False,
            supports_reasoning=supports_reasoning,
        )

        # Reserve daily-budget headroom before spending tokens.
        await check_and_reserve_budget(redis, job.user_id, system_prompt)

        # Stream LLM response.
        full_content = ""
        stream_input_tokens: int | None = None
        stream_output_tokens: int | None = None
        async for event in llm_stream_completion(
            job.user_id,
            job.model_unique_id,
            request,
            source="job:memory_extraction",
        ):
            match event:
                case ContentDelta(delta=delta):
                    full_content += delta
                case StreamDone(input_tokens=in_tok, output_tokens=out_tok):
                    stream_input_tokens = in_tok
                    stream_output_tokens = out_tok
                    _log.debug(
                        "Extraction stream completed for persona %s, session %s",
                        persona_id, session_id,
                    )
                    break
                case StreamError() as err:
                    _log.error(
                        "Extraction stream error for persona %s: %s — %s",
                        persona_id, err.error_code, err.message,
                    )
                    # A genuinely unreachable provider (local Ollama daemon
                    # not running → TCP connect refused) cannot be fixed by
                    # retrying — surface that to the consumer so it skips
                    # the retry chain instead of tying up a job slot for
                    # the full max_retries * (exec + delay) window.
                    if err.error_code == "provider_unavailable":
                        raise ProviderUnavailableError(
                            f"Provider unavailable: {err.message}"
                        )
                    raise RuntimeError(
                        f"Memory extraction failed: {err.error_code} — {err.message}"
                    )

        await record_handler_tokens(
            redis,
            job.user_id,
            system_prompt,
            full_content,
            input_tokens=stream_input_tokens,
            output_tokens=stream_output_tokens,
        )

        # Parse extraction output.
        parsed_entries = parse_extraction_output(full_content)
        _log.info(
            "Parsed %d entries from extraction for persona %s, session %s",
            len(parsed_entries), persona_id, session_id,
        )

        # Deduplicate against existing journal entries and memory body.
        # Normalise for comparison: lowercase, strip, collapse whitespace.
        def _normalise(text: str) -> str:
            return " ".join(text.lower().split())

        existing_normalised = {_normalise(c) for c in journal_contents}
        if memory_body:
            memory_lower = memory_body.lower()
        else:
            memory_lower = ""

        deduped_entries = []
        for entry_data in parsed_entries:
            norm = _normalise(entry_data["content"])
            if norm in existing_normalised:
                _log.debug(
                    "Skipping duplicate journal entry: %s", entry_data["content"],
                )
                continue
            # Also skip if the memory body already contains this fact verbatim.
            if memory_lower and norm in memory_lower:
                _log.debug(
                    "Skipping entry already in memory body: %s", entry_data["content"],
                )
                continue
            existing_normalised.add(norm)
            deduped_entries.append(entry_data)

        _log.info(
            "After dedup: %d entries remaining (was %d) for persona %s",
            len(deduped_entries), len(parsed_entries), persona_id,
        )

        # Create journal entries and mark the source messages as extracted in
        # a single MongoDB transaction so the two writes are atomic: either
        # both land or neither does. Events are collected in-memory and only
        # published after the transaction commits — a failed commit must not
        # leak entry-created events to the frontend.
        from backend.database import get_client
        mongo_client = get_client()

        pending_events: list[tuple[str, MemoryEntryCreatedEvent]] = []
        async with await mongo_client.start_session() as mongo_session:
            async with mongo_session.start_transaction():
                for entry_data in deduped_entries:
                    entry_id = await repo.create_journal_entry(
                        user_id=job.user_id,
                        persona_id=persona_id,
                        content=entry_data["content"],
                        category=entry_data["category"],
                        source_session_id=session_id,
                        is_correction=entry_data["is_correction"],
                        session=mongo_session,
                    )
                    now = datetime.now(UTC)
                    pending_events.append((
                        entry_id,
                        MemoryEntryCreatedEvent(
                            entry=JournalEntryDto(
                                id=entry_id,
                                persona_id=persona_id,
                                content=entry_data["content"],
                                category=entry_data["category"],
                                state="uncommitted",
                                is_correction=entry_data["is_correction"],
                                created_at=now,
                            ),
                            correlation_id=job.correlation_id,
                            timestamp=now,
                        ),
                    ))
                if message_ids:
                    from backend.modules.chat import mark_messages_extracted
                    await mark_messages_extracted(
                        message_ids, session=mongo_session,
                    )

        # Transaction committed — now it is safe to publish and announce.
        entries_created = 0
        for _entry_id, ev in pending_events:
            await event_bus.publish(
                Topics.MEMORY_ENTRY_CREATED,
                ev,
                scope=f"persona:{persona_id}",
                target_user_ids=[job.user_id],
                correlation_id=job.correlation_id,
            )
            entries_created += 1

        if message_ids:
            _log.info(
                "Marked %d messages as extracted: persona=%s session=%s ids=%s",
                len(message_ids), persona_id, session_id, message_ids,
            )

        # Enforce 50-entry cap on uncommitted entries.
        discarded = await repo.discard_oldest_uncommitted(
            job.user_id, persona_id, max_count=50,
        )
        if discarded > 0:
            _log.info(
                "Discarded %d oldest uncommitted entries for persona %s (cap enforcement)",
                discarded, persona_id,
            )
            await event_bus.publish(
                Topics.MEMORY_ENTRIES_DISCARDED,
                MemoryEntriesDiscardedEvent(
                    persona_id=persona_id,
                    discarded_count=discarded,
                    user_message=(
                        f"{discarded} oldest journal entries for this persona were "
                        "discarded to stay within the 50-entry limit. "
                        "Please review your uncommitted entries."
                    ),
                    correlation_id=job.correlation_id,
                    timestamp=datetime.now(UTC),
                ),
                scope=f"persona:{persona_id}",
                target_user_ids=[job.user_id],
                correlation_id=job.correlation_id,
            )

        # Source messages were marked as extracted inside the transaction
        # above, so nothing further is needed here.

        # Update Redis tracking state.
        tracking_key = f"memory:extraction:{job.user_id}:{persona_id}"
        await redis.hset(tracking_key, mapping={
            "last_extraction_at": datetime.now(UTC).isoformat(),
            "messages_since_extraction": "0",
        })

        # Publish completed event.
        await event_bus.publish(
            Topics.MEMORY_EXTRACTION_COMPLETED,
            MemoryExtractionCompletedEvent(
                persona_id=persona_id,
                entries_created=entries_created,
                correlation_id=job.correlation_id,
                timestamp=datetime.now(UTC),
            ),
            scope=f"persona:{persona_id}",
            target_user_ids=[job.user_id],
            correlation_id=job.correlation_id,
        )

        _log.info(
            "Extraction completed: persona=%s session=%s entries_created=%d discarded=%d source_msgs=%d",
            persona_id, session_id, entries_created, discarded, len(messages_raw),
        )
        success = True

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
        # Leave the slot held; the safety-net TTL covers the whole
        # retry chain (see JOB_REGISTRY memory_extraction config).
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

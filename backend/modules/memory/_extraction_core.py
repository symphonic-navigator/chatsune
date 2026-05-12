"""Reusable memory-extraction core.

This module owns the pure extraction pipeline: build the prompt from
existing memory + journal context, stream the LLM, parse the output,
deduplicate against existing entries, and persist the new journal
entries together with the ``messages_extracted`` flip in a single
MongoDB transaction. The per-entry ``MemoryEntryCreated`` events plus
the 50-entry cap enforcement and Redis tracking-counter reset belong to
the extraction itself and are also emitted here.

The function is deliberately decoupled from the job-system wrapper that
calls it. Job-system concerns — in-flight slot acquire/release,
execution-token dedup, retry semantics, terminal-failure handling, and
the ``started`` / ``completed`` / ``failed`` / ``skipped`` lifecycle
events — remain in the calling handler. This keeps the function reusable
from both the live job handler and the upcoming ChatGPT-import batch
handler (Phase 2).

Failure model:

* ``ProviderUnavailableError`` is re-raised unchanged so the caller can
  apply a provider cooldown instead of consuming a retry attempt.
* Any other stream error becomes a ``RuntimeError`` — same as today.
* Exceptions propagate out of the Mongo transaction unchanged, which
  rolls back both the journal inserts and the ``mark_messages_extracted``
  update. The source messages stay un-extracted so they will be picked
  up by a later run.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import structlog

from backend.jobs._errors import ProviderUnavailableError
from backend.jobs.handlers._budget_helpers import (
    check_and_reserve_budget,
    record_handler_tokens,
)
from backend.modules.llm import (
    ContentDelta,
    StreamDone,
    StreamError,
)
from backend.modules.memory._extraction import (
    build_extraction_prompt,
    strip_technical_content,
)
from backend.modules.memory._parser import parse_extraction_output
from backend.modules.memory._repository import MemoryRepository
from backend.modules.settings import get_admin_system_message
from shared.dtos.chat import ChatSessionExtras
from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart
from shared.dtos.llm import ReasoningCapability, ToolCapability
from shared.dtos.memory import JournalEntryDto
from shared.events.memory import (
    MemoryEntriesDiscardedEvent,
    MemoryEntryCreatedEvent,
)
from shared.topics import Topics

_log = structlog.get_logger(__name__)


@dataclass
class ExtractionResult:
    """Outcome of one extraction run.

    ``entries_created`` is the number of new journal entries actually
    persisted after dedup. ``messages_processed`` is the count of source
    messages handed in (used by the caller to drive UI counters). The
    token fields mirror what the LLM stream reported in ``StreamDone``
    and are ``None`` for short-circuit paths that never called the LLM.
    """

    entries_created: int
    messages_processed: int
    input_tokens: int | None
    output_tokens: int | None


async def extract_and_store_messages(
    *,
    user_id: str,
    persona_id: str,
    session_id: str,
    model_unique_id: str,
    messages: list[str],
    message_ids: list[str],
    correlation_id: str,
    redis,
    db,
    event_bus,
    skip_budget_reserve: bool = False,
) -> ExtractionResult:
    """Extract memorable facts from *messages* and persist them.

    See module docstring for the failure model and the split with the
    calling job-system wrapper. ``skip_budget_reserve=True`` is used by
    the ChatGPT-import batch handler (Phase 2): the importer has its
    own ``force_budget`` toggle, and we must not let the live-flow
    budget check silently veto the batch. Token recording stays active
    in both modes so the daily-usage logging is honest.
    """
    # Deferred chat-module import to avoid a top-level cycle: the chat
    # module pulls in the memory module via its assemble-context path.
    from backend.modules.chat import mark_messages_extracted

    # Deferred import for the LLM stream entry-point: same shape as the
    # rest of the codebase to keep import order stable across restarts.
    from backend.modules.llm import stream_completion as llm_stream_completion
    from backend.modules.llm import get_model_supports_reasoning

    _, model_slug = model_unique_id.split(":", 1)

    # Filter technical content from messages.
    filtered = [strip_technical_content(m) for m in messages]
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
            await mark_messages_extracted(message_ids)
        tracking_key = f"memory:extraction:{user_id}:{persona_id}"
        await redis.hset(tracking_key, mapping={
            "last_extraction_at": datetime.now(UTC).isoformat(),
            "messages_since_extraction": "0",
        })
        return ExtractionResult(
            entries_created=0,
            messages_processed=len(message_ids),
            input_tokens=None,
            output_tokens=None,
        )

    repo = MemoryRepository(db)

    # Load existing memory body and journal entries for context.
    body_doc = await repo.get_current_memory_body(user_id, persona_id)
    memory_body = body_doc["content"] if body_doc else None

    existing_entries = await repo.list_journal_entries(user_id, persona_id)
    journal_contents = [e["content"] for e in existing_entries]

    # Build extraction prompt.
    system_prompt = build_extraction_prompt(
        memory_body=memory_body,
        journal_entries=journal_contents,
        messages=filtered,
    )

    supports_reasoning = await get_model_supports_reasoning(
        user_id, model_unique_id,
    )
    # supports_reasoning is logged for parity with the old code path but
    # the extraction request does not toggle reasoning on — we leave the
    # mode "off" / "optional" as before so the parser remains in charge.
    _log.debug(
        "extraction.model_caps",
        model_unique_id=model_unique_id,
        supports_reasoning=supports_reasoning,
    )

    # Inject the admin master prompt as a leading system-role message
    # when one is configured. Mirrors the chat prompt assembler so that
    # admin-set guardrail-loosening directives apply here as well.
    admin = await get_admin_system_message()
    prefix_messages = [admin.message] if admin else []
    admin_text = (admin.raw_text + "\n") if admin else ""

    request = CompletionRequest(
        model=model_slug,
        messages=prefix_messages + [
            CompletionMessage(
                role="user",
                content=[ContentPart(type="text", text=system_prompt)],
            ),
        ],
        temperature=0.3,
        reasoning=ReasoningCapability(kind="optional"),
        tools_capability=ToolCapability(supported=False),
        extras=ChatSessionExtras(
            tools_enabled=False,
            reasoning_mode="off",
            reasoning_effort=None,
        ),
    )

    # Reserve daily-budget headroom before spending tokens — unless the
    # caller (batch importer) has explicitly opted out.
    if not skip_budget_reserve:
        await check_and_reserve_budget(
            redis, user_id, admin_text + system_prompt,
        )

    # Stream LLM response.
    full_content = ""
    stream_input_tokens: int | None = None
    stream_output_tokens: int | None = None
    async for event in llm_stream_completion(
        user_id,
        model_unique_id,
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

    # Record real token spend regardless of the budget-reserve toggle —
    # the daily usage log stays honest even when the import flow chose
    # to bypass the gate.
    await record_handler_tokens(
        redis,
        user_id,
        admin_text + system_prompt,
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

    deduped_entries: list[dict] = []
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
    mongo_client = db.client

    pending_events: list[tuple[str, MemoryEntryCreatedEvent]] = []
    async with await mongo_client.start_session() as mongo_session:
        async with mongo_session.start_transaction():
            for entry_data in deduped_entries:
                entry_id = await repo.create_journal_entry(
                    user_id=user_id,
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
                        correlation_id=correlation_id,
                        timestamp=now,
                    ),
                ))
            if message_ids:
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
            target_user_ids=[user_id],
            correlation_id=correlation_id,
        )
        entries_created += 1

    if message_ids:
        _log.info(
            "Marked %d messages as extracted: persona=%s session=%s ids=%s",
            len(message_ids), persona_id, session_id, message_ids,
        )

    # Enforce 50-entry cap on uncommitted entries.
    discarded = await repo.discard_oldest_uncommitted(
        user_id, persona_id, max_count=50,
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
                correlation_id=correlation_id,
                timestamp=datetime.now(UTC),
            ),
            scope=f"persona:{persona_id}",
            target_user_ids=[user_id],
            correlation_id=correlation_id,
        )

    # Update Redis tracking state.
    tracking_key = f"memory:extraction:{user_id}:{persona_id}"
    await redis.hset(tracking_key, mapping={
        "last_extraction_at": datetime.now(UTC).isoformat(),
        "messages_since_extraction": "0",
    })

    return ExtractionResult(
        entries_created=entries_created,
        messages_processed=len(message_ids),
        input_tokens=stream_input_tokens,
        output_tokens=stream_output_tokens,
    )

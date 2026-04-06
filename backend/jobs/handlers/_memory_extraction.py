"""Job handler — memory extraction from conversation messages.

Extracts facts, preferences, and corrections from user messages and
creates journal entries in the memory module.
"""

import logging
from datetime import UTC, datetime

from backend.jobs._models import JobConfig, JobEntry
from backend.modules.llm import ContentDelta, StreamDone, StreamError
from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart
from shared.events.memory import (
    MemoryEntryCreatedEvent,
    MemoryExtractionCompletedEvent,
    MemoryExtractionFailedEvent,
    MemoryExtractionStartedEvent,
)
from shared.dtos.memory import JournalEntryDto
from shared.topics import Topics

_log = logging.getLogger(__name__)


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

    persona_id = job.payload["persona_id"]
    session_id = job.payload["session_id"]
    messages_raw: list[str] = job.payload.get("messages", [])
    provider_id, model_slug = job.model_unique_id.split(":", 1)

    _log.info(
        "Starting memory extraction for persona %s, session %s (%d messages)",
        persona_id, session_id, len(messages_raw),
    )

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

    try:
        # Filter technical content from messages.
        filtered = [strip_technical_content(m) for m in messages_raw]
        filtered = [m for m in filtered if m.strip()]

        if not filtered:
            _log.info(
                "No extractable content after filtering for persona %s, session %s",
                persona_id, session_id,
            )
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

        supports_reasoning = await get_model_supports_reasoning(provider_id, model_slug)

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

        # Stream LLM response.
        full_content = ""
        async for event in llm_stream_completion(job.user_id, provider_id, request):
            match event:
                case ContentDelta(delta=delta):
                    full_content += delta
                case StreamDone():
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
                    raise RuntimeError(
                        f"Memory extraction failed: {err.error_code} — {err.message}"
                    )

        # Parse extraction output.
        parsed_entries = parse_extraction_output(full_content)
        _log.info(
            "Parsed %d entries from extraction for persona %s, session %s",
            len(parsed_entries), persona_id, session_id,
        )

        # Create journal entries in DB.
        entries_created = 0
        for entry_data in parsed_entries:
            entry_id = await repo.create_journal_entry(
                user_id=job.user_id,
                persona_id=persona_id,
                content=entry_data["content"],
                category=entry_data["category"],
                source_session_id=session_id,
                is_correction=entry_data["is_correction"],
            )

            now = datetime.now(UTC)
            await event_bus.publish(
                Topics.MEMORY_ENTRY_CREATED,
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
                scope=f"persona:{persona_id}",
                target_user_ids=[job.user_id],
                correlation_id=job.correlation_id,
            )
            entries_created += 1

        # Enforce 50-entry cap on uncommitted entries.
        discarded = await repo.discard_oldest_uncommitted(
            job.user_id, persona_id, max_count=50,
        )
        if discarded > 0:
            _log.info(
                "Discarded %d oldest uncommitted entries for persona %s (cap enforcement)",
                discarded, persona_id,
            )

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
            "Memory extraction completed for persona %s, session %s: %d entries created",
            persona_id, session_id, entries_created,
        )

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
        raise

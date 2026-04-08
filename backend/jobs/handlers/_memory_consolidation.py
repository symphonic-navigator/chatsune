"""Job handler — memory consolidation (dreaming).

Takes committed journal entries and integrates them into the persona's
persistent memory body via LLM-driven consolidation.
"""

import logging
from datetime import UTC, datetime
from uuid import uuid4

from backend.jobs._models import JobConfig, JobEntry
from backend.modules.llm import ContentDelta, StreamDone, StreamError
from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart
from shared.events.memory import (
    MemoryDreamCompletedEvent,
    MemoryDreamFailedEvent,
    MemoryDreamStartedEvent,
)
from shared.topics import Topics

_log = logging.getLogger(__name__)


async def handle_memory_consolidation(
    job: JobEntry,
    config: JobConfig,
    redis,
    event_bus,
) -> None:
    """Consolidate committed journal entries into the persona memory body."""
    # Deferred imports to avoid circular dependency.
    from backend.database import get_db
    from backend.modules.llm import stream_completion as llm_stream_completion
    from backend.modules.llm import get_model_supports_reasoning
    from backend.modules.memory._consolidation import (
        build_consolidation_prompt,
        validate_memory_body,
    )
    from backend.modules.memory._repository import MemoryRepository
    from backend.token_counter import count_tokens

    persona_id = job.payload["persona_id"]
    provider_id, model_slug = job.model_unique_id.split(":", 1)
    dream_id = str(uuid4())

    _log.info(
        "Starting memory consolidation (dream) for persona %s (dream_id=%s)",
        persona_id, dream_id,
    )

    db = get_db()
    repo = MemoryRepository(db)

    # Get committed entries — if none, return early.
    committed = await repo.list_journal_entries(
        job.user_id, persona_id, state="committed",
    )
    if not committed:
        _log.info(
            "No committed entries for persona %s — skipping consolidation",
            persona_id,
        )
        return

    # Publish started event.
    await event_bus.publish(
        Topics.MEMORY_DREAM_STARTED,
        MemoryDreamStartedEvent(
            persona_id=persona_id,
            entries_count=len(committed),
            correlation_id=job.correlation_id,
            timestamp=datetime.now(UTC),
        ),
        scope=f"persona:{persona_id}",
        target_user_ids=[job.user_id],
        correlation_id=job.correlation_id,
    )

    try:
        # Load current memory body.
        body_doc = await repo.get_current_memory_body(job.user_id, persona_id)
        existing_body = body_doc["content"] if body_doc else None

        # Build consolidation prompt.
        entries_for_prompt = [
            {"content": e["content"], "is_correction": e.get("is_correction", False)}
            for e in committed
        ]
        system_prompt = build_consolidation_prompt(
            existing_body=existing_body,
            entries=entries_for_prompt,
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
        async for event in llm_stream_completion(
            job.user_id, provider_id, request, source="job:memory_consolidation",
        ):
            match event:
                case ContentDelta(delta=delta):
                    full_content += delta
                case StreamDone():
                    _log.debug(
                        "Consolidation stream completed for persona %s",
                        persona_id,
                    )
                    break
                case StreamError() as err:
                    _log.error(
                        "Consolidation stream error for persona %s: %s — %s",
                        persona_id, err.error_code, err.message,
                    )
                    raise RuntimeError(
                        f"Memory consolidation failed: {err.error_code} — {err.message}"
                    )

        # Validate the result.
        if not validate_memory_body(full_content):
            raise ValueError(
                "Consolidation produced invalid memory body "
                "(empty, whitespace-only, or over token limit)"
            )

        # Save new memory body version.
        token_count = count_tokens(full_content)
        new_version = await repo.save_memory_body(
            user_id=job.user_id,
            persona_id=persona_id,
            content=full_content,
            token_count=token_count,
            entries_processed=len(committed),
        )

        # Archive processed entries.
        archived_count = await repo.archive_entries(
            job.user_id, persona_id, dream_id=dream_id,
        )
        _log.info(
            "Archived %d committed entries for persona %s (dream_id=%s)",
            archived_count, persona_id, dream_id,
        )

        # Update Redis tracking state.
        tracking_key = f"memory:dream:{job.user_id}:{persona_id}"
        await redis.hset(tracking_key, mapping={
            "last_dream_at": datetime.now(UTC).isoformat(),
        })

        # Publish completed event.
        await event_bus.publish(
            Topics.MEMORY_DREAM_COMPLETED,
            MemoryDreamCompletedEvent(
                persona_id=persona_id,
                entries_processed=len(committed),
                body_version=new_version,
                body_token_count=token_count,
                correlation_id=job.correlation_id,
                timestamp=datetime.now(UTC),
            ),
            scope=f"persona:{persona_id}",
            target_user_ids=[job.user_id],
            correlation_id=job.correlation_id,
        )

        _log.info(
            "Memory consolidation completed for persona %s: version=%d, tokens=%d, entries=%d",
            persona_id, new_version, token_count, len(committed),
        )

    except Exception as exc:
        _log.error(
            "Memory consolidation failed for persona %s: %s",
            persona_id, exc,
        )
        await event_bus.publish(
            Topics.MEMORY_DREAM_FAILED,
            MemoryDreamFailedEvent(
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

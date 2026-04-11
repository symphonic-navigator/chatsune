# Memory module public API
import os
from datetime import UTC, datetime

from backend.modules.memory._handlers import router
from backend.modules.memory._repository import MemoryRepository
from backend.modules.memory._assembly import assemble_memory_context
from shared.dtos.memory import JournalEntryDto
from shared.events.memory import MemoryEntryAuthoredByPersonaEvent
from shared.topics import Topics


async def init_indexes(db) -> None:
    repo = MemoryRepository(db)
    await repo.create_indexes()


async def get_memory_context(user_id: str, persona_id: str) -> str | None:
    """Load memory body + journal entries and assemble the RAG context block."""
    from backend.database import get_db

    repo = MemoryRepository(get_db())
    body_doc = await repo.get_current_memory_body(user_id, persona_id)
    memory_body = body_doc["content"] if body_doc else None
    committed = await repo.list_journal_entries(user_id, persona_id, state="committed")
    uncommitted = await repo.list_journal_entries(user_id, persona_id, state="uncommitted")

    max_tokens = int(os.environ.get("MEMORY_RAG_MAX_TOKENS", "6000"))

    return assemble_memory_context(
        memory_body=memory_body,
        committed_entries=committed,
        uncommitted_entries=uncommitted,
        max_tokens=max_tokens,
    )


async def delete_by_persona(user_id: str, persona_id: str) -> int:
    """Delete all memory data for a persona."""
    from backend.database import get_db

    repo = MemoryRepository(get_db())
    return await repo.delete_by_persona(user_id, persona_id)


async def write_persona_authored_entry(
    *,
    user_id: str,
    persona_id: str,
    persona_name: str,
    content: str,
    category: str,
    source_session_id: str,
    correlation_id: str,
) -> JournalEntryDto:
    """Create an uncommitted journal entry written by the persona itself.

    Used by the ``write_journal_entry`` server-side tool. Creates the
    entry via the repository, loads it back as a ``JournalEntryDto`` and
    publishes ``MemoryEntryAuthoredByPersonaEvent`` so the frontend can
    refresh the journal view and raise an info toast.
    """
    from backend.database import get_db
    from backend.ws.event_bus import get_event_bus

    repo = MemoryRepository(get_db())
    now = datetime.now(UTC)
    entry_id = await repo.create_journal_entry(
        user_id=user_id,
        persona_id=persona_id,
        content=content,
        category=category,
        source_session_id=source_session_id,
        created_at=now,
    )
    dto = JournalEntryDto(
        id=entry_id,
        persona_id=persona_id,
        content=content,
        category=category,
        state="uncommitted",
        is_correction=False,
        created_at=now,
        committed_at=None,
        auto_committed=False,
    )

    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.MEMORY_ENTRY_AUTHORED_BY_PERSONA,
        MemoryEntryAuthoredByPersonaEvent(
            entry=dto,
            persona_name=persona_name,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"persona:{persona_id}",
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )

    return dto


__all__ = [
    "router",
    "init_indexes",
    "get_memory_context",
    "MemoryRepository",
    "delete_by_persona",
    "write_persona_authored_entry",
]

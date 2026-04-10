# Memory module public API
import os

from backend.modules.memory._handlers import router
from backend.modules.memory._repository import MemoryRepository
from backend.modules.memory._assembly import assemble_memory_context


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
    from backend.modules.memory._repository import MemoryRepository
    from backend.database import get_db

    repo = MemoryRepository(await get_db())
    return await repo.delete_by_persona(user_id, persona_id)


__all__ = ["router", "init_indexes", "get_memory_context", "MemoryRepository", "delete_by_persona"]

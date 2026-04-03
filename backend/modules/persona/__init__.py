"""Persona module — user-owned AI personas.

Public API: import only from this file.
"""

from backend.modules.persona._handlers import router
from backend.modules.persona._repository import PersonaRepository
from backend.database import get_db


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the persona module collections."""
    await PersonaRepository(db).create_indexes()


async def get_persona(persona_id: str, user_id: str) -> dict | None:
    """Get a persona by ID, scoped to the owning user."""
    db = get_db()
    repo = PersonaRepository(db)
    return await repo.find_by_id(persona_id, user_id)


__all__ = ["router", "init_indexes", "get_persona"]

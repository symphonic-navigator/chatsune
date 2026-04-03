"""Persona module — user-owned AI personas.

Public API: import only from this file.
"""

from backend.modules.persona._handlers import router
from backend.modules.persona._repository import PersonaRepository
from backend.database import get_db


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the persona module collections."""
    await PersonaRepository(db).create_indexes()


__all__ = ["router", "init_indexes"]

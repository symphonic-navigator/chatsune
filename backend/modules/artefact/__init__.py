"""Artefact module — session-scoped artefact storage with undo/redo.

Public API: import only from this file.
"""

from backend.modules.artefact._handlers import router
from backend.modules.artefact._repository import ArtefactRepository


async def init_indexes(db) -> None:
    await ArtefactRepository(db).create_indexes()


__all__ = ["router", "init_indexes"]

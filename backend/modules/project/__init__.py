"""Project module — user-owned project containers.

Public API: import only from this file.
"""

from backend.modules.project._repository import ProjectRepository


async def init_indexes(db) -> None:
    await ProjectRepository(db).create_indexes()


__all__ = ["init_indexes", "ProjectRepository"]

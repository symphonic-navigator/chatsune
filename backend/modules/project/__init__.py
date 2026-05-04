"""Project module — user-owned project containers.

Public API: import only from this file.
"""

import logging

from backend.database import get_db
from backend.modules.project._handlers import router
from backend.modules.project._repository import ProjectRepository

_log = logging.getLogger(__name__)


def _repo() -> ProjectRepository:
    """Internal helper: build a repo bound to the current request DB."""
    return ProjectRepository(get_db())


async def init_indexes(db) -> None:
    await ProjectRepository(db).create_indexes()


async def delete_all_for_user(user_id: str) -> int:
    """Delete every project owned by ``user_id``. Returns the deleted count.

    Called by the user self-delete (right-to-be-forgotten) cascade.
    """
    count = await _repo().delete_all_for_user(user_id)
    _log.info(
        "project.delete_all_for_user user_id=%s deleted=%d", user_id, count,
    )
    return count


async def get_library_ids(project_id: str, user_id: str) -> list[str]:
    """Return the project's ``knowledge_library_ids`` or ``[]``.

    Called by the chat orchestrator on every inference turn (Phase 4) to
    merge project-level libraries into the retrieval search.
    """
    return await _repo().get_library_ids(project_id, user_id)


async def list_project_ids_for_user(user_id: str) -> list[str]:
    """Return every project ``_id`` owned by ``user_id``.

    Used by surfaces that need to enumerate the user's projects without
    paying for full document deserialisation.
    """
    docs = await _repo().list_for_user(user_id)
    return [d["_id"] for d in docs]


async def remove_library_from_all_projects(library_id: str) -> int:
    """Pull a deleted knowledge-library id from every project.

    Returns the number of project documents that were updated. Called by
    the knowledge-library cascade so that orphan library references never
    survive a delete.
    """
    return await _repo().remove_library_from_all_projects(library_id)


async def set_pinned(project_id: str, user_id: str, pinned: bool) -> bool:
    """Pin or unpin a project. Returns ``True`` iff a doc was modified."""
    return await _repo().set_pinned(project_id, user_id, pinned)


__all__ = [
    "router",
    "init_indexes",
    "ProjectRepository",
    "delete_all_for_user",
    "get_library_ids",
    "list_project_ids_for_user",
    "remove_library_from_all_projects",
    "set_pinned",
]

"""Project module — user-owned project containers.

Public API: import only from this file.
"""

import logging

from backend.database import get_db
from backend.modules.project._handlers import router
from backend.modules.project._repository import ProjectRepository

_log = logging.getLogger(__name__)


async def init_indexes(db) -> None:
    await ProjectRepository(db).create_indexes()


async def delete_all_for_user(user_id: str) -> int:
    """Delete every project owned by ``user_id``. Returns the deleted count.

    Called by the user self-delete (right-to-be-forgotten) cascade.
    """
    repo = ProjectRepository(get_db())
    count = await repo.delete_all_for_user(user_id)
    _log.info(
        "project.delete_all_for_user user_id=%s deleted=%d", user_id, count,
    )
    return count


__all__ = [
    "router",
    "init_indexes",
    "ProjectRepository",
    "delete_all_for_user",
]

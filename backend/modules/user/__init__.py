"""User module — auth, user management, audit log.

Public API: import only from this file.
"""

from backend.modules.user._handlers import router
from backend.modules.user._repository import UserRepository
from backend.modules.user._audit import AuditRepository


async def init_indexes(db) -> None:
    """Create MongoDB indexes for user module collections."""
    await UserRepository(db).create_indexes()
    await AuditRepository(db).create_indexes()


__all__ = ["router", "init_indexes"]

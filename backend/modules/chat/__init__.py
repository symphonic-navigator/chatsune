"""Chat module — sessions, messages, inference orchestration.

Public API: import only from this file.
"""

from backend.modules.chat._handlers import router
from backend.modules.chat._repository import ChatRepository


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the chat module collections."""
    await ChatRepository(db).create_indexes()


__all__ = ["router", "init_indexes"]

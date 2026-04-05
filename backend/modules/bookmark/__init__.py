"""Bookmark module — bookmark messages across chat sessions.

Public API: import only from this file.
"""

from backend.modules.bookmark._handlers import router as bookmark_router
from backend.modules.bookmark._repository import BookmarkRepository


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the bookmark module collections."""
    await BookmarkRepository(db).create_indexes()


async def delete_bookmarks_for_session(session_id: str) -> None:
    """Cascade delete: remove all bookmarks when a session is deleted."""
    from backend.database import get_db

    repo = BookmarkRepository(get_db())
    await repo.delete_by_session(session_id)


async def delete_bookmarks_for_message(message_id: str) -> None:
    """Cascade delete: remove all bookmarks when a message is deleted."""
    from backend.database import get_db

    repo = BookmarkRepository(get_db())
    await repo.delete_by_message(message_id)


__all__ = [
    "bookmark_router",
    "BookmarkRepository",
    "init_indexes",
    "delete_bookmarks_for_session",
    "delete_bookmarks_for_message",
]

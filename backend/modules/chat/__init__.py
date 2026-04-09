"""Chat module — sessions, messages, inference orchestration.

Public API: import only from this file. Internal modules (``_orchestrator``,
``_handlers_ws``, ``_repository`` …) must never be imported from outside the
chat module.
"""

import logging

from backend.modules.bookmark import delete_bookmarks_for_session
from backend.database import get_db
from backend.modules.chat._handlers import router
from backend.modules.chat._handlers_ws import (
    handle_chat_cancel,
    handle_chat_edit,
    handle_chat_regenerate,
    handle_chat_send,
    handle_incognito_send,
    update_session_title,
)
from backend.modules.chat._orchestrator import (
    cancel_all_for_user,
    trigger_disconnect_extraction,
)
from backend.modules.chat._prompt_assembler import assemble_preview
from backend.modules.chat._repository import ChatRepository

_log = logging.getLogger(__name__)


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the chat module collections."""
    await ChatRepository(db).create_indexes()


async def cleanup_stale_empty_sessions() -> int:
    """Delete empty sessions older than 24 hours. Returns count of deleted sessions."""
    db = get_db()
    repo = ChatRepository(db)
    stale_ids = await repo.delete_stale_empty_sessions(max_age_minutes=1440)
    if stale_ids:
        for sid in stale_ids:
            await delete_bookmarks_for_session(sid)
        _log.info("Cleaned up %d stale empty sessions", len(stale_ids))
    return len(stale_ids)


async def cleanup_soft_deleted_sessions() -> int:
    """Hard-delete sessions that were soft-deleted more than 1 hour ago. Returns count."""
    db = get_db()
    repo = ChatRepository(db)
    deleted_ids = await repo.hard_delete_expired_sessions(max_age_minutes=60)
    if deleted_ids:
        for sid in deleted_ids:
            await delete_bookmarks_for_session(sid)
        _log.info("Hard-deleted %d soft-deleted sessions", len(deleted_ids))
    return len(deleted_ids)


async def find_sessions_for_extraction(
    user_id: str, persona_id: str,
) -> dict | None:
    """Return the most recent non-deleted session for a (user, persona) pair, or None.

    Public API for the periodic memory-extraction loop so it does not need to
    reach into chat module internals or the chat_sessions collection directly.
    """
    db = get_db()
    repo = ChatRepository(db)
    return await repo.get_latest_active_session(user_id, persona_id)


async def list_unextracted_messages_for_session(
    session_id: str, limit: int = 20,
) -> list[dict]:
    """Return up to ``limit`` unextracted user messages for a session."""
    db = get_db()
    repo = ChatRepository(db)
    return await repo.list_unextracted_user_messages(session_id, limit=limit)


async def get_latest_user_messages_for_persona(
    user_id: str,
    persona_id: str,
    limit: int,
) -> tuple[str, list[dict]] | None:
    """Return ``(session_id, user_messages)`` for the most recent session of a persona.

    Returns ``None`` if the user has no sessions for that persona. Otherwise
    returns the latest session id together with up to ``limit`` most recent
    user messages (each as the raw message dict from the chat repository).
    Used by the memory module to trigger manual extractions without reaching
    into chat internals.
    """
    repo = ChatRepository(get_db())
    sessions = await repo.list_sessions(user_id)
    persona_sessions = [s for s in sessions if s.get("persona_id") == persona_id]
    if not persona_sessions:
        return None
    latest = persona_sessions[0]
    all_messages = await repo.list_messages(latest["_id"])
    user_messages = [m for m in all_messages if m["role"] == "user"]
    return latest["_id"], user_messages[-limit:]


async def mark_messages_extracted(
    message_ids: list[str], *, session=None,
) -> int:
    """Mark chat messages as having been processed by memory extraction.

    Public-API wrapper around the chat repository so other modules (memory
    extraction job handler) do not need to import chat internals. Accepts an
    optional MongoDB ``session`` so the caller can wrap the update in a
    transaction alongside other writes.
    """
    repo = ChatRepository(get_db())
    return await repo.mark_messages_extracted(message_ids, session=session)


async def get_session_summaries(session_ids: list[str], user_id: str) -> dict[str, dict]:
    """Return ``{session_id: {"title": str | None, "persona_id": str}}`` for the given ids.

    Public-API helper so other modules (artefact list view) can enrich rows with
    session context without reaching into the chat repository directly.
    """
    repo = ChatRepository(get_db())
    docs = await repo.find_sessions_by_ids(session_ids, user_id)
    return {
        str(d["_id"]): {"title": d.get("title"), "persona_id": d.get("persona_id")}
        for d in docs
    }


__all__ = [
    "router", "init_indexes",
    "handle_chat_send", "handle_chat_edit", "handle_chat_regenerate",
    "handle_chat_cancel",
    "handle_incognito_send", "update_session_title",
    "trigger_disconnect_extraction", "cancel_all_for_user",
    "cleanup_stale_empty_sessions", "cleanup_soft_deleted_sessions", "assemble_preview",
    "find_sessions_for_extraction", "list_unextracted_messages_for_session",
    "get_latest_user_messages_for_persona", "mark_messages_extracted",
    "get_session_summaries",
]

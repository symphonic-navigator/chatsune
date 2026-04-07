"""Artefact module — session-scoped artefact storage with undo/redo.

Public API: import only from this file.
"""

import re
from datetime import datetime, timezone

from backend.database import get_db
from backend.modules.artefact._handlers import router, global_router
from backend.modules.artefact._repository import ArtefactRepository

_HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


async def init_indexes(db) -> None:
    await ArtefactRepository(db).create_indexes()


async def create_artefact(
    *,
    user_id: str,
    session_id: str,
    handle: str,
    title: str,
    artefact_type: str,
    content: str,
    language: str | None = None,
    correlation_id: str = "",
) -> dict:
    """Create a new artefact in a session.

    Returns a result dict with either ``{"ok": True, "handle", "artefact_id"}``
    or ``{"error": "..."}`` for validation/conflict errors. Publishes
    ``ARTEFACT_CREATED`` on success.
    """
    from backend.ws.event_bus import get_event_bus
    from shared.events.artefact import ArtefactCreatedEvent
    from shared.topics import Topics

    if not _HANDLE_RE.match(handle) or len(handle) > 64:
        return {"error": f"Invalid handle '{handle}'. Must match ^[a-z0-9][a-z0-9-]*$ and be at most 64 characters."}

    repo = ArtefactRepository(get_db())
    existing = await repo.get_by_handle(session_id, handle)
    if existing:
        return {"error": f"An artefact with handle '{handle}' already exists in this session."}

    now = datetime.now(timezone.utc)
    doc = {
        "session_id": session_id,
        "user_id": user_id,
        "handle": handle,
        "title": title,
        "type": artefact_type,
        "language": language,
        "content": content,
        "size_bytes": len(content.encode("utf-8")),
        "version": 1,
        "max_version": 1,
        "created_at": now,
        "updated_at": now,
    }
    created = await repo.create(doc)
    artefact_id = str(created["_id"])

    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.ARTEFACT_CREATED,
        ArtefactCreatedEvent(
            session_id=session_id,
            artefact_id=artefact_id,
            handle=handle,
            title=title,
            artefact_type=artefact_type,
            language=language,
            size_bytes=created["size_bytes"],
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )

    return {"ok": True, "handle": handle, "artefact_id": artefact_id}


async def update_artefact(
    *,
    user_id: str,
    session_id: str,
    handle: str,
    content: str,
    title: str | None = None,
    correlation_id: str = "",
) -> dict:
    """Update an artefact, bumping its version and clearing redo history."""
    from backend.ws.event_bus import get_event_bus
    from shared.events.artefact import ArtefactUpdatedEvent
    from shared.topics import Topics

    repo = ArtefactRepository(get_db())
    artefact = await repo.get_by_handle(session_id, handle)
    if not artefact:
        return {"error": f"No artefact with handle '{handle}' found in this session."}

    artefact_id = str(artefact["_id"])
    current_version = artefact.get("version", 1)

    await repo.save_version(artefact_id, current_version, artefact["content"], artefact["title"])
    await repo.delete_versions_above(artefact_id, current_version)

    new_version = current_version + 1
    updated = await repo.update_content(
        artefact_id=artefact_id,
        content=content,
        title=title,
        new_version=new_version,
        max_version=new_version,
    )

    if not updated:
        return {"error": "Update failed unexpectedly."}

    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.ARTEFACT_UPDATED,
        ArtefactUpdatedEvent(
            session_id=session_id,
            handle=handle,
            title=updated["title"],
            artefact_type=updated["type"],
            size_bytes=updated["size_bytes"],
            version=new_version,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )

    return {"ok": True, "handle": handle, "version": new_version}


async def read_artefact(*, session_id: str, handle: str) -> dict | None:
    """Return the artefact dict for ``handle`` in ``session_id`` or None."""
    repo = ArtefactRepository(get_db())
    return await repo.get_by_handle(session_id, handle)


async def list_artefacts(*, session_id: str) -> list[dict]:
    """List all artefacts in a session."""
    repo = ArtefactRepository(get_db())
    return await repo.list_by_session(session_id)


__all__ = [
    "router",
    "global_router",
    "init_indexes",
    "create_artefact",
    "update_artefact",
    "read_artefact",
    "list_artefacts",
]

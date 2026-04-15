"""Artefact module — session-scoped artefact storage with undo/redo.

Public API: import only from this file.
"""

import re
from datetime import datetime, timezone

from bson import ObjectId

from backend.database import get_db
from backend.modules.artefact._handlers import router, global_router
from backend.modules.artefact._repository import ArtefactRepository
from shared.dtos.export import (
    ArtefactExportDto,
    ArtefactsBundleDto,
)

_HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# Fields stripped off an artefact document when exporting.
_STRIPPED_ARTEFACT_FIELDS: tuple[str, ...] = ("_id", "user_id", "session_id")

# Fields stripped off a version document when exporting.
_STRIPPED_VERSION_FIELDS: tuple[str, ...] = ("_id", "artefact_id")


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


async def delete_by_session_ids(session_ids: list[str]) -> int:
    """Delete all artefacts for the given session IDs."""
    repo = ArtefactRepository(get_db())
    return await repo.delete_by_session_ids(session_ids)


async def delete_all_for_sessions(session_ids: list[str]) -> int:
    """Alias for ``delete_by_session_ids`` — named for symmetry with other
    modules' rollback hooks so the Phase 2 import orchestrator can uniformly
    call ``delete_all_for_sessions`` on failure.
    """
    return await delete_by_session_ids(session_ids)


async def bulk_export_for_sessions(
    user_id: str, session_ids: list[str],
) -> ArtefactsBundleDto:
    """Export all artefacts + their version history for the given sessions.

    Owner identifiers (``_id``, ``user_id``, ``session_id``) are stripped
    from each artefact doc — the original session id is preserved separately
    as ``original_session_id`` so the import orchestrator can remap to new
    session ids via the map returned from the chat module's bulk_import.

    ``user_id`` is used to filter out any cross-user drift defensively.
    """
    repo = ArtefactRepository(get_db())
    raw_artefacts = await repo.list_for_sessions(session_ids)
    # Defensive ownership filter.
    raw_artefacts = [a for a in raw_artefacts if a.get("user_id") == user_id]

    artefact_ids = [str(a["_id"]) for a in raw_artefacts]
    versions_by_artefact = await repo.list_versions_for_artefacts(artefact_ids)

    exports: list[ArtefactExportDto] = []
    for a in raw_artefacts:
        original_session_id = a["session_id"]
        fields = {
            k: v for k, v in a.items() if k not in _STRIPPED_ARTEFACT_FIELDS
        }
        raw_versions = versions_by_artefact.get(str(a["_id"]), [])
        versions = [
            {k: v for k, v in vdoc.items() if k not in _STRIPPED_VERSION_FIELDS}
            for vdoc in raw_versions
        ]
        exports.append(ArtefactExportDto(
            original_session_id=original_session_id,
            artefact_fields=fields,
            versions=versions,
        ))

    return ArtefactsBundleDto(artefacts=exports)


async def bulk_import_for_sessions(
    user_id: str,
    session_id_map: dict[str, str],
    bundle: ArtefactsBundleDto,
) -> None:
    """Insert artefacts + versions, remapping session references.

    ``session_id_map`` maps ``old_session_id -> new_session_id`` from the
    chat module's bulk_import. Any artefact whose original session is not in
    the map is silently skipped (defensive — should never happen with a
    well-formed bundle).

    Each artefact receives a freshly-generated ``ObjectId``; each version
    receives a fresh ``ObjectId`` and references the new artefact id.
    """
    repo = ArtefactRepository(get_db())

    artefact_inserts: list[dict] = []
    version_inserts: list[dict] = []

    for art in bundle.artefacts:
        new_session_id = session_id_map.get(art.original_session_id)
        if not new_session_id:
            continue

        new_artefact_oid = ObjectId()
        new_artefact_id_str = str(new_artefact_oid)

        adoc = dict(art.artefact_fields)
        for k in _STRIPPED_ARTEFACT_FIELDS:
            adoc.pop(k, None)
        adoc["_id"] = new_artefact_oid
        adoc["user_id"] = user_id
        adoc["session_id"] = new_session_id
        artefact_inserts.append(adoc)

        for raw_version in art.versions:
            vdoc = dict(raw_version)
            for k in _STRIPPED_VERSION_FIELDS:
                vdoc.pop(k, None)
            vdoc["_id"] = ObjectId()
            vdoc["artefact_id"] = new_artefact_id_str
            version_inserts.append(vdoc)

    await repo.bulk_insert_artefacts(artefact_inserts)
    await repo.bulk_insert_versions(version_inserts)


__all__ = [
    "router",
    "global_router",
    "init_indexes",
    "create_artefact",
    "update_artefact",
    "read_artefact",
    "list_artefacts",
    "delete_by_session_ids",
    "delete_all_for_sessions",
    "bulk_export_for_sessions",
    "bulk_import_for_sessions",
]

"""REST handlers for artefact module — user-facing CRUD and undo/redo."""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.database import get_db
from backend.dependencies import require_active_session
from backend.modules.artefact._repository import ArtefactRepository
from backend.ws.event_bus import get_event_bus
from shared.dtos.artefact import ArtefactDetailDto, ArtefactSummaryDto
from shared.events.artefact import (
    ArtefactDeletedEvent,
    ArtefactRedoEvent,
    ArtefactUndoEvent,
    ArtefactUpdatedEvent,
)
from shared.topics import Topics

router = APIRouter(
    prefix="/api/chat/sessions/{session_id}/artefacts",
    tags=["artefacts"],
)


class PatchArtefactRequest(BaseModel):
    title: str | None = None
    content: str | None = None


def _repo() -> ArtefactRepository:
    return ArtefactRepository(get_db())


def _to_summary(doc: dict) -> ArtefactSummaryDto:
    return ArtefactSummaryDto(
        id=str(doc["_id"]),
        session_id=doc["session_id"],
        handle=doc["handle"],
        title=doc["title"],
        type=doc["type"],
        language=doc.get("language"),
        size_bytes=doc["size_bytes"],
        version=doc["version"],
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


def _to_detail(doc: dict) -> ArtefactDetailDto:
    return ArtefactDetailDto(
        id=str(doc["_id"]),
        session_id=doc["session_id"],
        handle=doc["handle"],
        title=doc["title"],
        type=doc["type"],
        language=doc.get("language"),
        size_bytes=doc["size_bytes"],
        version=doc["version"],
        max_version=doc.get("max_version", doc["version"]),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
        content=doc["content"],
    )


async def _get_owned_artefact(repo: ArtefactRepository, session_id: str, artefact_id: str, user_id: str) -> dict:
    """Fetch artefact by ID or handle and verify it belongs to the session and user."""
    from bson import ObjectId
    from bson.errors import InvalidId

    doc = None
    try:
        ObjectId(artefact_id)
        doc = await repo.get_by_id(artefact_id)
    except (InvalidId, Exception):
        # Not a valid ObjectId — try handle-based lookup
        doc = await repo.get_by_handle(session_id, artefact_id)

    if not doc or doc.get("session_id") != session_id or doc.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Artefact not found")
    return doc


@router.get("/")
async def list_artefacts(
    session_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    docs = await repo.list_by_session(session_id)
    # Filter to only artefacts owned by this user
    docs = [d for d in docs if d.get("user_id") == user["sub"]]
    return [_to_summary(d) for d in docs]


@router.get("/{artefact_id}")
async def get_artefact(
    session_id: str,
    artefact_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    doc = await _get_owned_artefact(repo, session_id, artefact_id, user["sub"])
    return _to_detail(doc)


@router.patch("/{artefact_id}")
async def update_artefact(
    session_id: str,
    artefact_id: str,
    body: PatchArtefactRequest,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    doc = await _get_owned_artefact(repo, session_id, artefact_id, user["sub"])

    if body.content is None and body.title is None:
        raise HTTPException(status_code=400, detail="No fields to update")

    if body.content is not None:
        # Save current version before overwriting
        await repo.save_version(
            artefact_id=artefact_id,
            version=doc["version"],
            content=doc["content"],
            title=doc["title"],
        )
        # Clear redo history — any versions above current are now unreachable
        await repo.delete_versions_above(artefact_id, doc["version"])

        new_version = doc["version"] + 1
        updated = await repo.update_content(
            artefact_id=artefact_id,
            content=body.content,
            title=body.title,
            new_version=new_version,
            max_version=new_version,
        )
    else:
        # Title-only rename
        updated = await repo.rename(artefact_id, body.title)

    if not updated:
        raise HTTPException(status_code=404, detail="Artefact not found")

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    await get_event_bus().publish(
        Topics.ARTEFACT_UPDATED,
        ArtefactUpdatedEvent(
            session_id=session_id,
            handle=updated["handle"],
            title=updated["title"],
            artefact_type=updated["type"],
            size_bytes=updated["size_bytes"],
            version=updated["version"],
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )

    return _to_detail(updated)


@router.delete("/{artefact_id}", status_code=204)
async def delete_artefact(
    session_id: str,
    artefact_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    doc = await _get_owned_artefact(repo, session_id, artefact_id, user["sub"])
    handle = doc["handle"]

    deleted = await repo.delete(artefact_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Artefact not found")

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    await get_event_bus().publish(
        Topics.ARTEFACT_DELETED,
        ArtefactDeletedEvent(
            session_id=session_id,
            handle=handle,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )


@router.post("/{artefact_id}/undo")
async def undo_artefact(
    session_id: str,
    artefact_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    doc = await _get_owned_artefact(repo, session_id, artefact_id, user["sub"])

    current_version = doc["version"]
    if current_version <= 1:
        raise HTTPException(status_code=409, detail="Nothing to undo")

    # Save current state before stepping back
    await repo.save_version(
        artefact_id=artefact_id,
        version=current_version,
        content=doc["content"],
        title=doc["title"],
    )

    target_version = current_version - 1
    updated = await repo.set_version_pointer(
        artefact_id=artefact_id,
        version=target_version,
        max_version=doc["max_version"],
    )
    if not updated:
        raise HTTPException(status_code=409, detail="Undo version not available")

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    await get_event_bus().publish(
        Topics.ARTEFACT_UNDO,
        ArtefactUndoEvent(
            session_id=session_id,
            handle=updated["handle"],
            version=updated["version"],
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )

    return _to_detail(updated)


@router.post("/{artefact_id}/redo")
async def redo_artefact(
    session_id: str,
    artefact_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    doc = await _get_owned_artefact(repo, session_id, artefact_id, user["sub"])

    current_version = doc["version"]
    max_version = doc["max_version"]
    if current_version >= max_version:
        raise HTTPException(status_code=409, detail="Nothing to redo")

    # Save current state before stepping forward
    await repo.save_version(
        artefact_id=artefact_id,
        version=current_version,
        content=doc["content"],
        title=doc["title"],
    )

    target_version = current_version + 1
    updated = await repo.set_version_pointer(
        artefact_id=artefact_id,
        version=target_version,
        max_version=max_version,
    )
    if not updated:
        raise HTTPException(status_code=409, detail="Redo version not available")

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    await get_event_bus().publish(
        Topics.ARTEFACT_REDO,
        ArtefactRedoEvent(
            session_id=session_id,
            handle=updated["handle"],
            version=updated["version"],
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )

    return _to_detail(updated)

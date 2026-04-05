from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.database import get_db
from backend.dependencies import require_active_session
from backend.modules.bookmark._repository import BookmarkRepository
from backend.ws.event_bus import get_event_bus
from shared.dtos.bookmark import CreateBookmarkDto, UpdateBookmarkDto
from shared.events.bookmark import (
    BookmarkCreatedEvent,
    BookmarkDeletedEvent,
    BookmarkUpdatedEvent,
)
from shared.topics import Topics

router = APIRouter(prefix="/api/bookmarks")


def _repo() -> BookmarkRepository:
    return BookmarkRepository(get_db())


@router.post("", status_code=201)
async def create_bookmark(
    body: CreateBookmarkDto,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    doc = await repo.create(
        user_id=user["sub"],
        session_id=body.session_id,
        message_id=body.message_id,
        persona_id=body.persona_id,
        title=body.title,
        scope=body.scope,
    )
    dto = BookmarkRepository.to_dto(doc)

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.BOOKMARK_CREATED,
        BookmarkCreatedEvent(
            bookmark=dto,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"user:{user['sub']}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )

    return dto


@router.get("")
async def list_bookmarks(
    user: dict = Depends(require_active_session),
    session_id: str | None = None,
):
    repo = _repo()
    if session_id:
        docs = await repo.list_by_session(session_id, user["sub"])
    else:
        docs = await repo.list_by_user(user["sub"])
    return [BookmarkRepository.to_dto(d) for d in docs]


class ReorderBookmarksRequest(BaseModel):
    ordered_ids: list[str]


@router.patch("/reorder")
async def reorder_bookmarks(
    body: ReorderBookmarksRequest,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    await repo.reorder(user["sub"], body.ordered_ids)
    return {"status": "ok"}


@router.patch("/{bookmark_id}")
async def update_bookmark(
    bookmark_id: str,
    body: UpdateBookmarkDto,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    existing = await repo.find_by_id(bookmark_id, user["sub"])
    if not existing:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    doc = await repo.update(bookmark_id, user["sub"], updates)
    if not doc:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    dto = BookmarkRepository.to_dto(doc)

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.BOOKMARK_UPDATED,
        BookmarkUpdatedEvent(
            bookmark=dto,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"user:{user['sub']}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )

    return dto


@router.delete("/{bookmark_id}")
async def delete_bookmark(
    bookmark_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    deleted = await repo.delete(bookmark_id, user["sub"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.BOOKMARK_DELETED,
        BookmarkDeletedEvent(
            bookmark_id=bookmark_id,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"user:{user['sub']}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )

    return {"status": "ok"}

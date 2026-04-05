from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, Form
from fastapi.responses import Response
from pydantic import BaseModel

from backend.config import settings
from backend.database import get_db
from backend.dependencies import require_active_session
from backend.modules.storage._blob_store import BlobStore
from backend.modules.storage._repository import StorageRepository
from backend.modules.storage._thumbnail import generate_thumbnail
from backend.modules.storage._validators import validate_upload
from backend.ws.event_bus import get_event_bus
from shared.dtos.storage import StorageFileDto, StorageQuotaDto
from shared.events.storage import (
    StorageFileDeletedEvent,
    StorageFileRenamedEvent,
    StorageFileUploadedEvent,
    StorageQuotaWarningEvent,
)
from shared.topics import Topics

router = APIRouter(prefix="/api/storage")

_TEXT_MEDIA_PREFIXES = ("text/",)
_TEXT_MEDIA_TYPES = {
    "application/json",
    "application/xml",
    "application/javascript",
    "application/x-yaml",
    "application/yaml",
}
_IMAGE_MEDIA_PREFIXES = ("image/",)


def _repo() -> StorageRepository:
    return StorageRepository(get_db())


def _blob() -> BlobStore:
    return BlobStore()


def _is_text(media_type: str) -> bool:
    if media_type.startswith(_TEXT_MEDIA_PREFIXES):
        return True
    return media_type in _TEXT_MEDIA_TYPES


def _is_image(media_type: str) -> bool:
    return media_type.startswith(_IMAGE_MEDIA_PREFIXES)


def _text_preview(data: bytes, max_chars: int = 200) -> str | None:
    try:
        text = data.decode("utf-8", errors="replace")
        return text[:max_chars] if text else None
    except Exception:
        return None


@router.post("/files", status_code=201, response_model=StorageFileDto)
async def upload_file(
    file: UploadFile,
    persona_id: str | None = Form(None),
    user: dict = Depends(require_active_session),
):
    user_id = user["sub"]
    is_admin = user["role"] in ("admin", "master_admin")

    data = await file.read()
    repo = _repo()
    quota_used = await repo.get_quota_used(user_id)

    media_type = validate_upload(
        filename=file.filename or "unnamed",
        data=data,
        content_type=file.content_type,
        current_quota_used=quota_used,
        quota_limit=settings.upload_quota_bytes,
        is_admin=is_admin,
    )

    file_id = str(uuid4())
    now = datetime.now(timezone.utc)
    blob_store = _blob()

    # Save blob to disk first
    rel_path = blob_store.save(user_id, file_id, data)

    # Generate thumbnail for images
    thumbnail_b64 = None
    if _is_image(media_type):
        thumbnail_b64 = generate_thumbnail(data)

    # Generate text preview for text files
    text_preview = None
    if _is_text(media_type):
        text_preview = _text_preview(data)

    display_name = file.filename or "unnamed"

    doc = {
        "_id": file_id,
        "user_id": user_id,
        "persona_id": persona_id,
        "original_name": file.filename or "unnamed",
        "display_name": display_name,
        "media_type": media_type,
        "size_bytes": len(data),
        "file_path": rel_path,
        "thumbnail_b64": thumbnail_b64,
        "text_preview": text_preview,
        "created_at": now,
        "updated_at": now,
    }

    await repo.create(doc)
    dto = StorageRepository.file_to_dto(doc)

    # Publish upload event
    correlation_id = str(uuid4())
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.STORAGE_FILE_UPLOADED,
        StorageFileUploadedEvent(
            file=dto,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"user:{user_id}",
        target_user_ids=[user_id],
    )

    # Check quota warning (>= 90%)
    new_quota_used = quota_used + len(data)
    percentage = (new_quota_used / settings.upload_quota_bytes) * 100
    if percentage >= 90:
        await event_bus.publish(
            Topics.STORAGE_QUOTA_WARNING,
            StorageQuotaWarningEvent(
                used_bytes=new_quota_used,
                limit_bytes=settings.upload_quota_bytes,
                percentage=round(percentage, 1),
                correlation_id=correlation_id,
                timestamp=now,
            ),
            scope=f"user:{user_id}",
            target_user_ids=[user_id],
        )

    return dto


@router.get("/files", response_model=list[StorageFileDto])
async def list_files(
    persona_id: str | None = Query(None),
    sort_by: str = Query("date", pattern="^(date|size)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    docs = await repo.find_by_user(
        user_id=user["sub"],
        persona_id=persona_id,
        sort_by=sort_by,
        order=order,
        limit=limit,
        offset=offset,
    )
    return [StorageRepository.file_to_dto(d) for d in docs]


@router.get("/files/{file_id}/download")
async def download_file(
    file_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    doc = await repo.find_by_id(file_id, user["sub"])
    if not doc:
        raise HTTPException(status_code=404, detail="File not found")

    blob_store = _blob()
    data = blob_store.load(doc["user_id"], doc["_id"])
    if data is None:
        raise HTTPException(status_code=404, detail="File data not found")

    return Response(
        content=data,
        media_type=doc["media_type"],
        headers={
            "Content-Disposition": f'inline; filename="{doc["display_name"]}"',
        },
    )


class RenameRequest(BaseModel):
    display_name: str


@router.patch("/files/{file_id}", response_model=StorageFileDto)
async def rename_file(
    file_id: str,
    body: RenameRequest,
    user: dict = Depends(require_active_session),
):
    if not body.display_name or not body.display_name.strip():
        raise HTTPException(status_code=400, detail="display_name must not be empty")

    repo = _repo()
    doc = await repo.update_display_name(file_id, user["sub"], body.display_name.strip())
    if not doc:
        raise HTTPException(status_code=404, detail="File not found")

    dto = StorageRepository.file_to_dto(doc)

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.STORAGE_FILE_RENAMED,
        StorageFileRenamedEvent(
            file_id=file_id,
            display_name=body.display_name.strip(),
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"user:{user['sub']}",
        target_user_ids=[user["sub"]],
    )

    return dto


@router.delete("/files/{file_id}", status_code=204)
async def delete_file(
    file_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    doc = await repo.find_by_id(file_id, user["sub"])
    if not doc:
        raise HTTPException(status_code=404, detail="File not found")

    # Delete blob from disk
    blob_store = _blob()
    blob_store.delete(doc["user_id"], doc["_id"])

    # Delete from database
    await repo.delete(file_id, user["sub"])

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.STORAGE_FILE_DELETED,
        StorageFileDeletedEvent(
            file_id=file_id,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"user:{user['sub']}",
        target_user_ids=[user["sub"]],
    )


@router.get("/quota", response_model=StorageQuotaDto)
async def get_quota(
    user: dict = Depends(require_active_session),
):
    repo = _repo()
    used = await repo.get_quota_used(user["sub"])
    limit_bytes = settings.upload_quota_bytes
    percentage = round((used / limit_bytes) * 100, 1) if limit_bytes > 0 else 0.0

    return StorageQuotaDto(
        used_bytes=used,
        limit_bytes=limit_bytes,
        percentage=percentage,
    )

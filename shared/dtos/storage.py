from datetime import datetime

from pydantic import BaseModel


class StorageFileDto(BaseModel):
    id: str
    user_id: str
    persona_id: str | None = None
    original_name: str
    display_name: str
    media_type: str
    size_bytes: int
    thumbnail_b64: str | None = None
    text_preview: str | None = None
    created_at: datetime
    updated_at: datetime


class StorageQuotaDto(BaseModel):
    used_bytes: int
    limit_bytes: int
    percentage: float


class AttachmentRefDto(BaseModel):
    file_id: str
    display_name: str
    media_type: str
    size_bytes: int
    thumbnail_b64: str | None = None
    text_preview: str | None = None

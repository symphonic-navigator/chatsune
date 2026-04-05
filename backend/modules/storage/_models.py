from datetime import datetime

from pydantic import BaseModel, Field


class StorageFileDocument(BaseModel):
    """Internal MongoDB document model for storage files. Never expose outside storage module."""

    id: str = Field(alias="_id")
    user_id: str
    persona_id: str | None = None
    original_name: str
    display_name: str
    media_type: str
    size_bytes: int
    file_path: str  # relative path: "{user_id}/{uuid}.bin"
    thumbnail_b64: str | None = None
    text_preview: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}

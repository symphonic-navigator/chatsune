"""DTOs for the chatgpt_import REST API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ImportedInfoDto(BaseModel):
    """A record of a single conversation having been imported into a persona."""
    persona_id: str
    persona_name: str
    session_id: str
    imported_at: datetime


class ImportDto(BaseModel):
    import_id: str
    filename: str
    file_size_bytes: int
    status: Literal["parsing", "ready", "failed"]
    conversation_count: int
    skipped_count: int
    skipped_reasons: dict[str, int]
    created_at: datetime
    expires_at: datetime
    last_import_at: datetime | None
    error_message: str | None


class ConversationItemDto(BaseModel):
    chatgpt_conversation_id: str
    title: str
    create_time: datetime
    update_time: datetime
    message_count: int
    first_user_message_preview: str
    first_assistant_message_preview: str
    default_model_slug: str | None
    imports: list[ImportedInfoDto]


class ImportTriggerRequest(BaseModel):
    persona_id: str
    chatgpt_conversation_ids: list[str]


class ImportTriggerJobInfo(BaseModel):
    chatgpt_conversation_id: str
    job_id: str


class ImportTriggerResponse(BaseModel):
    correlation_id: str
    jobs: list[ImportTriggerJobInfo]


class UploadResponse(BaseModel):
    import_id: str
    status: Literal["parsing", "ready", "failed"]
    duplicate: bool  # True if same file_hash already existed; no re-parse


class ReplaceConflictDetail(BaseModel):
    """Body returned by POST /uploads when an active import already exists."""
    message: str
    existing_import_id: str

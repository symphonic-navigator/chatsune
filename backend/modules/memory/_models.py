"""Internal document models for the memory module."""

from datetime import datetime

from pydantic import BaseModel


class JournalEntryDocument(BaseModel):
    user_id: str
    persona_id: str
    content: str
    category: str | None = None
    source_session_id: str
    state: str = "uncommitted"
    is_correction: bool = False
    archived_by_dream_id: str | None = None
    created_at: datetime
    committed_at: datetime | None = None
    auto_committed: bool = False


class MemoryBodyDocument(BaseModel):
    user_id: str
    persona_id: str
    content: str
    token_count: int
    version: int
    entries_processed: int
    created_at: datetime

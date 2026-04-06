"""Memory DTOs — shared between backend modules and frontend."""

from datetime import datetime

from pydantic import BaseModel


class JournalEntryDto(BaseModel):
    id: str
    persona_id: str
    content: str
    category: str | None = None
    state: str  # "uncommitted" | "committed" | "archived"
    is_correction: bool = False
    created_at: datetime
    committed_at: datetime | None = None
    auto_committed: bool = False


class MemoryBodyDto(BaseModel):
    persona_id: str
    content: str
    token_count: int
    version: int
    created_at: datetime


class MemoryBodyVersionDto(BaseModel):
    version: int
    token_count: int
    entries_processed: int
    created_at: datetime


class MemoryContextDto(BaseModel):
    persona_id: str
    uncommitted_count: int
    committed_count: int
    last_extraction_at: datetime | None = None
    last_dream_at: datetime | None = None
    can_trigger_extraction: bool = False

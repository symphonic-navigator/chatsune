"""Memory events — published through the event bus."""

from datetime import datetime

from pydantic import BaseModel

from shared.dtos.memory import JournalEntryDto


class MemoryExtractionStartedEvent(BaseModel):
    type: str = "memory.extraction.started"
    persona_id: str
    correlation_id: str
    timestamp: datetime


class MemoryExtractionCompletedEvent(BaseModel):
    type: str = "memory.extraction.completed"
    persona_id: str
    entries_created: int
    correlation_id: str
    timestamp: datetime


class MemoryExtractionFailedEvent(BaseModel):
    type: str = "memory.extraction.failed"
    persona_id: str
    error_message: str
    correlation_id: str
    timestamp: datetime


class MemoryEntryCreatedEvent(BaseModel):
    type: str = "memory.entry.created"
    entry: JournalEntryDto
    correlation_id: str
    timestamp: datetime


class MemoryEntryCommittedEvent(BaseModel):
    type: str = "memory.entry.committed"
    entry: JournalEntryDto
    correlation_id: str
    timestamp: datetime


class MemoryEntryUpdatedEvent(BaseModel):
    type: str = "memory.entry.updated"
    entry: JournalEntryDto
    correlation_id: str
    timestamp: datetime


class MemoryEntryDeletedEvent(BaseModel):
    type: str = "memory.entry.deleted"
    entry_id: str
    persona_id: str
    correlation_id: str
    timestamp: datetime


class MemoryEntryAutoCommittedEvent(BaseModel):
    type: str = "memory.entry.auto_committed"
    entry: JournalEntryDto
    correlation_id: str
    timestamp: datetime


class MemoryDreamStartedEvent(BaseModel):
    type: str = "memory.dream.started"
    persona_id: str
    entries_count: int
    correlation_id: str
    timestamp: datetime


class MemoryDreamCompletedEvent(BaseModel):
    type: str = "memory.dream.completed"
    persona_id: str
    entries_processed: int
    body_version: int
    body_token_count: int
    correlation_id: str
    timestamp: datetime


class MemoryDreamFailedEvent(BaseModel):
    type: str = "memory.dream.failed"
    persona_id: str
    error_message: str
    correlation_id: str
    timestamp: datetime


class MemoryBodyRollbackEvent(BaseModel):
    type: str = "memory.body.rollback"
    persona_id: str
    rolled_back_to_version: int
    new_version: int
    correlation_id: str
    timestamp: datetime

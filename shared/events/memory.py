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


class MemoryExtractionSkippedEvent(BaseModel):
    """Emitted when an extraction gave up after exhausting retries.

    The source messages have been marked as extracted to stop them
    looping through the queue forever, but no journal entries were
    created from them — effectively a controlled data drop. The UI is
    expected to surface ``user_message`` so the user knows something
    went wrong and can decide whether to re-trigger manually.
    """
    type: str = "memory.extraction.skipped"
    persona_id: str
    skipped_message_count: int
    reason: str            # dev/logging detail
    user_message: str      # shown in the UI
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


class MemoryEntryAuthoredByPersonaEvent(BaseModel):
    type: str = "memory.entry.authored_by_persona"
    entry: JournalEntryDto
    persona_name: str
    correlation_id: str
    timestamp: datetime


class MemoryEntriesDiscardedEvent(BaseModel):
    type: str = "memory.entries.discarded"
    persona_id: str
    discarded_count: int
    user_message: str
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

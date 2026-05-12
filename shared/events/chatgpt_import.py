"""ChatGPT-import events — published through the event bus."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ChatGptImportParseStartedEvent(BaseModel):
    type: str = "chatgpt_import.parse.started"
    import_id: str
    filename: str
    file_size_bytes: int
    correlation_id: str
    timestamp: datetime


class ChatGptImportParseProgressEvent(BaseModel):
    type: str = "chatgpt_import.parse.progress"
    import_id: str
    conversations_indexed: int
    correlation_id: str
    timestamp: datetime


class ChatGptImportParseDoneEvent(BaseModel):
    type: str = "chatgpt_import.parse.done"
    import_id: str
    conversation_count: int
    expires_at: datetime
    skipped_count: int
    skipped_reasons: dict[str, int]
    correlation_id: str
    timestamp: datetime


class ChatGptImportParseFailedEvent(BaseModel):
    type: str = "chatgpt_import.parse.failed"
    import_id: str
    error_code: str
    error_message: str
    correlation_id: str
    timestamp: datetime


class ChatGptImportConversationImportedEvent(BaseModel):
    type: str = "chatgpt_import.conversation.imported"
    import_id: str
    chatgpt_conversation_id: str
    persona_id: str
    session_id: str
    title: str
    correlation_id: str
    timestamp: datetime


class ChatGptImportConversationImportFailedEvent(BaseModel):
    type: str = "chatgpt_import.conversation.import_failed"
    import_id: str
    chatgpt_conversation_id: str
    persona_id: str
    error_code: str
    error_message: str
    correlation_id: str
    timestamp: datetime


class ChatGptImportMemoryProgressEvent(BaseModel):
    """Emitted as the memory batch advances through its sessions.

    ``state="extracting"`` fires when we open work on a session,
    ``state="done"`` when the session has no further unextracted user
    messages. ``session_index`` is 1-based for direct UI display.
    """

    type: str = "chatgpt_import.memory.progress"
    import_id: str
    persona_id: str
    session_id: str
    session_title: str
    session_index: int
    total: int
    state: Literal["extracting", "done"]
    # Filled with the cumulative entries created for this session when
    # ``state == "done"``; ``None`` for the leading ``extracting`` event.
    entries_created: int | None = None
    correlation_id: str
    timestamp: datetime


class ChatGptImportMemoryPausedEvent(BaseModel):
    """Emitted on terminal failure inside the batch handler.

    The UI surfaces a paused banner with Resume / Discard controls.
    ``reason="budget_exhausted"`` unlocks the ``force_budget`` Resume
    variant; all other reasons show a plain Resume button.
    """

    type: str = "chatgpt_import.memory.paused"
    import_id: str
    persona_id: str
    paused_at_session_index: int
    paused_at_session_id: str
    total: int
    reason: Literal["provider_unavailable", "budget_exhausted", "other"]
    user_message: str
    detail: str | None = None
    correlation_id: str
    timestamp: datetime


class ChatGptImportMemoryBatchDoneEvent(BaseModel):
    """Emitted when the batch reaches a terminal "done" or "discarded" state.

    Discard re-uses this event so the UI can collapse the banner with a
    single observer, surfacing ``total_entries_created`` reflecting work
    that completed before the discard.
    """

    type: str = "chatgpt_import.memory.done"
    import_id: str
    persona_id: str
    total: int
    total_entries_created: int
    correlation_id: str
    timestamp: datetime

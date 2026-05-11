"""ChatGPT-import events — published through the event bus."""

from datetime import datetime

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

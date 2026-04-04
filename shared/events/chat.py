from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ChatStreamStartedEvent(BaseModel):
    type: str = "chat.stream.started"
    session_id: str
    correlation_id: str
    timestamp: datetime


class ChatContentDeltaEvent(BaseModel):
    type: str = "chat.content.delta"
    correlation_id: str
    delta: str


class ChatThinkingDeltaEvent(BaseModel):
    type: str = "chat.thinking.delta"
    correlation_id: str
    delta: str


class ChatStreamEndedEvent(BaseModel):
    type: str = "chat.stream.ended"
    correlation_id: str
    session_id: str
    status: Literal["completed", "cancelled", "error"]
    usage: dict | None = None
    context_status: Literal["green", "yellow", "orange", "red"]
    context_fill_percentage: float = 0.0
    timestamp: datetime


class ChatStreamErrorEvent(BaseModel):
    type: str = "chat.stream.error"
    correlation_id: str
    error_code: str
    recoverable: bool
    user_message: str
    timestamp: datetime


class ChatMessagesTruncatedEvent(BaseModel):
    type: str = "chat.messages.truncated"
    session_id: str
    after_message_id: str
    correlation_id: str
    timestamp: datetime


class ChatMessageUpdatedEvent(BaseModel):
    type: str = "chat.message.updated"
    session_id: str
    message_id: str
    content: str
    token_count: int
    correlation_id: str
    timestamp: datetime


class ChatMessageDeletedEvent(BaseModel):
    type: str = "chat.message.deleted"
    session_id: str
    message_id: str
    correlation_id: str
    timestamp: datetime


class ChatSessionTitleUpdatedEvent(BaseModel):
    type: str = "chat.session.title_updated"
    session_id: str
    title: str
    correlation_id: str
    timestamp: datetime

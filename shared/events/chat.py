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
    timestamp: datetime


class ChatStreamErrorEvent(BaseModel):
    type: str = "chat.stream.error"
    correlation_id: str
    error_code: str
    recoverable: bool
    user_message: str
    timestamp: datetime

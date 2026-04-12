from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from shared.dtos.chat import ArtefactRefDto


class ChatMessageCreatedEvent(BaseModel):
    type: str = "chat.message.created"
    session_id: str
    message_id: str
    role: str
    content: str
    token_count: int
    correlation_id: str
    timestamp: datetime
    # Set only for user messages that originated from an optimistic client
    # entry. Echoed back so the frontend can atomically swap the optimistic
    # store entry for the real MongoDB ID.
    client_message_id: str | None = None


class ChatStreamStartedEvent(BaseModel):
    type: str = "chat.stream.started"
    session_id: str
    correlation_id: str
    timestamp: datetime


class ChatStreamSlowEvent(BaseModel):
    type: str = "chat.stream.slow"
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
    message_id: str | None = None
    status: Literal["completed", "cancelled", "error", "aborted", "refused"]
    usage: dict | None = None
    context_status: Literal["green", "yellow", "orange", "red"]
    context_fill_percentage: float = 0.0
    time_to_first_token_ms: int | None = None
    tokens_per_second: float | None = None
    generation_duration_ms: int | None = None
    provider_name: str | None = None
    model_name: str | None = None
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


class ChatSessionCreatedEvent(BaseModel):
    type: str = "chat.session.created"
    session_id: str
    user_id: str
    persona_id: str
    title: str | None = None
    created_at: datetime
    updated_at: datetime
    correlation_id: str
    timestamp: datetime


class ChatSessionDeletedEvent(BaseModel):
    type: str = "chat.session.deleted"
    session_id: str
    correlation_id: str
    timestamp: datetime


class ChatSessionRestoredEvent(BaseModel):
    type: str = "chat.session.restored"
    session_id: str
    session: dict
    correlation_id: str
    timestamp: datetime


class ChatToolCallStartedEvent(BaseModel):
    type: str = "chat.tool_call.started"
    correlation_id: str
    tool_call_id: str
    tool_name: str
    arguments: dict
    timestamp: datetime


class ChatToolCallCompletedEvent(BaseModel):
    type: str = "chat.tool_call.completed"
    correlation_id: str
    tool_call_id: str
    tool_name: str
    success: bool
    artefact_ref: ArtefactRefDto | None = None
    timestamp: datetime


class ChatClientToolDispatchEvent(BaseModel):
    """Server → client: please execute this tool call and reply with chat.client_tool.result."""
    type: str = "chat.client_tool.dispatch"
    session_id: str
    tool_call_id: str
    tool_name: str
    arguments: dict
    timeout_ms: int
    target_connection_id: str


class WebSearchContextItem(BaseModel):
    title: str
    url: str
    snippet: str
    source_type: str = "search"   # "search" or "fetch"


class ChatWebSearchContextEvent(BaseModel):
    type: str = "chat.web_search.context"
    correlation_id: str
    items: list[WebSearchContextItem]


class ChatSessionToolsUpdatedEvent(BaseModel):
    type: str = "chat.session.tools_updated"
    session_id: str
    disabled_tool_groups: list[str]
    correlation_id: str
    timestamp: datetime


class ChatSessionPinnedUpdatedEvent(BaseModel):
    type: str = "chat.session.pinned_updated"
    session_id: str
    pinned: bool
    correlation_id: str
    timestamp: datetime


class ChatVisionDescriptionEvent(BaseModel):
    type: str = "chat.vision.description"
    correlation_id: str
    file_id: str
    display_name: str
    model_id: str
    status: Literal["pending", "success", "error"]
    text: str | None = None
    error: str | None = None
    timestamp: datetime

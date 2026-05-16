from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from shared.dtos.chat import ArtefactRefDto, ChatSessionExtras, CompactionCheckpointDto
from shared.dtos.images import ImageRefDto


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
    # PTI: knowledge items injected by trigger-phrase match, and overflow info
    # when the combined context exceeds the configured token budget.
    knowledge_context: list[dict] | None = None
    pti_overflow: dict | None = None


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
    context_used_tokens: int = 0
    context_max_tokens: int = 0
    # Total tokens across every persisted message in the session — feeds
    # the user-facing "how full is the conversation" pill. Mirrors the
    # existing ``context_used_tokens`` semantic; kept as a separate field so
    # the two numbers can diverge without breaking older clients.
    total_session_tokens: int | None = None
    # Tokens actually sent upstream this turn (system prompt + tool
    # definitions + pair-selected history + new user message). May be lower
    # than ``total_session_tokens`` in long sessions where pair-selection
    # dropped older turns.
    tokens_actually_sent: int | None = None
    time_to_first_token_ms: int | None = None
    tokens_per_second: float | None = None
    generation_duration_ms: int | None = None
    provider_name: str | None = None
    model_name: str | None = None
    # Persisted assistant-message timeline. Frontend adopts this verbatim,
    # discarding anything it accumulated during the stream — guarantees
    # live and reload renders match. None on early-error paths where
    # nothing was persisted.
    events: list[dict] | None = None
    # Raw assistant content as the LLM emitted it, including unprocessed
    # integration tags (e.g. "<screen_effect rising_emojis 💖🤘🔥>"). The
    # frontend uses this to populate the persisted message in the chat
    # store, so the read-aloud path can re-parse the tags without a
    # database round-trip. None on error paths where nothing was persisted.
    raw_content: str | None = None
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
    # Mindspace: ``None`` = global history, otherwise the owning project.
    # Carried so the frontend can route the new session into the right
    # bucket (sidebar global history vs project-detail-overlay) without
    # a follow-up REST call.
    project_id: str | None = None
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
    # Populated for generate_image tool calls so the frontend can render
    # the inline image block live (without waiting for a session reload).
    # Mirrors the artefact_ref pattern.
    image_refs: list[ImageRefDto] | None = None
    moderated_count: int = 0
    # Tool result text — carried live so the chat pill can show the
    # Response section the moment the tool completes, instead of only
    # after a session reload. None when the tool produced no usable
    # text (rare; safe default).
    result_content: str | None = None
    timestamp: datetime


class ChatToolCallDeltaEvent(BaseModel):
    type: str = "chat.tool_call.delta"
    correlation_id: str
    tool_call_id: str
    tool_index: int
    tool_name: str | None = None
    args_delta: str
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


class ChatSessionTogglesUpdatedEvent(BaseModel):
    type: str = "chat.session.toggles_updated"
    session_id: str
    tools_enabled: bool
    auto_read: bool
    reasoning_override: bool | None
    correlation_id: str
    timestamp: datetime


class ChatSessionExtrasUpdatedEvent(BaseModel):
    """Broadcast when a session's extras (per-session reasoning/tools
    settings) change. Frontends subscribe for multi-device sync — when
    the user updates a setting on one tab, other tabs hydrate from this
    event without a follow-up REST call.
    """
    type: str = "chat.session.extras.updated"
    session_id: str
    extras: ChatSessionExtras
    correlation_id: str
    timestamp: datetime


class ChatSessionPinnedUpdatedEvent(BaseModel):
    type: str = "chat.session.pinned_updated"
    session_id: str
    pinned: bool
    correlation_id: str
    timestamp: datetime


class ChatSessionProjectUpdatedEvent(BaseModel):
    """Mindspace: a session was assigned to (or detached from) a project.

    Carries the new ``project_id`` (``None`` = detached, returned to
    global history) so subscribers can re-classify the session in the
    sidebar / HistoryTab without a follow-up REST call.
    """

    type: str = "chat.session.project.updated"
    session_id: str
    project_id: str | None
    user_id: str
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


class ChatCompactionStartedEvent(BaseModel):
    type: str = "chat.compaction.started"
    session_id: str
    correlation_id: str
    tokens_before: int
    estimated_tokens_after: int
    tail_message_count: int
    timestamp: datetime


class ChatCompactionProgressEvent(BaseModel):
    type: str = "chat.compaction.progress"
    session_id: str
    correlation_id: str
    stage: Literal["preparing", "calling_model", "validating", "persisting"]
    timestamp: datetime


class ChatCompactionCompletedEvent(BaseModel):
    type: str = "chat.compaction.completed"
    session_id: str
    correlation_id: str
    checkpoint: CompactionCheckpointDto
    tokens_saved: int
    new_context_used_tokens: int
    new_context_fill_percentage: float
    truncated_message_count: int = 0
    timestamp: datetime


class ChatCompactionFailedEvent(BaseModel):
    type: str = "chat.compaction.failed"
    session_id: str
    correlation_id: str
    error_code: Literal[
        "compaction_source_too_large",
        "below_threshold",
        "too_small",
        "already_running",
        "llm_failed",
        "validation_failed",
        "stale_prev_checkpoint",
        "unknown",
    ]
    user_message: str
    recoverable: bool
    timestamp: datetime

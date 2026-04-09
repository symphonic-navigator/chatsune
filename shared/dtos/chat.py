from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from shared.dtos.storage import AttachmentRefDto


class ChatSendMessageDto(BaseModel):
    session_id: str
    content: list[dict]
    attachment_ids: list[str] | None = None
    # Frontend-generated optimistic ID ("optimistic-<uuid>"). Echoed back
    # on the message.created event so the frontend can atomically swap
    # the optimistic store entry for the real MongoDB ID.
    client_message_id: str | None = None


class ChatSessionDto(BaseModel):
    id: str
    user_id: str
    persona_id: str
    model_unique_id: str
    state: Literal["idle", "streaming", "requires_action"]
    title: str | None = None
    disabled_tool_groups: list[str] = []
    reasoning_override: bool | None = None
    pinned: bool = False
    # Last-known context window utilisation, persisted at stream-end so
    # the UI can show a non-zero indicator when revisiting an existing
    # chat without having to wait for the next inference to complete.
    context_status: Literal["green", "yellow", "orange", "red"] = "green"
    context_fill_percentage: float = 0.0
    created_at: datetime
    updated_at: datetime


class WebSearchContextItemDto(BaseModel):
    title: str
    url: str
    snippet: str
    source_type: str = "search"   # "search" or "fetch"


class VisionDescriptionSnapshotDto(BaseModel):
    file_id: str
    display_name: str
    model_id: str
    text: str


class ChatMessageDto(BaseModel):
    id: str
    session_id: str
    role: Literal["user", "assistant", "tool"]
    content: str
    thinking: str | None = None
    token_count: int
    attachments: list[AttachmentRefDto] | None = None
    web_search_context: list[WebSearchContextItemDto] | None = None
    knowledge_context: list[dict] | None = None
    vision_descriptions_used: list[VisionDescriptionSnapshotDto] | None = None
    created_at: datetime


class ChatMessagesBundleDto(BaseModel):
    """Response for GET /sessions/{id}/messages.

    Carries the persisted message list plus the last-known context
    metrics so the frontend can hydrate the context pill without
    waiting for the next inference.
    """
    messages: list[ChatMessageDto]
    context_status: Literal["green", "yellow", "orange", "red"] = "green"
    context_fill_percentage: float = 0.0

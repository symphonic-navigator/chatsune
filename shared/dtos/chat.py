from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from shared.dtos.storage import AttachmentRefDto


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

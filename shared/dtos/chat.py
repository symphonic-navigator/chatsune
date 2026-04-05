from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ChatSessionDto(BaseModel):
    id: str
    user_id: str
    persona_id: str
    model_unique_id: str
    state: Literal["idle", "streaming", "requires_action"]
    title: str | None = None
    disabled_tool_groups: list[str] = []
    created_at: datetime
    updated_at: datetime


class WebSearchContextItemDto(BaseModel):
    title: str
    url: str
    snippet: str


class ChatMessageDto(BaseModel):
    id: str
    session_id: str
    role: Literal["user", "assistant", "tool"]
    content: str
    thinking: str | None = None
    token_count: int
    web_search_context: list[WebSearchContextItemDto] | None = None
    created_at: datetime

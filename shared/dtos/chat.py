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
    created_at: datetime
    updated_at: datetime


class ChatMessageDto(BaseModel):
    id: str
    session_id: str
    role: Literal["user", "assistant", "tool"]
    content: str
    thinking: str | None = None
    token_count: int
    created_at: datetime

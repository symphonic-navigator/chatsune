from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ChatSessionDocument(BaseModel):
    """Internal MongoDB document model for chat sessions. Never expose outside chat module."""

    id: str = Field(alias="_id")
    user_id: str
    persona_id: str
    model_unique_id: str
    state: Literal["idle", "streaming", "requires_action"] = "idle"
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}


class ChatMessageDocument(BaseModel):
    """Internal MongoDB document model for chat messages. Never expose outside chat module."""

    id: str = Field(alias="_id")
    session_id: str
    role: Literal["user", "assistant", "tool"]
    content: str
    thinking: str | None = None
    token_count: int
    created_at: datetime

    model_config = {"populate_by_name": True}

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class BookmarkDto(BaseModel):
    id: str
    user_id: str
    session_id: str
    message_id: str
    persona_id: str
    title: str
    scope: Literal["global", "local"]
    display_order: int = 0
    created_at: datetime


class CreateBookmarkDto(BaseModel):
    session_id: str
    message_id: str
    persona_id: str
    title: str
    scope: Literal["global", "local"] = "local"


class UpdateBookmarkDto(BaseModel):
    title: str | None = None
    scope: Literal["global", "local"] | None = None

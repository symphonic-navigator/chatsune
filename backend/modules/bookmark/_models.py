from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class BookmarkDocument(BaseModel):
    id: str = Field(alias="_id")
    user_id: str
    session_id: str
    message_id: str
    persona_id: str
    title: str
    scope: Literal["global", "local"]
    display_order: int = 0
    created_at: datetime

    model_config = {"populate_by_name": True}

"""Internal MongoDB document shape for projects.

Not part of the public API. External code uses ProjectDto from shared/dtos.
"""

from datetime import datetime

from pydantic import BaseModel


class ProjectDocument(BaseModel):
    id: str
    user_id: str
    title: str
    emoji: str | None
    description: str
    nsfw: bool
    pinned: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

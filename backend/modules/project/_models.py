"""Internal MongoDB document shape for projects.

Not part of the public API. External code uses ProjectDto from shared/dtos.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class ProjectDocument(BaseModel):
    id: str
    user_id: str
    title: str
    emoji: str | None
    # Mindspace adds an optional, nullable description. Pre-Mindspace
    # documents either carry a string or no value at all; legacy docs
    # written before this change always set ``""`` so existing rows
    # deserialise unchanged.
    description: str | None = None
    nsfw: bool
    pinned: bool
    sort_order: int
    # Knowledge libraries attached to this project. Merged with persona-
    # level libraries at retrieval time. Defaults to empty so legacy
    # documents read without raising.
    knowledge_library_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

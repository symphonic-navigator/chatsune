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
    # Mindspace adds an optional, nullable description. Both ``""`` (the
    # historical default written by pre-Mindspace creates) and ``None``
    # (the new default for documents created without an explicit
    # description) are valid on-disk values; the field defaults to
    # ``None`` so legacy rows that omit it entirely deserialise without
    # raising.
    description: str | None = None
    nsfw: bool
    pinned: bool
    # Defaults to ``0`` so legacy documents that predate the field
    # deserialise via ``ProjectDocument(**doc)`` without raising. The
    # repo currently bypasses direct construction, so this is a latent
    # safety net rather than an active bug fix.
    sort_order: int = 0
    # Knowledge libraries attached to this project. Merged with persona-
    # level libraries at retrieval time. Defaults to empty so legacy
    # documents read without raising.
    knowledge_library_ids: list[str] = Field(default_factory=list)
    # Mindspace: optional per-project Custom Instructions. ``None`` for
    # legacy documents that lack the field; backwards-compatible read.
    system_prompt: str | None = None
    created_at: datetime
    updated_at: datetime

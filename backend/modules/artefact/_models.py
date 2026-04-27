from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

ArtefactType = Literal["markdown", "code", "html", "svg", "jsx", "mermaid"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ArtefactDocument(BaseModel):
    """MongoDB document for an artefact."""
    session_id: str
    user_id: str
    handle: str
    title: str
    type: ArtefactType
    language: str | None = None
    content: str
    size_bytes: int
    version: int = 1
    max_version: int = 1
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class ArtefactVersionDocument(BaseModel):
    """MongoDB document for an artefact version (undo/redo stack)."""
    artefact_id: str
    version: int
    content: str
    title: str
    created_at: datetime = Field(default_factory=_utcnow)

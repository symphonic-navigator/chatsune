"""Artefact module DTOs."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

ArtefactType = Literal["markdown", "code", "html", "svg", "jsx", "mermaid"]


class ArtefactSummaryDto(BaseModel):
    id: str
    session_id: str
    handle: str
    title: str
    type: ArtefactType
    language: str | None = None
    size_bytes: int
    version: int
    created_at: datetime
    updated_at: datetime


class ArtefactDetailDto(ArtefactSummaryDto):
    content: str
    max_version: int = 1


class ArtefactListItemDto(BaseModel):
    """Row in the global artefacts list — enriched with session and persona context."""
    id: str
    handle: str
    title: str
    type: ArtefactType
    language: str | None = None
    size_bytes: int
    version: int
    created_at: datetime
    updated_at: datetime
    session_id: str
    session_title: str | None
    persona_id: str
    persona_name: str
    persona_monogram: str
    persona_colour_scheme: str

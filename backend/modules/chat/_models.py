from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from shared.dtos.chat import ChatSessionExtras, CompactionCheckpointDto


class ChatSessionDocument(BaseModel):
    """Internal MongoDB document model for chat sessions. Never expose outside chat module."""

    id: str = Field(alias="_id")
    user_id: str
    persona_id: str
    state: Literal["idle", "streaming", "requires_action"] = "idle"
    pinned: bool = False
    # Mindspace: optional reference to the owning project. ``None`` is
    # the legacy / unassigned state — sessions created before Mindspace
    # have no field at all and deserialise as ``None``.
    project_id: str | None = None
    # Per-session reasoning/tools preference. ``None`` means "compute
    # from model capability on first cockpit interaction" — legacy
    # sessions created before this field deserialise that way too.
    extras: ChatSessionExtras | None = None
    # Chat compaction checkpoints — append-only. Default [] keeps pre-feature
    # sessions deserialising without error. See devdocs/specs/2026-05-15-compact-and-continue-design.md.
    compaction_checkpoints: list[CompactionCheckpoint] = Field(default_factory=list)
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
    vision_descriptions_used: list[dict] | None = None
    token_count: int
    created_at: datetime

    model_config = {"populate_by_name": True}


# The document and the DTO are structurally identical — we reuse the
# DTO directly inside the document model to keep both shapes guaranteed
# in lock-step. Each new checkpoint is appended; the inference path
# only ever uses the latest entry.
CompactionCheckpoint = CompactionCheckpointDto

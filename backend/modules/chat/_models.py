from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from shared.dtos.chat import ChatSessionExtras, CompactionCheckpointDto


# The document and the DTO are structurally identical — we reuse the
# DTO directly inside the document model to keep both shapes guaranteed
# in lock-step. Each new checkpoint is appended; the inference path
# only ever uses the latest entry.
CompactionCheckpoint = CompactionCheckpointDto


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
    # High-water mark for per-session monotonic message ordering. Atomically
    # incremented on every message insert (see ``save_message`` /
    # ``next_session_seq`` in ``_repository.py``). Default 0 so legacy
    # sessions deserialise cleanly; backfilled by the
    # ``0001_session_seq`` migration. Never rewound on delete — gaps
    # after deletion are intentional, monotonicity is the only invariant.
    last_message_seq: int = 0
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
    # Per-session monotonic sequence number, assigned atomically at insert
    # time via ``find_one_and_update`` on the session's ``last_message_seq``.
    # Default 0 keeps legacy documents deserialisable; the
    # ``0001_session_seq`` migration backfills correct values for all
    # pre-existing messages before the app accepts requests.
    session_seq: int = 0
    # Snapshot of ``session.extras.replay_tool_history`` at the moment
    # this assistant turn was persisted. Read at history-expansion time
    # so toggle changes do NOT alter how prior turns are re-injected.
    # Default ``True`` preserves the pre-2026-05-17 behaviour for any
    # document written before this spec lands. Only meaningful on
    # assistant documents — user/tool documents never carry the field.
    tool_replay_at_save: bool = True

    model_config = {"populate_by_name": True}

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from shared.dtos.images import ImageRefDto
from shared.dtos.storage import AttachmentRefDto


class ChatSendMessageDto(BaseModel):
    session_id: str
    content: list[dict]
    attachment_ids: list[str] | None = None
    # Frontend-generated optimistic ID ("optimistic-<uuid>"). Echoed back
    # on the message.created event so the frontend can atomically swap
    # the optimistic store entry for the real MongoDB ID.
    client_message_id: str | None = None


class SessionProjectUpdateDto(BaseModel):
    """Body for ``PATCH /api/chat/sessions/{id}/project``.

    Mindspace: assigns ``project_id`` (or detaches when ``None``) on a
    chat session. The single-field shape lets us distinguish "set
    explicitly null" from "field omitted" — only the former is valid;
    omitting the field would surface as a 422 validation error.
    """

    project_id: str | None


class ChatSessionDto(BaseModel):
    id: str
    user_id: str
    persona_id: str
    state: Literal["idle", "streaming", "requires_action"]
    title: str | None = None
    tools_enabled: bool = False
    auto_read: bool = False
    reasoning_override: bool | None = None
    pinned: bool = False
    # Mindspace: optional owning project. ``None`` means the session
    # belongs to no project (the legacy / global-history bucket).
    project_id: str | None = None
    # Last-known context window utilisation, persisted at stream-end so
    # the UI can show a non-zero indicator when revisiting an existing
    # chat without having to wait for the next inference to complete.
    context_status: Literal["green", "yellow", "orange", "red"] = "green"
    context_fill_percentage: float = 0.0
    context_used_tokens: int = 0
    context_max_tokens: int = 0
    created_at: datetime
    updated_at: datetime


class WebSearchContextItemDto(BaseModel):
    title: str
    url: str
    snippet: str
    source_type: str = "search"   # "search" or "fetch"


class VisionDescriptionSnapshotDto(BaseModel):
    file_id: str
    display_name: str
    model_id: str
    text: str


class ArtefactRefDto(BaseModel):
    artefact_id: str
    handle: str
    title: str
    artefact_type: str
    operation: Literal["create", "update"]


class ToolCallRefDto(BaseModel):
    """Metadata for a single tool call executed during inference."""
    tool_call_id: str
    tool_name: str
    arguments: dict
    success: bool
    moderated_count: int = 0


class KnowledgeContextItem(BaseModel):
    library_name: str
    document_title: str
    heading_path: list[str] = Field(default_factory=list)
    preroll_text: str | None = None
    content: str
    score: float | None = None
    source: Literal["search", "trigger"] = "search"
    triggered_by: str | None = None  # phrase, only when source="trigger"


class PtiOverflow(BaseModel):
    dropped_count: int
    dropped_titles: list[str]


# --- chronological timeline entries for an assistant message ---------------
#
# Each tool-derived artefact (knowledge results, web-search results, generic
# tool-call metadata, artefact handle, image refs) becomes one entry on the
# message's ``events`` list. ``seq`` is monotonic per message (starts at 0)
# and is the single ordering key that the renderer follows. The legacy
# parallel lists (``tool_calls``, ``knowledge_context``, ...) remain on the
# DTO for read-back of historical documents but are no longer written by
# new inference runs.


class TimelineEntryKnowledgeSearch(BaseModel):
    kind: Literal["knowledge_search"] = "knowledge_search"
    seq: int
    items: list[KnowledgeContextItem]


class TimelineEntryWebSearch(BaseModel):
    kind: Literal["web_search"] = "web_search"
    seq: int
    items: list[WebSearchContextItemDto]


class TimelineEntryToolCall(BaseModel):
    """Generic tool call — used for tools without a specialised renderer
    and for any failed tool call regardless of which tool it was."""
    kind: Literal["tool_call"] = "tool_call"
    seq: int
    tool_call_id: str
    tool_name: str
    arguments: dict
    success: bool
    moderated_count: int = 0


class TimelineEntryArtefact(BaseModel):
    kind: Literal["artefact"] = "artefact"
    seq: int
    ref: ArtefactRefDto


class TimelineEntryImage(BaseModel):
    kind: Literal["image"] = "image"
    seq: int
    refs: list[ImageRefDto]
    moderated_count: int = 0


TimelineEntryDto = Annotated[
    TimelineEntryKnowledgeSearch
    | TimelineEntryWebSearch
    | TimelineEntryToolCall
    | TimelineEntryArtefact
    | TimelineEntryImage,
    Field(discriminator="kind"),
]


class ChatMessageDto(BaseModel):
    id: str
    session_id: str
    role: Literal["user", "assistant", "tool"]
    content: str
    thinking: str | None = None
    token_count: int
    attachments: list[AttachmentRefDto] | None = None
    web_search_context: list[WebSearchContextItemDto] | None = None
    knowledge_context: list[KnowledgeContextItem] | None = None
    pti_overflow: PtiOverflow | None = None
    vision_descriptions_used: list[VisionDescriptionSnapshotDto] | None = None
    created_at: datetime
    status: Literal["completed", "aborted", "refused"] = "completed"
    refusal_text: str | None = None
    artefact_refs: list[ArtefactRefDto] | None = None
    tool_calls: list[ToolCallRefDto] | None = None
    image_refs: list[ImageRefDto] | None = None
    # Chronological timeline of tool-derived events for this message.
    # New documents populate this list; legacy documents lack it and the
    # repository synthesises one on read.
    events: list[TimelineEntryDto] | None = None
    usage: dict | None = None


class ChatMessagesBundleDto(BaseModel):
    """Response for GET /sessions/{id}/messages.

    Carries the persisted message list plus the last-known context
    metrics so the frontend can hydrate the context pill without
    waiting for the next inference.
    """
    messages: list[ChatMessageDto]
    context_status: Literal["green", "yellow", "orange", "red"] = "green"
    context_fill_percentage: float = 0.0
    context_used_tokens: int = 0
    context_max_tokens: int = 0

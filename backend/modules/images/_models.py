"""MongoDB document models for the images module."""

from datetime import datetime

from pydantic import BaseModel, Field


class GeneratedImageDocument(BaseModel):
    """One row in the ``generated_images`` collection.

    For successful generations all blob/dimension fields are populated.
    For images filtered by upstream moderation, ``moderated=True`` and the
    blob/dimension fields are ``None`` — the stub is retained so the full
    batch context is available for audit and debugging.
    """

    id: str
    user_id: str
    blob_id: str | None = None
    thumb_blob_id: str | None = None
    prompt: str
    model_id: str
    group_id: str
    connection_id: str
    config_snapshot: dict
    width: int | None = None
    height: int | None = None
    content_type: str | None = None
    moderated: bool = False
    moderation_reason: str | None = None
    tags: list[str] = Field(default_factory=list)  # Phase II hook for E2EE-readiness
    generated_at: datetime


class UserImageConfigDocument(BaseModel):
    """One row in the ``user_image_configs`` collection.

    Composite id: ``{user_id}:{connection_id}:{group_id}``.

    ``selected=True`` marks the active config for a user; at most one document
    per user has ``selected=True``. Switching the active config flips this
    atomically (transaction in the repository).

    ``config`` is opaque here; the repository validates it against the group's
    typed schema (via ``LlmService.validate_image_config``) before writing.
    """

    id: str
    user_id: str
    connection_id: str
    group_id: str
    config: dict
    selected: bool = False
    updated_at: datetime

"""DTOs for the project module."""

from datetime import datetime
from typing import Any

import grapheme
from pydantic import BaseModel, Field, field_validator


class _Unset:
    """Sentinel type used to distinguish 'field absent' from 'explicit null'
    in PATCH-style update payloads."""

    _instance: "Any" = None

    def __new__(cls):  # singleton
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET = _Unset()


def _validate_title(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("title must not be empty")
    if len(stripped) > 80:
        raise ValueError("title must be at most 80 characters")
    return stripped


def _validate_emoji(value: str | None) -> str | None:
    if value is None:
        return None
    if grapheme.length(value) != 1:
        raise ValueError("emoji must be exactly one grapheme")
    return value


def _validate_description(value: str) -> str:
    if len(value) > 2000:
        raise ValueError("description must be at most 2000 characters")
    return value


class ProjectDto(BaseModel):
    id: str
    user_id: str
    title: str
    emoji: str | None
    # Mindspace: description is optional / nullable. Pre-Mindspace
    # documents either carry a string or were written with ``""``. Both
    # round-trip; absent means ``None``.
    description: str | None = None
    nsfw: bool
    pinned: bool
    sort_order: int
    # Mindspace: knowledge libraries attached to this project. Defaults
    # to empty for legacy documents that lack the field entirely.
    knowledge_library_ids: list[str] = Field(default_factory=list)
    # Project-level custom instructions injected into the assembled system
    # prompt between model instructions and persona. Defaults to ``None`` for
    # backwards-compatible reads of legacy documents.
    system_prompt: str | None = None
    created_at: datetime
    updated_at: datetime


class ProjectCreateDto(BaseModel):
    title: str
    emoji: str | None = None
    description: str | None = None
    nsfw: bool = False
    knowledge_library_ids: list[str] = Field(default_factory=list)
    system_prompt: str | None = None

    @field_validator("title")
    @classmethod
    def _check_title(cls, v: str) -> str:
        return _validate_title(v)

    @field_validator("emoji")
    @classmethod
    def _check_emoji(cls, v: str | None) -> str | None:
        return _validate_emoji(v)

    @field_validator("description")
    @classmethod
    def _check_description(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_description(v)


class ProjectUpdateDto(BaseModel):
    """Partial update payload.

    Several fields use the ``UNSET`` sentinel as their default so callers
    can distinguish 'field omitted' from 'explicit null clears the field'.
    Mindspace adds ``knowledge_library_ids`` and aligns ``description`` to
    the same pattern.
    """

    model_config = {"arbitrary_types_allowed": True}

    title: str | None = None
    emoji: str | None | _Unset = Field(default=UNSET)
    description: str | None | _Unset = Field(default=UNSET)
    nsfw: bool | None = None
    knowledge_library_ids: list[str] | _Unset = Field(default=UNSET)
    system_prompt: str | None | _Unset = Field(default=UNSET)

    @field_validator("title")
    @classmethod
    def _check_title(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_title(v)

    @field_validator("emoji")
    @classmethod
    def _check_emoji(cls, v: Any) -> Any:
        if isinstance(v, _Unset) or v is None:
            return v
        return _validate_emoji(v)

    @field_validator("description")
    @classmethod
    def _check_description(cls, v: Any) -> Any:
        if isinstance(v, _Unset) or v is None:
            return v
        return _validate_description(v)

    @field_validator("system_prompt")
    @classmethod
    def _check_system_prompt(cls, v: Any) -> Any:
        if isinstance(v, _Unset) or v is None:
            return v
        return v


class ProjectUsageDto(BaseModel):
    """Per-project usage counts surfaced by ``GET /api/projects/{id}?include_usage=true``.

    Used by the delete-modal to show what a full-purge would remove.
    Counts default to zero so callers can rely on the shape regardless
    of how empty a project is.
    """

    chat_count: int = 0
    upload_count: int = 0
    artefact_count: int = 0
    image_count: int = 0


class ProjectPinnedDto(BaseModel):
    """Body for ``PATCH /api/projects/{id}/pinned``."""

    pinned: bool

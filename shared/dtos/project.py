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
    description: str
    nsfw: bool
    pinned: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


class ProjectCreateDto(BaseModel):
    title: str
    emoji: str | None = None
    description: str = ""
    nsfw: bool = False

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
    def _check_description(cls, v: str) -> str:
        return _validate_description(v)


class ProjectUpdateDto(BaseModel):
    """Partial update payload.

    `emoji` uses the `UNSET` sentinel as its default so that callers can
    distinguish 'field omitted' from 'explicit null clears the emoji'.
    """

    model_config = {"arbitrary_types_allowed": True}

    title: str | None = None
    emoji: str | None | _Unset = Field(default=UNSET)
    description: str | None = None
    nsfw: bool | None = None

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
    def _check_description(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_description(v)

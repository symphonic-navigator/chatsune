"""DTOs for image generation: group configs, generation results, message refs."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field


# --- per-group typed configs (discriminated union via group_id) -----------

class XaiImagineConfig(BaseModel):
    group_id: Literal["xai_imagine"] = "xai_imagine"
    tier: Literal["normal", "pro"] = "normal"
    resolution: Literal["1k", "2k"] = "1k"
    aspect: Literal["1:1", "16:9", "9:16", "4:3", "3:4"] = "1:1"
    n: int = Field(4, ge=1, le=10)


# Future image groups (Seedream, FLUX, etc.) extend this union.
ImageGroupConfig = Annotated[
    XaiImagineConfig,
    Field(discriminator="group_id"),
]


# --- generation result items (per-image; discriminated by kind) ----------

class GeneratedImageResult(BaseModel):
    kind: Literal["image"] = "image"
    id: str
    width: int
    height: int
    model_id: str
    description: str | None = None  # Phase II hook (vision-derived caption)


class ModeratedRejection(BaseModel):
    kind: Literal["moderated"] = "moderated"
    reason: str | None = None


ImageGenItem = Annotated[
    GeneratedImageResult | ModeratedRejection,
    Field(discriminator="kind"),
]


# --- message-level reference (rendered inline under assistant message) ----

class ImageRefDto(BaseModel):
    id: str
    blob_url: str
    thumb_url: str
    width: int
    height: int
    prompt: str
    model_id: str
    tool_call_id: str


# --- gallery REST DTOs ----------------------------------------------------

class GeneratedImageSummaryDto(BaseModel):
    id: str
    thumb_url: str
    width: int
    height: int
    prompt: str
    model_id: str
    generated_at: datetime


class GeneratedImageDetailDto(GeneratedImageSummaryDto):
    blob_url: str
    config_snapshot: dict
    connection_id: str
    group_id: str


# --- discovery DTO for /api/images/config GET ----------------------------

class ConnectionImageGroupsDto(BaseModel):
    connection_id: str
    connection_display_name: str
    group_ids: list[str]


class ActiveImageConfigDto(BaseModel):
    connection_id: str
    group_id: str
    config: dict

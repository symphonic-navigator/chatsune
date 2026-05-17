"""DTOs for image generation: group configs, generation results, message refs."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# --- per-group typed configs (discriminated union via group_id) -----------

class XaiImagineConfig(BaseModel):
    group_id: Literal["xai_imagine"] = "xai_imagine"
    tier: Literal["normal", "quality"] = "normal"
    resolution: Literal["1k", "2k"] = "1k"
    aspect: Literal["1:1", "16:9", "9:16", "4:3", "3:4"] = "1:1"
    n: int = Field(4, ge=1, le=10)

    @field_validator("tier", mode="before")
    @classmethod
    def _alias_pro_to_quality(cls, v):
        # Lazy migration for legacy persisted configs (xAI deprecated
        # the "pro" image slug on 2026-05-15).
        return "quality" if v == "pro" else v


class ZImageConfig(BaseModel):
    group_id: Literal["nano_gpt_zimage"] = "nano_gpt_zimage"
    model: Literal["turbo", "base"] = "turbo"
    size: Literal[
        "256x256", "512x512", "768x768",
        "1024x1024",
        "1280x720", "720x1280",
        "1536x1024", "1024x1536",
        "1536x1536",
    ] = "1024x1024"
    n: int = Field(4, ge=1, le=10)

    @model_validator(mode="after")
    def _cap_base_n(self) -> "ZImageConfig":
        # Z-Image-Base is ~10x slower than Turbo (43 s vs 4 s at 1024² in the
        # 2026-05-17 spike). Cap n at 4 for Base so the worst-case wait stays
        # under ~3 minutes.
        if self.model == "base" and self.n > 4:
            self.n = 4
        return self


class SeedreamConfig(BaseModel):
    group_id: Literal["nano_gpt_seedream"] = "nano_gpt_seedream"
    aspect: Literal[
        "1:1", "16:9", "9:16",
        "4:3", "3:4",
        "3:2", "2:3",
    ] = "1:1"
    quality: Literal["standard", "high", "ultra"] = "standard"
    n: int = Field(1, ge=1, le=4)


ImageGroupConfig = Annotated[
    XaiImagineConfig | ZImageConfig | SeedreamConfig,
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
    # In-process handoff from adapter to ImageService. Never serialised —
    # the BlobStore is the durable home for image bytes.
    data: bytes | None = Field(default=None, exclude=True)
    content_type: str | None = Field(default=None, exclude=True)


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
    # Inline thumbnail bytes so <img> tags work without an auth header
    # (the API uses Bearer JWT, which browsers cannot attach to <img>
    # subresource requests). Mirrors storage's StorageFileDto pattern.
    # Always JPEG when present.
    thumbnail_b64: str | None = None


# --- gallery REST DTOs ----------------------------------------------------

class GeneratedImageSummaryDto(BaseModel):
    id: str
    thumb_url: str
    width: int
    height: int
    prompt: str
    model_id: str
    generated_at: datetime
    # See ImageRefDto.thumbnail_b64.
    thumbnail_b64: str | None = None


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

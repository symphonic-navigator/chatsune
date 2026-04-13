from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from shared.dtos.mcp import PersonaMcpConfig

ChakraColour = Literal[
    "root", "sacral", "solar", "heart", "throat", "third_eye", "crown"
]


class ProfileCropDto(BaseModel):
    x: float = 0
    y: float = 0
    zoom: float = 1.0
    width: int = 0
    height: int = 0


class VoiceConfigDto(BaseModel):
    dialogue_voice: str | None = None
    narrator_voice: str | None = None
    auto_read: bool = False
    roleplay_mode: bool = False


class PersonaDto(BaseModel):
    id: str
    user_id: str
    name: str
    tagline: str
    model_unique_id: str
    system_prompt: str
    temperature: float = Field(ge=0.0, le=2.0)
    reasoning_enabled: bool
    soft_cot_enabled: bool = False
    vision_fallback_model: str | None = None
    nsfw: bool
    colour_scheme: ChakraColour
    display_order: int
    monogram: str
    pinned: bool
    profile_image: str | None
    profile_crop: ProfileCropDto | None = None
    mcp_config: PersonaMcpConfig | None = None
    integrations_config: dict | None = None
    voice_config: VoiceConfigDto | None = None
    created_at: datetime
    updated_at: datetime


class CreatePersonaDto(BaseModel):
    name: str
    tagline: str
    model_unique_id: str
    system_prompt: str
    temperature: float = Field(default=0.8, ge=0.0, le=2.0)
    reasoning_enabled: bool = False
    soft_cot_enabled: bool = False
    vision_fallback_model: str | None = None
    nsfw: bool = False
    colour_scheme: ChakraColour = "solar"
    display_order: int = 0
    pinned: bool = False
    profile_image: str | None = None
    voice_config: VoiceConfigDto | None = None


class ReorderPersonasDto(BaseModel):
    ordered_ids: list[str]


class UpdatePersonaDto(BaseModel):
    name: str | None = None
    tagline: str | None = None
    model_unique_id: str | None = None
    system_prompt: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    reasoning_enabled: bool | None = None
    soft_cot_enabled: bool | None = None
    vision_fallback_model: str | None = None
    nsfw: bool | None = None
    colour_scheme: ChakraColour | None = None
    display_order: int | None = None
    pinned: bool | None = None
    profile_image: str | None = None
    profile_crop: ProfileCropDto | None = None
    mcp_config: PersonaMcpConfig | None = None
    integrations_config: dict | None = None
    voice_config: VoiceConfigDto | None = None

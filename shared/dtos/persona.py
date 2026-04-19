from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

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
    narrator_mode: Literal["off", "play", "narrate"] = "off"
    # Post-synthesis modulation applied client-side via SoundTouch.
    dialogue_speed: float = Field(default=1.0, ge=0.75, le=1.5)
    dialogue_pitch: int = Field(default=0, ge=-6, le=6)
    narrator_speed: float = Field(default=1.0, ge=0.75, le=1.5)
    narrator_pitch: int = Field(default=0, ge=-6, le=6)
    # Which TTS integration should speak for this persona. ``None`` means
    # "use the first enabled TTS provider" — the resolver applies the
    # fallback. Stored as a loose key so existing documents without this
    # field deserialise unchanged.
    tts_provider_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _translate_legacy_roleplay_mode(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        if "narrator_mode" in data:
            data.pop("roleplay_mode", None)
            return data
        legacy = data.pop("roleplay_mode", None)
        if legacy is True:
            data["narrator_mode"] = "play"
        elif legacy is False:
            data["narrator_mode"] = "off"
        return data


class PersonaDto(BaseModel):
    id: str
    user_id: str
    name: str
    tagline: str
    # ``None`` after the connections-refactor migration nulled stale IDs, or
    # after a connection delete unwired this persona. The Persona stays
    # listable so the user can pick a fresh model — see INS-019.
    model_unique_id: str | None = None
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
    integration_configs: dict[str, dict] = Field(default_factory=dict)
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
    integration_configs: dict[str, dict] = Field(default_factory=dict)
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
    integration_configs: dict[str, dict] | None = None
    voice_config: VoiceConfigDto | None = None

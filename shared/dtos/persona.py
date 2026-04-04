from datetime import datetime

from pydantic import BaseModel, Field


class PersonaDto(BaseModel):
    id: str
    user_id: str
    name: str
    tagline: str
    model_unique_id: str
    system_prompt: str
    temperature: float = Field(ge=0.0, le=2.0)
    reasoning_enabled: bool
    nsfw: bool
    colour_scheme: str
    display_order: int
    created_at: datetime
    updated_at: datetime


class CreatePersonaDto(BaseModel):
    name: str
    tagline: str
    model_unique_id: str
    system_prompt: str
    temperature: float = Field(default=0.8, ge=0.0, le=2.0)
    reasoning_enabled: bool = False
    nsfw: bool = False
    colour_scheme: str = ""
    display_order: int = 0


class UpdatePersonaDto(BaseModel):
    name: str | None = None
    tagline: str | None = None
    model_unique_id: str | None = None
    system_prompt: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    reasoning_enabled: bool | None = None
    nsfw: bool | None = None
    colour_scheme: str | None = None
    display_order: int | None = None

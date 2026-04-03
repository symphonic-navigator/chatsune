from datetime import datetime

from pydantic import BaseModel


class PersonaDto(BaseModel):
    id: str
    user_id: str
    name: str
    tagline: str
    model_unique_id: str
    system_prompt: str
    temperature: float
    reasoning_enabled: bool
    colour_scheme: str
    display_order: int
    created_at: datetime
    updated_at: datetime


class CreatePersonaDto(BaseModel):
    name: str
    tagline: str
    model_unique_id: str
    system_prompt: str
    temperature: float = 0.8
    reasoning_enabled: bool = False
    colour_scheme: str = ""
    display_order: int = 0


class UpdatePersonaDto(BaseModel):
    name: str | None = None
    tagline: str | None = None
    model_unique_id: str | None = None
    system_prompt: str | None = None
    temperature: float | None = None
    reasoning_enabled: bool | None = None
    colour_scheme: str | None = None
    display_order: int | None = None

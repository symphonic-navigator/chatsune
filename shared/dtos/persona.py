from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ChakraColour = Literal[
    "root", "sacral", "solar", "heart", "throat", "third_eye", "crown"
]


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
    colour_scheme: ChakraColour
    display_order: int
    monogram: str
    pinned: bool
    profile_image: str | None
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
    colour_scheme: ChakraColour = "solar"
    display_order: int = 0
    pinned: bool = False
    profile_image: str | None = None


class UpdatePersonaDto(BaseModel):
    name: str | None = None
    tagline: str | None = None
    model_unique_id: str | None = None
    system_prompt: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    reasoning_enabled: bool | None = None
    nsfw: bool | None = None
    colour_scheme: ChakraColour | None = None
    display_order: int | None = None
    pinned: bool | None = None
    profile_image: str | None = None

from datetime import datetime

from pydantic import BaseModel, Field


class PersonaDocument(BaseModel):
    """Internal MongoDB document model for personas. Never expose outside persona module."""

    id: str = Field(alias="_id")
    user_id: str
    name: str
    tagline: str
    model_unique_id: str
    system_prompt: str
    temperature: float
    reasoning_enabled: bool
    nsfw: bool
    colour_scheme: str
    display_order: int
    monogram: str
    pinned: bool
    profile_image: str | None
    profile_crop: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}

from datetime import datetime

from pydantic import BaseModel, Field


class UserCredentialDocument(BaseModel):
    """Internal MongoDB document model for LLM user credentials. Never expose outside llm module."""

    id: str = Field(alias="_id")
    user_id: str
    provider_id: str
    api_key_encrypted: str  # Fernet-encrypted; never returned via API
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}


class ModelCurationDocument(BaseModel):
    """Internal MongoDB document for admin model curation. Never expose outside llm module."""

    id: str = Field(alias="_id")
    provider_id: str
    model_slug: str
    overall_rating: str
    hidden: bool
    admin_description: str | None
    last_curated_at: datetime
    last_curated_by: str

    model_config = {"populate_by_name": True}

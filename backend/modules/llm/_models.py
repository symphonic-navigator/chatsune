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

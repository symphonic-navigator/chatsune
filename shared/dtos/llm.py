from datetime import datetime

from pydantic import BaseModel


class ProviderCredentialDto(BaseModel):
    provider_id: str
    display_name: str
    is_configured: bool
    created_at: datetime | None = None


class SetProviderKeyDto(BaseModel):
    api_key: str


class ModelMetaDto(BaseModel):
    provider_id: str
    model_id: str
    display_name: str
    context_window: int
    supports_reasoning: bool
    supports_vision: bool
    supports_tool_calls: bool

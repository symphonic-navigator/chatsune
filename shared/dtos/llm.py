from datetime import datetime
from enum import Enum

from pydantic import BaseModel, computed_field


class ProviderCredentialDto(BaseModel):
    provider_id: str
    display_name: str
    is_configured: bool
    created_at: datetime | None = None


class SetProviderKeyDto(BaseModel):
    api_key: str


class ModelRating(str, Enum):
    AVAILABLE = "available"
    RECOMMENDED = "recommended"
    NOT_RECOMMENDED = "not_recommended"


class ModelCurationDto(BaseModel):
    overall_rating: ModelRating = ModelRating.AVAILABLE
    hidden: bool = False
    admin_description: str | None = None
    last_curated_at: datetime | None = None
    last_curated_by: str | None = None


class SetModelCurationDto(BaseModel):
    overall_rating: ModelRating = ModelRating.AVAILABLE
    hidden: bool = False
    admin_description: str | None = None


class ModelMetaDto(BaseModel):
    provider_id: str
    model_id: str
    display_name: str
    context_window: int
    supports_reasoning: bool
    supports_vision: bool
    supports_tool_calls: bool
    parameter_count: str | None = None
    quantisation_level: str | None = None
    curation: ModelCurationDto | None = None

    @computed_field
    @property
    def unique_id(self) -> str:
        return f"{self.provider_id}:{self.model_id}"


class UserModelConfigDto(BaseModel):
    model_unique_id: str
    is_favourite: bool = False
    is_hidden: bool = False
    notes: str | None = None
    system_prompt_addition: str | None = None


class SetUserModelConfigDto(BaseModel):
    is_favourite: bool | None = None
    is_hidden: bool | None = None
    notes: str | None = None
    system_prompt_addition: str | None = None

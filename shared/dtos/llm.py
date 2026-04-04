from datetime import datetime
from enum import Enum

from pydantic import BaseModel, computed_field, field_validator, model_validator


class ProviderCredentialDto(BaseModel):
    provider_id: str
    display_name: str
    is_configured: bool
    requires_key_for_listing: bool = True
    test_status: str | None = None        # "untested" | "valid" | "failed" | None (not configured)
    last_test_error: str | None = None
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
    provider_display_name: str = ""
    model_id: str
    display_name: str
    context_window: int
    supports_reasoning: bool
    supports_vision: bool
    supports_tool_calls: bool
    parameter_count: str | None = None
    raw_parameter_count: int | None = None
    quantisation_level: str | None = None
    curation: ModelCurationDto | None = None

    @model_validator(mode="after")
    def _fill_provider_display_name(self) -> "ModelMetaDto":
        if not self.provider_display_name:
            self.provider_display_name = self.provider_id
        return self

    @computed_field
    @property
    def unique_id(self) -> str:
        return f"{self.provider_id}:{self.model_id}"


class FaultyProviderDto(BaseModel):
    provider_id: str
    display_name: str
    error_message: str


class UserModelConfigDto(BaseModel):
    model_unique_id: str
    is_favourite: bool = False
    is_hidden: bool = False
    custom_display_name: str | None = None
    custom_context_window: int | None = None
    notes: str | None = None
    system_prompt_addition: str | None = None


class SetUserModelConfigDto(BaseModel):
    is_favourite: bool | None = None
    is_hidden: bool | None = None
    custom_display_name: str | None = None
    custom_context_window: int | None = None
    notes: str | None = None
    system_prompt_addition: str | None = None

    @field_validator("custom_display_name")
    @classmethod
    def validate_display_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if len(v) == 0:
            return None
        if len(v) > 100:
            raise ValueError("custom_display_name must be 100 characters or fewer")
        return v

    @field_validator("custom_context_window")
    @classmethod
    def validate_context_window(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if v < 96_000:
            raise ValueError("custom_context_window must be at least 96000")
        return v

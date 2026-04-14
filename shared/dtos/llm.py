from pydantic import BaseModel, computed_field, field_validator


class ModelMetaDto(BaseModel):
    connection_id: str
    connection_display_name: str = ""
    model_id: str
    display_name: str
    context_window: int
    supports_reasoning: bool
    supports_vision: bool
    supports_tool_calls: bool
    parameter_count: str | None = None
    raw_parameter_count: int | None = None
    quantisation_level: str | None = None

    @computed_field
    @property
    def unique_id(self) -> str:
        return f"{self.connection_id}:{self.model_id}"


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


class AdapterTemplateDto(BaseModel):
    id: str
    display_name: str
    slug_prefix: str
    config_defaults: dict


class AdapterDto(BaseModel):
    adapter_type: str
    display_name: str
    view_id: str
    templates: list[AdapterTemplateDto]
    config_schema: list[dict]
    secret_fields: list[str]


class ConnectionDto(BaseModel):
    id: str
    user_id: str
    adapter_type: str
    display_name: str
    slug: str
    config: dict
    last_test_status: str | None = None
    last_test_error: str | None = None
    last_test_at: str | None = None
    created_at: str
    updated_at: str


class CreateConnectionDto(BaseModel):
    adapter_type: str
    display_name: str
    slug: str
    config: dict


class UpdateConnectionDto(BaseModel):
    display_name: str | None = None
    slug: str | None = None
    config: dict | None = None

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field, field_validator


class ModelMetaDto(BaseModel):
    connection_id: str
    connection_slug: str = ""  # populated by adapters once Task 2 lands
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
        return f"{self.connection_slug}:{self.model_id}"


class UserModelConfigDto(BaseModel):
    model_unique_id: str
    is_favourite: bool = False
    is_hidden: bool = False
    custom_display_name: str | None = None
    custom_context_window: int | None = None
    # Override for upstream-reported reasoning capability. Primary use case:
    # community/homelab sidecars that don't yet detect every thinker family.
    # ``None`` = respect upstream. ``True``/``False`` = force the flag.
    custom_supports_reasoning: bool | None = None
    notes: str | None = None
    system_prompt_addition: str | None = None


class SetUserModelConfigDto(BaseModel):
    is_favourite: bool | None = None
    is_hidden: bool | None = None
    custom_display_name: str | None = None
    custom_context_window: int | None = None
    custom_supports_reasoning: bool | None = None
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
        if v < 80_000:
            raise ValueError("custom_context_window must be at least 80000")
        return v


class AdapterTemplateDto(BaseModel):
    id: str
    display_name: str
    slug_prefix: str
    config_defaults: dict[str, Any]
    required_config_fields: list[str] = Field(default_factory=list)


class AdapterDto(BaseModel):
    adapter_type: str
    display_name: str
    view_id: str
    templates: list[AdapterTemplateDto]
    config_schema: list[dict[str, Any]]
    secret_fields: list[str]


class ConnectionDto(BaseModel):
    id: str
    user_id: str
    adapter_type: str
    display_name: str
    slug: str
    config: dict[str, Any]
    last_test_status: Literal["untested", "valid", "failed"] | None = None
    last_test_error: str | None = None
    last_test_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CreateConnectionDto(BaseModel):
    adapter_type: str
    display_name: str
    slug: str
    config: dict[str, Any]


class UpdateConnectionDto(BaseModel):
    display_name: str | None = None
    slug: str | None = None
    config: dict[str, Any] | None = None


# --- Community Provisioning ---


class HomelabEngineInfoDto(BaseModel):
    type: str
    version: str | None = None


class HomelabDto(BaseModel):
    homelab_id: str
    display_name: str
    host_key_hint: str
    status: Literal["active", "revoked"]
    created_at: datetime
    last_seen_at: datetime | None = None
    last_sidecar_version: str | None = None
    last_engine_info: HomelabEngineInfoDto | None = None
    is_online: bool = False


class HomelabCreatedDto(HomelabDto):
    plaintext_host_key: str = Field(
        ..., description="Shown exactly once; never returned again."
    )


class HomelabHostKeyRegeneratedDto(HomelabDto):
    plaintext_host_key: str = Field(
        ..., description="Shown exactly once; never returned again."
    )


class HomelabStatusDto(BaseModel):
    """Lightweight connection-status snapshot.

    Emitted alongside ``llm.homelab.status_changed`` / ``llm.homelab.last_seen``
    when Plan 3 (CSP sidecar) updates a homelab's live state without needing
    to re-send the full :class:`HomelabDto`.
    """

    homelab_id: str
    is_online: bool
    last_seen_at: datetime | None = None
    last_sidecar_version: str | None = None
    last_engine_info: HomelabEngineInfoDto | None = None


class CreateHomelabDto(BaseModel):
    display_name: str

    @field_validator("display_name")
    @classmethod
    def _name_len(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("display_name must not be empty")
        if len(v) > 80:
            raise ValueError("display_name must be 80 characters or fewer")
        return v


class UpdateHomelabDto(BaseModel):
    display_name: str | None = None

    @field_validator("display_name")
    @classmethod
    def _name_len(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("display_name must not be empty")
        if len(v) > 80:
            raise ValueError("display_name must be 80 characters or fewer")
        return v


class ApiKeyDto(BaseModel):
    api_key_id: str
    homelab_id: str
    display_name: str
    api_key_hint: str
    allowed_model_slugs: list[str]
    status: Literal["active", "revoked"]
    created_at: datetime
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None


class ApiKeyCreatedDto(ApiKeyDto):
    plaintext_api_key: str = Field(
        ..., description="Shown exactly once; never returned again."
    )


class CreateApiKeyDto(BaseModel):
    display_name: str
    allowed_model_slugs: list[str] = Field(default_factory=list)

    @field_validator("display_name")
    @classmethod
    def _name_len(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("display_name must not be empty")
        if len(v) > 80:
            raise ValueError("display_name must be 80 characters or fewer")
        return v


class UpdateApiKeyDto(BaseModel):
    display_name: str | None = None
    allowed_model_slugs: list[str] | None = None

    @field_validator("display_name")
    @classmethod
    def _name_len(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("display_name must not be empty")
        if len(v) > 80:
            raise ValueError("display_name must be 80 characters or fewer")
        return v

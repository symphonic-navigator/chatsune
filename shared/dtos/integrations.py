from enum import Enum
from typing import Literal

from pydantic import BaseModel


class IntegrationCapability(str, Enum):
    TOOL_PROVIDER = "tool_provider"
    TTS_PROVIDER = "tts_provider"
    STT_PROVIDER = "stt_provider"
    TTS_EXPRESSIVE_MARKUP = "tts_expressive_markup"
    TTS_VOICE_CLONING = "tts_voice_cloning"


class OptionsSource(str, Enum):
    PLUGIN = "plugin"


class IntegrationConfigFieldDto(BaseModel):
    """Describes one user-configurable field for an integration."""
    key: str
    label: str
    field_type: Literal["text", "password", "number", "boolean", "select", "textarea"]
    placeholder: str = ""
    required: bool = True
    description: str = ""
    secret: bool = False
    options_source: str | None = None
    options: list[dict] = []


class IntegrationDefinitionDto(BaseModel):
    """Static definition of an available integration (from the registry)."""
    id: str
    display_name: str
    description: str
    icon: str
    execution_mode: Literal["frontend", "backend", "hybrid"]
    config_fields: list[IntegrationConfigFieldDto]
    has_tools: bool = False
    has_response_tags: bool = False
    has_prompt_extension: bool = False
    capabilities: list[str] = []
    persona_config_fields: list[IntegrationConfigFieldDto] = []
    # ``False`` means the integration is backend-proxied: secrets stay on
    # the server, no hydration event is emitted, and the plugin lifecycle
    # must not block activation on browser-side secret presence.
    hydrate_secrets: bool = True
    # When set, the api_key for this integration is sourced from the user's
    # Premium Provider Account with the given provider id (e.g. ``xai`` for
    # ``xai_voice``). The frontend uses this to hide the per-integration
    # api_key UI and redirect the user to the Providers tab instead.
    linked_premium_provider: str | None = None


class UserIntegrationConfigDto(BaseModel):
    """Per-user config for one integration (persisted in MongoDB)."""
    integration_id: str
    enabled: bool = False
    config: dict = {}


class PersonaIntegrationConfigDto(BaseModel):
    """Which integrations a persona has enabled."""
    enabled_integration_ids: list[str] = []

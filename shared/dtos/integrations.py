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
    """Per-user config for one integration (persisted in MongoDB).

    ``effective_enabled`` is a response-only derived flag that reflects
    ``effective_enabled_map()`` — True when the integration is actually
    usable. For unlinked integrations (e.g. ``lovense``) it tracks the
    stored ``enabled`` flag. For integrations linked to a Premium Provider
    Account (e.g. ``xai_voice`` → ``xai``), it is True whenever the user
    has a matching Premium account, regardless of the stored ``enabled``
    (which has no independent meaning for linked integrations). Frontend
    voice-provider dropdowns and engine-readiness checks should use this
    field — not the raw ``enabled`` — so linked integrations show up even
    when there is no ``user_integration_configs`` document for them.
    """
    integration_id: str
    enabled: bool = False
    config: dict = {}
    effective_enabled: bool = False


class PersonaIntegrationConfigDto(BaseModel):
    """Which integrations a persona has enabled."""
    enabled_integration_ids: list[str] = []

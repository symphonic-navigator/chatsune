from enum import Enum
from typing import Literal

from pydantic import BaseModel


class IntegrationCapability(str, Enum):
    TOOL_PROVIDER = "tool_provider"
    TTS_PROVIDER = "tts_provider"
    STT_PROVIDER = "stt_provider"


class OptionsSource(str, Enum):
    PLUGIN = "plugin"


class IntegrationConfigFieldDto(BaseModel):
    """Describes one user-configurable field for an integration."""
    key: str
    label: str
    field_type: Literal["text", "number", "boolean"]
    placeholder: str = ""
    required: bool = True
    description: str = ""


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


class UserIntegrationConfigDto(BaseModel):
    """Per-user config for one integration (persisted in MongoDB)."""
    integration_id: str
    enabled: bool = False
    config: dict = {}


class PersonaIntegrationConfigDto(BaseModel):
    """Which integrations a persona has enabled."""
    enabled_integration_ids: list[str] = []

"""Internal document models for the integrations module."""

from dataclasses import dataclass, field
from typing import Literal

from shared.dtos.inference import ToolDefinition
from shared.dtos.integrations import IntegrationCapability, OptionsSource  # noqa: F401 (OptionsSource)


@dataclass(frozen=True)
class IntegrationDefinition:
    """Static definition of an available integration."""
    id: str
    display_name: str
    description: str
    icon: str
    execution_mode: Literal["frontend", "backend", "hybrid"]
    config_fields: list[dict]
    capabilities: list[IntegrationCapability] = field(default_factory=list)
    hydrate_secrets: bool = True
    persona_config_fields: list[dict] = field(default_factory=list)
    system_prompt_template: str = ""
    response_tag_prefix: str = ""
    tool_definitions: list[ToolDefinition] = field(default_factory=list)
    tool_side: Literal["server", "client"] = "client"

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
    linked_premium_provider: str | None = None
    # When True, the integration participates in the per-persona allowlist:
    # it is only active for a chat session if the persona has explicitly
    # opted in via ``integrations_config.enabled_integration_ids``. This
    # gates tool-providing integrations (e.g. ``lovense``) so a fresh
    # persona doesn't expose unwanted tools by default. Non-assignable
    # integrations (e.g. voice providers) remain active whenever
    # user-enabled, regardless of the persona allowlist.
    assignable: bool = False

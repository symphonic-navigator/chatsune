"""Static registry of all known integrations.

Each integration is defined here with its metadata, config schema, tools,
and system prompt template. Plugins are registered at import time.
"""

import logging
from backend.modules.integrations._models import IntegrationDefinition
from shared.dtos.inference import ToolDefinition

_log = logging.getLogger(__name__)

_registry: dict[str, IntegrationDefinition] = {}


def register(definition: IntegrationDefinition) -> None:
    """Register an integration definition."""
    if definition.id in _registry:
        raise ValueError(f"Integration '{definition.id}' already registered")
    _registry[definition.id] = definition
    _log.info("Registered integration: %s", definition.id)


def get(integration_id: str) -> IntegrationDefinition | None:
    """Look up an integration by ID."""
    return _registry.get(integration_id)


def get_all() -> dict[str, IntegrationDefinition]:
    """Return all registered integrations."""
    return dict(_registry)


def _register_builtins() -> None:
    """Register built-in integrations. Called once at import time."""

    register(IntegrationDefinition(
        id="lovense",
        display_name="Lovense",
        description="Control Lovense toys via the Game Mode API on your local network.",
        icon="lovense",
        execution_mode="frontend",
        config_fields=[
            {
                "key": "ip",
                "label": "Phone IP Address",
                "field_type": "text",
                "placeholder": "192.168.0.92",
                "required": True,
                "description": "IP address of the phone running Lovense Remote.",
            },
        ],
        system_prompt_template=(
            '<integrations name="lovense">\n'
            "You have access to Lovense toy control. The user's Lovense Remote app "
            "is connected and you can control their toys.\n\n"
            "To send a command, write a tag in your response:\n"
            "  <lovense command toy strength duration>\n\n"
            "Available commands:\n"
            "  <lovense vibrate TOYNAME STRENGTH SECONDS> — vibrate (strength 1-20)\n"
            "  <lovense rotate TOYNAME STRENGTH SECONDS> — rotate (strength 1-20)\n"
            "  <lovense stop TOYNAME> — stop a specific toy\n"
            "  <lovense stopall> — stop all toys immediately\n\n"
            "TOYNAME is the toy's nickname from GetToys. STRENGTH is 1-20. "
            "SECONDS is duration (0 = indefinite until stopped).\n\n"
            "You can also use the lovense_get_toys tool to query connected toys.\n"
            "Be creative and responsive. Integrate toy control naturally into "
            "conversation — never make it feel mechanical.\n"
            "</integrations>"
        ),
        response_tag_prefix="lovense",
        tool_definitions=[
            ToolDefinition(
                name="lovense_get_toys",
                description="Query connected Lovense toys. Returns toy names, types, and status.",
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
        ],
        tool_side="client",
    ))


_register_builtins()

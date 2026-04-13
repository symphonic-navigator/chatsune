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
            "## Inline tags\n"
            "Write tags in your response to control toys:\n\n"
            "  <lovense TOYNAME ACTION STRENGTH [SECONDS] [loop RUN PAUSE] [layer]>\n"
            "  <lovense TOYNAME stroke STROKE_POS THRUST_STRENGTH [SECONDS]>\n"
            "  <lovense TOYNAME stop>\n"
            "  <lovense stopall>\n\n"
            "Available actions (strength 0-20 unless noted):\n"
            "  vibrate, rotate, thrusting, fingering, suction, oscillate, all\n"
            "  pump (0-3), depth (0-3)\n"
            "  stroke POSITION(0-100) THRUST(0-20) — combined pattern (20-point gap required)\n\n"
            "Modifiers:\n"
            "  SECONDS — duration (omit or 0 = indefinite until stopped)\n"
            "  loop RUN PAUSE — pulsing pattern (both >1 second)\n"
            "  layer — add to running actions instead of replacing them\n\n"
            "Examples:\n"
            "  <lovense nova vibrate 10 5>           — vibrate at 10 for 5s\n"
            "  <lovense nova vibrate 8 30 loop 3 2>  — pulse: 3s on, 2s pause, 30s total\n"
            "  <lovense nova rotate 12 5 layer>       — add rotation on top of vibration\n"
            "  <lovense nova stroke 50 10 5>          — stroke pattern for 5s\n"
            "  <lovense stopall>                      — emergency stop\n\n"
            "## Tools\n"
            "Use lovense_get_toys to discover connected toys before controlling them.\n"
            "Use lovense_control for programmatic control with full parameters.\n\n"
            "TOYNAME is the toy's name from GetToys (e.g. 'nora'). Use names, not IDs.\n"
            "Be creative and responsive. Integrate control naturally — never mechanical.\n"
            "</integrations>"
        ),
        response_tag_prefix="lovense",
        tool_definitions=[
            ToolDefinition(
                name="lovense_get_toys",
                description="Query connected Lovense toys. Returns names, capabilities, battery, and online status.",
                parameters={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
            ToolDefinition(
                name="lovense_control",
                description=(
                    "Send a function command to a Lovense toy. "
                    "Actions: Vibrate, Rotate, Pump, Thrusting, Fingering, Suction, Depth, Oscillate, All, Stop, Stroke. "
                    "Strength 0-20 (Pump/Depth: 0-3). "
                    "For Stroke: set stroke_position (0-100) and strength is for thrusting (must differ by 20+)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "The function to execute (e.g. Vibrate, Rotate, Stop, Stroke)",
                        },
                        "toy": {
                            "type": "string",
                            "description": "Toy name from GetToys. Omit to target all toys.",
                        },
                        "strength": {
                            "type": "integer",
                            "description": "Intensity level (0-20, or 0-3 for Pump/Depth)",
                        },
                        "time_sec": {
                            "type": "number",
                            "description": "Duration in seconds (0 = indefinite)",
                        },
                        "stroke_position": {
                            "type": "integer",
                            "description": "Stroke position 0-100 (only for Stroke action)",
                        },
                        "loop_running_sec": {
                            "type": "number",
                            "description": "Active cycle duration for pulsing (>1 second)",
                        },
                        "loop_pause_sec": {
                            "type": "number",
                            "description": "Pause cycle duration for pulsing (>1 second)",
                        },
                        "layer": {
                            "type": "boolean",
                            "description": "If true, add to running actions instead of replacing them",
                        },
                    },
                    "required": ["action"],
                },
            ),
        ],
        tool_side="client",
    ))


_register_builtins()

"""Static registry of all known integrations.

Each integration is defined here with its metadata, config schema, tools,
and system prompt template. Plugins are registered at import time.
"""

import logging
from backend.modules.integrations._models import IntegrationDefinition
from backend.modules.integrations._screen_effects_prompt import SCREEN_EFFECT_PROMPT
from backend.modules.integrations._voice_expression_tags import build_system_prompt_extension
from shared.dtos.inference import ToolDefinition
from shared.dtos.integrations import IntegrationCapability, OptionsSource

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
        capabilities=[IntegrationCapability.TOOL_PROVIDER],
        system_prompt_template=(
            '<integrations name="lovense">\n'
            "## Lovense Integration\n\n"
            "You can control the user's Lovense toys in real time. The user has the "
            "Lovense Remote app running on their phone, and their toys are connected "
            "via local network.\n\n"
            "**Workflow:**\n"
            "1. At the start of a session (or when you're unsure what's connected), "
            "call the `lovense_get_toys` tool to discover available toys, their "
            "capabilities, battery level, and online status.\n"
            "2. Once you know the toy names and what they support, you can control "
            "them either via tool calls or via inline tags in your response.\n"
            "3. Always use the toy **name** (e.g. 'nora', 'hush'), never the hardware ID.\n"
            "4. Be creative and responsive — weave toy control naturally into the "
            "conversation. Never make it feel mechanical or list-like.\n\n"
            "### How to invoke\n\n"
            "**Option A — Tool calls** (best when you need to check the result or "
            "chain actions programmatically):\n\n"
            "- `lovense_get_toys` — discover connected toys, their capabilities and status\n"
            "- `lovense_control` — send a command with structured parameters:\n"
            "  - `action`: Vibrate, Rotate, Pump, Thrusting, Fingering, Suction, "
            "Depth, Oscillate, All, Stop, Stroke\n"
            "  - `toy`: toy name (omit to target all toys)\n"
            "  - `strength`: 0-20 (Pump/Depth: 0-3)\n"
            "  - `time_sec`: duration in seconds (0 = indefinite)\n"
            "  - `loop_running_sec` / `loop_pause_sec`: pulsing pattern (both >1s)\n"
            "  - `layer`: true to add on top of running actions instead of replacing\n"
            "  - `stroke_position`: 0-100 (only for Stroke, must differ from strength by 20+)\n\n"
            "**Option B — Inline tags** (best for spontaneous, conversational control — "
            "the tag is executed and replaced with a subtle italic confirmation in "
            "your response):\n\n"
            "Format: `<lovense TOYNAME ACTION STRENGTH [SECONDS] [loop RUN PAUSE] [layer]>`\n\n"
            "Actions and strength ranges:\n"
            "  vibrate, rotate, thrusting, fingering, suction, oscillate, all (0-20)\n"
            "  pump, depth (0-3)\n\n"
            "Special forms:\n"
            "  `<lovense TOYNAME stroke POSITION THRUST_STRENGTH [SECONDS]>` — combined stroke pattern\n"
            "  `<lovense TOYNAME stop>` — stop one toy\n"
            "  `<lovense stopall>` — stop all toys immediately (emergency stop)\n\n"
            "Modifiers (append after SECONDS):\n"
            "  `loop RUN PAUSE` — pulsing: RUN seconds active, PAUSE seconds rest, repeating\n"
            "  `layer` — add to currently running actions instead of replacing them\n\n"
            "Examples:\n"
            "  `<lovense nora vibrate 10 5>` — vibrate nora at 10 for 5 seconds\n"
            "  `<lovense nora vibrate 8 30 loop 3 2>` — pulse: 3s on, 2s pause, 30s total\n"
            "  `<lovense nora rotate 12 5 layer>` — layer rotation on top of vibration\n"
            "  `<lovense nora stroke 50 10 5>` — stroke pattern for 5 seconds\n"
            "  `<lovense stopall>` — emergency stop all toys\n"
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
        assignable=True,
    ))

    register(IntegrationDefinition(
        id="mistral_voice",
        display_name="Mistral Voice",
        description="Speech-to-text and text-to-speech via Mistral AI. Bring your own API key.",
        icon="mistral",
        execution_mode="hybrid",
        hydrate_secrets=False,
        capabilities=[
            IntegrationCapability.TTS_PROVIDER,
            IntegrationCapability.STT_PROVIDER,
            IntegrationCapability.TTS_VOICE_CLONING,
        ],
        linked_premium_provider="mistral",
        config_fields=[
            {
                "key": "playback_gap_ms",
                "label": "Pause between chunks",
                "field_type": "select",
                "required": False,
                "description": "Gap inserted between sentences and speaker switches. Mistral TTS produces crisp boundaries — a small pause sounds more natural.",
                "options": [
                    {"value": "100", "label": "100 ms"},
                    {"value": "200", "label": "200 ms"},
                    {"value": "300", "label": "300 ms"},
                    {"value": "400", "label": "400 ms"},
                    {"value": "500", "label": "500 ms (default)"},
                    {"value": "600", "label": "600 ms"},
                    {"value": "700", "label": "700 ms"},
                    {"value": "800", "label": "800 ms"},
                ],
            },
        ],
        persona_config_fields=[
            {
                "key": "voice_id",
                "label": "Voice",
                "field_type": "select",
                "options_source": OptionsSource.PLUGIN,
                "required": True,
                "description": "Voice used when this persona speaks.",
            },
            {
                "key": "narrator_voice_id",
                "label": "Narrator Voice",
                "field_type": "select",
                "options_source": OptionsSource.PLUGIN,
                "required": False,
                "description": "Voice used for narration / prose when narrator mode is active. Leave at 'Inherit' to use the primary voice.",
            },
        ],
        tool_definitions=[],
    ))

    register(IntegrationDefinition(
        id="xai_voice",
        display_name="xAI Voice",
        description="Speech-to-text and text-to-speech via xAI. Bring your own API key.",
        icon="xai",
        execution_mode="hybrid",
        hydrate_secrets=False,
        system_prompt_template=build_system_prompt_extension(),
        capabilities=[
            IntegrationCapability.TTS_PROVIDER,
            IntegrationCapability.STT_PROVIDER,
            IntegrationCapability.TTS_EXPRESSIVE_MARKUP,
        ],
        linked_premium_provider="xai",
        config_fields=[
            {
                "key": "playback_gap_ms",
                "label": "Pause between chunks",
                "field_type": "select",
                "required": False,
                "description": (
                    "Gap inserted between sentences and speaker switches. "
                    "xAI already leaves a natural silence at sentence ends, "
                    "so no extra gap is needed by default."
                ),
                "options": [
                    {"value": "0", "label": "0 ms (default)"},
                    {"value": "100", "label": "100 ms"},
                    {"value": "200", "label": "200 ms"},
                    {"value": "300", "label": "300 ms"},
                    {"value": "400", "label": "400 ms"},
                    {"value": "500", "label": "500 ms"},
                    {"value": "600", "label": "600 ms"},
                    {"value": "700", "label": "700 ms"},
                    {"value": "800", "label": "800 ms"},
                ],
            },
        ],
        persona_config_fields=[
            {
                "key": "voice_id",
                "label": "Voice",
                "field_type": "select",
                "options_source": OptionsSource.PLUGIN,
                "required": True,
                "description": "Voice used when this persona speaks.",
            },
            {
                "key": "narrator_voice_id",
                "label": "Narrator Voice",
                "field_type": "select",
                "options_source": OptionsSource.PLUGIN,
                "required": False,
                "description": (
                    "Voice used for narration / prose when narrator mode "
                    "is active. Leave at 'Inherit' to use the primary voice."
                ),
            },
        ],
        tool_definitions=[],
    ))

    register(IntegrationDefinition(
        id="screen_effect",
        display_name="Screen Effects",
        description="Visual inline flourishes the persona drops over the screen.",
        icon="sparkles",
        execution_mode="frontend",
        config_fields=[],
        capabilities=[],
        system_prompt_template=SCREEN_EFFECT_PROMPT,
        response_tag_prefix="screen_effect",
        tool_definitions=[],
        default_enabled=True,
        assignable=False,
    ))


_register_builtins()


def _register_builtin_voice_adapters() -> None:
    """Register voice adapters for backend-proxied integrations.

    Must be called AFTER the voice HTTP client is initialised (see
    backend/modules/integrations/_voice_adapters/_client.py).
    """
    from backend.modules.integrations._voice_adapters import register_adapter
    from backend.modules.integrations._voice_adapters._client import get_voice_http_client
    from backend.modules.integrations._voice_adapters._mistral import MistralVoiceAdapter
    from backend.modules.integrations._voice_adapters._xai import XaiVoiceAdapter
    register_adapter("xai_voice", XaiVoiceAdapter(get_voice_http_client()))
    register_adapter("mistral_voice", MistralVoiceAdapter(get_voice_http_client()))

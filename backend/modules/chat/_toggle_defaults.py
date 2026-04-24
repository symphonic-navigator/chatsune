"""Compute session-toggle defaults from a persona."""
from typing import Any

from backend.modules.tools import get_tool_groups_for_persona


def compute_persona_toggle_defaults(
    persona: dict[str, Any],
) -> dict[str, bool]:
    """Return {"tools_enabled": bool, "auto_read": bool} derived from persona.

    tools_enabled is True if at least one integration configured on the persona
    exposes tool definitions. Persona without explicit integration config has
    all user integrations active; in that case the registry is checked for any
    tool-providing integration.

    auto_read is True if the persona has both a TTS provider and a dialogue
    voice configured — meaning TTS is ready to use out of the box.
    """
    tool_groups = get_tool_groups_for_persona(persona)
    tools_enabled = any(group.get("tools") for group in tool_groups)

    voice_cfg = persona.get("voice_config") or {}
    has_tts_provider = bool(voice_cfg.get("tts_provider_id"))
    has_voice = bool(voice_cfg.get("dialogue_voice"))
    auto_read = has_tts_provider and has_voice

    return {"tools_enabled": tools_enabled, "auto_read": auto_read}

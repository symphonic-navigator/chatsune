"""Smoke checks on the ``screen_effect`` integration definition.

Pure import-only; no DB, no FastAPI app. Catches accidental drift between
the spec (default_enabled, assignable, response_tag_prefix == id) and the
registration call.
"""

from backend.modules.integrations._registry import get


def test_screen_effect_is_registered() -> None:
    definition = get("screen_effect")
    assert definition is not None, "screen_effect integration must be registered"


def test_screen_effect_is_default_on_for_every_user() -> None:
    definition = get("screen_effect")
    assert definition is not None
    assert definition.default_enabled is True
    assert definition.assignable is False


def test_screen_effect_response_tag_prefix_matches_id() -> None:
    definition = get("screen_effect")
    assert definition is not None
    assert definition.response_tag_prefix == definition.id == "screen_effect"


def test_screen_effect_has_prompt_extension() -> None:
    definition = get("screen_effect")
    assert definition is not None
    assert "rising_emojis" in definition.system_prompt_template
    assert "<screen_effect" in definition.system_prompt_template


def test_screen_effect_has_no_tools() -> None:
    definition = get("screen_effect")
    assert definition is not None
    assert definition.tool_definitions == []
    assert definition.capabilities == []

"""Unit test: compute_persona_toggle_defaults pulls the right bits."""
from backend.modules.chat._toggle_defaults import compute_persona_toggle_defaults


def test_auto_read_true_when_voice_configured(monkeypatch):
    monkeypatch.setattr(
        "backend.modules.chat._toggle_defaults.get_tool_groups_for_persona",
        lambda persona: [],
    )
    persona = {
        "voice_config": {
            "tts_provider_id": "xai",
            "dialogue_voice": "Ara",
        },
    }
    out = compute_persona_toggle_defaults(persona)
    assert out == {"tools_enabled": False, "auto_read": True}


def test_tools_enabled_true_when_integration_publishes_tools(monkeypatch):
    monkeypatch.setattr(
        "backend.modules.chat._toggle_defaults.get_tool_groups_for_persona",
        lambda persona: [{"id": "lovense", "tools": [{"name": "list_toys"}]}],
    )
    out = compute_persona_toggle_defaults({})
    assert out["tools_enabled"] is True


def test_all_false_for_blank_persona(monkeypatch):
    monkeypatch.setattr(
        "backend.modules.chat._toggle_defaults.get_tool_groups_for_persona",
        lambda persona: [],
    )
    out = compute_persona_toggle_defaults({})
    assert out == {"tools_enabled": False, "auto_read": False}

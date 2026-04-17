from backend.modules.integrations._registry import get
from shared.dtos.integrations import IntegrationCapability


def test_lovense_is_tool_provider():
    defn = get("lovense")
    assert defn is not None
    assert IntegrationCapability.TOOL_PROVIDER in defn.capabilities


def test_lovense_has_no_persona_config_fields():
    defn = get("lovense")
    assert defn.persona_config_fields == []


def test_mistral_voice_is_tts_and_stt():
    defn = get("mistral_voice")
    assert defn is not None
    assert IntegrationCapability.TTS_PROVIDER in defn.capabilities
    assert IntegrationCapability.STT_PROVIDER in defn.capabilities


def test_mistral_voice_api_key_is_secret():
    defn = get("mistral_voice")
    api_key_field = next(f for f in defn.config_fields if f["key"] == "api_key")
    assert api_key_field["secret"] is True


def test_mistral_voice_has_persona_voice_field():
    defn = get("mistral_voice")
    voice_field = next(f for f in defn.persona_config_fields if f["key"] == "voice_id")
    assert voice_field["field_type"] == "select"


def test_mistral_voice_has_narrator_voice_field():
    defn = get("mistral_voice")
    field = next(f for f in defn.persona_config_fields if f["key"] == "narrator_voice_id")
    assert field["field_type"] == "select"
    assert field["required"] is False


def test_mistral_voice_has_playback_gap_field():
    defn = get("mistral_voice")
    field = next(f for f in defn.config_fields if f["key"] == "playback_gap_ms")
    assert field["field_type"] == "select"
    assert field["required"] is False
    expected_values = {"0", "50", "100", "200", "300", "500"}
    actual_values = {o["value"] for o in field["options"]}
    assert actual_values == expected_values

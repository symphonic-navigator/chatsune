"""Unit tests for the persona tts_provider_id backfill migration helper."""
from backend.modules.persona._migration_tts_provider_id import (
    pick_default_provider_id,
)


TTS_INTEGRATION_IDS = ("xai_voice", "mistral_voice")


def test_returns_none_when_persona_has_no_integration_configs():
    assert pick_default_provider_id({}, TTS_INTEGRATION_IDS) is None


def test_returns_none_when_no_tts_integration_has_a_voice_id():
    persona = {"integration_configs": {"mistral_voice": {}}}
    assert pick_default_provider_id(persona, TTS_INTEGRATION_IDS) is None


def test_returns_the_integration_id_with_a_configured_voice_id():
    persona = {
        "integration_configs": {
            "mistral_voice": {"voice_id": "v-uuid"},
        },
    }
    assert pick_default_provider_id(persona, TTS_INTEGRATION_IDS) == "mistral_voice"


def test_skips_unknown_integrations():
    persona = {
        "integration_configs": {
            "unknown_voice": {"voice_id": "v-uuid"},
        },
    }
    assert pick_default_provider_id(persona, TTS_INTEGRATION_IDS) is None


def test_prefers_the_first_known_integration_in_the_supplied_order():
    # The order of TTS_INTEGRATION_IDS is the deciding tie-break: when
    # multiple TTS integrations on the persona have a voice_id set, we pick
    # whichever appears first in the registry-defined order so the migration
    # is deterministic across re-runs.
    persona = {
        "integration_configs": {
            "mistral_voice": {"voice_id": "m"},
            "xai_voice": {"voice_id": "x"},
        },
    }
    assert pick_default_provider_id(persona, TTS_INTEGRATION_IDS) == "xai_voice"


def test_ignores_falsy_voice_id():
    persona = {
        "integration_configs": {
            "mistral_voice": {"voice_id": ""},
            "xai_voice": {"voice_id": None},
        },
    }
    assert pick_default_provider_id(persona, TTS_INTEGRATION_IDS) is None

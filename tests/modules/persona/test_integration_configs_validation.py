import pytest

from backend.modules.persona._handlers import _validate_integration_configs


def test_known_integration_known_field_passes():
    _validate_integration_configs({"mistral_voice": {"voice_id": "nova"}})


def test_unknown_integration_raises():
    with pytest.raises(ValueError, match="Unknown integration"):
        _validate_integration_configs({"not_real": {}})


def test_unknown_field_raises():
    with pytest.raises(ValueError, match="Unknown persona-config keys"):
        _validate_integration_configs(
            {"mistral_voice": {"voice_id": "nova", "extra": 1}}
        )

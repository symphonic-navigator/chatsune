from backend.modules.integrations._repository import (
    _split_config, _redact_config, _encrypt, _decrypt,
)


def test_split_config_separates_secret_fields():
    plain, encrypted = _split_config(
        "mistral_voice",
        {"api_key": "sk-abc", "something_else": "x"},
    )
    assert "api_key" not in plain
    assert "api_key" in encrypted
    assert plain == {"something_else": "x"}


def test_split_config_skips_empty_secret():
    plain, encrypted = _split_config("mistral_voice", {"api_key": ""})
    assert encrypted == {}


def test_redact_reports_is_set_true_when_encrypted_present():
    redacted = _redact_config(
        "mistral_voice",
        plain={"something": 1},
        encrypted={"api_key": "gAAA..."},
    )
    assert redacted["api_key"] == {"is_set": True}
    assert redacted["something"] == 1


def test_redact_reports_is_set_false_when_encrypted_absent():
    redacted = _redact_config("mistral_voice", plain={}, encrypted={})
    assert redacted["api_key"] == {"is_set": False}


def test_encrypt_decrypt_roundtrip():
    assert _decrypt(_encrypt("hello")) == "hello"

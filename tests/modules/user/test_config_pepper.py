import pytest
from pydantic import ValidationError

from backend.config import Settings


def test_kdf_pepper_required_32_bytes(monkeypatch):
    monkeypatch.setenv("kdf_pepper", "")
    with pytest.raises(ValidationError):
        Settings()


def test_kdf_pepper_valid_base64url_32_bytes(monkeypatch):
    import base64, secrets
    value = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    monkeypatch.setenv("kdf_pepper", value)
    s = Settings()
    assert len(s.kdf_pepper_bytes) == 32


def test_kdf_pepper_rejects_short_material(monkeypatch):
    import base64
    value = base64.urlsafe_b64encode(b"too-short").decode()
    monkeypatch.setenv("kdf_pepper", value)
    with pytest.raises(ValidationError):
        Settings()

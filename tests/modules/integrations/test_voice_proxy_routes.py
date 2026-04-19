"""Voice proxy routes — list voices (and later stt/tts)."""
from unittest.mock import AsyncMock
import pytest
from starlette.testclient import TestClient

from backend.main import app
from backend.modules.user._auth import create_access_token, generate_session_id
from backend.modules.integrations._voice_adapters._base import (
    VoiceAuthError, VoiceInfo,
)


def _token() -> str:
    return create_access_token(
        user_id="u1", role="user",
        session_id=generate_session_id(), must_change_password=False,
    )


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _authed_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token()}"}


def test_list_voices_dispatches_to_adapter(monkeypatch, client):
    fake = AsyncMock()
    fake.list_voices.return_value = [VoiceInfo(id="v1", name="V1")]
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.get_adapter",
        lambda iid: fake if iid == "xai_voice" else None,
    )
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.load_api_key_for",
        AsyncMock(return_value="KEY"),
    )
    r = client.get(
        "/api/integrations/xai_voice/voice/voices",
        headers=_authed_headers(),
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"voices": [
        {"id": "v1", "name": "V1", "language": None, "gender": None},
    ]}
    fake.list_voices.assert_awaited_once_with("KEY")


def test_list_voices_no_adapter_returns_400(monkeypatch, client):
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.get_adapter",
        lambda _id: None,
    )
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.load_api_key_for",
        AsyncMock(return_value="KEY"),
    )
    r = client.get(
        "/api/integrations/mistral_voice/voice/voices",
        headers=_authed_headers(),
    )
    assert r.status_code == 400


def test_list_voices_integration_not_enabled(monkeypatch, client):
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.load_api_key_for",
        AsyncMock(return_value=None),
    )
    r = client.get(
        "/api/integrations/xai_voice/voice/voices",
        headers=_authed_headers(),
    )
    assert r.status_code == 404


def test_list_voices_auth_error_maps_to_401(monkeypatch, client):
    fake = AsyncMock()
    fake.list_voices.side_effect = VoiceAuthError()
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.get_adapter",
        lambda _id: fake,
    )
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.load_api_key_for",
        AsyncMock(return_value="KEY"),
    )
    r = client.get(
        "/api/integrations/xai_voice/voice/voices",
        headers=_authed_headers(),
    )
    assert r.status_code == 401
    body = r.json()
    assert "error_code" in body
    assert "message" in body


def test_list_voices_without_token_401(client):
    r = client.get("/api/integrations/xai_voice/voice/voices")
    assert r.status_code == 401

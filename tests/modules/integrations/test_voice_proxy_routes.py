"""Voice proxy routes — list voices (and later stt/tts)."""
from unittest.mock import AsyncMock
import pytest
from starlette.testclient import TestClient

from backend.main import app
from backend.modules.user._auth import create_access_token, generate_session_id
from backend.modules.integrations._voice_adapters._base import (
    VoiceAuthError, VoiceInfo, VoiceRateLimitError, VoiceBadRequestError,
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


def test_stt_dispatches_to_adapter(monkeypatch, client):
    fake = AsyncMock()
    fake.transcribe.return_value = "hello world"
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.get_adapter",
        lambda _id: fake,
    )
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.load_api_key_for",
        AsyncMock(return_value="KEY"),
    )
    r = client.post(
        "/api/integrations/xai_voice/voice/stt",
        files={"audio": ("sample.wav", b"RIFF....", "audio/wav")},
        data={"language": "en"},
        headers=_authed_headers(),
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"text": "hello world"}
    fake.transcribe.assert_awaited_once_with(
        audio=b"RIFF....", content_type="audio/wav", api_key="KEY", language="en",
    )


def test_stt_rate_limit_maps_to_429(monkeypatch, client):
    fake = AsyncMock()
    fake.transcribe.side_effect = VoiceRateLimitError()
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.get_adapter", lambda _id: fake,
    )
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.load_api_key_for",
        AsyncMock(return_value="KEY"),
    )
    r = client.post(
        "/api/integrations/xai_voice/voice/stt",
        files={"audio": ("s.wav", b"data", "audio/wav")},
        headers=_authed_headers(),
    )
    assert r.status_code == 429


def test_tts_dispatches_and_streams_bytes(monkeypatch, client):
    fake = AsyncMock()
    fake.synthesise.return_value = (b"\xff\xfbAUDIO", "audio/mpeg")
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.get_adapter", lambda _id: fake,
    )
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.load_api_key_for",
        AsyncMock(return_value="KEY"),
    )
    r = client.post(
        "/api/integrations/xai_voice/voice/tts",
        json={"text": "Hi", "voice_id": "v1"},
        headers=_authed_headers(),
    )
    assert r.status_code == 200, r.text
    assert r.content == b"\xff\xfbAUDIO"
    assert r.headers["content-type"].startswith("audio/mpeg")
    fake.synthesise.assert_awaited_once_with(
        text="Hi", voice_id="v1", api_key="KEY",
    )


def test_tts_bad_request_400(monkeypatch, client):
    fake = AsyncMock()
    fake.synthesise.side_effect = VoiceBadRequestError("unknown voice_id")
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.get_adapter", lambda _id: fake,
    )
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.load_api_key_for",
        AsyncMock(return_value="KEY"),
    )
    r = client.post(
        "/api/integrations/xai_voice/voice/tts",
        json={"text": "Hi", "voice_id": "bad"},
        headers=_authed_headers(),
    )
    assert r.status_code == 400
    assert "unknown voice_id" in r.json()["message"]

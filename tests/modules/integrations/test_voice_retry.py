"""Voice proxy routes — single retry on transient upstream 5xx.

The handler layer retries exactly once on :class:`VoiceUnavailableError`
(see :func:`backend.modules.integrations._handlers._with_transient_retry`)
so that brief xAI / Mistral hiccups do not bubble up as 502 to the user.

These tests pin that behaviour at the HTTP layer via ``TestClient`` so a
future refactor (e.g. moving retries down into the adapters) cannot
silently drop the retry without a failing test.
"""

from unittest.mock import AsyncMock
import pytest
from starlette.testclient import TestClient

from backend.main import app
from backend.modules.user._auth import create_access_token, generate_session_id
from backend.modules.integrations._voice_adapters._base import (
    VoiceAuthError,
    VoiceBadRequestError,
    VoiceInfo,
    VoiceRateLimitError,
    VoiceUnavailableError,
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


def _bind_adapter(monkeypatch, fake) -> None:
    """Wire up ``get_adapter`` and ``load_api_key_for`` to the fake adapter."""
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.get_adapter", lambda _id: fake,
    )
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.load_api_key_for",
        AsyncMock(return_value="KEY"),
    )


def _no_sleep(monkeypatch) -> None:
    """Skip the 250 ms retry pause during tests — correctness, not timing."""
    async def _instant(_seconds: float) -> None:
        return None
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.asyncio.sleep", _instant,
    )


# ---------------------------------------------------------------------------
# Success on retry: first call raises VoiceUnavailableError, second succeeds.
# ---------------------------------------------------------------------------


def test_list_voices_retries_once_on_transient_5xx(monkeypatch, client):
    fake = AsyncMock()
    fake.list_voices.side_effect = [
        VoiceUnavailableError("Upstream 500"),
        [VoiceInfo(id="v1", name="V1")],
    ]
    _bind_adapter(monkeypatch, fake)
    _no_sleep(monkeypatch)

    r = client.get(
        "/api/integrations/xai_voice/voice/voices",
        headers=_authed_headers(),
    )

    assert r.status_code == 200, r.text
    assert r.json() == {"voices": [
        {"id": "v1", "name": "V1", "language": None, "gender": None},
    ]}
    assert fake.list_voices.await_count == 2


def test_stt_retries_once_on_transient_5xx(monkeypatch, client):
    fake = AsyncMock()
    fake.transcribe.side_effect = [
        VoiceUnavailableError("Upstream 500"),
        "hello world",
    ]
    _bind_adapter(monkeypatch, fake)
    _no_sleep(monkeypatch)

    r = client.post(
        "/api/integrations/xai_voice/voice/stt",
        files={"audio": ("sample.wav", b"RIFF....", "audio/wav")},
        data={"language": "en"},
        headers=_authed_headers(),
    )

    assert r.status_code == 200, r.text
    assert r.json() == {"text": "hello world"}
    assert fake.transcribe.await_count == 2
    # Both attempts must receive the same audio payload — if the retry
    # re-read a consumed UploadFile we'd see an empty second payload.
    for call in fake.transcribe.await_args_list:
        assert call.kwargs["audio"] == b"RIFF...."


def test_tts_retries_once_on_transient_5xx(monkeypatch, client):
    fake = AsyncMock()
    fake.synthesise.side_effect = [
        VoiceUnavailableError("Upstream 503"),
        (b"\xff\xfbAUDIO", "audio/mpeg"),
    ]
    _bind_adapter(monkeypatch, fake)
    _no_sleep(monkeypatch)

    r = client.post(
        "/api/integrations/xai_voice/voice/tts",
        json={"text": "Hi", "voice_id": "v1"},
        headers=_authed_headers(),
    )

    assert r.status_code == 200, r.text
    assert r.content == b"\xff\xfbAUDIO"
    assert fake.synthesise.await_count == 2


# ---------------------------------------------------------------------------
# Persistent failure: both attempts raise VoiceUnavailableError -> 502.
# ---------------------------------------------------------------------------


def test_list_voices_persistent_5xx_returns_502_after_retry(monkeypatch, client):
    fake = AsyncMock()
    fake.list_voices.side_effect = VoiceUnavailableError("Upstream 500")
    _bind_adapter(monkeypatch, fake)
    _no_sleep(monkeypatch)

    r = client.get(
        "/api/integrations/xai_voice/voice/voices",
        headers=_authed_headers(),
    )

    assert r.status_code == 502
    assert fake.list_voices.await_count == 2
    body = r.json()
    assert body["error_code"] == "voice_unavailable"


def test_tts_persistent_5xx_returns_502_after_retry(monkeypatch, client):
    fake = AsyncMock()
    fake.synthesise.side_effect = VoiceUnavailableError("Upstream 500")
    _bind_adapter(monkeypatch, fake)
    _no_sleep(monkeypatch)

    r = client.post(
        "/api/integrations/xai_voice/voice/tts",
        json={"text": "Hi", "voice_id": "v1"},
        headers=_authed_headers(),
    )

    assert r.status_code == 502
    assert fake.synthesise.await_count == 2


# ---------------------------------------------------------------------------
# Non-transient errors must NOT be retried — these are deterministic
# failures, retrying them only doubles the load and delays the error.
# ---------------------------------------------------------------------------


def test_auth_error_is_not_retried(monkeypatch, client):
    fake = AsyncMock()
    fake.list_voices.side_effect = VoiceAuthError()
    _bind_adapter(monkeypatch, fake)
    _no_sleep(monkeypatch)

    r = client.get(
        "/api/integrations/xai_voice/voice/voices",
        headers=_authed_headers(),
    )

    assert r.status_code == 401
    assert fake.list_voices.await_count == 1


def test_rate_limit_is_not_retried(monkeypatch, client):
    fake = AsyncMock()
    fake.transcribe.side_effect = VoiceRateLimitError()
    _bind_adapter(monkeypatch, fake)
    _no_sleep(monkeypatch)

    r = client.post(
        "/api/integrations/xai_voice/voice/stt",
        files={"audio": ("s.wav", b"data", "audio/wav")},
        headers=_authed_headers(),
    )

    assert r.status_code == 429
    assert fake.transcribe.await_count == 1


def test_bad_request_is_not_retried(monkeypatch, client):
    fake = AsyncMock()
    fake.synthesise.side_effect = VoiceBadRequestError("unknown voice_id")
    _bind_adapter(monkeypatch, fake)
    _no_sleep(monkeypatch)

    r = client.post(
        "/api/integrations/xai_voice/voice/tts",
        json={"text": "Hi", "voice_id": "bad"},
        headers=_authed_headers(),
    )

    assert r.status_code == 400
    assert fake.synthesise.await_count == 1

"""Tests for the nano-gpt voice adapter (xAI backend)."""

from __future__ import annotations

import httpx
import pytest

from backend.modules.integrations._voice_adapters._nano_gpt_voice_xai import (
    NanoGptVoiceXaiAdapter,
)


def _client_with(handler) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, timeout=5.0)


@pytest.mark.asyncio
async def test_list_voices_returns_hardcoded_five() -> None:
    # list_voices does no HTTP — any client works.
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("list_voices must not perform HTTP")
    adapter = NanoGptVoiceXaiAdapter(_client_with(handler))

    voices = await adapter.list_voices(api_key="ignored")
    names = [v.name for v in voices]
    assert names == ["Eve", "Ara", "Leo", "Rex", "Sal"]
    ids = [v.id for v in voices]
    assert ids == ["Eve", "Ara", "Leo", "Rex", "Sal"]
    # Verify all five gender hints, not just three.
    by_name = {v.name: v.gender for v in voices}
    assert by_name == {
        "Eve": "female",
        "Ara": "female",
        "Leo": "male",
        "Rex": "male",
        "Sal": "neutral",
    }


@pytest.mark.asyncio
async def test_synthesise_posts_expected_body_and_returns_audio() -> None:
    import json

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/audio/speech"
        assert request.headers["x-api-key"] == "key-123"
        body = json.loads(request.content)
        assert body == {
            "model": "xai-tts",
            "voice": "Eve",
            "input": "Hello there.",
        }
        return httpx.Response(
            200,
            content=b"\x00\x01\x02FAKE_MP3",
            headers={"content-type": "audio/mpeg"},
        )

    adapter = NanoGptVoiceXaiAdapter(_client_with(handler))
    audio, ctype = await adapter.synthesise(
        text="Hello there.", voice_id="Eve", api_key="key-123",
    )
    assert audio == b"\x00\x01\x02FAKE_MP3"
    assert ctype == "audio/mpeg"


@pytest.mark.asyncio
async def test_synthesise_maps_401_to_voice_auth_error() -> None:
    from backend.modules.integrations._voice_adapters._base import VoiceAuthError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    adapter = NanoGptVoiceXaiAdapter(_client_with(handler))
    with pytest.raises(VoiceAuthError):
        await adapter.synthesise(text="hi", voice_id="Eve", api_key="bad")


@pytest.mark.asyncio
async def test_transcribe_posts_multipart_and_extracts_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/audio/transcriptions"
        assert request.headers["x-api-key"] == "key-123"
        body = request.content.decode("utf-8", errors="replace")
        # Multipart fields
        assert 'name="file"' in body
        assert 'name="model"' in body
        assert "xai/speech-to-text/v1" in body
        assert 'name="language"' in body
        assert "en" in body
        return httpx.Response(200, json={"text": "Hello there."})

    adapter = NanoGptVoiceXaiAdapter(_client_with(handler))
    text = await adapter.transcribe(
        audio=b"FAKE_WAV_BYTES",
        content_type="audio/wav",
        api_key="key-123",
        language="en",
    )
    assert text == "Hello there."


@pytest.mark.asyncio
async def test_transcribe_without_language_omits_field() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8", errors="replace")
        assert 'name="language"' not in body
        return httpx.Response(200, json={"text": "ok"})

    adapter = NanoGptVoiceXaiAdapter(_client_with(handler))
    await adapter.transcribe(
        audio=b"x", content_type="audio/wav", api_key="k", language=None,
    )


@pytest.mark.asyncio
async def test_transcribe_remaps_webm_to_mkv_for_nano_gpt_whitelist() -> None:
    # nano-gpt's STT rejects audio/webm at an early content-type check.
    # webm is a restricted MKV profile, so the adapter spoofs the
    # declared container to audio/x-matroska / audio.mkv before forwarding.
    # See INSIGHTS INS-054.
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode("utf-8", errors="replace")
        assert 'filename="audio.mkv"' in body
        assert "audio/x-matroska" in body
        assert "audio/webm" not in body
        return httpx.Response(200, json={"text": "ok"})

    adapter = NanoGptVoiceXaiAdapter(_client_with(handler))
    await adapter.transcribe(
        audio=b"FAKE_WEBM_BYTES",
        content_type="audio/webm;codecs=opus",
        api_key="k",
        language=None,
    )


@pytest.mark.asyncio
async def test_transcribe_maps_400_to_voice_bad_request() -> None:
    from backend.modules.integrations._voice_adapters._base import VoiceBadRequestError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad audio"})

    adapter = NanoGptVoiceXaiAdapter(_client_with(handler))
    with pytest.raises(VoiceBadRequestError):
        await adapter.transcribe(
            audio=b"x", content_type="audio/wav", api_key="k", language=None,
        )

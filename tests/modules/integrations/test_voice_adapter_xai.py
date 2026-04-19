"""XaiVoiceAdapter — list_voices."""
import pytest
import httpx

from backend.modules.integrations._voice_adapters._base import (
    VoiceAuthError,
    VoiceBadRequestError,
    VoiceRateLimitError,
    VoiceUnavailableError,
)
from backend.modules.integrations._voice_adapters._xai import XaiVoiceAdapter


def _client_with(handler) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, timeout=5.0)


@pytest.mark.asyncio
async def test_list_voices_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v1/tts/voices"
        assert request.headers["authorization"] == "Bearer KEY"
        return httpx.Response(
            200,
            json={"voices": [
                {"voice_id": "v1", "name": "Voice One"},
                {"voice_id": "v2", "name": "Voice Two", "language": "en"},
            ]},
        )

    adapter = XaiVoiceAdapter(_client_with(handler))
    voices = await adapter.list_voices("KEY")
    assert len(voices) == 2
    assert voices[0].id == "v1"
    assert voices[0].name == "Voice One"
    assert voices[1].language == "en"


@pytest.mark.asyncio
async def test_list_voices_auth_error():
    def handler(_req): return httpx.Response(401, json={"error": "bad key"})
    adapter = XaiVoiceAdapter(_client_with(handler))
    with pytest.raises(VoiceAuthError):
        await adapter.list_voices("KEY")


@pytest.mark.asyncio
async def test_list_voices_rate_limit():
    def handler(_req): return httpx.Response(429, json={"error": "too many"})
    adapter = XaiVoiceAdapter(_client_with(handler))
    with pytest.raises(VoiceRateLimitError):
        await adapter.list_voices("KEY")


@pytest.mark.asyncio
async def test_list_voices_upstream_500():
    def handler(_req): return httpx.Response(500, text="boom")
    adapter = XaiVoiceAdapter(_client_with(handler))
    with pytest.raises(VoiceUnavailableError):
        await adapter.list_voices("KEY")


@pytest.mark.asyncio
async def test_list_voices_timeout():
    def handler(_req): raise httpx.ReadTimeout("timed out")
    adapter = XaiVoiceAdapter(_client_with(handler))
    with pytest.raises(VoiceUnavailableError):
        await adapter.list_voices("KEY")


@pytest.mark.asyncio
async def test_transcribe_ok_with_language():
    captured = {}
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/stt"
        assert request.headers["authorization"] == "Bearer KEY"
        captured["body"] = bytes(request.content)
        return httpx.Response(200, json={"text": "hello world"})

    adapter = XaiVoiceAdapter(_client_with(handler))
    text = await adapter.transcribe(
        audio=b"RIFFfakewavdata", content_type="audio/wav", api_key="KEY", language="en",
    )
    assert text == "hello world"
    # language + format fields must be present in the multipart body.
    # xAI does NOT accept a ``model`` field on this endpoint.
    assert b'name="language"' in captured["body"]
    assert b'name="format"' in captured["body"]
    assert b"grok-stt-1" not in captured["body"]


@pytest.mark.asyncio
async def test_transcribe_ok_no_language():
    def handler(request: httpx.Request) -> httpx.Response:
        # language + format omitted when None (auto-detect on xAI side)
        assert b'name="language"' not in request.content
        assert b'name="format"' not in request.content
        return httpx.Response(200, json={"text": "ok"})

    adapter = XaiVoiceAdapter(_client_with(handler))
    text = await adapter.transcribe(
        audio=b"data", content_type="audio/wav", api_key="KEY", language=None,
    )
    assert text == "ok"


@pytest.mark.asyncio
async def test_transcribe_auto_language_omits_fields():
    """language='auto' is treated like None — no language/format on the request."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert b'name="language"' not in request.content
        assert b'name="format"' not in request.content
        return httpx.Response(200, json={"text": "ok"})

    adapter = XaiVoiceAdapter(_client_with(handler))
    text = await adapter.transcribe(
        audio=b"data", content_type="audio/wav", api_key="KEY", language="auto",
    )
    assert text == "ok"


@pytest.mark.asyncio
async def test_transcribe_rate_limit():
    def handler(_req): return httpx.Response(429, json={"error": "slow down"})
    adapter = XaiVoiceAdapter(_client_with(handler))
    with pytest.raises(VoiceRateLimitError):
        await adapter.transcribe(
            audio=b"d", content_type="audio/wav", api_key="KEY", language=None,
        )


@pytest.mark.asyncio
async def test_synthesise_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/tts"
        import json
        body = request.read()
        parsed = json.loads(body)
        # xAI's /v1/tts takes {text, voice_id, language} — NO model field.
        assert "model" not in parsed
        assert parsed["text"] == "Hello!"
        assert parsed["voice_id"] == "v1"
        assert parsed["language"] == "auto"
        return httpx.Response(
            200, content=b"\xff\xfbMP3DATA", headers={"content-type": "audio/mpeg"},
        )

    adapter = XaiVoiceAdapter(_client_with(handler))
    audio, ctype = await adapter.synthesise("Hello!", "v1", "KEY")
    assert audio == b"\xff\xfbMP3DATA"
    assert ctype == "audio/mpeg"


@pytest.mark.asyncio
async def test_synthesise_bad_voice():
    def handler(_req):
        return httpx.Response(400, json={"error": "unknown voice_id"})

    adapter = XaiVoiceAdapter(_client_with(handler))
    with pytest.raises(VoiceBadRequestError) as ei:
        await adapter.synthesise("hi", "nope", "KEY")
    assert "unknown voice_id" in ei.value.user_message

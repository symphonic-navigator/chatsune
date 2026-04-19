"""XaiVoiceAdapter — list_voices."""
import pytest
import httpx

from backend.modules.integrations._voice_adapters._base import (
    VoiceAuthError,
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

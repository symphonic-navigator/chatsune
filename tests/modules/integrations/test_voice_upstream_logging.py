"""Diagnostic logging on voice-upstream 5xx responses.

The voice adapters emit a single structured WARN log per 5xx response so
the operator can distinguish "xAI is down" from "we sent something
malformed" without re-running the request under a debugger. The log is
grep-able (``voice.upstream_5xx adapter=<x> operation=<y> status=<n>
...``) and lives at the adapter layer because that's where the full
request/response context is available.

These tests pin:
  1. A 5xx response emits exactly one WARN log carrying adapter,
     operation, status, request_id header, retry-after header, content
     type, a (truncated) body excerpt, and the adapter-provided request
     context.
  2. A 2xx response does NOT emit the log.
  3. A 401 (auth) response does NOT emit the log — the diagnostic path
     is 5xx-only.
"""
from __future__ import annotations

import logging

import httpx
import pytest

from backend.modules.integrations._voice_adapters._base import VoiceAuthError, VoiceUnavailableError
from backend.modules.integrations._voice_adapters._mistral import MistralVoiceAdapter
from backend.modules.integrations._voice_adapters._xai import XaiVoiceAdapter


def _client_with(handler) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, timeout=5.0)


# ---------------------------------------------------------------------------
# xAI — transcribe 5xx: the real user-reported problem case.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_xai_transcribe_5xx_emits_structured_log(caplog):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            text="internal server error: model overloaded",
            headers={
                "content-type": "text/plain; charset=utf-8",
                "x-request-id": "req-abc-123",
                "retry-after": "5",
            },
        )

    adapter = XaiVoiceAdapter(_client_with(handler))
    with caplog.at_level(logging.WARNING, logger="backend.modules.integrations._voice_adapters._xai"):
        with pytest.raises(VoiceUnavailableError):
            await adapter.transcribe(
                audio=b"RIFFfakewav", content_type="audio/wav",
                api_key="KEY", language="en",
            )

    # Exactly one diagnostic log emitted — no duplication between success /
    # raise branches.
    matching = [r for r in caplog.records if "voice.upstream_5xx" in r.getMessage()]
    assert len(matching) == 1, [r.getMessage() for r in caplog.records]

    msg = matching[0].getMessage()
    assert "adapter=xai" in msg
    assert "operation=transcribe" in msg
    assert "status=500" in msg
    assert "request_id='req-abc-123'" in msg
    assert "retry_after='5'" in msg
    assert "content_type='text/plain; charset=utf-8'" in msg
    assert "body_excerpt='internal server error: model overloaded'" in msg
    # Adapter-provided request-side context must round-trip through the helper.
    assert "url='https://api.x.ai/v1/stt'" in msg
    assert "audio_bytes=11" in msg
    assert "content_type='audio/wav'" in msg
    assert "language='en'" in msg
    assert "filename_ext='wav'" in msg


@pytest.mark.asyncio
async def test_xai_transcribe_5xx_body_excerpt_truncated(caplog):
    """Oversized response bodies are capped at 500 chars to keep logs sane."""
    long_body = "x" * 2000

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text=long_body, headers={"content-type": "text/html"})

    adapter = XaiVoiceAdapter(_client_with(handler))
    with caplog.at_level(logging.WARNING, logger="backend.modules.integrations._voice_adapters._xai"):
        with pytest.raises(VoiceUnavailableError):
            await adapter.list_voices("KEY")

    msg = next(r.getMessage() for r in caplog.records if "voice.upstream_5xx" in r.getMessage())
    # Excerpt is exactly 500 chars of 'x', not the full 2000.
    assert "body_excerpt='" + "x" * 500 + "'" in msg
    assert "x" * 501 not in msg


# ---------------------------------------------------------------------------
# Negative cases — non-5xx must NOT emit the log.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_xai_transcribe_2xx_emits_no_log(caplog):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": "hello"})

    adapter = XaiVoiceAdapter(_client_with(handler))
    with caplog.at_level(logging.WARNING, logger="backend.modules.integrations._voice_adapters._xai"):
        text = await adapter.transcribe(
            audio=b"x", content_type="audio/wav", api_key="KEY", language=None,
        )

    assert text == "hello"
    assert not any("voice.upstream_5xx" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_xai_auth_error_emits_no_5xx_log(caplog):
    """Auth failures have their own error class — the 5xx diagnosis path must stay untouched."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    adapter = XaiVoiceAdapter(_client_with(handler))
    with caplog.at_level(logging.WARNING, logger="backend.modules.integrations._voice_adapters._xai"):
        with pytest.raises(VoiceAuthError):
            await adapter.list_voices("KEY")

    assert not any("voice.upstream_5xx" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# Mistral — same helper path, smoke check to guard against drift.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mistral_synthesise_5xx_emits_structured_log(caplog):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            text="mistral busy",
            headers={"content-type": "text/plain", "x-request-id": "m-req-9"},
        )

    adapter = MistralVoiceAdapter(_client_with(handler))
    with caplog.at_level(logging.WARNING, logger="backend.modules.integrations._voice_adapters._mistral"):
        with pytest.raises(VoiceUnavailableError):
            await adapter.synthesise("Hello there", "v1", "KEY")

    matching = [r for r in caplog.records if "voice.upstream_5xx" in r.getMessage()]
    assert len(matching) == 1
    msg = matching[0].getMessage()
    assert "adapter=mistral" in msg
    assert "operation=synthesise" in msg
    assert "status=503" in msg
    assert "request_id='m-req-9'" in msg
    assert "voice_id='v1'" in msg
    assert "text_len=11" in msg

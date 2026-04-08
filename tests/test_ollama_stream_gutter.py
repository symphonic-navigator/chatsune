"""H-004: verify the NDJSON gutter-timeout aborts a stalled upstream stream."""

import asyncio

import pytest

from backend.modules.llm._adapters import _ollama_base
from backend.modules.llm._adapters._events import ContentDelta, StreamDone
from backend.modules.llm._adapters._ollama_cloud import OllamaCloudAdapter
from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart


class _HangingAiter:
    """Yields one NDJSON line, then blocks forever on the next ``__anext__``."""

    def __init__(self) -> None:
        self._yielded_first = False

    def __aiter__(self) -> "_HangingAiter":
        return self

    async def __anext__(self) -> str:
        if not self._yielded_first:
            self._yielded_first = True
            return '{"message":{"content":"hi"},"done":false}'
        await asyncio.sleep(3600)
        raise StopAsyncIteration


class _FakeResponse:
    status_code = 200

    def aiter_lines(self) -> _HangingAiter:
        return _HangingAiter()

    async def aread(self) -> bytes:
        return b""


class _FakeStreamCM:
    async def __aenter__(self) -> _FakeResponse:
        return _FakeResponse()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeClient:
    def stream(self, *args, **kwargs) -> _FakeStreamCM:
        return _FakeStreamCM()

    async def aclose(self) -> None:
        return None


def _make_request() -> CompletionRequest:
    return CompletionRequest(
        model="qwen3:32b",
        messages=[CompletionMessage(role="user", content=[ContentPart(type="text", text="hi")])],
    )


@pytest.mark.asyncio
async def test_gutter_timeout_aborts_stalled_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_ollama_base, "GUTTER_TIMEOUT_SECONDS", 0.5)

    adapter = OllamaCloudAdapter(base_url="https://test.ollama.com")
    adapter._client = _FakeClient()  # type: ignore[assignment]

    events: list = []

    async def _drive() -> None:
        async for event in adapter.stream_completion("test-key", _make_request()):
            events.append(event)

    # Must finish well before httpx's read-timeout (300s) would have fired.
    await asyncio.wait_for(_drive(), timeout=3.0)

    assert any(isinstance(e, ContentDelta) and e.delta == "hi" for e in events)
    assert events[-1] == StreamDone()
    assert len(events) == 2

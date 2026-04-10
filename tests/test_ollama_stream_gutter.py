"""Two-stage NDJSON gutter — slow-then-abort state machine tests."""

import asyncio

import pytest

from backend.modules.llm._adapters import _ollama_base
from backend.modules.llm._adapters._events import (
    ContentDelta,
    StreamAborted,
    StreamSlow,
)
from backend.modules.llm._adapters._ollama_cloud import OllamaCloudAdapter
from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart


class _HangingAiter:
    """Yields one NDJSON line, then hangs forever on the next line."""

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


class _ResumingAiter:
    """Yields one line, then blocks just long enough to trigger a slow
    event, then yields a second line and finishes cleanly."""

    def __init__(self, pause_seconds: float) -> None:
        self._yielded = 0
        self._pause = pause_seconds

    def __aiter__(self) -> "_ResumingAiter":
        return self

    async def __anext__(self) -> str:
        self._yielded += 1
        if self._yielded == 1:
            return '{"message":{"content":"one"},"done":false}'
        if self._yielded == 2:
            await asyncio.sleep(self._pause)
            return '{"message":{"content":"two"},"done":false}'
        if self._yielded == 3:
            return '{"done":true,"prompt_eval_count":1,"eval_count":2}'
        raise StopAsyncIteration


class _FakeResponse:
    status_code = 200

    def __init__(self, aiter) -> None:
        self._aiter = aiter

    def aiter_lines(self):
        return self._aiter

    async def aread(self) -> bytes:
        return b""


class _FakeStreamCM:
    def __init__(self, aiter) -> None:
        self._aiter = aiter

    async def __aenter__(self) -> _FakeResponse:
        return _FakeResponse(self._aiter)

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeClient:
    def __init__(self, aiter) -> None:
        self._aiter = aiter

    def stream(self, *args, **kwargs) -> _FakeStreamCM:
        return _FakeStreamCM(self._aiter)

    async def aclose(self) -> None:
        return None


def _make_request() -> CompletionRequest:
    return CompletionRequest(
        model="qwen3:32b",
        messages=[CompletionMessage(role="user", content=[ContentPart(type="text", text="hi")])],
    )


async def _collect_events(adapter) -> list:
    events: list = []
    async for event in adapter.stream_completion("test-key", _make_request()):
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_gutter_slow_then_abort_on_permanent_silence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stream that hangs after one line should first emit StreamSlow,
    then StreamAborted once the abort deadline is reached."""
    monkeypatch.setattr(_ollama_base, "GUTTER_SLOW_SECONDS", 0.3)
    monkeypatch.setattr(_ollama_base, "GUTTER_ABORT_SECONDS", 0.6)

    adapter = OllamaCloudAdapter(base_url="https://test.ollama.com")
    adapter._client = _FakeClient(_HangingAiter())  # type: ignore[assignment]

    events = await asyncio.wait_for(_collect_events(adapter), timeout=3.0)

    types = [type(e).__name__ for e in events]
    assert "ContentDelta" in types
    assert "StreamSlow" in types
    assert "StreamAborted" in types
    # StreamAborted must be the terminal event — nothing follows it.
    assert isinstance(events[-1], StreamAborted)
    assert events[-1].reason == "gutter_timeout"
    # StreamSlow must precede StreamAborted in the sequence.
    assert types.index("StreamSlow") < types.index("StreamAborted")


@pytest.mark.asyncio
async def test_gutter_slow_clears_when_tokens_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the stream is quiet long enough to trigger slow but then
    resumes, we should see StreamSlow followed by a normal completion
    and NO StreamAborted."""
    monkeypatch.setattr(_ollama_base, "GUTTER_SLOW_SECONDS", 0.2)
    monkeypatch.setattr(_ollama_base, "GUTTER_ABORT_SECONDS", 2.0)

    adapter = OllamaCloudAdapter(base_url="https://test.ollama.com")
    adapter._client = _FakeClient(_ResumingAiter(pause_seconds=0.35))  # type: ignore[assignment]

    events = await asyncio.wait_for(_collect_events(adapter), timeout=3.0)

    types = [type(e).__name__ for e in events]
    assert "StreamSlow" in types
    assert "StreamAborted" not in types
    # Natural completion: last event must be StreamDone.
    assert types[-1] == "StreamDone"
    # Both deltas arrived.
    deltas = [e for e in events if isinstance(e, ContentDelta)]
    assert [d.delta for d in deltas] == ["one", "two"]

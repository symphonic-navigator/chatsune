# Stream Abort Handling & Error Toasts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn silent LLM stream aborts into a visible, recoverable failure mode end-to-end: a two-stage gutter state machine surfaces a "slow" hint at 30 s idle and a hard abort at a configurable 120 s idle, aborted messages get a persistent status badge and are filtered out of the LLM context, and all stream errors raise actionable toasts with an inline regenerate action.

**Architecture:** Additive changes across shared contracts → Ollama adapter → chat inference → repository → orchestrator → frontend store → frontend UI. No data migration, no feature flags, no breaking changes. The design document is `docs/superpowers/specs/2026-04-11-stream-abort-and-error-toasts-design.md` — read it first.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic v2 / Motor (async MongoDB) for the backend; React 19 / TypeScript / Zustand / Tailwind / Vite for the frontend; pytest + pytest-asyncio for backend tests; vitest for frontend tests. Package managers: `uv` (backend), `pnpm` (frontend).

---

## Files Touched

**Backend (Python):**
- Modify: `backend/modules/llm/_adapters/_events.py` — new `StreamSlow`, `StreamAborted` event types, extend `ProviderStreamEvent` union.
- Modify: `backend/modules/llm/_adapters/_ollama_base.py` — replace single gutter with two-stage state machine, new constants, new env-var source.
- Modify: `backend/modules/chat/_inference.py` — two new `match` arms for `StreamSlow`/`StreamAborted`, extend break condition, pass `status` to `save_fn`.
- Modify: `backend/modules/chat/_repository.py` — add `status` kwarg to `save_message`, `setdefault` in `list_messages`/`get_last_message`, extend `message_to_dto`.
- Modify: `backend/modules/chat/_orchestrator.py` — extend inner `save_fn` signature, add aborted-status filter before context pair selection.
- Modify: `shared/events/chat.py` — add `ChatStreamSlowEvent`, extend `ChatStreamEndedEvent.status` literal.
- Modify: `shared/topics.py` — add `CHAT_STREAM_SLOW`.
- Modify: `shared/dtos/chat.py` — add `status` field to `ChatMessageDto`.

**Backend (tests):**
- Modify: `tests/test_ollama_stream_gutter.py` — existing test breaks, update expectations; add two new scenarios (slow-then-recover, hard abort).
- Modify: `tests/test_inference_runner.py` — three new tests: slow event propagation, aborted event propagation with content, aborted event propagation without content.
- Modify: `tests/test_chat_repository.py` — one new test for `save_message(..., status="aborted")` + legacy setdefault.
- Modify: `tests/test_shared_chat_contracts.py` — contract tests for new event type and extended status literal.

**Frontend (TypeScript / TSX):**
- Modify: `frontend/src/core/api/chat.ts` — add `status` field to `ChatMessageDto`.
- Modify: `frontend/src/core/types/events.ts` — add `CHAT_STREAM_SLOW` constant.
- Modify: `frontend/src/core/store/chatStore.ts` — add `streamingSlow: boolean` state and `setStreamingSlow` action, propagate slow-clear into `startStreaming`/`appendStreamingContent`/`appendStreamingThinking`/`finishStreaming`/`cancelStreaming`.
- Modify: `frontend/src/features/chat/useChatStream.ts` — new `CHAT_STREAM_SLOW` case, toast dispatch for recoverable `CHAT_STREAM_ERROR`, capture `status` from `CHAT_STREAM_ENDED` payload and attach to the finalised `ChatMessageDto`.
- Modify: `frontend/src/features/chat/AssistantMessage.tsx` — new optional `status` prop, warning-band rendering when `status === 'aborted'`.
- Modify: `frontend/src/features/chat/MessageList.tsx` — forward `msg.status` through to `AssistantMessage`, render the slow hint when `streamingSlow` is set.

**Frontend (tests):**
- Modify: `frontend/src/features/chat/__tests__/chatStore.test.ts` — new tests for `streamingSlow` lifecycle (set on slow, cleared on delta, cleared on finish).

**Docs / env:**
- Modify: `.env.example` — add `LLM_STREAM_ABORT_SECONDS=120`.
- Modify: `README.md` — add `LLM_STREAM_ABORT_SECONDS` under environment variables.

---

## Task 1: Add `StreamSlow` and `StreamAborted` adapter events

**Files:**
- Modify: `backend/modules/llm/_adapters/_events.py`
- Modify: `tests/test_provider_stream_events.py` (extend existing contract test)

- [ ] **Step 1: Write the failing contract test**

Append to `tests/test_provider_stream_events.py`:

```python
def test_stream_slow_is_instantiable_and_has_no_payload():
    from backend.modules.llm._adapters._events import StreamSlow, ProviderStreamEvent

    ev = StreamSlow()
    assert isinstance(ev, StreamSlow)
    # Union membership check — if the type is missing from the union,
    # mypy or a careful runtime check would notice; this is a minimal
    # guard that the union accepts the instance.
    sample: ProviderStreamEvent = ev
    assert sample is ev


def test_stream_aborted_carries_reason_with_default():
    from backend.modules.llm._adapters._events import StreamAborted, ProviderStreamEvent

    ev = StreamAborted()
    assert ev.reason == "gutter_timeout"

    custom = StreamAborted(reason="upstream_silence")
    assert custom.reason == "upstream_silence"

    sample: ProviderStreamEvent = custom
    assert sample is custom
```

- [ ] **Step 2: Run the test and verify it fails**

```bash
uv run pytest tests/test_provider_stream_events.py -v
```

Expected: both new tests fail with `ImportError: cannot import name 'StreamSlow'` and `StreamAborted`.

- [ ] **Step 3: Add the new event types**

Edit `backend/modules/llm/_adapters/_events.py` — add two new classes below `StreamError` and extend the union:

```python
class StreamSlow(BaseModel):
    """Emitted when the upstream stream has been idle for longer than
    ``GUTTER_SLOW_SECONDS`` but has not yet been declared aborted.

    Purely informational — the chat layer propagates a
    ``ChatStreamSlowEvent`` and the frontend shows a subtle "model still
    working" hint until the next content or thinking delta arrives.
    """


class StreamAborted(BaseModel):
    """Emitted when the upstream stream has been idle for longer than
    ``GUTTER_ABORT_SECONDS``. The stream is dead — any previously
    accumulated content should be persisted with ``status="aborted"``.
    """

    reason: str = "gutter_timeout"


# Union type used as the return type for adapter stream generators.
ProviderStreamEvent = (
    ContentDelta
    | ThinkingDelta
    | ToolCallEvent
    | StreamDone
    | StreamError
    | StreamSlow
    | StreamAborted
)
```

Leave the existing classes untouched. The old single-line union definition gets replaced by the multi-line version above.

- [ ] **Step 4: Run the test and verify it passes**

```bash
uv run pytest tests/test_provider_stream_events.py -v
```

Expected: all tests in the file pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_events.py tests/test_provider_stream_events.py
git commit -m "$(cat <<'EOF'
Add StreamSlow and StreamAborted adapter events

Two new provider stream event types used by the Ollama adapter's
two-stage gutter state machine. Part of the stream-abort-handling
feature; subsequent tasks wire them into the adapter and inference
handler.
EOF
)"
```

---

## Task 2: Add `ChatStreamSlowEvent`, `CHAT_STREAM_SLOW` topic, extend `ChatStreamEndedEvent.status`

**Files:**
- Modify: `shared/events/chat.py`
- Modify: `shared/topics.py`
- Modify: `tests/test_shared_chat_contracts.py`

- [ ] **Step 1: Write the failing contract tests**

Append to `tests/test_shared_chat_contracts.py`:

```python
def test_chat_stream_slow_event_shape():
    from datetime import datetime, timezone
    from shared.events.chat import ChatStreamSlowEvent

    ev = ChatStreamSlowEvent(
        correlation_id="corr-1",
        timestamp=datetime.now(timezone.utc),
    )
    dumped = ev.model_dump(mode="json")
    assert dumped["type"] == "chat.stream.slow"
    assert dumped["correlation_id"] == "corr-1"
    assert "timestamp" in dumped


def test_chat_stream_ended_event_accepts_aborted_status():
    from datetime import datetime, timezone
    from shared.events.chat import ChatStreamEndedEvent

    ev = ChatStreamEndedEvent(
        correlation_id="corr-1",
        session_id="sess-1",
        status="aborted",
        context_status="green",
        timestamp=datetime.now(timezone.utc),
    )
    assert ev.status == "aborted"


def test_chat_stream_slow_topic_constant_matches_type():
    from shared.events.chat import ChatStreamSlowEvent
    from shared.topics import Topics

    assert Topics.CHAT_STREAM_SLOW == "chat.stream.slow"
    assert ChatStreamSlowEvent.model_fields["type"].default == Topics.CHAT_STREAM_SLOW
```

- [ ] **Step 2: Run and verify the tests fail**

```bash
uv run pytest tests/test_shared_chat_contracts.py -v
```

Expected: three new tests fail with `ImportError` / `AttributeError` / validation error on `"aborted"`.

- [ ] **Step 3: Add the new event class and topic constant**

Edit `shared/events/chat.py` — add a new class below `ChatStreamStartedEvent` (or near the other stream events):

```python
class ChatStreamSlowEvent(BaseModel):
    type: str = "chat.stream.slow"
    correlation_id: str
    timestamp: datetime
```

In the same file, modify `ChatStreamEndedEvent.status`:

```python
class ChatStreamEndedEvent(BaseModel):
    type: str = "chat.stream.ended"
    correlation_id: str
    session_id: str
    message_id: str | None = None
    status: Literal["completed", "cancelled", "error", "aborted"]
    usage: dict | None = None
    context_status: Literal["green", "yellow", "orange", "red"]
    context_fill_percentage: float = 0.0
    timestamp: datetime
```

Edit `shared/topics.py` — add the new constant in the "Chat inference" block, right after `CHAT_STREAM_ERROR`:

```python
    # Chat inference
    CHAT_STREAM_STARTED = "chat.stream.started"
    CHAT_CONTENT_DELTA = "chat.content.delta"
    CHAT_THINKING_DELTA = "chat.thinking.delta"
    CHAT_STREAM_ENDED = "chat.stream.ended"
    CHAT_STREAM_ERROR = "chat.stream.error"
    CHAT_STREAM_SLOW = "chat.stream.slow"
    CHAT_VISION_DESCRIPTION = "chat.vision.description"
```

- [ ] **Step 4: Run and verify the tests pass**

```bash
uv run pytest tests/test_shared_chat_contracts.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add shared/events/chat.py shared/topics.py tests/test_shared_chat_contracts.py
git commit -m "$(cat <<'EOF'
Add ChatStreamSlowEvent and extend ChatStreamEndedEvent.status with aborted

New "chat.stream.slow" topic for the two-stage gutter state machine and
a fourth literal on the stream-ended status for messages that were cut
off mid-stream. Both are consumed by subsequent tasks in this feature.
EOF
)"
```

---

## Task 3: Add `status` field to `ChatMessageDto`

**Files:**
- Modify: `shared/dtos/chat.py`
- Modify: `tests/test_shared_chat_contracts.py`

- [ ] **Step 1: Write the failing contract test**

Append to `tests/test_shared_chat_contracts.py`:

```python
def test_chat_message_dto_status_defaults_to_completed():
    from datetime import datetime, timezone
    from shared.dtos.chat import ChatMessageDto

    msg = ChatMessageDto(
        id="m1",
        session_id="s1",
        role="assistant",
        content="hi",
        token_count=1,
        created_at=datetime.now(timezone.utc),
    )
    assert msg.status == "completed"


def test_chat_message_dto_accepts_aborted_status():
    from datetime import datetime, timezone
    from shared.dtos.chat import ChatMessageDto

    msg = ChatMessageDto(
        id="m1",
        session_id="s1",
        role="assistant",
        content="partial answer",
        token_count=2,
        created_at=datetime.now(timezone.utc),
        status="aborted",
    )
    assert msg.status == "aborted"
```

- [ ] **Step 2: Run and verify the tests fail**

```bash
uv run pytest tests/test_shared_chat_contracts.py -v
```

Expected: both new tests fail with `AttributeError` / validation error.

- [ ] **Step 3: Add the field to the DTO**

Edit `shared/dtos/chat.py` — add the `status` field at the bottom of `ChatMessageDto`:

```python
class ChatMessageDto(BaseModel):
    id: str
    session_id: str
    role: Literal["user", "assistant", "tool"]
    content: str
    thinking: str | None = None
    token_count: int
    attachments: list[AttachmentRefDto] | None = None
    web_search_context: list[WebSearchContextItemDto] | None = None
    knowledge_context: list[dict] | None = None
    vision_descriptions_used: list[VisionDescriptionSnapshotDto] | None = None
    created_at: datetime
    status: Literal["completed", "aborted"] = "completed"
```

- [ ] **Step 4: Run and verify the tests pass**

```bash
uv run pytest tests/test_shared_chat_contracts.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add shared/dtos/chat.py tests/test_shared_chat_contracts.py
git commit -m "$(cat <<'EOF'
Add status field to ChatMessageDto

New optional "completed" | "aborted" literal with default "completed"
for aborted-stream detection. Legacy messages without the field are
defaulted on read by the repository layer in a later task.
EOF
)"
```

---

## Task 4: Rewrite Ollama adapter gutter loop as two-stage state machine

**Files:**
- Modify: `backend/modules/llm/_adapters/_ollama_base.py`
- Modify: `tests/test_ollama_stream_gutter.py`

Note: the existing test `test_gutter_timeout_aborts_stalled_stream` will break because the adapter no longer yields `StreamDone` on timeout. It will be **rewritten** to match the new behaviour, and two new scenarios are added.

- [ ] **Step 1: Rewrite the existing gutter test and add two scenarios**

Replace the entire contents of `tests/test_ollama_stream_gutter.py` with:

```python
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
```

- [ ] **Step 2: Run and verify the tests fail**

```bash
uv run pytest tests/test_ollama_stream_gutter.py -v
```

Expected: all three tests fail — the first two with `AttributeError` because `GUTTER_SLOW_SECONDS` and `GUTTER_ABORT_SECONDS` do not yet exist, the third likewise.

- [ ] **Step 3: Rewrite the streaming loop in the adapter**

Edit `backend/modules/llm/_adapters/_ollama_base.py`.

At the top of the file, change the imports and the timeout constants:

```python
import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from uuid import uuid4

import httpx

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._events import (
    ContentDelta,
    ProviderStreamEvent,
    StreamAborted,
    StreamDone,
    StreamError,
    StreamSlow,
    ThinkingDelta,
    ToolCallEvent,
)
from shared.dtos.inference import CompletionMessage, CompletionRequest
from shared.dtos.llm import ModelMetaDto

_log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=15.0)

# Two-stage NDJSON idle thresholds. At GUTTER_SLOW_SECONDS of silence we
# emit a StreamSlow (informational); at GUTTER_ABORT_SECONDS we give up
# and emit StreamAborted. Module-level so tests can monkey-patch them.
# The abort threshold is sourced from LLM_STREAM_ABORT_SECONDS so that
# operators can extend it without a code change.
GUTTER_SLOW_SECONDS: float = 30.0
GUTTER_ABORT_SECONDS: float = float(os.environ.get("LLM_STREAM_ABORT_SECONDS", "120"))
```

Note: the old `GUTTER_TIMEOUT_SECONDS` is removed. Also note the `import time` and `import os` additions.

Replace the streaming loop inside `stream_completion` (the block from `stream_iter = resp.aiter_lines().__aiter__()` through `break` at the end of the outer `while True:` block) with the following. Leave everything before `stream_iter = ...` and everything after the loop (including the tail `if not seen_done: yield StreamDone()`) exactly as it is.

```python
                stream_iter = resp.aiter_lines().__aiter__()
                line_start = time.monotonic()
                slow_fired = False

                while True:
                    elapsed = time.monotonic() - line_start
                    if slow_fired:
                        budget = GUTTER_ABORT_SECONDS - elapsed
                    else:
                        budget = GUTTER_SLOW_SECONDS - elapsed

                    if budget <= 0:
                        if not slow_fired:
                            _log.info(
                                "ollama_base.gutter_slow model=%s idle=%.1fs",
                                payload.get("model"), elapsed,
                            )
                            yield StreamSlow()
                            slow_fired = True
                            continue  # re-evaluate against the abort deadline
                        _log.warning(
                            "ollama_base.gutter_abort model=%s idle=%.1fs",
                            payload.get("model"), elapsed,
                        )
                        yield StreamAborted(reason="gutter_timeout")
                        return

                    try:
                        line = await asyncio.wait_for(
                            stream_iter.__anext__(), timeout=budget,
                        )
                    except asyncio.TimeoutError:
                        continue  # loop back, recompute budget
                    except StopAsyncIteration:
                        break

                    # Successful line — reset the window. slow_fired is
                    # cleared so a subsequent silence phase will re-announce.
                    # The frontend also clears its slow flag implicitly on
                    # any subsequent content/thinking delta.
                    line_start = time.monotonic()
                    slow_fired = False

                    line = line.strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        _log.warning("Skipping malformed NDJSON line: %s", line)
                        continue

                    if chunk.get("done"):
                        seen_done = True
                        yield StreamDone(
                            input_tokens=chunk.get("prompt_eval_count"),
                            output_tokens=chunk.get("eval_count"),
                        )
                        break

                    message = chunk.get("message", {})
                    thinking = message.get("thinking", "")
                    if thinking:
                        yield ThinkingDelta(delta=thinking)
                    content = message.get("content", "")
                    if content:
                        yield ContentDelta(delta=content)
                    for tc in message.get("tool_calls", []):
                        fn = tc.get("function", {})
                        yield ToolCallEvent(
                            id=f"call_{uuid4().hex[:12]}",
                            name=fn.get("name", ""),
                            arguments=json.dumps(fn.get("arguments", {})),
                        )
```

The `except asyncio.CancelledError` and `except httpx.ConnectError` blocks after the `async with` remain unchanged. The tail `if not seen_done: yield StreamDone()` after the function's `try`/`except` also remains unchanged — it still protects the `StopAsyncIteration`-before-`done=true` case.

- [ ] **Step 4: Run the gutter tests and verify they pass**

```bash
uv run pytest tests/test_ollama_stream_gutter.py -v
```

Expected: all three tests pass within ~3 seconds of wall-clock time.

- [ ] **Step 5: Run the broader adapter test suite to catch regressions**

```bash
uv run pytest tests/llm/test_ollama_base.py tests/test_ollama_cloud_adapter.py tests/test_ollama_cloud_streaming.py -v
```

Expected: all pre-existing tests still pass. If any test explicitly referenced the removed `GUTTER_TIMEOUT_SECONDS` constant, update it to use `GUTTER_SLOW_SECONDS` / `GUTTER_ABORT_SECONDS` as appropriate.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_adapters/_ollama_base.py tests/test_ollama_stream_gutter.py
git commit -m "$(cat <<'EOF'
Two-stage gutter state machine in Ollama adapter

Replace the single 30-second silent timeout with an explicit slow signal
at 30 seconds and a hard abort at a configurable 120 seconds
(LLM_STREAM_ABORT_SECONDS). The chat layer propagates these to the
frontend in a later task so users see an informative hint and a
recoverable error instead of a silently truncated response.
EOF
)"
```

---

## Task 5: Wire `StreamSlow` and `StreamAborted` into the inference handler

**Files:**
- Modify: `backend/modules/chat/_inference.py`
- Modify: `tests/test_inference_runner.py`

- [ ] **Step 1: Write the failing inference-runner tests**

Append to `tests/test_inference_runner.py`:

```python
async def test_stream_slow_propagates_as_chat_stream_slow_event(
    runner, mock_emit, mock_save,
):
    from backend.modules.llm._adapters._events import StreamSlow
    from shared.events.chat import ChatStreamSlowEvent

    stream_fn = _make_stream(
        ContentDelta(delta="partial "),
        StreamSlow(),
        ContentDelta(delta="recovered"),
        StreamDone(input_tokens=5, output_tokens=3),
    )

    await runner.run(
        user_id="user-1", session_id="sess-1", correlation_id="corr-1",
        stream_fn=stream_fn, emit_fn=mock_emit, save_fn=mock_save,
    )

    emitted = [call.args[0] for call in mock_emit.call_args_list]
    slow_events = [e for e in emitted if isinstance(e, ChatStreamSlowEvent)]
    assert len(slow_events) == 1
    assert slow_events[0].correlation_id == "corr-1"

    # Final status is still "completed" — StreamSlow is informational.
    from shared.events.chat import ChatStreamEndedEvent
    ended = [e for e in emitted if isinstance(e, ChatStreamEndedEvent)][0]
    assert ended.status == "completed"

    # Both content chunks made it into the saved message.
    save_args = mock_save.call_args
    assert save_args.kwargs["content"] == "partial recovered"
    assert save_args.kwargs["status"] == "completed"


async def test_stream_aborted_with_content_saves_as_aborted(
    runner, mock_emit, mock_save,
):
    from backend.modules.llm._adapters._events import StreamAborted
    from shared.events.chat import (
        ChatStreamEndedEvent,
        ChatStreamErrorEvent,
    )

    stream_fn = _make_stream(
        ContentDelta(delta="I was writing a "),
        StreamAborted(reason="gutter_timeout"),
    )

    await runner.run(
        user_id="user-1", session_id="sess-1", correlation_id="corr-1",
        stream_fn=stream_fn, emit_fn=mock_emit, save_fn=mock_save,
    )

    emitted = [call.args[0] for call in mock_emit.call_args_list]

    error_events = [e for e in emitted if isinstance(e, ChatStreamErrorEvent)]
    assert len(error_events) == 1
    assert error_events[0].error_code == "stream_aborted"
    assert error_events[0].recoverable is True

    ended = [e for e in emitted if isinstance(e, ChatStreamEndedEvent)][0]
    assert ended.status == "aborted"

    # The half-written content is persisted with status="aborted".
    save_args = mock_save.call_args
    assert save_args.kwargs["content"] == "I was writing a "
    assert save_args.kwargs["status"] == "aborted"


async def test_stream_aborted_without_content_does_not_save(
    runner, mock_emit, mock_save,
):
    from backend.modules.llm._adapters._events import StreamAborted
    from shared.events.chat import ChatStreamEndedEvent

    stream_fn = _make_stream(
        StreamAborted(reason="gutter_timeout"),
    )

    await runner.run(
        user_id="user-1", session_id="sess-1", correlation_id="corr-1",
        stream_fn=stream_fn, emit_fn=mock_emit, save_fn=mock_save,
    )

    mock_save.assert_not_awaited()
    ended = [
        call.args[0] for call in mock_emit.call_args_list
        if isinstance(call.args[0], ChatStreamEndedEvent)
    ][0]
    assert ended.status == "aborted"
```

- [ ] **Step 2: Run and verify the tests fail**

```bash
uv run pytest tests/test_inference_runner.py -v
```

Expected: all three new tests fail — the first two because `save_fn` is called without a `status` kwarg (so the assertions about `status` mismatch or fail); the third because the current `_inference.py` does not understand `StreamAborted`.

- [ ] **Step 3: Add the two new match branches and pass status to save_fn**

Edit `backend/modules/chat/_inference.py`.

Update the top-level import from the llm module to include the new event types:

```python
from backend.modules.llm import (
    ContentDelta,
    StreamAborted,
    StreamDone,
    StreamError,
    StreamSlow,
    ThinkingDelta,
    ToolCallEvent,
)
```

Update the import from `shared.events.chat` to include the new slow event:

```python
from shared.events.chat import (
    ChatContentDeltaEvent, ChatStreamEndedEvent, ChatStreamErrorEvent,
    ChatStreamSlowEvent, ChatStreamStartedEvent, ChatThinkingDeltaEvent,
    ChatToolCallCompletedEvent, ChatToolCallStartedEvent,
    ChatWebSearchContextEvent, WebSearchContextItem,
)
```

Note: `backend/modules/llm/__init__.py` currently re-exports `ContentDelta`, `StreamDone`, `StreamError`, `ThinkingDelta`, `ToolCallEvent` (see line 8 of `_inference.py`). You MUST also re-export `StreamSlow` and `StreamAborted` from that package's `__init__.py`. Open `backend/modules/llm/__init__.py`, find the existing re-export block, and add `StreamSlow`, `StreamAborted` to both the import and the `__all__` (or the module-level import chain — follow the existing pattern there).

Inside `_run_locked`, extend the `match event` block with two new cases (add them after `case StreamError()`):

```python
                        case StreamSlow():
                            await emit_fn(ChatStreamSlowEvent(
                                correlation_id=correlation_id,
                                timestamp=datetime.now(timezone.utc),
                            ))

                        case StreamAborted():
                            status = "aborted"
                            await emit_fn(ChatStreamErrorEvent(
                                correlation_id=correlation_id,
                                error_code="stream_aborted",
                                recoverable=True,
                                user_message="The response was interrupted. Please regenerate.",
                                timestamp=datetime.now(timezone.utc),
                            ))
```

Extend the break condition that currently reads `if cancelled or status == "error":` to also cover the aborted case:

```python
                if cancelled or status in ("error", "aborted"):
                    break
```

Finally, update the `save_fn` call at the bottom of the method to pass the status through. The current call is:

```python
        if full_content:
            message_id = await save_fn(
                content=full_content,
                thinking=full_thinking or None,
                usage=usage,
                web_search_context=web_search_context or None,
                knowledge_context=knowledge_context or None,
            )
```

Change it to:

```python
        if full_content:
            message_id = await save_fn(
                content=full_content,
                thinking=full_thinking or None,
                usage=usage,
                web_search_context=web_search_context or None,
                knowledge_context=knowledge_context or None,
                status="aborted" if status == "aborted" else "completed",
            )
```

- [ ] **Step 4: Run and verify the tests pass**

```bash
uv run pytest tests/test_inference_runner.py -v
```

Expected: all tests in the file pass, including the three new ones.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/_inference.py backend/modules/llm/__init__.py tests/test_inference_runner.py
git commit -m "$(cat <<'EOF'
Handle StreamSlow and StreamAborted in chat inference runner

Propagate slow signals as ChatStreamSlowEvent, mark aborted streams
with status='aborted', emit a recoverable stream-error event on abort,
and persist partial content with the new status literal for later
context filtering.
EOF
)"
```

---

## Task 6: Extend `save_message` and `message_to_dto` with the status field

**Files:**
- Modify: `backend/modules/chat/_repository.py`
- Modify: `tests/test_chat_repository.py`

- [ ] **Step 1: Write the failing repository tests**

Append to `tests/test_chat_repository.py`:

```python
async def test_save_message_with_aborted_status(repo):
    session = await repo.create_session("user-1", "p-1", "ollama_cloud:m")
    sid = session["_id"]
    await repo.save_message(
        session_id=sid, role="assistant", content="partial", token_count=1,
        status="aborted",
    )
    msgs = await repo.list_messages(sid)
    assert len(msgs) == 1
    assert msgs[0]["status"] == "aborted"
    dto = repo.message_to_dto(msgs[0])
    assert dto.status == "aborted"


async def test_legacy_message_without_status_defaults_to_completed(repo):
    session = await repo.create_session("user-1", "p-1", "ollama_cloud:m")
    sid = session["_id"]
    # Simulate a legacy document: save without the new status field by
    # calling insert_one directly so we bypass save_message's default.
    from datetime import UTC, datetime
    from uuid import uuid4
    await repo._messages.insert_one({
        "_id": str(uuid4()),
        "session_id": sid,
        "role": "assistant",
        "content": "legacy",
        "thinking": None,
        "token_count": 1,
        "created_at": datetime.now(UTC),
    })
    msgs = await repo.list_messages(sid)
    assert len(msgs) == 1
    # Repo returns raw dicts from MongoDB; DTO conversion must default.
    dto = repo.message_to_dto(msgs[0])
    assert dto.status == "completed"
```

- [ ] **Step 2: Run and verify the tests fail**

```bash
uv run pytest tests/test_chat_repository.py -v
```

Expected: both new tests fail — the first with `TypeError: save_message() got an unexpected keyword argument 'status'`, the second with `AttributeError` on `dto.status`.

- [ ] **Step 3: Extend the repository**

Edit `backend/modules/chat/_repository.py`.

Add the import at the top (near the other `typing` imports):

```python
from typing import Literal
```

Update `save_message`'s signature and body — add the `status` kwarg and persist it:

```python
    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        token_count: int,
        thinking: str | None = None,
        web_search_context: list[dict] | None = None,
        knowledge_context: list[dict] | None = None,
        attachment_ids: list[str] | None = None,
        attachment_refs: list[dict] | None = None,
        vision_descriptions_used: list[dict] | None = None,
        status: Literal["completed", "aborted"] = "completed",
    ) -> dict:
        now = datetime.now(UTC)
        doc = {
            "_id": str(uuid4()),
            "session_id": session_id,
            "role": role,
            "content": content,
            "thinking": thinking,
            "token_count": token_count,
            "created_at": now,
            "status": status,
        }
        if web_search_context:
            doc["web_search_context"] = web_search_context
        if knowledge_context:
            doc["knowledge_context"] = knowledge_context
        if attachment_ids:
            doc["attachment_ids"] = attachment_ids
        if attachment_refs:
            doc["attachment_refs"] = attachment_refs
        if vision_descriptions_used:
            doc["vision_descriptions_used"] = vision_descriptions_used
        await self._messages.insert_one(doc)
        return doc
```

Update `message_to_dto` to read the field with a sensible default. Change the final `return ChatMessageDto(...)` block at the end of `message_to_dto` to include:

```python
        return ChatMessageDto(
            id=doc["_id"],
            session_id=doc["session_id"],
            role=doc["role"],
            content=doc["content"],
            thinking=doc.get("thinking"),
            token_count=doc["token_count"],
            attachments=attachments,
            web_search_context=ws_ctx,
            knowledge_context=doc.get("knowledge_context"),
            vision_descriptions_used=vision_snaps,
            created_at=doc["created_at"],
            status=doc.get("status", "completed"),
        )
```

- [ ] **Step 4: Run and verify the tests pass**

```bash
uv run pytest tests/test_chat_repository.py -v
```

Expected: all tests in the file pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/_repository.py tests/test_chat_repository.py
git commit -m "$(cat <<'EOF'
Persist message status in ChatRepository

New status="completed"|"aborted" kwarg on save_message, stored directly
on the document, and defaulted to "completed" in message_to_dto so
legacy documents written before this change continue to render as
normal messages.
EOF
)"
```

---

## Task 7: Orchestrator `save_fn` signature and aborted context filter

**Files:**
- Modify: `backend/modules/chat/_orchestrator.py`

This task has no new unit test because:
- The `save_fn` closure is exercised by `tests/test_inference_runner.py` via the `status` kwarg assertions added in Task 5 (those tests fail until this task is complete, because the orchestrator's `save_fn` wraps `repo.save_message` and must accept the new kwarg).
- The context filter is a four-line list comprehension; it is exercised by manual verification (step 6 below) because writing an isolated integration test for `run_inference` would require mocking half of the chat module.

- [ ] **Step 1: Extend the inner `save_fn` closure to accept and forward `status`**

Edit `backend/modules/chat/_orchestrator.py`. Around line 476, update the nested `save_fn`:

```python
    async def save_fn(
        content: str,
        thinking: str | None,
        usage: dict | None,
        web_search_context: list[dict] | None = None,
        knowledge_context: list[dict] | None = None,
        status: Literal["completed", "aborted"] = "completed",
    ) -> str | None:
        token_count = count_tokens(content)
        doc = await repo.save_message(
            session_id,
            role="assistant",
            content=content,
            token_count=token_count,
            thinking=thinking,
            web_search_context=web_search_context,
            knowledge_context=knowledge_context,
            status=status,
        )
        await repo.update_session_state(session_id, "idle")
        # ... existing title-generation trigger logic unchanged ...
        return doc["_id"]
```

Leave the title-generation block (the `if not session.get("title")` branch that follows) exactly as it is.

Ensure `Literal` is imported at the top of the file. If `from typing import Literal` is not already present, add it.

- [ ] **Step 2: Add the aborted-status context filter**

Still in `_orchestrator.py`, locate the line that currently reads `history_docs = await repo.list_messages(session_id)` (around line 305 inside `run_inference`). Immediately after that line, insert:

```python
    history_docs = await repo.list_messages(session_id)
    # Aborted assistant messages pollute the LLM context with
    # half-finished thoughts or truncated code — strip them before
    # context pair selection. The matching user prompts remain in place
    # so a regenerate still has the user's input to work with.
    history_docs = [
        d for d in history_docs
        if d.get("status", "completed") != "aborted"
    ]
```

Do NOT move or duplicate the `history_docs` assignment. The filter replaces the assigned list in place.

- [ ] **Step 3: Run the inference-runner tests from Task 5 to confirm save_fn integration**

```bash
uv run pytest tests/test_inference_runner.py -v
```

Expected: all tests pass. This confirms the inference handler's `save_fn(..., status=...)` call reaches a closure that knows the kwarg. (If this still fails, it means Task 5 was committed before Task 7 — check that the closure signature matches.)

- [ ] **Step 4: Run the full orchestrator-adjacent test suite for regressions**

```bash
uv run pytest tests/test_chat_orchestrator_vision_fallback.py tests/test_inference_runner.py tests/test_chat_repository.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Syntax-check the modified file**

```bash
uv run python -m py_compile backend/modules/chat/_orchestrator.py
```

Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/chat/_orchestrator.py
git commit -m "$(cat <<'EOF'
Forward aborted status through save_fn and filter aborted history

The orchestrator's inner save_fn closure now accepts the new status
kwarg and passes it to repo.save_message. Before context pair selection
in run_inference, aborted assistant messages are filtered out so they
cannot pollute future LLM calls — matching user prompts stay in place
so regenerate still has input to work with.
EOF
)"
```

---

## Task 8: Frontend `ChatMessageDto` and `Topics` extensions

**Files:**
- Modify: `frontend/src/core/api/chat.ts`
- Modify: `frontend/src/core/types/events.ts`

Frontend tests for these two shallow changes live in Task 9 (store) and Task 11 (components). This task is type-only.

- [ ] **Step 1: Extend the `ChatMessageDto` interface**

Edit `frontend/src/core/api/chat.ts`. Update the `ChatMessageDto` interface:

```ts
interface ChatMessageDto {
  id: string
  session_id: string
  role: "user" | "assistant" | "tool"
  content: string
  thinking: string | null
  token_count: number
  attachments: AttachmentRefDto[] | null
  web_search_context: WebSearchContextItem[] | null
  knowledge_context: RetrievedChunkDto[] | null
  vision_descriptions_used?: VisionDescriptionSnapshot[] | null
  created_at: string
  status?: "completed" | "aborted"
}
```

The field is optional on the TS side so backends that do not yet emit it (cached redis events, stale deployments) still typecheck. The default for missing values is handled in the rendering component.

- [ ] **Step 2: Add the `CHAT_STREAM_SLOW` topic constant**

Edit `frontend/src/core/types/events.ts`. Inside the `Topics` object, add the new constant right next to the other stream topics:

```ts
  CHAT_STREAM_STARTED: "chat.stream.started",
  CHAT_CONTENT_DELTA: "chat.content.delta",
  CHAT_THINKING_DELTA: "chat.thinking.delta",
  CHAT_STREAM_ENDED: "chat.stream.ended",
  CHAT_STREAM_ERROR: "chat.stream.error",
  CHAT_STREAM_SLOW: "chat.stream.slow",
```

- [ ] **Step 3: Typecheck**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: no errors. If there are errors, they likely originate from other files that will be updated in later tasks — note them, and re-run after Task 11.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/core/api/chat.ts frontend/src/core/types/events.ts
git commit -m "$(cat <<'EOF'
Mirror status field and stream.slow topic on the frontend side

Optional "completed"|"aborted" status on ChatMessageDto plus the new
CHAT_STREAM_SLOW topic constant. Used by the chat store and UI in
subsequent tasks.
EOF
)"
```

---

## Task 9: Chat store — `streamingSlow` state and implicit clearing

**Files:**
- Modify: `frontend/src/core/store/chatStore.ts`
- Modify: `frontend/src/features/chat/__tests__/chatStore.test.ts`

- [ ] **Step 1: Write the failing store tests**

Append to `frontend/src/features/chat/__tests__/chatStore.test.ts` (inside the existing test suite / describe block; match the file's existing style):

```ts
describe('streamingSlow lifecycle', () => {
  it('defaults to false', () => {
    const store = useChatStore.getState()
    expect(store.streamingSlow).toBe(false)
  })

  it('can be set to true via setStreamingSlow', () => {
    useChatStore.getState().setStreamingSlow(true)
    expect(useChatStore.getState().streamingSlow).toBe(true)
  })

  it('clears on appendStreamingContent', () => {
    useChatStore.getState().setStreamingSlow(true)
    useChatStore.getState().appendStreamingContent('hi')
    expect(useChatStore.getState().streamingSlow).toBe(false)
  })

  it('clears on appendStreamingThinking', () => {
    useChatStore.getState().setStreamingSlow(true)
    useChatStore.getState().appendStreamingThinking('thought')
    expect(useChatStore.getState().streamingSlow).toBe(false)
  })

  it('is reset by startStreaming', () => {
    useChatStore.getState().setStreamingSlow(true)
    useChatStore.getState().startStreaming('corr-2')
    expect(useChatStore.getState().streamingSlow).toBe(false)
  })

  it('is cleared by cancelStreaming', () => {
    useChatStore.getState().setStreamingSlow(true)
    useChatStore.getState().cancelStreaming()
    expect(useChatStore.getState().streamingSlow).toBe(false)
  })
})
```

If there is no existing `describe` for chatStore in that file, wrap the new tests in their own:

```ts
import { describe, it, expect, beforeEach } from 'vitest'
import { useChatStore } from '../../../core/store/chatStore'

describe('chatStore streamingSlow lifecycle', () => {
  beforeEach(() => {
    useChatStore.getState().reset()
  })

  // ... tests above ...
})
```

Match the import paths the file already uses for `useChatStore` — do not introduce a new path.

- [ ] **Step 2: Run and verify the tests fail**

```bash
cd frontend && pnpm vitest run src/features/chat/__tests__/chatStore.test.ts
```

Expected: the six new tests fail with `setStreamingSlow is not a function` / `streamingSlow` being undefined.

- [ ] **Step 3: Add the state and action to the store**

Edit `frontend/src/core/store/chatStore.ts`.

Extend the `ChatState` interface — add two new fields right after `error`:

```ts
interface ChatState {
  // ... existing fields up to and including `error: ChatError | null` ...
  streamingSlow: boolean
  // ... existing fields continuing with `sessionTitle: string | null`, etc. ...
  setStreamingSlow: (slow: boolean) => void
}
```

Extend the `INITIAL_STATE` constant:

```ts
const INITIAL_STATE = {
  // ... existing fields ...
  error: null as ChatError | null,
  streamingSlow: false,
  // ... rest ...
}
```

Extend the existing actions that must implicitly clear the slow flag. Each change is inside `create<ChatState>(...)`:

```ts
  startStreaming: (correlationId) =>
    set({
      isWaitingForResponse: false, isStreaming: true, correlationId,
      streamingContent: '', streamingThinking: '',
      streamingWebSearchContext: [], streamingKnowledgeContext: [],
      activeToolCalls: [], visionDescriptions: {}, error: null,
      streamingSlow: false,
    }),
  appendStreamingContent: (delta) =>
    set((s) => ({
      streamingContent: s.streamingContent + delta,
      streamingSlow: false,
    })),
  appendStreamingThinking: (delta) =>
    set((s) => ({
      streamingThinking: s.streamingThinking + delta,
      streamingSlow: false,
    })),
```

Extend `finishStreaming` and `cancelStreaming` to clear the flag as well — add `streamingSlow: false` to each of their `set(...)` payloads.

Add the new action itself, next to `setError`:

```ts
  setStreamingSlow: (slow) => set({ streamingSlow: slow }),
```

- [ ] **Step 4: Run and verify the tests pass**

```bash
cd frontend && pnpm vitest run src/features/chat/__tests__/chatStore.test.ts
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/store/chatStore.ts frontend/src/features/chat/__tests__/chatStore.test.ts
git commit -m "$(cat <<'EOF'
Add streamingSlow state to chatStore

New boolean that the UI uses to show a "model still working" hint.
Cleared implicitly by the existing append/start/finish/cancel actions
so handlers do not need explicit clearing logic.
EOF
)"
```

---

## Task 10: `useChatStream` — slow handler, error toast, status propagation

**Files:**
- Modify: `frontend/src/features/chat/useChatStream.ts`

No unit test for this task — the hook lives inside React's effect machinery and has no existing test harness. Changes here are verified through Task 13's manual scenarios.

- [ ] **Step 1: Add imports for notification store and sendMessage**

At the top of `frontend/src/features/chat/useChatStream.ts`, alongside the existing imports:

```ts
import { useNotificationStore } from '../../core/store/notificationStore'
import { sendMessage } from '../../core/websocket/connection'
```

- [ ] **Step 2: Add the `CHAT_STREAM_SLOW` case**

Inside the `switch (event.type)` block, add a new case next to `CHAT_THINKING_DELTA`:

```ts
        case Topics.CHAT_STREAM_SLOW: {
          if (event.correlation_id !== getStore().correlationId) return
          getStore().setStreamingSlow(true)
          break
        }
```

- [ ] **Step 3: Extend the `CHAT_STREAM_ERROR` handler to dispatch a toast**

Replace the existing `case Topics.CHAT_STREAM_ERROR:` block with the following. The block preserves all current behaviour (setting the error, clearing lock state, handling session-level codes) and adds a toast dispatch for every error that is NOT a session-level banner code:

```ts
        case Topics.CHAT_STREAM_ERROR: {
          getStore().clearWaitingForLock()
          const errorCode = p.error_code as string
          // Session-level errors arrive outside a streaming context —
          // they carry their own correlation id that the frontend never
          // saw, so we let them through unconditionally. This includes
          // rejections from handle_chat_edit that fire before any stream
          // has started (invalid_edit, session_busy, edit_target_missing,
          // edit_failed).
          const sessionLevelCodes = new Set([
            'session_expired',
            'invalid_edit',
            'edit_target_missing',
            'edit_failed',
          ])
          const isSessionError = sessionLevelCodes.has(errorCode)
          if (!isSessionError && event.correlation_id !== getStore().correlationId) return

          const recoverable = p.recoverable as boolean
          const userMessage = p.user_message as string
          getStore().setError({
            errorCode,
            recoverable,
            userMessage,
          })
          getStore().setWaitingForResponse(false)

          // Session-level errors have their own banner path (ChatView
          // renders them inline above the composer); everything else
          // surfaces through the toast system for visibility, with an
          // inline regenerate action when the error is recoverable.
          if (!isSessionError) {
            const sessionIdAtError = sessionId
            useNotificationStore.getState().addNotification({
              level: 'error',
              title: recoverable ? 'Response interrupted' : 'Error',
              message: userMessage,
              action: recoverable && sessionIdAtError
                ? {
                    label: 'Regenerate',
                    onClick: () => {
                      sendMessage({
                        type: 'chat.regenerate',
                        session_id: sessionIdAtError,
                      })
                    },
                  }
                : undefined,
            })
          }
          break
        }
```

The `sessionIdAtError` local is captured from the hook's closure so a later session switch cannot misroute the regenerate command.

- [ ] **Step 4: Capture `status` on the finalised message in `CHAT_STREAM_ENDED`**

Still in `useChatStream.ts`, find the `CHAT_STREAM_ENDED` handler and update the `finishStreaming` call so the constructed `ChatMessageDto` includes the status from the backend payload. Replace the existing `finishStreaming` call body:

```ts
          const backendMessageId = p.message_id as string | undefined
          const status = (p.status as 'completed' | 'cancelled' | 'error' | 'aborted') ?? 'completed'
          const messageStatus: 'completed' | 'aborted' =
            status === 'aborted' ? 'aborted' : 'completed'
          const content = getStore().streamingContent
          const thinking = getStore().streamingThinking
          const webSearchContext = getStore().streamingWebSearchContext
          const knowledgeContext = getStore().streamingKnowledgeContext
          if (backendMessageId && (content || thinking)) {
            getStore().finishStreaming(
              {
                id: backendMessageId,
                session_id: sessionId,
                role: 'assistant',
                content,
                thinking: thinking || null,
                token_count: 0,
                attachments: null,
                web_search_context: webSearchContext.length > 0 ? webSearchContext : null,
                knowledge_context: knowledgeContext.length > 0 ? knowledgeContext : null,
                created_at: new Date().toISOString(),
                status: messageStatus,
              },
              contextStatus,
              fillPercentage,
            )
          } else {
            getStore().cancelStreaming()
          }
```

- [ ] **Step 5: Typecheck**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: no errors in `useChatStream.ts`. (Downstream component errors about `status` on `AssistantMessage`/`MessageList` will appear and are resolved in Task 11.)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/chat/useChatStream.ts
git commit -m "$(cat <<'EOF'
Surface stream slow, aborted status, and error toasts in useChatStream

New CHAT_STREAM_SLOW handler flipping the store flag, CHAT_STREAM_ERROR
now dispatches an error toast (with inline Regenerate action when
recoverable), and the finalised message on CHAT_STREAM_ENDED inherits
the backend status so the UI can badge aborted replies.
EOF
)"
```

---

## Task 11: `AssistantMessage` warning band and `MessageList` slow hint

**Files:**
- Modify: `frontend/src/features/chat/AssistantMessage.tsx`
- Modify: `frontend/src/features/chat/MessageList.tsx`

- [ ] **Step 1: Extend `AssistantMessage` with a `status` prop and warning band**

Edit `frontend/src/features/chat/AssistantMessage.tsx`.

Update the props interface:

```ts
interface AssistantMessageProps {
  content: string
  thinking: string | null
  isStreaming: boolean
  accentColour: string
  highlighter: Highlighter | null
  isBookmarked?: boolean
  onBookmark?: () => void
  canRegenerate?: boolean
  onRegenerate?: () => void
  status?: 'completed' | 'aborted'
}
```

Update the function signature to destructure the new prop with a default:

```ts
export function AssistantMessage({
  content, thinking, isStreaming, accentColour, highlighter,
  isBookmarked, onBookmark, canRegenerate, onRegenerate,
  status = 'completed',
}: AssistantMessageProps) {
```

Inside the JSX, directly after the closing `</div>` of `<div className="chat-text chat-prose text-white/80">...</div>` (the block containing `<ReactMarkdown>`), insert the warning band. It appears before the action-button row:

```tsx
        {status === 'aborted' && !isStreaming && (
          <div className="mt-2 flex items-start gap-2 rounded-md border border-amber-400/30 bg-amber-400/5 px-3 py-2">
            <svg
              width="14" height="14" viewBox="0 0 14 14" fill="none"
              className="text-amber-400 mt-0.5 shrink-0"
              aria-hidden="true"
            >
              <path
                d="M7 1.5L13 12.5H1L7 1.5Z"
                stroke="currentColor" strokeWidth="1.2"
                strokeLinecap="round" strokeLinejoin="round"
              />
              <path
                d="M7 5.5V8.5M7 10.5V10.51"
                stroke="currentColor" strokeWidth="1.4"
                strokeLinecap="round"
              />
            </svg>
            <div className="text-[11px] leading-snug text-amber-200/90">
              This response was interrupted and may be incomplete.
              Click <strong>Regenerate</strong> to produce a fresh response.
            </div>
          </div>
        )}
```

The `!isStreaming` guard prevents the band from flickering in if a live stream somehow enters an aborted state mid-render — only persisted aborted messages (loaded from history or just finalised) ever render it.

- [ ] **Step 2: Forward `msg.status` from `MessageList` to `AssistantMessage`**

Edit `frontend/src/features/chat/MessageList.tsx`. Find the `AssistantMessage` render at lines 128-131 (inside the `messages.map` body, in the `msg.role === 'assistant'` branch):

```tsx
                <AssistantMessage content={msg.content} thinking={msg.thinking}
                  isStreaming={false} accentColour={accentColour} highlighter={highlighter}
                  isBookmarked={isBm} onBookmark={() => onBookmark(msg.id)}
                  canRegenerate={canRegenerate && i === lastAssistantIdx} onRegenerate={onRegenerate}
                  status={msg.status ?? 'completed'} />
```

The `?? 'completed'` covers legacy DTOs loaded from the server that may not carry the new field.

- [ ] **Step 3: Add the slow hint inside the streaming block**

Still in `MessageList.tsx`, find the existing `{isStreaming && (` block (the one that renders `activeToolCalls`, streaming pills, and the live content). At the top of `useChatStore` subscriptions (around line 56 where `visionDescriptions` is pulled via selector), add a new selector:

```tsx
  const streamingSlow = useChatStore((s) => s.streamingSlow)
```

Then, inside the `{isStreaming && (...)}` block, immediately after the streaming `<AssistantMessage>` / `<StreamingIndicator>` render and before the closing `</div>`, add the hint:

```tsx
            {streamingSlow && (
              <div className="mt-1 text-[11px] italic text-white/45">
                Model still working…
              </div>
            )}
```

- [ ] **Step 4: Typecheck**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 5: Production build to verify the whole frontend pipeline**

```bash
cd frontend && pnpm run build
```

Expected: clean build, no type errors, no missing imports.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/chat/AssistantMessage.tsx frontend/src/features/chat/MessageList.tsx
git commit -m "$(cat <<'EOF'
Add aborted warning band and slow hint to chat UI

Amber warning band on persisted aborted assistant messages with an
explicit pointer to the Regenerate button, plus a subtle "Model still
working…" line during the slow phase of a live stream. Both are
deliberately low-key to stay calm during recoverable hiccups.
EOF
)"
```

---

## Task 12: Environment variable documentation

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Add the variable to `.env.example`**

Edit `.env.example`. Add a new block near the Ollama-related variables (after `OLLAMA_LOCAL_BASE_URL`):

```
# Maximum idle time in seconds on the LLM upstream stream before we
# declare it aborted. Must be larger than 30 (the hard-coded slow-phase
# threshold). Increase if you use large cloud models on slow providers.
LLM_STREAM_ABORT_SECONDS=120
```

- [ ] **Step 2: Document the variable in `README.md`**

Edit `README.md`. Find the environment-variables table that starts around line 167 (the section titled `## Environment Variables`). Add a new row in the same table format the existing entries use (match columns and style):

```
| `LLM_STREAM_ABORT_SECONDS` | Maximum idle time in seconds the LLM upstream stream may stay silent before we declare it aborted and surface an error toast. Must be larger than 30 (the hard-coded slow-phase threshold). Increase if you use large cloud models on slow providers. | `120` |
```

If there is a second, more detailed table later in the file (the one that includes `OLLAMA_CLOUD_EMERGENCY_STOP` at line 194), add a similar row there too with the extra operator-guidance column:

```
| `LLM_STREAM_ABORT_SECONDS` | Idle-timeout before a silent LLM stream is aborted. | `120` | Positive integer (seconds); must exceed 30 | Increase if long artefact generations trip the abort on slow cloud providers. |
```

- [ ] **Step 3: Commit**

```bash
git add .env.example README.md
git commit -m "$(cat <<'EOF'
Document LLM_STREAM_ABORT_SECONDS environment variable

Adds the new tunable for the Ollama adapter's hard abort deadline to
both .env.example and the README environment-variable tables. Default
is 120 seconds.
EOF
)"
```

---

## Task 13: Full-stack verification and manual checklist

**Files:** none (verification task)

- [ ] **Step 1: Syntax-check every modified backend file**

```bash
uv run python -m py_compile \
  backend/modules/llm/_adapters/_events.py \
  backend/modules/llm/_adapters/_ollama_base.py \
  backend/modules/llm/__init__.py \
  backend/modules/chat/_inference.py \
  backend/modules/chat/_repository.py \
  backend/modules/chat/_orchestrator.py \
  shared/events/chat.py \
  shared/topics.py \
  shared/dtos/chat.py
```

Expected: no output from any file.

- [ ] **Step 2: Run the backend test suites touched by this feature**

```bash
uv run pytest \
  tests/test_provider_stream_events.py \
  tests/test_shared_chat_contracts.py \
  tests/test_ollama_stream_gutter.py \
  tests/test_inference_runner.py \
  tests/test_chat_repository.py \
  tests/test_chat_orchestrator_vision_fallback.py \
  -v
```

Expected: all tests pass.

- [ ] **Step 3: Run the full backend test suite to catch regressions**

```bash
uv run pytest tests/ -x
```

Expected: all tests pass. If any pre-existing test breaks because it referenced the removed `GUTTER_TIMEOUT_SECONDS` constant or called `save_message` positionally with the wrong argument count, fix the test to use the new names / signature and re-run.

- [ ] **Step 4: Run the frontend test suite**

```bash
cd frontend && pnpm vitest run
```

Expected: all tests pass, including the new `chatStore` streamingSlow tests.

- [ ] **Step 5: Production frontend build**

```bash
cd frontend && pnpm run build
```

Expected: clean build, no TypeScript errors.

- [ ] **Step 6: Manual scenario — happy path regression**

Start the backend and frontend. Send a normal chat message with a short expected reply (e.g. "What is 2+2?"). Verify:

- The slow hint is **never shown** during the short stream.
- No warning band appears on the response.
- No toast is raised.

- [ ] **Step 7: Manual scenario — simulated silence forces slow + abort**

Temporarily set the abort deadline low for testing. In the running backend environment, set `LLM_STREAM_ABORT_SECONDS=5` and restart. Using the LLM harness, or a manually crafted request against a hanging mock, induce a silence longer than 30 s (you will need a debug override for `GUTTER_SLOW_SECONDS` too — set it to `2.0` at the top of `_ollama_base.py` temporarily, or hit a model that is known to stall under load).

Verify:

- After the slow threshold, the "Model still working…" hint appears subtly below the streaming bubble.
- After the abort threshold, an error toast pops up with title "Response interrupted" and message "The response was interrupted. Please regenerate."
- The toast contains a **Regenerate** action button.
- Clicking the button triggers a new inference in the same session.
- The partial content (if any) remains visible in the chat with an amber warning band below it.

After the scenario, revert the debug overrides and restart.

- [ ] **Step 8: Manual scenario — refresh preserves the warning band**

After step 7, with an aborted message visible, refresh the browser tab. Verify:

- The aborted message still renders with the amber warning band.
- The band disappears if you regenerate and the replacement succeeds.

- [ ] **Step 9: Manual scenario — context filter drops aborted assistant**

Still in the session from step 7, send a new user message (without regenerating first). In the backend logs, inspect the LLM request payload (grep for the outbound `/api/chat` call, e.g. `backend | grep "ollama_base\|LLM call"`). Verify:

- The aborted assistant message does NOT appear in the `messages` array sent upstream.
- The user prompt that preceded the aborted reply **does** still appear.

- [ ] **Step 10: Manual scenario — error toast without content**

Temporarily set an invalid Ollama API key in the running instance. Try to send a chat message. Verify:

- A toast with title "Error" (not "Response interrupted") appears.
- The toast has no action button (error is not recoverable).
- No warning-band message is added to the chat history (nothing to persist).

Restore the valid key after the scenario.

- [ ] **Step 11: Final commit of any incidental fixes**

If steps 6-10 required any small follow-up fixes (e.g. a test that used the removed constant), commit them with a descriptive message. Otherwise, skip this step.

- [ ] **Step 12: Merge to master**

Per project defaults in `CLAUDE.md` ("Please always merge to master after implementation"), and assuming the execution mode was a branch or worktree:

```bash
git log --oneline -20   # sanity check the commit sequence
git checkout master
git merge --no-ff <feature-branch>
```

If the work was done directly on master through the subagent loop, skip the merge and simply confirm the log is clean.

---

## Risks & Reminders

- The existing `tests/test_ollama_stream_gutter.py` IS broken by Task 4's adapter rewrite. Task 4 Step 1 REPLACES the file contents entirely — do not try to patch the old test alongside the new behaviour. The new content is the full file.
- If `backend/modules/llm/__init__.py` does not currently re-export every stream event, Task 5 Step 3 notes that `StreamSlow` and `StreamAborted` must be added to the re-export block. Miss this and `_inference.py` will fail to import.
- `Literal` must be imported into `_repository.py` and `_orchestrator.py` if not already present. Task 6 and Task 7 flag this, but an agent executing out of order might miss it.
- `LLM_STREAM_ABORT_SECONDS` is read at module import time. A test that wants a different abort deadline must monkey-patch the `GUTTER_ABORT_SECONDS` constant directly (as Task 4's tests do), not set the env var after import.
- The toast's inline Regenerate button sends `chat.regenerate` which is the standard (non-incognito) path. Incognito sessions have their own handler in `ChatView.handleRegenerate`, and the toast button does NOT handle that case. This is an accepted limitation — incognito users can still click the in-message Regenerate button.
- Do NOT commit without explicit user approval of this plan first. The commits in each task are scoped to that task's changes only (`git add <exact paths>`), never `git add -A`.

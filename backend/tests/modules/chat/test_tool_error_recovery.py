"""Tests for the inference loop's recovery path on tool-related errors.

Covers two failure modes that must NOT abort the stream:
- The model emits a tool call whose name has no registered executor
  (``ToolNotFoundError``).
- The model emits a tool call whose ``arguments`` is not valid JSON
  (``json.JSONDecodeError``).

In both cases the loop must:
- continue to a follow-up iteration so the model can self-correct;
- feed a short, actionable error back as the tool result;
- emit a ``ChatToolCallCompletedEvent`` with ``success=False``;
- record a generic ``tool_call`` timeline entry with ``success=False``;
- persist whatever content / thinking the user already saw — even when
  the per-iteration content reset zeroed ``full_content``.

Also covers the persistence guard's new ``full_thinking``-only branch
and the existing ``full_content``-with-error branch.
"""

import asyncio
import json

import pytest

from backend.modules.chat._inference import InferenceRunner
from backend.modules.llm import (
    ContentDelta,
    StreamDone,
    ThinkingDelta,
    ToolCallEvent,
)
from backend.modules.tools import ToolNotFoundError
from shared.dtos.chat import TimelineEntryToolCall
from shared.events.chat import (
    ChatStreamEndedEvent,
    ChatToolCallCompletedEvent,
    ChatToolCallStartedEvent,
)


# ---------------------------------------------------------------------------
# Test scaffolding
# ---------------------------------------------------------------------------


async def _async_iter(events):
    """Yield each event in turn from a regular list as an async iterable."""
    for ev in events:
        yield ev


def _make_stream_fn(scripted_iterations):
    """Return a stream_fn whose successive invocations yield successive
    pre-scripted iteration event lists."""
    state = {"i": 0}

    async def stream_fn(_extra_messages):
        idx = state["i"]
        state["i"] += 1
        events = scripted_iterations[idx] if idx < len(scripted_iterations) else []
        return _async_iter(events)

    return stream_fn


def _make_emit_capture():
    captured: list = []

    async def emit(event):
        captured.append(event)

    return captured, emit


def _make_save_capture():
    captured: dict = {}

    async def save(*, content, thinking, usage, events, refusal_text, status):
        captured["content"] = content
        captured["thinking"] = thinking
        captured["usage"] = usage
        captured["events"] = events
        captured["refusal_text"] = refusal_text
        captured["status"] = status
        captured["called"] = True
        return "msg-id-1"

    return captured, save


# ---------------------------------------------------------------------------
# Test 1 — unknown tool keeps the stream alive and feeds the error back
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_tool_recovers_and_continues_loop() -> None:
    """An unknown tool name must NOT terminate the run.

    The loop should mark the call as failed, append a tool-result message
    explaining the error, fire a follow-up iteration, and persist the
    final content the user sees.
    """
    iter_one = [
        ContentDelta(delta="Hello, "),
        ContentDelta(delta="I will use a tool."),
        ToolCallEvent(id="call_1", name="xyz_unknown", arguments='{"q":"x"}'),
        StreamDone(input_tokens=10, output_tokens=20),
    ]
    iter_two = [
        ContentDelta(delta="Sorry, I cannot do that — final answer."),
        StreamDone(input_tokens=12, output_tokens=8),
    ]
    stream_fn = _make_stream_fn([iter_one, iter_two])
    emitted, emit_fn = _make_emit_capture()
    saved, save_fn = _make_save_capture()

    async def tool_executor(user_id, tool_name, args_json, *, tool_call_id):
        # The real dispatcher raises this for any unknown tool name.
        raise ToolNotFoundError(f"No executor registered for tool '{tool_name}'")

    runner = InferenceRunner()
    await runner.run(
        user_id="u1",
        session_id="s1",
        correlation_id="c1",
        stream_fn=stream_fn,
        emit_fn=emit_fn,
        save_fn=save_fn,
        cancel_event=None,
        tool_executor_fn=tool_executor,
    )

    # The follow-up iteration's content is the user-visible answer.
    assert saved.get("called"), "save_fn must be invoked after recovery"
    assert saved["content"] == "Sorry, I cannot do that — final answer."

    # Recovered tool call shows up as a generic, failed timeline entry.
    timeline = saved["events"] or []
    assert len(timeline) == 1
    assert isinstance(timeline[0], TimelineEntryToolCall)
    assert timeline[0].tool_name == "xyz_unknown"
    assert timeline[0].success is False

    # ChatToolCallCompletedEvent emitted with success=False so the
    # frontend renders the failed-pill.
    completed = [e for e in emitted if isinstance(e, ChatToolCallCompletedEvent)]
    assert len(completed) == 1
    assert completed[0].success is False
    assert completed[0].tool_name == "xyz_unknown"

    # Stream ended event carries the persisted message_id.
    ended = [e for e in emitted if isinstance(e, ChatStreamEndedEvent)]
    assert len(ended) == 1
    assert ended[0].message_id == "msg-id-1"
    assert ended[0].status == "completed"

    # Started event was emitted before the executor was invoked.
    started = [e for e in emitted if isinstance(e, ChatToolCallStartedEvent)]
    assert len(started) == 1


# ---------------------------------------------------------------------------
# Test 2 — malformed tool arguments JSON
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_tool_args_recovers_and_continues_loop() -> None:
    """JSONDecodeError on tool arguments must follow the same recovery path."""
    iter_one = [
        ContentDelta(delta="Trying tool now."),
        # Deliberately broken JSON — missing closing brace.
        ToolCallEvent(id="call_2", name="web_search", arguments='{"q":"x"'),
        StreamDone(input_tokens=5, output_tokens=4),
    ]
    iter_two = [
        ContentDelta(delta="Falling back to a direct answer."),
        StreamDone(input_tokens=6, output_tokens=6),
    ]
    stream_fn = _make_stream_fn([iter_one, iter_two])
    emitted, emit_fn = _make_emit_capture()
    saved, save_fn = _make_save_capture()

    executor_called = {"count": 0}

    async def tool_executor(user_id, tool_name, args_json, *, tool_call_id):
        # The malformed-args branch short-circuits before the executor.
        executor_called["count"] += 1
        return "{}"

    runner = InferenceRunner()
    await runner.run(
        user_id="u2",
        session_id="s2",
        correlation_id="c2",
        stream_fn=stream_fn,
        emit_fn=emit_fn,
        save_fn=save_fn,
        cancel_event=None,
        tool_executor_fn=tool_executor,
    )

    # Executor must NOT have been invoked — the args parse error is caught
    # before dispatching. The model still gets the error fed back via the
    # tool-result message and the loop continues.
    assert executor_called["count"] == 0

    assert saved.get("called")
    assert saved["content"] == "Falling back to a direct answer."

    completed = [e for e in emitted if isinstance(e, ChatToolCallCompletedEvent)]
    assert len(completed) == 1
    assert completed[0].success is False
    assert completed[0].tool_name == "web_search"


# ---------------------------------------------------------------------------
# Test 3 — persistence guard fires when only thinking is non-empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persists_when_only_thinking_present_with_error_status() -> None:
    """If the model produced thinking but no visible content and the
    stream then errored internally, the partial thinking must still be
    persisted so a refresh shows what the user saw live."""
    # An unhandled exception during the stream simulates a genuine
    # internal failure (DB drop, network reset). The outer ``except`` in
    # _run_locked will catch it, set status="error", and we still want
    # the thinking to be saved.
    async def stream_fn(_extra_messages):
        async def gen():
            yield ThinkingDelta(delta="reasoning step one ")
            yield ThinkingDelta(delta="reasoning step two")
            raise RuntimeError("simulated upstream blow-up")
        return gen()

    emitted, emit_fn = _make_emit_capture()
    saved, save_fn = _make_save_capture()

    runner = InferenceRunner()
    await runner.run(
        user_id="u3",
        session_id="s3",
        correlation_id="c3",
        stream_fn=stream_fn,
        emit_fn=emit_fn,
        save_fn=save_fn,
        cancel_event=None,
    )

    assert saved.get("called"), (
        "save_fn must be called when thinking is non-empty even if "
        "content is empty and the stream errored"
    )
    assert saved["content"] == ""
    assert saved["thinking"] == "reasoning step one reasoning step two"

    ended = [e for e in emitted if isinstance(e, ChatStreamEndedEvent)]
    assert len(ended) == 1
    assert ended[0].message_id == "msg-id-1"
    assert ended[0].status == "error"


# ---------------------------------------------------------------------------
# Test 4 — persistence with content present and error status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persists_when_content_present_with_error_status() -> None:
    """A genuine internal error after the model already streamed content
    must still persist the streamed content so the user does not lose it."""
    async def stream_fn(_extra_messages):
        async def gen():
            yield ContentDelta(delta="partial answer the user already saw")
            raise RuntimeError("simulated upstream blow-up")
        return gen()

    emitted, emit_fn = _make_emit_capture()
    saved, save_fn = _make_save_capture()

    runner = InferenceRunner()
    await runner.run(
        user_id="u4",
        session_id="s4",
        correlation_id="c4",
        stream_fn=stream_fn,
        emit_fn=emit_fn,
        save_fn=save_fn,
        cancel_event=None,
    )

    assert saved.get("called")
    assert saved["content"] == "partial answer the user already saw"

    ended = [e for e in emitted if isinstance(e, ChatStreamEndedEvent)]
    assert len(ended) == 1
    assert ended[0].message_id == "msg-id-1"
    assert ended[0].status == "error"

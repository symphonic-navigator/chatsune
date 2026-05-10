"""Tests for the empty-response retry path in the inference loop.

The retry sits one level above the adapter's HTTP-error retry: it
catches HTTP-200 streams that end cleanly (``[DONE]`` received, no
error/abort/refusal) but produce zero content, zero thinking, and zero
tool calls — the exact pattern observed on Novita DSv4 Flash on
2026-05-10.

We verify four behaviours:
  1. An empty stream in iteration 0 triggers a retry, and a follow-up
     stream that returns content halts the retry loop with the new
     content in the persisted message.
  2. A non-empty first stream never retries.
  3. The retry stops after ``_EMPTY_RESPONSE_MAX_RETRIES`` (no infinite
     loop) when every attempt is empty.
  4. Cancellation, error, refusal, and abort do not trigger a retry,
     and iteration > 0 never retries.

The harness mirrors the pattern from ``test_tool_error_recovery.py`` —
the ``InferenceRunner.run`` entry point is exercised directly with
no-op emit/save stubs and a scripted ``stream_fn``. Sleeps are
monkey-patched to keep the test wall time near zero.
"""
from __future__ import annotations

import asyncio
import logging

import pytest

from backend.modules.chat import _inference as inference_mod
from backend.modules.chat._inference import (
    _EMPTY_RESPONSE_MAX_RETRIES,
    InferenceRunner,
    _should_retry_empty_response,
)
from backend.modules.llm import (
    ContentDelta,
    StreamAborted,
    StreamDone,
    StreamError,
    StreamRefused,
    ThinkingDelta,
    ToolCallEvent,
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
    pre-scripted iteration event lists. Tracks call count for assertions."""
    state = {"calls": 0}

    async def stream_fn(_extra_messages):
        idx = state["calls"]
        state["calls"] += 1
        events = (
            scripted_iterations[idx]
            if idx < len(scripted_iterations)
            else []
        )
        return _async_iter(events)

    return state, stream_fn


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


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Patch the module-level ``asyncio.sleep`` reference so the retry
    backoff doesn't actually wait. We patch the binding inside
    ``backend.modules.chat._inference`` rather than ``asyncio`` globally
    so other coroutines (none here, defensively) are unaffected."""
    async def fast_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(inference_mod.asyncio, "sleep", fast_sleep)


# ---------------------------------------------------------------------------
# Predicate: _should_retry_empty_response
# ---------------------------------------------------------------------------


class TestPredicate:
    """Direct unit tests for the retry-decision predicate.

    The predicate encodes the entire trigger condition for the retry
    layer. Hitting it directly avoids the cost of wiring up the full
    runner for cases that only differ in scalar arguments.
    """

    def _kwargs(self, **overrides):
        base = dict(
            iteration=0,
            cancelled=False,
            status="completed",
            iter_content="",
            iter_thinking="",
            iter_tool_calls=[],
            empty_attempt=0,
        )
        base.update(overrides)
        return base

    def test_empty_iteration_zero_returns_true(self) -> None:
        assert _should_retry_empty_response(**self._kwargs()) is True

    def test_iteration_one_never_retries(self) -> None:
        assert (
            _should_retry_empty_response(**self._kwargs(iteration=1))
            is False
        )

    def test_cancelled_never_retries(self) -> None:
        assert (
            _should_retry_empty_response(
                **self._kwargs(cancelled=True, status="cancelled"),
            )
            is False
        )

    @pytest.mark.parametrize("status", ["error", "aborted", "refused"])
    def test_terminal_status_never_retries(self, status: str) -> None:
        assert (
            _should_retry_empty_response(**self._kwargs(status=status))
            is False
        )

    def test_non_empty_content_never_retries(self) -> None:
        assert (
            _should_retry_empty_response(
                **self._kwargs(iter_content="hi"),
            )
            is False
        )

    def test_non_empty_thinking_never_retries(self) -> None:
        assert (
            _should_retry_empty_response(
                **self._kwargs(iter_thinking="reasoning"),
            )
            is False
        )

    def test_non_empty_tool_calls_never_retries(self) -> None:
        tc = ToolCallEvent(id="t1", name="web_search", arguments="{}")
        assert (
            _should_retry_empty_response(
                **self._kwargs(iter_tool_calls=[tc]),
            )
            is False
        )

    def test_budget_exhausted_returns_false(self) -> None:
        assert (
            _should_retry_empty_response(
                **self._kwargs(empty_attempt=_EMPTY_RESPONSE_MAX_RETRIES),
            )
            is False
        )

    def test_budget_just_below_cap_returns_true(self) -> None:
        assert (
            _should_retry_empty_response(
                **self._kwargs(empty_attempt=_EMPTY_RESPONSE_MAX_RETRIES - 1),
            )
            is True
        )


# ---------------------------------------------------------------------------
# Behaviour 1 — empty iter 0 triggers a retry; follow-up content halts it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_iteration_zero_triggers_retry_then_completes(
    caplog,
) -> None:
    """First stream is clean-but-empty, second stream returns content.
    Verify the retry log line was emitted and the final saved content
    is the content from the second stream."""
    iter_one_empty = [
        # Clean stream, no deltas, no tool calls, just done.
        StreamDone(input_tokens=2775, output_tokens=0),
    ]
    iter_two_content = [
        ContentDelta(delta="retry-success"),
        StreamDone(input_tokens=2775, output_tokens=5),
    ]
    state, stream_fn = _make_stream_fn([iter_one_empty, iter_two_content])
    _emitted, emit_fn = _make_emit_capture()
    saved, save_fn = _make_save_capture()

    runner = InferenceRunner()
    with caplog.at_level(
        logging.INFO, logger="backend.modules.chat._inference",
    ):
        await runner.run(
            user_id="u1",
            session_id="s1",
            correlation_id="c1",
            stream_fn=stream_fn,
            emit_fn=emit_fn,
            save_fn=save_fn,
            cancel_event=None,
        )

    # Two stream calls: first empty, second succeeded.
    assert state["calls"] == 2
    assert saved.get("called")
    assert saved["content"] == "retry-success"

    # The retry log line carries attempt index, max, and backoff.
    retry_logs = [
        r for r in caplog.records
        if "inference.empty_response.retry" in r.getMessage()
    ]
    assert len(retry_logs) == 1
    msg = retry_logs[0].getMessage()
    assert "attempt=1/2" in msg
    assert "backoff=1.0s" in msg


# ---------------------------------------------------------------------------
# Behaviour 2 — non-empty first stream does not retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_empty_iteration_zero_does_not_retry(caplog) -> None:
    """If the first stream produces content, the runner must not retry."""
    iter_one = [
        ContentDelta(delta="Hello"),
        StreamDone(input_tokens=10, output_tokens=2),
    ]
    state, stream_fn = _make_stream_fn([iter_one])
    _emitted, emit_fn = _make_emit_capture()
    saved, save_fn = _make_save_capture()

    runner = InferenceRunner()
    with caplog.at_level(
        logging.INFO, logger="backend.modules.chat._inference",
    ):
        await runner.run(
            user_id="u2",
            session_id="s2",
            correlation_id="c2",
            stream_fn=stream_fn,
            emit_fn=emit_fn,
            save_fn=save_fn,
            cancel_event=None,
        )

    assert state["calls"] == 1
    assert saved.get("called")
    assert saved["content"] == "Hello"

    retry_logs = [
        r for r in caplog.records
        if "inference.empty_response.retry" in r.getMessage()
    ]
    assert retry_logs == []


# ---------------------------------------------------------------------------
# Behaviour 2b — first stream emits only thinking → also does not retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_thinking_only_first_stream_does_not_retry() -> None:
    """A stream that produces thinking but no content is also non-empty
    for retry purposes — partial output is the user-visible signal that
    something happened, not a failure to mask."""
    iter_one = [
        ThinkingDelta(delta="reasoning..."),
        StreamDone(input_tokens=8, output_tokens=0, reasoning_tokens=4),
    ]
    state, stream_fn = _make_stream_fn([iter_one])
    _emitted, emit_fn = _make_emit_capture()
    saved, save_fn = _make_save_capture()

    runner = InferenceRunner()
    await runner.run(
        user_id="u2b",
        session_id="s2b",
        correlation_id="c2b",
        stream_fn=stream_fn,
        emit_fn=emit_fn,
        save_fn=save_fn,
        cancel_event=None,
    )

    assert state["calls"] == 1
    # Thinking-only with no error/refusal is dropped by the persistence
    # guard (existing behaviour), so save is NOT called — that's fine,
    # we're only asserting the retry didn't fire.
    assert saved == {} or saved.get("thinking") == "reasoning..."


# ---------------------------------------------------------------------------
# Behaviour 3 — retry caps at constant; no infinite loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_retries_caps_at_constant(caplog) -> None:
    """When every attempt is empty, the runner makes exactly
    ``1 + _EMPTY_RESPONSE_MAX_RETRIES`` total stream calls and then
    falls through with an empty completed message."""
    empty = [StreamDone(input_tokens=10, output_tokens=0)]
    # Provide enough scripted empty iterations that we cannot
    # accidentally exceed the cap (the scaffolding falls back to []
    # after the list is exhausted, which is also a clean-empty stream).
    state, stream_fn = _make_stream_fn(
        [empty] * (1 + _EMPTY_RESPONSE_MAX_RETRIES + 2),
    )
    _emitted, emit_fn = _make_emit_capture()
    _saved, save_fn = _make_save_capture()

    runner = InferenceRunner()
    with caplog.at_level(
        logging.INFO, logger="backend.modules.chat._inference",
    ):
        await runner.run(
            user_id="u3",
            session_id="s3",
            correlation_id="c3",
            stream_fn=stream_fn,
            emit_fn=emit_fn,
            save_fn=save_fn,
            cancel_event=None,
        )

    assert state["calls"] == 1 + _EMPTY_RESPONSE_MAX_RETRIES

    retry_logs = [
        r for r in caplog.records
        if "inference.empty_response.retry" in r.getMessage()
    ]
    assert len(retry_logs) == _EMPTY_RESPONSE_MAX_RETRIES
    # Backoffs follow the documented schedule: 1.0s, 2.0s.
    messages = [r.getMessage() for r in retry_logs]
    assert any("attempt=1/2" in m and "backoff=1.0s" in m for m in messages)
    assert any("attempt=2/2" in m and "backoff=2.0s" in m for m in messages)


# ---------------------------------------------------------------------------
# Behaviour 4a — cancellation does not retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancelled_iteration_does_not_retry(caplog) -> None:
    """A cancel event fired before the stream starts must produce a
    single stream call (the loop body sets ``cancelled=True`` on the
    first event check) and no retry."""
    cancel_event = asyncio.Event()
    cancel_event.set()  # already cancelled before we start

    # The stream still has to yield at least one event for the cancel
    # check to fire. We wrap a single delta — it will be observed but
    # the cancel check runs first on the very next iteration of the
    # async-for, setting cancelled=True.
    iter_one = [
        ContentDelta(delta="ignored"),  # may or may not be processed
    ]
    state, stream_fn = _make_stream_fn([iter_one])
    _emitted, emit_fn = _make_emit_capture()
    _saved, save_fn = _make_save_capture()

    runner = InferenceRunner()
    with caplog.at_level(
        logging.INFO, logger="backend.modules.chat._inference",
    ):
        await runner.run(
            user_id="u4a",
            session_id="s4a",
            correlation_id="c4a",
            stream_fn=stream_fn,
            emit_fn=emit_fn,
            save_fn=save_fn,
            cancel_event=cancel_event,
        )

    assert state["calls"] == 1
    retry_logs = [
        r for r in caplog.records
        if "inference.empty_response.retry" in r.getMessage()
    ]
    assert retry_logs == []


# ---------------------------------------------------------------------------
# Behaviour 4b — error event does not retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_error_event_does_not_retry(caplog) -> None:
    """A StreamError mid-iteration sets status='error' and must short-
    circuit before the retry decision."""
    iter_one = [
        StreamError(error_code="provider_unavailable", message="boom"),
        StreamDone(input_tokens=0, output_tokens=0),
    ]
    state, stream_fn = _make_stream_fn([iter_one])
    _emitted, emit_fn = _make_emit_capture()
    _saved, save_fn = _make_save_capture()

    runner = InferenceRunner()
    with caplog.at_level(
        logging.INFO, logger="backend.modules.chat._inference",
    ):
        await runner.run(
            user_id="u4b",
            session_id="s4b",
            correlation_id="c4b",
            stream_fn=stream_fn,
            emit_fn=emit_fn,
            save_fn=save_fn,
            cancel_event=None,
        )

    assert state["calls"] == 1
    retry_logs = [
        r for r in caplog.records
        if "inference.empty_response.retry" in r.getMessage()
    ]
    assert retry_logs == []


# ---------------------------------------------------------------------------
# Behaviour 4c — refusal does not retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refusal_does_not_retry(caplog) -> None:
    """The provider refused the prompt — that's the model's decision and
    must be respected, not retried."""
    iter_one = [
        StreamRefused(reason="policy", refusal_text="No."),
        StreamDone(input_tokens=10, output_tokens=0),
    ]
    state, stream_fn = _make_stream_fn([iter_one])
    _emitted, emit_fn = _make_emit_capture()
    _saved, save_fn = _make_save_capture()

    runner = InferenceRunner()
    with caplog.at_level(
        logging.INFO, logger="backend.modules.chat._inference",
    ):
        await runner.run(
            user_id="u4c",
            session_id="s4c",
            correlation_id="c4c",
            stream_fn=stream_fn,
            emit_fn=emit_fn,
            save_fn=save_fn,
            cancel_event=None,
        )

    assert state["calls"] == 1
    retry_logs = [
        r for r in caplog.records
        if "inference.empty_response.retry" in r.getMessage()
    ]
    assert retry_logs == []


# ---------------------------------------------------------------------------
# Behaviour 4d — aborted does not retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aborted_does_not_retry(caplog) -> None:
    """A StreamAborted (mid-stream upstream truncation) sets
    status='aborted' and must short-circuit before the retry decision."""
    iter_one = [
        StreamAborted(reason="upstream_disconnect"),
        StreamDone(input_tokens=10, output_tokens=0),
    ]
    state, stream_fn = _make_stream_fn([iter_one])
    _emitted, emit_fn = _make_emit_capture()
    _saved, save_fn = _make_save_capture()

    runner = InferenceRunner()
    with caplog.at_level(
        logging.INFO, logger="backend.modules.chat._inference",
    ):
        await runner.run(
            user_id="u4d",
            session_id="s4d",
            correlation_id="c4d",
            stream_fn=stream_fn,
            emit_fn=emit_fn,
            save_fn=save_fn,
            cancel_event=None,
        )

    assert state["calls"] == 1
    retry_logs = [
        r for r in caplog.records
        if "inference.empty_response.retry" in r.getMessage()
    ]
    assert retry_logs == []

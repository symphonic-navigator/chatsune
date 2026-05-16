"""Tests for the save_fn failure path in the inference loop.

If ``save_fn`` raises (DB blip, validation failure, anything), the runner
must NOT crash. It must instead:

  - Emit a ``ChatStreamErrorEvent`` (recoverable=False) so the user gets
    feedback that the assistant message was lost.
  - Still emit the terminal ``ChatStreamEndedEvent`` so the frontend
    releases its "thinking" indicator.
  - Return cleanly so subsequent inferences can run.

The harness mirrors the pattern in ``test_inference_empty_response_retry``:
the ``InferenceRunner.run`` entry point is exercised directly with
scripted stream events and instrumented emit/save stubs.
"""
from __future__ import annotations

import logging

import pytest

from backend.modules.chat._inference import InferenceRunner
from backend.modules.llm import ContentDelta, StreamDone
from shared.events.chat import (
    ChatStreamEndedEvent,
    ChatStreamErrorEvent,
)


async def _async_iter(events):
    for ev in events:
        yield ev


def _make_stream_fn(scripted_iterations):
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


@pytest.mark.asyncio
async def test_save_fn_failure_emits_error_and_ended_events(caplog) -> None:
    """When save_fn raises, the runner logs the failure, emits a
    ChatStreamErrorEvent, and still emits ChatStreamEndedEvent with
    status='error' and message_id=None so the UI unblocks."""
    iter_one = [
        ContentDelta(delta="some content"),
        StreamDone(input_tokens=10, output_tokens=2),
    ]
    _state, stream_fn = _make_stream_fn([iter_one])
    emitted, emit_fn = _make_emit_capture()

    async def failing_save(**_kwargs):
        raise RuntimeError("simulated DB blip")

    runner = InferenceRunner()
    with caplog.at_level(
        logging.ERROR, logger="backend.modules.chat._inference",
    ):
        # The runner must NOT raise.
        await runner.run(
            user_id="u-save-fail",
            session_id="s-save-fail",
            correlation_id="c-save-fail",
            stream_fn=stream_fn,
            emit_fn=emit_fn,
            save_fn=failing_save,
            cancel_event=None,
        )

    error_events = [e for e in emitted if isinstance(e, ChatStreamErrorEvent)]
    ended_events = [e for e in emitted if isinstance(e, ChatStreamEndedEvent)]

    assert len(error_events) == 1, (
        f"expected exactly one ChatStreamErrorEvent, got {len(error_events)}"
    )
    assert error_events[0].error_code == "persistence_failed"
    assert error_events[0].recoverable is False
    assert error_events[0].correlation_id == "c-save-fail"

    assert len(ended_events) == 1, (
        f"expected exactly one ChatStreamEndedEvent, got {len(ended_events)}"
    )
    assert ended_events[0].status == "error"
    assert ended_events[0].message_id is None
    assert ended_events[0].correlation_id == "c-save-fail"

    failure_logs = [
        r for r in caplog.records
        if "inference.save.failed" in r.getMessage()
    ]
    assert len(failure_logs) == 1
    msg = failure_logs[0].getMessage()
    assert "session=s-save-fail" in msg
    assert "correlation_id=c-save-fail" in msg
    assert "exc_type=RuntimeError" in msg
    assert "simulated DB blip" in msg


@pytest.mark.asyncio
async def test_runner_recovers_for_subsequent_inferences() -> None:
    """After a save_fn failure, the runner must be reusable: a second
    invocation with a working save_fn must complete normally."""
    runner = InferenceRunner()

    iter_fail = [
        ContentDelta(delta="first"),
        StreamDone(input_tokens=5, output_tokens=1),
    ]
    _state_a, stream_fn_a = _make_stream_fn([iter_fail])
    emitted_a, emit_fn_a = _make_emit_capture()

    async def failing_save(**_kwargs):
        raise RuntimeError("simulated DB blip")

    await runner.run(
        user_id="u-reuse",
        session_id="s-reuse-1",
        correlation_id="c-reuse-1",
        stream_fn=stream_fn_a,
        emit_fn=emit_fn_a,
        save_fn=failing_save,
        cancel_event=None,
    )

    # Second inference with a working save_fn.
    iter_ok = [
        ContentDelta(delta="second"),
        StreamDone(input_tokens=5, output_tokens=1),
    ]
    _state_b, stream_fn_b = _make_stream_fn([iter_ok])
    emitted_b, emit_fn_b = _make_emit_capture()

    saved: dict = {}

    async def working_save(**kwargs):
        saved.update(kwargs)
        return "msg-after-recovery"

    await runner.run(
        user_id="u-reuse",
        session_id="s-reuse-2",
        correlation_id="c-reuse-2",
        stream_fn=stream_fn_b,
        emit_fn=emit_fn_b,
        save_fn=working_save,
        cancel_event=None,
    )

    ended_b = [e for e in emitted_b if isinstance(e, ChatStreamEndedEvent)]
    assert len(ended_b) == 1
    assert ended_b[0].status == "completed"
    assert ended_b[0].message_id == "msg-after-recovery"
    assert saved.get("content") == "second"


@pytest.mark.asyncio
async def test_save_fn_failure_after_refusal_still_terminates() -> None:
    """Refusal flows also persist (so the refusal text is captured). If
    that persistence call raises, the error path must still fire and the
    stream-ended event must still arrive."""
    from backend.modules.llm import StreamRefused

    iter_one = [
        StreamRefused(reason="policy", refusal_text="No."),
        StreamDone(input_tokens=10, output_tokens=0),
    ]
    _state, stream_fn = _make_stream_fn([iter_one])
    emitted, emit_fn = _make_emit_capture()

    async def failing_save(**_kwargs):
        raise ValueError("validation blew up")

    runner = InferenceRunner()
    await runner.run(
        user_id="u-refusal",
        session_id="s-refusal",
        correlation_id="c-refusal",
        stream_fn=stream_fn,
        emit_fn=emit_fn,
        save_fn=failing_save,
        cancel_event=None,
    )

    error_events = [e for e in emitted if isinstance(e, ChatStreamErrorEvent)]
    ended_events = [e for e in emitted if isinstance(e, ChatStreamEndedEvent)]

    # One error event from the refusal itself, plus one from the
    # persistence failure — order matters: refusal first, then persistence.
    assert len(error_events) == 2
    assert error_events[0].error_code == "refusal"
    assert error_events[1].error_code == "persistence_failed"

    assert len(ended_events) == 1
    assert ended_events[0].status == "error"
    assert ended_events[0].message_id is None

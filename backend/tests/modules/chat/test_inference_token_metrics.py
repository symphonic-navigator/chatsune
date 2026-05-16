"""Tests for the dual token-metric fields on ChatStreamEndedEvent.

The "context fill" pill historically conflated two distinct numbers:
the total tokens across every persisted message in the session, and the
tokens actually sent upstream this turn (clamped by pair-selection to
the model's context window). These can diverge a lot in long sessions.

The runner now surfaces both numbers on ``ChatStreamEndedEvent``:

  - ``total_session_tokens`` — user-facing "how full is the conversation"
  - ``tokens_actually_sent`` — what the LLM provider sees this turn

Both fields are optional for backwards compatibility with older event
producers; this test pins the contract that, when the orchestrator
supplies both numbers, both appear on the emitted event.
"""
from __future__ import annotations

import pytest

from backend.modules.chat._inference import InferenceRunner
from backend.modules.llm import ContentDelta, StreamDone
from shared.events.chat import ChatStreamEndedEvent


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
async def test_stream_ended_event_carries_both_token_metrics() -> None:
    """When the orchestrator passes both ``total_session_tokens`` and
    ``tokens_actually_sent``, the emitted ``ChatStreamEndedEvent`` must
    carry both verbatim, alongside the legacy ``context_used_tokens``
    field that older clients still read."""
    iter_one = [
        ContentDelta(delta="hello"),
        StreamDone(input_tokens=10, output_tokens=2),
    ]
    _state, stream_fn = _make_stream_fn([iter_one])
    emitted, emit_fn = _make_emit_capture()

    async def save_fn(**_kwargs):
        return "msg-id-1"

    runner = InferenceRunner()
    await runner.run(
        user_id="u-metrics",
        session_id="s-metrics",
        correlation_id="c-metrics",
        stream_fn=stream_fn,
        emit_fn=emit_fn,
        save_fn=save_fn,
        cancel_event=None,
        context_used_tokens=12_000,
        context_max_tokens=32_000,
        total_session_tokens=12_000,
        tokens_actually_sent=8_500,
    )

    ended = [e for e in emitted if isinstance(e, ChatStreamEndedEvent)]
    assert len(ended) == 1, f"expected one ended event, got {len(ended)}"
    assert ended[0].total_session_tokens == 12_000
    assert ended[0].tokens_actually_sent == 8_500
    # Legacy field still populated for backwards compatibility.
    assert ended[0].context_used_tokens == 12_000


@pytest.mark.asyncio
async def test_stream_ended_event_token_metrics_default_to_none() -> None:
    """Callers that do not supply the new fields (e.g. legacy code paths)
    must still produce a valid event — the fields default to ``None``."""
    iter_one = [
        ContentDelta(delta="hi"),
        StreamDone(input_tokens=4, output_tokens=1),
    ]
    _state, stream_fn = _make_stream_fn([iter_one])
    emitted, emit_fn = _make_emit_capture()

    async def save_fn(**_kwargs):
        return "msg-id-2"

    runner = InferenceRunner()
    await runner.run(
        user_id="u-metrics-legacy",
        session_id="s-metrics-legacy",
        correlation_id="c-metrics-legacy",
        stream_fn=stream_fn,
        emit_fn=emit_fn,
        save_fn=save_fn,
        cancel_event=None,
    )

    ended = [e for e in emitted if isinstance(e, ChatStreamEndedEvent)]
    assert len(ended) == 1
    assert ended[0].total_session_tokens is None
    assert ended[0].tokens_actually_sent is None

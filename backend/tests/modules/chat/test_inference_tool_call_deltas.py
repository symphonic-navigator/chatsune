"""Tests for tool-call delta routing through the inference loop.

Verifies the new ChatToolCallDeltaEvent emission path: streaming
adapters emit ToolCallArgsDelta which the loop forwards as
chat.tool_call.delta WS events, with late-id backfill and an
end-of-iteration drain hook for ids generated only at finalisation.
"""
import pytest

from backend.modules.chat._inference import InferenceRunner
from backend.modules.llm._adapters._events import (
    ContentDelta, StreamDone, ToolCallArgsDelta, ToolCallEvent,
)
from shared.events.chat import (
    ChatStreamEndedEvent, ChatToolCallCompletedEvent,
    ChatToolCallDeltaEvent, ChatToolCallStartedEvent,
)


async def _async_iter(events):
    for ev in events:
        yield ev


def _make_stream_fn(scripted_iterations):
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
        captured.update(dict(
            content=content, thinking=thinking, usage=usage,
            events=events, refusal_text=refusal_text, status=status,
            called=True,
        ))
        return "msg-id-1"

    return captured, save


async def _noop_executor(user_id, tool_name, args_json, *, tool_call_id):
    return "{}"


@pytest.mark.asyncio
async def test_streaming_tool_call_emits_delta_events_in_order() -> None:
    """Adapter that yields ToolCallArgsDelta before its final ToolCallEvent
    should produce ChatToolCallDeltaEvents in order, followed by
    ChatToolCallStartedEvent, then ChatToolCallCompletedEvent."""
    iter_one = [
        ToolCallArgsDelta(index=0, id="call_x", name="t",
                          arguments_delta='{"q'),
        ToolCallArgsDelta(index=0, id="call_x", name="t",
                          arguments_delta='":"hi"}'),
        ToolCallEvent(id="call_x", name="t",
                      arguments='{"q":"hi"}', index=0),
        StreamDone(input_tokens=5, output_tokens=10),
    ]
    iter_two = [
        ContentDelta(delta="done"),
        StreamDone(input_tokens=3, output_tokens=2),
    ]
    emitted, emit_fn = _make_emit_capture()
    _, save_fn = _make_save_capture()

    await InferenceRunner().run(
        user_id="u", session_id="s", correlation_id="c",
        stream_fn=_make_stream_fn([iter_one, iter_two]),
        emit_fn=emit_fn, save_fn=save_fn,
        cancel_event=None, tool_executor_fn=_noop_executor,
    )

    deltas = [e for e in emitted if isinstance(e, ChatToolCallDeltaEvent)]
    starteds = [e for e in emitted if isinstance(e, ChatToolCallStartedEvent)]
    completeds = [e for e in emitted if isinstance(e, ChatToolCallCompletedEvent)]
    assert len(deltas) == 2
    assert deltas[0].tool_call_id == "call_x"
    assert deltas[0].args_delta == '{"q'
    assert deltas[1].args_delta == '":"hi"}'
    # Order: deltas before started before completed.
    delta_idxs = [emitted.index(d) for d in deltas]
    started_idx = emitted.index(starteds[0])
    completed_idx = emitted.index(completeds[0])
    assert all(i < started_idx for i in delta_idxs)
    assert started_idx < completed_idx


@pytest.mark.asyncio
async def test_non_streaming_adapter_emits_no_deltas() -> None:
    """Adapter that yields only the final ToolCallEvent (no deltas) — the
    inference loop should NOT emit ChatToolCallDeltaEvent."""
    iter_one = [
        ToolCallEvent(id="call_y", name="t",
                      arguments='{}', index=0),
        StreamDone(input_tokens=5, output_tokens=5),
    ]
    iter_two = [
        ContentDelta(delta="done"),
        StreamDone(input_tokens=2, output_tokens=2),
    ]
    emitted, emit_fn = _make_emit_capture()
    _, save_fn = _make_save_capture()

    await InferenceRunner().run(
        user_id="u", session_id="s", correlation_id="c",
        stream_fn=_make_stream_fn([iter_one, iter_two]),
        emit_fn=emit_fn, save_fn=save_fn,
        cancel_event=None, tool_executor_fn=_noop_executor,
    )

    deltas = [e for e in emitted if isinstance(e, ChatToolCallDeltaEvent)]
    starteds = [e for e in emitted if isinstance(e, ChatToolCallStartedEvent)]
    assert deltas == []
    assert len(starteds) == 1


@pytest.mark.asyncio
async def test_late_id_is_backfilled_into_earlier_deltas() -> None:
    """First delta carries id=None; later delta supplies the id. The loop
    should buffer the first delta and emit it with the late id, then emit
    the second delta normally."""
    iter_one = [
        ToolCallArgsDelta(index=0, id=None, name=None,
                          arguments_delta='{"q'),
        ToolCallArgsDelta(index=0, id="call_z", name="t",
                          arguments_delta='":"x"}'),
        ToolCallEvent(id="call_z", name="t",
                      arguments='{"q":"x"}', index=0),
        StreamDone(input_tokens=5, output_tokens=5),
    ]
    iter_two = [
        ContentDelta(delta="done"),
        StreamDone(input_tokens=2, output_tokens=2),
    ]
    emitted, emit_fn = _make_emit_capture()
    _, save_fn = _make_save_capture()

    await InferenceRunner().run(
        user_id="u", session_id="s", correlation_id="c",
        stream_fn=_make_stream_fn([iter_one, iter_two]),
        emit_fn=emit_fn, save_fn=save_fn,
        cancel_event=None, tool_executor_fn=_noop_executor,
    )

    deltas = [e for e in emitted if isinstance(e, ChatToolCallDeltaEvent)]
    assert len(deltas) == 2
    # Both — including the first, originally-id-less one — carry call_z.
    assert all(d.tool_call_id == "call_z" for d in deltas)


@pytest.mark.asyncio
async def test_finalisation_drain_backfills_synth_id() -> None:
    """Adapter never sends the id in any delta — the final ToolCallEvent
    supplies a synthesised id (the accumulator generated it locally). The
    finally-block drain hook backfills the pending delta with that id."""
    iter_one = [
        ToolCallArgsDelta(index=0, id=None, name="t",
                          arguments_delta='{"q":"x"}'),
        ToolCallEvent(id="synth_id", name="t",
                      arguments='{"q":"x"}', index=0),
        StreamDone(input_tokens=5, output_tokens=5),
    ]
    iter_two = [
        ContentDelta(delta="done"),
        StreamDone(input_tokens=2, output_tokens=2),
    ]
    emitted, emit_fn = _make_emit_capture()
    _, save_fn = _make_save_capture()

    await InferenceRunner().run(
        user_id="u", session_id="s", correlation_id="c",
        stream_fn=_make_stream_fn([iter_one, iter_two]),
        emit_fn=emit_fn, save_fn=save_fn,
        cancel_event=None, tool_executor_fn=_noop_executor,
    )

    deltas = [e for e in emitted if isinstance(e, ChatToolCallDeltaEvent)]
    assert len(deltas) == 1
    assert deltas[0].tool_call_id == "synth_id"


@pytest.mark.asyncio
async def test_generate_image_persists_tool_call_and_image_entries() -> None:
    """generate_image with success=True should persist BOTH a tool_call
    entry (for the pill) AND an image entry (for InlineImageBlock), in
    that order."""
    from shared.dtos.chat import TimelineEntryImage, TimelineEntryToolCall

    iter_one = [
        ToolCallEvent(id="call_g", name="generate_image",
                      arguments='{"prompt":"a cat"}', index=0),
        StreamDone(input_tokens=5, output_tokens=10),
    ]
    iter_two = [
        ContentDelta(delta="done"),
        StreamDone(input_tokens=2, output_tokens=2),
    ]
    emitted, emit_fn = _make_emit_capture()
    saved, save_fn = _make_save_capture()

    async def image_executor(user_id, tool_name, args_json, *, tool_call_id):
        # The real executor stashes an ImageGenerationOutcome via the
        # _PENDING_OUTCOMES side-channel; absent that, drain_image_outcome
        # returns None and the inference loop treats the call as a
        # successful generation with zero image_refs. That keeps the test
        # focused on the timeline-entry structure rather than image
        # transformation.
        return '{"ok": true, "image_ids": []}'

    await InferenceRunner().run(
        user_id="u", session_id="s", correlation_id="c",
        stream_fn=_make_stream_fn([iter_one, iter_two]),
        emit_fn=emit_fn, save_fn=save_fn,
        cancel_event=None, tool_executor_fn=image_executor,
    )

    timeline = saved["events"] or []
    types = [type(e).__name__ for e in timeline]
    # tool_call entry exists and comes before the image entry.
    assert "TimelineEntryToolCall" in types
    assert "TimelineEntryImage" in types
    tool_call_idx = types.index("TimelineEntryToolCall")
    image_idx = types.index("TimelineEntryImage")
    assert tool_call_idx < image_idx
    # The tool_call entry is the generate_image one (not a failed one).
    tc_entry = timeline[tool_call_idx]
    assert isinstance(tc_entry, TimelineEntryToolCall)
    assert tc_entry.tool_name == "generate_image"
    assert tc_entry.success is True

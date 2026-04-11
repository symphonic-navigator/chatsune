import asyncio
import json
from unittest.mock import AsyncMock
import pytest

from backend.modules.chat._inference import InferenceRunner
from backend.modules.llm import ContentDelta, StreamAborted, StreamDone, StreamError, StreamRefused, StreamSlow, ThinkingDelta, ToolCallEvent
from shared.dtos.chat import ArtefactRefDto
from shared.events.chat import (
    ChatContentDeltaEvent, ChatStreamEndedEvent, ChatStreamErrorEvent,
    ChatStreamSlowEvent, ChatStreamStartedEvent, ChatThinkingDeltaEvent,
    ChatToolCallCompletedEvent,
)


@pytest.fixture
def runner():
    return InferenceRunner()

@pytest.fixture
def mock_emit():
    return AsyncMock()

@pytest.fixture
def mock_save():
    # save_fn must return a message id string; a bare AsyncMock would
    # return another AsyncMock and break pydantic validation downstream.
    return AsyncMock(return_value="msg-id-123")


def _make_stream(*events):
    """Return an async generator function that yields the given events."""
    async def _gen(extra_messages=None):
        for e in events:
            yield e
    return _gen



async def test_basic_content_stream(runner, mock_emit, mock_save):
    stream_fn = _make_stream(
        ContentDelta(delta="Hello"),
        ContentDelta(delta=" world"),
        StreamDone(input_tokens=10, output_tokens=5),
    )

    await runner.run(
        user_id="user-1", session_id="sess-1", correlation_id="corr-1",
        stream_fn=stream_fn, emit_fn=mock_emit, save_fn=mock_save,
    )

    emitted_types = [call.args[0].type for call in mock_emit.call_args_list]
    assert emitted_types[0] == "chat.stream.started"
    assert "chat.content.delta" in emitted_types
    assert emitted_types[-1] == "chat.stream.ended"

    deltas = [call.args[0] for call in mock_emit.call_args_list if isinstance(call.args[0], ChatContentDeltaEvent)]
    assert len(deltas) == 2
    assert deltas[0].delta == "Hello"
    assert deltas[1].delta == " world"

    ended = mock_emit.call_args_list[-1].args[0]
    assert isinstance(ended, ChatStreamEndedEvent)
    assert ended.status == "completed"
    assert ended.usage == {"input_tokens": 10, "output_tokens": 5}

    mock_save.assert_awaited_once()
    save_args = mock_save.call_args
    assert save_args.kwargs["content"] == "Hello world"
    assert save_args.kwargs["thinking"] is None


async def test_thinking_and_content(runner, mock_emit, mock_save):
    stream_fn = _make_stream(
        ThinkingDelta(delta="Let me think..."),
        ContentDelta(delta="42"),
        StreamDone(input_tokens=20, output_tokens=10),
    )

    await runner.run(
        user_id="user-1", session_id="sess-1", correlation_id="corr-1",
        stream_fn=stream_fn, emit_fn=mock_emit, save_fn=mock_save,
    )

    thinking_deltas = [call.args[0] for call in mock_emit.call_args_list if isinstance(call.args[0], ChatThinkingDeltaEvent)]
    assert len(thinking_deltas) == 1
    assert thinking_deltas[0].delta == "Let me think..."

    save_args = mock_save.call_args
    assert save_args.kwargs["content"] == "42"
    assert save_args.kwargs["thinking"] == "Let me think..."


async def test_stream_error(runner, mock_emit, mock_save):
    stream_fn = _make_stream(
        StreamError(error_code="invalid_api_key", message="Bad key"),
    )

    await runner.run(
        user_id="user-1", session_id="sess-1", correlation_id="corr-1",
        stream_fn=stream_fn, emit_fn=mock_emit, save_fn=mock_save,
    )

    emitted_types = [call.args[0].type for call in mock_emit.call_args_list]
    assert "chat.stream.started" in emitted_types
    assert "chat.stream.error" in emitted_types
    assert "chat.stream.ended" in emitted_types

    error_event = [call.args[0] for call in mock_emit.call_args_list if isinstance(call.args[0], ChatStreamErrorEvent)][0]
    assert error_event.error_code == "invalid_api_key"

    ended = [call.args[0] for call in mock_emit.call_args_list if isinstance(call.args[0], ChatStreamEndedEvent)][0]
    assert ended.status == "error"

    mock_save.assert_not_awaited()


async def test_cancellation(runner, mock_emit, mock_save):
    cancel_event = asyncio.Event()

    async def _slow_stream(extra_messages=None):
        yield ContentDelta(delta="Start")
        cancel_event.set()
        await asyncio.sleep(10)
        yield ContentDelta(delta="Should not appear")
        yield StreamDone()

    task = asyncio.create_task(runner.run(
        user_id="user-1", session_id="sess-1", correlation_id="corr-1",
        stream_fn=_slow_stream, emit_fn=mock_emit, save_fn=mock_save,
        cancel_event=cancel_event,
    ))

    await asyncio.sleep(0.05)
    await task

    ended_events = [call.args[0] for call in mock_emit.call_args_list if isinstance(call.args[0], ChatStreamEndedEvent)]
    assert len(ended_events) == 1
    assert ended_events[0].status == "cancelled"


async def test_per_user_serialisation(runner, mock_emit, mock_save):
    call_order = []

    async def _stream_a(extra_messages=None):
        call_order.append("a_start")
        yield ContentDelta(delta="A")
        await asyncio.sleep(0.05)
        yield StreamDone()
        call_order.append("a_end")

    async def _stream_b(extra_messages=None):
        call_order.append("b_start")
        yield ContentDelta(delta="B")
        yield StreamDone()
        call_order.append("b_end")

    task_a = asyncio.create_task(runner.run(
        user_id="user-1", session_id="sess-a", correlation_id="corr-a",
        stream_fn=_stream_a, emit_fn=mock_emit, save_fn=mock_save,
    ))
    await asyncio.sleep(0.01)
    task_b = asyncio.create_task(runner.run(
        user_id="user-1", session_id="sess-b", correlation_id="corr-b",
        stream_fn=_stream_b, emit_fn=mock_emit, save_fn=mock_save,
    ))

    await asyncio.gather(task_a, task_b)
    assert call_order.index("a_end") < call_order.index("b_start")


async def test_stream_slow_propagates_as_chat_stream_slow_event(
    runner, mock_emit, mock_save,
):
    """StreamSlow from the adapter must surface as a ChatStreamSlowEvent
    on the emit channel without changing the run's status. The tool
    loop continues normally."""
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
    ended = [e for e in emitted if isinstance(e, ChatStreamEndedEvent)][0]
    assert ended.status == "completed"

    # Both content chunks made it into the saved message.
    save_args = mock_save.call_args
    assert save_args.kwargs["content"] == "partial recovered"
    assert save_args.kwargs["status"] == "completed"


async def test_stream_aborted_with_content_saves_as_aborted(
    runner, mock_emit, mock_save,
):
    """StreamAborted with prior content sets the run's status to
    'aborted', emits a recoverable ChatStreamErrorEvent, persists the
    partial content with status='aborted', and ends the run."""
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

    save_args = mock_save.call_args
    assert save_args.kwargs["content"] == "I was writing a "
    assert save_args.kwargs["status"] == "aborted"


async def test_stream_aborted_without_content_does_not_save(
    runner, mock_emit, mock_save,
):
    """StreamAborted with no prior content must not call save_fn at
    all (the existing 'if full_content' guard preserves this)."""
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


async def test_run_inference_handles_stream_refused(
    runner, mock_emit, mock_save, caplog,
):
    """StreamRefused → status='refused', recoverable error event with
    error_code='refusal', save_fn called with status='refused' and the
    partial content that arrived before the refusal."""
    stream_fn = _make_stream(
        ContentDelta(delta="I am sorry"),
        StreamRefused(reason="content_filter", refusal_text=None),
    )

    with caplog.at_level("WARNING"):
        await runner.run(
            user_id="user-1", session_id="sess-1", correlation_id="corr-1",
            stream_fn=stream_fn, emit_fn=mock_emit, save_fn=mock_save,
        )

    emitted = [call.args[0] for call in mock_emit.call_args_list]

    refusal_errors = [
        e for e in emitted
        if isinstance(e, ChatStreamErrorEvent) and e.error_code == "refusal"
    ]
    assert len(refusal_errors) == 1
    assert refusal_errors[0].recoverable is True

    assert any("chat.stream.refused" in m for m in caplog.messages)

    save_args = mock_save.call_args
    assert save_args.kwargs["status"] == "refused"
    assert save_args.kwargs["refusal_text"] is None
    assert save_args.kwargs["content"] == "I am sorry"


async def test_run_inference_refused_with_provider_body(
    runner, mock_emit, mock_save,
):
    """When StreamRefused carries a refusal_text, it must be forwarded
    to save_fn unchanged."""
    stream_fn = _make_stream(
        StreamRefused(reason="refusal", refusal_text="I cannot help"),
    )

    await runner.run(
        user_id="user-1", session_id="sess-1", correlation_id="corr-1",
        stream_fn=stream_fn, emit_fn=mock_emit, save_fn=mock_save,
    )

    save_args = mock_save.call_args
    assert save_args.kwargs["refusal_text"] == "I cannot help"
    assert save_args.kwargs["status"] == "refused"


async def test_run_inference_captures_create_artefact_ref(
    runner, mock_emit, mock_save,
):
    """A successful create_artefact tool call must append a ref to artefact_refs
    and attach an ArtefactRefDto to the ChatToolCallCompletedEvent."""
    call_count = 0

    async def two_phase_stream(extra_messages=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First iteration: model emits a tool call
            yield ToolCallEvent(
                id="tc1", name="create_artefact",
                arguments=json.dumps({"handle": "h1", "title": "Hello snippet", "type": "code"}),
            )
            yield StreamDone(input_tokens=1, output_tokens=1)
        else:
            # Second iteration: model responds with content after tool execution
            yield ContentDelta(delta="Artefact created.")
            yield StreamDone(input_tokens=2, output_tokens=2)

    async def fake_tool_executor(user_id, tool_name, arguments_str):
        return json.dumps({"ok": True, "artefact_id": "a1", "handle": "h1"})

    await runner.run(
        user_id="user-1", session_id="sess-1", correlation_id="corr-1",
        stream_fn=two_phase_stream, emit_fn=mock_emit, save_fn=mock_save,
        tool_executor_fn=fake_tool_executor,
    )

    mock_save.assert_awaited_once()
    save_kwargs = mock_save.call_args.kwargs
    assert save_kwargs["artefact_refs"] == [
        {"artefact_id": "a1", "handle": "h1", "title": "Hello snippet", "artefact_type": "code", "operation": "create"}
    ]

    emitted = [call.args[0] for call in mock_emit.call_args_list]
    completed_events = [e for e in emitted if isinstance(e, ChatToolCallCompletedEvent)]
    assert len(completed_events) == 1
    assert isinstance(completed_events[0].artefact_ref, ArtefactRefDto)
    assert completed_events[0].artefact_ref.operation == "create"
    assert completed_events[0].artefact_ref.artefact_id == "a1"


async def test_run_inference_captures_update_artefact_without_artefact_id(
    runner, mock_emit, mock_save,
):
    """A successful update_artefact result that omits artefact_id must store
    an empty string for that field."""
    call_count = 0

    async def two_phase_stream(extra_messages=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield ToolCallEvent(
                id="tc2", name="update_artefact",
                arguments=json.dumps({"handle": "h2", "title": "x"}),
            )
            yield StreamDone(input_tokens=1, output_tokens=1)
        else:
            yield ContentDelta(delta="Updated.")
            yield StreamDone(input_tokens=2, output_tokens=2)

    async def fake_tool_executor(user_id, tool_name, arguments_str):
        return json.dumps({"ok": True, "handle": "h2", "version": 3})

    await runner.run(
        user_id="user-1", session_id="sess-1", correlation_id="corr-1",
        stream_fn=two_phase_stream, emit_fn=mock_emit, save_fn=mock_save,
        tool_executor_fn=fake_tool_executor,
    )

    save_kwargs = mock_save.call_args.kwargs
    refs = save_kwargs["artefact_refs"]
    assert refs[0]["artefact_id"] == ""
    assert refs[0]["handle"] == "h2"
    assert refs[0]["operation"] == "update"


async def test_run_inference_skips_failed_artefact_tool_call(
    runner, mock_emit, mock_save,
):
    """A failed artefact tool call (result contains 'error') must not
    add to artefact_refs; save_fn receives artefact_refs=None."""
    call_count = 0

    async def two_phase_stream(extra_messages=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield ToolCallEvent(
                id="tc3", name="create_artefact",
                arguments=json.dumps({"handle": "h3", "title": "x", "type": "code"}),
            )
            yield StreamDone(input_tokens=1, output_tokens=1)
        else:
            yield ContentDelta(delta="Could not create.")
            yield StreamDone(input_tokens=2, output_tokens=2)

    async def fake_tool_executor(user_id, tool_name, arguments_str):
        return json.dumps({"error": "validation failed"})

    await runner.run(
        user_id="user-1", session_id="sess-1", correlation_id="corr-1",
        stream_fn=two_phase_stream, emit_fn=mock_emit, save_fn=mock_save,
        tool_executor_fn=fake_tool_executor,
    )

    save_kwargs = mock_save.call_args.kwargs
    assert save_kwargs["artefact_refs"] is None


async def test_run_inference_preserves_artefact_call_order(
    runner, mock_emit, mock_save,
):
    """Two artefact tool calls in sequence must appear in artefact_refs
    in the same order they were executed."""
    call_count = 0

    async def two_phase_stream(extra_messages=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield ToolCallEvent(
                id="tc-a", name="create_artefact",
                arguments=json.dumps({"handle": "h", "title": "t1", "type": "code"}),
            )
            yield ToolCallEvent(
                id="tc-b", name="update_artefact",
                arguments=json.dumps({"handle": "h", "title": "t2"}),
            )
            yield StreamDone(input_tokens=2, output_tokens=2)
        else:
            yield ContentDelta(delta="Done.")
            yield StreamDone(input_tokens=3, output_tokens=3)

    async def fake_tool_executor(user_id, tool_name, arguments_str):
        if tool_name == "create_artefact":
            return json.dumps({"ok": True, "artefact_id": "a", "handle": "h"})
        return json.dumps({"ok": True, "handle": "h", "version": 2})

    await runner.run(
        user_id="user-1", session_id="sess-1", correlation_id="corr-1",
        stream_fn=two_phase_stream, emit_fn=mock_emit, save_fn=mock_save,
        tool_executor_fn=fake_tool_executor,
    )

    save_kwargs = mock_save.call_args.kwargs
    refs = save_kwargs["artefact_refs"]
    assert [r["operation"] for r in refs] == ["create", "update"]
    assert refs[0]["title"] == "t1"
    assert refs[1]["title"] == "t2"

import asyncio
from unittest.mock import AsyncMock
import pytest

from backend.modules.chat._inference import InferenceRunner
from backend.modules.llm import ContentDelta, StreamAborted, StreamDone, StreamError, StreamSlow, ThinkingDelta
from shared.events.chat import (
    ChatContentDeltaEvent, ChatStreamEndedEvent, ChatStreamErrorEvent,
    ChatStreamSlowEvent, ChatStreamStartedEvent, ChatThinkingDeltaEvent,
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


async def _run_inference_with_fake_stream(stream, emit_fn, save_fn):
    """Helper that runs InferenceRunner._run_locked with a pre-built async stream.

    Wraps the stream in a stream_fn callable so InferenceRunner can consume it.
    Stub values are used for arguments the refusal tests do not care about.
    """
    runner = InferenceRunner()

    async def _stream_fn(extra_messages=None):
        async for event in stream:
            yield event

    await runner._run_locked(
        user_id="user-1",
        session_id="sess-1",
        correlation_id="corr-1",
        stream_fn=_stream_fn,
        emit_fn=emit_fn,
        save_fn=save_fn,
        cancel_event=None,
    )


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


@pytest.mark.asyncio
async def test_run_inference_handles_stream_refused(caplog):
    """StreamRefused → status='refused', error event with error_code='refusal',
    save_fn called with refusal fields."""
    from backend.modules.llm._adapters._events import (
        ContentDelta, StreamRefused,
    )
    from shared.events.chat import ChatStreamErrorEvent

    async def fake_stream():
        yield ContentDelta(delta="I am sorry")
        yield StreamRefused(reason="content_filter", refusal_text=None)

    emitted: list = []
    save_calls: list = []

    async def fake_emit(event):
        emitted.append(event)

    async def fake_save(**kwargs):
        save_calls.append(kwargs)
        return "msg-1"

    with caplog.at_level("WARNING"):
        await _run_inference_with_fake_stream(
            stream=fake_stream(),
            emit_fn=fake_emit,
            save_fn=fake_save,
        )

    # Error event with refusal code emitted
    err_events = [e for e in emitted if isinstance(e, ChatStreamErrorEvent)]
    assert any(e.error_code == "refusal" and e.recoverable is True
               for e in err_events)
    # Warning log line
    assert any("chat.stream.refused" in m for m in caplog.messages)
    # save_fn called with status='refused' and refusal_text=None
    assert len(save_calls) == 1
    assert save_calls[0]["status"] == "refused"
    assert save_calls[0]["refusal_text"] is None
    assert save_calls[0]["content"] == "I am sorry"


@pytest.mark.asyncio
async def test_run_inference_refused_with_provider_body():
    from backend.modules.llm._adapters._events import StreamRefused

    async def fake_stream():
        yield StreamRefused(reason="refusal", refusal_text="I cannot help")

    emitted: list = []
    save_calls: list = []

    async def fake_emit(event):
        emitted.append(event)

    async def fake_save(**kwargs):
        save_calls.append(kwargs)
        return "msg-1"

    await _run_inference_with_fake_stream(
        stream=fake_stream(),
        emit_fn=fake_emit,
        save_fn=fake_save,
    )
    assert len(save_calls) == 1
    assert save_calls[0]["refusal_text"] == "I cannot help"
    assert save_calls[0]["status"] == "refused"

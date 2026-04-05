import asyncio
from unittest.mock import AsyncMock
import pytest

from backend.modules.chat._inference import InferenceRunner
from backend.modules.llm._adapters._events import ContentDelta, StreamDone, StreamError, ThinkingDelta
from shared.events.chat import (
    ChatContentDeltaEvent, ChatStreamEndedEvent, ChatStreamErrorEvent,
    ChatStreamStartedEvent, ChatThinkingDeltaEvent,
)


@pytest.fixture
def runner():
    return InferenceRunner()

@pytest.fixture
def mock_emit():
    return AsyncMock()

@pytest.fixture
def mock_save():
    return AsyncMock()


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

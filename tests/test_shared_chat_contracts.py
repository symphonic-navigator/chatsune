from datetime import datetime, timezone
from shared.dtos.chat import ChatSessionDto, ChatMessageDto
from shared.events.chat import (
    ChatStreamStartedEvent, ChatContentDeltaEvent, ChatThinkingDeltaEvent,
    ChatStreamEndedEvent, ChatStreamErrorEvent, ChatStreamSlowEvent,
)
from shared.topics import Topics


def test_chat_session_dto():
    dto = ChatSessionDto(
        id="sess-1", user_id="user-1", persona_id="persona-1",
        model_unique_id="ollama_cloud:qwen3:32b", state="idle",
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    assert dto.state == "idle"


def test_chat_message_dto():
    dto = ChatMessageDto(
        id="msg-1", session_id="sess-1", role="assistant",
        content="Hello!", thinking=None, token_count=5,
        created_at=datetime.now(timezone.utc),
    )
    assert dto.role == "assistant"
    assert dto.thinking is None


def test_stream_started_event():
    e = ChatStreamStartedEvent(
        session_id="sess-1", correlation_id="corr-1",
        timestamp=datetime.now(timezone.utc),
    )
    assert e.type == "chat.stream.started"


def test_content_delta_event():
    e = ChatContentDeltaEvent(correlation_id="corr-1", delta="Hello")
    assert e.type == "chat.content.delta"
    assert e.delta == "Hello"


def test_thinking_delta_event():
    e = ChatThinkingDeltaEvent(correlation_id="corr-1", delta="Hmm...")
    assert e.type == "chat.thinking.delta"


def test_stream_ended_event():
    e = ChatStreamEndedEvent(
        correlation_id="corr-1", session_id="sess-1", status="completed",
        usage={"input_tokens": 10, "output_tokens": 5}, context_status="green",
        timestamp=datetime.now(timezone.utc),
    )
    assert e.status == "completed"
    assert e.context_status == "green"


def test_stream_error_event():
    e = ChatStreamErrorEvent(
        correlation_id="corr-1", error_code="invalid_api_key",
        recoverable=False, user_message="Bad key",
        timestamp=datetime.now(timezone.utc),
    )
    assert e.type == "chat.stream.error"
    assert e.recoverable is False


def test_chat_topics_exist():
    assert Topics.CHAT_STREAM_STARTED == "chat.stream.started"
    assert Topics.CHAT_CONTENT_DELTA == "chat.content.delta"
    assert Topics.CHAT_THINKING_DELTA == "chat.thinking.delta"
    assert Topics.CHAT_STREAM_ENDED == "chat.stream.ended"
    assert Topics.CHAT_STREAM_ERROR == "chat.stream.error"


def test_chat_stream_slow_event_shape():
    ev = ChatStreamSlowEvent(
        correlation_id="corr-1",
        timestamp=datetime.now(timezone.utc),
    )
    dumped = ev.model_dump(mode="json")
    assert dumped["type"] == "chat.stream.slow"
    assert dumped["correlation_id"] == "corr-1"
    assert isinstance(dumped["timestamp"], str)


def test_chat_stream_ended_event_accepts_aborted_status():
    ev = ChatStreamEndedEvent(
        correlation_id="corr-1",
        session_id="sess-1",
        status="aborted",
        context_status="green",
        timestamp=datetime.now(timezone.utc),
    )
    assert ev.status == "aborted"


def test_chat_stream_slow_topic_constant_matches_type():
    assert Topics.CHAT_STREAM_SLOW == "chat.stream.slow"
    assert ChatStreamSlowEvent.model_fields["type"].default == Topics.CHAT_STREAM_SLOW

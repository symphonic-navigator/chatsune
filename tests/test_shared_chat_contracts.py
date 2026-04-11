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


def test_chat_message_dto_status_defaults_to_completed():
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


# --- Refusal detection & artefact persistence contracts ---

def test_artefact_ref_dto_required_fields():
    from shared.dtos.chat import ArtefactRefDto
    ref = ArtefactRefDto(
        artefact_id="a1",
        handle="h1",
        title="My snippet",
        artefact_type="code",
        operation="create",
    )
    assert ref.artefact_id == "a1"
    assert ref.operation == "create"


def test_artefact_ref_dto_rejects_invalid_operation():
    import pytest
    from pydantic import ValidationError
    from shared.dtos.chat import ArtefactRefDto

    with pytest.raises(ValidationError):
        ArtefactRefDto(
            artefact_id="a1",
            handle="h1",
            title="t",
            artefact_type="code",
            operation="delete",  # not in Literal
        )


def test_chat_message_dto_defaults_status_to_completed():
    from shared.dtos.chat import ChatMessageDto
    from datetime import datetime, timezone
    dto = ChatMessageDto(
        id="m1",
        session_id="s1",
        role="assistant",
        content="hi",
        token_count=1,
        created_at=datetime.now(timezone.utc),
    )
    assert dto.status == "completed"
    assert dto.refusal_text is None
    assert dto.artefact_refs is None
    assert dto.usage is None


def test_chat_message_dto_accepts_refused_status_and_new_fields():
    from shared.dtos.chat import ChatMessageDto, ArtefactRefDto
    from datetime import datetime, timezone
    dto = ChatMessageDto(
        id="m1",
        session_id="s1",
        role="assistant",
        content="",
        token_count=0,
        created_at=datetime.now(timezone.utc),
        status="refused",
        refusal_text="no can do",
        artefact_refs=[
            ArtefactRefDto(
                artefact_id="a1",
                handle="h1",
                title="t",
                artefact_type="code",
                operation="create",
            )
        ],
        usage={"input_tokens": 10, "output_tokens": 5},
    )
    assert dto.status == "refused"
    assert dto.refusal_text == "no can do"
    assert dto.artefact_refs and dto.artefact_refs[0].handle == "h1"
    assert dto.usage == {"input_tokens": 10, "output_tokens": 5}


def test_chat_stream_ended_event_accepts_refused_status():
    from shared.events.chat import ChatStreamEndedEvent
    from datetime import datetime, timezone
    ev = ChatStreamEndedEvent(
        correlation_id="c1",
        session_id="s1",
        status="refused",
        context_status="green",
        timestamp=datetime.now(timezone.utc),
    )
    assert ev.status == "refused"


def test_chat_tool_call_completed_event_artefact_ref_defaults_none():
    from shared.events.chat import ChatToolCallCompletedEvent
    from datetime import datetime, timezone
    ev = ChatToolCallCompletedEvent(
        correlation_id="c1",
        tool_call_id="tc1",
        tool_name="web_search",
        success=True,
        timestamp=datetime.now(timezone.utc),
    )
    assert ev.artefact_ref is None


def test_chat_tool_call_completed_event_carries_artefact_ref():
    from shared.events.chat import ChatToolCallCompletedEvent
    from shared.dtos.chat import ArtefactRefDto
    from datetime import datetime, timezone
    ref = ArtefactRefDto(
        artefact_id="a1",
        handle="h1",
        title="t",
        artefact_type="code",
        operation="create",
    )
    ev = ChatToolCallCompletedEvent(
        correlation_id="c1",
        tool_call_id="tc1",
        tool_name="create_artefact",
        success=True,
        artefact_ref=ref,
        timestamp=datetime.now(timezone.utc),
    )
    assert ev.artefact_ref is not None
    assert ev.artefact_ref.handle == "h1"

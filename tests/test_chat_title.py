from datetime import datetime, timezone


def test_chat_session_dto_has_title():
    from shared.dtos.chat import ChatSessionDto

    dto = ChatSessionDto(
        id="sess-1",
        user_id="user-1",
        persona_id="persona-1",
        model_unique_id="ollama_cloud:llama3.2",
        state="idle",
        title=None,
        created_at=datetime(2026, 4, 4, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 4, tzinfo=timezone.utc),
    )
    assert dto.title is None

    dto2 = ChatSessionDto(
        id="sess-2",
        user_id="user-1",
        persona_id="persona-1",
        model_unique_id="ollama_cloud:llama3.2",
        state="idle",
        title="My chat",
        created_at=datetime(2026, 4, 4, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 4, tzinfo=timezone.utc),
    )
    assert dto2.title == "My chat"


def test_chat_session_title_updated_event():
    from shared.events.chat import ChatSessionTitleUpdatedEvent

    event = ChatSessionTitleUpdatedEvent(
        session_id="sess-1",
        title="Generated title",
        correlation_id="corr-1",
        timestamp=datetime(2026, 4, 4, tzinfo=timezone.utc),
    )
    assert event.type == "chat.session.title_updated"


def test_topic_exists():
    from shared.topics import Topics

    assert Topics.CHAT_SESSION_TITLE_UPDATED == "chat.session.title_updated"

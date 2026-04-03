from shared.events.chat import (
    ChatMessagesTruncatedEvent,
    ChatMessageUpdatedEvent,
    ChatMessageDeletedEvent,
    ChatStreamEndedEvent,
)
from shared.topics import Topics
from datetime import datetime, timezone


def test_messages_truncated_event():
    now = datetime.now(timezone.utc)
    event = ChatMessagesTruncatedEvent(
        session_id="sess-1",
        after_message_id="msg-5",
        correlation_id="corr-1",
        timestamp=now,
    )
    assert event.type == "chat.messages.truncated"
    assert event.session_id == "sess-1"
    assert event.after_message_id == "msg-5"


def test_message_updated_event():
    now = datetime.now(timezone.utc)
    event = ChatMessageUpdatedEvent(
        session_id="sess-1",
        message_id="msg-5",
        content="edited content",
        token_count=42,
        correlation_id="corr-1",
        timestamp=now,
    )
    assert event.type == "chat.message.updated"


def test_message_deleted_event():
    now = datetime.now(timezone.utc)
    event = ChatMessageDeletedEvent(
        session_id="sess-1",
        message_id="msg-10",
        correlation_id="corr-1",
        timestamp=now,
    )
    assert event.type == "chat.message.deleted"


def test_stream_ended_has_fill_percentage():
    now = datetime.now(timezone.utc)
    event = ChatStreamEndedEvent(
        correlation_id="corr-1",
        session_id="sess-1",
        status="completed",
        usage=None,
        context_status="yellow",
        context_fill_percentage=0.55,
        timestamp=now,
    )
    assert event.context_fill_percentage == 0.55


def test_topics_exist():
    assert Topics.CHAT_MESSAGES_TRUNCATED == "chat.messages.truncated"
    assert Topics.CHAT_MESSAGE_UPDATED == "chat.message.updated"
    assert Topics.CHAT_MESSAGE_DELETED == "chat.message.deleted"

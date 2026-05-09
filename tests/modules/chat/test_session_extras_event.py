from datetime import datetime, timezone

from shared.dtos.chat import ChatSessionExtras
from shared.events.chat import ChatSessionExtrasUpdatedEvent
from shared.topics import Topics


def test_topic_constant_present():
    assert Topics.CHAT_SESSION_EXTRAS_UPDATED == "chat.session.extras.updated"


def test_event_carries_session_id_and_extras():
    extras = ChatSessionExtras(
        tools_enabled=True, reasoning_mode="off", reasoning_effort=None
    )
    now = datetime.now(timezone.utc)
    ev = ChatSessionExtrasUpdatedEvent(
        session_id="s1",
        extras=extras,
        correlation_id="corr-1",
        timestamp=now,
    )
    assert ev.session_id == "s1"
    assert ev.extras.tools_enabled is True
    assert ev.extras.reasoning_mode == "off"
    assert ev.extras.reasoning_effort is None
    assert ev.type == "chat.session.extras.updated"
    assert ev.correlation_id == "corr-1"
    assert ev.timestamp == now

"""Smoke test for the ChatSessionExtrasUpdatedEvent shape — full-bus integration
is covered by manual verification in Task 25."""
from datetime import datetime, timezone

from shared.dtos.chat import ChatSessionExtras
from shared.events.chat import ChatSessionExtrasUpdatedEvent


def test_extras_event_dto_serialises():
    extras = ChatSessionExtras(
        tools_enabled=True, reasoning_mode="off", reasoning_effort=None,
    )
    ev = ChatSessionExtrasUpdatedEvent(
        session_id="s1",
        extras=extras,
        correlation_id="corr-1",
        timestamp=datetime.now(timezone.utc),
    )
    assert ev.session_id == "s1"
    assert ev.extras.tools_enabled is True
    assert ev.type == "chat.session.extras.updated"
    payload = ev.model_dump()
    assert payload["extras"]["tools_enabled"] is True
    assert payload["session_id"] == "s1"
    assert payload["correlation_id"] == "corr-1"

from datetime import datetime, timezone
from shared.events.base import BaseEvent
from shared.events.audit import AuditLoggedEvent
from shared.topics import Topics


def test_base_event_has_required_fields():
    event = BaseEvent(
        type="user.created",
        scope="global",
        correlation_id="corr-1",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        payload={"user_id": "u1"},
    )
    assert event.type == "user.created"
    assert event.scope == "global"
    assert event.sequence == ""
    assert len(event.id) > 0


def test_base_event_id_is_unique():
    a = BaseEvent(type="x", scope="global", correlation_id="c", timestamp=datetime.now(timezone.utc), payload={})
    b = BaseEvent(type="x", scope="global", correlation_id="c", timestamp=datetime.now(timezone.utc), payload={})
    assert a.id != b.id


def test_base_event_sequence_is_mutable():
    event = BaseEvent(type="x", scope="global", correlation_id="c", timestamp=datetime.now(timezone.utc), payload={})
    event.sequence = "1735000000000-0"
    assert event.sequence == "1735000000000-0"


def test_audit_logged_event():
    event = AuditLoggedEvent(
        actor_id="user1",
        action="user.created",
        resource_type="user",
        resource_id="user2",
        detail={"role": "admin"},
    )
    assert event.actor_id == "user1"
    assert event.action == "user.created"


def test_topics_audit_logged_constant():
    assert Topics.AUDIT_LOGGED == "audit.logged"

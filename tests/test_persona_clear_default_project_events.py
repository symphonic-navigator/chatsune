"""Mindspace Phase 3 (task 15) — per-persona PERSONA_UPDATED event on
default-project cascade.

The project cascade-delete clears ``default_project_id`` on every
persona that pointed at the deleted project. The Phase 2 bulk update
returned the affected ids; Phase 3 extends the public-API wrapper so
each affected persona produces one ``PERSONA_UPDATED`` event with the
new (cleared) DTO state.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest_asyncio

from backend.database import connect_db, disconnect_db, get_db, get_redis
from backend.modules import persona as persona_service
from backend.ws.event_bus import EventBus, set_event_bus
from backend.ws.manager import ConnectionManager, set_manager
from shared.topics import Topics


@pytest_asyncio.fixture
async def env(clean_db):
    await connect_db()
    manager = ConnectionManager()
    set_manager(manager)
    set_event_bus(EventBus(redis=get_redis(), manager=manager))
    yield get_db()
    await disconnect_db()


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _seed_persona(
    db, *, user_id: str, default_project_id: str | None,
) -> str:
    pid = f"pers-{uuid4().hex[:8]}"
    await db["personas"].insert_one({
        "_id": pid,
        "user_id": user_id,
        "name": "X",
        "tagline": "x",
        "model_unique_id": None,
        "system_prompt": "...",
        "temperature": 0.8,
        "reasoning_enabled": False,
        "soft_cot_enabled": False,
        "vision_fallback_model": None,
        "nsfw": False,
        "use_memory": True,
        "colour_scheme": "solar",
        "display_order": 0,
        "monogram": "XX",
        "pinned": False,
        "profile_image": None,
        "default_project_id": default_project_id,
        "created_at": _now(),
        "updated_at": _now(),
    })
    return pid


async def test_clear_default_emits_one_event_per_affected_persona(
    env, monkeypatch,
):
    db = env
    a = await _seed_persona(db, user_id="u1", default_project_id="proj-X")
    b = await _seed_persona(db, user_id="u1", default_project_id="proj-X")
    # Persona pointing at a different project is untouched.
    c = await _seed_persona(db, user_id="u1", default_project_id="other")
    # Persona without a default is untouched.
    d = await _seed_persona(db, user_id="u1", default_project_id=None)

    captured: list[tuple] = []
    original_publish = EventBus.publish

    async def capturing_publish(
        self, topic, event,
        scope="global", target_user_ids=None, correlation_id=None,
    ):
        captured.append((topic, event, scope, target_user_ids))
        return await original_publish(
            self, topic, event,
            scope=scope, target_user_ids=target_user_ids,
            correlation_id=correlation_id,
        )

    monkeypatch.setattr(EventBus, "publish", capturing_publish)

    affected = await persona_service.clear_default_project_for_all(
        "u1", "proj-X",
    )
    assert set(affected) == {a, b}

    persona_events = [c for c in captured if c[0] == Topics.PERSONA_UPDATED]
    assert len(persona_events) == 2

    affected_persona_ids = {ev[1].persona_id for ev in persona_events}
    assert affected_persona_ids == {a, b}

    for topic, event, scope, targets in persona_events:
        assert event.user_id == "u1"
        assert event.persona.default_project_id is None
        assert scope == f"persona:{event.persona_id}"
        assert targets == ["u1"]


async def test_no_personas_affected_emits_no_events(env, monkeypatch):
    db = env
    await _seed_persona(db, user_id="u1", default_project_id=None)

    captured: list[tuple] = []
    original_publish = EventBus.publish

    async def capturing_publish(
        self, topic, event,
        scope="global", target_user_ids=None, correlation_id=None,
    ):
        captured.append((topic, event, scope, target_user_ids))
        return await original_publish(
            self, topic, event,
            scope=scope, target_user_ids=target_user_ids,
            correlation_id=correlation_id,
        )

    monkeypatch.setattr(EventBus, "publish", capturing_publish)

    affected = await persona_service.clear_default_project_for_all(
        "u1", "proj-not-pointed-at",
    )
    assert affected == []

    persona_events = [c for c in captured if c[0] == Topics.PERSONA_UPDATED]
    assert persona_events == []


async def test_does_not_affect_other_users(env, monkeypatch):
    db = env
    own = await _seed_persona(db, user_id="u1", default_project_id="proj-X")
    foreign = await _seed_persona(db, user_id="u2", default_project_id="proj-X")

    captured: list[tuple] = []
    original_publish = EventBus.publish

    async def capturing_publish(
        self, topic, event,
        scope="global", target_user_ids=None, correlation_id=None,
    ):
        captured.append((topic, event, scope, target_user_ids))
        return await original_publish(
            self, topic, event,
            scope=scope, target_user_ids=target_user_ids,
            correlation_id=correlation_id,
        )

    monkeypatch.setattr(EventBus, "publish", capturing_publish)

    affected = await persona_service.clear_default_project_for_all(
        "u1", "proj-X",
    )
    assert affected == [own]

    foreign_doc = await db["personas"].find_one({"_id": foreign})
    assert foreign_doc["default_project_id"] == "proj-X"

    persona_events = [c for c in captured if c[0] == Topics.PERSONA_UPDATED]
    assert len(persona_events) == 1
    assert persona_events[0][1].persona_id == own

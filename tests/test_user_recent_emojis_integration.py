"""Integration test for UserService.touch_recent_emojis.

Requires MongoDB replica-set + Redis. Runs inside Docker Compose only.
On the host pytest run, this file is in the host-ignore list (memory:
feedback_db_tests_on_host) — invoke it via ``docker compose exec backend
pytest tests/test_user_recent_emojis_integration.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest_asyncio

from backend.modules.user import UserService
from backend.modules.user._models import DEFAULT_RECENT_EMOJIS


@dataclass
class _CapturedEvent:
    """Snapshot of a single event_bus.publish() call."""

    topic: str
    payload: dict[str, Any]
    target_user_ids: list[str] | None
    scope: str


class _RecordingEventBus:
    """Stub event bus that records every publish call.

    Accepts the same kwargs as the real EventBus.publish so callers can
    use either ``scope`` or ``target_user_ids`` without surprises.
    """

    def __init__(self) -> None:
        self.published: list[_CapturedEvent] = []

    async def publish(
        self,
        topic: str,
        event: Any,
        scope: str = "global",
        target_user_ids: list[str] | None = None,
        correlation_id: str | None = None,
        target_connection_id: str | None = None,
    ) -> None:
        self.published.append(
            _CapturedEvent(
                topic=str(topic),
                payload=event.model_dump(mode="json"),
                target_user_ids=list(target_user_ids) if target_user_ids else None,
                scope=scope,
            )
        )

    def clear(self) -> None:
        self.published.clear()


@pytest_asyncio.fixture
async def event_bus() -> _RecordingEventBus:
    return _RecordingEventBus()


@pytest_asyncio.fixture
async def user_service(db, event_bus) -> UserService:
    return UserService(db, event_bus)


@pytest_asyncio.fixture
async def seed_user(db):
    """Insert a minimal user document and return its id."""

    async def _seed(username: str = "alice") -> str:
        user_id = str(uuid4())
        now = datetime.now(UTC)
        await db["users"].insert_one({
            "_id": user_id,
            "username": username,
            "email": f"{user_id[:6]}@example.com",
            "display_name": username.title(),
            "password_hash": "x",
            "password_hash_version": 1,
            "role": "user",
            "is_active": True,
            "must_change_password": False,
            "recent_emojis": list(DEFAULT_RECENT_EMOJIS),
            "created_at": now,
            "updated_at": now,
        })
        return user_id

    return _seed


async def test_touch_recent_emojis_persists_and_publishes(
    user_service: UserService,
    event_bus: _RecordingEventBus,
    seed_user,
    db,
):
    user_id = await seed_user(username="alice")

    await user_service.touch_recent_emojis(user_id, ["🚀", "🎯"])

    refreshed = await db["users"].find_one({"_id": user_id})
    assert refreshed is not None
    assert refreshed["recent_emojis"][:2] == ["🚀", "🎯"]
    assert len(refreshed["recent_emojis"]) == 6

    published = [e for e in event_bus.published if e.topic == "user.recent_emojis.updated"]
    assert len(published) == 1
    assert published[0].payload["user_id"] == user_id
    assert published[0].payload["emojis"][:2] == ["🚀", "🎯"]
    assert published[0].target_user_ids == [user_id]


async def test_touch_recent_emojis_no_change_does_not_publish(
    user_service: UserService,
    event_bus: _RecordingEventBus,
    seed_user,
):
    user_id = await seed_user(username="bob")

    # First call front-loads "🚀" → list mutates → one event published.
    await user_service.touch_recent_emojis(user_id, ["🚀"])
    event_bus.clear()

    # Second call with the same emoji is a no-op — list already starts with 🚀.
    await user_service.touch_recent_emojis(user_id, ["🚀"])

    published = [e for e in event_bus.published if e.topic == "user.recent_emojis.updated"]
    assert published == []


async def test_touch_recent_emojis_empty_input_is_noop(
    user_service: UserService,
    event_bus: _RecordingEventBus,
    seed_user,
):
    user_id = await seed_user(username="carol")
    await user_service.touch_recent_emojis(user_id, [])
    assert event_bus.published == []


async def test_touch_recent_emojis_unknown_user_is_noop(
    user_service: UserService,
    event_bus: _RecordingEventBus,
):
    await user_service.touch_recent_emojis("does-not-exist", ["🚀"])
    assert event_bus.published == []

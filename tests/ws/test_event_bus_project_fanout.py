"""Mindspace review blocker 1 — every project topic must have a fan-out rule.

Without an entry in ``_FANOUT`` the event bus persists the event to Redis
but logs a warning and never delivers it to the WebSocket client. The
six Mindspace topics are all per-user private events and route as
``([], True)`` — no role-based broadcast, deliver to ``target_user_ids``.
"""
from datetime import datetime, timezone
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from backend.ws.event_bus import _FANOUT, EventBus
from backend.ws.manager import ConnectionManager
from shared.events.chat import ChatSessionProjectUpdatedEvent
from shared.events.project import (
    ProjectCreatedEvent,
    ProjectDeletedEvent,
    ProjectPinnedUpdatedEvent,
    ProjectUpdatedEvent,
)
from shared.dtos.project import ProjectDto
from shared.topics import Topics


PROJECT_TOPICS = (
    Topics.PROJECT_CREATED,
    Topics.PROJECT_UPDATED,
    Topics.PROJECT_DELETED,
    Topics.PROJECT_PINNED_UPDATED,
    Topics.CHAT_SESSION_PROJECT_UPDATED,
    Topics.USER_RECENT_PROJECT_EMOJIS_UPDATED,
)


@pytest.mark.parametrize("topic", PROJECT_TOPICS)
def test_project_topic_present_in_fanout(topic):
    """Every Mindspace topic must have a fan-out rule registered."""
    assert topic in _FANOUT, (
        f"Topic {topic!r} missing from _FANOUT — events will persist but "
        "never reach the WebSocket client."
    )


@pytest.mark.parametrize("topic", PROJECT_TOPICS)
def test_project_topic_routes_to_target_user_only(topic):
    """All six Mindspace topics are private per-user state — no role broadcast."""
    roles, send_to_targets = _FANOUT[topic]
    assert roles == [], (
        f"Topic {topic!r} should not broadcast to any role — it is "
        "per-user private state."
    )
    assert send_to_targets is True, (
        f"Topic {topic!r} must deliver to target_user_ids."
    )


def _make_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.xadd = AsyncMock(return_value="1735000000000-0")
    redis.xtrim = AsyncMock()
    return redis


def _make_manager() -> MagicMock:
    manager = MagicMock(spec=ConnectionManager)
    manager._user_roles = {}
    manager.broadcast_to_roles = AsyncMock()
    manager.send_to_users = AsyncMock()
    manager.send_to_user = AsyncMock()
    manager.user_ids_by_role = MagicMock(return_value=[])
    return manager


def _project_dto() -> ProjectDto:
    now = datetime.now(timezone.utc)
    return ProjectDto(
        id="p1",
        user_id="u1",
        title="P",
        emoji=None,
        description=None,
        nsfw=False,
        pinned=False,
        sort_order=0,
        knowledge_library_ids=[],
        created_at=now,
        updated_at=now,
    )


async def test_project_created_delivers_to_target_user():
    redis = _make_redis()
    manager = _make_manager()
    bus = EventBus(redis=redis, manager=manager)
    event = ProjectCreatedEvent(
        project_id="p1",
        user_id="u1",
        project=_project_dto(),
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(
        Topics.PROJECT_CREATED, event, target_user_ids=["u1"],
    )
    manager.broadcast_to_roles.assert_awaited_once_with([], ANY)
    manager.send_to_users.assert_awaited_once_with(["u1"], ANY)


async def test_project_deleted_delivers_to_target_user():
    redis = _make_redis()
    manager = _make_manager()
    bus = EventBus(redis=redis, manager=manager)
    event = ProjectDeletedEvent(
        project_id="p1", user_id="u1",
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(
        Topics.PROJECT_DELETED, event, target_user_ids=["u1"],
    )
    manager.send_to_users.assert_awaited_once_with(["u1"], ANY)


async def test_project_pinned_updated_delivers_to_target_user():
    redis = _make_redis()
    manager = _make_manager()
    bus = EventBus(redis=redis, manager=manager)
    event = ProjectPinnedUpdatedEvent(
        project_id="p1", user_id="u1", pinned=True,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(
        Topics.PROJECT_PINNED_UPDATED, event, target_user_ids=["u1"],
    )
    manager.send_to_users.assert_awaited_once_with(["u1"], ANY)


async def test_chat_session_project_updated_delivers_to_target_user():
    redis = _make_redis()
    manager = _make_manager()
    bus = EventBus(redis=redis, manager=manager)
    event = ChatSessionProjectUpdatedEvent(
        session_id="s1", project_id="p1", user_id="u1",
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(
        Topics.CHAT_SESSION_PROJECT_UPDATED, event, target_user_ids=["u1"],
    )
    manager.send_to_users.assert_awaited_once_with(["u1"], ANY)


async def test_project_updated_delivers_to_target_user():
    redis = _make_redis()
    manager = _make_manager()
    bus = EventBus(redis=redis, manager=manager)
    event = ProjectUpdatedEvent(
        project_id="p1", user_id="u1", project=_project_dto(),
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(
        Topics.PROJECT_UPDATED, event, target_user_ids=["u1"],
    )
    manager.send_to_users.assert_awaited_once_with(["u1"], ANY)


# NOTE: ``USER_RECENT_PROJECT_EMOJIS_UPDATED`` has no backend Pydantic event
# model yet (the backend does not currently publish the topic — the
# frontend subscribes pre-emptively, see AppLayout). Membership and
# routing-rule tests above pin the wiring so when a future phase starts
# emitting the topic, fan-out works straight away.

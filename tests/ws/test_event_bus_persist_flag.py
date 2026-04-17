from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from backend.ws.event_bus import EventBus
from backend.ws.manager import ConnectionManager
from shared.topics import Topics


def make_redis():
    redis = AsyncMock()
    redis.xadd = AsyncMock(return_value="1735000000000-0")
    redis.xtrim = AsyncMock()
    return redis


def make_manager():
    manager = MagicMock(spec=ConnectionManager)
    manager._user_roles = {}
    manager.broadcast_to_roles = AsyncMock()
    manager.send_to_users = AsyncMock()
    manager.send_to_user = AsyncMock()
    manager.user_ids_by_role = MagicMock(return_value=[])
    return manager


class _MinimalEvent(BaseModel):
    """Minimal payload for testing purposes."""
    detail: str = "test"


def test_integration_secrets_topics_are_non_persistent():
    assert Topics.INTEGRATION_SECRETS_HYDRATED.persist is False
    assert Topics.INTEGRATION_SECRETS_CLEARED.persist is False


def test_lookup_finds_persist_flag():
    from backend.ws.event_bus import _topic_definition_for
    defn = _topic_definition_for("integration.secrets.hydrated")
    assert defn is not None
    assert defn.persist is False


def test_lookup_returns_none_for_unknown():
    from backend.ws.event_bus import _topic_definition_for
    assert _topic_definition_for("does.not.exist") is None


async def test_publish_skips_xadd_for_persist_false_topic():
    """publish() must not call redis.xadd for topics with persist=False."""
    redis = make_redis()
    bus = EventBus(redis=redis, manager=make_manager())
    await bus.publish(
        Topics.INTEGRATION_SECRETS_HYDRATED,
        _MinimalEvent(),
        target_user_ids=["u1"],
    )
    redis.xadd.assert_not_awaited()


async def test_publish_calls_xadd_for_persistent_topic():
    """Positive-control: publish() must call redis.xadd for normal persistent topics."""
    redis = make_redis()
    bus = EventBus(redis=redis, manager=make_manager())
    from shared.events.auth import UserCreatedEvent
    event = UserCreatedEvent(
        user_id="u1", username="alice", role="user",
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(Topics.USER_CREATED, event)
    redis.xadd.assert_awaited_once()

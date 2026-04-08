from datetime import datetime, timezone
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from backend.ws.event_bus import EventBus
from backend.ws.manager import ConnectionManager
from shared.events.auth import UserCreatedEvent, UserUpdatedEvent, UserDeactivatedEvent, UserPasswordResetEvent
from shared.events.audit import AuditLoggedEvent
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


def make_event():
    return UserCreatedEvent(
        user_id="u1", username="alice", role="user",
        timestamp=datetime.now(timezone.utc),
    )


async def test_publish_calls_xadd_with_stream_key():
    redis = make_redis()
    bus = EventBus(redis=redis, manager=make_manager())
    await bus.publish(Topics.USER_CREATED, make_event())
    redis.xadd.assert_awaited_once()
    assert redis.xadd.call_args[0][0] == "events:global"


async def test_publish_does_not_inline_trim():
    # Stream trimming runs in a periodic background task (start_periodic_trim),
    # NOT inline per publish. This test pins that contract so we do not
    # accidentally regress into per-call xtrim pressure on Redis.
    redis = make_redis()
    bus = EventBus(redis=redis, manager=make_manager())
    await bus.publish(Topics.USER_CREATED, make_event())
    redis.xtrim.assert_not_awaited()


async def test_publish_sets_sequence_from_stream_id():
    redis = make_redis()
    redis.xadd = AsyncMock(return_value="1735111111111-0")
    manager = make_manager()
    bus = EventBus(redis=redis, manager=manager)
    await bus.publish(Topics.USER_CREATED, make_event())
    # The broadcast call should contain the sequence in the envelope
    call_args = manager.broadcast_to_roles.call_args
    event_dict = call_args[0][1]
    assert event_dict["sequence"] == "1735111111111-0"


async def test_user_created_broadcasts_to_admins_only():
    redis = make_redis()
    manager = make_manager()
    bus = EventBus(redis=redis, manager=manager)
    await bus.publish(Topics.USER_CREATED, make_event(), target_user_ids=["u1"])
    manager.broadcast_to_roles.assert_awaited_once_with(
        ["admin", "master_admin"], ANY
    )
    manager.send_to_users.assert_not_awaited()


async def test_user_updated_broadcasts_to_admins_and_target():
    redis = make_redis()
    manager = make_manager()
    bus = EventBus(redis=redis, manager=manager)
    event = UserUpdatedEvent(
        user_id="u1", changes={"display_name": "Bob"},
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(Topics.USER_UPDATED, event, target_user_ids=["u1"])
    manager.broadcast_to_roles.assert_awaited_once_with(
        ["admin", "master_admin"], ANY
    )
    manager.send_to_users.assert_awaited_once_with(["u1"], ANY)


async def test_audit_logged_sends_to_master_admin_always():
    redis = make_redis()
    manager = make_manager()
    manager.user_ids_by_role = MagicMock(return_value=[])
    bus = EventBus(redis=redis, manager=manager)
    event = AuditLoggedEvent(
        actor_id="admin1", action="user.created",
        resource_type="user", resource_id="u1",
    )
    await bus.publish(Topics.AUDIT_LOGGED, event)
    manager.broadcast_to_roles.assert_awaited_once_with(["master_admin"], ANY)


async def test_audit_logged_sends_to_admin_only_if_actor_matches():
    redis = make_redis()
    manager = make_manager()
    # admin1 is the actor, admin2 is not
    manager.user_ids_by_role = MagicMock(return_value=["admin1", "admin2"])
    bus = EventBus(redis=redis, manager=manager)
    event = AuditLoggedEvent(
        actor_id="admin1", action="user.created",
        resource_type="user", resource_id="u1",
    )
    await bus.publish(Topics.AUDIT_LOGGED, event)
    # Only admin1 (the actor) gets it, not admin2
    manager.send_to_user.assert_awaited_once_with("admin1", ANY)


async def test_user_deactivated_broadcasts_to_admins_and_target():
    redis = make_redis()
    manager = make_manager()
    bus = EventBus(redis=redis, manager=manager)
    event = UserDeactivatedEvent(
        user_id="u1",
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(Topics.USER_DEACTIVATED, event, target_user_ids=["u1"])
    manager.broadcast_to_roles.assert_awaited_once_with(
        ["admin", "master_admin"], ANY
    )
    manager.send_to_users.assert_awaited_once_with(["u1"], ANY)


async def test_user_password_reset_broadcasts_to_admins_and_target():
    redis = make_redis()
    manager = make_manager()
    bus = EventBus(redis=redis, manager=manager)
    event = UserPasswordResetEvent(
        user_id="u1",
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(Topics.USER_PASSWORD_RESET, event, target_user_ids=["u1"])
    manager.broadcast_to_roles.assert_awaited_once_with(
        ["admin", "master_admin"], ANY
    )
    manager.send_to_users.assert_awaited_once_with(["u1"], ANY)


async def test_publish_uses_custom_scope():
    redis = make_redis()
    bus = EventBus(redis=redis, manager=make_manager())
    await bus.publish(Topics.USER_CREATED, make_event(), scope="custom")
    assert redis.xadd.call_args[0][0] == "events:custom"

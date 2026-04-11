import pytest
from unittest.mock import ANY, AsyncMock

from backend.ws.event_bus import EventBus
from shared.topics import Topics

pytestmark = pytest.mark.asyncio


def _make_bus() -> tuple[EventBus, AsyncMock]:
    redis = AsyncMock()
    redis.xadd = AsyncMock(return_value="1-0")
    manager = AsyncMock()
    bus = EventBus(redis, manager)
    return bus, manager


async def test_target_connection_id_routes_to_single_connection():
    bus, manager = _make_bus()

    from shared.events.chat import ChatClientToolDispatchEvent
    event = ChatClientToolDispatchEvent(
        session_id="s1",
        tool_call_id="t1",
        tool_name="calculate_js",
        arguments={"code": "console.log(1)"},
        timeout_ms=5000,
        target_connection_id="conn-42",
    )

    await bus.publish(
        Topics.CHAT_CLIENT_TOOL_DISPATCH,
        event,
        scope="user:u1",
        target_user_ids=["u1"],
        target_connection_id="conn-42",
    )

    # Exactly one targeted call — to the specific connection.
    manager.send_to_connection.assert_awaited_once()
    args, _ = manager.send_to_connection.call_args
    assert args[0] == "u1"
    assert args[1] == "conn-42"
    # No broadcast-to-user fallback.
    manager.send_to_users.assert_not_awaited()
    # Role broadcast still fires (with empty roles list, so it's a no-op
    # in practice — but the call itself must still happen because every
    # publish goes through broadcast_to_roles).
    manager.broadcast_to_roles.assert_awaited_once_with([], ANY)


async def test_without_target_connection_id_uses_normal_fanout():
    bus, manager = _make_bus()

    from shared.events.chat import ChatToolCallStartedEvent
    from datetime import datetime, timezone

    # Existing topic — must continue to use send_to_users
    event = ChatToolCallStartedEvent(
        correlation_id="c",
        tool_call_id="t1",
        tool_name="web_search",
        arguments={},
        timestamp=datetime.now(timezone.utc),
    )

    await bus.publish(
        Topics.CHAT_TOOL_CALL_STARTED,
        event,
        scope="user:u1",
        target_user_ids=["u1"],
    )

    manager.send_to_users.assert_awaited_once_with(["u1"], ANY)
    manager.send_to_connection.assert_not_awaited()

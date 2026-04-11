import asyncio
import json

import pytest

from backend.modules.tools._client_dispatcher import ClientToolDispatcher

pytestmark = pytest.mark.asyncio


class _FakeEventBus:
    def __init__(self) -> None:
        self.published: list[dict] = []

    async def publish(self, topic, event, **kwargs):
        self.published.append({"topic": topic, "event": event, "kwargs": kwargs})


@pytest.fixture
def bus(monkeypatch):
    bus = _FakeEventBus()
    import backend.modules.tools._client_dispatcher as mod
    monkeypatch.setattr(mod, "get_event_bus", lambda: bus)
    return bus


async def test_happy_path(bus):
    dispatcher = ClientToolDispatcher()

    async def simulate_client():
        await asyncio.sleep(0.01)  # let dispatch publish first
        dispatcher.resolve(
            tool_call_id="tc-1",
            received_from_user_id="user-a",
            result_json='{"stdout": "3\\n", "error": null}',
        )

    simulator = asyncio.create_task(simulate_client())
    result = await dispatcher.dispatch(
        user_id="user-a",
        session_id="sess-1",
        tool_call_id="tc-1",
        tool_name="calculate_js",
        arguments={"code": "console.log(3)"},
        server_timeout_ms=1000,
        client_timeout_ms=500,
        target_connection_id="conn-1",
    )
    await simulator

    assert result == '{"stdout": "3\\n", "error": null}'
    assert dispatcher._pending == {}
    assert len(bus.published) == 1
    pub = bus.published[0]
    assert pub["topic"] == "chat.client_tool.dispatch"
    assert pub["kwargs"]["target_connection_id"] == "conn-1"


async def test_timeout_returns_synthetic_error(bus):
    dispatcher = ClientToolDispatcher()

    result_json = await dispatcher.dispatch(
        user_id="user-a",
        session_id="sess-1",
        tool_call_id="tc-2",
        tool_name="calculate_js",
        arguments={"code": "x"},
        server_timeout_ms=50,
        client_timeout_ms=25,
        target_connection_id="conn-1",
    )
    result = json.loads(result_json)

    assert result == {
        "stdout": "",
        "error": "Tool execution timed out after 50ms",
    }
    assert dispatcher._pending == {}


async def test_resolve_user_mismatch_is_ignored(bus, caplog):
    dispatcher = ClientToolDispatcher()

    async def mismatched_client():
        await asyncio.sleep(0.01)
        dispatcher.resolve(
            tool_call_id="tc-3",
            received_from_user_id="user-b",  # wrong user
            result_json='{"stdout": "evil", "error": null}',
        )
        # then correct user resolves
        await asyncio.sleep(0.01)
        dispatcher.resolve(
            tool_call_id="tc-3",
            received_from_user_id="user-a",
            result_json='{"stdout": "ok", "error": null}',
        )

    task = asyncio.create_task(mismatched_client())
    with caplog.at_level("WARNING"):
        result = await dispatcher.dispatch(
            user_id="user-a",
            session_id="sess-1",
            tool_call_id="tc-3",
            tool_name="calculate_js",
            arguments={"code": "x"},
            server_timeout_ms=1000,
            client_timeout_ms=500,
            target_connection_id="conn-1",
        )
    await task

    assert result == '{"stdout": "ok", "error": null}'
    assert any("user mismatch" in rec.message for rec in caplog.records)


async def test_cancel_for_user_resolves_with_disconnect_error(bus):
    dispatcher = ClientToolDispatcher()

    async def disconnect_soon():
        await asyncio.sleep(0.01)
        dispatcher.cancel_for_user("user-a")

    task = asyncio.create_task(disconnect_soon())
    result_json = await dispatcher.dispatch(
        user_id="user-a",
        session_id="sess-1",
        tool_call_id="tc-4",
        tool_name="calculate_js",
        arguments={"code": "x"},
        server_timeout_ms=1000,
        client_timeout_ms=500,
        target_connection_id="conn-1",
    )
    await task
    result = json.loads(result_json)

    assert result == {
        "stdout": "",
        "error": "Client disconnected before tool completed",
    }


async def test_unknown_tool_call_id_resolve_is_silent(bus, caplog):
    dispatcher = ClientToolDispatcher()
    with caplog.at_level("WARNING"):
        dispatcher.resolve(
            tool_call_id="ghost",
            received_from_user_id="user-a",
            result_json='{"stdout": "x", "error": null}',
        )
    assert any("unknown tool_call_id" in rec.message for rec in caplog.records)


async def test_duplicate_resolve_first_wins(bus):
    dispatcher = ClientToolDispatcher()

    async def respond_twice():
        await asyncio.sleep(0.01)
        dispatcher.resolve(
            tool_call_id="tc-5",
            received_from_user_id="user-a",
            result_json='{"stdout": "first", "error": null}',
        )
        dispatcher.resolve(
            tool_call_id="tc-5",
            received_from_user_id="user-a",
            result_json='{"stdout": "second", "error": null}',
        )

    task = asyncio.create_task(respond_twice())
    result = await dispatcher.dispatch(
        user_id="user-a",
        session_id="sess-1",
        tool_call_id="tc-5",
        tool_name="calculate_js",
        arguments={"code": "x"},
        server_timeout_ms=1000,
        client_timeout_ms=500,
        target_connection_id="conn-1",
    )
    await task

    assert '"stdout": "first"' in result

"""Tests for client-provided correlation_id acceptance in chat handlers."""

from unittest.mock import AsyncMock
import pytest

from backend.database import connect_db, disconnect_db, get_db
from backend.modules.chat._repository import ChatRepository


@pytest.fixture
async def repo(clean_db):
    await connect_db()
    r = ChatRepository(get_db())
    await r.create_indexes()
    yield r
    await disconnect_db()


@pytest.mark.asyncio
async def test_handle_chat_send_uses_client_correlation_id(repo, monkeypatch):
    """Handler must forward the client-supplied correlation_id to published events."""
    captured = {}

    class FakeBus:
        async def publish(self, event_type, event, *, scope, target_user_ids, correlation_id):
            captured.setdefault("correlation_ids", []).append(correlation_id)

    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.get_event_bus",
        lambda: FakeBus(),
    )
    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.run_inference",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.cancel_all_for_user",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.track_extraction_trigger",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.get_db",
        lambda: get_db(),
    )

    session = await repo.create_session("user1", "persona1")
    session_id = session["_id"]

    from backend.modules.chat._handlers_ws import handle_chat_send
    await handle_chat_send("user1", {
        "session_id": session_id,
        "content": [{"type": "text", "text": "hello"}],
        "correlation_id": "client-supplied-id",
    })

    assert captured.get("correlation_ids"), "No events were published"
    assert all(
        cid == "client-supplied-id" for cid in captured["correlation_ids"]
    ), f"Expected all events to carry 'client-supplied-id', got: {captured['correlation_ids']}"


@pytest.mark.asyncio
async def test_handle_chat_send_generates_when_missing(repo, monkeypatch):
    """Backwards compat: if client omits correlation_id, server generates one."""
    captured = {}

    class FakeBus:
        async def publish(self, event_type, event, *, scope, target_user_ids, correlation_id):
            captured.setdefault("correlation_ids", []).append(correlation_id)

    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.get_event_bus",
        lambda: FakeBus(),
    )
    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.run_inference",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.cancel_all_for_user",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.track_extraction_trigger",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "backend.modules.chat._handlers_ws.get_db",
        lambda: get_db(),
    )

    session = await repo.create_session("user1", "persona1")
    session_id = session["_id"]

    from backend.modules.chat._handlers_ws import handle_chat_send
    await handle_chat_send("user1", {
        "session_id": session_id,
        "content": [{"type": "text", "text": "hello again"}],
        # no correlation_id key
    })

    assert captured.get("correlation_ids"), "No events were published"
    generated = captured["correlation_ids"][0]
    assert isinstance(generated, str) and len(generated) > 0, "Server must generate a non-empty correlation_id"
    assert generated != "client-supplied-id", "Should be server-generated, not the client value"

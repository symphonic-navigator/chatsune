"""Tests for handle_chat_retract — barge-before-delta path."""

import asyncio

import pytest

from backend.database import connect_db, disconnect_db, get_db
from backend.modules.chat._repository import ChatRepository
from backend.modules.chat._orchestrator import _cancel_events


@pytest.fixture
async def repo(clean_db):
    await connect_db()
    r = ChatRepository(get_db())
    await r.create_indexes()
    yield r
    await disconnect_db()


@pytest.mark.asyncio
async def test_retract_sets_cancel_event_and_deletes_user_message(repo, monkeypatch):
    corr = "corr-xyz"
    _cancel_events[corr] = asyncio.Event()

    session = await repo.create_session("user1", "persona1")
    session_id = session["_id"]
    await repo.save_message(
        session_id, role="user", content="hello",
        token_count=1, correlation_id=corr, user_id="user1",
    )

    published = []

    class FakeBus:
        async def publish(self, event_type, event, **kwargs):
            published.append((event_type, kwargs.get("correlation_id")))

    monkeypatch.setattr("backend.modules.chat._handlers_ws.get_event_bus", lambda: FakeBus())
    monkeypatch.setattr("backend.modules.chat._handlers_ws.get_db", lambda: get_db())

    from backend.modules.chat._handlers_ws import handle_chat_retract
    await handle_chat_retract("user1", {
        "correlation_id": corr,
        "session_id": session_id,
    })

    # Cancel event was set
    assert _cancel_events[corr].is_set()

    # Message was deleted
    remaining = await get_db()["chat_messages"].find({"correlation_id": corr}).to_list(length=5)
    assert len(remaining) == 0

    # CHAT_MESSAGE_DELETED was published with matching correlation_id
    assert any(corr == cid for (_, cid) in published)

    _cancel_events.pop(corr, None)


@pytest.mark.asyncio
async def test_retract_noop_when_no_correlation_id(repo, monkeypatch):
    published = []

    class FakeBus:
        async def publish(self, event_type, event, **kwargs):
            published.append(event_type)

    monkeypatch.setattr("backend.modules.chat._handlers_ws.get_event_bus", lambda: FakeBus())
    monkeypatch.setattr("backend.modules.chat._handlers_ws.get_db", lambda: get_db())

    from backend.modules.chat._handlers_ws import handle_chat_retract
    await handle_chat_retract("user1", {})
    assert published == []


@pytest.mark.asyncio
async def test_retract_noop_when_no_matching_user_message(repo, monkeypatch):
    """If the user message does not exist (already deleted or never persisted), retract logs and returns."""
    corr = "corr-does-not-exist"
    published = []

    class FakeBus:
        async def publish(self, event_type, event, **kwargs):
            published.append(event_type)

    monkeypatch.setattr("backend.modules.chat._handlers_ws.get_event_bus", lambda: FakeBus())
    monkeypatch.setattr("backend.modules.chat._handlers_ws.get_db", lambda: get_db())

    from backend.modules.chat._handlers_ws import handle_chat_retract
    await handle_chat_retract("user1", {"correlation_id": corr, "session_id": "whatever"})
    # No CHAT_MESSAGE_DELETED published
    assert published == []

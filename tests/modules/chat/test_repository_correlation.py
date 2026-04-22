"""Tests for correlation_id persistence on user messages."""

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


async def test_save_message_persists_correlation_id(repo):
    session = await repo.create_session("user1", "persona1")

    msg = await repo.save_message(
        session["_id"],
        role="user",
        content="hello",
        token_count=1,
        correlation_id="corr-abc",
        user_id="user1",
    )

    assert msg["correlation_id"] == "corr-abc"
    assert msg["user_id"] == "user1"


async def test_user_message_by_correlation_returns_id(repo):
    session = await repo.create_session("user1", "persona1")

    msg = await repo.save_message(
        session["_id"],
        role="user",
        content="hi",
        token_count=1,
        correlation_id="corr-xyz",
        user_id="user1",
    )

    found = await repo.user_message_by_correlation("user1", "corr-xyz")
    assert found == msg["_id"]


async def test_user_message_by_correlation_missing_returns_none(repo):
    found = await repo.user_message_by_correlation("user1", "does-not-exist")
    assert found is None


async def test_save_message_without_correlation_id_is_none(repo):
    """Backwards compatibility — old code paths that don't pass correlation_id or user_id should not break."""
    session = await repo.create_session("user1", "persona1")

    msg = await repo.save_message(
        session["_id"], role="user", content="x", token_count=1,
    )
    assert msg.get("correlation_id") is None
    assert msg.get("user_id") is None

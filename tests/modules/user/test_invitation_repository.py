import pytest
from datetime import datetime, timedelta, timezone
from backend.modules.user import InvitationRepository


@pytest.mark.asyncio
async def test_create_returns_token_doc(db):
    repo = InvitationRepository(db)
    await repo.create_indexes()
    doc = await repo.create(created_by="admin-id-1", ttl_hours=24)
    assert doc["token"]
    assert len(doc["token"]) >= 32
    assert doc["used"] is False
    assert doc["created_by"] == "admin-id-1"
    assert doc["expires_at"] > doc["created_at"]


@pytest.mark.asyncio
async def test_find_by_token_returns_doc(db):
    repo = InvitationRepository(db)
    await repo.create_indexes()
    created = await repo.create(created_by="admin", ttl_hours=24)
    found = await repo.find_by_token(created["token"])
    assert found is not None
    assert found["_id"] == created["_id"]


@pytest.mark.asyncio
async def test_find_by_token_returns_none_for_unknown(db):
    repo = InvitationRepository(db)
    await repo.create_indexes()
    assert await repo.find_by_token("nonexistent-token") is None


@pytest.mark.asyncio
async def test_mark_used_atomic_only_once(db):
    """find_one_and_update with the used:false filter must only succeed once."""
    repo = InvitationRepository(db)
    await repo.create_indexes()
    created = await repo.create(created_by="admin", ttl_hours=24)
    first = await repo.mark_used_atomic(created["token"], used_by_user_id="user-1")
    second = await repo.mark_used_atomic(created["token"], used_by_user_id="user-2")
    assert first is not None
    assert first["used"] is True
    assert first["used_by_user_id"] == "user-1"
    assert second is None  # second attempt finds no eligible doc


@pytest.mark.asyncio
async def test_mark_used_atomic_skips_expired(db):
    """An expired token must not be markable, even if unused."""
    repo = InvitationRepository(db)
    await repo.create_indexes()
    # Create with negative TTL so it's already expired
    created = await repo.create(created_by="admin", ttl_hours=-1)
    result = await repo.mark_used_atomic(created["token"], used_by_user_id="user-1")
    assert result is None


@pytest.mark.asyncio
async def test_indexes_created(db):
    repo = InvitationRepository(db)
    await repo.create_indexes()
    indexes = await db["invitation_tokens"].index_information()
    # Unique index on token
    assert any(idx.get("unique") and idx["key"] == [("token", 1)] for idx in indexes.values())
    # TTL index on expires_at
    assert any(
        idx.get("expireAfterSeconds") == 0 and idx["key"] == [("expires_at", 1)]
        for idx in indexes.values()
    )

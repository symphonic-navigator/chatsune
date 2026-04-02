import pytest
from redis.asyncio import Redis

from backend.config import settings
from backend.modules.user._refresh import RefreshTokenStore


@pytest.fixture
async def redis_client():
    client = Redis.from_url(settings.redis_uri, decode_responses=True)
    await client.flushdb()
    yield client
    await client.aclose()


@pytest.fixture
def store(redis_client):
    return RefreshTokenStore(redis_client)


async def test_store_and_retrieve_refresh_token(store):
    token = "test-token-abc"
    await store.store(token, user_id="user-1", session_id="sess-1")
    data = await store.get(token)
    assert data is not None
    assert data["user_id"] == "user-1"
    assert data["session_id"] == "sess-1"


async def test_consume_deletes_token(store):
    token = "test-token-def"
    await store.store(token, user_id="user-1", session_id="sess-1")
    data = await store.consume(token)
    assert data is not None
    assert data["user_id"] == "user-1"

    # Token is gone after consume
    again = await store.get(token)
    assert again is None


async def test_get_nonexistent_token_returns_none(store):
    data = await store.get("does-not-exist")
    assert data is None


async def test_revoke_all_for_user(store):
    await store.store("tok-1", user_id="user-1", session_id="s1")
    await store.store("tok-2", user_id="user-1", session_id="s2")
    await store.store("tok-3", user_id="user-2", session_id="s3")

    await store.revoke_all_for_user("user-1")

    assert await store.get("tok-1") is None
    assert await store.get("tok-2") is None
    # user-2's token is unaffected
    assert await store.get("tok-3") is not None

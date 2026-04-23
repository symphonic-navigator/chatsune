import base64
import secrets
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime, UTC
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from backend.config import settings
from backend.database import connect_db, disconnect_db, get_redis
from backend.main import app
from backend.ws.event_bus import EventBus, set_event_bus
from backend.ws.manager import ConnectionManager, set_manager


@dataclass
class SeededUser:
    id: str
    username: str
    h_auth_raw: bytes
    h_kek_raw: bytes
    recovery_key: str


def _make_test_uri(base: str) -> str:
    """Append '_test' to the database name (e.g. chatsune -> chatsune_test)."""
    if "?" in base:
        path, params = base.rsplit("?", 1)
        parts = path.rsplit("/", 1)
        return f"{parts[0]}/{parts[1]}_test?{params}"
    parts = base.rsplit("/", 1)
    return f"{parts[0]}/{parts[1]}_test"


# Override the URI and DB name once at import time so every test talks to the
# dedicated test database (chatsune_test) instead of the live one.
settings.mongodb_uri = _make_test_uri(settings.mongodb_uri)
settings.mongo_db_name = settings.mongo_db_name + "_test"


@pytest_asyncio.fixture
async def client(clean_db) -> AsyncGenerator[httpx.AsyncClient, None]:
    await connect_db()
    manager = ConnectionManager()
    set_manager(manager)
    set_event_bus(EventBus(redis=get_redis(), manager=manager))
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            yield ac
    finally:
        await disconnect_db()


@pytest_asyncio.fixture
async def clean_db():
    """Drop test database and flush Redis before each test.

    Not autouse -- only runs for tests that request it (directly or via the
    ``client`` fixture).  Pure unit tests that validate Pydantic models or
    other non-DB code run without needing a live MongoDB/Redis instance.
    """
    from redis.asyncio import Redis

    mongo_client = AsyncIOMotorClient(settings.mongodb_uri)
    db = mongo_client.get_database()
    collections = await db.list_collection_names()
    for col in collections:
        await db[col].drop()
    mongo_client.close()

    redis_client = Redis.from_url(settings.redis_uri, decode_responses=True)
    await redis_client.flushdb()
    await redis_client.aclose()
    yield


@pytest_asyncio.fixture
async def db(clean_db) -> AsyncGenerator:
    """Motor database handle against the test DB, already cleaned."""
    client = AsyncIOMotorClient(settings.mongodb_uri)
    database = client.get_database()
    try:
        yield database
    finally:
        client.close()


@pytest_asyncio.fixture
async def redis_client():
    from redis.asyncio import Redis

    client = Redis.from_url(settings.redis_uri, decode_responses=False)
    try:
        yield client
    finally:
        # Flush only the key spaces we use in tests so we don't nuke other tests' seeds.
        async for key in client.scan_iter("session_dek:*"):
            await client.delete(key)
        async for key in client.scan_iter("ratelimit:recovery:*"):
            await client.delete(key)
        await client.aclose()


@pytest_asyncio.fixture
async def user_key_service(db, redis_client):
    from backend.modules.user import UserKeyService
    svc = UserKeyService(db=db, redis=redis_client)
    await svc.ensure_indexes()
    return svc


@pytest_asyncio.fixture
async def seeded_user(db, user_key_service) -> SeededUser:
    from backend.modules.user._auth import hash_h_auth
    from backend.modules.user._recovery_key import generate_recovery_key

    h_auth = secrets.token_bytes(32)
    h_kek = secrets.token_bytes(32)
    recovery_key = generate_recovery_key()
    user_id = str(uuid4())
    username = f"test-{user_id[:6]}"
    now = datetime.now(UTC)
    await db["users"].insert_one({
        "_id": user_id,
        "username": username,
        "email": f"{user_id[:6]}@example.com",
        "display_name": "Test User",
        "password_hash": hash_h_auth(base64.urlsafe_b64encode(h_auth).decode()),
        "password_hash_version": 1,
        "role": "user",
        "is_active": True,
        "must_change_password": False,
        "created_at": now,
        "updated_at": now,
    })
    await user_key_service.provision_for_new_user(
        user_id=user_id, h_kek=h_kek, recovery_key=recovery_key, kdf_salt=b"s" * 32
    )
    return SeededUser(
        id=user_id,
        username=username,
        h_auth_raw=h_auth,
        h_kek_raw=h_kek,
        recovery_key=recovery_key,
    )

from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from backend.config import settings
from backend.database import connect_db, disconnect_db, get_redis
from backend.main import app
from backend.ws.event_bus import EventBus, set_event_bus
from backend.ws.manager import ConnectionManager, set_manager


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
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


@pytest_asyncio.fixture(autouse=True)
async def clean_db():
    """Drop test database and flush Redis before each test."""
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

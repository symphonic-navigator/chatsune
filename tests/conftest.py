from collections.abc import AsyncGenerator

import httpx
import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from backend.config import settings
from backend.main import app


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.fixture(autouse=True)
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

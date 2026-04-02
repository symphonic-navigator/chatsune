import asyncio
from collections.abc import AsyncGenerator

import httpx
import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from backend.config import settings
from backend.main import app


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.fixture
async def clean_db():
    """Drop test database before each test."""
    mongo_client = AsyncIOMotorClient(settings.mongodb_uri)
    db = mongo_client.get_database()
    collections = await db.list_collection_names()
    for col in collections:
        await db[col].drop()
    mongo_client.close()
    yield

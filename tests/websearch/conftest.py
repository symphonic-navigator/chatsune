"""Fixtures for websearch module tests that require a real MongoDB instance."""

import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from backend.config import settings


@pytest_asyncio.fixture
async def mock_db():
    """Provide a real MongoDB database for websearch tests.

    Uses the configured test URI (chatsune_test). Drops the collections
    touched by websearch / premium provider tests before and after each
    test to ensure isolation.
    """
    client = AsyncIOMotorClient(settings.mongodb_uri)
    db = client[settings.mongo_db_name]
    collections_to_clean = [
        "premium_provider_accounts",
        "websearch_user_credentials",
    ]
    for col_name in collections_to_clean:
        await db[col_name].drop()
    try:
        yield db
    finally:
        for col_name in collections_to_clean:
            await db[col_name].drop()
        client.close()

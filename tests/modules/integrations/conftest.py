"""Fixtures for integration module tests that require a real MongoDB instance."""

import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from backend.config import settings


_COLLECTIONS_TO_CLEAN = [
    "user_integration_configs",
    "premium_provider_accounts",
]


@pytest_asyncio.fixture
async def mongo_db():
    """Provide a real MongoDB database for integration repository tests.

    Uses the configured test URI (chatsune_test). Drops the relevant
    collection before and after each test to ensure isolation.
    """
    client = AsyncIOMotorClient(settings.mongodb_uri)
    db = client[settings.mongo_db_name]
    for col_name in _COLLECTIONS_TO_CLEAN:
        await db[col_name].drop()
    try:
        yield db
    finally:
        for col_name in _COLLECTIONS_TO_CLEAN:
            await db[col_name].drop()
        client.close()


@pytest_asyncio.fixture
async def mock_db():
    """Alias of ``mongo_db`` for tests that follow the ``mock_db`` naming."""
    client = AsyncIOMotorClient(settings.mongodb_uri)
    db = client[settings.mongo_db_name]
    for col_name in _COLLECTIONS_TO_CLEAN:
        await db[col_name].drop()
    try:
        yield db
    finally:
        for col_name in _COLLECTIONS_TO_CLEAN:
            await db[col_name].drop()
        client.close()

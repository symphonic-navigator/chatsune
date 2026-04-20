"""Fixtures for premium provider module tests that require a real MongoDB instance."""

import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from backend.config import settings


@pytest_asyncio.fixture
async def mongo_db():
    """Provide a real MongoDB database for provider repository tests.

    Uses the configured test URI (chatsune_test). Drops the relevant
    collections before and after each test to ensure isolation. The list
    covers every collection that the migration module reads or writes, so
    that migration tests do not leak state between runs.
    """
    client = AsyncIOMotorClient(settings.mongodb_uri)
    db = client[settings.mongo_db_name]
    collections_to_clean = [
        "premium_provider_accounts",
        "llm_connections",
        "user_integration_configs",
        "websearch_user_credentials",
        "personas",
        "llm_user_model_configs",
        "_migrations",
    ]
    for col_name in collections_to_clean:
        await db[col_name].drop()
    try:
        yield db
    finally:
        for col_name in collections_to_clean:
            await db[col_name].drop()
        client.close()

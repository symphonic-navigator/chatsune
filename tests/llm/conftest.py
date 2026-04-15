"""Fixtures for LLM module tests that require a real MongoDB instance."""

import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from backend.config import settings


@pytest_asyncio.fixture
async def mock_db():
    """Provide a real MongoDB database for tests requiring Atlas features (transactions, etc.).

    Uses the configured test URI (chatsune_test). Drops all collections in the LLM and
    persona namespaces before each test to ensure isolation.
    """
    client = AsyncIOMotorClient(settings.mongodb_uri)
    db = client[settings.mongo_db_name]
    collections_to_clean = [
        "llm_connections",
        "personas",
        "llm_user_model_configs",
    ]
    for col_name in collections_to_clean:
        await db[col_name].drop()
    try:
        yield db
    finally:
        for col_name in collections_to_clean:
            await db[col_name].drop()
        client.close()

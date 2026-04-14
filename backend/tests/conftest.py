import os
import uuid

import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")


@pytest_asyncio.fixture
async def test_db():
    client = AsyncIOMotorClient(MONGO_URL)
    db_name = f"chatsune_test_{uuid.uuid4().hex[:8]}"
    db = client[db_name]
    try:
        yield db
    finally:
        await client.drop_database(db_name)
        client.close()

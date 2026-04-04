import json

import pytest_asyncio

from backend.config import settings


@pytest_asyncio.fixture
async def redis(clean_db):
    """Provide a clean Redis client for job tests."""
    from backend.database import connect_db, disconnect_db, get_redis
    await connect_db()
    try:
        yield get_redis()
    finally:
        await disconnect_db()


async def test_submit_adds_entry_to_stream(redis):
    from backend.jobs import submit
    from backend.jobs._models import JobType

    job_id = await submit(
        job_type=JobType.TITLE_GENERATION,
        user_id="user-1",
        model_unique_id="ollama_cloud:llama3.2",
        payload={"session_id": "sess-1"},
        correlation_id="corr-1",
    )

    assert job_id  # non-empty string

    entries = await redis.xrange("jobs:pending")
    assert len(entries) == 1

    _, fields = entries[0]
    data = json.loads(fields["data"])
    assert data["id"] == job_id
    assert data["job_type"] == "title_generation"
    assert data["user_id"] == "user-1"
    assert data["model_unique_id"] == "ollama_cloud:llama3.2"
    assert data["payload"] == {"session_id": "sess-1"}
    assert data["attempt"] == 0


async def test_submit_returns_unique_ids(redis):
    from backend.jobs import submit
    from backend.jobs._models import JobType

    id_a = await submit(
        job_type=JobType.TITLE_GENERATION,
        user_id="user-1",
        model_unique_id="ollama_cloud:llama3.2",
        payload={"session_id": "sess-1"},
    )
    id_b = await submit(
        job_type=JobType.TITLE_GENERATION,
        user_id="user-1",
        model_unique_id="ollama_cloud:llama3.2",
        payload={"session_id": "sess-2"},
    )

    assert id_a != id_b

"""Safeguard integration tests for backend.jobs.submit.

Covers the kill-switch rejection path and the per-user queue cap eviction
path added in Task 8 of the background-jobs hardening plan."""
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def redis(clean_db):
    from backend.database import connect_db, disconnect_db, get_redis
    await connect_db()
    try:
        yield get_redis()
    finally:
        await disconnect_db()


async def test_submit_rejected_when_emergency_stop_active(redis, monkeypatch):
    from backend.jobs import submit
    from backend.jobs._models import JobType
    from backend.modules.safeguards import EmergencyStoppedError

    monkeypatch.setenv("OLLAMA_CLOUD_EMERGENCY_STOP", "true")

    with pytest.raises(EmergencyStoppedError):
        await submit(
            job_type=JobType.TITLE_GENERATION,
            user_id="user-1",
            model_unique_id="ollama_cloud:llama3.2",
            payload={"session_id": "sess-1"},
        )

    # xadd must not have been called.
    entries = await redis.xrange("jobs:pending")
    assert entries == []


async def test_submit_evicts_oldest_when_queue_cap_exceeded(redis, monkeypatch):
    from backend.jobs import submit
    from backend.jobs._models import JobType

    monkeypatch.setenv("JOB_QUEUE_CAP_PER_USER", "3")
    monkeypatch.delenv("OLLAMA_CLOUD_EMERGENCY_STOP", raising=False)

    submitted_ids = []
    for i in range(4):
        await submit(
            job_type=JobType.TITLE_GENERATION,
            user_id="user-cap",
            model_unique_id="ollama_cloud:llama3.2",
            payload={"session_id": f"sess-{i}"},
        )
        entries = await redis.xrange("jobs:pending")
        submitted_ids.append(entries[-1][0])

    # After the 4th submit the cap of 3 must have evicted the 1st.
    remaining = await redis.xrange("jobs:pending")
    remaining_ids = [mid for mid, _ in remaining]
    assert len(remaining_ids) == 3
    assert submitted_ids[0] not in remaining_ids
    assert submitted_ids[-1] in remaining_ids


async def test_submit_normal_path_unchanged(redis, monkeypatch):
    from backend.jobs import submit
    from backend.jobs._models import JobType

    monkeypatch.delenv("OLLAMA_CLOUD_EMERGENCY_STOP", raising=False)
    monkeypatch.setenv("JOB_QUEUE_CAP_PER_USER", "10")

    job_id = await submit(
        job_type=JobType.TITLE_GENERATION,
        user_id="user-ok",
        model_unique_id="ollama_cloud:llama3.2",
        payload={"session_id": "sess-ok"},
    )
    assert job_id
    entries = await redis.xrange("jobs:pending")
    assert len(entries) == 1

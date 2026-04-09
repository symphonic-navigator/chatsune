from datetime import datetime, timezone

import pytest_asyncio

from shared.dtos.jobs import JobLogEntryDto


@pytest_asyncio.fixture
async def redis(clean_db):
    from backend.database import connect_db, disconnect_db, get_redis
    await connect_db()
    try:
        yield get_redis()
    finally:
        await disconnect_db()


async def test_append_and_read_roundtrip(redis) -> None:
    from backend.jobs._log import append_job_log_entry, read_job_log_entries

    entry = JobLogEntryDto(
        entry_id="e1",
        job_id="j1",
        job_type="memory_extraction",
        persona_id="p1",
        status="started",
        ts=datetime(2026, 4, 9, 14, 30, tzinfo=timezone.utc),
    )
    await append_job_log_entry(redis, user_id="u1", entry=entry)

    entries = await read_job_log_entries(redis, user_id="u1", limit=50)
    assert len(entries) == 1
    assert entries[0].job_id == "j1"
    assert entries[0].status == "started"


async def test_trim_keeps_newest_n(redis) -> None:
    from backend.jobs._log import (
        JOB_LOG_MAX,
        append_job_log_entry,
        read_job_log_entries,
    )

    for i in range(JOB_LOG_MAX + 25):
        entry = JobLogEntryDto(
            entry_id=f"e{i}",
            job_id=f"j{i}",
            job_type="memory_extraction",
            status="started",
            ts=datetime(2026, 4, 9, 14, 30, tzinfo=timezone.utc),
        )
        await append_job_log_entry(redis, user_id="u1", entry=entry)

    length = await redis.llen("jobs:log:u1")
    assert length == JOB_LOG_MAX

    entries = await read_job_log_entries(redis, user_id="u1", limit=JOB_LOG_MAX)
    assert entries[0].job_id == f"j{JOB_LOG_MAX + 24}"


async def test_ttl_is_set(redis) -> None:
    from backend.jobs._log import (
        JOB_LOG_TTL_SECONDS,
        append_job_log_entry,
    )

    entry = JobLogEntryDto(
        entry_id="e1",
        job_id="j1",
        job_type="memory_extraction",
        status="started",
        ts=datetime(2026, 4, 9, 14, 30, tzinfo=timezone.utc),
    )
    await append_job_log_entry(redis, user_id="u1", entry=entry)

    ttl = await redis.ttl("jobs:log:u1")
    assert 0 < ttl <= JOB_LOG_TTL_SECONDS


async def test_read_empty(redis) -> None:
    from backend.jobs._log import read_job_log_entries

    entries = await read_job_log_entries(redis, user_id="nobody", limit=50)
    assert entries == []

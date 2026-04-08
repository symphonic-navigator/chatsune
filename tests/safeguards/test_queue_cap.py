import pytest_asyncio

from backend.modules.safeguards import SafeguardConfig
from backend.modules.safeguards._queue_cap import (
    acknowledge_job_done,
    enforce_queue_cap,
)


STREAM = "jobs:test-safeguard"


def _cfg(cap: int = 3) -> SafeguardConfig:
    return SafeguardConfig(
        emergency_stop=False,
        rate_limit_window_seconds=60,
        rate_limit_max_calls=50,
        queue_cap_per_user=cap,
        daily_token_budget=5_000_000,
        circuit_failure_threshold=5,
        circuit_window_seconds=300,
        circuit_open_seconds=900,
    )


@pytest_asyncio.fixture
async def redis(clean_db):
    from backend.database import connect_db, disconnect_db, get_redis
    await connect_db()
    try:
        yield get_redis()
    finally:
        await disconnect_db()


async def _add(redis, data: str) -> str:
    return await redis.xadd(STREAM, {"data": data})


async def test_under_cap_no_eviction(redis):
    cfg = _cfg(cap=3)
    for i in range(3):
        msg_id = await _add(redis, f"j{i}")
        evicted = await enforce_queue_cap(
            redis, cfg, "u1", STREAM, msg_id, now_ms=1000 + i,
        )
        assert evicted == []
    assert await redis.xlen(STREAM) == 3


async def test_one_over_cap_evicts_oldest(redis):
    cfg = _cfg(cap=3)
    ids = []
    for i in range(3):
        msg_id = await _add(redis, f"j{i}")
        ids.append(msg_id)
        await enforce_queue_cap(redis, cfg, "u1", STREAM, msg_id, now_ms=1000 + i)
    # 4th job
    new_id = await _add(redis, "j3")
    evicted = await enforce_queue_cap(
        redis, cfg, "u1", STREAM, new_id, now_ms=2000,
    )
    assert evicted == [ids[0]]
    assert await redis.xlen(STREAM) == 3


async def test_three_over_cap_evicts_three(redis):
    cfg = _cfg(cap=3)
    for i in range(6):
        msg_id = await _add(redis, f"j{i}")
        evicted = await enforce_queue_cap(
            redis, cfg, "u1", STREAM, msg_id, now_ms=1000 + i,
        )
        if i < 3:
            assert evicted == []
        else:
            assert len(evicted) == 1
    assert await redis.xlen(STREAM) == 3


async def test_cap_zero_disabled(redis):
    cfg = _cfg(cap=0)
    for i in range(10):
        msg_id = await _add(redis, f"j{i}")
        evicted = await enforce_queue_cap(
            redis, cfg, "u1", STREAM, msg_id, now_ms=1000 + i,
        )
        assert evicted == []
    assert await redis.xlen(STREAM) == 10


async def test_two_users_independent(redis):
    cfg = _cfg(cap=2)
    # Fill u1 to cap.
    for i in range(2):
        msg_id = await _add(redis, f"u1-{i}")
        await enforce_queue_cap(redis, cfg, "u1", STREAM, msg_id, now_ms=1000 + i)
    # u2 should be able to also fill its own cap without eviction.
    for i in range(2):
        msg_id = await _add(redis, f"u2-{i}")
        evicted = await enforce_queue_cap(
            redis, cfg, "u2", STREAM, msg_id, now_ms=2000 + i,
        )
        assert evicted == []
    assert await redis.xlen(STREAM) == 4


async def test_acknowledge_removes_from_set(redis):
    cfg = _cfg(cap=2)
    msg_id = await _add(redis, "j0")
    await enforce_queue_cap(redis, cfg, "u1", STREAM, msg_id, now_ms=1000)
    await acknowledge_job_done(redis, "u1", msg_id)
    # After ack, the slot is free: two more should fit without eviction.
    for i in range(2):
        nid = await _add(redis, f"j{i + 1}")
        evicted = await enforce_queue_cap(
            redis, cfg, "u1", STREAM, nid, now_ms=1100 + i,
        )
        assert evicted == []

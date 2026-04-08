import pytest
import pytest_asyncio

from backend.modules.safeguards import (
    CircuitOpenError,
    SafeguardConfig,
    check_circuit,
    record_failure,
    record_success,
)
from backend.modules.safeguards._circuit_breaker import _open_key


def _cfg(threshold: int = 3) -> SafeguardConfig:
    return SafeguardConfig(
        emergency_stop=False,
        rate_limit_window_seconds=60,
        rate_limit_max_calls=50,
        queue_cap_per_user=10,
        daily_token_budget=5_000_000,
        circuit_failure_threshold=threshold,
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


async def test_closed_by_default(redis):
    await check_circuit(redis, _cfg(), "u1", "p1", "m1")


async def test_failures_below_threshold_still_closed(redis):
    cfg = _cfg(threshold=3)
    for _ in range(2):
        await record_failure(redis, cfg, "u1", "p1", "m1")
    await check_circuit(redis, cfg, "u1", "p1", "m1")


async def test_nth_failure_opens(redis):
    cfg = _cfg(threshold=3)
    for _ in range(3):
        await record_failure(redis, cfg, "u1", "p1", "m1")
    # The first check after opening claims the probe slot and passes.
    await check_circuit(redis, cfg, "u1", "p1", "m1")
    # The second concurrent check is blocked.
    with pytest.raises(CircuitOpenError):
        await check_circuit(redis, cfg, "u1", "p1", "m1")


async def test_half_open_allows_one_probe(redis):
    cfg = _cfg(threshold=3)
    for _ in range(3):
        await record_failure(redis, cfg, "u1", "p1", "m1")
    # Simulate "open_seconds elapsed" by deleting the open marker directly,
    # which is exactly what the TTL would do. Avoids sleeping 900s.
    await redis.delete(_open_key("u1", "p1", "m1"))
    # But to truly test half-open behaviour we need the open marker present
    # AND then a probe to be claimable. Re-open it: the probe key was cleared
    # by record_failure on the N-th failure, so now check() should claim it.
    await redis.set(_open_key("u1", "p1", "m1"), "1", ex=900)
    # First check() claims probe and returns.
    await check_circuit(redis, cfg, "u1", "p1", "m1")
    # Second concurrent check() is blocked.
    with pytest.raises(CircuitOpenError):
        await check_circuit(redis, cfg, "u1", "p1", "m1")


async def test_probe_success_resets(redis):
    cfg = _cfg(threshold=3)
    for _ in range(3):
        await record_failure(redis, cfg, "u1", "p1", "m1")
    await record_success(redis, cfg, "u1", "p1", "m1")
    await check_circuit(redis, cfg, "u1", "p1", "m1")


async def test_probe_failure_reopens(redis):
    cfg = _cfg(threshold=3)
    for _ in range(3):
        await record_failure(redis, cfg, "u1", "p1", "m1")
    # Probe fails -> another record_failure. Counter already at threshold,
    # so open marker is re-set and the probe marker is cleared. The very
    # next check() will claim a fresh probe; a subsequent one is blocked.
    await record_failure(redis, cfg, "u1", "p1", "m1")
    await check_circuit(redis, cfg, "u1", "p1", "m1")
    with pytest.raises(CircuitOpenError):
        await check_circuit(redis, cfg, "u1", "p1", "m1")


async def test_tuples_are_independent(redis):
    cfg = _cfg(threshold=3)
    for _ in range(3):
        await record_failure(redis, cfg, "u1", "p1", "m1")
    # Different model
    await check_circuit(redis, cfg, "u1", "p1", "m2")
    # Different provider
    await check_circuit(redis, cfg, "u1", "p2", "m1")
    # Different user
    await check_circuit(redis, cfg, "u2", "p1", "m1")


async def test_success_in_closed_clears_counter(redis):
    cfg = _cfg(threshold=3)
    await record_failure(redis, cfg, "u1", "p1", "m1")
    await record_failure(redis, cfg, "u1", "p1", "m1")
    await record_success(redis, cfg, "u1", "p1", "m1")
    # One more failure alone should not open.
    await record_failure(redis, cfg, "u1", "p1", "m1")
    await check_circuit(redis, cfg, "u1", "p1", "m1")

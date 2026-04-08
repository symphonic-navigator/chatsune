from datetime import datetime, timezone

import pytest
import pytest_asyncio

from backend.modules.safeguards import (
    BudgetExceededError,
    SafeguardConfig,
    check_budget,
    record_tokens,
)


def _cfg(budget: int = 5_000_000) -> SafeguardConfig:
    return SafeguardConfig(
        emergency_stop=False,
        rate_limit_window_seconds=60,
        rate_limit_max_calls=50,
        queue_cap_per_user=10,
        daily_token_budget=budget,
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


async def test_disabled_budget_no_op(redis):
    cfg = _cfg(budget=0)
    await check_budget(redis, cfg, "u1", tokens_to_reserve=10_000_000)
    await record_tokens(redis, cfg, "u1", 999_999_999)
    # Nothing was stored.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert await redis.get(f"safeguard:budget:u1:{today}") is None


async def test_check_passes_when_under(redis):
    cfg = _cfg(budget=5_000_000)
    await check_budget(redis, cfg, "u1", tokens_to_reserve=1000)


async def test_record_then_check(redis):
    cfg = _cfg(budget=5_000_000)
    await record_tokens(redis, cfg, "u1", 1000)
    await check_budget(redis, cfg, "u1", tokens_to_reserve=1)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert int(await redis.get(f"safeguard:budget:u1:{today}")) == 1000


async def test_record_then_exceeds(redis):
    cfg = _cfg(budget=5_000_000)
    await record_tokens(redis, cfg, "u1", 5_000_001)
    with pytest.raises(BudgetExceededError):
        await check_budget(redis, cfg, "u1", tokens_to_reserve=1)


async def test_reserve_exceeds_budget_raises(redis):
    cfg = _cfg(budget=100)
    await record_tokens(redis, cfg, "u1", 50)
    with pytest.raises(BudgetExceededError):
        await check_budget(redis, cfg, "u1", tokens_to_reserve=51)


async def test_users_are_independent(redis):
    cfg = _cfg(budget=100)
    await record_tokens(redis, cfg, "u1", 100)
    with pytest.raises(BudgetExceededError):
        await check_budget(redis, cfg, "u1", tokens_to_reserve=1)
    # u2 untouched
    await check_budget(redis, cfg, "u2", tokens_to_reserve=100)


async def test_key_has_ttl(redis):
    cfg = _cfg(budget=1000)
    await record_tokens(redis, cfg, "u1", 10)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ttl = await redis.ttl(f"safeguard:budget:u1:{today}")
    # ~36h with some slack
    assert 30 * 3600 < ttl <= 36 * 3600

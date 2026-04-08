import asyncio

import pytest
import pytest_asyncio

from backend.modules.safeguards import (
    RateLimitExceededError,
    SafeguardConfig,
    check_rate_limit,
)


def _cfg(window: int = 60, max_calls: int = 3) -> SafeguardConfig:
    return SafeguardConfig(
        emergency_stop=False,
        rate_limit_window_seconds=window,
        rate_limit_max_calls=max_calls,
        queue_cap_per_user=10,
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


async def test_first_call_allowed(redis):
    await check_rate_limit(redis, _cfg(), "u1", "ollama_cloud")


async def test_up_to_max_allowed(redis):
    cfg = _cfg(max_calls=3)
    for _ in range(3):
        await check_rate_limit(redis, cfg, "u1", "ollama_cloud")


async def test_one_over_raises(redis):
    cfg = _cfg(max_calls=3)
    for _ in range(3):
        await check_rate_limit(redis, cfg, "u1", "ollama_cloud")
    with pytest.raises(RateLimitExceededError):
        await check_rate_limit(redis, cfg, "u1", "ollama_cloud")


async def test_users_are_independent(redis):
    cfg = _cfg(max_calls=2)
    await check_rate_limit(redis, cfg, "u1", "ollama_cloud")
    await check_rate_limit(redis, cfg, "u1", "ollama_cloud")
    # u2 must not be affected
    await check_rate_limit(redis, cfg, "u2", "ollama_cloud")
    await check_rate_limit(redis, cfg, "u2", "ollama_cloud")


async def test_providers_are_independent(redis):
    cfg = _cfg(max_calls=2)
    await check_rate_limit(redis, cfg, "u1", "provider_a")
    await check_rate_limit(redis, cfg, "u1", "provider_a")
    await check_rate_limit(redis, cfg, "u1", "provider_b")
    await check_rate_limit(redis, cfg, "u1", "provider_b")


async def test_window_resets_after_ttl(redis):
    cfg = _cfg(window=1, max_calls=2)
    await check_rate_limit(redis, cfg, "u1", "ollama_cloud")
    await check_rate_limit(redis, cfg, "u1", "ollama_cloud")
    with pytest.raises(RateLimitExceededError):
        await check_rate_limit(redis, cfg, "u1", "ollama_cloud")
    await asyncio.sleep(1.2)
    # Window has expired, counter should reset.
    await check_rate_limit(redis, cfg, "u1", "ollama_cloud")

"""Integration tests for the high-level safeguards entry points."""
from dataclasses import replace

import pytest
import pytest_asyncio

from backend.modules.safeguards import (
    BudgetExceededError,
    CircuitOpenError,
    EmergencyStoppedError,
    RateLimitExceededError,
    SafeguardConfig,
    check_circuit,
    check_job_preconditions,
    record_failure,
    record_job_failure,
    record_job_success,
)


def _cfg(**overrides) -> SafeguardConfig:
    base = SafeguardConfig(
        emergency_stop=False,
        rate_limit_window_seconds=60,
        rate_limit_max_calls=3,
        queue_cap_per_user=10,
        daily_token_budget=5_000_000,
        circuit_failure_threshold=3,
        circuit_window_seconds=300,
        circuit_open_seconds=900,
    )
    return replace(base, **overrides)


@pytest_asyncio.fixture
async def redis(clean_db):
    from backend.database import connect_db, disconnect_db, get_redis
    await connect_db()
    try:
        yield get_redis()
    finally:
        await disconnect_db()


USER = "u1"
PROVIDER = "ollama_cloud"
MODEL = "llama3.2"


async def test_happy_path(redis):
    await check_job_preconditions(
        redis,
        _cfg(),
        user_id=USER,
        provider_id=PROVIDER,
        model_slug=MODEL,
        estimated_input_tokens=100,
    )


async def test_kill_switch_raises(redis):
    with pytest.raises(EmergencyStoppedError):
        await check_job_preconditions(
            redis,
            _cfg(emergency_stop=True),
            user_id=USER,
            provider_id=PROVIDER,
            model_slug=MODEL,
            estimated_input_tokens=100,
        )


async def test_rate_limit_raises(redis):
    cfg = _cfg(rate_limit_max_calls=2)
    await check_job_preconditions(
        redis, cfg, user_id=USER, provider_id=PROVIDER,
        model_slug=MODEL, estimated_input_tokens=10,
    )
    await check_job_preconditions(
        redis, cfg, user_id=USER, provider_id=PROVIDER,
        model_slug=MODEL, estimated_input_tokens=10,
    )
    with pytest.raises(RateLimitExceededError):
        await check_job_preconditions(
            redis, cfg, user_id=USER, provider_id=PROVIDER,
            model_slug=MODEL, estimated_input_tokens=10,
        )


async def test_budget_raises(redis):
    cfg = _cfg(daily_token_budget=100)
    with pytest.raises(BudgetExceededError):
        await check_job_preconditions(
            redis, cfg, user_id=USER, provider_id=PROVIDER,
            model_slug=MODEL, estimated_input_tokens=1_000,
        )


async def test_circuit_open_raises(redis):
    cfg = _cfg(circuit_failure_threshold=2)
    for _ in range(2):
        await record_failure(redis, cfg, USER, PROVIDER, MODEL)
    # Burn probe slot (see INSIGHTS: first check after open claims probe).
    await check_circuit(redis, cfg, USER, PROVIDER, MODEL)
    with pytest.raises(CircuitOpenError):
        await check_job_preconditions(
            redis, cfg, user_id=USER, provider_id=PROVIDER,
            model_slug=MODEL, estimated_input_tokens=10,
        )


async def test_record_job_success_clears_breaker_and_records_tokens(redis):
    cfg = _cfg(circuit_failure_threshold=3, daily_token_budget=1_000)
    await record_failure(redis, cfg, USER, PROVIDER, MODEL)
    await record_failure(redis, cfg, USER, PROVIDER, MODEL)

    await record_job_success(
        redis, cfg, user_id=USER, provider_id=PROVIDER,
        model_slug=MODEL, tokens_spent=250,
    )

    # Breaker failures cleared: another two failures should not open it.
    await record_failure(redis, cfg, USER, PROVIDER, MODEL)
    await record_failure(redis, cfg, USER, PROVIDER, MODEL)
    await check_circuit(redis, cfg, USER, PROVIDER, MODEL)

    # Tokens were recorded — reserving 800 more exceeds the 1_000 budget.
    with pytest.raises(BudgetExceededError):
        await check_job_preconditions(
            redis, cfg, user_id=USER, provider_id=PROVIDER,
            model_slug=MODEL, estimated_input_tokens=800,
        )


async def test_record_job_failure_increments_breaker(redis):
    cfg = _cfg(circuit_failure_threshold=2)
    await record_job_failure(
        redis, cfg, user_id=USER, provider_id=PROVIDER, model_slug=MODEL,
    )
    await record_job_failure(
        redis, cfg, user_id=USER, provider_id=PROVIDER, model_slug=MODEL,
    )
    # Breaker now open — burn the probe, next check raises.
    await check_circuit(redis, cfg, USER, PROVIDER, MODEL)
    with pytest.raises(CircuitOpenError):
        await check_circuit(redis, cfg, USER, PROVIDER, MODEL)

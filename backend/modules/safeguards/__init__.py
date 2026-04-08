"""Public API of the safeguards module.

Provides a thin safety-net layer that sits in front of every background-job
LLM call. See ``docs/`` and INSIGHTS.md for rationale."""
from redis.asyncio import Redis

from ._budget import BudgetExceededError, check_budget, record_tokens
from ._circuit_breaker import (
    CircuitOpenError,
    check_circuit,
    record_failure,
    record_success,
)
from ._config import SafeguardConfig
from ._queue_cap import acknowledge_job_done, enforce_queue_cap
from ._rate_limiter import RateLimitExceededError, check_rate_limit


class EmergencyStoppedError(Exception):
    """Raised when the global background-job kill-switch is engaged."""

    def __init__(self) -> None:
        super().__init__("Background jobs are currently halted by the kill-switch.")


def is_emergency_stopped(config: SafeguardConfig) -> bool:
    """Return True when the global background-job kill-switch is engaged."""
    return config.emergency_stop


async def check_job_preconditions(
    redis: Redis,
    config: SafeguardConfig,
    *,
    user_id: str,
    provider_id: str,
    model_slug: str,
    estimated_input_tokens: int,
) -> None:
    """Run all safeguard checks before dispatching a background-job LLM call.

    Order is deliberate: cheapest/most-decisive checks first, so we don't burn
    Redis calls once we already know the job is going to be rejected.

    Raises:
        EmergencyStoppedError: global kill-switch is engaged.
        CircuitOpenError: per user/provider/model breaker is open.
        RateLimitExceededError: per user/provider rate-limit hit.
        BudgetExceededError: reserving ``estimated_input_tokens`` would exceed
            the daily token budget.
    """
    if is_emergency_stopped(config):
        raise EmergencyStoppedError()
    await check_circuit(redis, config, user_id, provider_id, model_slug)
    await check_rate_limit(redis, config, user_id, provider_id)
    await check_budget(
        redis, config, user_id, tokens_to_reserve=estimated_input_tokens,
    )


async def record_job_success(
    redis: Redis,
    config: SafeguardConfig,
    *,
    user_id: str,
    provider_id: str,
    model_slug: str,
    tokens_spent: int,
) -> None:
    """Mark a background-job LLM call as successful.

    Clears the circuit-breaker failure count for this user/provider/model and
    records the actual token spend against the daily budget."""
    await record_success(redis, config, user_id, provider_id, model_slug)
    if tokens_spent > 0:
        await record_tokens(redis, config, user_id, tokens_spent)


async def record_job_failure(
    redis: Redis,
    config: SafeguardConfig,
    *,
    user_id: str,
    provider_id: str,
    model_slug: str,
) -> None:
    """Mark a background-job LLM call as failed.

    Increments the circuit-breaker failure counter, which may open the breaker."""
    await record_failure(redis, config, user_id, provider_id, model_slug)


__all__ = [
    "SafeguardConfig",
    "is_emergency_stopped",
    "EmergencyStoppedError",
    "check_rate_limit",
    "RateLimitExceededError",
    "check_budget",
    "record_tokens",
    "BudgetExceededError",
    "check_circuit",
    "record_failure",
    "record_success",
    "CircuitOpenError",
    "enforce_queue_cap",
    "acknowledge_job_done",
    "check_job_preconditions",
    "record_job_success",
    "record_job_failure",
]

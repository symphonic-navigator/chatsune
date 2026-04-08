"""Public API of the safeguards module.

Provides a thin safety-net layer that sits in front of every background-job
LLM call. See ``docs/`` and INSIGHTS.md for rationale."""
from ._config import SafeguardConfig
from ._budget import BudgetExceededError, check_budget, record_tokens
from ._rate_limiter import RateLimitExceededError, check_rate_limit


def is_emergency_stopped(config: SafeguardConfig) -> bool:
    """Return True when the global background-job kill-switch is engaged."""
    return config.emergency_stop


__all__ = [
    "SafeguardConfig",
    "is_emergency_stopped",
    "check_rate_limit",
    "RateLimitExceededError",
    "check_budget",
    "record_tokens",
    "BudgetExceededError",
]

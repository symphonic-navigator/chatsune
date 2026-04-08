"""Configuration for the safeguards layer.

All values are read from environment variables with sensible defaults.
See README.md for documentation of each variable."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class SafeguardConfig:
    """Immutable snapshot of all safeguard-related environment variables."""

    emergency_stop: bool
    rate_limit_window_seconds: int
    rate_limit_max_calls: int
    queue_cap_per_user: int
    daily_token_budget: int
    circuit_failure_threshold: int
    circuit_window_seconds: int
    circuit_open_seconds: int

    @classmethod
    def from_env(cls) -> "SafeguardConfig":
        return cls(
            emergency_stop=_env_bool("OLLAMA_CLOUD_EMERGENCY_STOP", False),
            rate_limit_window_seconds=_env_int("JOB_RATE_LIMIT_WINDOW_SECONDS", 60),
            rate_limit_max_calls=_env_int("JOB_RATE_LIMIT_MAX_CALLS", 50),
            queue_cap_per_user=_env_int("JOB_QUEUE_CAP_PER_USER", 10),
            daily_token_budget=_env_int("JOB_DAILY_TOKEN_BUDGET", 5_000_000),
            circuit_failure_threshold=_env_int("JOB_CIRCUIT_FAILURE_THRESHOLD", 5),
            circuit_window_seconds=_env_int("JOB_CIRCUIT_WINDOW_SECONDS", 300),
            circuit_open_seconds=_env_int("JOB_CIRCUIT_OPEN_SECONDS", 900),
        )

    @property
    def queue_cap_enabled(self) -> bool:
        return self.queue_cap_per_user > 0

    @property
    def budget_enabled(self) -> bool:
        return self.daily_token_budget > 0

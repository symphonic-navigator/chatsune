"""Public API of the safeguards module.

Provides a thin safety-net layer that sits in front of every background-job
LLM call. See ``docs/`` and INSIGHTS.md for rationale."""
from ._config import SafeguardConfig


def is_emergency_stopped(config: SafeguardConfig) -> bool:
    """Return True when the global background-job kill-switch is engaged."""
    return config.emergency_stop


__all__ = ["SafeguardConfig", "is_emergency_stopped"]

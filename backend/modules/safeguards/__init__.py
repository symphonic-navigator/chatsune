"""Public API of the safeguards module.

Provides a thin safety-net layer that sits in front of every background-job
LLM call. See ``docs/`` and INSIGHTS.md for rationale."""
from ._config import SafeguardConfig

__all__ = ["SafeguardConfig"]

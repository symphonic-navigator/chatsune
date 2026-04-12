"""Prometheus metrics module.

Exposes metric objects for use by other modules and the /api/metrics endpoint.
"""

from backend.modules.metrics._definitions import (
    inference_total,
    inference_duration_seconds,
    inferences_aborted_total,
    tool_calls_total,
    tool_call_duration_seconds,
    models_available,
    embedding_calls_total,
)
from backend.modules.metrics._handlers import router

__all__ = [
    "router",
    "inference_total",
    "inference_duration_seconds",
    "inferences_aborted_total",
    "tool_calls_total",
    "tool_call_duration_seconds",
    "models_available",
    "embedding_calls_total",
]

"""Prometheus metric definitions for Chatsune.

All metrics are defined here. Other modules import the objects they need
and call .inc(), .observe(), or .set() directly.
"""

from prometheus_client import Counter, Histogram, Gauge

# ── Inference ──────────────────────────────────────────────────────────────────
inference_total = Counter(
    "chatsune_inferences_total",
    "Total number of LLM inferences",
    ["model", "provider", "source"],
)

inference_duration_seconds = Histogram(
    "chatsune_inference_duration_seconds",
    "Duration of LLM inferences in seconds",
    ["model", "provider"],
)

inferences_aborted_total = Counter(
    "chatsune_inferences_aborted_total",
    "Total number of aborted LLM inferences",
    ["model", "provider"],
)

# ── Tool calls ─────────────────────────────────────────────────────────────────
tool_calls_total = Counter(
    "chatsune_tool_calls_total",
    "Total number of tool calls",
    ["model", "tool_name"],
)

tool_call_duration_seconds = Histogram(
    "chatsune_tool_call_duration_seconds",
    "Duration of tool call execution in seconds",
    ["model", "tool_name"],
)

# ── Models ─────────────────────────────────────────────────────────────────────
models_available = Gauge(
    "chatsune_models_available",
    "Number of models available per upstream provider",
    ["provider"],
)

# ── Embeddings ─────────────────────────────────────────────────────────────────
embedding_calls_total = Counter(
    "chatsune_embedding_calls_total",
    "Total number of embedding calls",
    ["cache_status"],
)

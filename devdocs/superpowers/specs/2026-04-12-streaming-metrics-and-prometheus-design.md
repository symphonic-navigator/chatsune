# Streaming Metrics, Elapsed Time & Prometheus Module

**Date:** 2026-04-12
**Status:** Approved

---

## Overview

Three features that add observability to Chatsune:

1. **TTFT & tokens/s display** — inference performance stats shown per message
2. **Elapsed time during stalled streams** — timer when the model goes silent
3. **Prometheus metrics module** — `/api/metrics` endpoint for scraping

---

## Feature 1: TTFT & Tokens/s Display

### Backend — Timing in Inference Runner

In `chat/_inference.py`, `InferenceRunner._run_locked()`:

- Record `t_stream_start = time.monotonic()` at stream begin
- Record `t_first_token` on the first `ContentDelta` or `ThinkingDelta`
- At stream end, compute:
  - `ttft_ms = (t_first_token - t_stream_start) * 1000`
  - `tokens_per_second = output_tokens / total_duration`
  - `generation_duration_ms = total_duration * 1000`

### Transport — Extended ChatStreamEndedEvent

New optional fields on `ChatStreamEndedEvent` (in `shared/events/chat.py`):

```python
time_to_first_token_ms: int | None       # milliseconds
tokens_per_second: float | None          # rounded to 1 decimal
generation_duration_ms: int | None       # total stream duration in ms
provider_name: str | None                # display name, e.g. "Ollama Cloud"
model_name: str | None                   # display name, e.g. "Llama 3.2"
```

No new events. No new topics. Data piggybacks on the existing stream-ended event.

### Frontend — Collapsible Stats Line

Below each assistant message bubble, a small info icon appears after streaming ends.
On hover or click, a stats line expands:

```
ℹ stats → TTFT: 1.2s · 42.3 tok/s · 286 tokens · Ollama Cloud / Llama 3.2
```

- Values sourced from `ChatStreamEndedEvent` payload
- Persisted in the message object in the chat store (survives scroll/reload)
- No extra REST call — fully event-driven

### Fallbacks

- TTFT null (aborted before first token): field omitted from display
- Model info unavailable: show "Unknown model"
- Refused/aborted messages: show stats line with whatever data is available

---

## Feature 2: Elapsed Time During Stalled Streams

### Scope

Pure frontend change. No backend modifications.

### Trigger

The existing `ChatStreamSlowEvent` fires after 30s of silence.
The UI already shows "Model still working…". This feature appends a live timer.

### Behaviour

1. `ChatStreamSlowEvent` arrives → set `slowSince = Date.now()`
2. A `setInterval(1000)` updates the displayed elapsed time every second
3. On new `ContentDelta` or `ThinkingDelta` → reset timer, clear interval, hide text
4. On `ChatStreamEndedEvent` → clean up everything

### Display Format

```
Model still working… 34s
Model still working… 1m 12s
```

- Under 60s: seconds only (`34s`)
- 60s and above: minutes + seconds (`1m 12s`)
- Timer counts from the `ChatStreamSlowEvent` timestamp, not from stream start

### Edge Cases

- Chunks resume → timer disappears, normal streaming continues
- Another `ChatStreamSlowEvent` → timer restarts at 0
- Stream ends while timer runs → clean up, stats line appears

---

## Feature 3: Prometheus Metrics Module

### Module Structure

```
backend/modules/metrics/
  __init__.py          # public API: router, metric objects
  _definitions.py      # all Prometheus metric definitions
  _handlers.py         # /api/metrics endpoint
```

### Dependency

Add `prometheus-client` to `pyproject.toml`.

### Endpoint

`GET /api/metrics` returns `prometheus_client.generate_latest()` as `text/plain`.
No authentication required (internal network, Prometheus scrapes directly).

### Metric Definitions

| Metric Name | Type | Labels | Instrumented In |
|---|---|---|---|
| `chatsune_inferences_total` | Counter | `model`, `provider`, `source` (chat/job) | `llm/__init__.py::stream_completion()` |
| `chatsune_inference_duration_seconds` | Histogram | `model`, `provider` | `llm/__init__.py::stream_completion()` |
| `chatsune_inferences_aborted_total` | Counter | `model`, `provider` | `chat/_inference.py` (status=aborted) |
| `chatsune_tool_calls_total` | Counter | `model`, `tool_name` | `tools/__init__.py::execute_tool()` |
| `chatsune_tool_call_duration_seconds` | Histogram | `model`, `tool_name` | `tools/__init__.py::execute_tool()` |
| `chatsune_models_available` | Gauge | `provider` | `llm/_metadata.py` (on model refresh) |
| `chatsune_embedding_calls_total` | Counter | `cache_status` (cached/uncached) | `embedding/__init__.py::query_embed()` |

### Instrumentation Pattern

Each module imports metric objects from `metrics` and calls `.inc()`, `.observe()`,
or `.set()` directly. No decorators, no wrappers, no middleware.

```python
# Example in llm/__init__.py
from backend.modules.metrics import inference_counter, inference_duration

inference_counter.labels(model=model, provider=provider, source=source).inc()
inference_duration.labels(model=model, provider=provider).observe(duration)
```

### No Docker Changes

No Prometheus container. No Grafana. The endpoint is scraped externally or
read directly in a browser (`/api/metrics`).

---

## Files Changed

### New Files
- `backend/modules/metrics/__init__.py`
- `backend/modules/metrics/_definitions.py`
- `backend/modules/metrics/_handlers.py`

### Modified Files — Backend
- `shared/events/chat.py` — add timing + model fields to `ChatStreamEndedEvent`
- `backend/modules/chat/_inference.py` — compute TTFT, tok/s, duration; emit with stream-ended
- `backend/modules/llm/__init__.py` — instrument inference counter + histogram
- `backend/modules/tools/__init__.py` — instrument tool call counter + histogram
- `backend/modules/embedding/__init__.py` — instrument embedding cache hit/miss counter
- `backend/modules/llm/_metadata.py` — instrument models-available gauge on refresh
- `backend/main.py` — register metrics router
- `pyproject.toml` — add `prometheus-client`

### Modified Files — Frontend
- `shared/events/chat.py` types mirrored in frontend event types
- Chat store — persist stats from stream-ended event on message object
- `MessageList.tsx` or `AssistantMessage.tsx` — add collapsible stats line
- "Model still working" display — add elapsed timer with interval

# Streaming Metrics, Elapsed Time & Prometheus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add inference performance stats (TTFT, tok/s) to the chat UI, a live elapsed timer during stalled streams, and a Prometheus metrics endpoint for scraping.

**Architecture:** New `backend/modules/metrics/` module owns all Prometheus metric objects and exposes `/api/metrics`. Other modules import and call `.inc()`/`.observe()`/`.set()` directly. Timing data is computed in the inference runner and piggybacked on the existing `ChatStreamEndedEvent`. The frontend shows stats in a collapsible line under each assistant message and adds a live timer to the existing "Model still working..." indicator.

**Tech Stack:** prometheus-client (Python), Zustand (frontend state), React hooks (timer)

---

### Task 1: Create Prometheus metrics module — definitions and endpoint

**Files:**
- Create: `backend/modules/metrics/__init__.py`
- Create: `backend/modules/metrics/_definitions.py`
- Create: `backend/modules/metrics/_handlers.py`
- Modify: `pyproject.toml:6-30` (add prometheus-client dependency)

- [ ] **Step 1: Add prometheus-client dependency**

In `pyproject.toml`, add to the `dependencies` list:

```toml
"prometheus-client>=0.21",
```

Run:
```bash
cd /home/chris/workspace/chatsune && uv sync
```

- [ ] **Step 2: Create `_definitions.py` with all metric objects**

```python
"""Prometheus metric definitions for Chatsune.

All metrics are defined here. Other modules import the objects they need
and call .inc(), .observe(), or .set() directly.
"""

from prometheus_client import Counter, Histogram, Gauge

# ── Inference ───────────────────────────────────────────────────────
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

# ── Tool calls ───────���──────────────────────────────────────────────
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

# ── Models ──────────────────────────────────────────────────────────
models_available = Gauge(
    "chatsune_models_available",
    "Number of models available per upstream provider",
    ["provider"],
)

# ── Embeddings ──────────────────────────────────────────────────────
embedding_calls_total = Counter(
    "chatsune_embedding_calls_total",
    "Total number of embedding calls",
    ["cache_status"],
)
```

- [ ] **Step 3: Create `_handlers.py` with the metrics endpoint**

```python
"""HTTP handler exposing Prometheus metrics."""

from fastapi import APIRouter
from fastapi.responses import Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

router = APIRouter(prefix="/api", tags=["metrics"])


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

- [ ] **Step 4: Create `__init__.py` — public API**

```python
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
```

- [ ] **Step 5: Commit**

```bash
git add backend/modules/metrics/ pyproject.toml uv.lock
git commit -m "Add Prometheus metrics module with definitions and endpoint"
```

---

### Task 2: Register metrics router in main.py

**Files:**
- Modify: `backend/main.py:553-568` (add import and router registration)

- [ ] **Step 1: Add import**

At the top of `main.py`, alongside the other module imports, add:

```python
from backend.modules.metrics import router as metrics_router
```

- [ ] **Step 2: Register the router**

After line 567 (`app.include_router(ws_router)`), add:

```python
app.include_router(metrics_router)
```

- [ ] **Step 3: Verify endpoint responds**

```bash
cd /home/chris/workspace/chatsune && uv run python -c "
from fastapi.testclient import TestClient
from backend.main import app
# Just verify the route is registered
routes = [r.path for r in app.routes]
assert '/api/metrics' in routes, f'/api/metrics not found in {routes}'
print('OK: /api/metrics route registered')
"
```

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "Register Prometheus metrics router in FastAPI app"
```

---

### Task 3: Instrument LLM module — inference counter and histogram

**Files:**
- Modify: `backend/modules/llm/__init__.py:69-142` (instrument `stream_completion()`)

- [ ] **Step 1: Add metrics import**

At the top of `backend/modules/llm/__init__.py`, add:

```python
from backend.modules.metrics import inference_total, inference_duration_seconds
```

- [ ] **Step 2: Add counter increment at stream start**

In `stream_completion()`, after `started_at_perf = _now_perf()` (line 119), before the `try:` block on line 120, add:

```python
    inference_total.labels(model=request.model, provider=provider_id, source=source).inc()
```

- [ ] **Step 3: Add histogram observation in the finally block**

In the `finally:` block (lines 136-142), after `_tracker.unregister(inference_id)` and before the `await _publish_inference_finished(...)` call, add:

```python
        inference_duration_seconds.labels(
            model=request.model, provider=provider_id,
        ).observe(_now_perf() - started_at_perf)
```

- [ ] **Step 4: Commit**

```bash
git add backend/modules/llm/__init__.py
git commit -m "Instrument LLM inference with Prometheus counter and histogram"
```

---

### Task 4: Instrument tools module — tool call counter and histogram

**Files:**
- Modify: `backend/modules/tools/__init__.py:69-109` (instrument `execute_tool()`)

- [ ] **Step 1: Add imports**

At the top of `backend/modules/tools/__init__.py`, add:

```python
import time as _time

from backend.modules.metrics import tool_calls_total, tool_call_duration_seconds
```

- [ ] **Step 2: Wrap execute_tool with timing**

The `execute_tool()` function currently doesn't have a `model` parameter. Tool calls are dispatched from the inference runner, which knows the model. We need to add an optional `model` parameter.

In `backend/modules/tools/__init__.py`, change the `execute_tool` signature (line 69-77) to add `model: str = ""`:

```python
async def execute_tool(
    user_id: str,
    tool_name: str,
    arguments_json: str,
    *,
    tool_call_id: str,
    session_id: str,
    originating_connection_id: str,
    model: str = "",
) -> str:
```

Then wrap the body to capture timing. After `arguments = json.loads(arguments_json)` (line 88), add:

```python
    t_start = _time.monotonic()
```

Before the `raise ToolNotFoundError` at the end (line 109), and after each `return` statement inside the loop, the metric needs to fire. The cleanest approach: wrap the existing loop body in a try/finally. Replace the entire for-loop body (lines 90-109) with:

```python
    for group in get_groups().values():
        if tool_name not in group.tool_names:
            continue

        try:
            if group.side == "client":
                return await _dispatcher_singleton.dispatch(
                    user_id=user_id,
                    session_id=session_id,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    arguments=arguments,
                    server_timeout_ms=_CLIENT_TOOL_SERVER_TIMEOUT_MS,
                    client_timeout_ms=_CLIENT_TOOL_CLIENT_TIMEOUT_MS,
                    target_connection_id=originating_connection_id,
                )

            if group.executor is not None:
                return await group.executor.execute(user_id, tool_name, arguments)
        finally:
            duration = _time.monotonic() - t_start
            tool_calls_total.labels(model=model, tool_name=tool_name).inc()
            tool_call_duration_seconds.labels(model=model, tool_name=tool_name).observe(duration)

    raise ToolNotFoundError(f"No executor registered for tool '{tool_name}'")
```

- [ ] **Step 3: Pass model through from inference runner**

In `backend/modules/chat/_orchestrator.py`, the `_make_tool_executor` closure (line 104-157) wraps `execute_tool`. Add a `model_slug` parameter to `_make_tool_executor`:

Change the signature (line 104-108) to:

```python
def _make_tool_executor(
    session: dict,
    persona: dict | None,
    correlation_id: str = "",
    connection_id: str | None = None,
    model_slug: str = "",
):
```

Then in the inner `_executor` function, pass `model=model_slug` to `execute_tool` (line 148-155):

```python
        return await execute_tool(
            user_id,
            tool_name,
            arguments_json,
            tool_call_id=tool_call_id,
            session_id=session.get("_id", ""),
            originating_connection_id=connection_id or "",
            model=model_slug,
        )
```

And update the call site in `run_inference` where `_make_tool_executor` is called. Search for `_make_tool_executor(` in `_orchestrator.py` and add `model_slug=model_slug`:

```python
    tool_executor = _make_tool_executor(
        session, persona,
        correlation_id=correlation_id,
        connection_id=connection_id,
        model_slug=model_slug,
    )
```

- [ ] **Step 4: Commit**

```bash
git add backend/modules/tools/__init__.py backend/modules/chat/_orchestrator.py
git commit -m "Instrument tool calls with Prometheus counter and histogram"
```

---

### Task 5: Instrument embedding module — cache hit/miss counter

**Files:**
- Modify: `backend/modules/embedding/__init__.py:107-136` (instrument `query_embed()`)

- [ ] **Step 1: Add metrics import**

At the top of `backend/modules/embedding/__init__.py`, add:

```python
from backend.modules.metrics import embedding_calls_total
```

- [ ] **Step 2: Add counter calls in query_embed()**

In `query_embed()` (lines 107-136):

After the cache-disabled path returns (line 114: `return await _queue.submit_query(text)`), add before the return:

```python
    if not settings.embedding_cache_enabled:
        embedding_calls_total.labels(cache_status="uncached").inc()
        return await _queue.submit_query(text)
```

After the cache-miss fallback (line 124-125: `return await _queue.submit_query(text)`), add before the return:

```python
    if _cache is None:
        embedding_calls_total.labels(cache_status="uncached").inc()
        return await _queue.submit_query(text)
```

After the cache hit check (line 129-131), add before the return:

```python
    if cached is not None:
        _log.debug("query embedding cache hit")
        embedding_calls_total.labels(cache_status="cached").inc()
        return cached
```

After the cache miss path (lines 133-135), add before the return:

```python
    _log.debug("query embedding cache miss")
    vector = await _queue.submit_query(normalized)
    await _cache.set(normalized, vector)
    embedding_calls_total.labels(cache_status="uncached").inc()
    return vector
```

- [ ] **Step 3: Commit**

```bash
git add backend/modules/embedding/__init__.py
git commit -m "Instrument embedding calls with Prometheus cache hit/miss counter"
```

---

### Task 6: Instrument model gauge on provider refresh

**Files:**
- Modify: `backend/modules/llm/_metadata.py:85-168` (instrument `refresh_all_providers()`)

- [ ] **Step 1: Add metrics import**

At the top of `backend/modules/llm/_metadata.py`, add:

```python
from backend.modules.metrics import models_available
```

- [ ] **Step 2: Set gauge after each provider is fetched**

In `refresh_all_providers()`, after `all_models.extend(models)` (line 121), add:

```python
            models_available.labels(provider=provider_id).set(len(models))
```

And in the `except NotImplementedError` block (line 122-123), add:

```python
        except NotImplementedError:
            _log.debug("Provider %s has not implemented fetch_models", provider_id)
            models_available.labels(provider=provider_id).set(0)
            provider_failed = True
```

And in the `except Exception` block (line 125-132), add after the faulty append:

```python
            models_available.labels(provider=provider_id).set(0)
```

- [ ] **Step 3: Commit**

```bash
git add backend/modules/llm/_metadata.py
git commit -m "Instrument model count gauge per provider on refresh"
```

---

### Task 7: Extend ChatStreamEndedEvent with timing and model fields

**Files:**
- Modify: `shared/events/chat.py:49-58` (add fields to ChatStreamEndedEvent)

- [ ] **Step 1: Add new optional fields to ChatStreamEndedEvent**

In `shared/events/chat.py`, extend the `ChatStreamEndedEvent` class (lines 49-58). Add these fields after `context_fill_percentage`:

```python
class ChatStreamEndedEvent(BaseModel):
    type: str = "chat.stream.ended"
    correlation_id: str
    session_id: str
    message_id: str | None = None
    status: Literal["completed", "cancelled", "error", "aborted", "refused"]
    usage: dict | None = None
    context_status: Literal["green", "yellow", "orange", "red"]
    context_fill_percentage: float = 0.0
    time_to_first_token_ms: int | None = None
    tokens_per_second: float | None = None
    generation_duration_ms: int | None = None
    provider_name: str | None = None
    model_name: str | None = None
    timestamp: datetime
```

- [ ] **Step 2: Commit**

```bash
git add shared/events/chat.py
git commit -m "Add timing and model fields to ChatStreamEndedEvent"
```

---

### Task 8: Compute timing in inference runner and pass model info

**Files:**
- Modify: `backend/modules/chat/_inference.py:43-62,77-109,124-135,402-411` (add timing + model params)
- Modify: `backend/modules/chat/_orchestrator.py:304-311,492-523` (pass model info to runner)

- [ ] **Step 1: Add time import and model params to InferenceRunner**

In `backend/modules/chat/_inference.py`, add `import time` at the top if not already present.

Extend the `run()` method signature (lines 43-55) to accept model info (display names for the frontend event, raw IDs for Prometheus labels):

```python
    async def run(
        self,
        user_id: str,
        session_id: str,
        correlation_id: str,
        stream_fn: Callable,
        emit_fn: Callable,
        save_fn: Callable,
        cancel_event: asyncio.Event | None = None,
        context_status: str = "green",
        context_fill_percentage: float = 0.0,
        tool_executor_fn: Callable | None = None,
        provider_name: str | None = None,
        model_name: str | None = None,
        provider_id: str = "",
        model_slug: str = "",
    ) -> None:
        lock = get_user_lock(user_id)
        async with lock:
            await self._run_locked(
                user_id, session_id, correlation_id, stream_fn, emit_fn, save_fn,
                cancel_event, context_status, context_fill_percentage,
                tool_executor_fn, provider_name, model_name,
                provider_id, model_slug,
            )
```

Extend `_run_locked()` signature (lines 64-76) similarly:

```python
    async def _run_locked(
        self,
        user_id: str,
        session_id: str,
        correlation_id: str,
        stream_fn: Callable,
        emit_fn: Callable,
        save_fn: Callable,
        cancel_event: asyncio.Event | None,
        context_status: str = "green",
        context_fill_percentage: float = 0.0,
        tool_executor_fn: Callable | None = None,
        provider_name: str | None = None,
        model_name: str | None = None,
        provider_id: str = "",
        model_slug: str = "",
    ) -> None:
```

- [ ] **Step 2: Add timing variables after the existing initialisations**

After `extra_messages: list[CompletionMessage] = []` (line 93), add:

```python
        t_stream_start = time.monotonic()
        t_first_token: float | None = None
```

- [ ] **Step 3: Record first token timestamp**

In the `ContentDelta` handler (lines 125-129), add before the existing code:

```python
                        case ContentDelta(delta=delta):
                            if t_first_token is None:
                                t_first_token = time.monotonic()
                            iter_content += delta
                            await emit_fn(ChatContentDeltaEvent(
                                correlation_id=correlation_id, delta=delta,
                            ))
```

In the `ThinkingDelta` handler (lines 131-135), add similarly:

```python
                        case ThinkingDelta(delta=delta):
                            if t_first_token is None:
                                t_first_token = time.monotonic()
                            iter_thinking += delta
                            await emit_fn(ChatThinkingDeltaEvent(
                                correlation_id=correlation_id, delta=delta,
                            ))
```

- [ ] **Step 4: Compute metrics and include in ChatStreamEndedEvent**

Replace the `ChatStreamEndedEvent` emission (lines 402-411) with:

```python
        t_stream_end = time.monotonic()
        total_duration = t_stream_end - t_stream_start

        ttft_ms: int | None = None
        if t_first_token is not None:
            ttft_ms = round((t_first_token - t_stream_start) * 1000)

        tps: float | None = None
        output_tokens = (usage or {}).get("output_tokens")
        if output_tokens and total_duration > 0:
            tps = round(output_tokens / total_duration, 1)

        gen_duration_ms = round(total_duration * 1000)

        await emit_fn(ChatStreamEndedEvent(
            correlation_id=correlation_id,
            session_id=session_id,
            message_id=message_id,
            status=status,
            usage=usage,
            context_status=context_status,
            context_fill_percentage=context_fill_percentage,
            time_to_first_token_ms=ttft_ms,
            tokens_per_second=tps,
            generation_duration_ms=gen_duration_ms,
            provider_name=provider_name,
            model_name=model_name,
            timestamp=datetime.now(timezone.utc),
        ))
```

- [ ] **Step 5: Instrument aborted inference counter**

Add the metrics import at the top of `_inference.py`:

```python
from backend.modules.metrics import inferences_aborted_total
```

In the `StreamAborted` handler (lines 165-178), after `status = "aborted"` (line 170), add:

```python
                            inferences_aborted_total.labels(
                                model=model_slug or "unknown",
                                provider=provider_id or "unknown",
                            ).inc()
```

- [ ] **Step 6: Pass model info from orchestrator to runner**

In `backend/modules/chat/_orchestrator.py`, in the `run_inference()` function, the runner is called around the end. Find where `_runner.run(...)` is called and add the model info params.

First, resolve provider display name. After `provider_id, model_slug = model_unique_id.split(":", 1)` (line 325), add:

```python
    from backend.modules.llm._registry import PROVIDER_DISPLAY_NAMES
    provider_display_name = PROVIDER_DISPLAY_NAMES.get(provider_id, provider_id)
```

Then find the `_runner.run(...)` call (search for `_runner.run(` in the orchestrator) and add the new params:

```python
    await _runner.run(
        user_id=user_id,
        session_id=session_id,
        correlation_id=correlation_id,
        stream_fn=stream_fn,
        emit_fn=emit_fn,
        save_fn=save_fn,
        cancel_event=cancel_event,
        context_status=ampel_status,
        context_fill_percentage=context_fill_pct,
        tool_executor_fn=tool_executor,
        provider_name=provider_display_name,
        model_name=model_slug,
        provider_id=provider_id,
        model_slug=model_slug,
    )
```

Note: There may be multiple call sites (`run_inference` and `handle_incognito_send`). Search for all `_runner.run(` occurrences and update each one. For `handle_incognito_send`, the provider_id and model_slug should be available from the same model_unique_id split pattern.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/chat/_inference.py backend/modules/chat/_orchestrator.py
git commit -m "Compute TTFT, tok/s and generation duration in inference runner"
```

---

### Task 9: Frontend — extend ChatMessageDto with stats fields

**Files:**
- Modify: `frontend/src/core/api/chat.ts:40-56` (add stats fields to ChatMessageDto)

- [ ] **Step 1: Add stats fields to ChatMessageDto interface**

In `frontend/src/core/api/chat.ts`, extend the `ChatMessageDto` interface (lines 40-56). Add after the `usage` field:

```typescript
interface ChatMessageDto {
  id: string
  session_id: string
  role: "user" | "assistant" | "tool"
  content: string
  thinking: string | null
  token_count: number
  attachments: AttachmentRefDto[] | null
  web_search_context: WebSearchContextItem[] | null
  knowledge_context: RetrievedChunkDto[] | null
  vision_descriptions_used?: VisionDescriptionSnapshot[] | null
  created_at: string
  status?: 'completed' | 'aborted' | 'refused'
  refusal_text?: string | null
  artefact_refs?: ArtefactRef[] | null
  usage?: { input_tokens?: number; output_tokens?: number } | null
  time_to_first_token_ms?: number | null
  tokens_per_second?: number | null
  generation_duration_ms?: number | null
  provider_name?: string | null
  model_name?: string | null
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/core/api/chat.ts
git commit -m "Add streaming stats fields to frontend ChatMessageDto"
```

---

### Task 10: Frontend — wire stats from stream-ended event into message

**Files:**
- Modify: `frontend/src/features/chat/useChatStream.ts:77-130` (extract new fields from stream-ended)

- [ ] **Step 1: Extract stats from ChatStreamEndedEvent payload**

In `useChatStream.ts`, in the `CHAT_STREAM_ENDED` case (lines 77-130), after the existing payload extractions (lines 80-88), add:

```typescript
      const ttft = (p.time_to_first_token_ms as number | undefined) ?? null
      const tps = (p.tokens_per_second as number | undefined) ?? null
      const genDuration = (p.generation_duration_ms as number | undefined) ?? null
      const providerName = (p.provider_name as string | undefined) ?? null
      const modelName = (p.model_name as string | undefined) ?? null
```

Then include these in the finalMessage object (lines 106-120). Add the new fields:

```typescript
        getStore().finishStreaming(
          {
            id: backendMessageId,
            session_id: sessionId ?? '',
            role: 'assistant',
            content,
            thinking: thinking || null,
            token_count: 0,
            attachments: null,
            web_search_context: webSearchContext.length > 0 ? webSearchContext : null,
            knowledge_context: knowledgeContext.length > 0 ? knowledgeContext : null,
            artefact_refs: artefactRefs.length > 0 ? artefactRefs : null,
            refusal_text: refusalText || null,
            created_at: new Date().toISOString(),
            status: messageStatus,
            time_to_first_token_ms: ttft,
            tokens_per_second: tps,
            generation_duration_ms: genDuration,
            provider_name: providerName,
            model_name: modelName,
          },
          contextStatus,
          fillPercentage,
        )
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/features/chat/useChatStream.ts
git commit -m "Wire streaming stats from stream-ended event into persisted message"
```

---

### Task 11: Frontend — create StatsLine component and add to AssistantMessage

**Files:**
- Create: `frontend/src/features/chat/StatsLine.tsx`
- Modify: `frontend/src/features/chat/AssistantMessage.tsx` (add StatsLine below action bar)

- [ ] **Step 1: Create StatsLine component**

Create `frontend/src/features/chat/StatsLine.tsx`:

```tsx
import { useState } from 'react'

interface StatsLineProps {
  timeToFirstTokenMs: number | null | undefined
  tokensPerSecond: number | null | undefined
  generationDurationMs: number | null | undefined
  outputTokens: number | null | undefined
  providerName: string | null | undefined
  modelName: string | null | undefined
}

function formatTtft(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

export function StatsLine({
  timeToFirstTokenMs,
  tokensPerSecond,
  generationDurationMs,
  outputTokens,
  providerName,
  modelName,
}: StatsLineProps) {
  const [expanded, setExpanded] = useState(false)

  // Nothing to show if all values are missing
  const hasAny = timeToFirstTokenMs != null || tokensPerSecond != null || outputTokens != null
  if (!hasAny) return null

  const parts: string[] = []
  if (timeToFirstTokenMs != null) parts.push(`TTFT: ${formatTtft(timeToFirstTokenMs)}`)
  if (tokensPerSecond != null) parts.push(`${tokensPerSecond} tok/s`)
  if (outputTokens != null) parts.push(`${outputTokens} tokens`)

  const modelPart = providerName && modelName
    ? `${providerName} / ${modelName}`
    : providerName || modelName || null

  if (modelPart) parts.push(modelPart)

  return (
    <div className="mt-1">
      {!expanded ? (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="flex items-center gap-1 text-[11px] text-white/20 transition-colors hover:text-white/40"
          title="Show inference stats"
        >
          <svg width="12" height="12" viewBox="0 0 14 14" fill="none" aria-hidden="true">
            <circle cx="7" cy="7" r="6" stroke="currentColor" strokeWidth="1.2" />
            <path d="M7 6V10M7 4.5V4.51" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
          </svg>
          <span>stats</span>
        </button>
      ) : (
        <button
          type="button"
          onClick={() => setExpanded(false)}
          className="text-[11px] text-white/30 transition-colors hover:text-white/40"
        >
          {parts.join(' \u00B7 ')}
        </button>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Add StatsLine to AssistantMessage**

In `frontend/src/features/chat/AssistantMessage.tsx`:

Add import at the top:

```typescript
import { StatsLine } from './StatsLine'
```

Extend the `AssistantMessageProps` interface to include the new fields:

```typescript
interface AssistantMessageProps {
  content: string; thinking: string | null; isStreaming: boolean;
  accentColour: string; highlighter: Highlighter | null;
  isBookmarked?: boolean; onBookmark?: () => void;
  canRegenerate?: boolean; onRegenerate?: () => void;
  status?: 'completed' | 'aborted' | 'refused';
  refusalText?: string | null;
  timeToFirstTokenMs?: number | null;
  tokensPerSecond?: number | null;
  generationDurationMs?: number | null;
  outputTokens?: number | null;
  providerName?: string | null;
  modelName?: string | null;
}
```

Add the new props to the destructuring in the component function signature.

After the action bar (the `div` with `mt-2.5 flex gap-3 border-t` around line 99 in the original), add the StatsLine:

```tsx
        {!isStreaming && effectiveContent && (
          <>
            <div className="mt-2.5 flex gap-3 border-t border-white/6 pt-2">
              {/* ... existing copy/bookmark/regenerate buttons ... */}
            </div>
            <StatsLine
              timeToFirstTokenMs={timeToFirstTokenMs}
              tokensPerSecond={tokensPerSecond}
              generationDurationMs={generationDurationMs}
              outputTokens={outputTokens}
              providerName={providerName}
              modelName={modelName}
            />
          </>
        )}
```

Note: The existing `{!isStreaming && effectiveContent && (` block contains just the action bar `<div>`. Wrap it in a fragment `<>...</>` and add `<StatsLine>` after the action bar div.

- [ ] **Step 3: Pass stats props from MessageList**

In `frontend/src/features/chat/MessageList.tsx`, where `AssistantMessage` is rendered for persisted messages (around line 143-148), add the new props:

```tsx
<AssistantMessage content={msg.content} thinking={msg.thinking}
  isStreaming={false} accentColour={accentColour} highlighter={highlighter}
  isBookmarked={isBm} onBookmark={() => onBookmark(msg.id)}
  canRegenerate={canRegenerate && i === lastAssistantIdx} onRegenerate={onRegenerate}
  status={msg.status ?? 'completed'}
  refusalText={msg.refusal_text ?? null}
  timeToFirstTokenMs={msg.time_to_first_token_ms}
  tokensPerSecond={msg.tokens_per_second}
  generationDurationMs={msg.generation_duration_ms}
  outputTokens={msg.usage?.output_tokens}
  providerName={msg.provider_name}
  modelName={msg.model_name}
/>
```

- [ ] **Step 4: Verify build**

```bash
cd /home/chris/workspace/chatsune/frontend && pnpm run build
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/chat/StatsLine.tsx frontend/src/features/chat/AssistantMessage.tsx frontend/src/features/chat/MessageList.tsx
git commit -m "Add collapsible stats line below assistant messages"
```

---

### Task 12: Frontend — add elapsed timer to "Model still working" display

**Files:**
- Modify: `frontend/src/features/chat/MessageList.tsx:186-190` (replace static text with timer)

- [ ] **Step 1: Add timer state and effect**

In `MessageList.tsx`, add a local state and effect for the elapsed timer. Near the top of the component (after the existing hooks), add:

```typescript
const [slowElapsed, setSlowElapsed] = useState<number>(0)
const slowSinceRef = useRef<number | null>(null)

useEffect(() => {
  if (!streamingSlow) {
    slowSinceRef.current = null
    setSlowElapsed(0)
    return
  }
  slowSinceRef.current = Date.now()
  setSlowElapsed(0)
  const interval = setInterval(() => {
    if (slowSinceRef.current) {
      setSlowElapsed(Math.floor((Date.now() - slowSinceRef.current) / 1000))
    }
  }, 1000)
  return () => clearInterval(interval)
}, [streamingSlow])
```

Ensure `useState` and `useRef` are imported from React (they likely already are).

- [ ] **Step 2: Add elapsed time formatting helper**

Above the component or inside it, add:

```typescript
function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}m ${s}s`
}
```

- [ ] **Step 3: Replace static "Model still working" text**

Replace the "Model still working" block (lines 186-190):

```tsx
{streamingSlow && (
  <div className="mt-1 text-[11px] italic text-white/45">
    Model still working…
  </div>
)}
```

With:

```tsx
{streamingSlow && (
  <div className="mt-1 text-[11px] italic text-white/45">
    Model still working… {slowElapsed > 0 && formatElapsed(slowElapsed)}
  </div>
)}
```

- [ ] **Step 4: Verify build**

```bash
cd /home/chris/workspace/chatsune/frontend && pnpm run build
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/chat/MessageList.tsx
git commit -m "Add live elapsed timer to model-still-working indicator"
```

---

### Task 13: Full build verification

**Files:** None (verification only)

- [ ] **Step 1: Backend syntax check**

```bash
cd /home/chris/workspace/chatsune
uv run python -m py_compile backend/modules/metrics/__init__.py
uv run python -m py_compile backend/modules/metrics/_definitions.py
uv run python -m py_compile backend/modules/metrics/_handlers.py
uv run python -m py_compile backend/modules/llm/__init__.py
uv run python -m py_compile backend/modules/tools/__init__.py
uv run python -m py_compile backend/modules/embedding/__init__.py
uv run python -m py_compile backend/modules/llm/_metadata.py
uv run python -m py_compile backend/modules/chat/_inference.py
uv run python -m py_compile backend/modules/chat/_orchestrator.py
uv run python -m py_compile shared/events/chat.py
```

- [ ] **Step 2: Frontend build**

```bash
cd /home/chris/workspace/chatsune/frontend && pnpm run build
```

- [ ] **Step 3: Verify metrics endpoint is accessible**

Start the backend and check:

```bash
curl -s http://localhost:9000/api/metrics | head -20
```

Expected: Prometheus text format with `chatsune_` prefixed metrics.

- [ ] **Step 4: Final commit (if any fixes needed)**

Only if build issues required fixes. Otherwise, skip.

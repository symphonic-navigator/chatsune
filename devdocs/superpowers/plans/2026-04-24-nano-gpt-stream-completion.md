# Nano-GPT Adapter — `stream_completion` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Phase-2 `stream_completion` method of `NanoGptHttpAdapter` — SSE streaming against nano-gpt's OpenAI-compatible `/v1/chat/completions`, with upstream-slug selection driven by the Redis pair map (set by Phase-1 `fetch_models`). The adapter must **not** carry `reasoning` / `thinking` flags in the request body — thinking is switched exclusively by picking the `thinking_slug` from the pair map.

**Architectural decisions (confirmed with Chris 2026-04-24):**
- Duplicate the OpenAI-compat SSE helpers from `_xai_http.py` into `_nano_gpt_http.py`. A future refactor to `_openai_compat.py` is tracked in memory (`project_openai_compat_refactor.md`); once the 3rd adapter ships, the de-duplication is justified — but not in this session.
- Plumb `Redis` into `llm.stream_completion` via the existing `_instantiate_adapter(adapter_cls, redis)` helper. Same pattern as `_metadata.py` already uses. Future redis-consuming adapters opt-in automatically.
- Model-exploration / nano-gpt metadata curation is a separate session. This plan is strictly about making `/completions` work end-to-end.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, httpx, redis.asyncio (via fakeredis in tests), pytest-asyncio. No new dependencies.

**Out of scope (future sessions):**
- Extraction of `_openai_compat.py` shared module
- Model iteration / curation (nano-gpt metadata quality is apparently poor — separate workstream)
- Tool-calls verification at upstream level (covered by test mocks, not live)
- Thinking budget / level controls (stripped at catalogue time, see `filter_budget_variants`)

---

## File Structure

**Modify:**
- `backend/modules/llm/_adapters/_nano_gpt_http.py` — add SSE helpers, `_build_chat_payload`, `_pick_upstream_slug`, rewrite `stream_completion`
- `backend/modules/llm/__init__.py:152` — use `_instantiate_adapter(adapter_cls, get_redis())`
- `backend/tests/modules/llm/adapters/test_nano_gpt_http.py` — replace the Phase-2-stub test with real SSE tests

**No new files.**

---

### Task 1: Port SSE helpers and `_build_chat_payload` into `_nano_gpt_http.py`

The goal here is pure mechanical duplication from `_xai_http.py`, **minus** the xAI-specific bits (model-slug constants, `x-grok-conv-id` header support, cache_hint wiring). Stream_completion itself stays as the Phase-2 stub — we wire it up in Task 2.

**Files:**
- Modify: `backend/modules/llm/_adapters/_nano_gpt_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_nano_gpt_http.py`

- [ ] **Step 1: Write failing unit tests for `_translate_message`**

Add to `test_nano_gpt_http.py`:

```python
from shared.dtos.inference import CompletionMessage, ContentPart, ToolCallResult
from backend.modules.llm._adapters._nano_gpt_http import _translate_message


def test_translate_message_plain_text_becomes_string():
    msg = CompletionMessage(
        role="user",
        content=[ContentPart(type="text", text="hi")],
    )
    out = _translate_message(msg)
    assert out == {"role": "user", "content": "hi"}


def test_translate_message_with_image_becomes_list_of_parts():
    msg = CompletionMessage(
        role="user",
        content=[
            ContentPart(type="text", text="look at this"),
            ContentPart(type="image", data="BASE64DATA", media_type="image/png"),
        ],
    )
    out = _translate_message(msg)
    assert out["role"] == "user"
    assert out["content"] == [
        {"type": "text", "text": "look at this"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,BASE64DATA"}},
    ]


def test_translate_message_tool_call_round_trip():
    msg = CompletionMessage(
        role="assistant",
        content=[ContentPart(type="text", text="")],
        tool_calls=[ToolCallResult(id="c1", name="f", arguments='{"x":1}')],
    )
    out = _translate_message(msg)
    assert out["tool_calls"] == [
        {"id": "c1", "type": "function",
         "function": {"name": "f", "arguments": '{"x":1}'}},
    ]


def test_translate_message_tool_response_carries_tool_call_id():
    msg = CompletionMessage(
        role="tool",
        content=[ContentPart(type="text", text="result")],
        tool_call_id="c1",
    )
    out = _translate_message(msg)
    assert out["tool_call_id"] == "c1"
    assert out["content"] == "result"
```

- [ ] **Step 2: Write failing unit tests for `_parse_sse_line`**

```python
from backend.modules.llm._adapters._nano_gpt_http import _parse_sse_line, _SSE_DONE


def test_parse_sse_line_ignores_blank():
    assert _parse_sse_line("") is None
    assert _parse_sse_line("   ") is None


def test_parse_sse_line_ignores_non_data_frames():
    assert _parse_sse_line("event: ping") is None
    assert _parse_sse_line(":keepalive") is None


def test_parse_sse_line_done_sentinel():
    assert _parse_sse_line("data: [DONE]") is _SSE_DONE


def test_parse_sse_line_valid_json():
    assert _parse_sse_line('data: {"x":1}') == {"x": 1}


def test_parse_sse_line_malformed_json_returns_none():
    assert _parse_sse_line("data: {bad json") is None
```

- [ ] **Step 3: Write failing unit tests for `_ToolCallAccumulator` + `_chunk_to_events`**

```python
from backend.modules.llm._adapters._nano_gpt_http import (
    _ToolCallAccumulator, _chunk_to_events,
)
from backend.modules.llm._adapters._events import (
    ContentDelta, ThinkingDelta, StreamDone, StreamRefused, ToolCallEvent,
)


def test_tool_call_accumulator_merges_fragments():
    acc = _ToolCallAccumulator()
    acc.ingest([{"index": 0, "id": "c_1", "function": {"name": "sum", "arguments": '{"a":1'}}])
    acc.ingest([{"index": 0, "function": {"arguments": ',"b":2}'}}])
    calls = acc.finalised()
    assert calls == [{"id": "c_1", "name": "sum", "arguments": '{"a":1,"b":2}'}]


def test_chunk_to_events_content_delta():
    acc = _ToolCallAccumulator()
    events = _chunk_to_events(
        {"choices": [{"delta": {"content": "hello"}}]}, acc,
    )
    assert events == [ContentDelta(delta="hello")]


def test_chunk_to_events_thinking_delta_from_reasoning_content():
    acc = _ToolCallAccumulator()
    events = _chunk_to_events(
        {"choices": [{"delta": {"reasoning_content": "thinking…"}}]}, acc,
    )
    assert events == [ThinkingDelta(delta="thinking…")]


def test_chunk_to_events_usage_only_emits_stream_done_with_tokens():
    acc = _ToolCallAccumulator()
    events = _chunk_to_events(
        {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 34}}, acc,
    )
    assert events == [StreamDone(input_tokens=12, output_tokens=34)]


def test_chunk_to_events_tool_call_finish():
    acc = _ToolCallAccumulator()
    # fragment chunk
    _chunk_to_events({"choices": [{"delta": {
        "tool_calls": [{"index": 0, "id": "c1",
                         "function": {"name": "f", "arguments": '{"x":1}'}}],
    }}]}, acc)
    # finish chunk
    events = _chunk_to_events({"choices": [{
        "delta": {}, "finish_reason": "tool_calls",
    }]}, acc)
    assert events == [ToolCallEvent(id="c1", name="f", arguments='{"x":1}')]


def test_chunk_to_events_refusal():
    acc = _ToolCallAccumulator()
    events = _chunk_to_events({"choices": [{
        "delta": {"refusal": "blocked"},
        "finish_reason": "content_filter",
    }]}, acc)
    assert events == [StreamRefused(reason="content_filter", refusal_text="blocked")]
```

- [ ] **Step 4: Run the tests — expect ImportError / AttributeError failures**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_nano_gpt_http.py -v
```

Expected: the new tests FAIL with `ImportError` or `AttributeError` on the not-yet-ported helpers. Existing tests continue to PASS.

- [ ] **Step 5: Port the helpers from `_xai_http.py`**

Copy the following from `backend/modules/llm/_adapters/_xai_http.py` into `_nano_gpt_http.py`, **above** the `class NanoGptHttpAdapter` definition:

1. Module-level imports needed (add to existing import block, alphabetised):
   ```python
   import asyncio
   import json
   import logging
   import os
   import time
   from uuid import uuid4
   ```

2. Module-level constants — place near existing `_DEFAULT_BASE_URL`:
   ```python
   _log = logging.getLogger(__name__)

   _TRACE_PAYLOADS = os.environ.get("LLM_TRACE_PAYLOADS") == "1"

   GUTTER_SLOW_SECONDS: float = 30.0
   GUTTER_ABORT_SECONDS: float = float(
       os.environ.get("LLM_STREAM_ABORT_SECONDS", "120"),
   )

   _STREAM_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=15.0)
   _REFUSAL_REASONS: frozenset[str] = frozenset({"content_filter", "refusal"})

   _SSE_DONE = object()  # sentinel — distinct from any JSON-decodable value
   ```

   Note: the existing `_TIMEOUT = 30.0` is for `_http_get_models` — keep it. Add `_STREAM_TIMEOUT` as a separate httpx.Timeout for the streaming path (matches xAI's 300-second read budget).

3. Class `_ToolCallAccumulator` — copy verbatim from `_xai_http.py:54-91`.

4. Function `_chunk_to_events(chunk, acc)` — copy verbatim from `_xai_http.py:94-157`.

5. Function `_parse_sse_line(line)` — copy verbatim from `_xai_http.py:160-178`.

6. Function `_translate_message(msg)` — copy verbatim from `_xai_http.py:181-216`.

7. Adjust imports: add `CompletionMessage` to the existing `from shared.dtos.inference import ...` line so `_translate_message` signature compiles.

8. Update `ProviderStreamEvent` import in `_nano_gpt_http.py` to additionally bring in the concrete event classes used by `_chunk_to_events`:
   ```python
   from backend.modules.llm._adapters._events import (
       ContentDelta,
       ProviderStreamEvent,
       StreamAborted,
       StreamDone,
       StreamError,
       StreamRefused,
       StreamSlow,
       ThinkingDelta,
       ToolCallEvent,
   )
   ```

- [ ] **Step 6: Add `_build_chat_payload` — nano-gpt-specific (no reasoning flag)**

Add this helper, **below** the translated helpers, above the class. It is deliberately different from xAI — it receives the upstream slug as an argument rather than picking it based on `reasoning_enabled`, and it carries no reasoning/thinking hints in the body.

```python
def _build_chat_payload(request: CompletionRequest, upstream_slug: str) -> dict:
    """Build an OpenAI-compatible chat-completions request body.

    Thinking capability is expressed *exclusively* via ``upstream_slug`` —
    nano-gpt does not honour any ``reasoning`` / ``thinking`` flag in the
    body. Do not add one here; see the module docstring.
    """
    payload: dict = {
        "model": upstream_slug,
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [_translate_message(m) for m in request.messages],
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in request.tools
        ]
    return payload
```

- [ ] **Step 7: Run tests to verify the helpers pass**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_nano_gpt_http.py -v
```

Expected: all new helper tests PASS. The `test_stream_completion_raises_phase_2_not_implemented` still PASSES (we haven't touched `stream_completion` yet).

- [ ] **Step 8: Verify Python build**

```bash
uv run python -m py_compile backend/modules/llm/_adapters/_nano_gpt_http.py
```

Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add backend/modules/llm/_adapters/_nano_gpt_http.py \
        backend/tests/modules/llm/adapters/test_nano_gpt_http.py
git commit -m "Port OpenAI-compat SSE helpers into nano-gpt adapter"
```

---

### Task 2: Implement `stream_completion`

Replace the Phase-2 `NotImplementedError` stub with the full SSE loop. Pair-map lookup picks `thinking_slug` when `request.reasoning_enabled` is true **and** the pair has one, otherwise `non_thinking_slug`.

**Files:**
- Modify: `backend/modules/llm/_adapters/_nano_gpt_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_nano_gpt_http.py`

- [ ] **Step 1: Write a failing test for `_pick_upstream_slug`**

This is a pure helper — testing it in isolation is much cheaper than through the full SSE stack.

```python
from backend.modules.llm._adapters._nano_gpt_http import _pick_upstream_slug


def test_pick_upstream_slug_reasoning_off_returns_non_thinking():
    pair_map = {"m1": {"non_thinking_slug": "m1", "thinking_slug": "m1:thinking"}}
    assert _pick_upstream_slug(pair_map, model_id="m1", reasoning_enabled=False) == "m1"


def test_pick_upstream_slug_reasoning_on_returns_thinking():
    pair_map = {"m1": {"non_thinking_slug": "m1", "thinking_slug": "m1:thinking"}}
    assert _pick_upstream_slug(pair_map, model_id="m1", reasoning_enabled=True) == "m1:thinking"


def test_pick_upstream_slug_reasoning_on_but_no_thinking_falls_back():
    # Model has no thinking variant — we fall back to the non-thinking slug
    # instead of refusing the request. Surprises no-one and matches the
    # frontend's capability-gated UI.
    pair_map = {"m1": {"non_thinking_slug": "m1", "thinking_slug": None}}
    assert _pick_upstream_slug(pair_map, model_id="m1", reasoning_enabled=True) == "m1"


def test_pick_upstream_slug_unknown_model_returns_none():
    assert _pick_upstream_slug({}, model_id="nope", reasoning_enabled=False) is None
```

- [ ] **Step 2: Write failing end-to-end SSE tests**

Replace the existing `test_stream_completion_raises_phase_2_not_implemented` with real tests. Keep the existing `_resolved_conn` / `redis_client` fixtures.

```python
from backend.modules.llm._adapters._nano_gpt_pair_map import save_pair_map
from shared.dtos.inference import ContentPart


def _make_request(model_id: str, *, reasoning_enabled: bool = False) -> CompletionRequest:
    return CompletionRequest(
        model=model_id,
        messages=[CompletionMessage(
            role="user",
            content=[ContentPart(type="text", text="hi")],
        )],
        reasoning_enabled=reasoning_enabled,
    )


class _FakeResponse:
    """Minimal httpx.Response lookalike for client.stream(...) context."""
    def __init__(self, status_code: int, lines: list[str], body: bytes = b""):
        self.status_code = status_code
        self._lines = lines
        self._body = body

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self):
        return self._body

    async def __aenter__(self):
        return self
    async def __aexit__(self, *exc):
        return False


class _FakeClient:
    def __init__(self, response: _FakeResponse):
        self._response = response
        self.posted_url: str | None = None
        self.posted_payload: dict | None = None
        self.posted_headers: dict | None = None

    def stream(self, method, url, *, json=None, headers=None):
        self.posted_url = url
        self.posted_payload = json
        self.posted_headers = headers
        return self._response

    async def __aenter__(self):
        return self
    async def __aexit__(self, *exc):
        return False


async def _populate_pair_map(redis_client, conn_id: str):
    await save_pair_map(
        redis_client, connection_id=conn_id,
        pair_map={
            "anthropic/claude-opus-4.6": {
                "non_thinking_slug": "anthropic/claude-opus-4.6",
                "thinking_slug": "anthropic/claude-opus-4.6:thinking",
            },
            "free/phi-small": {
                "non_thinking_slug": "free/phi-small",
                "thinking_slug": None,
            },
        },
    )


@pytest.mark.asyncio
async def test_stream_completion_happy_path_non_thinking(redis_client, monkeypatch):
    conn = _resolved_conn()
    await _populate_pair_map(redis_client, conn.id)

    sse_lines = [
        'data: {"choices":[{"delta":{"content":"hel"}}]}',
        'data: {"choices":[{"delta":{"content":"lo"}}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":2}}',
        'data: [DONE]',
    ]
    fake = _FakeClient(_FakeResponse(200, sse_lines))
    monkeypatch.setattr(
        "backend.modules.llm._adapters._nano_gpt_http.httpx.AsyncClient",
        lambda *a, **k: fake,
    )

    adapter = NanoGptHttpAdapter(redis=redis_client)
    events = []
    async for ev in adapter.stream_completion(
        conn, _make_request("anthropic/claude-opus-4.6"),
    ):
        events.append(ev)

    from backend.modules.llm._adapters._events import ContentDelta, StreamDone
    assert [type(e) for e in events] == [ContentDelta, ContentDelta, StreamDone]
    assert events[0].delta == "hel"
    assert events[1].delta == "lo"
    assert events[2].input_tokens == 3
    assert events[2].output_tokens == 2

    # Upstream slug used is the non-thinking variant; Authorization header set.
    assert fake.posted_payload["model"] == "anthropic/claude-opus-4.6"
    assert "reasoning" not in fake.posted_payload
    assert "thinking" not in fake.posted_payload
    assert fake.posted_headers["Authorization"] == "Bearer nano-test-key"
    assert fake.posted_url.endswith("/chat/completions")


@pytest.mark.asyncio
async def test_stream_completion_thinking_picks_thinking_slug(redis_client, monkeypatch):
    conn = _resolved_conn()
    await _populate_pair_map(redis_client, conn.id)

    sse_lines = [
        'data: {"choices":[{"delta":{"reasoning_content":"…"}}]}',
        'data: {"choices":[{"delta":{"content":"ok"}}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":1}}',
        'data: [DONE]',
    ]
    fake = _FakeClient(_FakeResponse(200, sse_lines))
    monkeypatch.setattr(
        "backend.modules.llm._adapters._nano_gpt_http.httpx.AsyncClient",
        lambda *a, **k: fake,
    )

    adapter = NanoGptHttpAdapter(redis=redis_client)
    events = []
    async for ev in adapter.stream_completion(
        conn, _make_request("anthropic/claude-opus-4.6", reasoning_enabled=True),
    ):
        events.append(ev)

    from backend.modules.llm._adapters._events import ThinkingDelta
    assert any(isinstance(e, ThinkingDelta) for e in events)
    assert fake.posted_payload["model"] == "anthropic/claude-opus-4.6:thinking"


@pytest.mark.asyncio
async def test_stream_completion_unknown_model_emits_model_not_found(redis_client, monkeypatch):
    conn = _resolved_conn()
    await _populate_pair_map(redis_client, conn.id)

    adapter = NanoGptHttpAdapter(redis=redis_client)
    events = [
        ev async for ev in adapter.stream_completion(
            conn, _make_request("not/in/map"),
        )
    ]
    assert len(events) == 1
    from backend.modules.llm._adapters._events import StreamError
    assert isinstance(events[0], StreamError)
    assert events[0].error_code == "model_not_found"


@pytest.mark.asyncio
async def test_stream_completion_401_emits_invalid_api_key(redis_client, monkeypatch):
    conn = _resolved_conn()
    await _populate_pair_map(redis_client, conn.id)

    fake = _FakeClient(_FakeResponse(401, [], body=b"unauthorized"))
    monkeypatch.setattr(
        "backend.modules.llm._adapters._nano_gpt_http.httpx.AsyncClient",
        lambda *a, **k: fake,
    )

    adapter = NanoGptHttpAdapter(redis=redis_client)
    events = [
        ev async for ev in adapter.stream_completion(
            conn, _make_request("anthropic/claude-opus-4.6"),
        )
    ]
    from backend.modules.llm._adapters._events import StreamError
    assert len(events) == 1
    assert events[0].error_code == "invalid_api_key"


@pytest.mark.asyncio
async def test_stream_completion_500_emits_provider_unavailable(redis_client, monkeypatch):
    conn = _resolved_conn()
    await _populate_pair_map(redis_client, conn.id)

    fake = _FakeClient(_FakeResponse(500, [], body=b"boom"))
    monkeypatch.setattr(
        "backend.modules.llm._adapters._nano_gpt_http.httpx.AsyncClient",
        lambda *a, **k: fake,
    )

    adapter = NanoGptHttpAdapter(redis=redis_client)
    events = [
        ev async for ev in adapter.stream_completion(
            conn, _make_request("anthropic/claude-opus-4.6"),
        )
    ]
    from backend.modules.llm._adapters._events import StreamError
    assert len(events) == 1
    assert events[0].error_code == "provider_unavailable"
    assert "500" in events[0].message


@pytest.mark.asyncio
async def test_stream_completion_requires_redis():
    adapter = NanoGptHttpAdapter()  # no redis
    conn = _resolved_conn()
    agen = adapter.stream_completion(conn, _make_request("m1"))
    with pytest.raises(RuntimeError, match="Redis"):
        async for _ in agen:
            pass
```

**Delete** the old `test_stream_completion_raises_phase_2_not_implemented` test — `stream_completion` is no longer a stub.

- [ ] **Step 3: Run tests to confirm they fail**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_nano_gpt_http.py -v -k stream_completion
```

Expected: most FAIL with `NotImplementedError: Phase 2` (the existing stub).

- [ ] **Step 4: Implement `_pick_upstream_slug` + `stream_completion`**

Add below `_build_chat_payload`:

```python
def _pick_upstream_slug(
    pair_map: dict[str, dict[str, str | None]],
    *, model_id: str, reasoning_enabled: bool,
) -> str | None:
    """Return the upstream slug to dispatch to, or ``None`` if unknown.

    When ``reasoning_enabled`` is true but the model has no thinking
    variant, fall back to the non-thinking slug. This matches the
    frontend's capability-gated UI: if the user toggles reasoning on a
    model that lacks it, we continue rather than refuse.
    """
    pair = pair_map.get(model_id)
    if pair is None:
        return None
    if reasoning_enabled and pair.get("thinking_slug"):
        return pair["thinking_slug"]
    return pair["non_thinking_slug"]
```

Replace the `stream_completion` body. Structure mirrors `_xai_http.py:312-438`, with these differences:
- no `cache_hint` / `x-grok-conv-id` header
- model slug is picked from pair_map via `_pick_upstream_slug`
- emits `StreamError("model_not_found")` when the lookup fails
- requires `self._redis` (consistent with `fetch_models`)

Full body:

```python
async def stream_completion(
    self, connection: ResolvedConnection, request: CompletionRequest,
) -> AsyncIterator[ProviderStreamEvent]:
    if self._redis is None:
        raise RuntimeError(
            "NanoGptHttpAdapter requires a Redis client for pair-map "
            "lookup — construct with redis= kwarg",
        )

    base_url = (connection.config.get("base_url") or _DEFAULT_BASE_URL).rstrip("/")
    api_key = connection.config.get("api_key") or ""

    # Load the pair map. ``fetch_models`` populates this; if the user has
    # never fetched models for this connection, the map is empty and we
    # signal model_not_found rather than attempting a blind upstream call.
    from backend.modules.llm._adapters._nano_gpt_pair_map import load_pair_map
    pair_map = await load_pair_map(self._redis, connection_id=connection.id)

    upstream_slug = _pick_upstream_slug(
        pair_map, model_id=request.model,
        reasoning_enabled=request.reasoning_enabled,
    )
    if upstream_slug is None:
        yield StreamError(
            error_code="model_not_found",
            message=(
                f"Model {request.model!r} is not in the nano-gpt pair map "
                f"for connection {connection.id}. Refresh the model list "
                f"and retry."
            ),
        )
        return

    payload = _build_chat_payload(request, upstream_slug)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    acc = _ToolCallAccumulator()
    seen_done = False
    pending_next: asyncio.Task | None = None

    if _TRACE_PAYLOADS:
        _log.info(
            "LLM_TRACE path=nano-gpt-out url=%s payload=%s",
            base_url, json.dumps(payload, default=str, sort_keys=True),
        )

    async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as client:
        try:
            async with client.stream(
                "POST", f"{base_url}/chat/completions",
                json=payload, headers=headers,
            ) as resp:
                if resp.status_code in (401, 403):
                    yield StreamError(
                        error_code="invalid_api_key",
                        message="Nano-GPT rejected the API key",
                    )
                    return
                if resp.status_code == 429:
                    yield StreamError(
                        error_code="provider_unavailable",
                        message="Nano-GPT rate limit hit",
                    )
                    return
                if resp.status_code != 200:
                    body = await resp.aread()
                    detail = body.decode("utf-8", errors="replace")[:500]
                    _log.error(
                        "nano_gpt_http upstream %d: %s",
                        resp.status_code, detail,
                    )
                    yield StreamError(
                        error_code="provider_unavailable",
                        message=f"Nano-GPT returned {resp.status_code}: {detail}",
                    )
                    return

                stream_iter = resp.aiter_lines().__aiter__()
                line_start = time.monotonic()
                slow_fired = False

                while True:
                    elapsed = time.monotonic() - line_start
                    budget = (
                        GUTTER_ABORT_SECONDS - elapsed if slow_fired
                        else GUTTER_SLOW_SECONDS - elapsed
                    )
                    if budget <= 0:
                        if not slow_fired:
                            _log.info(
                                "nano_gpt_http.gutter_slow model=%s idle=%.1fs",
                                upstream_slug, elapsed,
                            )
                            yield StreamSlow()
                            slow_fired = True
                            continue
                        _log.warning(
                            "nano_gpt_http.gutter_abort model=%s idle=%.1fs",
                            upstream_slug, elapsed,
                        )
                        if pending_next is not None:
                            pending_next.cancel()
                        yield StreamAborted(reason="gutter_timeout")
                        return
                    if pending_next is None:
                        pending_next = asyncio.ensure_future(
                            stream_iter.__anext__(),
                        )
                    done, _ = await asyncio.wait(
                        {pending_next}, timeout=budget,
                    )
                    if not done:
                        continue
                    task = done.pop()
                    pending_next = None
                    try:
                        line = task.result()
                    except StopAsyncIteration:
                        break
                    line_start = time.monotonic()
                    slow_fired = False

                    parsed = _parse_sse_line(line)
                    if parsed is None:
                        continue
                    if parsed is _SSE_DONE:
                        break

                    for event in _chunk_to_events(parsed, acc):
                        if isinstance(event, StreamDone):
                            seen_done = True
                        yield event
                        if isinstance(event, (StreamDone,
                                               StreamRefused,
                                               StreamError)):
                            return

        except asyncio.CancelledError:
            if pending_next is not None and not pending_next.done():
                pending_next.cancel()
            raise
        except httpx.ConnectError:
            yield StreamError(
                error_code="provider_unavailable",
                message="Cannot connect to Nano-GPT",
            )
            return

    if not seen_done:
        yield StreamDone()
```

Update the module docstring at the top: remove the "Phase-2 stub" sentence and tighten to describe the finished adapter. Keep the "no reasoning/thinking flag in the body" warning — it is load-bearing.

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_nano_gpt_http.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Verify Python build**

```bash
uv run python -m py_compile backend/modules/llm/_adapters/_nano_gpt_http.py
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/llm/_adapters/_nano_gpt_http.py \
        backend/tests/modules/llm/adapters/test_nano_gpt_http.py
git commit -m "Implement nano-gpt stream_completion with pair-map-driven slug selection"
```

---

### Task 3: Plumb Redis through `llm.stream_completion`

Today `backend/modules/llm/__init__.py:152` does `adapter = adapter_cls()` without redis. Nano-GPT needs redis to read the pair map at request time. Swap to the existing `_instantiate_adapter` helper so future redis-consuming adapters opt in by merely declaring a `redis` kwarg.

**Files:**
- Modify: `backend/modules/llm/__init__.py`
- Modify: `backend/tests/modules/llm/test_llm_module.py` (or wherever `stream_completion` is tested — verify first)

- [ ] **Step 1: Confirm the integration test shape**

```bash
rg -ln "async def test_.*stream_completion|llm\.stream_completion\(" backend/tests/ | head
```

Identify the test file that exercises `llm.stream_completion`. Most likely a wider `test_llm_module.py` or similar — if no such test exists, the change is exercised only by the new `test_stream_completion_nano_gpt_plumbs_redis` we add below.

- [ ] **Step 2: Write a failing integration-level test**

Add to whichever test file covers `llm.stream_completion` (or create a new `test_llm_module_nano_gpt_integration.py`):

```python
import pytest
from unittest.mock import patch

from backend.modules.llm import stream_completion
from shared.dtos.inference import CompletionRequest, CompletionMessage, ContentPart


@pytest.mark.asyncio
async def test_stream_completion_passes_redis_to_nano_gpt_adapter(
    monkeypatch, redis_client,
):
    """The top-level llm.stream_completion must construct the nano-gpt
    adapter with the live Redis client, otherwise pair-map lookup fails
    at request time."""
    # Patch get_redis to return our fake
    monkeypatch.setattr(
        "backend.modules.llm.get_redis", lambda: redis_client,
    )

    # Patch resolve_for_model to return a nano-gpt ResolvedConnection
    from backend.modules.llm._adapters._types import ResolvedConnection
    from datetime import UTC, datetime
    now = datetime.now(UTC)
    fake_conn = ResolvedConnection(
        id="c1", user_id="u1", adapter_type="nano_gpt_http",
        display_name="d", slug="s",
        config={"base_url": "https://example", "api_key": "k"},
        created_at=now, updated_at=now,
    )

    async def _fake_resolve(*a, **k):
        return fake_conn

    monkeypatch.setattr(
        "backend.modules.llm.resolve_for_model", _fake_resolve,
    )

    # Populate an empty pair_map so stream_completion emits model_not_found
    # cleanly (this proves the adapter's redis plumbing worked without us
    # needing to mock httpx).
    request = CompletionRequest(
        model="does/not/exist",
        messages=[CompletionMessage(role="user", content=[
            ContentPart(type="text", text="hi"),
        ])],
    )
    events = [
        ev async for ev in stream_completion("u1", "s:does/not/exist", request)
    ]
    from backend.modules.llm._adapters._events import StreamError
    assert len(events) == 1
    assert isinstance(events[0], StreamError)
    assert events[0].error_code == "model_not_found"
```

Reuse the `redis_client` fakeredis fixture from the adapter tests — copy to a conftest if not already there.

- [ ] **Step 3: Run the test to confirm it fails**

```bash
uv run pytest backend/tests/modules/llm/ -v -k test_stream_completion_passes_redis
```

Expected: FAIL with `RuntimeError: NanoGptHttpAdapter requires a Redis client` (because the adapter is constructed bare).

- [ ] **Step 4: Apply the plumbing**

In `backend/modules/llm/__init__.py`, replace:

```python
adapter = adapter_cls()
```

with:

```python
adapter = _instantiate_adapter(adapter_cls, get_redis())
```

Add the import at the top of the file:

```python
from backend.modules.llm._registry import get_adapter_class, _instantiate_adapter
```

(Merge with any existing import from `_registry` — today the file imports only `get_adapter_class`.)

- [ ] **Step 5: Run the full LLM test suite**

```bash
uv run pytest backend/tests/modules/llm/ -v
```

Expected: all tests PASS — the new integration test plus every existing test.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/__init__.py \
        backend/tests/modules/llm/   # whichever file got the new test
git commit -m "Plumb Redis through llm.stream_completion via _instantiate_adapter"
```

---

### Task 4: Full verification + merge to master

**Files:** none modified.

- [ ] **Step 1: Full backend test suite**

```bash
cd /home/chris/workspace/chatsune && uv run pytest backend/ shared/ 2>&1 | tail -40
```

Expected: all tests PASS, no unexpected skips.

- [ ] **Step 2: Compile check for every modified module**

```bash
uv run python -m py_compile \
    backend/modules/llm/_adapters/_nano_gpt_http.py \
    backend/modules/llm/__init__.py
```

Expected: no errors.

- [ ] **Step 3: Grep for forbidden bodies**

Confirm no `reasoning` / `thinking` flag sneaked into the nano-gpt payload:

```bash
rg -n "'reasoning'|\"reasoning\"|think" backend/modules/llm/_adapters/_nano_gpt_http.py
```

Expected: only occurrences are in comments/docstrings or in `delta.get("reasoning_content")` (the *response*-side reasoning field, which is exactly what xAI and Mistral also read). **No** `payload["reasoning"] = ...` or similar body field.

- [ ] **Step 4: Manual verification steps (to run at end of session, Chris)**

1. `docker compose up -d` and verify backend starts cleanly (`docker logs chatsune-backend | tail`). No startup errors.
2. In the frontend, pick a nano-gpt model, send a prompt, confirm tokens stream in. Try both reasoning-on and reasoning-off for a dual-slug model (e.g. Claude Opus 4.6).
3. Try a model that exists in upstream but **not** in the user's cached pair map (e.g. refresh with a subset, then request an old one) → expect a clean "model_not_found" error in the UI.
4. `redis-cli keys 'nano_gpt:pair_map:*'` — expect at least one key after `fetch_models` has run.

- [ ] **Step 5: Merge to master**

```bash
git checkout master
git merge --no-ff nano-gpt-stream-completion -m "Merge branch 'nano-gpt-stream-completion'"
```

Per Chris' project CLAUDE.md: "Please always merge to master after implementation."

---

## Self-Review Checklist

**1. Spec coverage** — every point in the briefing has a task?

- ✅ Pair-Map aus Redis laden (helper load_pair_map) — Task 2 Step 4
- ✅ Upstream-Slug aus pair["thinking_slug"] bzw pair["non_thinking_slug"] — Task 2 Step 4 (`_pick_upstream_slug`)
- ✅ Kein reasoning/thinking-Flag im Request-Body — Task 1 Step 6 + Task 4 Step 3 (grep check)
- ✅ SSE-Loop analog xAI, OpenAI-kompatibel — Task 1 (helpers) + Task 2 Step 4 (loop)
- ✅ Gutter-Timer — Task 2 Step 4 (same structure as xAI)
- ✅ ThinkingDelta aus `delta.reasoning_content` — Task 1 Step 3 (`_chunk_to_events` tests)
- ✅ Error-Mapping 401/500 — Task 2 Step 2 + Step 4
- ✅ ~150-200 LOC — SSE helpers (~100) + stream_completion (~120) ≈ 220 LOC; close enough

**2. Placeholder scan** — any TBD/TODO/"similar to Task X"?

- None. Every task has full code or explicit diff instructions.

**3. Type consistency**

- `_pick_upstream_slug` signature identical in Task 2 Step 1 tests and Step 4 implementation.
- `_build_chat_payload(request, upstream_slug)` — 2-arg signature referenced only inside Task 2 Step 4, no drift.
- `pair_map` shape matches what `save_pair_map` / `load_pair_map` in `_nano_gpt_pair_map.py` already persist: `dict[str, dict[str, str | None]]`.

**4. Redis plumbing consistency**

- `_instantiate_adapter(adapter_cls, get_redis())` is the same pattern `_metadata.py` already uses. No new abstraction introduced.

---

## Execution Handoff

**Plan saved.** Subagent-Driven Execution via `superpowers:subagent-driven-development` per Chris' standing preference (global: "Subagent preferred", project: "subagent driven implementation always").

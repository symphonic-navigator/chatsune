# xAI / Grok Adapter (`xai_http`)

**Status:** Approved (brainstorming)
**Date:** 2026-04-20

## Goal

Add a new LLM adapter `xai_http` that exposes **Grok 4.1 Fast** (both the
reasoning and non-reasoning variants) as a single logical model to the
Chatsune chat stack. The adapter talks to xAI's OpenAI-compatible Chat
Completions API at `https://api.x.ai/v1/chat/completions`, supports the full
feature matrix (vision, tool calls, streaming, reasoning), and hides xAI's
provider idiosyncrasies inside the adapter boundary so the rest of the system
stays unchanged.

## Motivation

- xAI offers Grok 4.1 Fast at pricing that undercuts a subscription even for
  heavy users (0.05 / 0.20 / 0.50 per million input / cached input / output
  tokens as of 2026-04). Integrating it widens the set of useful providers
  for BYOK users.
- It is also a clean test case for our adapter architecture: xAI splits
  reasoning and non-reasoning into two upstream model IDs and uses an
  unconventional cache-hint header — if the adapter layer can absorb both
  quirks in one file without touching the chat flow, the boundaries are
  working as designed.

## Non-goals

- **xAI Responses API.** Its server-side `web_search` is attractive, but it
  conflicts with our own context management and our pluggable `websearch`
  module. Revisit as a separate spec if Grok's native search proves
  materially better than our adapter-agnostic tool.
- **Raw `/v1/completions` (generate-text).** No roles, no tools, no vision;
  would break our entire message-based stack. Not considered.
- **Other Grok models** (Grok 3, Grok 4, Grok 4.20, `grok-code-fast-1`,
  `grok-imagine-*`). The adapter's `fetch_models` hard-codes a single DTO for
  now. Adding further models later is a one-line extension.
- **Cache-hit token telemetry** — captured but not surfaced yet, see
  INS-024 (follow-up iteration).

## Design

### 1. Contract change — `shared/dtos/inference.py`

Single new field on `CompletionRequest`:

```python
cache_hint: str | None = None
# Opaque, provider-specific cache locality hint. Adapters that support
# upstream cache locality (currently only xai_http) translate this into a
# provider header; others ignore it.
```

No other shared contract changes.

### 2. Chat orchestrator — one new line

In `backend/modules/chat/_orchestrator.py` (or wherever `CompletionRequest`
is constructed for inference), pass the current chat session UUID as a
string through the new field:

```python
cache_hint=str(chat_session_id)
```

That is the full change on the chat side.

### 3. New adapter — `backend/modules/llm/_adapters/_xai_http.py`

```
class XaiHttpAdapter(BaseAdapter):
    adapter_type  = "xai_http"
    display_name  = "xAI / Grok"
    view_id       = "xai_http"
    secret_fields = frozenset({"api_key"})
```

#### 3.1 Templates and config

Single template `"xAI Cloud"` with:

- `url`: `https://api.x.ai/v1` (editable — users can point at regional
  endpoints or a proxy if they ever need to; xAI itself routes optimally
  without manual selection)
- `api_key`: required, stored encrypted via the `secret_fields` mechanism
- `max_parallel`: default `4` (xAI's current limits are 1,800 RPM /
  10M TPM per account — four concurrent in-flight requests is well inside
  that, with huge headroom)

`config_schema()` returns the usual hints: text URL, password API key,
integer `max_parallel` (1..50).

#### 3.2 `fetch_models()` — hard-coded, single entry

Returns one `ModelMetaDto`:

```python
ModelMetaDto(
    connection_id=...,              # from resolver
    connection_slug=...,            # from resolver
    connection_display_name=...,    # from resolver
    model_id="grok-4.1-fast",
    display_name="Grok 4.1 Fast",
    context_window=200_000,         # capped; upstream would allow 2M but
                                    # pricing changes above 200K
    supports_reasoning=True,
    supports_vision=True,
    supports_tool_calls=True,
)
```

No upstream `GET /v1/models` roundtrip for the model list. The metadata is
shaped by our product decision (expose both reasoning variants as one
toggleable model), not by xAI's raw listing.

#### 3.3 `stream_completion()`

##### Upstream model selection

```python
model_slug = (
    "grok-4-1-fast-reasoning"
    if request.reasoning_enabled
    else "grok-4-1-fast-non-reasoning"
)
```

Chat flow is unaware of the split. The reasoning toggle in the UI already
drives `request.reasoning_enabled`; all we do is map that bool to one of two
upstream IDs. xAI's cache is shared across both IDs when prefixes match
(confirmed empirically via grok.com TTFT observations), so toggling does
not force a cold start.

##### Request payload

```python
payload = {
    "model": model_slug,
    "stream": True,
    "messages": [_translate_message(m) for m in request.messages],
    "temperature": request.temperature,
}
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
```

##### Headers

```python
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}",
}
if request.cache_hint:
    headers["x-grok-conv-id"] = request.cache_hint
```

Prefix invalidation is safe: if the prompt prefix changes (system-prompt
tweak, memory updated, persona edited), xAI still checks the actual prefix
and simply misses the cache for that request. No error, just a cold call.
This matches our no-wipe data-model rules — we can keep evolving the
PromptAssembler freely.

##### Content-part translation

```python
# ContentPart(type="text", text="...")
#   → {"type": "text", "text": "..."}
# ContentPart(type="data", data=<b64>, media_type="image/png")
#   → {"type": "image_url",
#      "image_url": {"url": f"data:{media_type};base64,{b64}"}}
```

Assistant messages with `tool_calls` and `role="tool"` messages with
`tool_call_id` are already OpenAI-compatible in our `CompletionMessage`
model — pass through unchanged.

#### 3.4 SSE response parsing

```
Content-Type: text/event-stream
Data lines: data: {json}\n\n
Terminal:   data: [DONE]\n\n
```

Use `httpx.AsyncClient.stream("POST", ...)` + `aiter_lines()`, strip the
`data: ` prefix, parse JSON. Empty lines delimit events.

#### 3.5 Delta → `ProviderStreamEvent` mapping

Expected chunk shape (OpenAI-compatible):

```json
{
  "choices": [{
    "delta": {"content": "...", "reasoning_content": "..."},
    "finish_reason": null
  }],
  "usage": null
}
```

| Upstream                                         | Emitted event                                            |
| ------------------------------------------------ | -------------------------------------------------------- |
| `delta.content` non-empty                        | `ContentDelta(delta=...)`                                |
| `delta.reasoning_content` non-empty              | `ThinkingDelta(delta=...)`                               |
| `delta.tool_calls[]` fragments                   | Accumulate; see §3.6                                     |
| `finish_reason="stop"` + final `usage`           | `StreamDone(input_tokens, output_tokens)`                |
| `finish_reason="tool_calls"`                     | Emit accumulated `ToolCallEvent`s, then `StreamDone`     |
| `finish_reason="length"`                         | `StreamDone` (context-fill signalled via chat status)    |
| `finish_reason="content_filter"`                 | `StreamRefused(reason, refusal_text)`                    |

**Verify at implementation time**, via the LLM harness: the exact field name
for reasoning output. Assumption is `reasoning_content` (OpenAI-o1 /
DeepSeek convention). Five-minute test against `grok-4-1-fast-reasoning`
confirms or corrects. If the field is different, adjust only §3.5 — no
other code changes.

#### 3.6 Tool-call fragment accumulation

Unlike Ollama (whole tool call in one chunk), xAI streams tool calls
OpenAI-style fragmented:

```
chunk 1: tool_calls=[{index:0, id:"call_abc",
                      function:{name:"web_search"}}]
chunk 2: tool_calls=[{index:0, function:{arguments:"{\"query\":"}}]
chunk 3: tool_calls=[{index:0, function:{arguments:"\"grok\"}"}}]
final:   finish_reason="tool_calls"
```

Adapter holds local state:

```python
accumulator: dict[int, dict] = {}  # indexed by upstream tool_calls[].index
# Each value accumulates id, name, and an args string buffer.
```

At `finish_reason="tool_calls"`, for each entry emit
`ToolCallEvent(id, name, arguments=json.loads(args_buffer))`, then
`StreamDone`.

#### 3.7 Gutter timer and error handling

Idle-detection timer mirrors `ollama_http`:

- 30 s without upstream data → `StreamSlow`
- A further 120 s → `StreamAborted`

HTTP error mapping:

| Status                  | Event                                                      |
| ----------------------- | ---------------------------------------------------------- |
| 401                     | `StreamError(error_code="auth_failed", recoverable=False)` |
| 429                     | `StreamError(error_code="rate_limited", recoverable=True)` |
| other 4xx               | `StreamError(error_code="bad_request", message=<body>)`    |
| 5xx                     | `StreamError(error_code="provider_error", recoverable=True)` |
| network timeout         | Handled by the gutter timer path                           |

#### 3.8 Usage tokens

xAI returns `usage.prompt_tokens` / `usage.completion_tokens` on the final
chunk. Forwarded as `StreamDone(input_tokens, output_tokens)`.

`usage.prompt_tokens_details.cached_tokens` is **captured in local logs
only**, not surfaced via the event contract. Promoted to the event in a
follow-up iteration — see INS-024.

#### 3.9 Sub-router — `POST /test`

Mounted at `/api/llm/connections/{connection_id}/adapter/test`. Handler
performs `GET https://api.x.ai/v1/models` with the connection's bearer
token:

- HTTP 200 → `{valid: true}`, emits `LLM_CONNECTION_UPDATED`
- HTTP 401 → `{valid: false, error: "API key rejected by xAI"}`
- other → `{valid: false, error: <short upstream message>}`

Cost: zero. Matches the pattern of `ollama_http`'s `/test` but without a
separate `/api/me` endpoint.

No other sub-router endpoints in this iteration — no pull, no delete, no
diagnostics. xAI is cloud-only; those concepts don't apply.

### 4. Registry

`backend/modules/llm/_registry.py`:

```python
ADAPTER_REGISTRY = {
    "ollama_http": OllamaHttpAdapter,
    "community": CommunityAdapter,
    "xai_http": XaiHttpAdapter,  # new
}
```

### 5. Frontend

**No changes.** The existing provider wizard, connection list, model picker,
and chat reasoning toggle all render the new adapter automatically from
DTOs (`AdapterDto`, `ConnectionDto`, `ModelMetaDto`).

## Verification

Executed in this order at implementation time:

1. **LLM harness scenarios.** Create `tests/llm_scenarios/
   xai_grok_fast_non_reasoning.json` and `xai_grok_fast_reasoning.json`.
   Key file `.xai-test-key` (plain text, gitignored, analogous to the
   existing `.llm-test-key`). The harness already takes `--key-file` and
   `--base-url`; a small patch is needed to teach it SSE parsing in
   addition to NDJSON — roughly 30 lines in `backend/llm_harness/_runner.py`.
   Primary purposes: verify the `reasoning_content` field name and confirm
   the SSE parser consumes real upstream traffic cleanly.
2. **Connection test.** `POST /api/llm/connections/{id}/adapter/test` with
   a real key returns `{valid: true}`; with an invalid key returns
   `{valid: false}`.
3. **End-to-end tool call.** Open a chat session, attach the new connection,
   enable `web_search`, switch reasoning on, send a query that should
   trigger a web search. Verify: tool-call fragment accumulation emits a
   single clean `ToolCallEvent`, the tool dispatcher runs, and the
   follow-up chunk stream resumes without losing `cache_hint` stickiness
   for subsequent turns.

## Scope / sizing

| Change                                        | Approx. LoC  |
| --------------------------------------------- | ------------ |
| `_xai_http.py` (new)                          | ~400         |
| `_registry.py`                                | +1           |
| `shared/dtos/inference.py` (new field)        | +1           |
| Chat orchestrator (set `cache_hint`)          | +1           |
| LLM harness SSE patch                         | ~30          |
| `tests/llm_scenarios/*.json`                  | 2 files      |
| **Frontend**                                  | **0**        |

One focused PR. No migrations, no DB touch, no shared-contract churn
beyond the single optional field.

## Follow-ups (tracked, not this PR)

- Cache-hit token telemetry surfaced via event contract — INS-024
- Additional Grok models (Grok 3, 4, 4.20, `grok-code-fast-1`) as hard-coded
  DTOs in the same adapter when the need arises
- xAI Responses API + native `web_search` — separate brainstorming, only if
  its benefit over our own `websearch` module becomes material

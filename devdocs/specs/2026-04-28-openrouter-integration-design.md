# OpenRouter Integration — Phase 1 (Text-Only)

**Date:** 2026-04-28
**Status:** Spec for review
**Scope:** Add OpenRouter as the fifth Premium Provider and fourth LLM
adapter, restricted to text generation. Image, audio, and video
modalities are explicitly out of scope for this iteration.

---

## 1. Goal

Let any Chatsune user bring their own OpenRouter API key and route chat
inference through OpenRouter to any of its 50+ upstream providers. The
user's OpenRouter-side privacy guardrails (ZDR, provider exclusions,
free-tier policies) become the single source of truth for which models
appear in the Chatsune Model Browser.

---

## 2. Non-Goals (this iteration)

- Image generation, TTS, STT, ITI via OpenRouter.
- Anthropic-style explicit `cache_control` cache-breakpoint markers.
- Surfacing or controlling `reasoning.effort`.
- A user-facing "Allow moderated" filter (the data is captured, the
  filter UI follows in a later iteration).
- Surfacing or enforcing OpenRouter's per-request limits beyond the
  generic `StreamError` pathway when an upstream returns 429.
- Sharing the OpenAI-compatible SSE parser, tool-call accumulator, and
  gutter-timer code with the existing xAI/Mistral/nano-gpt adapters.
  That refactor is tracked separately and will land in its own session
  once OpenRouter has been added.

---

## 3. Architecture Fit

OpenRouter slots into the existing Premium-Provider + adapter pattern
without introducing new concepts.

### 3.1 Files to create

- `backend/modules/llm/_adapters/_openrouter_http.py` — adapter
  implementation. Structurally a Mistral clone (OpenAI-compatible chat
  completions, dedicated tool-call accumulator, gutter timer). Estimated
  ~500 LOC.

### 3.2 Files to modify

- `backend/modules/providers/_registry.py` — register the
  `openrouter` Premium Provider definition.
- `backend/modules/llm/_adapters/__init__.py` — re-export
  `OpenRouterHttpAdapter`.
- `backend/modules/llm/_registry.py` — add to `_PREMIUM_ONLY_ADAPTERS`
  (premium-only, never user-creatable as a standalone Connection).
- `backend/modules/llm/_resolver.py` — extend `_PREMIUM_ADAPTER_TYPE`
  with `"openrouter": "openrouter_http"`.
- `shared/dtos/llm.py` — add `is_moderated: bool | None = None` to
  `ModelMetaDto`.
- `INSIGHTS.md` — append `INS-032` (OpenRouter caching note).

### 3.3 No frontend changes in this iteration

- The Premium-Provider settings UI renders generically from the registry
  entry — no new view component needed.
- No provider icon assets are added (Chatsune does not currently render
  upstream-provider logos anywhere).
- The Model Browser already handles `billing_category` and capability
  flags generically.

### 3.4 Data flow (identical to Mistral / xAI / nano-gpt)

```
1. User saves OpenRouter API key in Settings → Premium Providers.
   The key is encrypted at rest by PremiumProviderService.

2. Model Browser fetches available models:
   resolver.resolve_premium_for_listing("openrouter") synthesises a
   ResolvedConnection with id="premium:openrouter", base_url from the
   registry, and the decrypted api_key.
   adapter.fetch_models(c) → GET /api/v1/models/user?output_modalities=text
   → list[ModelMetaDto] with billing_category, is_moderated, etc.

3. User starts a chat with model_unique_id="openrouter:<model_id>"
   (e.g. "openrouter:anthropic/claude-3-5-sonnet").
   resolver.resolve_for_model splits at first ":" → prefix="openrouter"
   → Premium-Provider path → ResolvedConnection.
   adapter.stream_completion(c, request) → POST /api/v1/chat/completions
   (stream=true) → AsyncIterator[ProviderStreamEvent].
```

The `partition(":")` semantics in the resolver split at the first colon
only, so OpenRouter model IDs containing extra colons (e.g.
`openrouter:nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`) round-trip
correctly: prefix=`openrouter`, model_id=`nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`.

---

## 4. Premium-Provider Registry Entry

In `backend/modules/providers/_registry.py`, alongside the existing
`xai`, `mistral`, `ollama_cloud`, and `nano_gpt` entries:

```python
register(PremiumProviderDefinition(
    id="openrouter",
    display_name="OpenRouter",
    icon="openrouter",
    base_url="https://openrouter.ai/api/v1",
    capabilities=[Capability.LLM],
    config_fields=[_api_key_field("OpenRouter API Key")],
    probe_url="https://openrouter.ai/api/v1/models/user?output_modalities=text",
    probe_method="GET",
    linked_integrations=[],
))
```

**Choices:**

- `capabilities=[Capability.LLM]` — text generation only. Other
  capabilities (TTS / STT / TTI / ITI) are intentionally omitted; we
  add them when we cross those bridges.
- `probe_url` points at `/models/user`, **not** `/models`. The
  authenticated endpoint returns 401 for an invalid key, which is what
  we want from a probe; the public `/models` endpoint would happily
  accept any key string and falsely report "valid".
- `linked_integrations=[]` — no companion voice integration (unlike
  xAI / Mistral).
- `icon="openrouter"` — string is required by the `Definition` model;
  no asset is shipped in this iteration.

---

## 5. Adapter Implementation

`backend/modules/llm/_adapters/_openrouter_http.py`. Structurally
cloned from `_mistral_http.py` with the differences below.

### 5.1 Class identity

```python
class OpenRouterHttpAdapter(BaseAdapter):
    adapter_type = "openrouter_http"
    display_name = "OpenRouter"
    view_id = "openrouter_http"
    secret_fields = frozenset({"api_key"})
```

Registered in `_PREMIUM_ONLY_ADAPTERS` (not in `ADAPTER_REGISTRY`),
keeping it premium-only.

### 5.2 `fetch_models(c)`

1. `GET {base_url}/models/user?output_modalities=text` with
   `Authorization: Bearer {api_key}`.
2. Map status codes:
   - `401` / `403` → log a warning and return `[]` (matches Mistral).
   - non-200 → log and return `[]`.
3. Parse `data[]` and map each entry:

   | Source field | → | `ModelMetaDto` field |
   |---|---|---|
   | `id` | → | `model_id` (kept verbatim, may contain `:free` and `/`) |
   | `name` | → | `display_name` |
   | `context_length` | → | `context_window` |
   | `"image" in architecture.input_modalities` | → | `supports_vision` |
   | `"reasoning" in supported_parameters` ∨ `"include_reasoning" in supported_parameters` | → | `supports_reasoning` |
   | `"tools" in supported_parameters` | → | `supports_tool_calls` |
   | `top_provider.is_moderated` (`bool` or missing) | → | `is_moderated` (set explicitly when present, else `None`) |
   | `expiration_date is not None` | → | `is_deprecated` |
   | `pricing.prompt == "0" ∧ pricing.completion == "0"` | → | `billing_category = "free"` |
   | otherwise | → | `billing_category = "pay_per_token"` |

4. **Defensive client-side filter:** drop entries whose
   `architecture.output_modalities` is missing or not equal to
   `["text"]`. Belt-and-braces in case `?output_modalities=text` is
   ever loosened upstream; image-only or audio-only output models must
   not appear in this iteration.
5. No deduplication is required — OpenRouter does not use `-latest`
   aliases the way Mistral does; every `id` is canonical.

### 5.3 `stream_completion(c, request)`

`POST {base_url}/chat/completions` with `stream=true`. Body shape and
headers match Mistral's helper, with these adjustments:

- **Headers:**
  - `Authorization: Bearer {api_key}` (required).
  - `HTTP-Referer: https://chatsune.app` (OpenRouter attribution;
    polite, helps OR usage analytics).
  - `X-Title: Chatsune` (same purpose).
  - `Content-Type: application/json`.
- **Body fields beyond Mistral parity:**
  - `stream_options: {"include_usage": true}` so token counts arrive
    in the terminal usage chunk.
  - `reasoning` field, conditional on the request (see 5.4).
  - **No** `cache_control` markers anywhere in the message blocks — see
    INSIGHTS-032.

### 5.4 Reasoning handling

OpenRouter exposes a `reasoning` parameter whose semantics differ by
upstream model. Chatsune's `CompletionRequest` only carries an on/off
toggle (`reasoning_enabled`) and a capability flag
(`supports_reasoning`); we do not surface effort levels in this
iteration.

The adapter emits the `reasoning` field only when meaningful:

| `supports_reasoning` | `reasoning_enabled` | Body emits |
|---|---|---|
| `True` | `True` | _no `reasoning` field_ (provider default) |
| `True` | `False` | `"reasoning": {"exclude": true}` |
| `False` | _any_ | _no `reasoning` field_ |

**Caveat to document inline:** "exclude" controls **visibility** of the
thinking stream, not whether the model actually reasons. Models with
reasoning baked into the architecture (e.g. DeepSeek R1) ignore
`exclude: true` and stream thinking deltas anyway. This is acceptable
behaviour — Chatsune already renders thinking deltas correctly when
they arrive.

### 5.5 SSE parser

Cloned from `_mistral_http.py` `_chunk_to_events`, with one extension:

- `delta.reasoning_content` (OpenAI convention) → `ThinkingDelta`
  (already present in the Mistral parser).
- `delta.reasoning` (OpenRouter normalisation) → `ThinkingDelta` (new
  branch).

Tool-call accumulator, refusal handling (`finish_reason in
{"content_filter", "refusal"}` → `StreamRefused`), terminal usage chunk
emitting `StreamDone` with token counts, and the gutter timer
(`GUTTER_SLOW_SECONDS`, `GUTTER_ABORT_SECONDS`) are all carried over
verbatim from Mistral.

### 5.6 Error mapping

| Upstream status | → | Stream event |
|---|---|---|
| `401`, `403` | → | `StreamError(error_code="invalid_api_key", message="OpenRouter rejected the API key")` |
| `429` | → | `StreamError(error_code="provider_unavailable", message="OpenRouter rate limit hit")` |
| other non-200 | → | `StreamError(error_code="provider_unavailable", message=f"OpenRouter returned {status}: {body[:500]}")` |
| transport error | → | `StreamError(error_code="provider_unavailable", message="Cannot connect to OpenRouter")` |

### 5.7 Sub-router (`/test`)

Implemented analogously to xAI's adapter sub-router:

```python
@classmethod
def router(cls) -> APIRouter:
    return _build_adapter_router()  # mounts POST /test
```

The `POST /test` handler invokes a probe of `/models/user` with the
`probe` timeout (10 s). A successful 200 with non-empty `data[]`
returns `{"valid": True, "error": None}`; 401/403 returns
`{"valid": False, "error": "OpenRouter rejected the API key"}`; other
errors return `{"valid": False, "error": "<short detail>"}`. The route
is mounted under
`/api/llm/connections/{connection_id}/adapter/test` by the existing
adapter-router infrastructure and reached via the Premium-Provider
settings UI's generic "Test" button.

---

## 6. Schema Change — `is_moderated` on `ModelMetaDto`

In `shared/dtos/llm.py`:

```python
class ModelMetaDto(BaseModel):
    ...
    is_deprecated: bool = False
    billing_category: Literal["free", "subscription", "pay_per_token"] | None = None
    # NEW:
    # ``True``/``False`` when the upstream provider makes an explicit
    # statement (today: only OpenRouter via ``top_provider.is_moderated``).
    # ``None`` = no statement — every other adapter leaves this default.
    # A future "Allow moderated" filter must handle all three buckets
    # (yes / no / unknown) sensibly.
    is_moderated: bool | None = None
```

### 6.1 Migration / backwards compatibility

- **No DB wipe.** Conforms to CLAUDE.md §Data-Model Migrations: a new
  optional field with `None` default deserialises pre-existing cached
  documents cleanly.
- **No index changes.**
- **Cache:** `ModelMetaDto` is cached per-Connection in Redis (30 min
  TTL). Stale entries deserialise as `is_moderated=None`, which is the
  semantically correct default for adapters that don't report the flag.
  After cache expiry the new field is populated for OpenRouter and
  remains `None` for all other adapters.
- **Other adapters touched:** none. xAI, Mistral, Nano-GPT, Ollama,
  and Community do not set `is_moderated` — `None` is correct.

---

## 7. INSIGHTS.md Entry — `INS-032`

Append to `INSIGHTS.md`:

> ## INS-032 — OpenRouter prompt caching is per-provider, not uniform (2026-04-28)
>
> **Context:** OpenRouter routes to 50+ upstream providers, each with a
> different caching story:
> - **OpenAI / Gemini / DeepSeek models** — automatic prefix caching
>   above ~1024 tokens. No marker needed, transparent savings. (List
>   grows empirically; validated via the OpenRouter dashboard.)
> - **Anthropic models** — require explicit
>   `cache_control: {type: "ephemeral"}` markers on individual
>   message-content blocks (typically system prompt and long tool
>   definitions). Without markers, every turn pays full token price.
> - **Others (Llama, Mistral on OR, etc.)** — usually no caching.
>
> **Phase-1 decision:** Pass-through with no `cache_control` markers.
> OpenAI / Gemini / DeepSeek auto-caching covers an estimated 80% of
> realistic Chatsune traffic; Anthropic models run uncached.
>
> **What testers must know:** users who route mostly to Claude through
> OpenRouter will see no cache savings until we ship marker support.
> Iterate on real usage data before optimising.
>
> **Why not implement markers now:** `cache_control` belongs at the
> content-block level inside chat messages, not on the message itself.
> Adding it to OpenRouter's `_translate_message` path would either
> require an OR-specific message translator (more code, more
> divergence from Mistral / xAI / nano-gpt) or a parameter on the
> shared `CompletionMessage` model that every other adapter ignores.
> Both are non-trivial; deferring until we have usage data justifying
> the work.

---

## 8. Tests

### 8.1 Unit tests (Python, pytest)

In `backend/modules/llm/tests/test_openrouter_http.py`:

1. **`test_openrouter_fetch_models_maps_fields_correctly`** — fixture
   from a real `/models/user` response; assert all mapping rules
   including `:free` → `billing_category="free"`,
   `top_provider.is_moderated` → `is_moderated`, `input_modalities`
   containing `"image"` → `supports_vision`, `supported_parameters`
   containing `"tools"` → `supports_tool_calls`, etc.
2. **`test_openrouter_fetch_models_filters_non_text_output`** — fixture
   includes a model with `output_modalities=["image"]` → assertion that
   it is dropped from the result.
3. **`test_openrouter_fetch_models_401_returns_empty_list`** — mocked
   401 → returns `[]` and emits a warning log.
4. **`test_openrouter_stream_completion_reasoning_field`** — three
   cases (enabled/disabled/no-support) → assert request body shape via
   captured payload.
5. **`test_openrouter_stream_parses_both_reasoning_keys`** — feed a
   chunk with `delta.reasoning` and another with
   `delta.reasoning_content` → both yield a `ThinkingDelta`.
6. **`test_openrouter_test_endpoint_valid_invalid_keys`** — sub-router
   `POST /test` happy path and 401 path.

### 8.2 What is not tested in this iteration

- SSE-line parsing, tool-call accumulation, and gutter-timer behaviour
  are covered by the existing Mistral tests. The OpenRouter adapter
  carries verbatim copies; once the OpenAI-compat extract refactor
  lands, those tests cover OpenRouter for free.

### 8.3 Build commands

```bash
# Backend syntax check
uv run python -m py_compile backend/modules/llm/_adapters/_openrouter_http.py

# Adapter test suite (no Mongo needed — safe to run on host)
uv run pytest backend/modules/llm/tests/test_openrouter_http.py -v
```

The four DB-dependent test files listed in `feedback_db_tests_on_host`
remain excluded from on-host runs.

### 8.4 Frontend build check

Not applicable — no frontend changes.

---

## 9. Manual verification

Run on a real Chatsune instance with a real OpenRouter API key (Chris
will execute these on his dev box). Memory entry
`feedback_manual_test_sections_in_specs` captures that this list is
expected and will be exercised before merge.

1. **Provider entry visible.** Settings → Premium Providers shows an
   OpenRouter card with an "API Key" field. (Tests: registry, no
   frontend regressions.)
2. **Probe rejects invalid key.** Enter a random string → "Test"
   button → red status with a 401-shaped error. (Tests: probe URL
   targets `/models/user`, not `/models`.)
3. **Probe accepts valid key.** Enter a real OR key → "Test" → green.
4. **Model Browser populates.** With the key saved, Model Browser
   shows OpenAI, Gemini, Anthropic, DeepSeek, Llama, etc. families
   under the OpenRouter connection. (Tests: `fetch_models`.)
5. **Privacy guardrails honoured.** Toggle the "ZDR-only" policy in
   the OpenRouter dashboard, refresh Chatsune's Model Browser → list
   shrinks visibly. (Tests: we are calling `/models/user` with the
   key, not the public `/models`.)
6. **Output-modality filter works.** No image-only or audio-only
   model appears in the list. (Tests: query param + defensive
   client-side filter.)
7. **Inference with a default model.** Start a chat with
   `openai/gpt-4o` → tokens stream, terminal `StreamDone` carries
   token counts, no errors.
8. **Reasoning toggle off, R1 model.** Chat with
   `deepseek/deepseek-r1`, reasoning toggle off → either no thinking
   stream (model honours `exclude: true`) **or** thinking stream
   appears anyway (built-in reasoner ignores it). Both are
   acceptable; second case proves we don't crash.
9. **Reasoning toggle on, optional-reasoner.** Chat with a model that
   supports optional reasoning (e.g. an Anthropic 3.7 variant if
   available), toggle on → thinking pills appear.
10. **Tool call.** Pick a model with `supports_tool_calls=true` and
    run an MCP tool round-trip (existing PTI flow). Tool call → tool
    result → final assistant message all stream correctly.
11. **Vision.** Upload an image to a `supports_vision=true` model
    (e.g. `openai/gpt-4o`) and ask about it. (Tests:
    `_translate_message` image path.)
12. **Free-model rate limit.** Hammer a `:free` variant in quick
    succession → eventual 429 → user sees "OpenRouter rate limit
    hit" as a stream error event in the chat (recoverable).

---

## 10. Open questions

None at the time of writing. All design choices have been agreed in
the brainstorming session preceding this spec.

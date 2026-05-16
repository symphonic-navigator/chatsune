# Chutes AI Integration — Design

**Date:** 2026-05-16
**Status:** Draft, awaiting review
**Scope:** First-cut integration of Chutes AI as a BYOK LLM provider, exposing only TEE (Trusted Execution Environment) models as Chatsune's "ultra privacy" inference option.

---

## 1. Context

Chutes AI is a Bittensor SN64-hosted inference aggregator that runs a wide range of LLMs behind an OpenAI-compatible API. A significant subset of their flagship models run inside Intel TDX Trusted Execution Environments, where prompts and responses are hardware-isolated even from Chutes operators themselves. SCAI (the NGO behind Chatsune) is entering into a formal partnership with Chutes — making them a natural fit for Chatsune's privacy-first positioning.

The integration uses Chutes' OpenAI-compatible inference endpoint and relies on their model-metadata response rather than hand-curated per-model handling. This keeps the integration thin and lets Chutes' own catalogue drive what users see.

Reference notes captured prior to this spec live in `CHUTES.md` at the repo root.

## 2. Goals

- Expose Chutes as a user-creatable Connection (BYOK), in line with Chatsune's "BYOK first" principle.
- Surface every Chutes model that satisfies all three criteria: `confidential_compute == true`, `context_length >= 80_000`, and text output. Hide everything else — TEE-only is a hard filter.
- Reuse Chatsune's existing OpenAI-compatible streaming pipeline conventions (SSE, gutter timers, tool-call accumulation, retry, terminal events).
- Ship quickly with low blast radius. No refactor of shared OpenAI-compat helpers in this change.

## 3. Non-Goals

- **First-class model curating.** No driver hooks, no per-model overrides, no hardcoded model list. Capabilities derive purely from Chutes' `supported_features` and `input_modalities`.
- **Routing syntax** (`modelA,modelB,modelC:latency`, `default:throughput`, etc.). Pass-through only via the regular `model` field; no virtual entries in the picker. Tracked separately.
- **Cache-pricing display**, `chute_id` cost tracking, attestation evidence, quantisation/engine metadata. Out of scope; revisit after MVP.
- **Research-data opt-in proxy** (`research-data-opt-in-proxy.chutes.ai`). Logs prompts. Never exposed.
- **Premium Provider (admin-managed shared key) path.** BYOK only for now. If a partnership-level shared key becomes appropriate later, the same adapter class can be added to `_PREMIUM_ONLY_ADAPTERS` without code changes.
- **Generic TEE badge** in the model browser. With Chutes the entire connection is TEE-only, so the connection display name already carries the signal. A cross-provider TEE flag in `ModelMetaDto` can be added later if a second TEE source materialises.

## 4. Architecture

### 4.1 Backend module placement

New file: `backend/modules/llm/_adapters/_chutes_http.py`. Structurally a slimmed-down clone of `_openrouter_http.py`. No shared-helper extraction — that refactor is tracked separately and is out of scope here.

Registry change in `backend/modules/llm/_registry.py`:

```python
ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = {
    "ollama_http": OllamaHttpAdapter,
    "community": CommunityAdapter,
    "chutes_http": ChutesHttpAdapter,   # added
}
```

`chutes_http` lives in the user-facing registry, not `_PREMIUM_ONLY_ADAPTERS`. Users create their own Connection with their own `cpk_...` key.

### 4.2 Adapter class attributes

| Attribute | Value |
|---|---|
| `adapter_type` | `"chutes_http"` |
| `display_name` | `"Chutes AI"` |
| `view_id` | `"chutes_http"` |
| `secret_fields` | `frozenset({"api_key"})` |
| `supports_image_generation` | `False` (default) |

### 4.3 Hardcoded endpoints

The adapter does not expose a `url` config field. Chutes runs a single public managed endpoint with no self-host alternative, so making the URL configurable would be ceremony without value.

| Purpose | URL | Used by |
|---|---|---|
| Inference + model discovery | `https://llm.chutes.ai/v1` | `fetch_models`, `stream_completion` |
| Account / key validation | `https://api.chutes.ai` | `/test` sub-router |

If Chutes ever introduces a self-host or enterprise endpoint that needs overriding, adding a `url` field at that point is a backwards-compatible change (existing documents simply pick up the new default).

### 4.4 Connection template

A single wizard template, `"Chutes AI (TEE-only)"`, with `required_config_fields = ["api_key"]`. No other variants.

### 4.5 Frontend view

New file: `frontend/src/app/components/llm-providers/adapter-views/ChutesHttpView.tsx`. Structurally derived from `CommunityView`, reduced to a single `api_key` field with the `is_set` / clear-saved-key pattern used elsewhere.

UI texts (hardcoded in the view, British English per project convention):
- Label: `API-Key`
- Empty placeholder: `cpk_…`
- Saved-state placeholder: `••••••••  (leave empty to keep)`
- Helper text: `Get a Chutes API-Key from chutes.ai. Only models running in a Trusted Execution Environment (TEE) appear in the picker — your prompts are hardware-isolated and even Chutes operators cannot read them.`

Registry update in `frontend/src/core/adapters/AdapterViewRegistry.tsx`:

```tsx
import { ChutesHttpView } from '../../app/components/llm-providers/adapter-views/ChutesHttpView'

export const ADAPTER_VIEW_REGISTRY = {
  ollama_http: OllamaHttpView,
  community: CommunityView,
  xai_http: XaiHttpView,
  chutes_http: ChutesHttpView,
}
```

## 5. Model Discovery

### 5.1 Fetch path

`fetch_models(connection)` calls `GET https://llm.chutes.ai/v1/models` with header `Authorization: Bearer <cpk_...>`. The endpoint is public — sending the key is consistent and harmless. Pagination follows Chutes' `page=0, limit=25` convention; we walk pages until the returned page contains fewer than `limit` entries or zero entries.

### 5.2 Filter — TEE-only and ≥80k context

Each entry from the catalogue passes only if all three predicates hold. Order chosen to fail fast and keep the log signal clean:

1. `entry.get("confidential_compute") is True` — the TEE hard-gate. The `-TEE` suffix in `id` is convention, not contract; trust the flag.
2. `entry.get("context_length") >= 80_000` — mirrors the OpenRouter / nano-gpt `MIN_CONTEXT_TOKENS` floor in the codebase. Chats grow long once journals and tool definitions accumulate; sub-80k models leave no headroom.
3. `entry.get("output_modalities") == ["text"]` — image-only, audio-only, and mixed-output models are out of scope for Phase 1. (Per `CHUTES.md`, Chutes exposes `output_modalities` at the top level of each catalogue entry, not nested under `architecture` as OpenRouter does. If the field is missing on an entry it is treated as not-text-only and skipped.)

The non-TEE Chutes models are legacy slugs kept alive for users with old configurations — confirmed directly by Chutes' lead. Hiding them is the correct default.

### 5.3 Mapping to `ModelMetaDto`

| Chutes field | `ModelMetaDto` field |
|---|---|
| `id` | `model_id` |
| `id` (fallback for missing `name`) | `display_name` |
| `context_length` | `context_window` |
| `"tools" in supported_features` | `supports_tool_calls` |
| `"image" in input_modalities` | `supports_vision` |
| `"reasoning" in supported_features` | `ReasoningCapability(kind="optional")` else `ReasoningCapability(kind="no_reasoning")` |
| `pricing.prompt == "0"` (or numeric zero) | `billing_category = "free"`, else `"pay_per_token"` |

`connection_id`, `connection_slug`, `connection_display_name` are populated from the `ResolvedConnection`. `is_deprecated` stays `False` (Chutes has no explicit deprecation field today); `is_moderated` stays `None` (Chutes adds no censorship, per their lead's statement, but we do not assert `False` either since this is not a structured catalogue field).

### 5.4 Capability resolution

Capabilities pass through `backend.modules.llm._capabilities.resolve_capabilities(adapter_type, model_id, adapter=self)`, matching the OpenRouter pattern. The adapter's `capability_hint(model_id)` returns a `CapabilityHint` with `first_class_support=False` — heuristic, not curated. Reasoning becomes `optional` when `"reasoning"` appears in `supported_features`; otherwise `no_reasoning`. Tools follow `"tools" in supported_features`.

To enable the heuristic the adapter stashes the per-model `supported_features` list on `self._features_by_model_id` during `_entry_to_meta`, identical to OpenRouter's `_params_by_model_id` pattern. The adapter also stashes the per-model `supported_sampling_parameters` whitelist on `self._sampling_params_by_model_id`, used at request-build time for drift-resistant payload filtering (see §6.1).

### 5.5 Caching

`fetch_models` results are cached in Redis for 30 minutes by the generic Connection layer — the adapter itself does no caching.

## 6. Streaming

### 6.1 Request body

`build_request_body(request)` produces:

```python
{
    "model": request.model,
    "stream": True,
    "stream_options": {"include_usage": True},
    "messages": [_translate_message(m) for m in request.messages],
    # optional, included only when present in the request:
    "temperature": request.temperature,
    "tools": [...],                              # if request.tools and request.extras.tools_enabled
    "reasoning_effort": request.extras.reasoning_effort,  # see below
}
```

Reasoning rules:
- `request.reasoning.kind == "optional"` and `request.extras.reasoning_mode == "on"`: send `reasoning_effort` using the OpenAI-standard values (`low`/`medium`/`high`). This is the most common convention across the OpenAI-compat / vLLM / SGLang landscape that Chutes runs.
- `reasoning_mode == "off"`: omit `reasoning_effort` entirely.
- Other `reasoning.kind` values (`no_reasoning`, `always_on`): omit. The backend either does not support the toggle or has no effort axis.

**Drift-resistance via `supported_sampling_parameters`.** Chutes' catalogue gives each model a `supported_sampling_parameters` whitelist (vLLM and SGLang accept different parameter sets, and individual models further narrow that). The build path stashes this whitelist alongside `supported_features` during `_entry_to_meta`, and immediately before sending the request body the adapter filters out any keys not present in the whitelist for the chosen model. This applies to `temperature`, `reasoning_effort`, and any other non-mandatory sampling parameter. Required fields (`model`, `messages`, `stream`, `stream_options`, `tools`) are not filtered. Effect: we ship the common-case body shape and let the per-model whitelist quietly drop fields the engine cannot consume, so model drift never causes a hard 400.

If a model later requires a fundamentally different reasoning shape (e.g. `reasoning: {enabled, effort}` instead of `reasoning_effort`), a Driver handles it. None planned for MVP.

### 6.2 Message translation

`_translate_message(msg)`:
- Plain text: send as a string when the message has only text parts. More cache-friendly for the backend's prefix caching.
- Mixed or image content: send as the OpenAI `[{type: "text"|"image_url", ...}]` array. Image parts are embedded as `data:<media_type>;base64,<data>` URLs.
- `tool_calls` and `tool_call_id` are preserved unchanged.

Anthropic `cache_control` markers are **not** emitted. Chutes is not Anthropic and runs its own prefix caching transparently.

### 6.3 SSE consumption

The SSE consumer mirrors OpenRouter's: `data:` lines parsed as JSON, `[DONE]` sentinel terminates, malformed JSON lines are logged and skipped.

Per-chunk event extraction (`_chunk_to_events`) produces:
- `ThinkingDelta` from `delta.reasoning_content` *or* `delta.reasoning` (both shapes seen across vendors).
- `ContentDelta` from `delta.content`.
- `ToolCallEvent` from finalised accumulator output at `finish_reason == "tool_calls"`.
- `StreamRefused` at `finish_reason in {"refusal", "content_filter"}`. Models themselves emit refusal either via the `refusal` field on the delta (Claude's pattern) or simply as content text — they do not raise `content_filter` for their own decisions. `content_filter` is reserved for platform-level moderation middleware, of which Chutes runs none (confirmed by their lead). We therefore do not expect to see `content_filter` from Chutes in practice; defensively mapping it to `StreamRefused` if it ever appears is harmless and gives the user a clean recoverable error instead of a confusing stop.
- `StreamDone` carrying `prompt_tokens` / `completion_tokens` / `reasoning_tokens` from `usage`. Usage may arrive either in a separate usage-only chunk or attached to the final content chunk; both paths are handled.

The `_ToolCallAccumulator` is identical to OpenRouter's — gathers fragments by `index`, finalises once.

### 6.4 Gutter timers

Same constants and semantics as OpenRouter:
- `GUTTER_SLOW_SECONDS = 30.0` — fire `StreamSlow` once at the 30s idle mark.
- `GUTTER_ABORT_SECONDS` from env `LLM_STREAM_ABORT_SECONDS`, default `120` — emit `StreamAborted(reason="gutter_timeout")` and return.

### 6.5 Retry policy

Same as OpenRouter: `backend._retry.should_retry_status` decides which statuses (429/503) are retriable, `compute_retry_delay` computes the backoff, `parse_retry_after` honours `Retry-After`. Retries happen only *before* the first stream event has been yielded; once content has hit the user's UI, partial-token retries are unsafe.

### 6.6 Header policy

Only the two required headers:

```python
{
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}",
}
```

Explicitly **no** `X-API-Key` header. Chutes silently ignores it and falls back to the anonymous rate limit, which surfaces as an nginx 429 with HTML body — extremely confusing in logs.

## 7. Key Test, Sub-Router and Errors

### 7.1 `/test` endpoint

```python
@classmethod
def router(cls) -> APIRouter:
    router = APIRouter()

    @router.post("/test")
    async def test_connection(
        c: ResolvedConnection = Depends(resolve_connection_for_user),
    ) -> dict:
        api_key = c.config.get("api_key") or ""
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            try:
                resp = await client.get(
                    "https://api.chutes.ai/users/me",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            except httpx.HTTPError as exc:
                return {"valid": False, "error": f"Cannot reach Chutes: {exc}"}

        if resp.status_code == 200:
            return {"valid": True, "error": None}
        if resp.status_code in (401, 403):
            return {"valid": False, "error": "Chutes rejected the API key."}
        return {
            "valid": False,
            "error": f"Chutes management API returned {resp.status_code}.",
        }

    return router
```

We deliberately do **not** reuse the OpenRouter pattern of "fetch_models returned models → key is valid". Chutes' `/v1/models` is public and answers 200 with the full catalogue even with no key — so it cannot validate anything. The management endpoint `/users/me` requires authentication and returns the user's account record; it is the correct gate.

### 7.2 Streaming-path error mapping

| Upstream condition | Emitted event |
|---|---|
| `401` or `403` (any time) | `StreamError(error_code="invalid_api_key", message="Chutes rejected the API key")` — no retry |
| `429`/`503`, attempts remaining | sleep, retry |
| `429`/`503`, attempts exhausted | `StreamError(error_code="provider_unavailable", message="Chutes returned <code>; gave up after N attempts")` |
| Other non-200 | `StreamError(error_code="provider_unavailable", message="Chutes returned <code>: <body[:500]>")` |
| `httpx.ConnectError` | `StreamError(error_code="provider_unavailable", message="Cannot connect to Chutes")` |
| Idle >`GUTTER_ABORT_SECONDS` | `StreamAborted(reason="gutter_timeout")` |
| `finish_reason == "refusal"` | `StreamRefused(reason="refusal", refusal_text=delta.get("refusal"))` |

### 7.3 Logging conventions

All log records use the `chutes_http` prefix so `grep chutes_http` is precise:

- `chutes_http.fetch_models auth failure: status=%d` — for 401/403 from the models endpoint
- `chutes_http.fetch_models upstream %d: %s` — other non-200
- `chutes_http.fetch_models transport: %s` — transport-layer error
- `chutes_http.fetch_models malformed JSON` — body could not be decoded
- `chutes_http upstream %d: %s` — streaming-path non-200
- `chutes_http.gutter_slow model=%s idle=%.1fs`
- `chutes_http.gutter_abort model=%s idle=%.1fs`

`LLM_TRACE_PAYLOADS=1` toggles a `LLM_TRACE path=chutes-out url=%s payload=%s` line on each request, matching the convention in OpenRouter.

## 8. Tests

### 8.1 Backend unit tests (new files under `backend/modules/llm/tests/`)

`test_chutes_filter.py` — covers `_entry_to_meta` / the catalogue-filter predicate:

- `confidential_compute: false` → entry skipped
- `confidential_compute` missing → entry skipped (treated as not TEE)
- `context_length: 32_000` → skipped
- `context_length: 80_000` → kept (boundary)
- `output_modalities: ["image"]` → skipped
- `output_modalities: ["text", "image"]` → skipped (Phase 1 text-output only)
- Valid TEE entry → `ModelMetaDto` populated correctly, including capabilities derived from `supported_features` and `supports_vision` from `input_modalities`

`test_chutes_request_body.py` — covers `build_request_body` and the whitelist filter:

- Minimal request: only `model`, `messages`, `stream`, `stream_options`
- Request with `temperature` set → field present (pre-filter)
- `request.tools` set but `tools_enabled = False` → `tools` omitted
- `reasoning.kind = "optional"`, `reasoning_mode = "on"`, `reasoning_effort = "high"` → `reasoning_effort: "high"` in body
- `reasoning.kind = "optional"`, `reasoning_mode = "off"` → no `reasoning_effort`
- Vision message with an image part → `image_url` data-URL correctly embedded; text part remains text
- Whitelist filter: whitelist omits `reasoning_effort` → field dropped from final body even when reasoning is on
- Whitelist filter: whitelist omits `temperature` → field dropped from final body
- Whitelist filter: `model`, `messages`, `stream`, `stream_options`, `tools` always preserved regardless of whitelist contents
- Whitelist filter: empty / missing whitelist → body unchanged (no filtering applied)

No integration tests against the live Chutes endpoint in the automated suite. A manual smoke checklist (§8.3) covers that.

### 8.2 Frontend tests

No new component tests for `ChutesHttpView` — the existing model-browser and modal tests cover the general adapter-view contract, and `ChutesHttpView` is a trivial single-field view derived from `CommunityView`. If the component grows, tests come with that change.

### 8.3 Manual smoke checklist (post-deploy)

1. Create a Chutes Connection using the test key (`.chutes-test-key` at the repo root). `/test` returns `{valid: true}`.
2. Replace the key with a malformed string, retest. `/test` returns `{valid: false, error: "Chutes rejected the API key."}`.
3. Model picker shows 16+ TEE-only models, including `deepseek-ai/DeepSeek-V3.2-TEE`.
4. Chat with `deepseek-ai/DeepSeek-V3.2-TEE`, no tools. Stream renders smoothly end-to-end.
5. Chat with `deepseek-ai/DeepSeek-R1-0528-TEE`, reasoning toggled on. `ThinkingDelta` events appear in the UI before content.
6. Chat with a model that lists `tools` in `supported_features`, with one Chatsune tool enabled in the session. Tool-call streaming works and the result round-trips.

## 9. Dependencies and Migrations

- **Python deps:** no additions. `httpx` is already a project dependency. Both `pyproject.toml` files remain unchanged.
- **Frontend deps:** none.
- **Database migrations:** none. A new `Connection` document with `adapter_type = "chutes_http"` is just a new value — no schema change. Existing documents are unaffected.
- **Schema-compat note** per CLAUDE.md "No More Wipes": this change is purely additive. There is no field rename, removal, or type change; no migration script is required.

## 10. Build Verification

Per CLAUDE.md:

- Backend syntax check: `uv run python -m py_compile backend/modules/llm/_adapters/_chutes_http.py`
- Frontend: `pnpm tsc --noEmit && pnpm run build`

A task is not considered done until both pass.

## 11. Future Work (explicitly out of scope here)

- Routing-syntax support (`default:latency`, comma-separated failover lists)
- Cache-pricing display in the model browser
- `chute_id`-based cost / usage tracking via `/invocations/stats/llm`
- TEE attestation evidence surface in diagnostics
- Generic `tee: bool` flag on `ModelMetaDto` if a second TEE provider ever appears
- Premium Provider variant (admin-managed shared key) once the SCAI partnership produces one
- Shared-helper extraction across OpenAI-compatible adapters

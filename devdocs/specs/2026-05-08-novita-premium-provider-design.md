# Novita AI as a Premium Upstream Provider

**Status:** Design approved 2026-05-08
**Author:** Chris (with Claude)

## Goal

Add **Novita AI** as a Premium Upstream Provider so users can run open-source
inference models — primarily MiMo V2.5 Pro and MiMo V2.5 Omni — without
routing through nano-gpt or OpenRouter. Novita is open-source-inference-only
(not a router), exposes clean per-model metadata, and provides a third
high-quality fallback alongside OpenRouter and nano-gpt for models where the
existing routes are unsatisfying.

## Architecture

Novita slots into the existing Premium Provider pattern (mirrors
OpenRouter/Nano-GPT). It is **not** a user-creatable connection type:
the LLM resolver synthesises a `ResolvedConnection` on demand from the
user's Premium Provider Account, decrypting the API key and combining it
with the registry-fixed `base_url`.

The new adapter is structurally a slimmed-down clone of
`_openrouter_http.py`. The diff vs OR is:

* **No** `_anthropic_cache` import or `cache_control` markers — Novita
  hosts open-source models, never routes to Anthropic, so the cache flow
  is irrelevant.
* **No** `anthropic_cache` log line.
* **No** OpenRouter-specific app-attribution headers.
* Uses Novita's augmented model schema (`features`, `endpoints`,
  `context_size`, `display_name`, etc.) instead of OR's.

Otherwise the SSE loop, tool-call accumulator, retry policy
(`backend._retry`), gutter timer (`StreamSlow` / `StreamAborted`), and
auth-error handling stay identical to OR.

The pre-existing OpenAI-compat SSE-helper extraction (deferred after the
third adapter) remains deferred and is **not** part of this change. The
helpers continue to be cloned per adapter; the refactor is a separate
session.

## Endpoints

| Purpose | URL | Method |
|---|---|---|
| Chat completions | `https://api.novita.ai/openai/v1/chat/completions` | POST |
| Model listing | `https://api.novita.ai/openai/v1/models` | GET |
| API-key probe (billing balance) | `https://api.novita.ai/openapi/v1/billing/balance/detail` | GET |

The probe target is intentionally separate from `/v1/models` because the
models endpoint is unauthenticated — it returns the public catalogue
regardless of the supplied key, so it cannot validate credentials. The
billing endpoint requires authentication and 401s on a bad key.

## Registry Wiring

Five touch points, all backend:

1. `backend/modules/providers/_registry.py`
   ```python
   register(PremiumProviderDefinition(
       id="novita",
       display_name="Novita AI",
       icon="novita",
       base_url="https://api.novita.ai/openai/v1",
       capabilities=[Capability.LLM],
       config_fields=[_api_key_field("Novita AI API Key")],
       probe_url="https://api.novita.ai/openapi/v1/billing/balance/detail",
       probe_method="GET",
       linked_integrations=[],
   ))
   ```

2. `backend/modules/llm/_resolver.py`
   ```python
   _PREMIUM_ADAPTER_TYPE: dict[str, str] = {
       ...,
       "novita": "novita_http",
   }
   ```

3. `backend/modules/llm/_registry.py`
   ```python
   from backend.modules.llm._adapters._novita_http import NovitaHttpAdapter
   _PREMIUM_ONLY_ADAPTERS: dict[str, type[BaseAdapter]] = {
       ...,
       "novita_http": NovitaHttpAdapter,
   }
   ```

4. `backend/modules/llm/_connections.py:50` — append `"novita"` to the
   reserved-slug list so a user cannot create a stray `novita`-slugged
   connection that would bypass the Premium credential flow.

5. `backend/modules/llm/_adapters/_novita_http.py` — new file, full
   adapter (see below).

## Adapter — `_novita_http.py`

Class `NovitaHttpAdapter(BaseAdapter)` with:

* `adapter_type = "novita_http"`
* `display_name = "Novita AI"`
* `view_id = "novita_http"`
* `secret_fields = frozenset({"api_key"})`
* No `templates()` / `config_schema()` overrides (premium-only adapter,
  not user-creatable — these aren't surfaced).

### `fetch_models(c: ResolvedConnection) -> list[ModelMetaDto]`

Hits `GET {base_url}/models` with `Authorization: Bearer <api_key>`
(harmless when models endpoint is unauthenticated; required for parity
with OR's listing). Standard `httpx.AsyncClient` with the OR `_PROBE_TIMEOUT`.

Returns `[]` on transport error, 4xx, or malformed JSON — matches OR's
soft-fail behaviour so the model browser stays usable.

For each entry in the `data` array, applies the filter rules and the
mapping below. Entries that fail any filter are silently skipped.

### `stream_completion(c, request) -> AsyncIterator[ProviderStreamEvent]`

OpenAI-compat SSE loop, structurally identical to OR's adapter minus the
Anthropic cache logic. Specifically:

* `_build_chat_payload` produces `{model, stream, stream_options:
  {include_usage}, messages, [temperature], [tools], [reasoning]}`.
  No `cache_control` markers anywhere.
* `_translate_message` collapses text-only content to a plain string
  (cache-friendly default), uses the array form only when images are
  present.
* Reasoning toggle: only emitted when meaningful —
  ```python
  if request.supports_reasoning and not request.reasoning_enabled:
      payload["reasoning"] = {"exclude": True}
  ```
* `_chunk_to_events` reads both `delta.reasoning` and
  `delta.reasoning_content` (defensive — providers in the wild use
  either; emit `ThinkingDelta` for whichever is present).
* Tool-call accumulator is the idempotent variant from OR (multiple
  `finish_reason="tool_calls"` chunks for the same call must not produce
  duplicate events).
* Retry / backoff via `backend._retry` (`MAX_RETRY_ATTEMPTS`,
  `compute_retry_delay`, `parse_retry_after`, `should_retry_status`) for
  429 / 503.
* Gutter timer: `GUTTER_SLOW_SECONDS = 30.0`, `GUTTER_ABORT_SECONDS =
  120.0` (env-overridable via `LLM_STREAM_ABORT_SECONDS`). Emits
  `StreamSlow` at 30 s of silence and `StreamAborted` at 120 s.
* 401 / 403 → `StreamError(error_code="invalid_api_key", message="Novita
  rejected the API key")`.
* Other non-200 → `StreamError(error_code="provider_unavailable", ...)`.
* `httpx.ConnectError` → `StreamError(error_code="provider_unavailable",
  message="Cannot connect to Novita")`.

## Model Filter Rules

A Novita catalogue entry is exposed only if **all** are true:

1. `output_modalities == ["text"]`
2. `context_size >= 80_000`
3. `"chat/completions" in endpoints`
4. `"serverless" in features`
5. `model_type == "chat"`
6. `status == 1`

Rationale:

* (1) Same text-only restriction as OR / nano-gpt; image / audio output
  is out of scope for Phase 1.
* (2) The 80k floor mirrors the existing OR / nano-gpt rule. Sub-80k
  models leave no headroom once persona memory and tool definitions
  stack up.
* (3) Filters out completion-only models that wouldn't accept our
  chat-style request.
* (4) Filters out models that only run on dedicated deployments — they
  return a different status code on the OpenAI-compat path and have a
  different billing model.
* (5) `model_type` exists in Novita's schema; explicitly limit to chat.
* (6) `status == 1` is Novita's "active" marker; deprecated / paused
  models return other values and should not appear.

## Field Mapping

| `ModelMetaDto` field | Source in Novita response |
|---|---|
| `connection_id` | `c.id` (`"premium:novita"`) |
| `connection_slug` | `c.slug` (`"novita"`) |
| `connection_display_name` | `c.display_name` (`"Novita AI"`) |
| `model_id` | `id` (e.g. `xiaomimimo/mimo-v2.5-pro`) |
| `display_name` | `display_name` |
| `context_window` | `context_size` |
| `supports_reasoning` | `"reasoning" in features` |
| `supports_vision` | `"image" in input_modalities` |
| `supports_tool_calls` | `"function-calling" in features` |
| `is_deprecated` | `False` (filter rule (6) excludes deprecated) |
| `billing_category` | `"free"` if `input_token_price_per_m == 0` and `output_token_price_per_m == 0`, else `"pay_per_token"` |
| `is_moderated` | `None` (Novita schema has no equivalent) |

Entries with a missing or non-integer `id` field are skipped with a
warning log line (mirrors OR).

## Probe / Test

Uses the existing `backend/modules/providers/_probe.py` machinery — no
adapter-side `/test` route. The probe sends a `GET` to `probe_url` with
`Authorization: Bearer <api_key>`; status 200 → `ok`, 401/403 → `error`,
other non-2xx → `error` with the upstream status surfaced.

Novita is **not** added to `AUTO_TEST_PROVIDER_IDS` — like OR and
nano-gpt, it is probed only on explicit user request from the
Integrations tab. Easy to lift later if needed.

## Frontend Impact

None — the existing `IntegrationsTab` iterates over the providers
returned by `providersStore.ts` and renders a `PremiumAccountCard` per
entry. `display_name` and the API-key field are everything the card
needs; `icon` is data-model decoration only and is not currently
rendered. No new components, no new types, no new client code.

## Cross-File / Boundary Considerations

* `shared/dtos/llm.py::ModelMetaDto` — no changes; existing fields
  cover all the metadata we surface.
* `shared/events/providers.py` — no changes; the
  `PremiumProviderAccountTestedEvent` flow already covers Novita once
  it is registered.
* `shared/topics.py` — no changes.
* No migration needed: this only adds a new optional Premium Provider;
  existing users keep working unchanged.

## Manual Verification

These steps run against a real device using the API key in
`.novita-test-key`. The implementer must complete this list before
declaring the change done.

1. UserModal → Integrations → Novita AI card is visible.
2. Paste API key from `.novita-test-key`, click Save, click Test → status
   reads `ok`.
3. Edit the key to a known-bad string, Test → status reads `error` with a
   clear message (`invalid_api_key` or upstream 401 surfaced).
4. Restore the good key. Open Model Browser and verify:
   * `xiaomimimo/mimo-v2.5-pro` appears under Novita AI.
   * `xiaomimimo/mimo-v2.5-omni` appears under Novita AI.
   * No model with `context_size < 80_000` appears.
   * No image-output model appears.
5. Create a persona with `novita:xiaomimimo/mimo-v2.5-pro` as the default
   model. Send a short message — the assistant streams and finishes.
6. With `mimo-v2.5-pro` and reasoning **enabled**, send a reasoning-
   provoking prompt. Thinking pill appears with reasoning content.
7. With `mimo-v2.5-pro` and reasoning **disabled**, repeat: no thinking
   pill, plain answer only.
8. Tool-call check: pick a Novita model with
   `supports_tool_calls=True`, set up a persona with at least one tool
   group enabled, and trigger a request that should call a tool. Verify
   `ToolCallEvent` is emitted and the tool runs.
9. Vision check (only if a vision-capable Novita model is in the
   filtered list): attach an image, send — model responds based on the
   image.
10. Mid-stream invalid-key check: temporarily corrupt the stored key in
    Mongo, start a chat → user sees `invalid_api_key` error event with a
    recoverable status.

## Out of Scope

Explicit non-goals for this change:

* Anthropic prompt caching (Novita is OSS-only, no Anthropic upstream).
* OpenAI-compat SSE-helper extraction across adapters — already deferred
  to its own session.
* Auto-probe at login (`AUTO_TEST_PROVIDER_IDS` membership).
* Vision-specific edge handling beyond `"image" in input_modalities`.
* An adapter-side `/test` sub-router — the central `_probe.py` flow
  covers it.
* Pricing display in the UI — `billing_category` retains the binary
  `free` / `pay_per_token` shape used everywhere else.

## Open Questions

None at this point — all major decisions confirmed during
brainstorming on 2026-05-08:

* Endpoint URLs: `/openai/v1/...` (chat + models),
  `/openapi/v1/billing/balance/detail` (probe).
* Filter strategy: OR-style + `serverless`-only.
* Anthropic cache: not applicable (OSS-only inference).
* Naming: id `novita`, display `Novita AI`, no icon asset required.

The reasoning toggle relies on Novita honouring the OpenRouter-style
`{"reasoning": {"exclude": true}}` body field — to be confirmed in
manual verification step (6) / (7); if it diverges, the adapter switches
to the matching shape and the fix lands as a follow-up.

# Tensorix Premium Provider — Phase 1

**Date:** 2026-05-15
**Status:** Spec for review
**Scope:** Add Tensorix as a curated Premium LLM Provider with seven
hand-picked models, per-model reasoning configuration, and explicit
sort priority in the AddConnectionWizard. Text generation only.

---

## Revision 2026-05-15 (post-empirical)

After implementing the spec as originally written we probed all seven
curated models against the live Tensorix API and discovered that the
`binary` / `stepped` classification below does not match runtime
behaviour. The findings:

- Tensorix routes models through two heterogeneous internal backends,
  visible in `GET /v1/model/info` as `litellm_params.model`:
  - **OpenRouter proxy** (`openrouter/...` prefix) — deepseek-v4-pro,
    deepseek-v3.2, kimi-k2.6, glm-5, glm-4.6. These honour the OpenAI
    `reasoning_effort` field properly.
  - **Direct in-house engines** (`openai/...` prefix on
    95.133.253.*:8002 hosts) — deepseek-v4-flash and glm-5.1. These
    don't honour `reasoning_effort` consistently: glm-5.1 ignores
    `"none"` and reasons anyway; deepseek-v4-flash exposes no
    separate `reasoning_content` channel at all (thinking surfaces
    inline in `content`).

Because the two routes don't agree, our adapter can't pretend it
controls reasoning on every model. The classification was therefore
recut to two cases only:

| Model | Capability | Wire payload |
|---|---|---|
| `deepseek-v3-2` | `optional`, `default_on=False` | `reasoning_effort: "high"` when on, `"none"` when off |
| `deepseek-v4-pro` | `always_on` | (field omitted) |
| `deepseek-v4-flash` | `always_on` | (field omitted) |
| `kimi-k2-6` | `always_on` | (field omitted) |
| `glm-4-6` | `always_on` | (field omitted) |
| `glm-5` | `always_on` | (field omitted) |
| `glm-5-1` | `always_on` | (field omitted) |

The six `always_on` models render a disabled-but-visible reasoning
toggle in the UI (reusing the same treatment Mistral and others
already apply). Only `deepseek-v3-2` gets a live toggle. The
``ReasoningEffortDropdown`` stepped-selector component originally
proposed in §3.1 was therefore never built, and §5.3 / §7 below are
superseded by this revision. Documented as INSIGHTS INS-046.

The rest of this spec — provider ordering, drift-canary, sub-router,
error handling — remains accurate.

---

## 1. Goal

Bring Tensorix online as Chatsune's first GDPR/ZDR/EU-compute upstream
provider. Tensorix is OpenAI-compatible (litellm-backed), so the work
slots cleanly into the existing Premium-Provider + Premium-only adapter
pattern. The integration ships with a fixed seven-model curated list,
biased to the community blockbusters and a couple of historically
significant variants.

The Tensorix provider should appear directly under Ollama Cloud in the
Premium-Provider order so it gets first-screen visibility for the
partnership conversations starting in week 2026-W21.

---

## 2. Non-Goals (this iteration)

- TTS / STT / vision-image-out (Tensorix offers LLM only in scope here).
- Dynamic model discovery — the curated tuple is the source of truth.
- EU/GDPR/ZDR badge in the wizard or model browser (deferred; the
  marketing surface is a follow-up after the partner discussion lands).
- Extending the curated list beyond the seven slugs below — any
  additions (e.g. DeepSeek-R1-0528, Kimi-K2.5, GLM-5-Turbo) come in a
  follow-up PR after live operational experience.
- Sharing the OpenAI-compatible SSE parser / tool-call accumulator with
  the existing xAI/Mistral/Nano-GPT/OpenRouter adapters. That refactor
  is tracked separately.
- Per-model price surfacing in the UI. Tensorix exposes price metadata
  via `/v1/model/info`, but Phase 1 does not render it.

---

## 3. Architecture Fit

Tensorix follows the established two-layer pattern:

1. **Premium Provider** — user-facing account in
   `backend/modules/providers/_registry.py`, validated via the existing
   probe pipeline against `GET /v1/model/info` with a Bearer header.
2. **Premium-only LLM adapter** — instantiated by the resolver when a
   user has a Tensorix account; never user-creatable as a standalone
   Connection.

### 3.1 Files to create

- `backend/modules/llm/_adapters/_tensorix_http.py` — adapter
  implementation. Structurally a Mistral clone (OpenAI-compatible chat
  completions, dedicated tool-call accumulator) with the per-model
  reasoning-mode extension described in §4.
- `backend/tests/modules/llm/adapters/test_tensorix_http.py` — adapter
  unit tests (payload build, stream parsing, capability hints, test
  sub-router).

### 3.2 Files to modify

- `backend/modules/providers/_registry.py` — register the `tensorix`
  Premium Provider definition with `sort_priority` (see §6).
- `backend/modules/providers/_models.py` — add a new
  `sort_priority: int = 100` field to `PremiumProviderDefinition`.
- `backend/modules/providers/_handlers.py` — sort providers by
  `sort_priority` ascending in any list endpoint that currently relies
  on registration order.
- `backend/modules/llm/_registry.py` — add `tensorix_http` to
  `_PREMIUM_ONLY_ADAPTERS`.
- `backend/modules/llm/_resolver.py` — extend the premium-adapter map
  with `"tensorix": "tensorix_http"`.
- `backend/modules/llm/_adapters/__init__.py` — re-export
  `TensorixHttpAdapter` if that file maintains the public surface.
- `shared/dtos/llm.py` — add `reasoning_mode: Literal["binary",
  "stepped"] | None = None` to `ModelMetaDto` so the frontend can
  pick the right control. (Existing `reasoning_supported: bool` stays
  as a coarser hint for non-Tensorix adapters.)
- `frontend/src/app/components/llm-providers/AddConnectionWizard.tsx`
  (or its data source) — sort the provider list by `sort_priority`.
- Frontend reasoning control — a new small `<ReasoningEffortDropdown />`
  component for `stepped` mode (low/medium/high). The existing Mistral
  on/off toggle is reused as-is for `binary`. Renderer picks based on
  `reasoning_mode`.

---

## 4. Curated Model Schema

Mistral's `_ModelEntry` is the template. Tensorix extends it with
`reasoning_mode` to drive the per-model UI:

```python
from typing import Literal

@dataclass(frozen=True)
class _TensorixModelEntry:
    model_slug: str            # user-facing: stripped form, e.g. "deepseek-v4-flash"
    upstream_slug: str         # API slug: "deepseek/deepseek-v4-flash"
    display_name: str          # human label, e.g. "DeepSeek V4 Flash"
    context_window: int
    max_output_tokens: int
    supports_tools: bool
    supports_vision: bool
    reasoning_mode: Literal["binary", "stepped"] | None
    first_class_support: bool  # True for all seven (see §4.2)
```

### 4.1 The seven curated entries

> Note: the `Reasoning` column below is **superseded by the
> 2026-05-15 revision** at the top of this document. The current
> classification is `always_on` for six models and `off_on_toggle`
> for `deepseek-v3-2`. The table is preserved as-is for historical
> context; the live truth lives in
> `backend/modules/llm/_adapters/_tensorix_http.py::_TENSORIX_MODELS`.

| `model_slug` | `upstream_slug` | Display name | Ctx | Out | Tools | Vision | Reasoning (original) |
|---|---|---|---|---|---|---|---|
| `deepseek-v4-flash` | `deepseek/deepseek-v4-flash` | DeepSeek V4 Flash | 1 048 576 | 384 000 | yes | no | ~~binary~~ |
| `deepseek-v4-pro` | `deepseek/deepseek-v4-pro` | DeepSeek V4 Pro | 1 048 576 | 384 000 | yes | no | ~~stepped~~ |
| `kimi-k2-6` | `moonshotai/Kimi-K2.6` | Kimi K2.6 | 262 144 | 262 144 | yes | yes | ~~binary~~ |
| `glm-5-1` | `z-ai/glm-5.1` | GLM 5.1 | 202 752 | 202 752 | yes | no | ~~stepped~~ |
| `glm-5` | `z-ai/glm-5` | GLM 5 | 202 752 | 202 752 | yes | no | ~~stepped~~ |
| `deepseek-v3-2` | `deepseek/deepseek-v3.2` | DeepSeek V3.2 | 163 840 | 163 840 | yes | no | binary (still applies) |
| `glm-4-6` | `z-ai/glm-4.6` | GLM 4.6 | 203 000 | 131 000 | yes | no | ~~binary~~ |

`upstream_slug` is what we send to Tensorix; `model_slug` is the
user-facing identifier used in `<connection_id>:<model_slug>`. The
mapping is one-way and lives only inside the adapter.

### 4.2 First-class flag

All seven entries set `first_class_support=True`. Tensorix is a curated
provider — every model on it is a model we've vetted. The flag drives
the existing first-class badge in the Model Browser (Mistral, xAI,
etc. already use it).

### 4.3 Capability drift guard

The adapter's `/test` sub-router validates the Tensorix key against
`/v1/model/info` and additionally asserts that **at least one** of the
seven `upstream_slug`s is present in the response. This is a cheap
canary against Tensorix renaming or retiring a model behind our back.
The test fails closed when none match, so an operator will notice
before users do.

We accept that this is a smoke test, not a contract test — Tensorix
may add capabilities we don't reflect (e.g. tool support widening) and
we'd miss it. Phase 1 doesn't try to detect that.

---

## 5. Data Flow

### 5.1 Account setup (BYOK)

1. User opens Premium Providers → Tensorix → enters API key.
2. Backend probes `GET https://api.tensorix.ai/v1/model/info` with
   `Authorization: Bearer <key>`. 200 = valid, 401 = rejected.
3. Key is encrypted at rest exactly like every other Premium Provider.

### 5.2 Connection synthesis

The existing resolver synthesises a Premium Connection from the
Tensorix account on demand. No user action.

### 5.3 Chat request (streaming)

1. Resolver hands the adapter a request with
   `model = "<connection_id>:<model_slug>"`.
2. Adapter looks up the `_TensorixModelEntry` by `model_slug`, maps to
   `upstream_slug` for the wire payload.
3. Payload builder:
   - Standard OpenAI chat-completions body (`model`, `messages`,
     `temperature`, `max_tokens`, `tools`, `stream: true`).
   - `stream_options: {"include_usage": true}` always set, so we get
     usage in the final SSE chunk.
   - **Reasoning injection** (driven by `reasoning_mode`, post the
     2026-05-15 revision — see top of this document):
     - `off_on_toggle` mode + toggle ON  → `reasoning_effort: "high"`.
     - `off_on_toggle` mode + toggle OFF → `reasoning_effort: "none"`.
     - `always_on` mode → field omitted unconditionally; Tensorix
       either ignores the field or reasons regardless.
4. POST to `https://api.tensorix.ai/v1/chat/completions`, stream the
   response.
5. SSE parser handles three delta shapes:
   - `delta.content` (str) → `ContentDelta`.
   - `delta.reasoning_content` (str) → `ThinkingDelta`. (Tensorix
     emits this when reasoning is active. Same shape as DeepSeek's
     native reasoning field; the existing OAI fallback gating from
     commit `6b05a8ce` is already in place, but we double-check that
     we don't emit duplicate ThinkingDeltas here.)
   - `delta.tool_calls` (array of partial fragments) → fed into the
     index-keyed accumulator, flushed on `finish_reason="tool_calls"`.
6. Final chunk's `usage` is converted to `TokenUsage` and emitted.

### 5.4 Model listing

`fetch_models()` returns the seven curated entries verbatim — no live
API call. Capabilities are derived from the static tuple. This matches
the late-Mistral pattern (commit `94b4f3a2`).

---

## 6. Provider Ordering — `sort_priority`

New field on `PremiumProviderDefinition`:

```python
sort_priority: int = 100
```

Lower = earlier in the list. Assignments:

| Provider | `sort_priority` |
|---|---|
| `ollama_cloud` | 10 |
| `tensorix` | 20 |
| `xai` | 30 |
| `mistral` | 40 |
| `nano_gpt` | 100 (default) |
| `openrouter` | 100 (default) |
| `novita` | 100 (default) |

Ties break by registration order (stable sort). This makes the
"featured" tier explicit and lets future providers slot in without
renumbering the long tail.

The provider-list endpoint (`GET /api/providers`) sorts on this field
before returning. The frontend wizard becomes a passive consumer — no
sort logic on the client.

---

## 7. Reasoning UI

The frontend already supports the two capability shapes we need —
no new component lands as part of this provider.

- `ReasoningCapability.kind == "optional"` (only deepseek-v3.2) →
  render the existing on/off toggle. ON sends
  `reasoning_effort: "high"`; OFF sends `"none"` (this mirrors the
  Mistral and xAI surface).
- `ReasoningCapability.kind == "always_on"` (the other six) → render
  the existing always-on treatment (disabled-but-visible toggle with
  the "always on" hint). No wire-side `reasoning_effort` is sent.

The `<ReasoningEffortDropdown />` proposed in §3.1 was never built —
the empirical findings (see top revision) made the stepped surface
moot before the component landed. If a future Tensorix model lands
that genuinely honours stepped effort buckets, revisit this section
then.

---

## 8. Sub-Router: `/test`

Mirrors `_mistral_http.py` lines 611–663. Mounted at
`POST /api/llm/connections/{id}/adapter/test`:

1. Resolve the connection via the LLM module's generic dependency.
2. GET `https://api.tensorix.ai/v1/model/info` with the connection's
   key.
3. On 2xx, parse the JSON and assert at least one curated
   `upstream_slug` appears in `data[].model_name`. Return
   `{"ok": true, "models_seen": <n_curated_found>}`.
4. On 401 or empty curated intersection, return `{"ok": false,
   "reason": "..."}` with an appropriate detail string.
5. On 5xx / network errors, surface a generic `service_unavailable`.

---

## 9. Error Handling

Standard OpenAI-shape error responses, mapped via the existing Premium
adapter error pathway:

| Upstream | UI message | Recoverable |
|---|---|---|
| 401 | "Tensorix API key is invalid. Re-enter it in Premium Providers." | no |
| 403 | "Tensorix denied this request. Check your account permissions." | no |
| 404 (model) | "Tensorix doesn't recognise this model." (Drift canary — capability guard didn't fire.) | no |
| 429 | "Tensorix rate limit reached. Try again in a moment." | yes |
| 5xx | "Tensorix is temporarily unavailable." | yes |
| network / timeout | Generic `StreamError`. | yes |

No Tensorix-specific error shape — they're OpenAI-compatible all the
way down to the error envelope.

---

## 10. Testing

### 10.1 Unit tests (pytest)

- Payload builder: each `reasoning_mode` × toggle/effort combination
  injects the right `reasoning_effort` (or omits it).
- Slug mapping: every `model_slug` resolves to the right
  `upstream_slug`; unknown slugs raise.
- Stream parser: content / reasoning_content / tool_calls
  interleaving, with the usage chunk at end.
- Capability hint: returns the right tools / vision / reasoning flags
  per model, with `first_class_support=True` for all seven.

### 10.2 Sub-router test

- Happy path: stub `/v1/model/info` with one curated slug present →
  200 `{ok: true}`.
- 401 path: stub a 401 → 200 `{ok: false, reason: "unauthorised"}`.
- Drift path: stub a response with zero curated slugs → 200
  `{ok: false, reason: "no curated models present"}`.

### 10.3 LLM harness scenarios

Add `tests/llm_scenarios/tensorix_*.json` for at least:

- `tensorix_deepseek_v4_flash_simple.json` — non-reasoning sanity check.
- `tensorix_deepseek_v4_pro_stepped_reasoning.json` — stepped reasoning,
  asserts reasoning content appears in the stream.
- `tensorix_kimi_k2_6_tools.json` — tool-call round trip.
- `tensorix_glm_5_1_streaming_usage.json` — confirms `include_usage`
  delivers a final usage chunk.

### 10.4 Manual smoke (pre-merge)

- Create a Tensorix account in the wizard with the test key.
- Verify it appears between Ollama Cloud and xAI.
- Send a chat to each of the seven models with reasoning off.
- Send a chat to one binary-reasoning model with reasoning on.
- Send a chat to one stepped-reasoning model at each of low / medium /
  high, confirm reasoning effort visibly changes.
- Trigger a tool call from `Kimi-K2.6` and confirm round trip.
- Run `pnpm run build` and `uv run python -m py_compile` on changed
  files.

---

## 11. Open Questions Resolved During Brainstorming

- **Reasoning API** — per-model: four binary, three stepped. Mapping in
  §4.1.
- **EU/GDPR branding** — deferred, no badge in Phase 1.
- **Provider ordering** — explicit `sort_priority` field on
  `PremiumProviderDefinition`, not registration-order dependent.
- **Curated list** — exactly the seven slugs. Additions later.
- **First-class flag** — all seven set to `True`.

---

## 12. Dependency-File Hygiene

No new Python dependencies — Tensorix calls reuse the existing
`httpx` client. Both `pyproject.toml` files therefore stay untouched,
but the spec calls this out so the implementation plan can re-verify.

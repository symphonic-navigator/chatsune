# Nano-GPT Billing Filter & Thinking-Trace Fix — Design

**Date:** 2026-04-24
**Author:** Chris + Claude (brainstorming session)
**Status:** Approved pending final review
**Scope:** One branch, two independent workstreams delivered as separate commits.

---

## Background

Phase 2 of the nano-gpt adapter landed yesterday (`stream_completion` against
`/v1/chat/completions`). Two follow-up gaps surfaced during live use:

1. **Billing filter missing.** Every model now carries a `billing_category`
   (`free` / `subscription` / `pay_per_token`), but the `ModelBrowser` has
   no UI to filter on it. A nano-gpt subscription user does not care
   whether a model is zero-cost because it is free or because their plan
   covers it — "no per-token cost" is the real decision dimension. Users
   without a plan need to see the metered models too.
2. **Thinking traces never render.** TTFT (time-to-first-token) is fine,
   but the chat view sits silent for a long while before anything
   appears. Root cause identified via the official nano-gpt docs: the
   default SSE endpoint streams reasoning in `choices[0].delta.reasoning`,
   while our adapter reads only the legacy field
   `choices[0].delta.reasoning_content`. Every reasoning chunk is being
   silently discarded.

Source for the reasoning contract:
<https://docs.nano-gpt.com/api-reference/endpoint/chat-completion>

---

## Goals

- Global, single-select cost filter in the model browser that cuts across
  every connection/provider.
- Nano-gpt reasoning traces visible in the chat UI, starting at the same
  TTFT as text content.
- Thinking mode is activated defensively via `reasoning_effort` in the
  request body **only** for models the pair map marks as thinking-capable.
  Non-thinking slugs are never touched.
- Zero behavioural change for xAI, Mistral, Community, and Ollama
  adapters. Zero new dependencies.

## Out of scope

- A UI control for thinking intensity (effort level). We hard-code
  `"medium"` for now.
- Persisting the billing filter across sessions. Session-scoped like the
  existing capability chips.
- Switching to `/v1legacy` or `/v1thinking` endpoints. Default endpoint
  remains correct.
- Refactor of `_chunk_to_events` into a shared `_openai_compat.py`
  module. Separately tracked in memory `project_openai_compat_refactor.md`.

---

## Workstream 1 — Global Billing Filter (Frontend)

### UI placement

`frontend/src/app/components/model-browser/ModelBrowser.tsx` — the
filter bar currently reads:

```
[Search] [Provider ▾] ★ Fav | Reasoning | Vision | Tools | Show hidden
```

Insert a new dropdown **immediately after** the provider dropdown:

```
[Search] [Provider ▾] [Billing: All ▾] ★ Fav | Reasoning | ... | Hidden
```

Native `<select>`, same styling as the provider dropdown (dark
`<option>` inline styles per the CLAUDE.md gotcha).

### Options

| Value             | Label               | Semantics                                         |
|-------------------|---------------------|---------------------------------------------------|
| `all`             | `All billing`       | no filter (default)                               |
| `no_per_token`    | `No per-token cost` | `billing_category ∈ {free, subscription}`         |
| `free`            | `Free only`         | `billing_category == "free"`                      |
| `subscription`    | `Subscription only` | `billing_category == "subscription"`              |
| `pay_per_token`   | `Pay per token`     | `billing_category == "pay_per_token"`             |

### Handling `billing_category == null`

Legacy cached documents from before the alpha→beta cut may be missing
`billing_category`. Adapters now populate it on every fetch, but a stale
Redis cache could still serve `None`.

- `all`               → included (current behaviour)
- any other filter    → excluded

Rationale: if the user is actively filtering by cost, surfacing a model
whose cost is *unknown* defeats the point. Refreshing the connection
repopulates the field.

### Filter logic

`frontend/src/app/components/model-browser/modelFilters.ts`:

- Add `BillingFilter = 'all' | 'no_per_token' | 'free' | 'subscription' | 'pay_per_token'`
- Extend `ModelFilters` with `billing?: BillingFilter` (optional; absent
  == `all`).
- In `applyModelFilters`, add a clause before the search clause:

  ```ts
  if (filters.billing && filters.billing !== 'all') {
    const cat = m.billing_category ?? null
    if (cat === null) return false
    switch (filters.billing) {
      case 'no_per_token':  if (cat !== 'free' && cat !== 'subscription') return false; break
      case 'free':           if (cat !== 'free') return false; break
      case 'subscription':   if (cat !== 'subscription') return false; break
      case 'pay_per_token':  if (cat !== 'pay_per_token') return false; break
    }
  }
  ```

### Type update

`frontend/src/core/types/llm.ts::ModelMetaDto` — add:

```ts
/**
 * How this model bills the user. ``free`` = no cost, ``subscription`` =
 * covered by an upstream plan (Ollama Cloud, nano-gpt subscription tier),
 * ``pay_per_token`` = metered. Optional for backwards compat with older
 * cached payloads — treat missing as ``null`` (= unknown).
 */
billing_category?: 'free' | 'subscription' | 'pay_per_token' | null
```

### State

`useState<BillingFilter>('all')` in `ModelBrowser`, wired like the
existing `providerFilter`. Merged into `effectiveFilters` alongside
locked capability flags. No persistence.

### Tests

`frontend/src/app/components/model-browser/modelFilters.test.ts` (create
if missing, extend otherwise):

- 5 billing values × 3 `billing_category` states (free/subscription/pay_per_token) +
  null = 20 assertions covering every combination.
- Regression: `all` passes all models through unchanged.

---

## Workstream 2 — Nano-GPT Thinking Traces (Backend)

### Fix A — Read the correct SSE field

`backend/modules/llm/_adapters/_nano_gpt_http.py::_chunk_to_events`,
line ~144. Replace:

```python
reasoning = delta.get("reasoning_content") or ""
```

with:

```python
# Default endpoint streams reasoning in ``delta.reasoning``; the legacy
# endpoint (``/v1legacy``) uses ``delta.reasoning_content``. We treat the
# default as authoritative and fall back to the legacy field so the
# adapter keeps working if the endpoint ever switches. They never arrive
# together in a single chunk.
reasoning = delta.get("reasoning") or delta.get("reasoning_content") or ""
```

### Fix B — Defensive `reasoning_effort` flag

Thinking activation is primarily via the thinking_slug from the pair
map. The docs confirm reasoning is delivered by default, so the flag is
redundant in the common case. We add it anyway as a belt-and-braces
measure for upstream routers that inspect the body rather than the slug.

**`_build_chat_payload` — new signature:**

```python
def _build_chat_payload(
    request: CompletionRequest,
    upstream_slug: str,
    *,
    is_thinking_slug: bool,
) -> dict:
```

Inside the body, **only** when `is_thinking_slug` is true:

```python
if is_thinking_slug:
    payload["reasoning_effort"] = "medium"
```

Non-thinking slugs get no reasoning field in the body — this is
load-bearing, the test suite must enforce it.

**Caller update** in `stream_completion`:

```python
pair = pair_map.get(request.model) or {}
is_thinking_slug = bool(
    pair.get("thinking_slug")
    and upstream_slug == pair["thinking_slug"],
)
payload = _build_chat_payload(
    request, upstream_slug, is_thinking_slug=is_thinking_slug,
)
```

### Docstring revision

Top of `_nano_gpt_http.py`. Replace the absolutist warning with a
precise one that matches the new behaviour:

> Thinking capability is expressed primarily by picking the
> `thinking_slug` from the pair map as the upstream model. For
> thinking-capable slugs we additionally set `reasoning_effort:
> "medium"` in the request body as a defensive signal to upstream
> routers that dispatch on the body rather than the slug.
>
> **Non-thinking slugs must never carry a `reasoning`/`reasoning_effort`
> field in the body.** This is enforced by `_build_chat_payload`'s
> `is_thinking_slug` gate and covered by tests.

### Effort value

Hard-coded `"medium"`. The docs list
`none | minimal | low | medium | high | xhigh`. We have no UI for
thinking intensity today, and `"medium"` is a safe default (matches the
OpenAI reasoning-models default). A configurable effort level is a
later, separate workstream.

### Tests

`backend/tests/modules/llm/adapters/test_nano_gpt_http.py`:

1. **`_chunk_to_events`** — two new tests:
   - `reasoning` field alone produces a `ThinkingDelta`
   - When both `reasoning` and `reasoning_content` are present in the
     same delta, `reasoning` wins (defensive, never expected in practice).
   Keep the existing `reasoning_content` test for backwards-compat
   coverage.
2. **`_build_chat_payload`** — two new tests:
   - `is_thinking_slug=True` → payload contains `reasoning_effort="medium"`
   - `is_thinking_slug=False` → payload contains **no** `reasoning`,
     `reasoning_effort`, or `thinking` key at all (use
     `set(payload.keys())` inspection).
3. **`stream_completion`** — extend the existing happy-path tests:
   - Thinking request with a dual-slug model → `fake.posted_payload`
     has `reasoning_effort == "medium"` AND `model == thinking_slug`.
   - Non-thinking request with the same dual-slug model →
     `reasoning_effort` absent, `model == non_thinking_slug`.
   - Thinking request on a model whose `thinking_slug is None`
     (capability-gated fallback) → `reasoning_effort` absent,
     `model == non_thinking_slug`.

### Build verification

- `uv run python -m py_compile backend/modules/llm/_adapters/_nano_gpt_http.py`
- `uv run pytest backend/tests/modules/llm/adapters/test_nano_gpt_http.py -v`
- `uv run pytest backend/ shared/` (full suite, no regressions)

---

## File change summary

**Modify:**
- `frontend/src/app/components/model-browser/ModelBrowser.tsx` — billing dropdown, state, merge into filters
- `frontend/src/app/components/model-browser/modelFilters.ts` — `BillingFilter`, `ModelFilters.billing`, filter clause
- `frontend/src/core/types/llm.ts` — `ModelMetaDto.billing_category`
- `backend/modules/llm/_adapters/_nano_gpt_http.py` — docstring, `_chunk_to_events` field fallback, `_build_chat_payload` signature + gated flag, `stream_completion` call site

**Create:**
- `frontend/src/app/components/model-browser/modelFilters.test.ts` — new Vitest file colocated with `modelFilters.ts`, matching the repo's established test-file convention (e.g. `frontend/src/core/store/chatStore.test.ts`).

**Tests modified:**
- `backend/tests/modules/llm/adapters/test_nano_gpt_http.py`

No new dependencies. No changes to `shared/dtos/*`.

## Commit plan

Two commits on one feature branch (name TBD during plan-writing), merged
to master per project convention:

1. `Add defensive reasoning_effort and reasoning field fallback to nano-gpt adapter`
2. `Add global billing-category filter to ModelBrowser`

Order: backend first (reasoning fix is user-facing for anyone already on
master), frontend second.

## Manual verification

At the end of the session Chris will:

1. `docker compose up -d`, tail backend logs for clean startup.
2. Open chat, select a nano-gpt thinking-capable model (e.g.
   `anthropic/claude-opus-4.6`), toggle reasoning ON, send a prompt —
   thinking pill appears within seconds, reasoning trace renders
   continuously, content follows.
3. Same model, reasoning OFF → trace via `LLM_TRACE_PAYLOADS=1` shows
   **no** `reasoning_effort` in the outgoing body, non-thinking slug
   chosen, content streams without a thinking pill.
4. A pay-per-token-only model (no thinking variant) with reasoning ON
   in the UI → outgoing body still has no `reasoning_effort` (pair-map
   gate holds).
5. Model browser: open, pick `No per-token cost` from the new billing
   dropdown — all xAI/Mistral rows disappear, nano-gpt subscription
   rows remain, Community/Ollama-local rows remain. Pick `Pay per
   token` → only xAI/Mistral/nano-gpt metered rows remain.

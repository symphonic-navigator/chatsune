# Nano-GPT Billing Filter & Thinking-Trace Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make nano-gpt reasoning traces render in the chat UI (field-name fix + defensive `reasoning_effort` flag), and add a global single-select billing-category filter to the ModelBrowser that cuts across every connection.

**Architecture:**
- Backend (`_nano_gpt_http.py`): `_chunk_to_events` reads `delta.reasoning` with a fallback to `delta.reasoning_content`; `_build_chat_payload` takes a new `is_thinking_slug` kwarg and sets `reasoning_effort: "medium"` only when that is true; `stream_completion` derives the flag from the pair-map comparison.
- Frontend (`ModelBrowser.tsx` + `modelFilters.ts`): new `BillingFilter` union, new `billing` field on `ModelFilters`, single-select `<select>` in the filter bar. `billing_category == null` is shown only under `all`.

**Tech Stack:** Python 3.12+, pytest-asyncio, httpx, redis.asyncio (via fakeredis in tests). Frontend: TypeScript, React, Vite, Vitest, Tailwind. No new dependencies.

**Spec:** `devdocs/superpowers/specs/2026-04-24-nano-gpt-billing-filter-and-thinking-design.md`

**Commit plan:**
1. `Add defensive reasoning_effort and reasoning field fallback to nano-gpt adapter` (backend)
2. `Add global billing-category filter to ModelBrowser` (frontend)

**Branch:** `nano-gpt-billing-filter-and-thinking`. Merge to master at the end per project convention.

---

## File Structure

**Modify:**
- `backend/modules/llm/_adapters/_nano_gpt_http.py` — docstring, `_chunk_to_events`, `_build_chat_payload`, `stream_completion` call site
- `backend/tests/modules/llm/adapters/test_nano_gpt_http.py` — new assertions for field fallback, `is_thinking_slug` gating, end-to-end payload shape
- `frontend/src/core/types/llm.ts` — add `billing_category` to `ModelMetaDto`
- `frontend/src/app/components/model-browser/modelFilters.ts` — `BillingFilter`, extend `ModelFilters`, filter clause
- `frontend/src/app/components/model-browser/ModelBrowser.tsx` — dropdown in filter bar, state, merge into `effectiveFilters`

**Create:**
- `frontend/src/app/components/model-browser/modelFilters.test.ts` — Vitest colocated with `modelFilters.ts`

**No new files on the backend side. No new dependencies.**

---

### Task 0: Create feature branch

**Files:** none modified.

- [ ] **Step 1: Create and switch to feature branch**

```bash
cd /home/chris/workspace/chatsune
git checkout -b nano-gpt-billing-filter-and-thinking
```

Expected: `Switched to a new branch 'nano-gpt-billing-filter-and-thinking'`

- [ ] **Step 2: Confirm clean working tree**

```bash
git status
```

Expected: `nothing to commit, working tree clean`. The spec commit is on master and present on the branch.

---

### Task 1: `_chunk_to_events` reads `delta.reasoning` with legacy fallback

The default nano-gpt endpoint streams reasoning via `choices[0].delta.reasoning`; the legacy endpoint uses `delta.reasoning_content`. Our adapter currently reads only the legacy field. This task adds `reasoning` as the primary field and keeps `reasoning_content` as the fallback.

**Files:**
- Modify: `backend/modules/llm/_adapters/_nano_gpt_http.py` (function `_chunk_to_events`, near line 144)
- Modify: `backend/tests/modules/llm/adapters/test_nano_gpt_http.py`

- [ ] **Step 1: Write failing tests for the new field and the fallback**

Add these two tests to `test_nano_gpt_http.py`. Keep the existing `test_chunk_to_events_thinking_delta_from_reasoning_content` test as-is — it still passes and documents legacy compatibility.

```python
def test_chunk_to_events_thinking_delta_from_reasoning_field():
    """Default nano-gpt endpoint streams reasoning in delta.reasoning."""
    acc = _ToolCallAccumulator()
    events = _chunk_to_events(
        {"choices": [{"delta": {"reasoning": "thinking…"}}]}, acc,
    )
    assert events == [ThinkingDelta(delta="thinking…")]


def test_chunk_to_events_reasoning_takes_precedence_over_reasoning_content():
    """If a single delta somehow carries both (never expected in practice),
    ``reasoning`` wins so the modern field name is authoritative."""
    acc = _ToolCallAccumulator()
    events = _chunk_to_events(
        {"choices": [{"delta": {
            "reasoning": "modern",
            "reasoning_content": "legacy",
        }}]}, acc,
    )
    assert events == [ThinkingDelta(delta="modern")]
```

The imports `_ToolCallAccumulator`, `_chunk_to_events`, and `ThinkingDelta` are already present at the top of the test module from earlier Phase-2 tests.

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/chris/workspace/chatsune
uv run pytest backend/tests/modules/llm/adapters/test_nano_gpt_http.py -v -k "reasoning_field or reasoning_takes_precedence"
```

Expected: both new tests FAIL — the first because `delta.reasoning` is ignored, the second because `reasoning_content` is used instead of `reasoning`.

- [ ] **Step 3: Apply the field fallback**

In `backend/modules/llm/_adapters/_nano_gpt_http.py`, locate inside `_chunk_to_events`:

```python
    reasoning = delta.get("reasoning_content") or ""
    if reasoning:
        events.append(ThinkingDelta(delta=reasoning))
```

Replace with:

```python
    # Default endpoint streams reasoning in ``delta.reasoning``; the legacy
    # endpoint (``/v1legacy``) uses ``delta.reasoning_content``. We treat
    # the default as authoritative and fall back to the legacy field so
    # the adapter keeps working if the endpoint ever switches. They never
    # arrive together in a single chunk in practice.
    reasoning = delta.get("reasoning") or delta.get("reasoning_content") or ""
    if reasoning:
        events.append(ThinkingDelta(delta=reasoning))
```

- [ ] **Step 4: Run the full adapter test file to confirm all chunk tests pass**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_nano_gpt_http.py -v -k "chunk_to_events"
```

Expected: every `test_chunk_to_events_*` test PASSES, including the new ones and the retained `reasoning_content` test.

- [ ] **Step 5: No commit yet**

Tasks 1–3 share a single commit. Stay on the branch, staged work accumulates until Task 4.

---

### Task 2: `_build_chat_payload` gates `reasoning_effort` behind `is_thinking_slug`

Thinking activation is primarily via the `thinking_slug` from the pair map. As a defensive signal, we also set `reasoning_effort: "medium"` in the request body — but only when the resolved upstream slug is the thinking variant. Non-thinking slugs must never carry the flag.

**Files:**
- Modify: `backend/modules/llm/_adapters/_nano_gpt_http.py` (function `_build_chat_payload`, near line 237)
- Modify: `backend/tests/modules/llm/adapters/test_nano_gpt_http.py`

- [ ] **Step 1: Write failing tests for the new gate**

Add to `test_nano_gpt_http.py`:

```python
from backend.modules.llm._adapters._nano_gpt_http import _build_chat_payload
from shared.dtos.inference import CompletionRequest, CompletionMessage, ContentPart


def _basic_request(model: str = "m1") -> CompletionRequest:
    return CompletionRequest(
        model=model,
        messages=[CompletionMessage(
            role="user",
            content=[ContentPart(type="text", text="hi")],
        )],
    )


def test_build_chat_payload_thinking_slug_sets_reasoning_effort():
    req = _basic_request()
    payload = _build_chat_payload(
        req, upstream_slug="m1:thinking", is_thinking_slug=True,
    )
    assert payload["reasoning_effort"] == "medium"
    assert payload["model"] == "m1:thinking"


def test_build_chat_payload_non_thinking_slug_has_no_reasoning_keys():
    req = _basic_request()
    payload = _build_chat_payload(
        req, upstream_slug="m1", is_thinking_slug=False,
    )
    forbidden = {"reasoning", "reasoning_effort", "reasoning_content", "thinking"}
    assert not (forbidden & set(payload.keys())), (
        f"Non-thinking slug leaked reasoning keys: {forbidden & set(payload.keys())}"
    )
    assert payload["model"] == "m1"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_nano_gpt_http.py -v -k "build_chat_payload"
```

Expected: the first test FAILS with `TypeError: _build_chat_payload() got an unexpected keyword argument 'is_thinking_slug'`. The second may fail the same way or pass trivially depending on evaluation order.

- [ ] **Step 3: Update `_build_chat_payload` signature and body**

In `_nano_gpt_http.py`, replace the current `_build_chat_payload` (around lines 237–264) with:

```python
def _build_chat_payload(
    request: CompletionRequest,
    upstream_slug: str,
    *,
    is_thinking_slug: bool,
) -> dict:
    """Build an OpenAI-compatible chat-completions request body.

    Thinking capability is primarily expressed via ``upstream_slug`` —
    nano-gpt's pair map picks the thinking variant. For thinking-capable
    slugs we additionally set ``reasoning_effort: "medium"`` as a
    defensive signal to upstream routers that dispatch on the body
    rather than on the slug. Non-thinking slugs must never carry a
    reasoning/thinking field in the body.
    """
    payload: dict = {
        "model": upstream_slug,
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [_translate_message(m) for m in request.messages],
    }
    if is_thinking_slug:
        payload["reasoning_effort"] = "medium"
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

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_nano_gpt_http.py -v -k "build_chat_payload"
```

Expected: both new tests PASS.

- [ ] **Step 5: No commit yet**

Tasks 1–3 share a single commit.

---

### Task 3: `stream_completion` call-site + module docstring

Thread the `is_thinking_slug` determination from the pair-map lookup into `_build_chat_payload`, and revise the module docstring to match the new behaviour.

**Files:**
- Modify: `backend/modules/llm/_adapters/_nano_gpt_http.py` (module docstring at top; function `stream_completion`, around lines 398–435)
- Modify: `backend/tests/modules/llm/adapters/test_nano_gpt_http.py`

- [ ] **Step 1: Write failing end-to-end tests for the gated body flag**

Add to `test_nano_gpt_http.py`. These extend the existing end-to-end tests (`test_stream_completion_happy_path_non_thinking` and `test_stream_completion_thinking_picks_thinking_slug`) to assert the presence/absence of `reasoning_effort`.

```python
@pytest.mark.asyncio
async def test_stream_completion_non_thinking_omits_reasoning_effort(
    redis_client, monkeypatch,
):
    """Non-thinking dispatch: body must not carry reasoning_effort."""
    conn = _resolved_conn()
    await _populate_pair_map(redis_client, conn.id)

    sse_lines = [
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
    async for _ in adapter.stream_completion(
        conn, _make_request("anthropic/claude-opus-4.6", reasoning_enabled=False),
    ):
        pass

    assert "reasoning_effort" not in fake.posted_payload
    assert fake.posted_payload["model"] == "anthropic/claude-opus-4.6"


@pytest.mark.asyncio
async def test_stream_completion_thinking_sets_reasoning_effort(
    redis_client, monkeypatch,
):
    """Thinking dispatch on a dual-slug model: reasoning_effort=medium,
    and the thinking_slug is used."""
    conn = _resolved_conn()
    await _populate_pair_map(redis_client, conn.id)

    sse_lines = [
        'data: {"choices":[{"delta":{"reasoning":"…"}}]}',
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
    async for _ in adapter.stream_completion(
        conn, _make_request("anthropic/claude-opus-4.6", reasoning_enabled=True),
    ):
        pass

    assert fake.posted_payload["reasoning_effort"] == "medium"
    assert fake.posted_payload["model"] == "anthropic/claude-opus-4.6:thinking"


@pytest.mark.asyncio
async def test_stream_completion_reasoning_on_no_thinking_variant_omits_flag(
    redis_client, monkeypatch,
):
    """Model with thinking_slug=None: reasoning toggled ON in the UI
    must still NOT send reasoning_effort, since we'd be dispatching to
    the non-thinking slug anyway. Capability-gated fallback."""
    conn = _resolved_conn()
    await _populate_pair_map(redis_client, conn.id)  # has free/phi-small with thinking_slug=None

    sse_lines = [
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
    async for _ in adapter.stream_completion(
        conn, _make_request("free/phi-small", reasoning_enabled=True),
    ):
        pass

    assert "reasoning_effort" not in fake.posted_payload
    assert fake.posted_payload["model"] == "free/phi-small"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_nano_gpt_http.py -v -k "stream_completion"
```

Expected: the three new tests FAIL with `TypeError: _build_chat_payload() got an unexpected keyword argument 'is_thinking_slug'` (caller still passes two positional args), or `AssertionError` if Python's keyword handling swallows the extra arg. The existing stream-completion tests also FAIL because of the same signature change.

- [ ] **Step 3: Update the `stream_completion` call site**

In `_nano_gpt_http.py`, locate in `stream_completion` (around line 430):

```python
        payload = _build_chat_payload(request, upstream_slug)
```

Replace with:

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

- [ ] **Step 4: Revise the module docstring**

At the top of `_nano_gpt_http.py`, replace lines 1–15 (the current docstring) with:

```python
"""Nano-GPT HTTP adapter.

Implements the model catalogue (filter / pair / map via
``_nano_gpt_catalog``), persists the pair map to Redis
(``_nano_gpt_pair_map``), and drives an OpenAI-compatible SSE
streaming loop in ``stream_completion`` that picks the correct
upstream slug (thinking vs non-thinking) from the pair map at
request time.

Thinking activation — nano-gpt supports thinking in two ways:

1. Primary: pick the ``thinking_slug`` from the pair map as the
   upstream model. This is how every dual-slug model is routed.
2. Defensive: when (and only when) the resolved upstream slug is
   the thinking variant, ``_build_chat_payload`` also sets
   ``reasoning_effort: "medium"`` in the request body. This is a
   belt-and-braces signal for upstream routers that inspect the
   body rather than the slug.

**Non-thinking slugs must never carry a reasoning / reasoning_effort
/ thinking field in the body.** This is gated by the ``is_thinking_slug``
kwarg in ``_build_chat_payload`` and enforced by the test suite.

SSE field names — the default ``/api/v1/chat/completions`` endpoint
streams reasoning in ``delta.reasoning``; the legacy
``/api/v1legacy/chat/completions`` endpoint uses
``delta.reasoning_content``. ``_chunk_to_events`` reads both (modern
field takes precedence) so the adapter works against either.
"""
```

- [ ] **Step 5: Run the full adapter test file**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_nano_gpt_http.py -v
```

Expected: every test PASSES, including existing ones and all new ones from Tasks 1–3.

- [ ] **Step 6: Verify Python build**

```bash
uv run python -m py_compile backend/modules/llm/_adapters/_nano_gpt_http.py
```

Expected: no errors.

- [ ] **Step 7: Run the full backend test suite to catch any regression**

```bash
uv run pytest backend/ shared/ 2>&1 | tail -40
```

Expected: all tests PASS. No failures in other adapters or unrelated modules.

- [ ] **Step 8: Commit backend changes**

```bash
git add backend/modules/llm/_adapters/_nano_gpt_http.py \
        backend/tests/modules/llm/adapters/test_nano_gpt_http.py
git commit -m "Add defensive reasoning_effort and reasoning field fallback to nano-gpt adapter"
```

Expected: clean commit, one file for src, one for tests.

---

### Task 4: TypeScript type — `ModelMetaDto.billing_category`

Add the new field to the frontend DTO. Optional for backwards compat with older cached payloads that may still be `null` or missing.

**Files:**
- Modify: `frontend/src/core/types/llm.ts` (interface `ModelMetaDto`, near line 71)

- [ ] **Step 1: Add the field**

In `frontend/src/core/types/llm.ts`, locate the `ModelMetaDto` interface (line 71). After the `is_deprecated?: boolean` field (around line 89), insert:

```ts
  /**
   * How this model bills the user. ``free`` = no cost, ``subscription`` =
   * covered by an upstream plan (Ollama Cloud, nano-gpt subscription tier),
   * ``pay_per_token`` = metered. Optional for backwards compat with older
   * cached payloads — treat missing/null as "unknown".
   */
  billing_category?: 'free' | 'subscription' | 'pay_per_token' | null
```

- [ ] **Step 2: Verify TypeScript compilation**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm tsc --noEmit
```

Expected: no errors. The field is optional so no existing construction sites break.

- [ ] **Step 3: No commit yet**

Tasks 4–6 share a single frontend commit.

---

### Task 5: `BillingFilter` union, filter-logic extension, and unit tests

Extend `modelFilters.ts` with the new union type, the `billing` field on `ModelFilters`, and the clause in `applyModelFilters`. Add a colocated Vitest file covering the 5 × 4 behaviour matrix.

**Files:**
- Create: `frontend/src/app/components/model-browser/modelFilters.test.ts`
- Modify: `frontend/src/app/components/model-browser/modelFilters.ts`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/app/components/model-browser/modelFilters.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import type { EnrichedModelDto } from '../../../core/types/llm'
import { applyModelFilters, type BillingFilter } from './modelFilters'

function makeModel(
  billing: 'free' | 'subscription' | 'pay_per_token' | null | undefined,
  overrides: Partial<EnrichedModelDto> = {},
): EnrichedModelDto {
  return {
    connection_id: 'c1',
    connection_slug: 's',
    connection_display_name: 'D',
    model_id: 'm1',
    display_name: 'Model',
    context_window: 128000,
    supports_reasoning: false,
    supports_vision: false,
    supports_tool_calls: false,
    parameter_count: null,
    raw_parameter_count: null,
    quantisation_level: null,
    unique_id: 's:m1',
    billing_category: billing === undefined ? undefined : billing,
    user_config: null,
    ...overrides,
  } as EnrichedModelDto
}

describe('applyModelFilters — billing', () => {
  const free = makeModel('free', { model_id: 'free-m', unique_id: 's:free-m' })
  const sub = makeModel('subscription', { model_id: 'sub-m', unique_id: 's:sub-m' })
  const pay = makeModel('pay_per_token', { model_id: 'pay-m', unique_id: 's:pay-m' })
  const unknown = makeModel(null, { model_id: 'unk-m', unique_id: 's:unk-m' })
  const all = [free, sub, pay, unknown]

  it('all (or undefined) lets everything through', () => {
    expect(applyModelFilters(all, {})).toEqual(all)
    expect(applyModelFilters(all, { billing: 'all' })).toEqual(all)
  })

  it('no_per_token keeps free + subscription, drops pay_per_token and unknown', () => {
    const result = applyModelFilters(all, { billing: 'no_per_token' })
    expect(result.map((m) => m.model_id).sort()).toEqual(['free-m', 'sub-m'])
  })

  it('free keeps only free, drops subscription/pay/unknown', () => {
    const result = applyModelFilters(all, { billing: 'free' })
    expect(result.map((m) => m.model_id)).toEqual(['free-m'])
  })

  it('subscription keeps only subscription, drops the rest', () => {
    const result = applyModelFilters(all, { billing: 'subscription' })
    expect(result.map((m) => m.model_id)).toEqual(['sub-m'])
  })

  it('pay_per_token keeps only pay_per_token, drops the rest', () => {
    const result = applyModelFilters(all, { billing: 'pay_per_token' })
    expect(result.map((m) => m.model_id)).toEqual(['pay-m'])
  })

  it('null billing_category is excluded by every filter except all', () => {
    const filters: BillingFilter[] = [
      'no_per_token',
      'free',
      'subscription',
      'pay_per_token',
    ]
    for (const billing of filters) {
      const result = applyModelFilters([unknown], { billing })
      expect(result, `filter=${billing}`).toEqual([])
    }
  })

  it('billing filter composes with capability filters', () => {
    const visionFree = makeModel('free', {
      model_id: 'vf', unique_id: 's:vf', supports_vision: true,
    })
    const visionPay = makeModel('pay_per_token', {
      model_id: 'vp', unique_id: 's:vp', supports_vision: true,
    })
    const textFree = makeModel('free', { model_id: 'tf', unique_id: 's:tf' })
    const result = applyModelFilters(
      [visionFree, visionPay, textFree],
      { billing: 'free', capVision: true },
    )
    expect(result.map((m) => m.model_id)).toEqual(['vf'])
  })
})
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm vitest run src/app/components/model-browser/modelFilters.test.ts
```

Expected: the test file fails to import (`BillingFilter` not exported) or the first filter-check fails (`billing` field not recognised).

- [ ] **Step 3: Extend `modelFilters.ts`**

In `frontend/src/app/components/model-browser/modelFilters.ts`:

Add the new union export at the top of the file, after the `EnrichedModelDto` import:

```ts
export type BillingFilter =
  | 'all'
  | 'no_per_token'
  | 'free'
  | 'subscription'
  | 'pay_per_token'
```

Extend the `ModelFilters` interface with the optional field:

```ts
export interface ModelFilters {
  search?: string
  favouritesOnly?: boolean
  capTools?: boolean
  capVision?: boolean
  capReason?: boolean
  showHidden?: boolean
  billing?: BillingFilter
}
```

Add a clause to `applyModelFilters`, immediately before the `filters.search` clause:

```ts
    if (filters.billing && filters.billing !== 'all') {
      const cat = m.billing_category ?? null
      if (cat === null) return false
      switch (filters.billing) {
        case 'no_per_token':
          if (cat !== 'free' && cat !== 'subscription') return false
          break
        case 'free':
          if (cat !== 'free') return false
          break
        case 'subscription':
          if (cat !== 'subscription') return false
          break
        case 'pay_per_token':
          if (cat !== 'pay_per_token') return false
          break
      }
    }
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pnpm vitest run src/app/components/model-browser/modelFilters.test.ts
```

Expected: every test in the new file PASSES.

- [ ] **Step 5: Run the full frontend test suite to catch regressions**

```bash
pnpm vitest run
```

Expected: all tests PASS. The other suites are unaffected because `billing` is optional.

- [ ] **Step 6: No commit yet**

Tasks 4–6 share a single commit.

---

### Task 6: UI dropdown in `ModelBrowser.tsx`

Add the single-select dropdown to the filter bar, wire it to a `useState<BillingFilter>`, and merge it into `effectiveFilters`.

**Files:**
- Modify: `frontend/src/app/components/model-browser/ModelBrowser.tsx`

- [ ] **Step 1: Update the `modelFilters` import**

In `ModelBrowser.tsx`, replace the existing import:

```tsx
import { applyModelFilters, slugWithoutConnection, sortModels, type ModelFilters } from './modelFilters'
```

with:

```tsx
import { applyModelFilters, slugWithoutConnection, sortModels, type BillingFilter, type ModelFilters } from './modelFilters'
```

- [ ] **Step 2: Add billing state and merge into `effectiveFilters`**

Locate in `ModelBrowser.tsx` (around line 37):

```tsx
  const [providerFilter, setProviderFilter] = useState<string>('')
  const [configModel, setConfigModel] = useState<EnrichedModelDto | null>(null)
```

Insert a new state hook between them:

```tsx
  const [providerFilter, setProviderFilter] = useState<string>('')
  const [billingFilter, setBillingFilter] = useState<BillingFilter>('all')
  const [configModel, setConfigModel] = useState<EnrichedModelDto | null>(null)
```

In the `effectiveFilters` memo (around line 41), add `billing: billingFilter` to the returned object and add `billingFilter` to the dependency array:

```tsx
  const effectiveFilters = useMemo<ModelFilters>(() => ({
    ...filters,
    search,
    billing: billingFilter,
    capTools: filters.capTools || !!lockedFilters?.capTools,
    capVision: filters.capVision || !!lockedFilters?.capVision,
    capReason: filters.capReason || !!lockedFilters?.capReason,
  }), [filters, search, billingFilter, lockedFilters])
```

- [ ] **Step 3: Add the dropdown to the filter bar**

Locate the provider `<select>` (around lines 112–124). Immediately after its closing `</select>` tag and before the first `<Chip>`, insert:

```tsx
        <select
          value={billingFilter}
          onChange={(e) => setBillingFilter(e.target.value as BillingFilter)}
          className="rounded border border-white/15 bg-black/30 px-2 py-1 text-[12px] text-white/80"
          aria-label="Filter by billing category"
        >
          <option value="all" style={OPTION_STYLE}>All billing</option>
          <option value="no_per_token" style={OPTION_STYLE}>No per-token cost</option>
          <option value="free" style={OPTION_STYLE}>Free only</option>
          <option value="subscription" style={OPTION_STYLE}>Subscription only</option>
          <option value="pay_per_token" style={OPTION_STYLE}>Pay per token</option>
        </select>
```

- [ ] **Step 4: Verify TypeScript compilation**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 5: Production build check**

```bash
pnpm run build
```

Expected: build completes cleanly with no type errors and no missing-import warnings.

- [ ] **Step 6: Commit frontend changes**

```bash
cd /home/chris/workspace/chatsune
git add frontend/src/core/types/llm.ts \
        frontend/src/app/components/model-browser/modelFilters.ts \
        frontend/src/app/components/model-browser/modelFilters.test.ts \
        frontend/src/app/components/model-browser/ModelBrowser.tsx
git commit -m "Add global billing-category filter to ModelBrowser"
```

---

### Task 7: Full verification pass + merge

**Files:** none modified.

- [ ] **Step 1: Backend full suite**

```bash
cd /home/chris/workspace/chatsune
uv run pytest backend/ shared/ 2>&1 | tail -40
```

Expected: all tests PASS.

- [ ] **Step 2: Frontend type-check + full test suite**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm tsc --noEmit && pnpm vitest run
```

Expected: no TS errors, every Vitest suite PASSES.

- [ ] **Step 3: Grep check — no stray reasoning body flags on non-thinking paths**

```bash
cd /home/chris/workspace/chatsune
rg -n "reasoning_effort|\"reasoning\"|'reasoning'" backend/modules/llm/_adapters/_nano_gpt_http.py
```

Expected: every match is either inside the `if is_thinking_slug:` block, inside the docstring, inside `_chunk_to_events` (reading the response-side `delta.reasoning`), or inside a docstring line. No unconditional body assignment.

- [ ] **Step 4: Manual verification (runs at end of session, Chris does this)**

These steps are **for Chris** — do not attempt to execute them from the subagent.

1. `docker compose up -d` and tail backend logs (`docker logs chatsune-backend --tail 50 -f`) — verify clean startup.
2. Open the chat UI, pick a nano-gpt thinking-capable model (e.g. `anthropic/claude-opus-4.6`), toggle reasoning **ON**, send a prompt. Expected: thinking pill appears within a few seconds of TTFT and the reasoning trace streams continuously; content follows.
3. Same model, reasoning **OFF**. Expected: content streams from TTFT with no thinking pill. With `LLM_TRACE_PAYLOADS=1` set, confirm the outgoing trace log shows **no** `reasoning_effort` key.
4. A pay-per-token-only nano-gpt model whose pair-map entry has `thinking_slug: null` (e.g. a free/phi-small if present in your dump), reasoning toggled **ON** in the UI. Expected: no `reasoning_effort` in the outgoing body (capability-gated fallback).
5. Open the Model Browser. Pick `No per-token cost` from the new billing dropdown. Expected: xAI/Mistral rows disappear; nano-gpt subscription rows remain; Community / Ollama-local rows remain. Switch to `Pay per token`: only xAI/Mistral/nano-gpt metered rows remain. Switch back to `All billing`: everything reappears.

- [ ] **Step 5: Merge to master**

```bash
cd /home/chris/workspace/chatsune
git checkout master
git merge --no-ff nano-gpt-billing-filter-and-thinking \
  -m "Merge branch 'nano-gpt-billing-filter-and-thinking'"
```

Expected: fast-forward merge completes cleanly, master is now on the feature branch's tip.

- [ ] **Step 6: Confirm final state**

```bash
git log --oneline -5
git status
```

Expected: `git status` clean; `git log` shows the merge commit, the two feature commits (backend + frontend), and the spec commit.

---

## Self-Review Checklist

**1. Spec coverage** — every spec section has a corresponding task?

- ✅ Workstream 1 UI placement — Task 6 Step 3
- ✅ Workstream 1 five dropdown options — Task 6 Step 3
- ✅ `billing_category == null` handling — Task 5 Step 3 (filter clause) + Task 5 Step 1 (dedicated test)
- ✅ Filter logic / `BillingFilter` union — Task 5 Step 3
- ✅ `ModelMetaDto.billing_category` TypeScript type — Task 4 Step 1
- ✅ `useState` + merge into `effectiveFilters` — Task 6 Steps 2–3
- ✅ Workstream 1 Vitest file — Task 5 (creation + tests)
- ✅ Workstream 2 Fix A (`delta.reasoning` field fallback) — Task 1
- ✅ Workstream 2 Fix B (`reasoning_effort` gated flag) — Task 2 + Task 3
- ✅ Module docstring revision — Task 3 Step 4
- ✅ Hard-coded `"medium"` effort — Task 2 Step 3 (implementation), Task 3 Step 1 (e2e assertion)
- ✅ Tests — Tasks 1, 2, 3, 5 each have dedicated test steps
- ✅ Build verification — Task 6 Step 5 (pnpm build) + Task 3 Step 6 (py_compile) + Task 7 Steps 1–2
- ✅ Manual verification steps — Task 7 Step 4
- ✅ Commit plan (2 commits) — Task 3 Step 8 (backend) + Task 6 Step 6 (frontend)
- ✅ Merge to master — Task 7 Step 5

**2. Placeholder scan** — any TBD/TODO/"implement later"?

- None. Every step has runnable commands or inline code blocks. Branch name is fixed (`nano-gpt-billing-filter-and-thinking`).

**3. Type consistency**

- `_build_chat_payload(request, upstream_slug, *, is_thinking_slug)` — signature identical in Task 2 Steps 1 (tests) and 3 (impl), Task 3 Step 3 (call site).
- `BillingFilter` union identical in Task 5 (type decl + tests) and Task 6 (import + state type).
- `ModelFilters.billing` optional field identical in Task 5 Step 3 and Task 6 Step 2.
- `billing_category` field shape consistent in Task 4 (TS type) and Task 5 (filter clause reads `m.billing_category`).
- `"medium"` literal used identically in Task 2 Step 3 (impl), Task 3 Step 1 (e2e assertion), Task 7 Step 3 (grep anchor).
- Test fixture reuse: `_resolved_conn()`, `_populate_pair_map()`, `_FakeClient`, `_FakeResponse`, `_make_request()` all defined in the existing Phase-2 test file and reused verbatim by Tasks 1–3.

---

## Execution Handoff

**Plan saved.** Subagent-Driven Execution via `superpowers:subagent-driven-development` per Chris' standing preference (global: "Subagent preferred", project: "subagent driven implementation always").

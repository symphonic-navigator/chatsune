# DeepSeek V4 nano-gpt Capability-only Driver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add nano-gpt support to the DeepSeek V4 driver layer as a *capability-only* extension — the driver supplies the canonical DSv4 capability spec for nano-gpt slugs (on/off-only reasoning, no effort buckets, slug-based first-class differentiation) while the existing nano-gpt adapter retains full ownership of wire-shape translation (build_request, parse_chunk, slug-pair switching).

**Architecture:** Extend `deepseek_v4_capability_spec` with a `nano_gpt_http` branch that returns `kind=optional` reasoning **without** an effort spec (so the UI shows only an on/off toggle), and uses a slug-classifier helper to mark `TEE/*` and `*-cheaper` variants as `first_class_support=False`. The `DeepSeekV4Driver.build_request` and `parse_chunk` methods continue to raise `NotImplementedError` for `nano_gpt_http` — this is *by design*, not a TODO. The nano-gpt adapter's existing slug-pair-switching mechanism (`_nano_gpt_http.py:402-424`) and OR-style reasoning parsing (`_nano_gpt_http.py:188`) cover wire-shape needs adequately.

**Tech Stack:** Python 3, Pydantic v2, pytest. Pure backend changes; no frontend code touched (the existing UI logic already collapses `effort=None` into an on/off-only toggle, and the model browser already renders `first_class_support` prominently).

---

## Background and Empirical Context

The full empirical probe results live in Task 1's research doc. The headline findings:

- **Slug list (verified 2026-05-10 via `GET /v1/models`)**: `deepseek/deepseek-v4-{pro,flash}` plus `:thinking` pair-suffixed variants are the first-class targets. `TEE/deepseek-v4-pro` (half-vLLM, incomplete upstream) and `deepseek/deepseek-v4-pro-cheaper` (Chinese upstream — privacy-undesirable) also appear and are deliberately classified as non-first-class.
- **Reasoning wire-key**: `delta.reasoning` (OR-unified shape), with redundant `delta.reasoning_details` array. The existing `_nano_gpt_http._chunk_to_events` already reads `delta.reasoning` correctly.
- **Tool-call wire-shape**: atomic — a single chunk carries the full `tool_calls` array, no fragmenting. Existing nano-gpt adapter uses an accumulator that handles atomic delivery as a degenerate case (works fine).
- **Off-signal**: not needed — nano-gpt's existing slug-pair mechanism (`:thinking` suffix on/off) already encodes thinking-mode in the URL slug. No `enable_thinking` or `reasoning.enabled` field manipulation is required.
- **Effort vocabulary**: deliberately *not* exposed for nano-gpt. Per product decision, on/off-only is the supported surface ("best effort, not gold-plating" — nano-gpt's track record on basic feature pflege is weak; user wants minimal driver coupling).
- **Telemetry quirk**: `reasoning_tokens=0` even when reasoning text is present (nano-gpt server-side bug; we ignore it — the reasoning *content* is correct, only the counter is wrong). Existing parser does not depend on this counter for correctness.
- **Cache visibility**: API does emit `cached_tokens` field; field stays at 0 in observed traffic. The pre-existing memory note about UI/dashboard cache-visibility (OR has it, nano-gpt does not) remains valid for tester-facing QA workflows.

---

## File Structure

**Create:**
- `devdocs/research/dsv4-nano-gpt-wire-shapes.md` — empirical probe doc (Task 1)

**Modify:**
- `backend/modules/llm/_drivers/deepseek_v4/_capability.py` — add nano-gpt branch and helper (Task 2)
- `backend/modules/llm/tests/test_deepseek_v4_driver.py` — update parametrised tests, add nano-gpt-specific tests (Task 3)
- `INSIGHTS.md` — INS-043 entry (Task 4)

**Unchanged but referenced:**
- `backend/modules/llm/_drivers/deepseek_v4/__init__.py` — `DeepSeekV4Driver.build_request` and `parse_chunk` keep raising `NotImplementedError` for `nano_gpt_http`. Comment in those methods is updated in Task 3 to clarify "capability-only by design".
- `backend/modules/llm/_adapters/_nano_gpt_http.py` — no changes; the adapter's `stream_completion` path does NOT call into the driver's wire helpers.

---

## Task 1: Empirical wire-shape research doc

**Files:**
- Create: `devdocs/research/dsv4-nano-gpt-wire-shapes.md`

**Why first:** The capability decisions in Task 2 reference this doc. Writing it down up front means Task 2's tests can cite the probe verbatim instead of paraphrasing.

- [ ] **Step 1: Create the research doc**

Use this exact structure (mirrors the prior DSv4 wire-shape docs for OR/Ollama/Novita):

````markdown
# DeepSeek V4 wire shapes — nano-gpt

**Probed:** 2026-05-10
**Endpoint:** `https://nano-gpt.com/api/v1/chat/completions`
**Models probed:** `deepseek/deepseek-v4-pro:thinking`, `deepseek/deepseek-v4-flash:thinking`

## Q1 — slug catalogue

`GET /v1/models` returns the following DSv4-related slugs:

```
deepseek/deepseek-v4-flash
deepseek/deepseek-v4-flash:thinking
deepseek/deepseek-v4-pro
deepseek/deepseek-v4-pro:thinking
deepseek/deepseek-v4-pro-cheaper
deepseek/deepseek-v4-pro-cheaper:thinking
TEE/deepseek-v4-pro
TEE/deepseek-v4-pro:thinking
```

The four `:thinking`-suffixed entries pair automatically with their non-suffixed
counterparts via the existing `_nano_gpt_catalog._detect_suffix` logic
(switching_mode = "slug"). The `model_id` exposed to chatsune is the
non-thinking slug; the thinking slug is selected at request time when
`reasoning_mode="on"` (`_nano_gpt_http.py:402-424`).

### First-class classification

We mark only the canonical `deepseek/deepseek-v4-{pro,flash}` family as
first-class. The other two upstream paths are intentionally not curated:

- `TEE/deepseek-v4-*` — TEE is an incomplete vLLM-derived deployment; quirks
  upstream are not worth chatsune support burden.
- `deepseek/deepseek-v4-*-cheaper` — routes via the Chinese DeepSeek upstream;
  privacy-first product stance keeps these visible (users may opt in) but
  off the curated/recommended path.

Both are still streamable via the regular nano-gpt adapter; they simply do
not receive the `first_class_support=True` UI signal.

## Q2 — reasoning wire-key

The default `/api/v1/chat/completions` endpoint streams reasoning in
`delta.reasoning` (OR-unified shape), with a parallel `delta.reasoning_details`
array carrying typed fragments. Example chunk fragment:

```json
{"choices":[{"index":0,"delta":{
  "reasoning":"We are",
  "reasoning_details":[{"type":"reasoning.text","text":"We are","format":"unknown","index":0}],
  "content":""
},"finish_reason":null}]}
```

The existing `_nano_gpt_http._chunk_to_events` (line ~188) already reads
`delta.reasoning` (and falls back to legacy `delta.reasoning_content`). No
parser change is needed for the driver to function on nano-gpt.

## Q3-Q4 — effort vocabulary and on/off signal

Skipped by product decision: nano-gpt is exposed as on/off only. The
existing slug-pair mechanism (`:thinking` suffix) is the canonical
on/off encoding; the driver's nano-gpt capability spec deliberately
publishes `effort=None` (no buckets) so the UI shows only the toggle.

## Q5 — Flash + reasoning health

`deepseek/deepseek-v4-flash:thinking` produces coherent reasoning text.
**Telemetry quirk:** the `usage.reasoning_tokens` field is consistently
`0` despite reasoning content being present in the stream. This is a
nano-gpt server-side bug (counter not populated); we ignore it.
The reasoning *content* is correct.

## Q6 — tool-call wire-shape

Atomic. A single chunk carries the full `tool_calls` array:

```json
{"choices":[{"index":0,"delta":{
  "tool_calls":[{
    "index":0,
    "id":"call_00_JFoVArF7Sywzl32dCDhh5437",
    "type":"function",
    "function":{
      "arguments":"{\"city\": \"Vienna\"}",
      "name":"get_weather"
    }
  }]
},"finish_reason":null}]}
```

Unlike OR / Novita, nano-gpt does not fragment tool-call arguments
across multiple chunks. The existing `_nano_gpt_http` accumulator handles
atomic delivery as a degenerate case (one fragment carrying the full args).

## Q7 — cache visibility

The `usage` block exposes `cached_tokens` and `cache_read_input_tokens`,
but both stayed at `0` in repeat-prompt probing. This is consistent with
the existing reference memory note: nano-gpt's *dashboard* shows no
cache split, and the API surface technically exposes the field but
appears not to populate it (or caching is not active for these requests).
For QA work that depends on cache validation visibility, OR remains the
preferred test path.

---

## Driver implications

This driver is a **capability-only extension**:

- Capability spec (`deepseek_v4_capability_spec`) gains a
  `nano_gpt_http` branch that emits `kind=optional`, `effort=None`,
  `default_on=True`, and a slug-classifier-derived
  `first_class_support` boolean.
- `DeepSeekV4Driver.build_request` / `parse_chunk` continue to raise
  `NotImplementedError` for `nano_gpt_http` — by design. The nano-gpt
  adapter's existing wire-shape handling is sufficient.
````

- [ ] **Step 2: Commit**

```bash
git add devdocs/research/dsv4-nano-gpt-wire-shapes.md
git commit -m "Add DSv4 nano-gpt wire-shape research doc"
```

---

## Task 2: Add nano-gpt branch to capability spec

**Files:**
- Modify: `backend/modules/llm/_drivers/deepseek_v4/_capability.py`

**Why:** Drive the on/off-only UX for nano-gpt and the slug-based first-class differentiation. This is a pure addition — existing OR/Ollama/Novita behaviour is unchanged.

- [ ] **Step 1: Write the failing tests**

Add these to `backend/modules/llm/tests/test_deepseek_v4_driver.py` (place after the existing `test_capability_spec_buckets` parametrised test, around line 792):

```python
@pytest.mark.parametrize(
    "slug,expected_first_class",
    [
        # Curated DSv4 family — first class
        ("deepseek/deepseek-v4-pro", True),
        ("deepseek/deepseek-v4-flash", True),
        # Pair-suffixed variants — first class (model_id == non-thinking slug,
        # but defence-in-depth: classifier handles the suffixed form too).
        ("deepseek/deepseek-v4-pro:thinking", True),
        ("deepseek/deepseek-v4-flash:thinking", True),
        # TEE upstream — not first class (incomplete vLLM-derived deploy)
        ("TEE/deepseek-v4-pro", False),
        ("TEE/deepseek-v4-pro:thinking", False),
        # *-cheaper upstream — not first class (privacy-undesired Chinese path)
        ("deepseek/deepseek-v4-pro-cheaper", False),
        ("deepseek/deepseek-v4-pro-cheaper:thinking", False),
    ],
)
def test_capability_spec_nano_gpt_first_class(
    slug: str, expected_first_class: bool,
) -> None:
    """nano-gpt capability spec marks only the curated DSv4 family
    as first class. TEE/* and *-cheaper are visible-but-not-curated."""
    spec = deepseek_v4_capability_spec(adapter_type="nano_gpt_http", slug=slug)
    assert spec.first_class_support is expected_first_class


def test_capability_spec_nano_gpt_has_no_effort_buckets() -> None:
    """nano-gpt is exposed as on/off only — no effort buckets, so the UI
    collapses to a single toggle. Slug-pair switching at the adapter
    layer (existing logic) handles thinking-mode encoding."""
    spec = deepseek_v4_capability_spec(
        adapter_type="nano_gpt_http",
        slug="deepseek/deepseek-v4-pro",
    )
    assert spec.reasoning.kind == "optional"
    assert spec.reasoning.default_on is True
    assert spec.reasoning.effort is None
    assert spec.tools.supported is True
    assert spec.tools.exclusive_with_reasoning is False
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/modules/llm/tests/test_deepseek_v4_driver.py \
  -k "test_capability_spec_nano_gpt_first_class or test_capability_spec_nano_gpt_has_no_effort_buckets" \
  -v
```

Expected: FAIL — current capability spec returns `effort` with buckets and unconditional `first_class_support=True` regardless of slug.

- [ ] **Step 3: Add the nano-gpt classifier helper**

In `backend/modules/llm/_drivers/deepseek_v4/_capability.py`, add this helper *above* `deepseek_v4_capability_spec` (after the imports):

```python
# Slugs the chatsune product treats as first-class for DSv4 on nano-gpt.
# The two upstream paths we deliberately exclude:
#   * ``TEE/deepseek-v4-*`` — TEE is an incomplete vLLM-derived upstream;
#     quirks are not worth chatsune support burden.
#   * ``deepseek/deepseek-v4-*-cheaper`` — routes via the Chinese DeepSeek
#     upstream; privacy-first product stance keeps these visible (users
#     may opt in) but off the curated/recommended path.
# Both classes remain streamable via the regular nano-gpt adapter; they
# simply do not get the ``first_class_support=True`` UI signal.
def _is_nano_gpt_first_class(slug: str) -> bool:
    """Return True for the curated DSv4 family on nano-gpt.

    Curated set: ``deepseek/deepseek-v4-pro`` and ``deepseek/deepseek-v4-flash``,
    with optional ``:thinking`` pair-suffix. Excluded: ``TEE/*`` and
    ``*-cheaper`` variants. Case-insensitive on the upstream prefix to
    survive any future casing drift in nano-gpt's catalogue (the
    ``-cheaper`` token is also matched case-insensitively).
    """
    lower = slug.lower()
    if lower.startswith("tee/"):
        return False
    if "-cheaper" in lower:
        return False
    # Strip optional :thinking pair-suffix before matching the family.
    base = lower[: -len(":thinking")] if lower.endswith(":thinking") else lower
    return base in (
        "deepseek/deepseek-v4-pro",
        "deepseek/deepseek-v4-flash",
    )
```

- [ ] **Step 4: Add the nano-gpt branch to `deepseek_v4_capability_spec`**

Modify the body of `deepseek_v4_capability_spec` so it short-circuits for nano-gpt before the existing OR-Flash-quirk logic. The full updated function body:

```python
def deepseek_v4_capability_spec(
    *,
    adapter_type: str,
    slug: str,
) -> ResolvedCapabilities:
    """Return the DeepSeek V4 capability spec for (adapter_type, slug).

    Default: ``buckets=["high","max"]``. Override: when the OR-Flash
    quirk applies (see ``_quirks.py``), drop ``"max"`` from the buckets
    list. Re-probe quarterly; drop the override branch when fixed.

    nano-gpt: on/off only — no effort buckets exposed (slug-pair
    switching at the adapter layer encodes thinking mode). Slug-based
    ``first_class_support`` differentiation: curated DSv4 family yes,
    ``TEE/*`` and ``*-cheaper`` no.
    """
    if adapter_type == "nano_gpt_http":
        return ResolvedCapabilities(
            reasoning=ReasoningCapability(
                kind="optional",
                effort=None,
                default_on=True,
            ),
            tools=ToolCapability(
                supported=True,
                exclusive_with_reasoning=False,
            ),
            first_class_support=_is_nano_gpt_first_class(slug),
        )

    if _is_or_flash_quirk_applicable(adapter_type, slug):
        # OR-quirk override (probed 2026-05-10): xhigh halves Flash
        # reasoning. Re-probe via dsv4_flash_or_drift.py; next due
        # 2026-08-10. Drop this branch when the probe flips to FIXED.
        buckets = ["high"]
    else:
        buckets = ["high", "max"]

    return ResolvedCapabilities(
        reasoning=ReasoningCapability(
            kind="optional",
            effort=ReasoningEffortSpec(
                buckets=buckets,
                default_bucket="high",
            ),
            default_on=True,
        ),
        tools=ToolCapability(
            supported=True,
            exclusive_with_reasoning=False,
        ),
        first_class_support=True,
    )
```

- [ ] **Step 5: Run the new tests to verify they pass**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/modules/llm/tests/test_deepseek_v4_driver.py \
  -k "test_capability_spec_nano_gpt_first_class or test_capability_spec_nano_gpt_has_no_effort_buckets" \
  -v
```

Expected: PASS (10 parametrised cases + 1 plain test = 11 passing).

- [ ] **Step 6: Add a direct unit test for the helper**

Add to the test file (immediately after the new tests from Step 1):

```python
@pytest.mark.parametrize(
    "slug,expected",
    [
        ("deepseek/deepseek-v4-pro", True),
        ("deepseek/deepseek-v4-flash", True),
        ("deepseek/deepseek-v4-pro:thinking", True),
        ("deepseek/deepseek-v4-flash:thinking", True),
        # Case-insensitive on the upstream prefix
        ("DEEPSEEK/DEEPSEEK-V4-PRO", True),
        ("TEE/deepseek-v4-pro", False),
        ("tee/deepseek-v4-pro", False),  # case-insensitive TEE check
        ("TEE/deepseek-v4-pro:thinking", False),
        ("deepseek/deepseek-v4-pro-cheaper", False),
        ("deepseek/deepseek-v4-pro-cheaper:thinking", False),
        # Unrelated slug — not first-class either (helper returns False
        # by virtue of the family check; capability_spec wouldn't even
        # call this helper for non-DSv4 slugs because the driver's
        # PATTERNS list filters those upstream of resolve_capabilities).
        ("anthropic/claude-3-5-sonnet", False),
    ],
)
def test_is_nano_gpt_first_class(slug: str, expected: bool) -> None:
    from backend.modules.llm._drivers.deepseek_v4._capability import (
        _is_nano_gpt_first_class,
    )
    assert _is_nano_gpt_first_class(slug) is expected
```

- [ ] **Step 7: Run all tests in the file to verify nothing else broke**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/modules/llm/tests/test_deepseek_v4_driver.py -v
```

Expected: ALL pass — including the existing `test_dsv4_driver_build_request_for_unsupported_adapter_raises` and `test_dsv4_driver_parse_chunk_for_unsupported_adapter_raises`, which still expect `NotImplementedError` for `nano_gpt_http` (this plan does NOT change that behaviour).

- [ ] **Step 8: Verify backend syntax**

```bash
uv run python -m py_compile backend/modules/llm/_drivers/deepseek_v4/_capability.py
```

Expected: silent (no syntax errors).

- [ ] **Step 9: Commit**

```bash
git add backend/modules/llm/_drivers/deepseek_v4/_capability.py \
        backend/modules/llm/tests/test_deepseek_v4_driver.py
git commit -m "Add nano-gpt branch to DSv4 capability spec (on/off only, slug-based first-class)"
```

---

## Task 3: Reconcile pre-existing parametrised tests + clarify NotImplementedError comments

**Files:**
- Modify: `backend/modules/llm/tests/test_deepseek_v4_driver.py`
- Modify: `backend/modules/llm/_drivers/deepseek_v4/__init__.py`

**Why:** Two pre-existing tests now have stale assumptions about nano-gpt:

1. `test_deepseek_v4_capability_spec_is_router_agnostic_for_now` (line 60-66) compares OR vs nano-gpt capabilities and asserts equality. Now they diverge — nano-gpt has no effort buckets.
2. `test_capability_spec_buckets` parametrised case `("nano_gpt_http", "deepseek/deepseek-v4-flash", ["high", "max"])` (line 782) asserts buckets exist. With the nano-gpt branch, `effort` is `None`, so accessing `.effort.buckets` would crash.

We also rephrase the docstring/comments on the `NotImplementedError` branches in `DeepSeekV4Driver.build_request` and `parse_chunk` to clarify that nano-gpt is a *capability-only* deliberate choice, not a future TODO.

- [ ] **Step 1: Remove the stale "router-agnostic" test**

Delete `test_deepseek_v4_capability_spec_is_router_agnostic_for_now` entirely (the two specs no longer have a shared invariant worth asserting; per-router capability divergence is exactly what the driver layer was built for). Keep the OR-specific `test_deepseek_v4_capability_spec_for_openrouter` test as the canonical OR baseline check.

- [ ] **Step 2: Remove the stale nano-gpt parametrised case from `test_capability_spec_buckets`**

In the parametrise table for `test_capability_spec_buckets`, delete this row:

```python
("nano_gpt_http", "deepseek/deepseek-v4-flash", ["high", "max"]),
```

The remaining rows (OR + Flash, OR + Pro, Ollama variants, Novita) still validate the bucket-bearing path. nano-gpt's no-bucket path is covered by `test_capability_spec_nano_gpt_has_no_effort_buckets` from Task 2.

- [ ] **Step 3: Update the comment on the parametrise table**

Replace the inline comment line that read

```python
        # Future adapters keep the default until probed
```

with

```python
        # Future un-driver-aware adapters keep the default until probed.
        # nano-gpt has its own driver branch (Task 2) — covered separately.
```

- [ ] **Step 4: Run the modified test file to verify all pass**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/modules/llm/tests/test_deepseek_v4_driver.py -v
```

Expected: ALL pass.

- [ ] **Step 5: Update the NotImplementedError comments in the driver class**

In `backend/modules/llm/_drivers/deepseek_v4/__init__.py`, update the two `raise NotImplementedError(...)` messages to make clear that the nano-gpt arm is by design.

Replace both messages (in `build_request` and `parse_chunk`) — locate the existing string

```
"DeepSeekV4Driver: adapter_type={adapter_type!r} not supported "
"yet (Plans 1-3 cover openrouter_http + ollama_http + "
"novita_http; Plan 4 adds nano_gpt_http)."
```

with

```
"DeepSeekV4Driver: adapter_type={adapter_type!r} has no driver-level "
"wire support. nano_gpt_http is capability-only by design — the "
"adapter's own slug-pair switching and OR-style chunk parser are "
"sufficient. Other adapter_types: not yet integrated."
```

Apply the same replacement to both methods (`build_request` and `parse_chunk`).

Also update the class docstring at the top of `DeepSeekV4Driver`:

Replace:

```
    """Driver for DeepSeek V4 Pro and DeepSeek V4 Flash.

    Plan 1: OpenRouter. Plan 2: + Ollama Cloud. Plan 3: + Novita (this
    class). Plan 4 adds nano-gpt.
    """
```

with:

```
    """Driver for DeepSeek V4 Pro and DeepSeek V4 Flash.

    Wire support: OpenRouter, Ollama Cloud, Novita (per-adapter
    builders + parsers). Capability-only support: nano-gpt — the
    driver supplies the canonical DSv4 capability spec while the
    nano-gpt adapter retains full ownership of wire-shape translation
    (slug-pair switching, OR-style reasoning parsing, atomic
    tool-call delivery).
    """
```

- [ ] **Step 6: Run the full DSv4 driver test file again to confirm**

```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
  backend/modules/llm/tests/test_deepseek_v4_driver.py -v
```

Expected: ALL pass.

- [ ] **Step 7: Verify backend syntax**

```bash
uv run python -m py_compile backend/modules/llm/_drivers/deepseek_v4/__init__.py
```

Expected: silent.

- [ ] **Step 8: Commit**

```bash
git add backend/modules/llm/tests/test_deepseek_v4_driver.py \
        backend/modules/llm/_drivers/deepseek_v4/__init__.py
git commit -m "Reconcile DSv4 tests + driver docstrings with nano-gpt capability-only path"
```

---

## Task 4: INSIGHTS.md INS-043 — capability-only driver pattern

**Files:**
- Modify: `INSIGHTS.md`

**Why:** Future contributors looking at the driver layer will see four wire-bearing arms (OR, Ollama, Novita, ?) and the "?" for nano-gpt that just raises NotImplementedError. They need a written rationale to avoid filing a bug or "completing" the asymmetry.

- [ ] **Step 1: Append INS-043 to INSIGHTS.md**

Add this entry at the bottom of `INSIGHTS.md` (after the most recent INS- entry — INS-042 per the prior session):

```markdown
## INS-043 — Driver layer capability-only mode (nano-gpt + DSv4)

**Date:** 2026-05-10

**Context:** When integrating DeepSeek V4 across four routers (OR, Ollama
Cloud, Novita, nano-gpt) we found nano-gpt's existing adapter already
covers DSv4 wire-shape needs adequately:

- Slug-pair switching for thinking on/off (`:thinking` suffix) is
  encoded directly in the URL slug — nano-gpt's
  `_nano_gpt_http.py:402-424` handles this without driver help.
- Reasoning streams as `delta.reasoning` (OR-unified shape), already
  parsed by `_nano_gpt_http._chunk_to_events`.
- Tool-calls are delivered atomically (single chunk, full args), which
  the existing accumulator handles as a degenerate case.

The only DSv4-specific knowledge the existing path lacks is the
**capability shape** itself: on/off-only reasoning (no effort buckets,
because nano-gpt's slug-pair encoding already covers thinking mode),
plus a slug-based `first_class_support` differentiation (curated
DSv4 family yes; `TEE/*` and `*-cheaper` upstream paths no).

**Decision:** Introduce a "capability-only driver arm" pattern. The
DSv4 driver's `capability_spec` gains a `nano_gpt_http` branch with
its own logic, while `build_request` and `parse_chunk` continue to
raise `NotImplementedError` for that adapter — *by design, not as a
TODO*.

This shape:

1. Keeps the canonical DSv4 capability truth in one place (the driver),
   so the UI behaves consistently regardless of adapter.
2. Avoids duplicating the nano-gpt adapter's (working) wire-shape code
   into a parallel driver path.
3. Reflects the "best effort, not gold-plating" product stance for
   nano-gpt — we coupled minimally to a provider whose pflege of
   basics has been historically uneven.

**Generalises to:** any future provider where the existing adapter
already implements the wire shape correctly, but the model has
provider-specific capability rules worth centralising. The driver
arm acts purely as a capability lookup; wire calls stay in the
adapter.

**Anti-pattern this prevents:** dispatching a "complete the
asymmetry" task that would copy `build_request_*` and `parse_chunk_*`
into the driver for nano-gpt, duplicating logic and increasing
surface area for drift between the driver arm and the live adapter
path. The `NotImplementedError` messages and class docstring spell
this out so it's not mistaken for unfinished work.

**Slug-based `first_class_support`:** A second sub-decision worth
recording. We were tempted to introduce a "do not recommend" list
or new `is_curated` field, but `first_class_support` already encodes
the right semantic: it's the UI signal for "this is a path the
product recommends." Marking nano-gpt's `TEE/*` and `*-cheaper`
variants as `first_class_support=False` (while still listing them)
matches existing UI behaviour and avoids schema growth.

**Re-probe condition:** if nano-gpt ever introduces effort granularity
on the `:thinking` slug (e.g. `:thinking-max` or a real
`reasoning.effort` parameter that reaches the model), revisit this
to expose buckets. As of 2026-05-10, no such surface exists.
```

- [ ] **Step 2: Commit**

```bash
git add INSIGHTS.md
git commit -m "INS-043: capability-only driver pattern (nano-gpt DSv4)"
```

---

## Task 5: Manual smoke verification

**Files:** none (manual verification by the human user).

**Why:** Backend tests prove correctness of the spec resolution path, but the user-visible signals (UI toggle shape, first-class badge, model browser surface) only show up end-to-end. Per chatsune memory `Manual test sections in specs`, this gets explicit listed steps the human runs.

- [ ] **Step 1: Backend reload sanity**

In dev environment, the backend should auto-reload on branch switch (per memory `Feature-Branches default in Chatsune`). After implementer-subagent's last commit, verify the backend started cleanly:

```bash
docker logs <chatsune-backend-container> --tail 30
```

Expected: no exceptions; capability resolution endpoints respond.

- [ ] **Step 2: Manual verification in the UI**

Reported by Chris (the user) — *not* by the subagent:

1. Connect the existing nano-gpt connection in the model browser.
2. Find `deepseek/deepseek-v4-pro` in the list.
   - **Expected:** "first-class" badge present (the UI's prominent first-class indicator).
   - **Expected:** reasoning toggle is **on/off only**, no effort selector.
3. Find `deepseek/deepseek-v4-flash` analogously.
   - **Expected:** same as Pro — first-class, on/off-only.
4. Find `TEE/deepseek-v4-pro` in the list.
   - **Expected:** **NO** first-class badge.
   - **Expected:** still selectable, still streamable; on/off-only toggle.
5. Find `deepseek/deepseek-v4-pro-cheaper` analogously.
   - **Expected:** **NO** first-class badge; still streamable.
6. Pick `deepseek/deepseek-v4-pro`, enable thinking mode, send a short
   prompt. Verify reasoning content streams (existing behaviour, just
   re-confirming it didn't regress).
7. Pick `deepseek/deepseek-v4-flash`, enable thinking mode, send the
   same prompt. Verify reasoning streams (the telemetry-bug
   `reasoning_tokens=0` is server-side and expected — the
   reasoning *content* must be visible).

If all seven checks pass, the feature is verified. If any check fails,
report the symptom and let Claude diagnose before merging.

---

## Final review (after all tasks)

After Tasks 1-4 complete and Task 5 has been verified by Chris:

1. Run the full DSv4 driver test file one more time as a regression
   gate:

   ```bash
   PYTHONPATH=/home/chris/workspace/chatsune uv run pytest \
     backend/modules/llm/tests/test_deepseek_v4_driver.py -v
   ```

   Expected: every test passes (count: pre-existing ones minus 1
   removed router-agnostic test minus 1 nano-gpt parametrise row,
   plus the new tests added in Tasks 2 and 3).

2. Dispatch the final code-quality reviewer over the cumulative diff
   (Tasks 1-4) before handing back to Chris for the manual smoke and
   the merge step.

The merge / push happens manually (user-driven) per chatsune's
established convention — subagents must not merge, push, or switch
branches.

# Claude Fable 5 via nano-gpt — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `anthropic/claude-fable-*` a first-class model on the nano-gpt route with working effort-based reasoning, cache_control, and hard-CoT replay.

**Architecture:** One capability-YAML entry plus two small adapter touchpoints. The Anthropic-detection regex in `_anthropic_cache.py` learns the `fable` token (enables cache markers + thinking replay on both routers); a new helper `is_effort_based_claude()` punches a hole through the INS-037 effort omission, because Fable's reasoning is a silent no-op without an `effort` value (empirically verified — see the spec).

**Tech Stack:** Python/FastAPI backend, Pydantic v2, pytest. No frontend changes.

**Spec:** `devdocs/specs/2026-06-10-claude-fable-5-nano-gpt-design.md`

**Branch:** work happens on `feature/fable-5-nano-gpt-first-class` (already created, spec committed). Do NOT merge, do NOT push, do NOT switch branches.

**Test invocation (host quirk):** `backend/pyproject.toml` is pytest's configfile, so always prepend `PYTHONPATH=/home/chris/workspace/chatsune` and run from the repo root. None of the files below need MongoDB.

**Spec §4 verification (done during planning, no task needed):**
`extras.reasoning_effort` can never be None while reasoning is on for a
model whose capability declares an effort spectrum:
`remap_extras_for_capability` (`backend/modules/chat/_extras_remap.py:48-53`)
falls back to `default_bucket` whenever the old bucket is absent or
invalid, and `default_extras_for_capability` (same file, line 115) seeds
fresh sessions with `default_bucket`. No silent no-op path exists.

---

### Task 1: Extend Anthropic detection regex + add `is_effort_based_claude()`

**Files:**
- Modify: `backend/modules/llm/_adapters/_anthropic_cache.py:20-46`
- Test: `backend/tests/modules/llm/adapters/test_anthropic_cache.py`

- [ ] **Step 1: Write the failing tests**

In `backend/tests/modules/llm/adapters/test_anthropic_cache.py`, extend the existing positive parametrize list (lines 9–16) with two Fable slugs:

```python
@pytest.mark.parametrize("model_id", [
    "anthropic/claude-3-7-sonnet-20250219",
    "~anthropic/claude-opus-4-1",
    "claude-haiku-4-5",
    "claude-3-7-sonnet-20250219",
    "anthropic/claude-3.5-sonnet-vision",
    "ANTHROPIC/Claude-Sonnet-4-5",
    "anthropic/claude-fable-5",
    "anthropic/claude-fable-latest",
])
def test_is_anthropic_model_positive(model_id: str) -> None:
    assert is_anthropic_model(model_id)
```

Directly below the existing negative test (after line 35), add tests for the new helper:

```python
from backend.modules.llm._adapters._anthropic_cache import is_effort_based_claude


@pytest.mark.parametrize("model_id", [
    "anthropic/claude-fable-5",
    "anthropic/claude-fable-latest",
    "claude-fable-5",
])
def test_is_effort_based_claude_positive(model_id: str) -> None:
    assert is_effort_based_claude(model_id)


@pytest.mark.parametrize("model_id", [
    "anthropic/claude-opus-4.7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
    "openai/gpt-5",
    "gemma-4-31B-Fabled",   # 'Fabled' must not match \bfable\b
    "",
])
def test_is_effort_based_claude_negative(model_id: str) -> None:
    assert not is_effort_based_claude(model_id)
```

Note: `gemma-4-31B-Fabled` is a real nano-gpt slug; `\bfable\b` does not match `Fabled` because there is no word boundary between `fable` and `d` — this case guards exactly that.

- [ ] **Step 2: Run tests to verify the new ones fail**

Run:
```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest backend/tests/modules/llm/adapters/test_anthropic_cache.py -v
```
Expected: the two Fable entries in `test_is_anthropic_model_positive` FAIL (regex does not match yet); `is_effort_based_claude` tests FAIL with ImportError. All pre-existing tests PASS.

- [ ] **Step 3: Implement**

In `backend/modules/llm/_adapters/_anthropic_cache.py`, replace the regex (line 28) and its comment block (lines 20–27), keeping the existing explanation and adding the fable token:

```python
# Match "claude" anywhere in the slug tail, followed by a haiku /
# sonnet / opus / fable token at a word boundary. Older
# "claude-instant-*" slugs deliberately do not match — they predate
# cache_control support, so the negative case is correct behaviour.
# ``[^/]*`` (not ``.*``) bounds the wildcard inside the slug tail.
# ``rsplit("/", 1)[-1]`` already strips any path prefix, so the tail
# cannot contain ``/`` — the bounded form keeps regex evaluation
# linear regardless of slug length.
_CLAUDE_RE = re.compile(r"claude[^/]*\b(haiku|sonnet|opus|fable)\b", re.IGNORECASE)
```

After the `is_anthropic_model` function (line 46), add:

```python
_EFFORT_BASED_CLAUDE_RE = re.compile(r"claude[^/]*\bfable\b", re.IGNORECASE)


def is_effort_based_claude(model_id: str) -> bool:
    """True iff ``model_id`` is a Claude model with effort-based thinking.

    Fable-family models do not start thinking on ``enabled: true``
    alone — the router silently returns a plain completion unless an
    ``effort`` value is present. They therefore bypass the INS-037
    effort omission. Effort is verified cache-safe on these routes;
    see devdocs/specs/2026-06-10-claude-fable-5-nano-gpt-design.md
    and INS-055.
    """
    tail = model_id.rsplit("/", 1)[-1]
    return bool(_EFFORT_BASED_CLAUDE_RE.search(tail))
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest backend/tests/modules/llm/adapters/test_anthropic_cache.py -v
```
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_anthropic_cache.py backend/tests/modules/llm/adapters/test_anthropic_cache.py
git commit -m "Extend Anthropic detection to Fable and add is_effort_based_claude helper"
```

---

### Task 2: nano-gpt adapter — send effort for Fable

**Files:**
- Modify: `backend/modules/llm/_adapters/_nano_gpt_http.py:404-441`
- Test: `tests/modules/llm/test_translation_nano_gpt.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/modules/llm/test_translation_nano_gpt.py` (the file's `_user` and `_req` helpers are at lines 37–55; reuse them):

```python
# ----- Fable: effort-based Claude bypasses the INS-037 omission -----


def _fable_effort_capability() -> ReasoningCapability:
    return ReasoningCapability(
        kind="optional",
        effort=ReasoningEffortSpec(
            buckets=["low", "medium", "high"], default_bucket="medium",
        ),
    )


def test_nano_gpt_fable_keeps_effort():
    """Fable reasons only when effort is present — the INS-037 omission
    does not apply to effort-based Claude (see INS-055)."""
    req = _req(
        "anthropic/claude-fable-5",
        ChatSessionExtras(
            tools_enabled=False, reasoning_mode="on", reasoning_effort="medium",
        ),
        _fable_effort_capability(),
    )
    body, _slug = build_request_body(req)
    assert body["reasoning"] == {"enabled": True, "effort": "medium"}


def test_nano_gpt_fable_off_sends_enabled_false_without_effort():
    req = _req(
        "anthropic/claude-fable-5",
        ChatSessionExtras(
            tools_enabled=False, reasoning_mode="off", reasoning_effort=None,
        ),
        _fable_effort_capability(),
    )
    body, _slug = build_request_body(req)
    assert body["reasoning"] == {"enabled": False}


def test_nano_gpt_fable_effort_coexists_with_cache_control():
    """The whole point of the exception: effort AND cache markers in one
    body. Verified live against nano-gpt 2026-06-10 (see spec)."""
    system = CompletionMessage(
        role="system", content=[ContentPart(type="text", text="be terse")],
    )
    req = CompletionRequest(
        model="anthropic/claude-fable-5",
        messages=[system, _user("hi")],
        reasoning=_fable_effort_capability(),
        tools_capability=ToolCapability(supported=True),
        extras=ChatSessionExtras(
            tools_enabled=False, reasoning_mode="on", reasoning_effort="high",
        ),
        anthropic_cache_ttl="1h",
    )
    body, _slug = build_request_body(req)
    assert body["reasoning"] == {"enabled": True, "effort": "high"}
    system_content = body["messages"][0]["content"]
    assert system_content[-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest tests/modules/llm/test_translation_nano_gpt.py -v
```
Expected: `test_nano_gpt_fable_keeps_effort` and `test_nano_gpt_fable_effort_coexists_with_cache_control` FAIL (effort missing from the reasoning object — Task 1 made the regex match Fable, so the INS-037 guard now strips it). `test_nano_gpt_fable_off_sends_enabled_false_without_effort` already PASSES (off-path never carries effort). All pre-existing tests PASS.

- [ ] **Step 3: Implement the guard exception**

In `backend/modules/llm/_adapters/_nano_gpt_http.py`, extend the local import inside `_build_chat_payload` (lines 404–407):

```python
    from backend.modules.llm._adapters._anthropic_cache import (
        compute_cache_markers,
        is_anthropic_model,
        is_effort_based_claude,
    )
```

Replace the guard and comment (lines 434–441):

```python
    if send_reasoning_flag:
        reasoning_obj: dict = {"enabled": reasoning_enabled}
        # Effort buckets are NOT sent for Anthropic models — see INS-037.
        # Mirrors openrouter_http: cache survival beats effort control on
        # router-mediated paths. Other vendors keep effort as before.
        # Exception: effort-based Claude (Fable) reasons only when effort
        # is present, and effort is verified cache-safe there — INS-055.
        if reasoning_enabled and reasoning_effort and (
            not is_anthropic_model(request.model)
            or is_effort_based_claude(request.model)
        ):
            reasoning_obj["effort"] = reasoning_effort
        payload["reasoning"] = reasoning_obj
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest tests/modules/llm/test_translation_nano_gpt.py -v
```
Expected: ALL PASS — including the pre-existing `test_nano_gpt_anthropic_model_drops_effort_keeps_enabled` (Sonnet regression: still no effort).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_nano_gpt_http.py tests/modules/llm/test_translation_nano_gpt.py
git commit -m "Send reasoning effort for Fable on the nano-gpt route"
```

---

### Task 3: OpenRouter adapter — same guard exception

**Files:**
- Modify: `backend/modules/llm/_adapters/_openrouter_http.py:427-481`
- Test: `tests/modules/llm/test_translation_openrouter.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/modules/llm/test_translation_openrouter.py` (its `_req` helper at lines 40–51 takes `extras, reasoning, model=...`; note the argument order differs from the nano-gpt twin):

```python
def test_openrouter_fable_keeps_effort():
    """Effort-based Claude (Fable) bypasses the INS-037 omission — the
    enabled flag alone is a silent no-op for this family (INS-055).
    Router-wide rule; Fable is first-class on nano-gpt only, but the
    wire shape must be correct on OpenRouter too."""
    req = _req(
        ChatSessionExtras(
            tools_enabled=False, reasoning_mode="on", reasoning_effort="medium",
        ),
        ReasoningCapability(
            kind="optional",
            effort=ReasoningEffortSpec(
                buckets=["low", "medium", "high"], default_bucket="medium",
            ),
        ),
        model="anthropic/claude-fable-5",
    )
    body = build_request_body(req)
    assert body["reasoning"] == {"enabled": True, "effort": "medium"}
```

- [ ] **Step 2: Run tests to verify it fails**

Run:
```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest tests/modules/llm/test_translation_openrouter.py -v
```
Expected: `test_openrouter_fable_keeps_effort` FAILS (effort stripped); all pre-existing tests PASS.

- [ ] **Step 3: Implement**

In `backend/modules/llm/_adapters/_openrouter_http.py`, extend the local import (lines 427–430):

```python
    from backend.modules.llm._adapters._anthropic_cache import (
        compute_cache_markers,
        is_anthropic_model,
        is_effort_based_claude,
    )
```

Replace the guard and trailing comment lines (lines 470–481):

```python
    if request.reasoning.kind == "optional":
        reasoning_on = request.extras.reasoning_mode == "on"
        reasoning_obj: dict = {"enabled": reasoning_on}
        # Effort buckets are NOT sent for Anthropic models — see INS-037.
        # Router translators (OR / nano-gpt) clobber reasoning.max_tokens
        # when cache_control markers are present, and cache is too valuable
        # to drop on every reasoning turn. Sonnet's adaptive default-effort
        # handles depth choice intelligently; we only toggle on/off here.
        # Other vendors (OpenAI o-series, DeepSeek, etc.) keep effort.
        # Exception: effort-based Claude (Fable) reasons only when effort
        # is present, and effort is verified cache-safe there — INS-055.
        if reasoning_on and request.extras.reasoning_effort and (
            not is_anthropic_model(request.model)
            or is_effort_based_claude(request.model)
        ):
            reasoning_obj["effort"] = request.extras.reasoning_effort
        payload["reasoning"] = reasoning_obj
    return payload
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest tests/modules/llm/test_translation_openrouter.py -v
```
Expected: ALL PASS (including the pre-existing Sonnet no-effort regression tests).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_openrouter_http.py tests/modules/llm/test_translation_openrouter.py
git commit -m "Send reasoning effort for Fable on the OpenRouter route"
```

---

### Task 4: Capability YAML entry for Fable via nano-gpt

**Files:**
- Modify: `backend/modules/llm/data/model_capabilities.yaml` (insert after the nano-gpt opus-4.7 block, line 110)
- Test: `tests/modules/llm/test_capabilities.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/modules/llm/test_capabilities.py`:

```python
def test_fable_nano_gpt_is_first_class_with_effort_buckets():
    """Fable 5 via nano-gpt — effort-based thinking (INS-055). Unlike
    the Sonnet/Opus entries (INS-037, no effort block), Fable carries
    buckets because the enabled flag alone is a silent no-op."""
    res = resolve_capabilities(
        adapter_type="nano_gpt_http",
        model_id="anthropic/claude-fable-5",
        adapter=_StubAdapter(),
    )
    assert res.first_class_support is True
    assert res.reasoning.kind == "optional"
    assert res.reasoning.effort is not None
    assert res.reasoning.effort.buckets == ["low", "medium", "high"]
    assert res.reasoning.effort.default_bucket == "medium"
    assert res.reasoning.default_on is True
    assert res.reasoning.replay_reasoning is True
    assert res.tools.supported is True
    assert res.tools.exclusive_with_reasoning is False


def test_fable_latest_alias_matches_same_entry():
    """The claude-fable-latest alias routes to Fable 5 upstream; the
    wildcard pattern covers it with identical capabilities."""
    res = resolve_capabilities(
        adapter_type="nano_gpt_http",
        model_id="anthropic/claude-fable-latest",
        adapter=_StubAdapter(),
    )
    assert res.first_class_support is True
    assert res.reasoning.effort is not None
    assert res.reasoning.effort.default_bucket == "medium"


def test_fable_via_openrouter_is_not_first_class():
    """Cross-adapter scope: first-class Fable is nano-gpt only (spec §5)."""
    res = resolve_capabilities(
        adapter_type="openrouter_http",
        model_id="anthropic/claude-fable-5",
        adapter=_StubAdapter(),
    )
    assert res.first_class_support is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest tests/modules/llm/test_capabilities.py -v
```
Expected: the two nano-gpt Fable tests FAIL (`first_class_support is False` — no YAML match yet); the OpenRouter scope test already PASSES. All pre-existing tests PASS.

- [ ] **Step 3: Add the YAML entry**

In `backend/modules/llm/data/model_capabilities.yaml`, insert after the `nano_gpt_http` / `anthropic/claude-opus-4.7*` block (after line 110), matching the file's indentation:

```yaml
  # Claude Fable 5 via nano-gpt — effort-based thinking, see INS-055:
  # unlike Sonnet/Opus, the enabled flag alone is a silent no-op; effort
  # is required and verified cache-safe on this route.
  - adapter: nano_gpt_http
    pattern: "anthropic/claude-fable-*"
    reasoning:
      kind: optional
      effort: { buckets: [low, medium, high], default_bucket: medium }
      default_on: true
      replay_reasoning: true
    tools: { supported: true, exclusive_with_reasoning: false }
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest tests/modules/llm/test_capabilities.py -v
```
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/data/model_capabilities.yaml tests/modules/llm/test_capabilities.py
git commit -m "Add Claude Fable 5 as first-class model via nano-gpt"
```

---

### Task 5: INSIGHTS entry + full verification

**Files:**
- Modify: `INSIGHTS.md` (append after INS-054)

- [ ] **Step 1: Append the INSIGHTS entry**

```markdown
## INS-055 — Fable is effort-based Claude; INS-037 gets an exception (2026-06-10)

**Decision:** ``anthropic/claude-fable-*`` models send
``reasoning: {enabled: true, effort: <bucket>}`` on the router paths
(nano-gpt, OpenRouter). ``is_effort_based_claude()`` in
``_anthropic_cache.py`` carries the exception; all other Claude
families keep the INS-037 effort omission.

**Context:** Live probes (2026-06-10, nano-gpt) showed that for Fable 5
``{"enabled": true}`` alone is a **silent no-op** — zero reasoning
output, while Opus 4.7 reasons on the identical flag. With an
``effort`` bucket present, reasoning streams and scales plausibly
(low/medium/high). The INS-037 rationale does not apply here: no
INS-035-style percentage-budget explosion (Fable handles effort
natively), and no INS-036-style silent drop — effort and
``cache_control`` markers coexisted in one body with reasoning intact.
Unsigned thinking-block replay (nano-gpt streams no signature for
Fable) is accepted upstream. Cache usage metrics read zero via
nano-gpt for Fable *and* Opus alike — the known nano-gpt
cache-visibility gap, not a Fable regression; cache QA stays on
OpenRouter.

**Probes:** see devdocs/specs/2026-06-10-claude-fable-5-nano-gpt-design.md.
```

- [ ] **Step 2: Syntax-check all changed Python files**

Run:
```bash
uv run python -m py_compile backend/modules/llm/_adapters/_anthropic_cache.py backend/modules/llm/_adapters/_nano_gpt_http.py backend/modules/llm/_adapters/_openrouter_http.py
```
Expected: exit 0, no output.

- [ ] **Step 3: Run the full LLM test trees (adapters touched → full adapter suites, per project convention)**

Run:
```bash
PYTHONPATH=/home/chris/workspace/chatsune uv run pytest tests/modules/llm/ backend/tests/modules/llm/ -v
```
Expected: ALL PASS, no skips beyond pre-existing ones. (No MongoDB needed for these trees.)

- [ ] **Step 4: Commit**

```bash
git add INSIGHTS.md
git commit -m "Document Fable effort exception to INS-037 as INS-055"
```

---

## Out of scope (per spec)

- No OpenRouter YAML entry (first-class is nano-gpt only; the guard fix there is wire-shape correctness, not first-class support).
- No frontend changes — `first_class_support` and effort buckets propagate through existing DTOs; the ThinkingButton effort pop-out is generic.
- No preview badge; preview communication happens via Discord.
- No version.txt bump — Chris cuts releases explicitly.

## Manual verification (after merge, Chris on the real instance)

See spec §"Manual verification" — 7 steps: model appears with full metadata, effort pop-out defaults to medium, thinking pill streams, multi-turn stays clean, toggle off works, low/high visibly differ, cost display plausible.

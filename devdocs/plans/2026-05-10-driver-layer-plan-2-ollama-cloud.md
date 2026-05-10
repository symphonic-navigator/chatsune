# Driver Layer Plan 2 — DeepSeekV4Driver for Ollama Cloud + Plan 1 Cleanup

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Hard subagent constraint (per Chris's standing rule):** subagents MUST NOT merge, push, or switch branches. Each subagent works on the current branch only. The orchestrator (or Chris) handles merge to master AFTER the manual smoke test (Task 7) passes.

**Goal:** Extend `DeepSeekV4Driver` to handle Ollama Cloud's native protocol (NDJSON, `/api/chat`, `message.thinking`, `think: bool|"max"`) end-to-end through the driver layer, then bundle the three known Plan-1 cleanup items so the driver path reaches feature parity with the legacy adapter path.

**Architecture:** Add `(ollama_http, *)` entries to the driver's builder/parser dispatch. The Ollama builder validates DSv4 effort vocabulary (`high`/`max`), translates user-effort to Ollama's `think` field (boolean or `"max"` string), and delegates everything else (messages, options.temperature) to the existing `_ollama_http.build_request_body`. The Ollama parser reads NDJSON-decoded chunks: `message.thinking` → `ThinkingDelta`, `message.content` → `ContentDelta`, `done=true` with refusal `done_reason` → `StreamRefused`, `done=true` otherwise → `StreamDone(prompt_eval_count, eval_count)`. The `OllamaHttpAdapter.stream_completion` gains a driver hook analogous to Plan 1 Task 8 in the OpenRouter adapter.

**Tech Stack:** Python 3.13, Pydantic v2, pytest. No new third-party deps.

**Companion documents:**
- Spec: [`devdocs/specs/driver-layer.md`](../specs/driver-layer.md)
- Research: [`devdocs/research/deepseek-v4-wire-shapes.md`](../research/deepseek-v4-wire-shapes.md) (esp. "Ollama Cloud" section + Quirks table)
- Insight: [`INSIGHTS.md` INS-040](../../INSIGHTS.md)
- Plan 1 (template + foundation): [`2026-05-10-driver-layer-foundation-and-deepseek-v4-or.md`](2026-05-10-driver-layer-foundation-and-deepseek-v4-or.md)

**Scope of THIS plan (Plan 2 of 5):**
- `DeepSeekV4Driver` Ollama Cloud builder + parser
- Driver-class `(adapter_type=="ollama_http")` dispatch in `build_request` and `parse_chunk`
- Hook driver into `OllamaHttpAdapter.stream_completion`
- Plan 1 cleanup A: `StreamRefused` parity in driver parsers (Ollama new + OR backport)
- Plan 1 cleanup B: `adapter_type` string normalisation across `_entry_to_meta` call sites and `model_capabilities.yaml`
- Plan 1 cleanup C: symmetric test for `parse_chunk` with unsupported adapter
- Manual smoke test against live Ollama Cloud (DS V4 Pro)

**Out of scope (deferred to Plans 3-5):**
- Novita support — top-level `thinking.type`, `delta.reasoning_content` parser, `effort=["high"]` capability spec, client-side rejection of `effort=max` (Plan 3)
- nano-gpt support — `:thinking` slug-suffix dispatch, `x_nanogpt_pricing` instead of `usage`, slug-based reasoning toggle (Plan 4)
- `force_default_routing` toggle and provider-metadata-merge (Plan 5)
- DSv4 + tool-call handling in the driver path on ANY adapter (deferred — Plan 1 precedent; tracked in spec's worked example but not yet wired)

**Pre-requisites (handled before kickoff, NOT by subagents):**
- Feature branch `feat/driver-layer-plan-2` exists and is checked out (Chris's standing rule: branch first, then dispatch).
- `.llm-test-key` is present in repo root with a valid Ollama Cloud bearer token (gitignored, plain text).
- Existing Ollama Cloud Connection in the dev DB pointing at `https://ollama.com` with `deepseek-v4-pro` available (used in Task 7 smoke test). If absent, Chris adds it via the UI before Task 7.

**Test invocation note:** All `pytest` commands in this plan are prefixed with `PYTHONPATH=/home/chris/workspace/chatsune` because `backend/pyproject.toml` is the pytest configfile (rootdir is `backend/`). Without the prefix, imports of `backend.*` and `shared.*` fail. This is a host-only quirk, not a Docker concern. (See user-memory: `pytest_rootdir_quirk`.)

**Backend pytest exclude rule (per user-memory `db_tests_on_host`):** When running the FULL backend suite from the host, exclude the four MongoDB-using files. The driver tests in this plan do NOT touch Mongo, so per-file invocations work without the exclude. Only Task 6 / final verification runs the broader LLM suite, which is also Mongo-free.

---

## File Structure

**New files:** none. All additions go into existing driver files (Plan 1 already created the package skeleton).

**Modified files:**

| Path | What changes |
|---|---|
| `backend/modules/llm/_drivers/deepseek_v4/_builders.py` | Add `build_request_for_ollama_cloud` + `_OLLAMA_EFFORT_MAP` |
| `backend/modules/llm/_drivers/deepseek_v4/_parsers.py` | Add `parse_chunk_ollama_cloud`; backport `StreamRefused` to `parse_chunk_openrouter` |
| `backend/modules/llm/_drivers/deepseek_v4/__init__.py` | Driver-class `build_request`/`parse_chunk` add `adapter_type=="ollama_http"` branches |
| `backend/modules/llm/_adapters/_openrouter_http.py:153` | `_entry_to_meta` calls `resolve_capabilities` with `self.adapter_type` (was hardcoded `"openrouter"`) |
| `backend/modules/llm/_adapters/_nano_gpt_http.py:612` | Same normalisation: pass `self.adapter_type` (was `"nano_gpt"`) |
| `backend/modules/llm/_adapters/_novita_http.py:242` | Same normalisation: pass `self.adapter_type` (was `"novita"`) |
| `backend/modules/llm/_adapters/_ollama_http.py` | Hook driver lookup at top of `stream_completion`; bypass inline chunk-handling when driver matches |
| `backend/modules/llm/data/model_capabilities.yaml` | Rename adapter keys: `openrouter` → `openrouter_http`, `nano_gpt` → `nano_gpt_http` |
| `backend/modules/llm/tests/test_capabilities_with_drivers.py` | Update two `adapter_type="openrouter"` literals to `"openrouter_http"` |
| `backend/modules/llm/tests/test_deepseek_v4_driver.py` | Append: builder tests (Ollama), parser tests (Ollama + refusal), driver-class tests (Ollama dispatch + symmetric `parse_chunk` unsupported test) |

---

## Task 1: Normalise `adapter_type` strings (Gap B)

**Why this is first:** subsequent tasks add per-adapter capability dispatch where the driver's `capability_spec` may branch on `adapter_type`. If the same driver receives `"openrouter"` from `_entry_to_meta` and `"openrouter_http"` from `stream_completion`, that branching breaks silently. Fixing the inconsistency now (one focused task) prevents a silent bug class in Plans 3-5.

**Files:**
- Modify: `backend/modules/llm/_adapters/_openrouter_http.py:153`
- Modify: `backend/modules/llm/_adapters/_nano_gpt_http.py:612`
- Modify: `backend/modules/llm/_adapters/_novita_http.py:242`
- Modify: `backend/modules/llm/data/model_capabilities.yaml` (adapter keys)
- Modify: `backend/modules/llm/tests/test_capabilities_with_drivers.py:56,71` (two test literals)

- [ ] **Step 1: Confirm the current YAML adapter keys**

Run: `grep -n "adapter:" backend/modules/llm/data/model_capabilities.yaml`
Expected output (lines and short-form keys; counts may differ but the SET should be exactly `{openrouter, nano_gpt}`):

```
15:  - adapter: openrouter
22:  - adapter: openrouter
29:  - adapter: openrouter
36:  - adapter: openrouter
43:  - adapter: openrouter
50:  - adapter: openrouter
58:  - adapter: nano_gpt
65:  - adapter: nano_gpt
72:  - adapter: nano_gpt
79:  - adapter: nano_gpt
86:  - adapter: nano_gpt
93:  - adapter: nano_gpt
101:  - adapter: openrouter
110:  - adapter: nano_gpt
```

If `novita` or `ollama_http` appears, the codebase has changed since this plan was written — STOP and consult Chris before proceeding.

- [ ] **Step 2: Rewrite YAML adapter keys to long-form**

Edit `backend/modules/llm/data/model_capabilities.yaml`. Replace EVERY occurrence of `adapter: openrouter` with `adapter: openrouter_http` and EVERY occurrence of `adapter: nano_gpt` with `adapter: nano_gpt_http`. Use the Edit tool with `replace_all=True` per token (two separate edits).

Concrete edits:
- `adapter: openrouter` → `adapter: openrouter_http` (replace_all)
- `adapter: nano_gpt` → `adapter: nano_gpt_http` (replace_all)

- [ ] **Step 3: Update OpenRouter `_entry_to_meta` call site**

In `backend/modules/llm/_adapters/_openrouter_http.py`, the call at line 152-156 currently reads:

```python
    resolved = resolve_capabilities(
        adapter_type="openrouter",
        model_id=entry["id"],
        adapter=adapter,
    )
```

Change `adapter_type="openrouter"` to `adapter_type=adapter.adapter_type`. Final form:

```python
    resolved = resolve_capabilities(
        adapter_type=adapter.adapter_type,
        model_id=entry["id"],
        adapter=adapter,
    )
```

- [ ] **Step 4: Update nano-gpt `_entry_to_meta` call site**

In `backend/modules/llm/_adapters/_nano_gpt_http.py:612`, find the `resolve_capabilities(...)` call passing `adapter_type="nano_gpt"`. Change the literal to `adapter.adapter_type` exactly the same way as Step 3.

- [ ] **Step 5: Update Novita `_entry_to_meta` call site**

In `backend/modules/llm/_adapters/_novita_http.py:242`, find the `resolve_capabilities(...)` call passing `adapter_type="novita"`. Change the literal to `adapter.adapter_type` exactly the same way as Step 3.

(Note: the Novita class attribute is `adapter_type = "novita_http"`; YAML currently has no Novita entries so the YAML rename above did not touch Novita. After this step, `_entry_to_meta` on Novita will pass `"novita_http"` to `resolve_capabilities`. That's consistent with the new world.)

- [ ] **Step 6: Update tests using the old short-form literal**

In `backend/modules/llm/tests/test_capabilities_with_drivers.py`, change BOTH occurrences of `adapter_type="openrouter"` (lines 56 and 71) to `adapter_type="openrouter_http"`.

- [ ] **Step 7: Verify the YAML is still loadable and tests pass**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/ -v`
Expected: ALL tests pass — no regressions. If a test fails referencing `"openrouter"` or `"nano_gpt"` as a literal, fix that test the same way (long-form). If a test fails referencing the YAML lookup, the rename was incomplete — re-check Step 2.

- [ ] **Step 8: Compile-check the touched adapter files**

Run: `uv run python -m py_compile backend/modules/llm/_adapters/_openrouter_http.py backend/modules/llm/_adapters/_nano_gpt_http.py backend/modules/llm/_adapters/_novita_http.py`
Expected: no output (zero-exit).

- [ ] **Step 9: Commit**

```bash
git add backend/modules/llm/_adapters/_openrouter_http.py backend/modules/llm/_adapters/_nano_gpt_http.py backend/modules/llm/_adapters/_novita_http.py backend/modules/llm/data/model_capabilities.yaml backend/modules/llm/tests/test_capabilities_with_drivers.py
git commit -m "Normalise adapter_type strings: long-form everywhere (openrouter_http, nano_gpt_http, novita_http)"
```

---

## Task 2: DeepSeekV4 Ollama Cloud request body builder

**Files:**
- Modify: `backend/modules/llm/_drivers/deepseek_v4/_builders.py` (add function + map)
- Modify: `backend/modules/llm/tests/test_deepseek_v4_driver.py` (append tests)

**Strategy note:** Mirror the Plan 1 OR builder pattern — translate user-effort, then delegate the rest to the existing `_ollama_http.build_request_body`. The existing Ollama builder always emits `think: bool` (line 165 of `_ollama_http.py`); we override `think` to the string `"max"` when DSv4 user-effort is `max`. For `effort=high` the existing boolean `think=True` is exactly correct (per research doc Probe B). For `reasoning_mode=off` the existing `think=False` is correct.

- [ ] **Step 1: Append the failing tests**

Append to `backend/modules/llm/tests/test_deepseek_v4_driver.py`:

```python
from backend.modules.llm._drivers.deepseek_v4._builders import (
    build_request_for_ollama_cloud,
)


def test_builder_ollama_reasoning_off():
    """reasoning_mode='off' → think=false, no effort translation."""
    body = build_request_for_ollama_cloud(
        slug="deepseek-v4-pro",
        request=_make_request(effort=None, reasoning_mode="off"),
    )
    assert body["model"] == "deepseek-v4-pro"
    assert body["stream"] is True
    assert body["think"] is False


def test_builder_ollama_reasoning_on_no_effort():
    """reasoning_mode='on' with no explicit effort: think=true (existing default)."""
    body = build_request_for_ollama_cloud(
        slug="deepseek-v4-pro",
        request=_make_request(effort=None, reasoning_mode="on"),
    )
    assert body["think"] is True


def test_builder_ollama_reasoning_high():
    """user effort='high' → think=true (boolean, per research doc Probe B)."""
    body = build_request_for_ollama_cloud(
        slug="deepseek-v4-pro",
        request=_make_request(effort="high"),
    )
    assert body["think"] is True


def test_builder_ollama_reasoning_max_translates_to_string():
    """user effort='max' → think='max' (STRING, not bool — per research doc Probe C)."""
    body = build_request_for_ollama_cloud(
        slug="deepseek-v4-pro",
        request=_make_request(effort="max"),
    )
    assert body["think"] == "max"
    # Sanity: not the boolean True. (json.dumps would serialise True → 'true',
    # which Ollama Cloud accepts but treats as default 'high'-like — wrong.)
    assert body["think"] is not True


def test_builder_ollama_rejects_unknown_effort():
    """Silent degradation is the failure mode this driver layer prevents."""
    with pytest.raises(ValueError, match="effort"):
        build_request_for_ollama_cloud(
            slug="deepseek-v4-pro",
            request=_make_request(effort="garbage_xyz"),
        )


def test_builder_ollama_inherits_message_translation():
    """Delegate to existing build_request_body → ContentPart-to-string handled."""
    body = build_request_for_ollama_cloud(
        slug="deepseek-v4-pro",
        request=_make_request(effort="high"),
    )
    assert len(body["messages"]) == 1
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"] == "Hello"
```

- [ ] **Step 2: Run the appended tests to verify they fail**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/test_deepseek_v4_driver.py -v`
Expected: 6 new failures (`ImportError: cannot import name 'build_request_for_ollama_cloud'`).

- [ ] **Step 3: Implement `build_request_for_ollama_cloud`**

Append to `backend/modules/llm/_drivers/deepseek_v4/_builders.py`:

```python
# User-effort -> Ollama Cloud `think` field. ``None`` and reasoning_mode="off"
# are handled separately (no override; the existing builder already emits the
# correct boolean). Per research doc:
#   user 'high' -> think=True (Ollama Cloud default reasoning level)
#   user 'max'  -> think="max" (string-valued; activates DeepSeek-native max
#                  upstream, mirrored by prompt_eval_count 19 -> 98)
_OLLAMA_EFFORT_MAP: dict[str, bool | str] = {
    "high": True,
    "max": "max",
}


def build_request_for_ollama_cloud(
    *, slug: str, request: CompletionRequest,
) -> dict[str, Any]:
    """Build the Ollama Cloud request body for DeepSeek V4 with effort translation.

    Strategy: delegate to the existing ``_ollama_http.build_request_body`` so
    message translation, ``options.temperature``, and the base ``think``
    boolean are inherited. Then, when reasoning is on AND user-effort is
    explicit, override ``think`` to the appropriate value from the effort map.

    Raises ``ValueError`` when ``extras.reasoning_effort`` is set to a value
    outside the DSv4 supported buckets ``[high, max]``.
    """
    # Local import to avoid a circular dependency at module load time
    # (drivers depend on adapter helpers; adapter consults drivers at call time).
    from backend.modules.llm._adapters._ollama_http import (
        build_request_body as _ollama_build_request_body,
    )

    base = _ollama_build_request_body(request)

    # Reasoning off OR no explicit effort: delegate unchanged. The existing
    # builder already set ``think`` to True/False based on reasoning_mode,
    # which matches the DSv4-on-Ollama-Cloud "default" / "off" semantics.
    if (
        request.extras.reasoning_mode == "off"
        or request.extras.reasoning_effort is None
    ):
        return base

    # Reasoning on AND effort explicit: translate or reject.
    user_effort = request.extras.reasoning_effort
    if user_effort not in _OLLAMA_EFFORT_MAP:
        raise ValueError(
            f"DeepSeek V4 effort {user_effort!r} not in supported "
            f"buckets {list(_OLLAMA_EFFORT_MAP.keys())}; cannot translate "
            f"for Ollama Cloud"
        )

    base["think"] = _OLLAMA_EFFORT_MAP[user_effort]
    return base
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/test_deepseek_v4_driver.py -v`
Expected: 6 new tests PASS, plus all previously-passing tests still pass (Plan 1 totals 11 driver tests; this raises to 17).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_drivers/deepseek_v4/_builders.py backend/modules/llm/tests/test_deepseek_v4_driver.py
git commit -m "Add DeepSeek V4 request-body builder for Ollama Cloud (effort -> think bool/string)"
```

---

## Task 3: DeepSeekV4 Ollama Cloud chunk parser (with refusal handling)

**Files:**
- Modify: `backend/modules/llm/_drivers/deepseek_v4/_parsers.py` (add function + import StreamRefused)
- Modify: `backend/modules/llm/tests/test_deepseek_v4_driver.py` (append tests)

**Strategy note:** Ollama Cloud uses NDJSON, but each line decodes to a single dict — `parse_chunk_ollama_cloud` operates on the same shape (`dict[str, Any]`) as `parse_chunk_openrouter`. The adapter layer handles the NDJSON-vs-SSE transport difference; the parser just consumes decoded dicts. Refusal handling is included from day one (Gap A applied locally) because the existing Ollama legacy path handles refusals (`_ollama_http.py:490-496`); the driver path must maintain parity or it silently swallows refusals.

- [ ] **Step 1: Append the failing tests**

Append to `backend/modules/llm/tests/test_deepseek_v4_driver.py`:

```python
from backend.modules.llm._adapters._events import StreamRefused
from backend.modules.llm._drivers.deepseek_v4._parsers import (
    parse_chunk_ollama_cloud,
)


def test_parser_ollama_extracts_visible_content():
    chunk = {
        "model": "deepseek-v4-pro",
        "message": {"role": "assistant", "content": "Hello"},
        "done": False,
    }
    events = parse_chunk_ollama_cloud(chunk=chunk)
    assert any(isinstance(e, ContentDelta) and e.delta == "Hello" for e in events)


def test_parser_ollama_extracts_thinking_from_message_thinking():
    """Ollama Cloud's CoT key is message.thinking (Anthropic-style on the
    Ollama native envelope; see research doc Probe B)."""
    chunk = {
        "model": "deepseek-v4-pro",
        "message": {"role": "assistant", "content": "", "thinking": "We need to think..."},
        "done": False,
    }
    events = parse_chunk_ollama_cloud(chunk=chunk)
    assert any(
        isinstance(e, ThinkingDelta) and e.delta == "We need to think..."
        for e in events
    )


def test_parser_ollama_emits_stream_done_with_eval_counts():
    """Ollama returns prompt_eval_count + eval_count on the done chunk; eval_count
    bundles thinking + visible (no separate reasoning_tokens — see research doc)."""
    chunk = {
        "model": "deepseek-v4-pro",
        "message": {"role": "assistant", "content": ""},
        "done": True,
        "done_reason": "stop",
        "total_duration": 615230395,
        "prompt_eval_count": 19,
        "eval_count": 789,
    }
    events = parse_chunk_ollama_cloud(chunk=chunk)
    done = next((e for e in events if isinstance(e, StreamDone)), None)
    assert done is not None
    assert done.input_tokens == 19
    assert done.output_tokens == 789
    # Ollama does not split reasoning out — it stays None.
    assert done.reasoning_tokens is None


def test_parser_ollama_emits_stream_refused_on_content_filter():
    chunk = {
        "model": "deepseek-v4-pro",
        "message": {"role": "assistant", "content": ""},
        "done": True,
        "done_reason": "content_filter",
    }
    events = parse_chunk_ollama_cloud(chunk=chunk)
    refused = next((e for e in events if isinstance(e, StreamRefused)), None)
    assert refused is not None
    assert refused.reason == "content_filter"
    # No StreamDone when refused — refusal is the terminal event.
    assert not any(isinstance(e, StreamDone) for e in events)


def test_parser_ollama_emits_stream_refused_with_refusal_text():
    chunk = {
        "model": "deepseek-v4-pro",
        "message": {"role": "assistant", "content": "", "refusal": "I cannot help with that."},
        "done": True,
        "done_reason": "refusal",
    }
    events = parse_chunk_ollama_cloud(chunk=chunk)
    refused = next((e for e in events if isinstance(e, StreamRefused)), None)
    assert refused is not None
    assert refused.reason == "refusal"
    assert refused.refusal_text == "I cannot help with that."


def test_parser_ollama_handles_chunk_with_no_actionable_delta():
    """Empty message + done=False → no events."""
    chunk = {"model": "deepseek-v4-pro", "message": {"content": ""}, "done": False}
    events = parse_chunk_ollama_cloud(chunk=chunk)
    assert events == []
```

- [ ] **Step 2: Run the appended tests to verify they fail**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/test_deepseek_v4_driver.py -v`
Expected: 6 new failures (`ImportError: cannot import name 'parse_chunk_ollama_cloud'`).

- [ ] **Step 3: Implement `parse_chunk_ollama_cloud` and import `StreamRefused`**

Edit `backend/modules/llm/_drivers/deepseek_v4/_parsers.py`. First, extend the imports block to also pull in `StreamRefused`:

Replace:

```python
from backend.modules.llm._adapters._events import (
    ContentDelta,
    ProviderStreamEvent,
    StreamDone,
    ThinkingDelta,
)
```

with:

```python
from backend.modules.llm._adapters._events import (
    ContentDelta,
    ProviderStreamEvent,
    StreamDone,
    StreamRefused,
    ThinkingDelta,
)


# Mirrors _ollama_http._REFUSAL_REASONS — keeping a local copy avoids
# importing adapter internals from the driver layer.
_REFUSAL_REASONS: frozenset[str] = frozenset({"content_filter", "refusal"})
```

Then append at the bottom of the file:

```python
def parse_chunk_ollama_cloud(*, chunk: dict[str, Any]) -> list[ProviderStreamEvent]:
    """Translate one Ollama Cloud NDJSON-decoded chunk into ProviderStreamEvents.

    Ollama Cloud uses the native Ollama envelope (no OpenAI ``choices``
    list). Each chunk contains a ``message`` block with ``content`` and
    optional ``thinking``; the final chunk has ``done=True`` plus
    ``prompt_eval_count`` and ``eval_count``. Refusals are signalled via
    ``done_reason in {content_filter, refusal}`` — emit ``StreamRefused``
    instead of ``StreamDone``.
    """
    events: list[ProviderStreamEvent] = []

    message = chunk.get("message") or {}

    # Visible content fragment
    content = message.get("content")
    if content:
        events.append(ContentDelta(delta=content))

    # Ollama-native CoT key. Mapped to ThinkingDelta (per INS-038, "thinking"
    # and "reasoning" are interchangeable in this codebase).
    thinking = message.get("thinking")
    if thinking:
        events.append(ThinkingDelta(delta=thinking))

    # Terminal handling
    if chunk.get("done"):
        done_reason = chunk.get("done_reason")
        if done_reason and done_reason.lower() in _REFUSAL_REASONS:
            events.append(StreamRefused(
                reason=done_reason,
                refusal_text=message.get("refusal") or None,
            ))
        else:
            events.append(StreamDone(
                input_tokens=chunk.get("prompt_eval_count"),
                output_tokens=chunk.get("eval_count"),
                # Ollama Cloud bundles reasoning into eval_count — no separate
                # reasoning_tokens field. Leave it as None.
            ))

    return events
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/test_deepseek_v4_driver.py -v`
Expected: 6 new tests PASS, total now 23 driver tests.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_drivers/deepseek_v4/_parsers.py backend/modules/llm/tests/test_deepseek_v4_driver.py
git commit -m "Add DeepSeek V4 chunk parser for Ollama Cloud (message.thinking, NDJSON, refusal)"
```

---

## Task 4: Backport `StreamRefused` to OpenRouter parser (Gap A completion)

**Files:**
- Modify: `backend/modules/llm/_drivers/deepseek_v4/_parsers.py` (extend `parse_chunk_openrouter`)
- Modify: `backend/modules/llm/tests/test_deepseek_v4_driver.py` (append tests)

**Why this matters:** Plan 1's `parse_chunk_openrouter` does not emit `StreamRefused` for `finish_reason in {content_filter, refusal}`, but the legacy `_chunk_to_events` (`_openrouter_http.py:276-280`) does. Without this, the driver path on OR silently drops refusals — DSv4 is a high-volume model and content-filter refusals are a real failure mode we need to surface to the user.

- [ ] **Step 1: Append the failing tests**

**Note:** Imports referenced by the new tests below are ALREADY in the top-level imports block of `test_deepseek_v4_driver.py` (lines 6-23, after the import-consolidation fix-up commit during Task 3). Do NOT add inline imports — `StreamRefused` is already imported at module top, `parse_chunk_openrouter` is already imported, `pytest`/`StreamDone` are too.

Append to `backend/modules/llm/tests/test_deepseek_v4_driver.py`:

```python
def test_parser_or_emits_stream_refused_on_content_filter():
    chunk = {
        "id": "gen-1", "provider": "DeepInfra",
        "choices": [{
            "index": 0,
            "delta": {"content": "", "role": "assistant"},
            "finish_reason": "content_filter",
        }],
    }
    events = parse_chunk_openrouter(chunk=chunk)
    refused = next((e for e in events if isinstance(e, StreamRefused)), None)
    assert refused is not None
    assert refused.reason == "content_filter"


def test_parser_or_emits_stream_refused_with_refusal_text():
    chunk = {
        "id": "gen-1", "provider": "DeepInfra",
        "choices": [{
            "index": 0,
            "delta": {"content": "", "role": "assistant", "refusal": "Cannot help."},
            "finish_reason": "refusal",
        }],
    }
    events = parse_chunk_openrouter(chunk=chunk)
    refused = next((e for e in events if isinstance(e, StreamRefused)), None)
    assert refused is not None
    assert refused.reason == "refusal"
    assert refused.refusal_text == "Cannot help."


def test_parser_or_does_not_emit_refused_on_normal_stop():
    """Sanity: finish_reason='stop' must NOT produce StreamRefused."""
    chunk = {
        "id": "gen-1",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": 19, "completion_tokens": 800, "total_tokens": 819,
            "completion_tokens_details": {"reasoning_tokens": 360},
        },
    }
    events = parse_chunk_openrouter(chunk=chunk)
    assert not any(isinstance(e, StreamRefused) for e in events)
    # Should still emit StreamDone.
    assert any(isinstance(e, StreamDone) for e in events)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/test_deepseek_v4_driver.py -v`
Expected: 2 new failures (`StreamRefused not emitted`); the third test (`stop`) likely passes already.

- [ ] **Step 3: Extend `parse_chunk_openrouter` to emit `StreamRefused`**

Edit `backend/modules/llm/_drivers/deepseek_v4/_parsers.py`. Find `parse_chunk_openrouter` and replace its body with the version below. The new logic mirrors `_chunk_to_events` line 266-282 from `_openrouter_http.py` so behaviour is identical to the legacy path.

Replace:

```python
def parse_chunk_openrouter(*, chunk: dict[str, Any]) -> list[ProviderStreamEvent]:
    """Translate one OR SSE chunk dict into ProviderStreamEvents."""
    events: list[ProviderStreamEvent] = []

    choices = chunk.get("choices") or []
    if choices:
        delta = choices[0].get("delta") or {}

        # Visible content fragment
        content = delta.get("content")
        if content:
            events.append(ContentDelta(delta=content))

        # OR-canonical reasoning fragment (mapped to ThinkingDelta —
        # "reasoning" and "thinking" are used interchangeably in the
        # codebase per INS-038).
        reasoning = delta.get("reasoning")
        if reasoning:
            events.append(ThinkingDelta(delta=reasoning))

    # Terminal usage block (chunk with finish_reason or final usage info)
    usage = chunk.get("usage")
    if usage is not None:
        details = usage.get("completion_tokens_details") or {}
        events.append(StreamDone(
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            reasoning_tokens=details.get("reasoning_tokens"),
        ))

    return events
```

with:

```python
def parse_chunk_openrouter(*, chunk: dict[str, Any]) -> list[ProviderStreamEvent]:
    """Translate one OR SSE chunk dict into ProviderStreamEvents."""
    events: list[ProviderStreamEvent] = []

    choices = chunk.get("choices") or []
    if choices:
        choice = choices[0]
        delta = choice.get("delta") or {}

        # Visible content fragment
        content = delta.get("content")
        if content:
            events.append(ContentDelta(delta=content))

        # OR-canonical reasoning fragment (mapped to ThinkingDelta —
        # "reasoning" and "thinking" are used interchangeably in the
        # codebase per INS-038).
        reasoning = delta.get("reasoning")
        if reasoning:
            events.append(ThinkingDelta(delta=reasoning))

        # Refusal: parity with _openrouter_http._chunk_to_events. Without
        # this the driver path silently drops refusals; the legacy path
        # surfaces them as StreamRefused.
        finish = choice.get("finish_reason")
        if finish and finish.lower() in _REFUSAL_REASONS:
            events.append(StreamRefused(
                reason=finish,
                refusal_text=delta.get("refusal") or None,
            ))

    # Terminal usage block (chunk with finish_reason or final usage info)
    usage = chunk.get("usage")
    if usage is not None:
        details = usage.get("completion_tokens_details") or {}
        events.append(StreamDone(
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            reasoning_tokens=details.get("reasoning_tokens"),
        ))

    return events
```

(Note: the `_REFUSAL_REASONS` frozenset was added at module level in Task 3 Step 3, so it is already available here.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/test_deepseek_v4_driver.py -v`
Expected: 3 new tests PASS, total now 26.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_drivers/deepseek_v4/_parsers.py backend/modules/llm/tests/test_deepseek_v4_driver.py
git commit -m "Backport StreamRefused parity to OpenRouter parser (Gap A completion)"
```

---

## Task 5: Wire Ollama dispatch into `DeepSeekV4Driver` class (with Gap C symmetric test)

**Files:**
- Modify: `backend/modules/llm/_drivers/deepseek_v4/__init__.py` (add Ollama branches in `build_request` and `parse_chunk`)
- Modify: `backend/modules/llm/tests/test_deepseek_v4_driver.py` (append driver-class tests + symmetric parse_chunk test)

- [ ] **Step 1: Append the failing tests**

**Note:** All imports referenced below (`pytest`, `ContentDelta`, `DeepSeekV4Driver`, `_make_request` fixture) are ALREADY in the top-level imports/fixtures of `test_deepseek_v4_driver.py`. Do NOT add inline imports.

Append to `backend/modules/llm/tests/test_deepseek_v4_driver.py`:

```python
def test_dsv4_driver_build_request_via_class_for_ollama_cloud():
    d = DeepSeekV4Driver()
    body = d.build_request(
        adapter_type="ollama_http",
        slug="deepseek-v4-pro",
        request=_make_request(effort="max"),
    )
    assert body["think"] == "max"
    # body["model"] comes from request.model, which the _make_request fixture
    # sets to "deepseek/deepseek-v4-pro" (prefixed). The driver's `slug`
    # parameter is for dispatch only — it does NOT override the body model.
    assert body["model"] == "deepseek/deepseek-v4-pro"


def test_dsv4_driver_parse_chunk_via_class_for_ollama_cloud():
    d = DeepSeekV4Driver()
    events = d.parse_chunk(
        adapter_type="ollama_http",
        slug="deepseek-v4-pro",
        chunk={
            "model": "deepseek-v4-pro",
            "message": {"role": "assistant", "content": "Hi"},
            "done": False,
        },
    )
    assert any(isinstance(e, ContentDelta) and e.delta == "Hi" for e in events)


def test_dsv4_driver_parse_chunk_for_unsupported_adapter_raises():
    """Symmetric to test_dsv4_driver_build_request_for_unsupported_adapter_raises
    (Gap C — Plan 1 only had this test for build_request)."""
    d = DeepSeekV4Driver()
    with pytest.raises(NotImplementedError, match="adapter_type"):
        d.parse_chunk(
            adapter_type="nano_gpt_http",
            slug="deepseek/deepseek-v4-pro:thinking",
            chunk={"id": "x", "choices": [{"index": 0, "delta": {"content": "Hi"}}]},
        )


def test_dsv4_driver_build_request_for_unsupported_adapter_still_raises_on_novita():
    """Plan 2 added Ollama, NOT Novita. Novita must still raise."""
    d = DeepSeekV4Driver()
    with pytest.raises(NotImplementedError, match="adapter_type"):
        d.build_request(
            adapter_type="novita_http",
            slug="deepseek/deepseek-v4-pro",
            request=_make_request(effort="high"),
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/test_deepseek_v4_driver.py -v`
Expected: 4 new failures — the two Ollama tests fail with `NotImplementedError` (driver class not yet routing Ollama), the symmetric `parse_chunk` and Novita-still-raises tests should mostly already pass except for any wording mismatch.

- [ ] **Step 3: Add Ollama branches to the driver class**

Edit `backend/modules/llm/_drivers/deepseek_v4/__init__.py`. First, extend the imports at the top of the file to pull in the new builder + parser functions. Replace:

```python
from backend.modules.llm._drivers.deepseek_v4._builders import (
    build_request_for_openrouter,
)
from backend.modules.llm._drivers.deepseek_v4._capability import (
    deepseek_v4_capability_spec,
)
from backend.modules.llm._drivers.deepseek_v4._parsers import (
    parse_chunk_openrouter,
)
```

with:

```python
from backend.modules.llm._drivers.deepseek_v4._builders import (
    build_request_for_ollama_cloud,
    build_request_for_openrouter,
)
from backend.modules.llm._drivers.deepseek_v4._capability import (
    deepseek_v4_capability_spec,
)
from backend.modules.llm._drivers.deepseek_v4._parsers import (
    parse_chunk_ollama_cloud,
    parse_chunk_openrouter,
)
```

Then replace the `build_request` method body. Currently:

```python
    def build_request(
        self, *, adapter_type: str, slug: str, request: CompletionRequest,
    ) -> dict[str, Any]:
        if adapter_type == "openrouter_http":
            return build_request_for_openrouter(slug=slug, request=request)
        raise NotImplementedError(
            f"DeepSeekV4Driver: adapter_type={adapter_type!r} not supported "
            f"in Plan 1 (only openrouter_http). See Plans 2-4 for the rest."
        )
```

Replace with:

```python
    def build_request(
        self, *, adapter_type: str, slug: str, request: CompletionRequest,
    ) -> dict[str, Any]:
        if adapter_type == "openrouter_http":
            return build_request_for_openrouter(slug=slug, request=request)
        if adapter_type == "ollama_http":
            return build_request_for_ollama_cloud(slug=slug, request=request)
        raise NotImplementedError(
            f"DeepSeekV4Driver: adapter_type={adapter_type!r} not supported "
            f"yet (Plan 2 covers openrouter_http + ollama_http; Plans 3-4 "
            f"add novita_http and nano_gpt_http)."
        )
```

Likewise for `parse_chunk`. Replace:

```python
    def parse_chunk(
        self, *, adapter_type: str, slug: str, chunk: dict[str, Any],
    ) -> list[ProviderStreamEvent]:
        if adapter_type == "openrouter_http":
            return parse_chunk_openrouter(chunk=chunk)
        raise NotImplementedError(
            f"DeepSeekV4Driver: adapter_type={adapter_type!r} not supported "
            f"in Plan 1 (only openrouter_http). See Plans 2-4 for the rest."
        )
```

with:

```python
    def parse_chunk(
        self, *, adapter_type: str, slug: str, chunk: dict[str, Any],
    ) -> list[ProviderStreamEvent]:
        if adapter_type == "openrouter_http":
            return parse_chunk_openrouter(chunk=chunk)
        if adapter_type == "ollama_http":
            return parse_chunk_ollama_cloud(chunk=chunk)
        raise NotImplementedError(
            f"DeepSeekV4Driver: adapter_type={adapter_type!r} not supported "
            f"yet (Plan 2 covers openrouter_http + ollama_http; Plans 3-4 "
            f"add novita_http and nano_gpt_http)."
        )
```

- [ ] **Step 4: Update the docstring on the class**

In the same file, update the class docstring from:

```python
    """Driver for DeepSeek V4 Pro and DeepSeek V4 Flash.

    Plan 1: OpenRouter only. Plans 2-4 add nano-gpt, Novita, Ollama Cloud.
    """
```

to:

```python
    """Driver for DeepSeek V4 Pro and DeepSeek V4 Flash.

    Plan 1: OpenRouter. Plan 2: + Ollama Cloud (this class). Plans 3-4 add
    Novita and nano-gpt.
    """
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/test_deepseek_v4_driver.py -v`
Expected: 4 new tests PASS, total now 30. The original `test_dsv4_driver_build_request_for_unsupported_adapter_raises` from Plan 1 (which used `nano_gpt_http`) must still PASS — Plan 2 only adds `ollama_http`.

- [ ] **Step 6: Run the full LLM test suite to confirm no regression**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/ -v`
Expected: ALL tests PASS (driver suite + capability suite + registry suite + any other LLM tests).

- [ ] **Step 7: Commit**

```bash
git add backend/modules/llm/_drivers/deepseek_v4/__init__.py backend/modules/llm/tests/test_deepseek_v4_driver.py
git commit -m "Wire Ollama Cloud dispatch into DeepSeekV4Driver; symmetric parse_chunk-unsupported test (Gap C)"
```

---

## Task 6: Hook driver into `OllamaHttpAdapter.stream_completion`

**Files:**
- Modify: `backend/modules/llm/_adapters/_ollama_http.py:344-` (`stream_completion`)

**Why this is invasive but small:** Mirror the Plan 1 OR-adapter hook. Two interception points: (1) before `build_request_body(request)` is called, check the driver registry and use `driver.build_request` instead; (2) inside the NDJSON chunk loop, when the driver path is active, replace the inline content/thinking/done/refusal extraction with `driver.parse_chunk` and yield its events. Everything else (HTTP client, retry, gutter timeout, NDJSON line-iter, auth headers, refusal-via-_is_refusal_reason on the legacy path) stays exactly as-is.

**Tool-call note:** Tool calls on DSv4 + Ollama Cloud are out of scope for Plan 2 (deferred per Plan 1 precedent). The driver's `parse_chunk_ollama_cloud` does not emit `ToolCallEvent`, and DSv4 prompts in the Task 7 smoke test do not exercise tools. The legacy path (when no driver matches) still handles tool calls inline at lines 509-515 — that path is unchanged.

- [ ] **Step 1: Re-read the current `stream_completion` to locate the hook points**

Read `backend/modules/llm/_adapters/_ollama_http.py:344-528`. Identify two locations:

A. The line `payload = build_request_body(request)` near the top (currently line 349). The driver hook goes right before this line, with the driver-or-default conditional replacing the call.

B. The chunk-handling block starting at the `if chunk.get("done"):` check (currently line 482) and ending after the inline tool-call extraction (line 515). When the driver matched, this entire block is replaced with a `driver.parse_chunk(...)` call + yield-loop.

- [ ] **Step 2: Add the driver lookup at the top of `stream_completion`**

In `backend/modules/llm/_adapters/_ollama_http.py`, find the existing top of `stream_completion`:

```python
    async def stream_completion(
        self, c: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        url = c.config["url"].rstrip("/")
        api_key = c.config.get("api_key") or None
        payload = build_request_body(request)
```

Replace with:

```python
    async def stream_completion(
        self, c: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        url = c.config["url"].rstrip("/")
        api_key = c.config.get("api_key") or None

        # Driver-layer hook (mirrors Plan 1 Task 8 in _openrouter_http.py).
        # Local import avoids an import cycle: drivers depend on adapter
        # helpers (build_request_body), and the adapter consults drivers
        # at call time.
        from backend.modules.llm._drivers import match_driver
        driver_cls = match_driver(request.model)
        driver = driver_cls() if driver_cls is not None else None

        if driver is not None:
            payload = driver.build_request(
                adapter_type=self.adapter_type,
                slug=request.model,
                request=request,
            )
        else:
            payload = build_request_body(request)
```

- [ ] **Step 3: Replace the inline chunk-handling with driver-aware dispatch**

Find the inline chunk-handling block (currently lines 482-515):

```python
                                    if chunk.get("done"):
                                        seen_done = True
                                        done_reason = chunk.get("done_reason")
                                        if done_reason and done_reason not in ("stop", "length"):
                                            _log.info(
                                                "ollama_base.done_reason model=%s reason=%s",
                                                payload.get("model"), done_reason,
                                            )
                                        if _is_refusal_reason(done_reason):
                                            msg = chunk.get("message", {})
                                            yield StreamRefused(
                                                reason=done_reason,
                                                refusal_text=msg.get("refusal") or None,
                                            )
                                            return
                                        yield StreamDone(
                                            input_tokens=chunk.get("prompt_eval_count"),
                                            output_tokens=chunk.get("eval_count"),
                                        )
                                        break
                                    message = chunk.get("message", {})
                                    thinking = message.get("thinking", "")
                                    if thinking:
                                        yield ThinkingDelta(delta=thinking)
                                    content = message.get("content", "")
                                    if content:
                                        yield ContentDelta(delta=content)
                                    for tc in message.get("tool_calls", []):
                                        fn = tc.get("function", {})
                                        yield ToolCallEvent(
                                            id=f"call_{uuid4().hex[:12]}",
                                            name=fn.get("name", ""),
                                            arguments=json.dumps(fn.get("arguments", {})),
                                        )
```

Replace with the driver-aware version:

```python
                                    if driver is not None:
                                        # Driver path: parser is the single
                                        # source of truth for chunk -> events.
                                        chunk_events = driver.parse_chunk(
                                            adapter_type=self.adapter_type,
                                            slug=request.model,
                                            chunk=chunk,
                                        )
                                        for event in chunk_events:
                                            if isinstance(event, StreamDone):
                                                seen_done = True
                                            yield event
                                            if isinstance(event, (
                                                StreamDone, StreamRefused, StreamError,
                                            )):
                                                return
                                        # Driver handled this chunk; loop to next NDJSON line.
                                        continue

                                    if chunk.get("done"):
                                        seen_done = True
                                        done_reason = chunk.get("done_reason")
                                        if done_reason and done_reason not in ("stop", "length"):
                                            _log.info(
                                                "ollama_base.done_reason model=%s reason=%s",
                                                payload.get("model"), done_reason,
                                            )
                                        if _is_refusal_reason(done_reason):
                                            msg = chunk.get("message", {})
                                            yield StreamRefused(
                                                reason=done_reason,
                                                refusal_text=msg.get("refusal") or None,
                                            )
                                            return
                                        yield StreamDone(
                                            input_tokens=chunk.get("prompt_eval_count"),
                                            output_tokens=chunk.get("eval_count"),
                                        )
                                        break
                                    message = chunk.get("message", {})
                                    thinking = message.get("thinking", "")
                                    if thinking:
                                        yield ThinkingDelta(delta=thinking)
                                    content = message.get("content", "")
                                    if content:
                                        yield ContentDelta(delta=content)
                                    for tc in message.get("tool_calls", []):
                                        fn = tc.get("function", {})
                                        yield ToolCallEvent(
                                            id=f"call_{uuid4().hex[:12]}",
                                            name=fn.get("name", ""),
                                            arguments=json.dumps(fn.get("arguments", {})),
                                        )
```

(Note: the legacy block is preserved verbatim BELOW the new `if driver is not None` branch — that branch returns/continues before hitting the legacy code. This keeps the diff small and the legacy behaviour pixel-identical.)

- [ ] **Step 4: Verify the file compiles**

Run: `uv run python -m py_compile backend/modules/llm/_adapters/_ollama_http.py`
Expected: no output (zero-exit success).

- [ ] **Step 5: Run the full LLM test suite to verify no regression**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/ -v`
Expected: ALL tests PASS. The Ollama adapter has no DSv4-specific unit tests (smoke test in Task 7 covers that), but any existing Ollama unit tests must still pass — the legacy path is untouched.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_adapters/_ollama_http.py
git commit -m "Hook driver layer into Ollama adapter stream_completion"
```

---

## Task 7: Manual smoke test against live Ollama Cloud

**Files:**
- No code changes — pure manual verification step.

This task validates the full end-to-end path against the real Ollama Cloud API. Bearer token at `.llm-test-key` (project root, gitignored, plain text). Existing Ollama Cloud Connection in dev DB pointing at `https://ollama.com` with `deepseek-v4-pro` available is required (per pre-requisites).

- [ ] **Step 1: Confirm the dev backend is running**

The implementing agent must NOT start the backend. Ask Chris to confirm the backend is running, or to start it via the project's standard dev command. (Per user-memory `feature_branches_default`: dev setup auto-reloads on branch switch, so backend should already be live on `feat/driver-layer-plan-2`.)

- [ ] **Step 2: Verify the Ollama Cloud Connection has DS V4 Pro selected**

In the running app:
1. Navigate to LLM Connections.
2. Confirm an "Ollama Cloud" connection exists pointing at `https://ollama.com`.
3. Confirm `deepseek-v4-pro` is selectable in the model picker for that connection.

If the connection or model is missing, Chris adds it before continuing.

- [ ] **Step 3: Send a reasoning-triggering prompt with effort=high**

Suggested prompt (mirrors the research doc Probe B):

> Why are there infinitely many prime numbers? Give a step-by-step proof.

Set reasoning ON, effort = `high`.

Expected backend behaviour:
- Driver matches DSv4 (basename `deepseek-v4-pro` matches `deepseek-v4-pro*`).
- Wire payload contains `"think": true` (boolean — see research doc Probe B).
- Stream emits `ThinkingDelta` events from `message.thinking` followed by `ContentDelta` events from `message.content`.
- Stream terminates with `StreamDone(input_tokens=~19, output_tokens=~789)`. The exact numbers vary; structurally `input_tokens` should be in the low double-digits and `output_tokens` in the hundreds.

If `LLM_TRACE_PAYLOADS=1` is set in the env, the log line `LLM_TRACE path=direct url=… payload=…` should show `"think": true` (NOT a string).

- [ ] **Step 4: Send the same prompt with effort=max**

Same prompt, reasoning ON, effort = `max`.

Expected backend behaviour:
- Wire payload contains `"think": "max"` (STRING, not boolean — see research doc Probe C).
- `prompt_eval_count` jumps from ~19 to ~98 (upstream injects the DeepSeek-native max system prompt; this is the canonical fingerprint).
- Stream terminates with `StreamDone(input_tokens=~98, output_tokens=~891)`.

If the `prompt_eval_count` does NOT jump to ~98, the `"max"` string is not reaching upstream — Chris should inspect the LLM_TRACE log line for the actual wire shape and report.

- [ ] **Step 5: Send a non-reasoning prompt (reasoning OFF)**

Prompt: `What is 2+2? Answer with just the number.`
Reasoning OFF.

Expected:
- Wire payload contains `"think": false`.
- Stream emits one or two `ContentDelta` events with the `4`.
- No `ThinkingDelta` events.
- `StreamDone(input_tokens=~17, output_tokens=~2)`.

- [ ] **Step 6: Send a reasoning prompt with effort = (intentionally invalid) "low"**

This validates that the driver rejects invalid effort buckets at the boundary instead of silently degrading.

If the UI does not allow picking `low` for DSv4 (per the capability spec, buckets are `[high, max]`), this step is satisfied by the UI itself — the option is not offered. Note this in the smoke-test summary and skip to Step 7.

If Chris can construct a request bypassing the UI (e.g. via direct API or via the LLM harness), the expected result is `ValueError: DeepSeek V4 effort 'low' not in supported buckets ['high', 'max']` raised in the backend, surfaced to the user as a `StreamError`.

- [ ] **Step 7: Re-verify OpenRouter still works (no Plan-1 regression)**

Re-run a DSv4 prompt against OpenRouter with effort = `max`. Expected: identical behaviour to the Plan 1 smoke test — request body has `"reasoning": {"effort": "xhigh"}`, `prompt_tokens` jumps from 19 to ~98, reasoning streams via `delta.reasoning`. This guards against the cleanup tasks (1, 4) accidentally breaking OR.

- [ ] **Step 8: If anything deviated, document and fix**

Record any deviation in `devdocs/research/deepseek-v4-wire-shapes.md` as a follow-up note dated today. Either:
- Fix in this plan (extend a task) if the fix is small and obvious, or
- Capture as a follow-up note in INSIGHTS.md for a Plan-2.x patch.

If everything matches expectations, no documentation updates are required for this task — the existing research doc and INS-040 already cover the design.

- [ ] **Step 9: Commit any verification notes**

If documentation changes were needed:

```bash
git add devdocs/research/deepseek-v4-wire-shapes.md INSIGHTS.md
git commit -m "Plan 2 smoke test: verification notes for Ollama Cloud DSv4 path"
```

If no notes were needed, skip the commit.

---

## Self-review checklist (run before declaring Plan 2 complete)

- [ ] All driver tests pass: `PYTHONPATH=/home/chris/workspace/chatsune uv run python -m pytest backend/modules/llm/tests/ -v`
- [ ] No untracked files left in `backend/modules/llm/_drivers/deepseek_v4/`
- [ ] All commits present (Tasks 1-6 each produced at least one commit; Task 7 either committed verification notes or didn't need any)
- [ ] `INSIGHTS.md`, `devdocs/specs/driver-layer.md` are unchanged unless Task 7 deviation notes were added
- [ ] No changes outside the in-scope files listed in the **File Structure** section (no surprise edits to chat module, frontend, etc.)
- [ ] `nano.json` (Chris's curl-output dump from previous session) is still untracked and was NOT committed
- [ ] Capability YAML still loads correctly (Task 1 Step 7 confirmed)
- [ ] Manual smoke test (Task 7) was either completed by Chris or explicitly scheduled by him as a follow-up
- [ ] Branch `feat/driver-layer-plan-2` has NOT been merged or pushed by any subagent (Chris handles merge after sign-off)

# Empty-Response Retry — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When an upstream stream ends cleanly (HTTP 200, `[DONE]` received, no error) but produces zero content, zero thinking, and zero tool-calls in the first iteration of a chat completion, retry the call up to 2 more times (3 total attempts) with exponential backoff. This is a cross-cutting reliability fix for provider-side glitches that the existing HTTP-error retry path does not catch (the existing retry covers 429/5xx/connection-drops; an "empty 200" never enters that path).

**Architecture:** Wrap the iteration body in a per-iteration retry-loop in `backend/modules/chat/_inference.py`, but only enable the retry for `iteration == 0` (subsequent iterations after a tool call have legitimate empty-response patterns we don't want to disrupt — that's a separate problem with separate evidence requirements). Trigger condition is the precise pattern observed: `iter_content == "" AND iter_thinking == "" AND iter_tool_calls == [] AND not cancelled AND status not in {"error","aborted","refused"}`. On match, sleep with exponential backoff (1s → 2s) and re-execute the iteration body; the per-iteration accumulators reset naturally.

**Tech Stack:** Python 3.13, pytest, pytest-asyncio (existing), no new dependencies.

---

## Empirical context (probed 2026-05-10)

Chris observed today on Novita with DSv4 Flash + reasoning effort=high/max:

```
inference.stream.end session=… correlation_id=… iteration=0 reason=done
  tool_calls=0 content_chars=0 thinking_chars=0
  input_tokens=2775 output_tokens=0 reasoning_tokens=n/a
```

The stream completed (`reason=done`), the request was tokenised (`input_tokens=2775`), but the model produced nothing. Re-sending the same prompt 1-2 times succeeded normally. This is a Novita-side intermittent glitch on Flash specifically; on the same connection, Pro is fully reliable. Mid-tool-call drops (also observed) are a separate issue requiring its own evidence and are explicitly **out of scope** for this plan.

---

## Important: scope discipline

**Do not** widen the retry beyond `iteration == 0`. A retry inside the tool-loop is conceptually different (the model may legitimately emit an empty assistant turn in some patterns) and needs its own evidence pass — that's a future plan, not this one.

**Do not** retry on cancellation, error, refusal, or abort. The user pressed stop or the provider rejected the content; both must be respected.

**Do not** retry when ANY of {content, thinking, tool_calls} is non-empty. Partial content is not a failure mode we want to mask — it's the user-visible signal that something went wrong, and rebuilding from a half-stream would risk duplicate output.

**Do not** modify the existing HTTP-error retry path in any adapter — the empty-response retry sits one level above (in `_inference.py`, around the adapter call), not inside it.

**Do not** add inline imports. All imports at the top of `_inference.py`.

---

## File Structure

- Modify: `backend/modules/chat/_inference.py` — add the retry constants, wrap iteration body in a `while True` empty-retry loop, log line on retry
- Create: `backend/tests/modules/chat/test_inference_empty_response_retry.py` — focused unit tests for the retry behaviour

---

## Task 1: Add the empty-retry loop

**Files:**
- Modify: `backend/modules/chat/_inference.py`

- [ ] **Step 1: Add the retry constants**

Near the existing `_MAX_TOOL_ITERATIONS = 5` (line 51) and `_REFUSAL_FALLBACK_TEXT = "..."` (line 52), add:

```python
# When iteration 0 of a completion ends cleanly (no error, no abort, no
# refusal) but produces zero content / zero thinking / zero tool_calls,
# retry the iteration up to ``_EMPTY_RESPONSE_MAX_RETRIES`` more times
# with exponential backoff. Provider-side intermittent glitches (observed
# on Novita DSv4 Flash, 2026-05-10) produce HTTP-200 streams that the
# existing 429/5xx retry path doesn't catch. Only iteration 0 is retried —
# legitimately-empty assistant turns inside the tool loop are out of scope.
_EMPTY_RESPONSE_MAX_RETRIES = 2  # 3 total attempts
_EMPTY_RESPONSE_BACKOFF_BASE = 1.0  # seconds; sleeps 1s, then 2s
```

- [ ] **Step 2: Wrap the iteration body in a retry-loop**

Inside the existing `for iteration in range(_MAX_TOOL_ITERATIONS + 1):` (line 207), wrap the iteration body in `while True:` and insert the retry decision before the existing `if cancelled or status in (...)` check (line 366). Pseudocode of the resulting structure (the actual edit must preserve all existing code lines and semantics — only the new `while True` wrapper, the retry-decision block, and minor indentation adjustments):

```python
for iteration in range(_MAX_TOOL_ITERATIONS + 1):
    empty_attempt = 0
    while True:
        # === EXISTING ITERATION BODY STARTS ===
        stream = (await stream_fn(...) ...)

        # Per-iteration accumulators reset on every retry — that's the
        # right behaviour, since iter_content/iter_thinking are empty
        # by definition on the empty-response path.
        iter_content = ""
        iter_thinking = ""
        # ... (all other iter_* and stream_end_reason init)

        if settings.inference_logging:
            _log.info("inference.stream.begin ...")

        try:
            async for event in stream:
                # ... existing match cases ...
        finally:
            full_content += iter_content
            if iter_thinking:
                full_thinking += iter_thinking

        if settings.inference_logging:
            _log.info("inference.stream.end ...")
        # === EXISTING ITERATION BODY ENDS ===

        # NEW: empty-response retry decision (only for iteration 0).
        is_clean_end = (
            not cancelled
            and status not in ("error", "aborted", "refused")
        )
        is_empty = (
            not iter_content
            and not iter_thinking
            and not iter_tool_calls
        )
        if (
            iteration == 0
            and is_clean_end
            and is_empty
            and empty_attempt < _EMPTY_RESPONSE_MAX_RETRIES
        ):
            empty_attempt += 1
            backoff = _EMPTY_RESPONSE_BACKOFF_BASE * (2 ** (empty_attempt - 1))
            _log.info(
                "inference.empty_response.retry session=%s correlation_id=%s "
                "attempt=%d/%d backoff=%.1fs",
                session_id, correlation_id,
                empty_attempt, _EMPTY_RESPONSE_MAX_RETRIES, backoff,
            )
            await asyncio.sleep(backoff)
            continue  # re-enter the while: re-execute the iteration body
        break  # exit while; fall through to existing post-iteration logic

    # === EXISTING POST-ITERATION CODE STARTS (unchanged) ===
    if cancelled or status in ("error", "aborted", "refused"):
        break
    if not iter_tool_calls or tool_executor_fn is None:
        break
    # ... tool execution ...
```

**Critical correctness points:**

1. The `while True:` opens **inside** the `for iteration ...` loop. Indent the existing iteration body one level deeper. Do not move any lines between blocks.
2. The retry-decision block goes **after** the existing `inference.stream.end` log line and **before** the `if cancelled or status in (...)` break check. Both of those checks must remain in their current relative order; the retry decision sits between them.
3. The `full_content += iter_content` and `full_thinking += iter_thinking` lines (currently in the `finally:` block) are executed on each retry. Since the empty-retry only fires when both are `""`, they accumulate nothing — no double-count. Do **not** move them out of the finally; that would break the partial-content-on-mid-stream-error path.
4. `empty_attempt` is local to each `iteration`. It must be initialised at the top of every outer-loop turn (so iteration 1+ starts fresh — moot in practice because we don't retry past iteration 0, but defensive).
5. The `t_first_token` variable is set on the FIRST content/thinking delta seen across the WHOLE inference (line 247). Because the empty-retry path produces no deltas, `t_first_token` stays `None` until the eventual successful stream — that's correct, do not reset it.

- [ ] **Step 3: Run existing inference event tests to confirm no regression**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run pytest backend/tests/modules/chat/test_inference_events.py -v`

Expected: all existing tests still pass. The retry block is a no-op on the happy path (any non-empty content/thinking/tool_calls falls through `is_empty=False` to the existing break logic).

- [ ] **Step 4: Commit**

```bash
git add backend/modules/chat/_inference.py
git commit -m "Add empty-response retry for iteration 0 of chat completion"
```

---

## Task 2: Tests for the retry behaviour

**Files:**
- Create: `backend/tests/modules/chat/test_inference_empty_response_retry.py`

The existing `test_inference_events.py` is event-mapping-focused — no full-stream fixture infrastructure. Build a minimal one for this test file. The aim is to verify the **retry decision logic**, not the full inference flow; use the lightest mocks that exercise the new code path.

- [ ] **Step 1: Write the test file**

Create `backend/tests/modules/chat/test_inference_empty_response_retry.py`:

```python
"""Tests for the empty-response retry path in run_inference.

We don't simulate the full WebSocket / event-bus surface — we only need
to verify that:
  - An empty stream in iteration 0 triggers a retry (logged).
  - A non-empty stream halts retries.
  - Cancellation / error / refusal does not trigger a retry.
  - The retry stops after _EMPTY_RESPONSE_MAX_RETRIES (no infinite loop).
  - Iteration > 0 never retries (out of scope for this plan).

The harness mocks ``stream_fn`` to return scripted async iterators; all
other dependencies (emit_fn, executors) are no-op stubs.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.modules.llm import (
    ContentDelta,
    StreamDone,
    ThinkingDelta,
    ToolCallEvent,
)
from backend.modules.chat._inference import (
    _EMPTY_RESPONSE_MAX_RETRIES,
    run_inference,  # if this is the entry point; else use the actual name
)


def _empty_stream() -> AsyncIterator[Any]:
    async def gen() -> AsyncIterator[Any]:
        # Clean stream that produces zero content/thinking/tool-calls.
        yield StreamDone(input_tokens=42, output_tokens=0, reasoning_tokens=None)
    return gen()


def _content_stream(text: str = "Hello") -> AsyncIterator[Any]:
    async def gen() -> AsyncIterator[Any]:
        yield ContentDelta(delta=text)
        yield StreamDone(input_tokens=42, output_tokens=5, reasoning_tokens=None)
    return gen()


# Use the harness pattern from test_inference_events.py for minimal-shape
# session/persona/correlation_id setup; reuse rather than duplicate where
# possible. If no such pattern exists, build the smallest fixture that
# makes run_inference callable.

@pytest.mark.asyncio
async def test_empty_iteration_0_triggers_retry(caplog) -> None:
    """First call returns empty stream; second returns content. Verify
    a retry log line was emitted at level INFO and the final content
    matches the second stream."""
    call_count = {"n": 0}
    def stream_fn(_extras: list) -> AsyncIterator[Any]:
        call_count["n"] += 1
        return _empty_stream() if call_count["n"] == 1 else _content_stream("retry-success")

    with caplog.at_level(logging.INFO, logger="backend.modules.chat._inference"):
        # Patch asyncio.sleep so the test doesn't actually wait
        original_sleep = asyncio.sleep
        async def fast_sleep(_s: float) -> None:
            return None
        # ... pass stream_fn into run_inference, capture result
        # The exact run_inference call signature must be matched against
        # the source — adapt as needed.
        # Assert: call_count["n"] == 2, retry log emitted, final content is "retry-success".


@pytest.mark.asyncio
async def test_non_empty_iteration_0_does_not_retry() -> None:
    """First call returns content; verify only one stream_fn call."""
    # ... assert call_count["n"] == 1, no retry log


@pytest.mark.asyncio
async def test_max_retries_caps_at_constant() -> None:
    """All calls return empty; verify exactly 1 + _EMPTY_RESPONSE_MAX_RETRIES
    total stream_fn calls (no infinite loop)."""
    # ... assert call_count["n"] == 1 + _EMPTY_RESPONSE_MAX_RETRIES


@pytest.mark.asyncio
async def test_cancelled_iteration_does_not_retry() -> None:
    """Cancel signal during the first stream; no retry."""
    # ... build a cancel_event that fires immediately, assert call_count["n"] == 1
```

**If the test harness setup is more involved than expected** (run_inference takes many parameters, requires DB fixtures, etc.), pivot to a unit-test for ONLY the retry-decision predicate — extract the predicate into a small helper that can be called with synthetic state and asserted against. The plan does not mandate the test shape, only that the four behaviours above are verified somehow.

- [ ] **Step 2: Run the new tests**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run pytest backend/tests/modules/chat/test_inference_empty_response_retry.py -v`

Expected: 4/4 PASS.

- [ ] **Step 3: Run all chat-module inference tests together**

Run: `PYTHONPATH=/home/chris/workspace/chatsune uv run pytest backend/tests/modules/chat/ -v`

Expected: all pass (no regression).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/modules/chat/test_inference_empty_response_retry.py
git commit -m "Test empty-response retry: triggers on empty, halts on content, caps at constant, respects cancel"
```

---

## Manual verification (controller runs after subagents complete)

These steps are for the human controller after the subagent commits. Do not execute them in any subagent.

1. Restart backend (auto-reload).
2. Reproduce the empty-response symptom with DSv4 Flash on Novita: send a chat with reasoning on, max effort. Expect either:
   - Normal response on the first try (the upstream glitch is intermittent), or
   - Initial empty stream → retry log line in backend log → second/third attempt produces content visible to the user.
3. Verify the retry log line shape:

   ```
   inference.empty_response.retry session=<id> correlation_id=<id>
     attempt=1/2 backoff=1.0s
   ```

4. Push a synthetic empty case if upstream is currently happy: temporarily edit the request to a malformed prompt that the model might decline silently, or simply note that the retry is observable when the upstream glitch surfaces in the wild.
5. Confirm the existing happy path is unaffected: a normal Pro-on-Novita / Pro-on-OR / Flash-on-Ollama-Cloud chat works exactly as before, no spurious retries, no extra log lines on success.

---

## Done conditions

- All tasks 1–2 complete with green tests
- Manual verification 1–5 confirmed by the human controller (when an empty case occurs naturally — do not block merge on a stochastic event)
- Branch has 2 commits (one per task)
- Subagent must not merge to master, must not push, must not switch branches

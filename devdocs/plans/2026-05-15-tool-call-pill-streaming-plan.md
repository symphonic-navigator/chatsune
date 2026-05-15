# Tool-Call Pill Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the full tool-call life cycle visible in the chat UI as one pill morphing through `streaming → executing → completed`, unified across all tools including `generate_image`.

**Architecture:** Adapters emit a new `ToolCallArgsDelta` provider-stream event alongside the existing accumulation pipeline. The inference loop routes these through a new `chat.tool_call.delta` WS event with late-id backfill. The frontend keeps a per-session `streamingToolCalls` slice in the chat store and renders a single `ToolCallPill` component that branches on a `phase` prop. The existing `ToolCallActivity` + `ToolCallPills` pair is replaced.

**Tech Stack:** Python 3 / FastAPI / Pydantic v2 (backend), React + TSX + Vite + Zustand (frontend), pytest (backend tests), Vitest + React Testing Library (frontend tests).

**Spec:** `devdocs/specs/2026-05-15-tool-call-pill-streaming-design.md`

---

## File Structure

### Backend — files created
- `backend/modules/llm/_adapters/_tool_call_streaming.py` — `fragments_to_delta_events` helper, shared between all OpenAI-style adapters
- `backend/tests/modules/llm/adapters/test_tool_call_streaming.py` — unit tests for the helper

### Backend — files modified
- `shared/topics.py` — add `CHAT_TOOL_CALL_DELTA`
- `shared/events/chat.py` — add `ChatToolCallDeltaEvent`
- `backend/modules/llm/_adapters/_events.py` — add `ToolCallArgsDelta`, extend `ToolCallEvent` with `index`, extend union
- `backend/ws/event_bus.py` — register new topic in `_TOPIC_DEFINITIONS`
- `backend/modules/llm/_adapters/_xai_http.py` — emit deltas from `_chunk_to_events`, set `index` on `ToolCallEvent`
- `backend/modules/llm/_adapters/_mistral_http.py` — same
- `backend/modules/llm/_adapters/_community.py` — same
- `backend/modules/llm/_adapters/_openrouter_http.py` — same (Anthropic models pass through here in OpenAI-wrapped form)
- `backend/modules/llm/_adapters/_nano_gpt_http.py` — same (Anthropic models pass through here in OpenAI-wrapped form)
- `backend/modules/llm/_adapters/_tensorix_http.py` — same
- `backend/modules/llm/_adapters/_novita_http.py` — same
- `backend/modules/llm/_adapters/_ollama_http.py` — set `index=0` on `ToolCallEvent` (no streaming)
- `backend/modules/chat/_inference.py` — `ToolCallArgsDelta` case, drain hook, `id` buffer, log line, additional `tool_call` timeline entry for `generate_image`

### Frontend — files created
- `frontend/src/features/chat/ToolCallPill.tsx` — unified pill, three phases
- `frontend/src/features/chat/__tests__/ToolCallPill.test.tsx` — pill tests
- `frontend/src/features/chat/toolLabels.ts` — extracted `TOOL_LABELS` and `friendlyLabel` helper

### Frontend — files modified
- `frontend/src/core/types/events.ts` — add `CHAT_TOOL_CALL_DELTA` topic constant
- `frontend/src/core/store/chatStore.ts` — new `streamingToolCalls` Map slice + 3 reducers, remove `activeToolCalls` + 2 reducers
- `frontend/src/features/chat/useChatStream.ts` — handle `CHAT_TOOL_CALL_DELTA`, call `promoteToolCallToExecuting`/`removeStreamingToolCall`; remove `addToolCall`/`completeToolCall` calls; drop client-side `tool_call` entry for `generate_image` (backend now persists it)
- `frontend/src/features/chat/MessageList.tsx` — render `ToolCallPill` in live + timeline paths; remove `ToolCallActivity` block

### Frontend — files deleted
- `frontend/src/features/chat/ToolCallActivity.tsx`
- `frontend/src/features/chat/ToolCallPills.tsx`
- `frontend/src/features/chat/__tests__/ToolCallPills.test.tsx` (replaced by `ToolCallPill.test.tsx`)

---

## Phase 1 — Shared Contracts

### Task 1: Add `CHAT_TOOL_CALL_DELTA` topic constant

**Files:**
- Modify: `shared/topics.py`
- Modify: `frontend/src/core/types/events.ts`

- [ ] **Step 1: Add backend topic constant**

In `shared/topics.py`, find the existing `CHAT_TOOL_CALL_COMPLETED` line. Add the new constant directly below it:

```python
CHAT_TOOL_CALL_STARTED = "chat.tool_call.started"
CHAT_TOOL_CALL_COMPLETED = "chat.tool_call.completed"
CHAT_TOOL_CALL_DELTA = "chat.tool_call.delta"
```

- [ ] **Step 2: Add frontend topic constant**

In `frontend/src/core/types/events.ts`, mirror the addition in the `Topics` object. Locate the existing `CHAT_TOOL_CALL_COMPLETED` and add below it:

```typescript
CHAT_TOOL_CALL_DELTA: 'chat.tool_call.delta',
```

- [ ] **Step 3: Verify backend imports work**

Run: `uv run python -c "from shared.topics import Topics; print(Topics.CHAT_TOOL_CALL_DELTA)"`
Expected: prints `chat.tool_call.delta`.

- [ ] **Step 4: Verify frontend type compiles**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add shared/topics.py frontend/src/core/types/events.ts
git commit -m "Add CHAT_TOOL_CALL_DELTA topic constant"
```

---

### Task 2: Add `ChatToolCallDeltaEvent` Pydantic model

**Files:**
- Modify: `shared/events/chat.py`

- [ ] **Step 1: Add the event class**

Open `shared/events/chat.py`. After the `ChatToolCallCompletedEvent` class, add:

```python
class ChatToolCallDeltaEvent(BaseModel):
    type: str = "chat.tool_call.delta"
    correlation_id: str
    tool_call_id: str
    tool_index: int
    tool_name: str | None = None
    args_delta: str
    timestamp: datetime
```

- [ ] **Step 2: Verify**

Run: `uv run python -c "from shared.events.chat import ChatToolCallDeltaEvent; import datetime as d; print(ChatToolCallDeltaEvent(correlation_id='c', tool_call_id='t', tool_index=0, args_delta='x', timestamp=d.datetime.now(d.timezone.utc)))"`
Expected: prints a valid event.

- [ ] **Step 3: Commit**

```bash
git add shared/events/chat.py
git commit -m "Add ChatToolCallDeltaEvent model"
```

---

### Task 3: Add `ToolCallArgsDelta` and `index` field in adapter events

**Files:**
- Modify: `backend/modules/llm/_adapters/_events.py`

- [ ] **Step 1: Add `ToolCallArgsDelta` and extend `ToolCallEvent`**

Open `backend/modules/llm/_adapters/_events.py`. Replace the existing `ToolCallEvent` class and add `ToolCallArgsDelta` directly above it:

```python
class ToolCallArgsDelta(BaseModel):
    """Provider-stream event: a fragment of a not-yet-finalised tool call.

    Streaming adapters emit one of these per upstream fragment for each tool
    call still being assembled. ``id`` and ``name`` are filled in as soon as
    the provider supplies them; deltas emitted before either field is known
    carry ``None`` and the inference loop performs late backfill.

    ``arguments_delta`` is NOT cumulative — it is the new fragment only.
    """
    index: int
    id: str | None = None
    name: str | None = None
    arguments_delta: str


class ToolCallEvent(BaseModel):
    """A tool call emitted by the model during a streaming response."""

    id: str       # tool-call ID (from provider where available, else synthesised)
    name: str
    arguments: str  # JSON-encoded argument object
    index: int      # OpenAI-style index for parallel calls; used by the
                    # inference loop for late-id backfill
```

- [ ] **Step 2: Extend the union**

At the bottom of the same file, add `ToolCallArgsDelta` to the union:

```python
ProviderStreamEvent = (
    ContentDelta
    | ThinkingDelta
    | ToolCallEvent
    | ToolCallArgsDelta
    | StreamDone
    | StreamError
    | StreamSlow
    | StreamAborted
    | StreamRefused
)
```

- [ ] **Step 3: Verify the file imports cleanly**

Run: `uv run python -c "from backend.modules.llm._adapters._events import ToolCallArgsDelta, ToolCallEvent, ProviderStreamEvent; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 4: Update existing `ToolCallEvent` constructions in tests**

Adding `index: int` as a required field breaks every existing call site that constructs `ToolCallEvent(...)` without `index`. Find them:

```bash
grep -rn "ToolCallEvent(" backend/ tests/ | grep -v "_events.py"
```

For each match, add `index=0` to the constructor call. Examples of files likely affected:
- `backend/tests/modules/chat/test_tool_error_recovery.py`
- `backend/tests/modules/chat/test_inference_events.py` (if any)
- `backend/tests/modules/chat/test_inference_empty_response_retry.py`
- `backend/tests/modules/chat/test_orchestrator_cancel.py`
- adapter test files (Tasks 6–10 also touch these, but those Tasks already overwrite the assertions — fine to make this update in those Tasks)

For test files outside the adapter tests, change every `ToolCallEvent(id=..., name=..., arguments=...)` to add `, index=0` as the last keyword. The exact index value doesn't matter for these tests — they predate the field — so `0` is the conventional default.

- [ ] **Step 5: Run the full backend test suite to confirm no `TypeError: missing required argument 'index'`**

Run: `uv run pytest backend/tests/modules/chat/ -v`
Expected: pre-existing tests pass.

If any test breaks with a different error (semantic, not "missing index"), this is a real regression — investigate before continuing.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_adapters/_events.py backend/tests/modules/chat/
git commit -m "Add ToolCallArgsDelta and index field on ToolCallEvent"
```

---

### Task 4: Register `CHAT_TOOL_CALL_DELTA` in the WS event-bus replay table

**Files:**
- Modify: `backend/ws/event_bus.py`

- [ ] **Step 1: Add to `_TOPIC_DEFINITIONS`**

Open `backend/ws/event_bus.py`. Locate the `# Tool call progress` comment in `_TOPIC_DEFINITIONS` (around line 116). Add the new topic right after the existing two entries:

```python
    # Tool call progress — target user only
    Topics.CHAT_TOOL_CALL_STARTED: ([], True),
    Topics.CHAT_TOOL_CALL_COMPLETED: ([], True),
    Topics.CHAT_TOOL_CALL_DELTA: ([], True),
    Topics.CHAT_CLIENT_TOOL_DISPATCH: ([], True),
```

- [ ] **Step 2: Add to `_SKIP_PERSISTENCE`**

In the same file, locate `_SKIP_PERSISTENCE` (around line 221). Tool-call events are ephemeral (the persisted message timeline carries the durable record), so add:

```python
_SKIP_PERSISTENCE: set[str] = {
    Topics.CHAT_CONTENT_DELTA,
    Topics.CHAT_THINKING_DELTA,
    Topics.CHAT_TOOL_CALL_STARTED,
    Topics.CHAT_TOOL_CALL_COMPLETED,
    Topics.CHAT_TOOL_CALL_DELTA,
    Topics.CHAT_CLIENT_TOOL_DISPATCH,
    Topics.CHAT_WEB_SEARCH_CONTEXT,
    ...
```

- [ ] **Step 3: Verify**

Run: `uv run python -c "from backend.ws.event_bus import _TOPIC_DEFINITIONS, _SKIP_PERSISTENCE; from shared.topics import Topics; assert Topics.CHAT_TOOL_CALL_DELTA in _TOPIC_DEFINITIONS; assert Topics.CHAT_TOOL_CALL_DELTA in _SKIP_PERSISTENCE; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add backend/ws/event_bus.py
git commit -m "Register CHAT_TOOL_CALL_DELTA in event-bus topic table"
```

---

## Phase 2 — Adapter Layer

### Task 5: Build `_tool_call_streaming.py` helper + tests

**Files:**
- Create: `backend/modules/llm/_adapters/_tool_call_streaming.py`
- Create: `backend/tests/modules/llm/adapters/test_tool_call_streaming.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/modules/llm/adapters/test_tool_call_streaming.py`:

```python
from backend.modules.llm._adapters._events import ToolCallArgsDelta
from backend.modules.llm._adapters._tool_call_streaming import (
    fragments_to_delta_events,
)


class _FakeAccumulator:
    """Minimal stand-in for _ToolCallAccumulator, exposing the slot dict and
    capturing ingested fragments. Real accumulators live per-adapter; the
    helper only touches `_by_index` for read access and calls `.ingest()`."""

    def __init__(self):
        self._by_index: dict[int, dict] = {}
        self.ingested: list[list[dict]] = []

    def ingest(self, frags: list[dict]) -> None:
        self.ingested.append(frags)
        for f in frags:
            idx = f.get("index")
            if idx is None:
                continue
            slot = self._by_index.setdefault(
                idx, {"id": None, "name": "", "args": ""},
            )
            if f.get("id"):
                slot["id"] = f["id"]
            fn = f.get("function") or {}
            if fn.get("name"):
                slot["name"] = fn["name"]
            if fn.get("arguments"):
                slot["args"] += fn["arguments"]


def test_emits_one_event_per_fragment_with_args():
    acc = _FakeAccumulator()
    frags = [
        {"index": 0, "id": "call_x", "function": {"name": "search", "arguments": '{"q'}},
        {"index": 0, "function": {"arguments": '":"x"}'}},
    ]
    events = fragments_to_delta_events(frags, acc)
    assert len(events) == 2
    assert events[0] == ToolCallArgsDelta(
        index=0, id="call_x", name="search", arguments_delta='{"q',
    )
    assert events[1] == ToolCallArgsDelta(
        index=0, id="call_x", name="search", arguments_delta='":"x"}',
    )
    # accumulator was fed
    assert acc.ingested == [frags]


def test_emits_for_id_or_name_even_without_args():
    """First fragment often carries only id and name, no arguments yet."""
    acc = _FakeAccumulator()
    frags = [
        {"index": 0, "id": "call_x", "function": {"name": "search"}},
    ]
    events = fragments_to_delta_events(frags, acc)
    assert len(events) == 1
    assert events[0].arguments_delta == ""
    assert events[0].id == "call_x"
    assert events[0].name == "search"


def test_skips_fragments_without_index():
    """Some upstream chunks contain top-level tool_calls but no per-index
    fragments (e.g. heartbeats). Skip them entirely."""
    acc = _FakeAccumulator()
    frags = [{"function": {"arguments": "x"}}]
    events = fragments_to_delta_events(frags, acc)
    assert events == []


def test_resolves_id_from_accumulator_state_when_fragment_omits_it():
    acc = _FakeAccumulator()
    # First fragment seeds the id.
    fragments_to_delta_events(
        [{"index": 0, "id": "call_x", "function": {"name": "s"}}], acc,
    )
    # Second fragment omits id — helper resolves from accumulator state.
    events = fragments_to_delta_events(
        [{"index": 0, "function": {"arguments": "y"}}], acc,
    )
    assert events[0].id == "call_x"


def test_parallel_calls_separate_indices():
    acc = _FakeAccumulator()
    frags = [
        {"index": 0, "id": "a", "function": {"name": "f", "arguments": "1"}},
        {"index": 1, "id": "b", "function": {"name": "g", "arguments": "2"}},
    ]
    events = fragments_to_delta_events(frags, acc)
    assert len(events) == 2
    assert events[0].index == 0 and events[0].id == "a"
    assert events[1].index == 1 and events[1].id == "b"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_tool_call_streaming.py -v`
Expected: ImportError or ModuleNotFoundError for `_tool_call_streaming`.

- [ ] **Step 3: Write the minimal implementation**

Create `backend/modules/llm/_adapters/_tool_call_streaming.py`:

```python
"""Helper for streaming OpenAI-style tool-call fragments through the
adapter layer as ``ToolCallArgsDelta`` events.

Used by every OpenAI-compatible adapter (xAI, Mistral, Community,
nano-gpt). Anthropic has its own delta shape and does not use this
helper.
"""
from __future__ import annotations

from typing import Any

from backend.modules.llm._adapters._events import ToolCallArgsDelta


def fragments_to_delta_events(
    fragments: list[dict[str, Any]],
    acc: Any,
) -> list[ToolCallArgsDelta]:
    """Map raw OpenAI-style tool_call fragments to ``ToolCallArgsDelta``
    events and feed them into ``acc`` for final accumulation.

    Order of operations: build events first (reading current accumulator
    state for id/name resolution), then ``acc.ingest(fragments)``. This
    way each emitted event reflects the fragment AS SEEN, not the
    post-ingest state, which matters when a single fragment supplies a
    previously-unknown id or name.

    ``acc`` is duck-typed against ``_ToolCallAccumulator`` defined in the
    adapter modules. The helper only reads ``acc._by_index`` and calls
    ``acc.ingest()`` — both stable parts of the contract.
    """
    events: list[ToolCallArgsDelta] = []
    for frag in fragments:
        idx = frag.get("index")
        if idx is None:
            continue
        fn = frag.get("function") or {}
        existing = acc._by_index.get(idx, {})
        resolved_id = frag.get("id") or existing.get("id")
        resolved_name = fn.get("name") or existing.get("name") or None
        args_fragment = fn.get("arguments") or ""
        if args_fragment or frag.get("id") or fn.get("name"):
            events.append(ToolCallArgsDelta(
                index=idx,
                id=resolved_id,
                name=resolved_name,
                arguments_delta=args_fragment,
            ))
    acc.ingest(fragments)
    return events
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_tool_call_streaming.py -v`
Expected: all five tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_tool_call_streaming.py \
        backend/tests/modules/llm/adapters/test_tool_call_streaming.py
git commit -m "Add fragments_to_delta_events helper for streaming tool-call args"
```

---

### Task 6: Wire helper into `_xai_http.py` and set `index` on final `ToolCallEvent`

**Files:**
- Modify: `backend/modules/llm/_adapters/_xai_http.py`

- [ ] **Step 1: Update `_chunk_to_events` to emit deltas**

In `_xai_http.py`, locate the block in `_chunk_to_events` that processes `tool_frags` (around line 185–187):

```python
tool_frags = delta.get("tool_calls") or []
if tool_frags:
    acc.ingest(tool_frags)
```

Replace with:

```python
tool_frags = delta.get("tool_calls") or []
if tool_frags:
    from backend.modules.llm._adapters._tool_call_streaming import (
        fragments_to_delta_events,
    )
    events.extend(fragments_to_delta_events(tool_frags, acc))
```

- [ ] **Step 2: Update `_ToolCallAccumulator.finalised` to include `index`**

In the same file, locate the `finalised` method on `_ToolCallAccumulator` (around line 131). Replace it with:

```python
def finalised(self) -> list[dict]:
    """Return accumulated calls as [{id, name, arguments, index}, ...]."""
    calls: list[dict] = []
    for idx, slot in sorted(self._by_index.items()):
        calls.append({
            "id": slot["id"] or f"call_{uuid4().hex[:12]}",
            "name": slot["name"],
            "arguments": slot["args"] or "{}",
            "index": idx,
        })
    return calls
```

- [ ] **Step 3: Update the `ToolCallEvent` construction at `finish_reason="tool_calls"`**

In the same file, find where `ToolCallEvent` is constructed (around line 197). Replace with:

```python
if finish == "tool_calls":
    for call in acc.finalised():
        events.append(ToolCallEvent(
            id=call["id"], name=call["name"],
            arguments=call["arguments"],
            index=call["index"],
        ))
```

- [ ] **Step 4: Update existing tests to accept extra delta events**

Find the existing test file for the xAI adapter. Run:

```bash
ls backend/tests/modules/llm/adapters/ | grep xai
```

Open each match. For every assertion of the form `assert events == [ToolCallEvent(...)]` or `assert len(events) == 1`, rewrite to "contains-style" assertions:

```python
# Before
assert events == [ToolCallEvent(id="call_x", name="search", arguments='{}', index=0)]

# After
tool_call_events = [e for e in events if isinstance(e, ToolCallEvent)]
assert tool_call_events == [
    ToolCallEvent(id="call_x", name="search", arguments='{}', index=0),
]
```

This pattern keeps existing finalisation behaviour verified while allowing the new `ToolCallArgsDelta` events to coexist in the same stream.

- [ ] **Step 5: Add a new delta-emission test**

The xAI test file is `backend/tests/modules/llm/adapters/test_xai_http.py`. Append:

```python
def test_streaming_tool_call_emits_args_deltas():
    """Streaming a tool call should emit one ToolCallArgsDelta per
    fragment, followed by exactly one finalised ToolCallEvent."""
    from backend.modules.llm._adapters._xai_http import (
        _ToolCallAccumulator, _chunk_to_events,
    )
    from backend.modules.llm._adapters._events import (
        ToolCallArgsDelta, ToolCallEvent,
    )
    acc = _ToolCallAccumulator()
    # Fragment 1: id + name + opening of args
    chunk1 = {"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "call_x",
         "function": {"name": "search", "arguments": '{"q'}},
    ]}, "finish_reason": None}]}
    # Fragment 2: rest of args
    chunk2 = {"choices": [{"delta": {"tool_calls": [
        {"index": 0, "function": {"arguments": '":"x"}'}},
    ]}, "finish_reason": None}]}
    # Final chunk
    chunk3 = {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}
    events: list = []
    events.extend(_chunk_to_events(chunk1, acc))
    events.extend(_chunk_to_events(chunk2, acc))
    events.extend(_chunk_to_events(chunk3, acc))
    deltas = [e for e in events if isinstance(e, ToolCallArgsDelta)]
    finals = [e for e in events if isinstance(e, ToolCallEvent)]
    assert len(deltas) == 2
    assert deltas[0].arguments_delta == '{"q'
    assert deltas[1].arguments_delta == '":"x"}'
    assert len(finals) == 1
    assert finals[0].arguments == '{"q":"x"}'
    assert finals[0].index == 0
```

- [ ] **Step 6: Run xAI adapter tests**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_xai_http.py backend/tests/modules/llm/adapters/test_xai_image_groups.py -v`
Expected: all tests pass, including the new delta-emission test.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/llm/_adapters/_xai_http.py \
        backend/tests/modules/llm/adapters/test_xai_http.py
git commit -m "Wire xAI adapter to emit tool-call args deltas"
```

---

### Task 7: Wire helper into `_mistral_http.py`

**Files:**
- Modify: `backend/modules/llm/_adapters/_mistral_http.py`

- [ ] **Step 1: Update `_chunk_to_events` (analogous to xAI)**

In `_mistral_http.py`, locate the `tool_frags = delta.get("tool_calls") or []` block (around line 251). Replace:

```python
tool_frags = delta.get("tool_calls") or []
if tool_frags:
    from backend.modules.llm._adapters._tool_call_streaming import (
        fragments_to_delta_events,
    )
    events.extend(fragments_to_delta_events(tool_frags, acc))
```

- [ ] **Step 2: Update `_ToolCallAccumulator.finalised` and `ToolCallEvent` construction**

Apply the same two replacements as in Task 6 Step 2 and Step 3 (the accumulator and `finish_reason` handler in `_mistral_http.py` mirror the xAI shape — search for `finalised` and `finish == "tool_calls"` to locate them).

- [ ] **Step 3: Update existing tests to use containment assertions**

Open `backend/tests/modules/llm/adapters/test_mistral_http.py`. Rewrite final-event assertions to filter `events` by `isinstance(e, ToolCallEvent)` first (same pattern as Task 6 Step 4).

- [ ] **Step 4: Add streaming test (analogous to Task 6 Step 5)**

```python
def test_streaming_tool_call_emits_args_deltas_mistral():
    from backend.modules.llm._adapters._mistral_http import (
        _ToolCallAccumulator, _chunk_to_events,
    )
    from backend.modules.llm._adapters._events import (
        ToolCallArgsDelta, ToolCallEvent,
    )
    acc = _ToolCallAccumulator()
    chunk1 = {"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "call_x",
         "function": {"name": "search", "arguments": '{"q'}},
    ]}, "finish_reason": None}]}
    chunk2 = {"choices": [{"delta": {"tool_calls": [
        {"index": 0, "function": {"arguments": '":"x"}'}},
    ]}, "finish_reason": None}]}
    chunk3 = {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}
    events: list = []
    events.extend(_chunk_to_events(chunk1, acc))
    events.extend(_chunk_to_events(chunk2, acc))
    events.extend(_chunk_to_events(chunk3, acc))
    deltas = [e for e in events if isinstance(e, ToolCallArgsDelta)]
    finals = [e for e in events if isinstance(e, ToolCallEvent)]
    assert len(deltas) == 2
    assert finals[0].arguments == '{"q":"x"}'
    assert finals[0].index == 0
```

- [ ] **Step 5: Run Mistral adapter tests**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_mistral_http.py -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_adapters/_mistral_http.py \
        backend/tests/modules/llm/adapters/test_mistral_http.py
git commit -m "Wire Mistral adapter to emit tool-call args deltas"
```

---

### Task 8: Wire helper into `_community.py` (covers nano-gpt and other OpenAI-compatible adapters)

**Files:**
- Modify: `backend/modules/llm/_adapters/_community.py`

- [ ] **Step 1: Inspect the community adapter's tool-call handling**

Read `backend/modules/llm/_adapters/_community.py` around line 78 (where `delta.tool_calls` is currently handled). The community adapter uses a slightly different shape from `_xai_http.py` — confirm whether it has a `_ToolCallAccumulator` class or accumulates inline.

If the community adapter does NOT have a `_ToolCallAccumulator` class (it processes calls inline), refactor inline accumulation into a small local class first, mirroring the xAI shape (just the `_by_index` dict and `ingest` method). This is a small refactor required for the helper to work — keep it minimal.

- [ ] **Step 2: Apply the same three changes as Task 6**

After step 1, the community adapter has a `_ToolCallAccumulator` with `_by_index` and `ingest`. Apply the same three changes from Task 6:

1. Replace direct `acc.ingest(tool_frags)` with `events.extend(fragments_to_delta_events(tool_frags, acc))`
2. Add `index` to the dict returned by `finalised()`
3. Pass `index=call["index"]` when constructing `ToolCallEvent` at finish_reason

- [ ] **Step 3: Update existing tests with containment-style assertions**

Open `backend/tests/modules/llm/adapters/test_community.py`. Rewrite final-event assertions to filter by `isinstance(e, ToolCallEvent)` first. Also check `backend/tests/integration/test_community_e2e.py` for any related assertions and update similarly if needed.

- [ ] **Step 4: Add streaming-delta test (analogous to Task 6 Step 5)**

```python
def test_streaming_tool_call_emits_args_deltas_community():
    from backend.modules.llm._adapters._community import (
        _ToolCallAccumulator, _chunk_to_events,
    )
    from backend.modules.llm._adapters._events import (
        ToolCallArgsDelta, ToolCallEvent,
    )
    acc = _ToolCallAccumulator()
    chunk1 = {"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "call_x",
         "function": {"name": "f", "arguments": '{"q'}},
    ]}, "finish_reason": None}]}
    chunk2 = {"choices": [{"delta": {"tool_calls": [
        {"index": 0, "function": {"arguments": '":"x"}'}},
    ]}, "finish_reason": None}]}
    chunk3 = {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}
    events: list = []
    events.extend(_chunk_to_events(chunk1, acc))
    events.extend(_chunk_to_events(chunk2, acc))
    events.extend(_chunk_to_events(chunk3, acc))
    assert sum(1 for e in events if isinstance(e, ToolCallArgsDelta)) == 2
    finals = [e for e in events if isinstance(e, ToolCallEvent)]
    assert finals[0].arguments == '{"q":"x"}'
    assert finals[0].index == 0
```

- [ ] **Step 5: Run community adapter tests**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_community.py backend/tests/integration/test_community_e2e.py -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_adapters/_community.py \
        backend/tests/modules/llm/adapters/test_community.py \
        backend/tests/integration/test_community_e2e.py
git commit -m "Wire community adapter to emit tool-call args deltas"
```

---

### Task 9: Wire the remaining OpenAI-style adapters (OpenRouter, nano-gpt, Tensorix, Novita)

> **Note:** chatsune does not have a separate Anthropic adapter — Claude
> models are served via OpenRouter and nano-gpt, both of which expose
> OpenAI-compatible SSE with `tool_calls[].index`/`function.arguments`
> fragments. So this task applies the same pattern as Tasks 6–8 to four
> more adapters: OpenRouter, nano-gpt, Tensorix, Novita.

**Files:**
- Modify: `backend/modules/llm/_adapters/_openrouter_http.py`
- Modify: `backend/modules/llm/_adapters/_nano_gpt_http.py`
- Modify: `backend/modules/llm/_adapters/_tensorix_http.py`
- Modify: `backend/modules/llm/_adapters/_novita_http.py`

For each of the four files, perform the same three edits as in Task 6 (steps 1, 2, 3): swap the `acc.ingest(tool_frags)` call for `events.extend(fragments_to_delta_events(tool_frags, acc))`, add `index` to `finalised()`'s returned dicts, and pass `index=call["index"]` into `ToolCallEvent` at `finish_reason == "tool_calls"`.

Each adapter has a `_ToolCallAccumulator` class and a `_chunk_to_events` function with the same shape as `_xai_http.py` — the OpenRouter file's header explicitly notes "Structurally a Mistral clone".

#### Sub-task 9a: OpenRouter

- [ ] **Step 1: Apply the three edits to `_openrouter_http.py`**

Same pattern as Task 6 Steps 1–3.

- [ ] **Step 2: Update existing tests with containment-style assertions**

Open `backend/tests/modules/llm/adapters/test_openrouter_http.py`. Convert equality assertions on `events == [...]` lists into `[e for e in events if isinstance(e, ToolCallEvent)] == [...]`.

- [ ] **Step 3: Add a streaming-delta test**

```python
def test_streaming_tool_call_emits_args_deltas_openrouter():
    from backend.modules.llm._adapters._openrouter_http import (
        _ToolCallAccumulator, _chunk_to_events,
    )
    from backend.modules.llm._adapters._events import (
        ToolCallArgsDelta, ToolCallEvent,
    )
    acc = _ToolCallAccumulator()
    chunk1 = {"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "call_x",
         "function": {"name": "search", "arguments": '{"q'}},
    ]}, "finish_reason": None}]}
    chunk2 = {"choices": [{"delta": {"tool_calls": [
        {"index": 0, "function": {"arguments": '":"x"}'}},
    ]}, "finish_reason": None}]}
    chunk3 = {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}
    events: list = []
    events.extend(_chunk_to_events(chunk1, acc))
    events.extend(_chunk_to_events(chunk2, acc))
    events.extend(_chunk_to_events(chunk3, acc))
    assert sum(1 for e in events if isinstance(e, ToolCallArgsDelta)) == 2
    finals = [e for e in events if isinstance(e, ToolCallEvent)]
    assert finals[0].arguments == '{"q":"x"}'
    assert finals[0].index == 0
```

- [ ] **Step 4: Run OpenRouter tests**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_openrouter_http.py -v`
Expected: all tests pass.

#### Sub-task 9b: nano-gpt

- [ ] **Step 5: Apply the three edits to `_nano_gpt_http.py`**

Same pattern.

- [ ] **Step 6: Update existing tests and add streaming-delta test**

Open `backend/tests/modules/llm/adapters/test_nano_gpt_http.py`. Apply containment-style assertions and add a streaming-delta test (paste the body from Step 3 above, change the import path and the test name to `..._nano_gpt`).

- [ ] **Step 7: Run nano-gpt tests**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_nano_gpt_http.py -v`
Expected: all tests pass.

#### Sub-task 9c: Tensorix

- [ ] **Step 8: Apply the three edits to `_tensorix_http.py`**

Same pattern.

- [ ] **Step 9: Update existing tests and add streaming-delta test**

Open `backend/tests/modules/llm/adapters/test_tensorix_http.py`. Apply containment-style assertions and add a streaming-delta test (paste the body from Step 3, change names).

- [ ] **Step 10: Run Tensorix tests**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_tensorix_http.py -v`
Expected: all tests pass.

#### Sub-task 9d: Novita

- [ ] **Step 11: Apply the three edits to `_novita_http.py`**

Same pattern.

- [ ] **Step 12: Update existing tests and add streaming-delta test**

Open `backend/tests/modules/llm/adapters/test_novita_http.py`. Apply containment-style assertions and add a streaming-delta test (paste the body from Step 3, change names).

- [ ] **Step 13: Run Novita tests**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_novita_http.py -v`
Expected: all tests pass.

- [ ] **Step 14: Commit**

```bash
git add backend/modules/llm/_adapters/_openrouter_http.py \
        backend/modules/llm/_adapters/_nano_gpt_http.py \
        backend/modules/llm/_adapters/_tensorix_http.py \
        backend/modules/llm/_adapters/_novita_http.py \
        backend/tests/modules/llm/adapters/test_openrouter_http.py \
        backend/tests/modules/llm/adapters/test_nano_gpt_http.py \
        backend/tests/modules/llm/adapters/test_tensorix_http.py \
        backend/tests/modules/llm/adapters/test_novita_http.py
git commit -m "Wire remaining OpenAI-style adapters (OpenRouter, nano-gpt, Tensorix, Novita) for tool-call delta streaming"
```

---

### Task 10: Update Ollama adapter to set `index` (no delta streaming)

**Files:**
- Modify: `backend/modules/llm/_adapters/_ollama_http.py`

- [ ] **Step 1: Find `ToolCallEvent` construction in the Ollama adapter**

Run: `grep -n "ToolCallEvent" backend/modules/llm/_adapters/_ollama_http.py`

- [ ] **Step 2: Add `index` to each construction**

Ollama returns tool calls fully formed as a list in a single message. Each call's position in the list is its index:

```python
# Before
for tc in tool_calls:
    events.append(ToolCallEvent(
        id=tc.get("id") or f"call_{uuid4().hex[:12]}",
        name=tc["function"]["name"],
        arguments=json.dumps(tc["function"]["arguments"]),
    ))

# After
for i, tc in enumerate(tool_calls):
    events.append(ToolCallEvent(
        id=tc.get("id") or f"call_{uuid4().hex[:12]}",
        name=tc["function"]["name"],
        arguments=json.dumps(tc["function"]["arguments"]),
        index=i,
    ))
```

Match the actual variable names in the file.

- [ ] **Step 3: Update existing Ollama tests**

Open `backend/tests/modules/llm/adapters/test_ollama_http.py`. If assertions compare `ToolCallEvent(...)` for equality, add `index=...` to the expected value. No `ToolCallArgsDelta` events are emitted by Ollama, so no new streaming tests.

Also check `tests/llm/test_ollama_http_adapter.py` (a second Ollama test file outside backend/tests) — apply the same update if it asserts on `ToolCallEvent` shape.

- [ ] **Step 4: Run Ollama tests**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_ollama_http.py tests/llm/test_ollama_http_adapter.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_ollama_http.py \
        backend/tests/modules/llm/adapters/test_ollama_http.py \
        tests/llm/test_ollama_http_adapter.py
git commit -m "Set index on Ollama adapter ToolCallEvents (no streaming path)"
```

---

## Phase 3 — Inference Loop

### Task 11: Add `ToolCallArgsDelta` case and id-buffer in `_inference.py`

**Files:**
- Modify: `backend/modules/chat/_inference.py`

- [ ] **Step 1: Add the buffer initialisation at iteration start**

Open `backend/modules/chat/_inference.py`. Locate the start of the per-iteration block (where `iter_content`, `iter_thinking`, `iter_tool_calls` are initialised — around line 285). Add:

```python
# Per-iteration buffer for tool-call delta events whose tool_call_id is
# not yet known. Keys are the OpenAI-style index. Backfilled when the id
# arrives in a later fragment, or in the finally-block drain if it never
# arrives mid-stream (e.g. xAI synthesises ids only at finalisation).
tool_call_id_buffer: dict[int, dict] = {}
```

- [ ] **Step 2: Add the `ToolCallArgsDelta` case to the switch**

In the same file, find the `match event:` block inside the `async for event in stream` loop. Add a new case after `ContentDelta` and `ThinkingDelta`:

```python
case ToolCallArgsDelta(index=idx, id=tc_id, name=tc_name, arguments_delta=frag):
    slot = tool_call_id_buffer.setdefault(idx, {
        "id": None, "name": None, "pending_events": [],
        "chars": 0, "deltas": 0,
    })
    if tc_id and slot["id"] is None:
        slot["id"] = tc_id
        # Backfill all previously-queued events for this index.
        for pending in slot["pending_events"]:
            pending.tool_call_id = tc_id
            await emit_fn(pending)
        slot["pending_events"] = []
    if tc_name and slot["name"] is None:
        slot["name"] = tc_name

    resolved_id = slot["id"] or tc_id
    slot["chars"] += len(frag)
    slot["deltas"] += 1

    event_out = ChatToolCallDeltaEvent(
        correlation_id=correlation_id,
        tool_call_id=resolved_id or "",
        tool_index=idx,
        tool_name=slot["name"],
        args_delta=frag,
        timestamp=datetime.now(timezone.utc),
    )
    if resolved_id:
        await emit_fn(event_out)
    else:
        slot["pending_events"].append(event_out)
```

- [ ] **Step 3: Add the necessary imports**

At the top of `_inference.py`, add to the existing imports:

```python
from backend.modules.llm._adapters._events import ToolCallArgsDelta
from shared.events.chat import ChatToolCallDeltaEvent
```

(`ChatToolCallDeltaEvent` is likely already adjacent to `ChatToolCallStartedEvent` in the import block — add it there.)

- [ ] **Step 4: Add the drain hook in the `finally` block**

Locate the `finally:` block at the end of the `async for` loop (around line 406). Inside it, AFTER the `full_content += iter_content` lines and BEFORE the post-iteration logging, add:

```python
# Pending-Drain: any deltas emitted before the provider supplied an id
# are now matchable against iter_tool_calls (which carries the
# accumulator's index). Backfill and emit them in order.
for tc in iter_tool_calls:
    slot = tool_call_id_buffer.get(tc.index)
    if slot and slot["pending_events"]:
        for pending in slot["pending_events"]:
            pending.tool_call_id = tc.id
            await emit_fn(pending)
        slot["pending_events"] = []
```

- [ ] **Step 5: Add a log line for streamed tool calls**

Inside the same `finally` block, after the drain hook, add per-tool-call info log:

```python
if settings.inference_logging:
    for tc in iter_tool_calls:
        slot = tool_call_id_buffer.get(tc.index, {})
        _log.info(
            "inference.tool_call.stream session=%s correlation_id=%s "
            "tool_call_id=%s tool=%s args_chars=%d deltas=%d",
            session_id, correlation_id, tc.id, tc.name,
            slot.get("chars", 0), slot.get("deltas", 0),
        )
```

- [ ] **Step 6: Run the existing inference tests to catch regressions**

Run: `uv run pytest backend/tests/modules/chat/ -v`
Expected: all tests pass. If any test breaks, the regression is most likely in assertion shape (e.g. expecting a specific event count) — adjust to the actual new count and re-run.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/chat/_inference.py
git commit -m "Route ToolCallArgsDelta through inference loop with id backfill"
```

---

### Task 12: Inference-loop tests (streaming, non-streaming, late-id, drain)

**Files:**
- Create: `backend/tests/modules/chat/test_inference_tool_call_deltas.py`

The existing pattern in `backend/tests/modules/chat/test_tool_error_recovery.py` uses `InferenceRunner().run(...)` with local `_make_stream_fn`, `_make_emit_capture`, `_make_save_capture` helpers. Mirror that pattern.

- [ ] **Step 1: Write the test file (failing on import)**

Create `backend/tests/modules/chat/test_inference_tool_call_deltas.py`:

```python
"""Tests for tool-call delta routing through the inference loop.

Verifies the new ChatToolCallDeltaEvent emission path: streaming
adapters emit ToolCallArgsDelta which the loop forwards as
chat.tool_call.delta WS events, with late-id backfill and an
end-of-iteration drain hook for ids generated only at finalisation.
"""
import pytest

from backend.modules.chat._inference import InferenceRunner
from backend.modules.llm._adapters._events import (
    ContentDelta, StreamDone, ToolCallArgsDelta, ToolCallEvent,
)
from shared.events.chat import (
    ChatStreamEndedEvent, ChatToolCallCompletedEvent,
    ChatToolCallDeltaEvent, ChatToolCallStartedEvent,
)


async def _async_iter(events):
    for ev in events:
        yield ev


def _make_stream_fn(scripted_iterations):
    state = {"i": 0}

    async def stream_fn(_extra_messages):
        idx = state["i"]
        state["i"] += 1
        events = scripted_iterations[idx] if idx < len(scripted_iterations) else []
        return _async_iter(events)

    return stream_fn


def _make_emit_capture():
    captured: list = []

    async def emit(event):
        captured.append(event)

    return captured, emit


def _make_save_capture():
    captured: dict = {}

    async def save(*, content, thinking, usage, events, refusal_text, status):
        captured.update(dict(
            content=content, thinking=thinking, usage=usage,
            events=events, refusal_text=refusal_text, status=status,
            called=True,
        ))
        return "msg-id-1"

    return captured, save


async def _noop_executor(user_id, tool_name, args_json, *, tool_call_id):
    return "{}"


@pytest.mark.asyncio
async def test_streaming_tool_call_emits_delta_events_in_order() -> None:
    """Adapter that yields ToolCallArgsDelta before its final ToolCallEvent
    should produce ChatToolCallDeltaEvents in order, followed by
    ChatToolCallStartedEvent, then ChatToolCallCompletedEvent."""
    iter_one = [
        ToolCallArgsDelta(index=0, id="call_x", name="t",
                          arguments_delta='{"q'),
        ToolCallArgsDelta(index=0, id="call_x", name="t",
                          arguments_delta='":"hi"}'),
        ToolCallEvent(id="call_x", name="t",
                      arguments='{"q":"hi"}', index=0),
        StreamDone(input_tokens=5, output_tokens=10),
    ]
    iter_two = [
        ContentDelta(delta="done"),
        StreamDone(input_tokens=3, output_tokens=2),
    ]
    emitted, emit_fn = _make_emit_capture()
    _, save_fn = _make_save_capture()

    await InferenceRunner().run(
        user_id="u", session_id="s", correlation_id="c",
        stream_fn=_make_stream_fn([iter_one, iter_two]),
        emit_fn=emit_fn, save_fn=save_fn,
        cancel_event=None, tool_executor_fn=_noop_executor,
    )

    deltas = [e for e in emitted if isinstance(e, ChatToolCallDeltaEvent)]
    starteds = [e for e in emitted if isinstance(e, ChatToolCallStartedEvent)]
    completeds = [e for e in emitted if isinstance(e, ChatToolCallCompletedEvent)]
    assert len(deltas) == 2
    assert deltas[0].tool_call_id == "call_x"
    assert deltas[0].args_delta == '{"q'
    assert deltas[1].args_delta == '":"hi"}'
    # Order: deltas before started before completed.
    delta_idxs = [emitted.index(d) for d in deltas]
    started_idx = emitted.index(starteds[0])
    completed_idx = emitted.index(completeds[0])
    assert all(i < started_idx for i in delta_idxs)
    assert started_idx < completed_idx


@pytest.mark.asyncio
async def test_non_streaming_adapter_emits_no_deltas() -> None:
    """Adapter that yields only the final ToolCallEvent (no deltas) — the
    inference loop should NOT emit ChatToolCallDeltaEvent."""
    iter_one = [
        ToolCallEvent(id="call_y", name="t",
                      arguments='{}', index=0),
        StreamDone(input_tokens=5, output_tokens=5),
    ]
    iter_two = [
        ContentDelta(delta="done"),
        StreamDone(input_tokens=2, output_tokens=2),
    ]
    emitted, emit_fn = _make_emit_capture()
    _, save_fn = _make_save_capture()

    await InferenceRunner().run(
        user_id="u", session_id="s", correlation_id="c",
        stream_fn=_make_stream_fn([iter_one, iter_two]),
        emit_fn=emit_fn, save_fn=save_fn,
        cancel_event=None, tool_executor_fn=_noop_executor,
    )

    deltas = [e for e in emitted if isinstance(e, ChatToolCallDeltaEvent)]
    starteds = [e for e in emitted if isinstance(e, ChatToolCallStartedEvent)]
    assert deltas == []
    assert len(starteds) == 1


@pytest.mark.asyncio
async def test_late_id_is_backfilled_into_earlier_deltas() -> None:
    """First delta carries id=None; later delta supplies the id. The loop
    should buffer the first delta and emit it with the late id, then emit
    the second delta normally."""
    iter_one = [
        ToolCallArgsDelta(index=0, id=None, name=None,
                          arguments_delta='{"q'),
        ToolCallArgsDelta(index=0, id="call_z", name="t",
                          arguments_delta='":"x"}'),
        ToolCallEvent(id="call_z", name="t",
                      arguments='{"q":"x"}', index=0),
        StreamDone(input_tokens=5, output_tokens=5),
    ]
    iter_two = [
        ContentDelta(delta="done"),
        StreamDone(input_tokens=2, output_tokens=2),
    ]
    emitted, emit_fn = _make_emit_capture()
    _, save_fn = _make_save_capture()

    await InferenceRunner().run(
        user_id="u", session_id="s", correlation_id="c",
        stream_fn=_make_stream_fn([iter_one, iter_two]),
        emit_fn=emit_fn, save_fn=save_fn,
        cancel_event=None, tool_executor_fn=_noop_executor,
    )

    deltas = [e for e in emitted if isinstance(e, ChatToolCallDeltaEvent)]
    assert len(deltas) == 2
    # Both — including the first, originally-id-less one — carry call_z.
    assert all(d.tool_call_id == "call_z" for d in deltas)


@pytest.mark.asyncio
async def test_finalisation_drain_backfills_synth_id() -> None:
    """Adapter never sends the id in any delta — the final ToolCallEvent
    supplies a synthesised id (the accumulator generated it locally). The
    finally-block drain hook backfills the pending delta with that id."""
    iter_one = [
        ToolCallArgsDelta(index=0, id=None, name="t",
                          arguments_delta='{"q":"x"}'),
        ToolCallEvent(id="synth_id", name="t",
                      arguments='{"q":"x"}', index=0),
        StreamDone(input_tokens=5, output_tokens=5),
    ]
    iter_two = [
        ContentDelta(delta="done"),
        StreamDone(input_tokens=2, output_tokens=2),
    ]
    emitted, emit_fn = _make_emit_capture()
    _, save_fn = _make_save_capture()

    await InferenceRunner().run(
        user_id="u", session_id="s", correlation_id="c",
        stream_fn=_make_stream_fn([iter_one, iter_two]),
        emit_fn=emit_fn, save_fn=save_fn,
        cancel_event=None, tool_executor_fn=_noop_executor,
    )

    deltas = [e for e in emitted if isinstance(e, ChatToolCallDeltaEvent)]
    assert len(deltas) == 1
    assert deltas[0].tool_call_id == "synth_id"
```

- [ ] **Step 2: Run the four new tests to verify they fail**

Run: `uv run pytest backend/tests/modules/chat/test_inference_tool_call_deltas.py -v`
Expected: all four fail. Most likely failure mode at this point: no `ChatToolCallDeltaEvent` ever emitted (Task 11 has wired the loop), so tests fail at the `len(deltas) == N` assertion. If Task 11 was implemented correctly before this task, the tests should now pass.

If Task 11 has NOT been done yet, return to Task 11 first.

- [ ] **Step 3: Verify all four tests pass after Task 11 is wired**

Run: `uv run pytest backend/tests/modules/chat/test_inference_tool_call_deltas.py -v`
Expected: all four tests pass.

- [ ] **Step 4: Run the full inference test suite to catch regressions**

Run: `uv run pytest backend/tests/modules/chat/ -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/modules/chat/test_inference_tool_call_deltas.py
git commit -m "Test tool-call delta routing in inference loop"
```

---

## Phase 4 — Frontend Store

### Task 13: Add `StreamingToolCall` type and `streamingToolCalls` slice

**Files:**
- Modify: `frontend/src/core/store/chatStore.ts`

- [ ] **Step 1: Add the `StreamingToolCall` interface**

Open `frontend/src/core/store/chatStore.ts`. Near the top, next to existing interface declarations (after `ActiveToolCall` or similar), add:

```typescript
export interface StreamingToolCall {
  toolCallId: string
  toolIndex: number
  toolName: string | null
  argsBuffer: string
  charCount: number
  phase: 'streaming' | 'executing'
  startedAt: number
  parsedArguments: Record<string, unknown> | null
}
```

- [ ] **Step 2: Add the slice to `SessionStreamingState`**

In the same file, locate the `SessionStreamingState` interface (around line 30–50). Add a new field:

```typescript
interface SessionStreamingState {
  // ... existing fields ...
  streamingToolCalls: Map<string /* tool_call_id */, StreamingToolCall>
}
```

- [ ] **Step 3: Add the slice to `EMPTY_STREAM`**

Right below the interface, locate `EMPTY_STREAM` (around line 53). Add:

```typescript
const EMPTY_STREAM: SessionStreamingState = {
  // ... existing fields ...
  streamingToolCalls: new Map(),
}
```

- [ ] **Step 4: Verify the type compiles**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: exit 0 (no callers yet, but the slice must compile cleanly).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/store/chatStore.ts
git commit -m "Add streamingToolCalls slice to chat store"
```

---

### Task 14: Add `appendToolCallDelta` reducer + test

**Files:**
- Modify: `frontend/src/core/store/chatStore.ts`
- Modify: `frontend/src/core/store/chatStore.test.ts`

- [ ] **Step 1: Write the failing test**

In `frontend/src/core/store/chatStore.test.ts`, append:

```typescript
describe('appendToolCallDelta', () => {
  it('creates a new streaming slot on first delta', () => {
    const store = useChatStore.getState()
    store.startStreaming('corr-1', { sessionId: 'sess-1' })
    store.appendToolCallDelta(
      'call_x', 0, 'search', '{"q', { sessionId: 'sess-1' },
    )
    const slot = store.getStreamFor('sess-1')!.streamingToolCalls.get('call_x')
    expect(slot).toBeDefined()
    expect(slot!.toolName).toBe('search')
    expect(slot!.argsBuffer).toBe('{"q')
    expect(slot!.charCount).toBe(3)
    expect(slot!.phase).toBe('streaming')
  })

  it('appends to existing slot and updates counters', () => {
    const store = useChatStore.getState()
    store.startStreaming('corr-2', { sessionId: 'sess-2' })
    store.appendToolCallDelta('call_y', 0, 'f', '{"a', { sessionId: 'sess-2' })
    store.appendToolCallDelta('call_y', 0, null, '":"b"}', { sessionId: 'sess-2' })
    const slot = store.getStreamFor('sess-2')!.streamingToolCalls.get('call_y')!
    expect(slot.argsBuffer).toBe('{"a":"b"}')
    expect(slot.charCount).toBe(9)
    expect(slot.toolName).toBe('f')
  })

  it('sets toolName when supplied in a later delta', () => {
    const store = useChatStore.getState()
    store.startStreaming('corr-3', { sessionId: 'sess-3' })
    store.appendToolCallDelta('call_z', 0, null, '', { sessionId: 'sess-3' })
    store.appendToolCallDelta('call_z', 0, 'lateName', 'x', { sessionId: 'sess-3' })
    const slot = store.getStreamFor('sess-3')!.streamingToolCalls.get('call_z')!
    expect(slot.toolName).toBe('lateName')
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && pnpm vitest run chatStore.test.ts -t appendToolCallDelta`
Expected: tests fail with `appendToolCallDelta is not a function`.

- [ ] **Step 3: Write the reducer**

In `frontend/src/core/store/chatStore.ts`, find the existing reducers area (around line 270). Add to the `ChatState` interface declaration (around line 127):

```typescript
appendToolCallDelta: (
  toolCallId: string,
  toolIndex: number,
  toolName: string | null,
  argsDelta: string,
  opts: { sessionId: string },
) => void
```

And add the implementation alongside the other reducer implementations:

```typescript
appendToolCallDelta: (toolCallId, toolIndex, toolName, argsDelta, { sessionId }) =>
  set((s) => {
    const prev = s.streamsBySession.get(sessionId) ?? EMPTY_STREAM
    const existing = prev.streamingToolCalls.get(toolCallId)
    const next: StreamingToolCall = existing
      ? {
          ...existing,
          toolName: existing.toolName ?? toolName,
          argsBuffer: existing.argsBuffer + argsDelta,
          charCount: existing.charCount + argsDelta.length,
        }
      : {
          toolCallId,
          toolIndex,
          toolName,
          argsBuffer: argsDelta,
          charCount: argsDelta.length,
          phase: 'streaming',
          startedAt: performance.now(),
          parsedArguments: null,
        }
    const nextMap = new Map(prev.streamingToolCalls)
    nextMap.set(toolCallId, next)
    return {
      streamsBySession: withStream(s.streamsBySession, sessionId, {
        streamingToolCalls: nextMap,
      }),
    }
  }),
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && pnpm vitest run chatStore.test.ts -t appendToolCallDelta`
Expected: all three tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/store/chatStore.ts frontend/src/core/store/chatStore.test.ts
git commit -m "Add appendToolCallDelta reducer"
```

---

### Task 15: Add `promoteToolCallToExecuting` reducer + test

**Files:**
- Modify: `frontend/src/core/store/chatStore.ts`
- Modify: `frontend/src/core/store/chatStore.test.ts`

- [ ] **Step 1: Write the failing test**

Append to `chatStore.test.ts`:

```typescript
describe('promoteToolCallToExecuting', () => {
  it('promotes an existing streaming slot to executing', () => {
    const store = useChatStore.getState()
    store.startStreaming('c1', { sessionId: 's1' })
    store.appendToolCallDelta('call_x', 0, 'search', '{}', { sessionId: 's1' })
    store.promoteToolCallToExecuting(
      'call_x', 'search', { q: 'hi' }, { sessionId: 's1' },
    )
    const slot = store.getStreamFor('s1')!.streamingToolCalls.get('call_x')!
    expect(slot.phase).toBe('executing')
    expect(slot.parsedArguments).toEqual({ q: 'hi' })
  })

  it('creates a new executing slot when streaming slot is absent (Ollama path)', () => {
    const store = useChatStore.getState()
    store.startStreaming('c2', { sessionId: 's2' })
    store.promoteToolCallToExecuting(
      'call_y', 'lookup', { id: 42 }, { sessionId: 's2' },
    )
    const slot = store.getStreamFor('s2')!.streamingToolCalls.get('call_y')!
    expect(slot.phase).toBe('executing')
    expect(slot.toolName).toBe('lookup')
    expect(slot.argsBuffer).toBe('')
    expect(slot.parsedArguments).toEqual({ id: 42 })
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && pnpm vitest run chatStore.test.ts -t promoteToolCallToExecuting`
Expected: tests fail (reducer not defined).

- [ ] **Step 3: Write the reducer**

Add to the `ChatState` interface in `chatStore.ts`:

```typescript
promoteToolCallToExecuting: (
  toolCallId: string,
  toolName: string,
  parsedArguments: Record<string, unknown>,
  opts: { sessionId: string },
) => void
```

Add the implementation:

```typescript
promoteToolCallToExecuting: (toolCallId, toolName, parsedArguments, { sessionId }) =>
  set((s) => {
    const prev = s.streamsBySession.get(sessionId) ?? EMPTY_STREAM
    const existing = prev.streamingToolCalls.get(toolCallId)
    const next: StreamingToolCall = existing
      ? { ...existing, phase: 'executing', toolName, parsedArguments }
      : {
          toolCallId,
          toolIndex: 0,
          toolName,
          argsBuffer: '',
          charCount: 0,
          phase: 'executing',
          startedAt: performance.now(),
          parsedArguments,
        }
    const nextMap = new Map(prev.streamingToolCalls)
    nextMap.set(toolCallId, next)
    return {
      streamsBySession: withStream(s.streamsBySession, sessionId, {
        streamingToolCalls: nextMap,
      }),
    }
  }),
```

- [ ] **Step 4: Run the test**

Run: `cd frontend && pnpm vitest run chatStore.test.ts -t promoteToolCallToExecuting`
Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/store/chatStore.ts frontend/src/core/store/chatStore.test.ts
git commit -m "Add promoteToolCallToExecuting reducer"
```

---

### Task 16: Add `removeStreamingToolCall` reducer + test

**Files:**
- Modify: `frontend/src/core/store/chatStore.ts`
- Modify: `frontend/src/core/store/chatStore.test.ts`

- [ ] **Step 1: Write the failing test**

Append to `chatStore.test.ts`:

```typescript
describe('removeStreamingToolCall', () => {
  it('removes the slot for the given tool_call_id', () => {
    const store = useChatStore.getState()
    store.startStreaming('c1', { sessionId: 's1' })
    store.appendToolCallDelta('call_x', 0, 'search', '{}', { sessionId: 's1' })
    expect(store.getStreamFor('s1')!.streamingToolCalls.has('call_x')).toBe(true)
    store.removeStreamingToolCall('call_x', { sessionId: 's1' })
    expect(store.getStreamFor('s1')!.streamingToolCalls.has('call_x')).toBe(false)
  })

  it('is a no-op when the id does not exist', () => {
    const store = useChatStore.getState()
    store.startStreaming('c2', { sessionId: 's2' })
    expect(() => store.removeStreamingToolCall('nope', { sessionId: 's2' }))
      .not.toThrow()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && pnpm vitest run chatStore.test.ts -t removeStreamingToolCall`
Expected: tests fail.

- [ ] **Step 3: Write the reducer**

Add to the `ChatState` interface:

```typescript
removeStreamingToolCall: (toolCallId: string, opts: { sessionId: string }) => void
```

Add the implementation:

```typescript
removeStreamingToolCall: (toolCallId, { sessionId }) =>
  set((s) => {
    const prev = s.streamsBySession.get(sessionId) ?? EMPTY_STREAM
    if (!prev.streamingToolCalls.has(toolCallId)) return s
    const nextMap = new Map(prev.streamingToolCalls)
    nextMap.delete(toolCallId)
    return {
      streamsBySession: withStream(s.streamsBySession, sessionId, {
        streamingToolCalls: nextMap,
      }),
    }
  }),
```

- [ ] **Step 4: Run the test**

Run: `cd frontend && pnpm vitest run chatStore.test.ts -t removeStreamingToolCall`
Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/store/chatStore.ts frontend/src/core/store/chatStore.test.ts
git commit -m "Add removeStreamingToolCall reducer"
```

---

### Task 17: Wire `streamingToolCalls` into `cancelStreaming` and `CHAT_STREAM_ERROR` cleanup

**Files:**
- Modify: `frontend/src/core/store/chatStore.ts`
- Modify: `frontend/src/core/store/chatStore.test.ts`

- [ ] **Step 1: Write the failing test**

Append to `chatStore.test.ts`:

```typescript
describe('streamingToolCalls cleanup on cancel', () => {
  it('cancelStreaming clears streamingToolCalls', () => {
    const store = useChatStore.getState()
    store.startStreaming('c1', { sessionId: 's1' })
    store.appendToolCallDelta('call_x', 0, 'f', '{}', { sessionId: 's1' })
    store.cancelStreaming({ sessionId: 's1' })
    expect(store.getStreamFor('s1')!.streamingToolCalls.size).toBe(0)
  })
})
```

- [ ] **Step 2: Run the test**

Run: `cd frontend && pnpm vitest run chatStore.test.ts -t 'cleanup on cancel'`
Expected: fails — `cancelStreaming` does not yet clear the slice.

- [ ] **Step 3: Update `cancelStreaming` in `chatStore.ts`**

Find the `cancelStreaming` reducer (search for `cancelStreaming:`). It currently resets the slot to `EMPTY_STREAM` or similar. Confirm the implementation merges with an explicit reset of `streamingToolCalls` to a fresh `Map`:

```typescript
cancelStreaming: ({ sessionId }) =>
  set((s) => ({
    streamsBySession: withStream(s.streamsBySession, sessionId, {
      ...EMPTY_STREAM,
      // (if the existing implementation only resets specific fields, add:)
      streamingToolCalls: new Map(),
    }),
  })),
```

If `cancelStreaming` already does a full slot reset to `EMPTY_STREAM`, this is automatic — the test will pass without code changes. In that case, the test is still valuable as a regression check.

- [ ] **Step 4: Run the test**

Run: `cd frontend && pnpm vitest run chatStore.test.ts -t 'cleanup on cancel'`
Expected: passes.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/store/chatStore.ts frontend/src/core/store/chatStore.test.ts
git commit -m "Clear streamingToolCalls on stream cancel"
```

---

### Task 18: Remove `activeToolCalls`, `addToolCall`, `completeToolCall`

**Files:**
- Modify: `frontend/src/core/store/chatStore.ts`
- Modify: `frontend/src/core/store/chatStore.test.ts`

> **Note:** This task removes the legacy slice. Tasks 19–21 (which adapt
> `useChatStream` and `MessageList`) must be done before this task in
> chronological order — otherwise the live build breaks between commits.
> If executing strictly task-by-task, defer this task until after Task 21.
> The task itself is listed here in the store section to keep store
> changes grouped; subagent orchestration should sequence accordingly.

- [ ] **Step 1: Remove `addToolCall` and `completeToolCall` from interface and implementation**

In `chatStore.ts`:

- Delete the two lines from the `ChatState` interface (`addToolCall: …`, `completeToolCall: …`).
- Delete the two reducer implementations (lines around 277–306 in the current file).

- [ ] **Step 2: Remove `activeToolCalls` from `SessionStreamingState` and `EMPTY_STREAM`**

In the same file:

- Delete the `activeToolCalls: ActiveToolCall[]` field from `SessionStreamingState`.
- Delete the `activeToolCalls: []` entry from `EMPTY_STREAM`.
- Delete the `ActiveToolCall` interface (search for `interface ActiveToolCall` or `type ActiveToolCall`); if it is exported, also remove the export.

- [ ] **Step 3: Update tests that reference `activeToolCalls` / `addToolCall` / `completeToolCall`**

Search and remove obsolete tests:

```bash
grep -rn "addToolCall\|completeToolCall\|activeToolCalls" frontend/src/
```

Migrate any test that exercised `addToolCall`/`completeToolCall` semantics to use the new `promoteToolCallToExecuting` / `removeStreamingToolCall` reducers, or delete it if covered by the new tests from Tasks 14–17.

- [ ] **Step 4: Verify build**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: exit 0.

Run: `cd frontend && pnpm vitest run`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/store/chatStore.ts frontend/src/core/store/chatStore.test.ts
git commit -m "Remove activeToolCalls slice and its reducers"
```

---

## Phase 5 — Frontend Pill Component

### Task 19: Extract `friendlyLabel` + `TOOL_LABELS` into shared module

**Files:**
- Create: `frontend/src/features/chat/toolLabels.ts`
- Modify: `frontend/src/features/chat/ToolCallActivity.tsx` (read-only at this point — we'll import from the new module)

- [ ] **Step 1: Create the shared module**

Create `frontend/src/features/chat/toolLabels.ts`:

```typescript
export const TOOL_LABELS: Record<string, (args: Record<string, unknown>) => string> = {
  web_search: (args) => `Searching the web for "${args.query ?? '...'}"`,
  web_fetch: (args) => {
    const url = String(args.url ?? '')
    const display = url.length > 40 ? url.slice(0, 40) + '...' : url
    return `Fetching ${display}`
  },
  knowledge_search: (args) => `Searching knowledge for "${args.query ?? '...'}"`,
  create_artefact: (args) => `Creating artefact "${args.title ?? args.handle ?? '...'}"`,
  update_artefact: (args) => `Updating artefact "${args.handle ?? '...'}"`,
  read_artefact: (args) => `Reading artefact "${args.handle ?? '...'}"`,
  list_artefacts: () => 'Listing artefacts',
}

export function friendlyLabel(
  toolName: string,
  args: Record<string, unknown>,
): string {
  const fn = TOOL_LABELS[toolName]
  return fn ? fn(args) : `Running ${toolName}...`
}

export function displayName(toolName: string): string {
  // Strip namespace prefix if present (e.g. "global__quotes_about" -> "quotes_about").
  const parts = toolName.split('__')
  return parts.length > 1 ? parts.slice(1).join('__') : toolName
}
```

`displayName` is lifted from the existing `ToolCallPills.tsx` (line 29–33) so the new pill component can use it.

- [ ] **Step 2: Verify**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/toolLabels.ts
git commit -m "Extract tool-label helpers into shared module"
```

---

### Task 20: Build `ToolCallPill.tsx` with tests

**Files:**
- Create: `frontend/src/features/chat/ToolCallPill.tsx`
- Create: `frontend/src/features/chat/__tests__/ToolCallPill.test.tsx`

- [ ] **Step 1: Write the failing test file**

Create `frontend/src/features/chat/__tests__/ToolCallPill.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ToolCallPill } from '../ToolCallPill'

describe('ToolCallPill — streaming phase', () => {
  it('renders tool name and char count when known', () => {
    render(
      <ToolCallPill
        phase={{
          kind: 'streaming',
          toolName: 'search',
          charCount: 12,
          argsBuffer: '{"q":"hi"}',
          toolCallId: 'call_x',
        }}
      />,
    )
    expect(screen.getByText('search')).toBeInTheDocument()
    expect(screen.getByText(/12 chars/)).toBeInTheDocument()
  })

  it('renders placeholder name before tool name is known', () => {
    render(
      <ToolCallPill
        phase={{
          kind: 'streaming',
          toolName: null,
          charCount: 0,
          argsBuffer: '',
          toolCallId: 'call_x',
        }}
      />,
    )
    expect(screen.getByText('Tool')).toBeInTheDocument()
  })

  it('shows raw argsBuffer when expanded', () => {
    render(
      <ToolCallPill
        phase={{
          kind: 'streaming',
          toolName: 'f',
          charCount: 3,
          argsBuffer: '{"x',
          toolCallId: 'call_x',
        }}
      />,
    )
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByText('{"x')).toBeInTheDocument()
  })
})

describe('ToolCallPill — executing phase', () => {
  it('renders friendly label for known tools', () => {
    render(
      <ToolCallPill
        phase={{
          kind: 'executing',
          toolName: 'web_search',
          arguments: { query: 'pizza' },
          toolCallId: 'call_x',
        }}
      />,
    )
    expect(screen.getByText(/Searching the web for "pizza"/)).toBeInTheDocument()
  })

  it('renders generic label for unknown tools', () => {
    render(
      <ToolCallPill
        phase={{
          kind: 'executing',
          toolName: 'unknown_thing',
          arguments: {},
          toolCallId: 'call_x',
        }}
      />,
    )
    expect(screen.getByText(/Running unknown_thing/)).toBeInTheDocument()
  })
})

describe('ToolCallPill — completed phase', () => {
  it('renders the display name and toggles Request/Response sections', () => {
    render(
      <ToolCallPill
        phase={{
          kind: 'completed',
          ref: {
            tool_call_id: 'call_x',
            tool_name: 'search',
            arguments: { query: 'pizza' },
            success: true,
            moderated_count: 0,
            result_content: '{"hits":3}',
          },
        }}
      />,
    )
    expect(screen.getByText('search')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByText('Request')).toBeInTheDocument()
    expect(screen.getByText('Response')).toBeInTheDocument()
    expect(screen.getByText(/query: pizza/)).toBeInTheDocument()
    expect(screen.getByText('{"hits":3}')).toBeInTheDocument()
  })

  it('omits Response section when result_content is empty', () => {
    render(
      <ToolCallPill
        phase={{
          kind: 'completed',
          ref: {
            tool_call_id: 'call_x',
            tool_name: 'f',
            arguments: {},
            success: true,
            moderated_count: 0,
            result_content: null,
          },
        }}
      />,
    )
    fireEvent.click(screen.getByRole('button'))
    expect(screen.queryByText('Response')).toBeNull()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && pnpm vitest run ToolCallPill.test.tsx`
Expected: fails — `ToolCallPill` not found.

- [ ] **Step 3: Implement `ToolCallPill.tsx`**

Create `frontend/src/features/chat/ToolCallPill.tsx`:

```tsx
import { useState } from 'react'
import type { ToolCallRef } from '../../core/api/chat'
import { friendlyLabel, displayName } from './toolLabels'

export type ToolCallPillPhase =
  | {
      kind: 'streaming'
      toolName: string | null
      charCount: number
      argsBuffer: string
      toolCallId: string
    }
  | {
      kind: 'executing'
      toolName: string
      arguments: Record<string, unknown>
      toolCallId: string
    }
  | { kind: 'completed'; ref: ToolCallRef }

interface ToolCallPillProps {
  phase: ToolCallPillPhase
}

function ToolIcon() {
  return (
    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
    </svg>
  )
}

function SpinnerIcon() {
  return (
    <svg className="animate-spin" width="12" height="12" viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M12 2a10 10 0 0 1 10 10" />
    </svg>
  )
}

function formatArgs(args: Record<string, unknown>): string {
  const entries = Object.entries(args)
  if (entries.length === 0) return '(no arguments)'
  return entries
    .map(([k, v]) => {
      const val = typeof v === 'string' ? v : JSON.stringify(v)
      const display = val.length > 60 ? val.slice(0, 60) + '...' : val
      return `${k}: ${display}`
    })
    .join('\n')
}

function colourFor(phase: ToolCallPillPhase): string {
  if (phase.kind === 'completed') {
    return phase.ref.success ? '245,194,131' : '243,139,168'
  }
  if (phase.kind === 'executing') {
    if (phase.toolName === 'knowledge_search') return '140,118,215'
    if (phase.toolName.includes('artefact')) return '201,169,110'
    return '137,180,250'
  }
  return '137,180,250'  // streaming
}

export function ToolCallPill({ phase }: ToolCallPillProps) {
  const [isExpanded, setIsExpanded] = useState(false)
  const colour = colourFor(phase)

  const labelNode = (() => {
    if (phase.kind === 'streaming') {
      return (
        <>
          <ToolIcon />
          <span>{phase.toolName ?? 'Tool'}</span>
          <span className="ml-1 opacity-70">{phase.charCount} chars</span>
        </>
      )
    }
    if (phase.kind === 'executing') {
      return (
        <>
          <SpinnerIcon />
          <span>{friendlyLabel(phase.toolName, phase.arguments)}</span>
        </>
      )
    }
    return (
      <>
        <ToolIcon />
        <span>{displayName(phase.ref.tool_name)}</span>
      </>
    )
  })()

  const expandedNode = (() => {
    if (phase.kind === 'streaming') {
      return (
        <>
          <div className="mb-1 text-[10px] font-medium"
            style={{ color: `rgba(${colour},0.9)` }}>
            Streaming arguments…
          </div>
          <pre className="whitespace-pre-wrap text-[11px] leading-relaxed text-white/50"
            style={{ fontFamily: "'Courier New', monospace" }}>
            {phase.argsBuffer || '(empty)'}
          </pre>
        </>
      )
    }
    if (phase.kind === 'executing') {
      return (
        <>
          <div className="mb-1 text-[10px] font-medium"
            style={{ color: `rgba(${colour},0.9)` }}>
            Request
          </div>
          <pre className="whitespace-pre-wrap text-[11px] leading-relaxed text-white/50"
            style={{ fontFamily: "'Courier New', monospace" }}>
            {formatArgs(phase.arguments)}
          </pre>
        </>
      )
    }
    const ref = phase.ref
    const hasResult = ref.result_content != null && ref.result_content !== ''
    return (
      <>
        <div className="mb-1.5 text-[10px] font-medium"
          style={{ color: `rgba(${colour},0.9)` }}>
          {ref.tool_name}
        </div>
        <div className="mb-1 text-[10px] font-medium"
          style={{ color: `rgba(${colour},0.9)` }}>
          Request
        </div>
        <pre className="whitespace-pre-wrap text-[11px] leading-relaxed text-white/50"
          style={{ fontFamily: "'Courier New', monospace" }}>
          {formatArgs(ref.arguments)}
        </pre>
        {hasResult && (
          <>
            <div className="mt-2 mb-1 text-[10px] font-medium"
              style={{ color: `rgba(${colour},0.9)` }}>
              Response
            </div>
            <pre className="whitespace-pre-wrap text-[11px] leading-relaxed text-white/50"
              style={{ fontFamily: "'Courier New', monospace" }}>
              {ref.result_content}
            </pre>
          </>
        )}
      </>
    )
  })()

  return (
    <div className="relative mb-2">
      <button
        type="button"
        onClick={() => setIsExpanded((x) => !x)}
        className="flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] transition-opacity hover:opacity-90"
        style={{
          background: `rgba(${colour},0.12)`,
          border: `1px solid rgba(${colour},0.25)`,
          color: `rgba(${colour},0.9)`,
          fontFamily: "'Courier New', monospace",
        }}
      >
        {labelNode}
      </button>
      {isExpanded && (
        <div
          className="absolute left-0 top-full z-20 mt-1 min-w-[280px] max-w-[400px] rounded-lg p-3"
          style={{
            background: 'rgba(20, 18, 28, 0.98)',
            border: `1px solid rgba(${colour},0.25)`,
            boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
            maxHeight: 320,
            overflowY: 'auto',
          }}
        >
          {expandedNode}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run the test**

Run: `cd frontend && pnpm vitest run ToolCallPill.test.tsx`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/chat/ToolCallPill.tsx \
        frontend/src/features/chat/__tests__/ToolCallPill.test.tsx
git commit -m "Add ToolCallPill component with streaming/executing/completed phases"
```

---

## Phase 6 — Frontend Integration

### Task 21: Update `useChatStream.ts` event handlers

**Files:**
- Modify: `frontend/src/features/chat/useChatStream.ts`

- [ ] **Step 1: Add `CHAT_TOOL_CALL_DELTA` case to the event switch**

In `useChatStream.ts`, locate the existing `case Topics.CHAT_TOOL_CALL_STARTED:` block (around line 133). Add directly above it:

```typescript
case Topics.CHAT_TOOL_CALL_DELTA: {
  const slot = getStore().getStreamFor(sessionId)
  if (event.correlation_id !== slot?.correlationId) return
  getStore().appendToolCallDelta(
    p.tool_call_id as string,
    p.tool_index as number,
    (p.tool_name as string | null) ?? null,
    p.args_delta as string,
    writeOpts,
  )
  break
}
```

- [ ] **Step 2: Replace `addToolCall` call in the `CHAT_TOOL_CALL_STARTED` handler**

In the same file, locate the existing `CHAT_TOOL_CALL_STARTED` case (around line 133–143). Replace the body:

```typescript
// Before
case Topics.CHAT_TOOL_CALL_STARTED: {
  const slot = getStore().getStreamFor(sessionId)
  if (event.correlation_id !== slot?.correlationId) return
  getStore().addToolCall({
    id: p.tool_call_id as string,
    toolName: p.tool_name as string,
    arguments: p.arguments as Record<string, unknown>,
    status: 'running',
  }, writeOpts)
  break
}

// After
case Topics.CHAT_TOOL_CALL_STARTED: {
  const slot = getStore().getStreamFor(sessionId)
  if (event.correlation_id !== slot?.correlationId) return
  getStore().promoteToolCallToExecuting(
    p.tool_call_id as string,
    p.tool_name as string,
    p.arguments as Record<string, unknown>,
    writeOpts,
  )
  break
}
```

- [ ] **Step 3: Replace `completeToolCall` call in the `CHAT_TOOL_CALL_COMPLETED` handler**

Find the line `getStore().completeToolCall(p.tool_call_id as string, writeOpts)` (around line 147). Replace with:

```typescript
// IMPORTANT: remove only AFTER the timeline entry has been appended.
// React batches both updates into the same render, so no empty frame
// appears at the pill's position.
// The actual timeline-entry append happens further down in the same
// case block, so the remove call goes at the very END of that block.
```

Locate the END of the `CHAT_TOOL_CALL_COMPLETED` case (after all `getStore().appendStreamingEvent(...)` calls — around line 219). Add right before the `break`:

```typescript
getStore().removeStreamingToolCall(p.tool_call_id as string, writeOpts)
break
```

And delete the original `getStore().completeToolCall(...)` line near the top of the case.

- [ ] **Step 4: Drop client-side `generate_image` tool_call entry**

Inside the `CHAT_TOOL_CALL_COMPLETED` case, locate the `else if (toolName === 'generate_image')` branch (around line 181). The backend will now persist a `tool_call` entry for `generate_image` (Task 23). The frontend's live-rendering path no longer needs to skip it — but the existing branch only appends an `image` entry and does NOT add a `tool_call` entry, so this code can stay as-is for live rendering. The backend-persisted `tool_call` entry surfaces on the next session load via the timeline entries replayed at message commit.

For live streaming, the new `streamingToolCalls` slice already holds the pill from Phase 2; it morphs to the completed display by being removed from the live slice while the `tool_call` and `image` entries arrive in `streamingEvents`.

To make this work, the live branch must ALSO append a `tool_call` entry for generate_image. Update the existing block:

```typescript
} else if (toolName === 'generate_image') {
  const refs: ImageRefDto[] = Array.isArray(imageRefsRaw) ? (imageRefsRaw as ImageRefDto[]) : []
  // Match backend persistence (Task 23): tool_call entry + image entry,
  // so the live render matches what reload will show.
  const toolCallEntry: TimelineEntry = {
    kind: 'tool_call',
    seq: 0,
    tool_call_id: toolCallId,
    tool_name: toolName,
    arguments: args,
    success,
    moderated_count: moderatedCount,
    result_content: resultContent,
  }
  getStore().appendStreamingEvent(toolCallEntry, writeOpts)
  if (refs.length > 0 || moderatedCount > 0) {
    const entry: TimelineEntry = {
      kind: 'image',
      seq: 0,
      refs,
      moderated_count: moderatedCount,
    }
    getStore().appendStreamingEvent(entry, writeOpts)
  }
}
```

- [ ] **Step 5: Verify the build**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: exit 0.

- [ ] **Step 6: Run existing useChatStream tests**

Run: `cd frontend && pnpm vitest run useChatStream.test.ts`
Expected: tests pass. If `addToolCall`/`completeToolCall`-style tests break, update them to use the new reducer names (the test file's setup likely mocks the store reducers).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/chat/useChatStream.ts
git commit -m "Wire useChatStream to streamingToolCalls slice"
```

---

### Task 22: Update `MessageList.tsx` to render `ToolCallPill`

**Files:**
- Modify: `frontend/src/features/chat/MessageList.tsx`

- [ ] **Step 1: Update the `renderTimelineEntry` `tool_call` case**

In `MessageList.tsx`, locate the `case 'tool_call':` branch (around line 120). Replace with:

```typescript
case 'tool_call': {
  const ref: ToolCallRef = {
    tool_call_id: entry.tool_call_id,
    tool_name: entry.tool_name,
    arguments: entry.arguments,
    success: entry.success,
    moderated_count: entry.moderated_count,
    result_content: entry.result_content ?? null,
  }
  return <ToolCallPill key={k} phase={{ kind: 'completed', ref }} />
}
```

- [ ] **Step 2: Update the import**

At the top of `MessageList.tsx`, find:

```typescript
import { ToolCallPills } from './ToolCallPills'
import { ToolCallActivity } from './ToolCallActivity'
```

Replace with:

```typescript
import { ToolCallPill } from './ToolCallPill'
```

- [ ] **Step 3: Replace the live `activeToolCalls` block with the new `streamingToolCalls` map**

Find the section in the `isStreaming` branch (around line 356):

```tsx
{activeToolCalls.filter((tc) => tc.status === 'running').map((tc) => (
  <ToolCallActivity key={tc.id} toolName={tc.toolName} arguments={tc.arguments} />
))}
```

Replace with:

```tsx
{Array.from(streamingToolCalls.values()).map((tc) => (
  <ToolCallPill
    key={tc.toolCallId}
    phase={
      tc.phase === 'streaming'
        ? {
            kind: 'streaming',
            toolName: tc.toolName,
            charCount: tc.charCount,
            argsBuffer: tc.argsBuffer,
            toolCallId: tc.toolCallId,
          }
        : {
            kind: 'executing',
            toolName: tc.toolName ?? 'tool',
            arguments: tc.parsedArguments ?? {},
            toolCallId: tc.toolCallId,
          }
    }
  />
))}
```

- [ ] **Step 4: Update the `MessageList` props**

Find the `MessageListProps` interface or destructured-args type at the component definition. Replace the `activeToolCalls` prop with `streamingToolCalls`:

```typescript
streamingToolCalls: Map<string, StreamingToolCall>
```

Import `StreamingToolCall` from `chatStore.ts`.

- [ ] **Step 5: Update the call site (`ChatView.tsx`)**

Run: `grep -rn "activeToolCalls" frontend/src/features/chat/`

Open every match (likely `ChatView.tsx`). For each, change the prop passed to `MessageList` from `activeToolCalls={...}` to `streamingToolCalls={...}` and update the source — read it from the current session's slot:

```typescript
streamingToolCalls={streamSlot.streamingToolCalls}
```

(Exact accessor depends on how `ChatView` extracts the streaming state — match the existing pattern.)

- [ ] **Step 6: Verify the build**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: exit 0.

Run: `cd frontend && pnpm vitest run MessageList.test`
Expected: tests pass. Update test fixtures if they construct `activeToolCalls` — replace with a `Map` of `StreamingToolCall`.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/chat/MessageList.tsx \
        frontend/src/features/chat/ChatView.tsx \
        frontend/src/features/chat/__tests__/MessageList.test.tsx
git commit -m "Render ToolCallPill in MessageList live and timeline paths"
```

---

### Task 23: Delete obsolete components

**Files:**
- Delete: `frontend/src/features/chat/ToolCallActivity.tsx`
- Delete: `frontend/src/features/chat/ToolCallPills.tsx`
- Delete: `frontend/src/features/chat/__tests__/ToolCallPills.test.tsx`

- [ ] **Step 1: Confirm no remaining imports**

Run: `grep -rn "ToolCallActivity\|ToolCallPills" frontend/src/`
Expected: no matches (other than the files we're about to delete).

If matches exist outside the deletion targets, fix those callers first.

- [ ] **Step 2: Delete the files**

```bash
rm frontend/src/features/chat/ToolCallActivity.tsx
rm frontend/src/features/chat/ToolCallPills.tsx
rm frontend/src/features/chat/__tests__/ToolCallPills.test.tsx
```

- [ ] **Step 3: Verify the build**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: exit 0.

Run: `cd frontend && pnpm vitest run`
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add -A frontend/src/features/chat/
git commit -m "Remove ToolCallActivity and ToolCallPills (replaced by ToolCallPill)"
```

---

## Phase 7 — generate_image Persistence

### Task 24: Persist `tool_call` timeline entry for `generate_image` in the backend

**Files:**
- Modify: `backend/modules/chat/_inference.py`

- [ ] **Step 1: Locate the generate_image entry-building block**

Open `backend/modules/chat/_inference.py`. Find the block that builds timeline entries for the persisted message (search for `image_refs_for_entry` or `kind="image"`).

This is the post-tool-execution code that walks `iter_tool_calls`, executes them, and appends timeline entries (around line 590–710).

- [ ] **Step 2: Add `tool_call` entry alongside `image` entry**

Read `backend/modules/chat/_inference.py` and locate the per-tool-call block where `make_timeline_entry(...)` is invoked after a tool execution (search for `make_timeline_entry(`). This is the post-execution loop body that appends entries onto the persisted timeline.

The helper `make_timeline_entry` returns ONE entry — for `generate_image` with `success=True`, that one entry is a `TimelineEntryImage` (and no separate `TimelineEntryToolCall`). To satisfy the spec ("pill remains visible alongside the image block"), the caller must additionally produce a `TimelineEntryToolCall` for `generate_image` and prepend it before the image entry.

Update the caller site to:

```python
entry = make_timeline_entry(
    seq=next_seq(),
    tool_name=tc.name,
    tool_call_id=tc.id,
    arguments=arguments,
    success=tool_success,
    moderated_count=moderated_count,
    knowledge_results=knowledge_results_for_entry,
    web_items=web_items_for_entry,
    artefact_ref=ref_for_event,
    image_refs=image_refs_for_entry,
    result_content=result_str,
)

# generate_image is the only tool that produces a non-tool_call typed
# entry AND requires a separate tool_call entry for the pill. Prepend
# a TimelineEntryToolCall so the pill renders above the image block.
# Failure path is already covered: make_timeline_entry collapses any
# failed call to TimelineEntryToolCall regardless of tool name.
if tc.name == "generate_image" and tool_success:
    timeline_entries.append(TimelineEntryToolCall(
        seq=next_seq(),
        tool_call_id=tc.id,
        tool_name=tc.name,
        arguments=arguments,
        success=True,
        moderated_count=moderated_count,
        result_content=result_str,
    ))
timeline_entries.append(entry)
```

The exact variable names (`timeline_entries`, `next_seq`, `image_refs_for_entry`, `knowledge_results_for_entry`, `web_items_for_entry`) need to match the actual function — read the file first to identify each name. Also import `TimelineEntryToolCall` at the top of `_inference.py` if it isn't already imported.

- [ ] **Step 3: Verify the file imports cleanly**

Run: `uv run python -m py_compile backend/modules/chat/_inference.py`
Expected: no output (success).

- [ ] **Step 4: Add an inference-loop test for generate_image persistence**

Append to `backend/tests/modules/chat/test_inference_tool_call_deltas.py` (the file created in Task 12):

```python
@pytest.mark.asyncio
async def test_generate_image_persists_tool_call_and_image_entries() -> None:
    """generate_image with success=True should persist BOTH a tool_call
    entry (for the pill) AND an image entry (for InlineImageBlock), in
    that order."""
    from shared.dtos.chat import TimelineEntryImage, TimelineEntryToolCall

    iter_one = [
        ToolCallEvent(id="call_g", name="generate_image",
                      arguments='{"prompt":"a cat"}', index=0),
        StreamDone(input_tokens=5, output_tokens=10),
    ]
    iter_two = [
        ContentDelta(delta="done"),
        StreamDone(input_tokens=2, output_tokens=2),
    ]
    emitted, emit_fn = _make_emit_capture()
    saved, save_fn = _make_save_capture()

    async def image_executor(user_id, tool_name, args_json, *, tool_call_id):
        # Mimic the structured output of the real generate_image executor.
        # The exact shape depends on _inference.py's image_refs extraction
        # logic — check the relevant block (search for image_refs_for_entry).
        # Falling back to a simple ok response keeps the test focused on
        # the timeline-entry structure rather than image transformation.
        return '{"ok": true, "image_ids": []}'

    await InferenceRunner().run(
        user_id="u", session_id="s", correlation_id="c",
        stream_fn=_make_stream_fn([iter_one, iter_two]),
        emit_fn=emit_fn, save_fn=save_fn,
        cancel_event=None, tool_executor_fn=image_executor,
    )

    timeline = saved["events"] or []
    types = [type(e).__name__ for e in timeline]
    # tool_call entry exists and comes before the image entry.
    assert "TimelineEntryToolCall" in types
    assert "TimelineEntryImage" in types
    tool_call_idx = types.index("TimelineEntryToolCall")
    image_idx = types.index("TimelineEntryImage")
    assert tool_call_idx < image_idx
    # The tool_call entry is the generate_image one (not a failed one).
    tc_entry = timeline[tool_call_idx]
    assert isinstance(tc_entry, TimelineEntryToolCall)
    assert tc_entry.tool_name == "generate_image"
    assert tc_entry.success is True
```

If the image-tool integration in `_inference.py` requires a more elaborate executor stub (e.g. real `ImageRefDto` parsing), inspect the existing `image_refs_for_entry` extraction code in `_inference.py` and produce a payload that satisfies it. The test's assertion is on the timeline structure, not the image content.

- [ ] **Step 5: Run the new test**

Run: `uv run pytest backend/tests/modules/chat/test_inference_tool_call_deltas.py::test_generate_image_persists_tool_call_and_image_entries -v`
Expected: passes.

- [ ] **Step 6: Run the full inference suite**

Run: `uv run pytest backend/tests/modules/chat/ -v`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/chat/_inference.py \
        backend/tests/modules/chat/test_inference_tool_call_deltas.py
git commit -m "Persist tool_call entry alongside image for generate_image"
```

---

## Phase 8 — End-to-end Verification & Squash

### Task 25: Run full backend test suite

- [ ] **Step 1: Run backend tests**

Run: `uv run pytest backend/ -v`
Expected: all tests pass. Investigate any failure — most likely an adapter test that still uses equality-style assertions; fix in place.

- [ ] **Step 2: Verify backend Python compiles**

Run: `uv run python -m py_compile $(find backend -name '*.py')`
Expected: no output.

---

### Task 26: Run full frontend test suite and build

- [ ] **Step 1: Run frontend tests**

Run: `cd frontend && pnpm vitest run`
Expected: all tests pass.

- [ ] **Step 2: Verify frontend build**

Run: `cd frontend && pnpm tsc --noEmit && pnpm run build`
Expected: build succeeds without errors.

---

### Task 27: Manual smoke test via dev server

> **For manual verification before merging.** Backend tests confirm event
> shape; frontend tests confirm component logic. This step confirms the UX
> the user actually sees.

- [ ] **Step 1: Start the dev environment**

Run the project's dev startup (consult `README.md` — typically a `docker compose up -d` plus `cd frontend && pnpm dev` plus `uv run uvicorn backend.main:app`).

- [ ] **Step 2: Trigger a tool call**

In the running app, send a chat message that prompts a tool call — e.g. with `web_search` enabled, ask: "What's the weather in Berlin right now?"

- [ ] **Step 3: Verify three phases**

Watch the assistant area:

1. A pill appears with `web_search` and `N chars` while the model is still streaming arguments. Click to expand — raw JSON visible.
2. Counter is replaced by a spinner; label becomes `Searching the web for "..."`. Click to expand — pretty-printed Request.
3. Pill is replaced by the `WebSearchPills` (URL cards) when results arrive.

- [ ] **Step 4: Trigger `generate_image`**

Send a prompt like "Generate an image of a cat in space".

Verify:
1. Pill appears in streaming phase (counter only — generate_image's args are usually short, so this phase may flash by).
2. Pill morphs to executing with spinner.
3. After completion: the pill stays visible (clickable, expanded view shows `Request: prompt: a cat in space`) AND the `InlineImageBlock` renders below the pill.

- [ ] **Step 5: Reload the chat**

Hit F5. Verify:
- The `generate_image` pill is still visible above its image block.
- Other tool-call pills (`web_search`, generic tools) render in their post-reload state.

- [ ] **Step 6: Test non-streaming adapter (optional, if Ollama is configured)**

Switch the session model to an Ollama-served model with tool support. Repeat Step 2. Verify the pill skips streaming phase and appears directly with the spinner.

---

### Task 28: Squash and merge

> **Per [[squash-spec-commits]] feedback memory:** all commits from spec
> authoring + implementation collapse into one before merging to master.

- [ ] **Step 1: Identify the pre-spec commit**

Run: `git log --oneline | head -30`

The pre-spec commit is the one immediately before the spec was added (currently `775da351 image generation fixes, added setup-dev.sh`, but confirm fresh — earlier commits may have been added since).

- [ ] **Step 2: Soft-reset to that commit**

```bash
git reset --soft <pre-spec-commit-sha>
```

All changes from spec + implementation are now staged.

- [ ] **Step 3: Create the single squashed commit**

```bash
git commit -m "$(cat <<'EOF'
Add tool-call pill streaming

Tool calls now show as one pill morphing through three phases:
streaming (live char counter + raw JSON buffer when expanded),
executing (spinner + friendly label), and completed (per-tool
result layout). Image generation joins the unified pill flow and
persists a tool_call timeline entry alongside its image block.

Adapters emit a new ToolCallArgsDelta provider-stream event; the
inference loop routes it through a new chat.tool_call.delta WS
event with late-id backfill. Frontend keeps a per-session
streamingToolCalls slice; ToolCallActivity and ToolCallPills are
replaced by a single ToolCallPill component branching on phase.

Spec: devdocs/specs/2026-05-15-tool-call-pill-streaming-design.md
Plan: devdocs/plans/2026-05-15-tool-call-pill-streaming-plan.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Verify the commit**

Run: `git log --oneline | head -5`
Expected: one new commit at the top, the prior commit unchanged.

Run: `git diff HEAD~1 HEAD --stat`
Expected: shows all files touched by the spec + implementation, in one diff.

- [ ] **Step 5: Per CLAUDE.md "Please always merge to master after implementation"**

If we are not already on master, fast-forward master to this commit:

```bash
git checkout master
git merge --ff-only <feature-branch>
```

If we are on master directly (single-branch workflow), no action needed.

---

## Self-Review Coverage Check

Every section of the spec maps to at least one task:

| Spec section | Tasks |
|---|---|
| 1.1 Topic constant | Task 1 |
| 1.2 ChatToolCallDeltaEvent | Task 2 |
| 1.3 ToolCallArgsDelta provider event | Task 3 |
| 1.4 ToolCallEvent.index | Task 3, 6–10 |
| 1.5 Replay buffer | Task 4 |
| 2.1 OpenAI-style adapters (xAI, Mistral, Community, OpenRouter, nano-gpt, Tensorix, Novita) | Task 5, 6, 7, 8, 9 |
| 2.2 Anthropic adapter | n/a — Claude models flow through OpenRouter / nano-gpt (Task 9), which expose OpenAI-shaped SSE |
| 2.3 Ollama adapter | Task 10 |
| 2.4 Adapter tests | Task 6–10 |
| 3.1 ToolCallArgsDelta case | Task 11 |
| 3.2 Drain hook | Task 11 |
| 3.3 Started/Completed unchanged | (no task — verified by Task 12) |
| 3.4 Log line | Task 11 |
| 3.5 Inference tests | Task 12 |
| 4.1 generate_image extra tool_call entry | Task 24 |
| 4.2–4.4 Other persistence unchanged | (no task — design constraint) |
| 4.5 No migration | (no task — design constraint) |
| 5.1 StreamingToolCall slice | Task 13 |
| 5.2 Reducers | Task 14, 15, 16 |
| 5.3 Event handler additions | Task 21 |
| 5.4 Render-order invariant | Task 21 (handler order) |
| 5.5 Legacy removal | Task 18 |
| 5.6 Reconnect/catchup | (no task — relies on Task 4 replay registration) |
| 5.7 Cleanup on cancel/error | Task 17 |
| 6.1–6.4 ToolCallPill | Task 19, 20 |
| 6.5 MessageList integration | Task 22 |
| 6.6 Component deletions | Task 23 |
| 6.7 Tests | Task 14–17, 20 |
| 7 Edge cases | covered across tasks |
| 8 Roll-out order | tasks ordered to match |
| 9 Out of scope | (no task — design constraint) |

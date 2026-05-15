# Tool-Call Pill Streaming — Design

**Date:** 2026-05-15
**Status:** Spec — awaiting implementation
**Authors:** Chris, in collaboration with Claude

## Problem

Today the tool-calling UX in Chatsune is dry. The user sees that tool calls
happen — pills appear — but there is no live evidence that *something is
actually happening*, especially during two phases:

1. **While the model streams the tool call itself** (most upstream providers
   stream tool-call argument fragments over SSE). The user sees nothing during
   this phase.
2. **While the tool is executing on the server.** Some pills show a spinner
   here (`ToolCallActivity`), but the `generate_image` tool is handled
   separately and never reaches a unified treatment.

The goal: make the tool-call life cycle visible and consistent across all
tools, including `generate_image`.

## Goals

- During tool-call streaming: show a pill with the tool name (as soon as
  known) plus a live character counter. Expanded: raw JSON buffer, monospace,
  same vibe as the `ThinkingBubble`.
- After streaming, while the tool is executing: same pill morphs in place;
  counter is replaced by a spinner; label becomes the existing friendly label
  (e.g. `"Searching the web for ..."`).
- After completion: pill morphs to the tool-specific completed state.
- `generate_image` joins the unified pill flow and persists a `tool_call`
  timeline entry in addition to its `image` entry.
- Non-streaming providers (Ollama) still get a useful UI: the pill skips
  Phase 1 and appears directly in Phase 2.

## Non-goals

- No new token-counting logic. Character count is the unit shown to the user.
- No pretty-printing of streaming arguments during Phase 1 — raw JSON only.
- No animations between phase transitions in this iteration; the UX will be
  evaluated in practice and polish ticketed separately.
- No change to the `web_search` / `knowledge_search` / `web_fetch` persistence
  path.
- No backfill for historical `generate_image` messages — they continue to show
  only the `InlineImageBlock`.

---

## Phase model

A tool-call pill traverses three phases, each driven by a distinct event:

```
+-----------------------------------------------------------------------+
| Phase 1: STREAMING                                                    |
|   Trigger:  first ToolCallArgsDelta from adapter                      |
|   WS event: chat.tool_call.delta                                      |
|             (correlation_id, tool_call_id, tool_index,                |
|              tool_name?, args_delta)                                  |
|   UI:       pill shows tool name (as soon as known) + "123 chars";    |
|             expanded view shows raw JSON buffer in monospace.         |
+-----------------------------------------------------------------------+
| Phase 2: EXECUTING                                                    |
|   Trigger:  chat.tool_call.started — arguments are finalised,         |
|             tool executes on the server                               |
|   UI:       same pill, counter -> spinner, friendly label             |
|             ("Searching the web for ..."); expanded view shows        |
|             pretty-formatted final arguments.                         |
+-----------------------------------------------------------------------+
| Phase 3: COMPLETED                                                    |
|   Trigger:  chat.tool_call.completed                                  |
|   UI:       pill morphs to tool-specific completed state:             |
|             - generic / artefact / generate_image: ToolCallPill       |
|               with arguments + response, expandable                   |
|             - web_search:        WebSearchPills (pill disappears)     |
|             - knowledge_search:  KnowledgePills  (pill disappears)    |
|             - generate_image:    InlineImageBlock additionally        |
|                                  rendered below the pill              |
+-----------------------------------------------------------------------+
```

**Non-streaming case (Ollama):** the adapter never emits
`ToolCallArgsDelta`, so the inference loop never emits `chat.tool_call.delta`.
The pill appears directly in Phase 2 when `chat.tool_call.started` arrives.

**Identity invariant:** `tool_call_id` is the stable identity. Every
`ChatToolCallDeltaEvent` that leaves the backend carries a non-empty
`tool_call_id` (see Section 3 for the buffer/backfill logic that enforces
this). The frontend mounts one React node per id and keeps it mounted through
all three phases.

---

## 1. Shared contracts (`shared/`)

### 1.1 New topic constant

`shared/topics.py`:

```python
CHAT_TOOL_CALL_DELTA = "chat.tool_call.delta"
```

### 1.2 New WS event

`shared/events/chat.py`:

```python
class ChatToolCallDeltaEvent(BaseModel):
    type: str = "chat.tool_call.delta"
    correlation_id: str
    tool_call_id: str            # first delta to land settles it
    tool_index: int              # OpenAI-style index for parallel calls
    tool_name: str | None = None # null until the provider sends it
    args_delta: str              # the new fragment, NOT cumulative
    timestamp: datetime
```

Bandwidth deliberately scales linearly: the event carries fragments, not
cumulative snapshots, and the frontend accumulates locally.

### 1.3 New provider-stream event (internal, adapter-facing)

`backend/modules/llm/_adapters/_events.py` (where the other adapter-facing
provider-stream events such as `ContentDelta`, `ThinkingDelta`,
`ToolCallEvent` already live):

```python
class ToolCallArgsDelta(BaseModel):
    """Provider-stream event: a fragment of a not-yet-finalised tool call."""
    index: int
    id: str | None = None        # first delta typically supplies it
    name: str | None = None      # OpenAI-style: first delta; Anthropic:
                                 # content_block_start (tool_use)
    arguments_delta: str
```

The new type is added to the `ProviderStreamEvent` union at the bottom of
the same file. The existing `ToolCallEvent` (finalised) is unchanged.

### 1.4 `ToolCallEvent.index`

The existing `ToolCallEvent` in `backend/modules/llm/_adapters/_events.py`
gains one new required field: `index: int`. Every adapter (including Ollama,
which does not stream deltas) sets it from its accumulator's index slot. The
inference loop uses this for the late-id backfill described in Section 3.2.

### 1.5 Replay buffer

`backend/ws/event_bus.py`:

- `WS_REPLAY_TOPICS` and `WS_REPLAY_TOPIC_KEYS` include
  `Topics.CHAT_TOOL_CALL_DELTA`. Reconnect mid-stream can replay deltas.

---

## 2. Adapter changes

Three adapter families are affected. Each emits `ToolCallArgsDelta` events
during streaming **in addition to** the existing accumulation pipeline. The
existing `_ToolCallAccumulator` keeps producing the final `ToolCallEvent`
unchanged.

### 2.1 OpenAI-style SSE — `_xai_http.py`, `_mistral_http.py`, `_community.py`, `_nano_gpt_*`

Today, in `_chunk_to_events`:

```python
tool_frags = delta.get("tool_calls") or []
if tool_frags:
    acc.ingest(tool_frags)
```

Replaced with a helper in a new module
`backend/modules/llm/_adapters/_tool_call_streaming.py`:

```python
def fragments_to_delta_events(
    fragments: list[dict],
    acc: _ToolCallAccumulator,
) -> list[ToolCallArgsDelta]:
    """Pre-ingest hook: emit one delta event per fragment, then feed the
    accumulator. The events reflect the fragment as seen, before any
    finalisation logic touches them."""
    events: list[ToolCallArgsDelta] = []
    for frag in fragments:
        idx = frag.get("index")
        if idx is None:
            continue
        fn = frag.get("function") or {}
        existing = acc._by_index.get(idx, {})
        resolved_id = frag.get("id") or existing.get("id")
        args_fragment = fn.get("arguments") or ""
        if args_fragment or frag.get("id") or fn.get("name"):
            events.append(ToolCallArgsDelta(
                index=idx,
                id=resolved_id,
                name=fn.get("name") or existing.get("name") or None,
                arguments_delta=args_fragment,
            ))
    acc.ingest(fragments)
    return events
```

All four OpenAI-style adapters call this helper from `_chunk_to_events` and
prepend the returned events to the existing event list.

**Late-id subtlety.** Some providers send `id` only in the final fragment.
The adapter emits `id=None` in earlier deltas; the inference loop buffers and
backfills (Section 3.1).

### 2.2 Anthropic adapter

Anthropic's SSE is easier:

- `content_block_start` with `type=tool_use` carries `id` + `name` upfront.
  Emit `ToolCallArgsDelta(index, id, name, arguments_delta="")`.
- `content_block_delta` with `delta.type=input_json_delta` carries
  `partial_json`. Emit `ToolCallArgsDelta(index, id, name, arguments_delta=partial_json)`.
- `content_block_stop` finalises through the existing accumulator path.

### 2.3 Ollama (`_ollama_http.py`)

Native Ollama chat streaming returns tool calls in a single complete message.
**No `ToolCallArgsDelta` is emitted.** The existing path is unchanged. From
the frontend's perspective this is the non-streaming case — the pill enters
directly at Phase 2.

### 2.4 Tests

Per adapter, extend the existing streaming tests in
`backend/modules/llm/_adapters/__tests__/`:

- Existing assertions that match the **final** `ToolCallEvent` must keep
  passing. Assertions of the form `events == [ToolCallEvent(...)]` are
  rewritten to "contains-style" (`ToolCallEvent in events` plus
  `events[-1] == ToolCallEvent(...)`) so that the additional `ToolCallArgsDelta`
  events do not break them.
- New tests cover: per-fragment delta emission, ordering, and the case where
  `id` arrives late.

---

## 3. Inference loop (`backend/modules/chat/_inference.py`)

Three changes inside the existing `async for event in stream` block.

### 3.1 New case `ToolCallArgsDelta`

Sits next to `ContentDelta` / `ThinkingDelta`:

```python
case ToolCallArgsDelta(index=idx, id=tc_id, name=tc_name, arguments_delta=frag):
    slot = tool_call_id_buffer.setdefault(idx, {
        "id": None, "name": None, "pending_events": [],
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

    if settings.inference_logging and frag:
        _log.debug(
            "inference.tool_call.delta session=%s correlation_id=%s "
            "index=%d id=%s name=%s frag_chars=%d",
            session_id, correlation_id, idx,
            resolved_id or "<pending>", slot["name"] or "<pending>",
            len(frag),
        )

    event = ChatToolCallDeltaEvent(
        correlation_id=correlation_id,
        tool_call_id=resolved_id or "",
        tool_index=idx,
        tool_name=slot["name"],
        args_delta=frag,
        timestamp=datetime.now(timezone.utc),
    )
    if resolved_id:
        await emit_fn(event)
    else:
        slot["pending_events"].append(event)
```

`tool_call_id_buffer` is a per-iteration local
(`dict[int, dict]`) reinitialised at the top of every iteration body.

### 3.2 Drain at iteration end

In the existing `finally` block, before the post-iteration emission of
`ChatToolCallStartedEvent` for each finalised tool call:

```python
for tc in iter_tool_calls:
    for idx, slot in tool_call_id_buffer.items():
        if slot["pending_events"] and tc.index == idx:
            for pending in slot["pending_events"]:
                pending.tool_call_id = tc.id
                await emit_fn(pending)
            slot["pending_events"] = []
```

This holds the invariant: any `chat.tool_call.delta` that ever reaches the
client carries a non-empty `tool_call_id`.

### 3.3 `ChatToolCallStartedEvent` and `ChatToolCallCompletedEvent` are unchanged

These remain the Phase 1→2 and Phase 2→3 triggers respectively.

### 3.4 New log line

A single info-level log per tool call at stream end:

```python
"inference.tool_call.stream session=%s correlation_id=%s "
"tool_call_id=%s tool=%s args_chars=%d deltas=%d"
```

`args_chars` and `deltas` are tracked per `tool_call_id_buffer` slot
(`slot["chars"] += len(frag)`, `slot["deltas"] += 1` on each emission). At
stream end the loop reads them from the slot when emitting the log. So a
reload of the logs reveals whether a given tool call was streamed and, if so,
how chunked it was.

### 3.5 Tests

`backend/modules/chat/__tests__/` gains:

- Streaming path: deltas → started → completed event sequence, in order.
- Non-streaming path (Ollama-shape stream): no deltas, started → completed.
- Late-id path: deltas buffered without id, then id arrives mid-stream;
  backfill verified.
- Drain path: iteration ends with pending events; drain hook backfills.

---

## 4. Persistence

### 4.1 `generate_image` — additional `tool_call` entry

Today `generate_image` writes only an `image` timeline entry. With the new
"pill remains visible alongside the image block" behaviour, the inference
loop's entry-building block must additionally write a `tool_call` entry:

```python
if tool_name == 'generate_image':
    persisted_entries.append({
        "kind": "tool_call",
        "seq": next_seq(),
        "tool_call_id": tc.id,
        "tool_name": tc.name,
        "arguments": arguments,
        "success": tool_success,
        "moderated_count": moderated_count,
        "result_content": result_str,
    })
    persisted_entries.append({
        "kind": "image",
        "seq": next_seq(),
        "refs": image_refs_for_entry,
        "moderated_count": moderated_count,
    })
```

Order: `tool_call` precedes `image` so the pill renders above the image
block, matching read order.

### 4.2 `web_search` / `knowledge_search` — unchanged

Their dedicated `web_search` / `knowledge_search` timeline entries continue
to carry the result data. No generic `tool_call` entry is written.

### 4.3 Failed tool calls — unchanged

`useChatStream.ts` already writes a generic `tool_call` entry for any failed
tool, regardless of name. This stays.

### 4.4 Streaming arguments are NOT persisted

Only the final, parsed arguments survive a reload. The raw streaming buffer
is a Phase-1-only artefact.

### 4.5 Migration

None required. Additive change. Old `generate_image` messages render with
only the image block — same as today.

---

## 5. Frontend store (`core/store/chatStore.ts`)

### 5.1 New slice

Per-session (analogous to `streamsBySession`):

```typescript
interface StreamingToolCall {
  toolCallId: string
  toolIndex: number
  toolName: string | null
  argsBuffer: string
  charCount: number
  phase: 'streaming' | 'executing'
  startedAt: number
  parsedArguments: Record<string, unknown> | null  // set on phase 'executing'
}

streamingToolCalls: Map<string /* tool_call_id */, StreamingToolCall>
```

### 5.2 Reducers

```typescript
appendToolCallDelta(
  toolCallId: string,
  toolIndex: number,
  toolName: string | null,
  argsDelta: string,
  writeOpts: WriteOpts,
): void
// If the id is new, create a slot with phase='streaming'.
// If toolName arrives, set it.
// Append fragment, bump charCount.

promoteToolCallToExecuting(
  toolCallId: string,
  toolName: string,
  args: Record<string, unknown>,
  writeOpts: WriteOpts,
): void
// Called by the CHAT_TOOL_CALL_STARTED handler.
// If slot exists: phase='executing', parsedArguments=args.
// If slot does not exist: create with phase='executing' and empty buffer
// (non-streaming case, e.g. Ollama).

removeStreamingToolCall(toolCallId: string, writeOpts: WriteOpts): void
// Called by CHAT_TOOL_CALL_COMPLETED handler AFTER the timeline entry has
// been appended.
```

### 5.3 Event-handler additions in `useChatStream.ts`

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

`CHAT_TOOL_CALL_STARTED` additionally calls `promoteToolCallToExecuting`.
`CHAT_TOOL_CALL_COMPLETED` additionally calls `removeStreamingToolCall`
AFTER it has appended the timeline entry — order is critical (Section 5.4).

### 5.4 Render-order invariant Phase 2→3

When `CHAT_TOOL_CALL_COMPLETED` arrives, the handler first appends the
timeline entry, then removes the streaming slot. React batches both state
updates into the same render, so no empty frame appears at the pill's
position. A vitest asserts the order.

### 5.5 Legacy `activeToolCalls` removed

The existing `activeToolCalls` array in `chatStore.ts` and its two reducers
(`addToolCall`, `completeToolCall`) are removed in this change. The
`CHAT_TOOL_CALL_STARTED` handler in `useChatStream.ts` no longer calls
`addToolCall`; it calls `promoteToolCallToExecuting` instead. The
`CHAT_TOOL_CALL_COMPLETED` handler no longer calls `completeToolCall`; it
calls `removeStreamingToolCall` after the timeline entry append (Section
5.4). The `ToolCallActivity` component, which was the sole consumer of
`activeToolCalls`, is deleted (Section 6.6).

### 5.6 Reconnect/catchup

`chat.tool_call.delta` is in the replay buffer (Section 1.5). Mid-stream
reconnect replays all missed deltas; the slice reconstructs the args buffer.

**Edge case:** reconnect after the 24h Redis Streams TTL → buffer gone →
no Phase 1 reconstruction possible. The client receives `CHAT_TOOL_CALL_STARTED`
from the resumption snapshot and enters Phase 2 directly with the parsed
arguments carried by that event. Acceptable degradation.

### 5.7 Cleanup on cancel / error

`cancelStreaming` reducer (existing) and the `CHAT_STREAM_ERROR` handler
clear `streamingToolCalls` slots whose `correlation_id` matches. Tests cover
both paths.

---

## 6. `ToolCallPill` component

One component replaces three render paths: `ToolCallActivity` (during stream),
the existing `ToolCallPills` (after reload), and the generic tool-call entry
in the timeline.

### 6.1 Props

```typescript
type Phase =
  | { kind: 'streaming'; toolName: string | null; charCount: number;
      argsBuffer: string; toolCallId: string }
  | { kind: 'executing'; toolName: string; arguments: Record<string, unknown>;
      toolCallId: string }
  | { kind: 'completed'; ref: ToolCallRef }

interface ToolCallPillProps { phase: Phase }
```

### 6.2 Render branches

Closed (default) shows:

- `streaming`: tool icon, tool name (or `"Tool"` placeholder),
  `"123 chars"` counter, animated dots.
- `executing`: spinner icon + friendly label (`friendlyLabel(toolName, arguments)`).
- `completed`: tool icon + display name (existing behaviour).

Expanded shows:

- `streaming`: `"Streaming arguments..."` header, `<pre>` with raw `argsBuffer`.
- `executing`: `"Request"` header, `<pre>` with `formatArgs(arguments)`.
- `completed`: `"Request"` + optional `"Response"` sections (existing
  behaviour from `ToolCallPills`).

The `friendlyLabel` helper migrates from `ToolCallActivity.tsx` into a shared
helper module `frontend/src/features/chat/toolLabels.ts`. The label map
(`TOOL_LABELS`) is unchanged.

### 6.3 Colour scheme

- `streaming`: muted accent (e.g. `137,180,250` at 0.10 background).
- `executing`: same accent + spinner — matches today's `ToolCallActivity`.
- `completed`: today's `ToolCallPills` palette (success: peach, error: pink,
  plus the per-tool overrides for `knowledge_search` and artefact tools).

### 6.4 Expander state

Local `useState<boolean>(false)` — default closed. Stable React `key`
(`toolCallId`) keeps the same instance mounted through phase transitions, so
a manually-opened pill stays open across `streaming → executing → completed`.

### 6.5 Integration in `MessageList.tsx`

`renderTimelineEntry` for `kind: 'tool_call'` renders
`<ToolCallPill phase={{ kind: 'completed', ref }} />`.

The `isStreaming` branch renders a new block iterating over
`streamingToolCalls` and producing `streaming`-phase or `executing`-phase
pills.

### 6.6 Removed components

- `ToolCallActivity.tsx` — deleted.
- `ToolCallPills.tsx` — replaced by `ToolCallPill.tsx`. Any remaining call
  sites are migrated.

### 6.7 Tests

- `ToolCallPill.test.tsx`: each phase renders correct elements; toggle
  works; expanded state survives phase transitions.
- `useChatStream.test.ts`: delta sequence grows the slice correctly;
  `started` promotes; `completed` removes only after entry append.
- `chatStore.test.ts`: reducer-level tests for each new action including
  cancel/error cleanup.

---

## 7. Edge cases

| Case | Behaviour |
|---|---|
| `id=None` in first fragments, late delivery | Inference loop buffers and backfills (Section 3.1) |
| Iteration ends with pending events | Drain hook attaches ids from `iter_tool_calls` (Section 3.2) |
| Stream cancelled mid-Phase-1 | `cancelStreaming` clears `streamingToolCalls` |
| Stream error mid-Phase-1 | `CHAT_STREAM_ERROR` handler clears the slot |
| Parallel tool calls (multiple indices in flight) | Map schema natively supports it |
| Empty `args` fragment (e.g. first delta carries only `id`/`name`) | Slot is created if absent; `toolName` is set if supplied; `charCount` unchanged. Pill becomes visible with `0 chars`. |
| Late fragment after `finish_reason=tool_calls` | Swallowed at adapter level; loop ignores |
| `generate_image` with `moderated_count > 0` and zero images | `tool_call` entry still written; `image` entry per existing rule |
| Reconnect beyond 24h Redis TTL | Phase 2 only; no Phase 1 reconstruction |

---

## 8. Roll-out order

Each step is individually deployable; the frontend ignores the new topic
until step 4 wires it up.

1. **Shared DTOs and topic** (Section 1) — additive, no breaking change.
2. **Adapter layer** — OpenAI-style first, then Anthropic. Tests rewritten
   from equality to containment assertions.
3. **Inference loop** — delta routing + id backfill, with the four new test
   paths (Section 3.5).
4. **Frontend store slice** — new slice and reducers, plus tests. No UI
   change yet.
5. **`ToolCallPill` component** — implement and test in isolation. Existing
   `ToolCallPills.test.tsx` migrates to `ToolCallPill.test.tsx`.
6. **`MessageList` integration** — remove the old `ToolCallActivity` render
   path, drop the `activeToolCalls` slice, wire the new pill into the live
   and the timeline render paths.
7. **`generate_image` persistence extension** — additional `tool_call`
   entry in `_inference.py`.
8. **Coverage expansion** — Mistral, NanoGPT, Community.

---

## 9. Out of scope

- Token-counting (Tokenizer integration). Char-count only.
- Pretty-printing of streaming arguments during Phase 1.
- Phase-transition animations — to be evaluated after seeing the feature in
  practice and ticketed separately if desired.
- Historical backfill for old `generate_image` messages.
- Changes to the `web_search` / `knowledge_search` / `web_fetch` persistence
  pipelines.

---

## 10. References

- `CLAUDE.md` — module boundaries, shared contracts, event-first architecture.
- `frontend/src/features/chat/ThinkingBubble.tsx` — UI vocabulary template
  for streaming-content pills.
- `frontend/src/features/chat/ToolCallActivity.tsx`,
  `frontend/src/features/chat/ToolCallPills.tsx` — current behaviour, both
  removed in this change.
- `backend/modules/llm/_adapters/_xai_http.py:103` —
  `_ToolCallAccumulator`, the existing fragment-collection logic that this
  spec extends.
- `backend/modules/chat/_inference.py:300` — the `async for event in stream`
  block that gains the new `ToolCallArgsDelta` case.

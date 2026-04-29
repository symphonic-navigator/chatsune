# Spec: Chronological Message Timeline

**Date:** 2026-04-29
**Status:** Draft — awaiting approval

---

## Problem

Pills, tool-call indicators, artefact cards, and inline images attached to an
assistant message render in a different order during the live stream than they
do after a chat reload, and pills are categorically grouped (all knowledge
pills lumped, all web-search pills lumped, all tool pills lumped) rather than
appearing in execution order. Users who reload a chat see content shift around;
some pills appear that weren't visible during the live stream, and vice versa.

`MessageList.tsx:235-268` (live render) places pills **after** tool-call
activity. `MessageList.tsx:177-209` (persisted render) places pills **before**
tool-call activity. Same data, two visible orderings.

Underlying cause: each tool-derived artefact (knowledge results, web-search
results, tool-call metadata, artefact handle, image refs) is stored on the
persisted assistant message in **separate parallel lists** with no shared
ordering key. The chat store mirrors this with separate streaming slots
(`streamingKnowledgeContext`, `streamingWebSearchContext`,
`streamingArtefactRefs`, `streamingImageRefs`, `activeToolCalls`). Live render
and reload render reach into different slots in different orders.

A secondary issue: `KnowledgeSearchCompletedEvent`
(`backend/modules/tools/_executors.py:91`) is published with a fresh UUID as
`correlation_id`, disconnected from the chat-stream correlation_id. This is
chat-local (no other subscribers, audited) but invites race conditions and
makes Redis-Streams reconnect/catchup harder to reason about.

## Goal

Live render and reload render produce **the same DOM structure** for any
assistant message. Nothing visible during the stream disappears on reload, and
nothing new appears on reload that wasn't visible during the stream.
Chronological order within a message is a desirable side-effect, not a hard
requirement; consistency is the hard requirement.

## Non-goals

- Cross-message timeline reordering (messages stay in `created_at` order).
- Splitting assistant text by tool boundaries (text remains a single primary
  field; the timeline covers only the pre-text and tool-derived elements).
- Changing what each pill type looks like.
- Migrating historical messages eagerly. Lazy-on-read until the alpha→beta
  wipe announcement (per CLAUDE.md migration policy).

## Design

### Data model

Add a single new field `events: list[TimelineEntryDto] | None = None` to
`ChatMessageDto` (`shared/dtos/chat.py`). It is a tagged-union list, ordered
by `seq` (monotonic, starting at `0` per message).

Tagged-union variants:

```python
class TimelineEntryKnowledgeSearch(BaseModel):
    kind: Literal["knowledge_search"] = "knowledge_search"
    seq: int
    items: list[KnowledgeContextItem]

class TimelineEntryWebSearch(BaseModel):
    kind: Literal["web_search"] = "web_search"
    seq: int
    items: list[WebSearchContextItemDto]

class TimelineEntryToolCall(BaseModel):
    """Generic tool call — for tools that don't have a specialised renderer."""
    kind: Literal["tool_call"] = "tool_call"
    seq: int
    tool_call_id: str
    tool_name: str
    arguments: dict
    success: bool
    moderated_count: int = 0

class TimelineEntryArtefact(BaseModel):
    kind: Literal["artefact"] = "artefact"
    seq: int
    ref: ArtefactRefDto

class TimelineEntryImage(BaseModel):
    kind: Literal["image"] = "image"
    seq: int
    refs: list[ImageRefDto]
    moderated_count: int = 0

TimelineEntryDto = Annotated[
    TimelineEntryKnowledgeSearch
    | TimelineEntryWebSearch
    | TimelineEntryToolCall
    | TimelineEntryArtefact
    | TimelineEntryImage,
    Field(discriminator="kind"),
]
```

The legacy fields (`tool_calls`, `knowledge_context`, `web_search_context`,
`artefact_refs`, `image_refs`) stay on `ChatMessageDto` as `Optional[...] =
None` for read-back of historical documents only. New documents written by the
backend after this change populate **only** `events`.

`pti_overflow` and `vision_descriptions_used` stay on the user message as
today. They are not part of the assistant timeline.

### Where seq is assigned

In `backend/modules/chat/_inference.py`, the per-stream tool-execution loop
maintains an integer counter `next_seq = 0`. Each tool completion produces
exactly one `TimelineEntry`, with `seq = next_seq` followed by `next_seq +=
1`. Mapping from tool to entry kind:

| `tool_name`                     | Entry kind          | Notes                                                            |
| ------------------------------- | ------------------- | ---------------------------------------------------------------- |
| `knowledge_search`              | `knowledge_search`  | `items` = `RetrievedChunkDto`s mapped to `KnowledgeContextItem`. |
| `web_search`, `web_fetch`       | `web_search`        | `items.source_type` is `"search"` or `"fetch"`.                  |
| `create_artefact`               | `artefact`          | `ref.operation = "create"`.                                      |
| `update_artefact`               | `artefact`          | `ref.operation = "update"`.                                      |
| `generate_image`                | `image`             | One entry per call, `refs` may be empty when fully moderated.    |
| any other (incl. failures)      | `tool_call`         | Generic pill via `ToolCallPills`.                                |

A failed tool call still produces an entry: kind `tool_call` with `success =
false`, regardless of which tool it was. (Rationale: a failed
`knowledge_search` should not appear as an empty `KnowledgePills` — it should
appear as a failed-tool pill.)

The persisted `ChatMessageDocument` writes `events` and **not** the legacy
fields. After this change, MongoDB documents created on or after release have
`events` populated and the legacy fields absent.

### Lazy-on-read for historical messages

`ChatRepository.message_to_dto` (`backend/modules/chat/_repository.py`)
synthesises `events` for documents that lack it. Algorithm:

```
def synthesise_events(doc: dict) -> list[TimelineEntryDto] | None:
    has_legacy = any(k in doc for k in (
        "tool_calls", "knowledge_context", "web_search_context",
        "artefact_refs", "image_refs",
    ))
    if not has_legacy:
        return None  # nothing to render

    events = []
    seq = 0
    tool_calls = doc.get("tool_calls") or []

    # Index legacy result lists once so each tool_call can claim its share.
    knowledge_pool = list(doc.get("knowledge_context") or [])
    web_pool = list(doc.get("web_search_context") or [])
    artefact_pool = list(doc.get("artefact_refs") or [])
    image_pool = list(doc.get("image_refs") or [])

    for tc in tool_calls:
        name = tc["tool_name"]
        if name == "knowledge_search":
            # Drain knowledge_pool entirely into the FIRST search call;
            # subsequent calls get an empty list. Provenance was lossy in
            # legacy data — accept it.
            events.append(TimelineEntryKnowledgeSearch(
                seq=seq, items=knowledge_pool,
            ))
            knowledge_pool = []
        elif name in ("web_search", "web_fetch"):
            events.append(TimelineEntryWebSearch(
                seq=seq, items=web_pool,
            ))
            web_pool = []
        elif name in ("create_artefact", "update_artefact"):
            ref = artefact_pool.pop(0) if artefact_pool else None
            if ref is not None:
                events.append(TimelineEntryArtefact(seq=seq, ref=ref))
            else:
                # Tool ran but ref data is missing — fall back to generic.
                events.append(TimelineEntryToolCall(
                    seq=seq,
                    tool_call_id=tc["tool_call_id"],
                    tool_name=name,
                    arguments=tc.get("arguments") or {},
                    success=tc.get("success", True),
                    moderated_count=tc.get("moderated_count", 0),
                ))
        elif name == "generate_image":
            events.append(TimelineEntryImage(
                seq=seq,
                refs=image_pool,
                moderated_count=tc.get("moderated_count", 0),
            ))
            image_pool = []
        else:
            events.append(TimelineEntryToolCall(
                seq=seq,
                tool_call_id=tc["tool_call_id"],
                tool_name=name,
                arguments=tc.get("arguments") or {},
                success=tc.get("success", True),
                moderated_count=tc.get("moderated_count", 0),
            ))
        seq += 1

    # If knowledge or web results survived (no matching tool_call recorded —
    # can happen with very early documents), append them as standalone
    # entries so they remain visible.
    if knowledge_pool:
        events.append(TimelineEntryKnowledgeSearch(seq=seq, items=knowledge_pool))
        seq += 1
    if web_pool:
        events.append(TimelineEntryWebSearch(seq=seq, items=web_pool))
        seq += 1

    return events
```

This is **deterministic**: the same legacy document always yields the same
`events`. That is the consistency guarantee the user asked for. It is **not**
chronologically perfect for old messages (provenance was lossy), but it is
stable across reloads.

`message_to_dto` calls `synthesise_events` whenever `events` is absent and
populates the DTO's `events` field. The legacy fields stay populated on the
DTO too (used nowhere on the frontend after this change, but harmless and
keeps the DTO truthful about what's stored).

The synthesis path stays in the codebase until the alpha→beta wipe (Chris
announces the wipe with a few days' notice). After wipe, all legacy paths
including `synthesise_events` are removed in a follow-up PR.

### Backend write path

`_inference.py` currently passes four lists into `save_fn`. Replace with a
single `events: list[TimelineEntryDto]`. The save path
(`ChatRepository.save_assistant_message` or equivalent) writes
`doc["events"] = [e.model_dump() for e in events]` and **does not** write the
legacy fields. `_repository.py`'s message-document index does not need a new
index for `events`.

### Frontend store

Replace these state slots in `chatStore.ts`:

- `streamingWebSearchContext`
- `streamingKnowledgeContext`
- `streamingArtefactRefs`
- `streamingImageRefs`

with a single:

```ts
streamingEvents: TimelineEntryDto[]
```

`activeToolCalls` stays — it represents the transient "tool currently running"
indicator, which has no persistent counterpart and is not part of the
timeline. When a tool completes, `useChatStream` (or `useKnowledgeEvents` for
the KB-specific case) appends the corresponding `TimelineEntry` to
`streamingEvents` and removes the entry from `activeToolCalls`.

`finishStreaming` consumes `streamingEvents` to populate `finalMessage.events`
before appending `finalMessage` to `messages`. The legacy `streamingArtefactRefs`
and `streamingImageRefs` paths in `useChatStream.ts:90-148` collapse into the
same `appendStreamingEvent` helper.

The `seq` on streaming entries is computed client-side (incrementing counter
per stream). The backend sends the same `seq` on the persisted message. They
must agree — see "Sequence agreement" below.

### Sequence handling — local counters, persisted record wins

`seq` exists only as an internal ordering key per message. We do **not**
extend any WebSocket event payload with `seq`. Both sides increment their
own counters independently:

- **Backend (`_inference.py`):** keeps `next_seq` per message; assigns to
  each entry as it goes; writes them into MongoDB at stream end.
- **Frontend (`chatStore`):** keeps `next_seq` per active stream; assigns
  to each entry it appends to `streamingEvents` as live tool-events arrive.

If an event is dropped or arrives out-of-order on the WebSocket the live
view will momentarily diverge from what the backend recorded. That is
**acceptable** — order is secondary; presence is what matters. The
authoritative reconciliation happens at stream end:

- `ChatStreamEndedEvent` carries the persisted `ChatMessageDto` (it already
  does). Its `events` field is the source of truth.
- `finishStreaming` discards `streamingEvents` and uses
  `finalMessage.events` exclusively.

This means no event-contract changes. Existing event subscribers keep
working unchanged. The only frontend-side rule is "during streaming, append
in arrival order; at stream end, replace with the persisted list".

### KB-event correlation_id fix (RC-3)

`backend/modules/tools/_executors.py:91` currently does
`correlation_id = str(uuid4())`. Change: accept the chat-stream's correlation
id from the tool execution context (already available — the executor is
called with stream context) and pass it through.

The frontend `useKnowledgeEvents.ts:66` keeps working unchanged because it
doesn't gate on correlation_id today. It will keep working after the fix
because it still reads the event's payload regardless of the id. The fix is
defensive — it makes the event semantically correct (it belongs to the
stream) and unlocks future correlation-based filtering if needed.

### Frontend render

`MessageList.tsx` collapses to one render path per role.

For an assistant message (live or persisted):

```tsx
const rawEvents = msg.events ?? []   // for persisted
// or
const rawEvents = streamingEvents    // for the live block

// PTI from the preceding user message stays *merged* into the assistant's
// first knowledge_search entry, preserving the visible behaviour of today's
// `combinedItems = ptiItems + assistant_knowledge_context`. This merge runs
// on both the live and persisted render paths, so the result is identical.
const ptiItems = prevUserMessage?.knowledge_context ?? []
const ptiOverflow = prevUserMessage?.pti_overflow ?? null
const events = mergePtiIntoFirstKnowledgeEntry(rawEvents, ptiItems, ptiOverflow)

return (
  <div>
    {events.map((e) => renderTimelineEntry(e))}
    {activeToolCalls.filter((tc) => tc.status === "running").map(...)}
    <AssistantMessage thinking={msg.thinking} content={msg.content} ... />
  </div>
)
```

`mergePtiIntoFirstKnowledgeEntry` rules:

- If `events` contains at least one `knowledge_search` entry: prepend
  `ptiItems` to that entry's `items` and attach `ptiOverflow` for the
  renderer. Keep `seq` unchanged.
- If `events` has no `knowledge_search` entry but PTI items exist: insert a
  synthetic `knowledge_search` entry at index 0 with `seq = -1`, items =
  `ptiItems`, plus an `_overflow` field for `ptiOverflow`. The synthetic
  entry is render-only and never reaches the store.
- If both are empty: no-op.

`renderTimelineEntry` switches on `e.kind`:

- `knowledge_search` → `<KnowledgePills items={e.items} overflow={null} />`
- `web_search` → `<WebSearchPills items={e.items} />`
- `tool_call` → `<ToolCallPills toolCalls={[e]} />`
- `artefact` → `<ArtefactCard ... />`
- `image` → `<InlineImageBlock refs={e.refs} moderatedCount={e.moderated_count} />`

The "currently running" tool indicator (`ToolCallActivity`) is rendered
**after** the events list and **before** the message body. It only ever
shows for in-flight tools; once the tool completes, the corresponding event
is in the events list and the activity indicator disappears for that tool.
This is the only piece that legitimately differs between live and reload —
because reload, by definition, has no in-flight tools.

Thinking stays at the top inside `AssistantMessage` (no change).

### What about live "running tool → completed tool" handover?

When a tool starts: an entry appears in `activeToolCalls` (status `running`)
and `<ToolCallActivity>` renders. When the tool completes: the
corresponding `TimelineEntry` is appended to `streamingEvents` (with `seq`)
and the `activeToolCalls` entry is removed. From the user's perspective:
the "spinner-like" activity indicator disappears at the same instant the
real pill appears in the timeline above it. No flicker, no double-render.

Because activity indicators are positioned **after** the events list, and
events are positioned **above** the message body, the visual flow is:

```
[ thinking, collapsible ]
[ event seq=0: knowledge pill ]
[ event seq=1: web pill ]
[ event seq=2: artefact card ]
[ activity: tool currently running, e.g. seq=3 placeholder ]
[ message body, possibly streaming text ]
```

After stream end, no activity indicators — events and message body only.
After reload, same structure, same `events` list, same DOM.

## Migrations

- **No DB write migration.** New writes use the new shape; old reads use
  `synthesise_events`.
- Indexes: none added or removed.
- Pydantic field defaults: `events: list[...] | None = None`. Legacy fields
  also default to `None`. Existing documents (which have legacy fields and
  no `events`) deserialise without error because each legacy field is
  already optional or has a default.

## Test strategy

### Backend

- Unit test `synthesise_events` with hand-crafted legacy documents covering:
  one knowledge_search call, multiple knowledge_search calls, mixed tools,
  failed tools, missing artefact_ref, missing tool_calls but populated
  knowledge_context (very early documents).
- Unit test the inference loop's `seq` counter: run a mock tool sequence,
  assert resulting `events` list matches expected entries with monotonic
  `seq`, and assert no entries land in legacy fields.
- Round-trip test: write an `events`-shaped message, read it back via
  `message_to_dto`, assert the DTO matches the original (no synthesis runs
  when `events` is present).

### Frontend

- Unit test `chatStore` `streamingEvents` accumulation: dispatch tool-related
  events in arrival order, assert append-only with monotonically increasing
  client-side `seq`; assert `streamingEvents` is cleared on
  `finishStreaming` and the new `messages[-1].events` reflects the persisted
  list (not the streamed one).
- Unit test `MessageList` render: feed a persisted message with `events =
  [knowledge_search@0, web_search@1, artefact@2]`, assert DOM order matches.
- Unit test `mergePtiIntoFirstKnowledgeEntry`: with PTI + existing
  knowledge_search entry → PTI items prepended; PTI only → synthetic entry
  at index 0 with `seq = -1`; no PTI, no knowledge_search → unchanged.
- Unit test `MessageList` render with legacy message (no `events`, has
  `tool_calls + knowledge_context`): assert it falls through to the same
  render path because the DTO already carries synthesised events.

### Manual verification (real device)

1. Open Chatsune, start a new chat with a persona that has tools and
   knowledge libraries attached.
2. Ask a question that triggers `knowledge_search`. Watch: a knowledge
   pill should appear at the moment the tool completes, **above** the
   message text as it streams in. Note the position visually.
3. Continue the same chat with a question triggering `web_search`. Watch:
   a web-search pill appears below the existing knowledge pill, above the
   new assistant text.
4. Ask a question that triggers `create_artefact`. Watch: artefact card
   appears in chronological position relative to existing pills.
5. Reload the page (full browser refresh, F5).
6. Open the same chat from the session list. **Verify:** the assistant
   messages from step 2/3/4 render with pills/cards in the **exact same
   visual order** as during the live stream. No pill missing, no pill new.
7. Repeat with an existing chat that pre-dates this change. Pills should
   render (synthesised from legacy fields). Reload the chat twice in a row;
   visual layout must be identical between the two reloads.
8. Edge case: ask something that triggers two `knowledge_search` calls in
   one assistant turn. New documents: two knowledge pills, in order. Old
   documents (synthesised): one knowledge pill containing all results.
9. Edge case: trigger a tool that fails (e.g. malformed argument). The
   failed call should appear as a generic tool pill with the failure
   indicator, not as an empty knowledge pill or a vanishing.
10. **Continuous voice (first-class scenario).** Enter continuous-voice
    mode on a persona with tools and knowledge libraries attached. Speak
    a turn that triggers `knowledge_search` and `web_search`. Watch:
    pills appear in the chat scroll area as the spoken response is
    being generated. End the voice session and reload the page. Open
    the same chat. Assert: pills render in the same order/positions as
    they did during the voice turn. No pill missing, no pill new.
11. **Continuous voice — multi-turn with mixed tools.** Within one
    continuous-voice session, do three turns: (a) one with KB only,
    (b) one with web search only, (c) one with `create_artefact`. Reload
    the page. Open the chat. Assert each assistant message renders its
    pills/cards in the same arrangement as it had live, including the
    artefact card.
12. **Continuous voice — mid-stream barge.** Start a turn that triggers
    a tool, then barge-in (speak over) before the assistant finishes
    speaking. The aborted assistant message should still persist its
    timeline up to the barge point. Reload. Assert the partial message
    renders the pills that had appeared before the barge.

## Open risks

- **Legacy synthesis loses provenance.** Two `knowledge_search` calls in an
  old document collapse into one event. Acceptable per CLAUDE.md migration
  policy (we don't promise perfect history) and Chris's "consistency over
  chronology" relaxation.
- **Live ordering may briefly differ from persisted ordering.** Because we
  use independent counters and don't reconcile per-event, a dropped or
  out-of-order WebSocket event can show pills in a different position
  during the live stream than after `ChatStreamEndedEvent` arrives. At
  stream end the persisted list takes over, so the user sees a
  one-time reorder if this happens. Acceptable: presence is the hard
  guarantee, order is secondary.
- **PTI merge is render-only.** `mergePtiIntoFirstKnowledgeEntry` runs on
  the render path, not in the store. The store keeps assistant `events`
  pure (no PTI smuggled in). This avoids backend-frontend
  representation drift.

## Out of scope (future work)

- Eager DB migration to drop legacy fields.
- Storing per-tool execution timestamps on the timeline entries (would
  enable "took 2.3s" on each pill).
- Splitting message text by tool boundaries (mid-text tool calls).

# Frontend Race Condition Fixes (d-6 + d-13) — Design Specification

**Date:** 2026-05-17
**Status:** Approved (pre-implementation)
**Source brief:** [PRE-BRANCHING.md](../../PRE-BRANCHING.md) findings **d-6** (optimistic dedup-by-content fallback) and **d-13** (`reset` + REST `getMessages` race buffering).
**Scope:** Two frontend race-condition fixes that stabilise multi-session UX. Both multiply once branching ships (more sessions, more switches, more concurrent stream activity), so we land them before the branching feature itself.

---

## 1. The two problems

### 1.1 d-6 — optimistic dedup-by-content fallback

`frontend/src/features/chat/useChatStream.ts:548-580` handles
`CHAT_MESSAGE_CREATED`:

```ts
const clientId = p.client_message_id as string | undefined
if (clientId) {
  const idx = getStore().messages.findIndex((m) => m.id === clientId)
  if (idx !== -1) {
    getStore().swapMessageId(clientId, p.message_id as string, { ... })
    break
  }
}
// Fallback: append if we have no matching optimistic entry
getStore().appendMessage({ ... })
```

If the server-echoed user message arrives **without** the current
tab's `client_message_id` (ChatGPT import replay, branch-fork
synthetic message, second-tab echo), or with an id that doesn't match
any optimistic entry in this tab, the handler appends the real
message — and the optimistic entry **stays** in the store. The user
sees the same message twice.

### 1.2 d-13 — `reset` + REST `getMessages` race

`frontend/src/features/chat/ChatView.tsx:482-505`:

```ts
chatApi.getMessages(sessionId).then((bundle) => {
  if (cancelled) return
  useChatStore.getState().setMessages(bundle.messages)
  // ... hydrate context state
})
```

The REST call takes 50–500 ms. During that window, the WS connection
can deliver events targeting the same session. Possible interleavings:

- `REST → WS event`: WS event applies its update *on top of* the REST
  snapshot. Usually fine.
- `WS event → REST`: REST overwrites the WS update with its older
  snapshot. The newer state is lost until the next event.

Both are observable today. Branching makes the second case worse
because branch-switching is a frequent session switch under live
streams.

---

## 2. Fix 1 — Optimistic dedup-by-content fallback (d-6)

### 2.1 Solution

Add a second fallback before the unconditional `appendMessage`:

```ts
case Topics.CHAT_MESSAGE_CREATED: {
  if (p.session_id !== sessionId) return
  const knowledgeContext =
    (p.knowledge_context as KnowledgeContextItem[] | null | undefined) ?? null
  const ptiOverflow = (p.pti_overflow as PtiOverflow | null | undefined) ?? null
  const clientId = p.client_message_id as string | undefined

  // Fallback 0: exact match on the current tab's optimistic id.
  if (clientId) {
    const idx = getStore().messages.findIndex((m) => m.id === clientId)
    if (idx !== -1) {
      getStore().swapMessageId(clientId, p.message_id as string, {
        knowledge_context: knowledgeContext,
        pti_overflow: ptiOverflow,
        is_optimistic: false,
      })
      break
    }
  }

  // Fallback 1 (NEW): dedup by content + role. Branching, second-tab
  // echo, and ChatGPT replay all create real user docs without the
  // current tab's client_message_id but with content that matches an
  // optimistic entry from THIS tab.
  if (p.role === 'user') {
    const content = p.content as string
    const optimistic = getStore().messages.find((m) =>
      m.is_optimistic && m.role === 'user' && m.content === content,
    )
    if (optimistic) {
      getStore().swapMessageId(optimistic.id, p.message_id as string, {
        knowledge_context: knowledgeContext,
        pti_overflow: ptiOverflow,
        is_optimistic: false,
      })
      break
    }
  }

  // Fallback 2: pure appendMessage.
  getStore().appendMessage({ ... })
  break
}
```

### 2.2 Constraints

- **`role === 'user'` gate**: only user messages have optimistic
  counterparts today.
- **Exact content match** — no trimming, no normalisation, no fuzzy
  matching. Same-text false positives are vanishingly rare and the
  cost (dedup) is preferable to the cost (duplicate display).
- **`is_optimistic: true` is the gate** so we never collapse a real
  message into another real message. The flag was introduced by the
  earlier `is_optimistic` low-hanging-fruit fix.
- **Multi-optimistic edge case**: if two optimistic entries have the
  same content (retry-without-let-the-first-land), the first-in-store
  is swapped. The second optimistic gets cleaned up by its own
  eventual `CHAT_MESSAGE_CREATED`. Acceptable; rare and self-healing.

### 2.3 Tests

New file: `frontend/src/features/chat/__tests__/useChatStream.dedup.test.ts`.

Test cases:

- Optimistic exists, real msg arrives **with** matching `client_message_id` → swap via fallback 0 (regression for the existing path).
- Optimistic exists, real msg arrives **without** `client_message_id` but matching content → swap via fallback 1.
- No optimistic, real msg arrives → append (fallback 2).
- Optimistic exists, real msg arrives with **different content** → append (real msg is genuinely new; optimistic stays until its own echo).
- Real msg with `role: assistant` → never collapses against an optimistic user message even if content matches.

---

## 3. Fix 2 — `reset` + REST race buffering (d-13)

### 3.1 Solution — store-level reconciliation flag

Per Chris's option-2 from the brainstorm (simpler than hoisting the WS
subscription out of `useChatStream`):

Add a per-session reconciliation flag to `chatStore`:

```ts
// chatStore.ts state shape additions
interface ChatStoreState {
  // ... existing
  reconciling: Record<string, BaseEvent[]>  // sid -> pending events
}

// Actions
beginReconciliation: (sessionId: string) => void
endReconciliation: (sessionId: string, handler: (e: BaseEvent) => void) => void
queueOrPass: (e: BaseEvent, sessionId: string, handler: (e: BaseEvent) => void) => void
```

- `beginReconciliation(sid)` initialises `reconciling[sid] = []`.
- `endReconciliation(sid, handler)` calls `handler(e)` for every
  queued event in order, then `delete reconciling[sid]`.
- The `useChatStream` event handler consults `reconciling[sid]` for
  each incoming session-targeted event: if the entry exists, push;
  otherwise dispatch normally.

### 3.2 ChatView wiring

`frontend/src/features/chat/ChatView.tsx:482-505`:

```ts
setIsLoading(true)
useChatStore.getState().beginReconciliation(sessionId)

chatApi.getMessages(sessionId)
  .then((bundle) => {
    if (cancelled) {
      // Drop the pending queue — the user switched away.
      useChatStore.getState().endReconciliation(sessionId, () => {})
      return
    }
    useChatStore.getState().setMessages(bundle.messages)
    useChatStore.getState().setContextStatus(bundle.context_status)
    // ... hydrate context state
    useChatStore.getState().setCompactionCheckpoints(
      bundle.compaction_checkpoints ?? [],
    )
    // Drain the queued WS events through the same dispatcher that
    // would have handled them live.
    useChatStore.getState().endReconciliation(sessionId, dispatchChatStreamEvent)
  })
  .catch(...)
```

`dispatchChatStreamEvent` is the function inside `useChatStream`'s
event handler — extract it into a stable exported reference so
ChatView can call it during drain. (Cheaper than the alternative of
trying to make ChatView re-emit through the WS layer.)

### 3.3 useChatStream wiring

At the top of the `case` switch inside `useChatStream`'s event
handler, check the reconciliation queue:

```ts
const handler = (e: BaseEvent) => {
  const sid = (e.payload as { session_id?: string })?.session_id
  if (sid) {
    const pending = useChatStore.getState().reconciling[sid]
    if (pending !== undefined) {
      // We're inside a REST reconciliation window for this session.
      // Queue and return; dispatcher will replay us when the REST lands.
      useChatStore.getState().queueOrPass(e, sid, handler)
      return
    }
  }
  // ... existing switch statement ...
}
```

`queueOrPass` pushes into `reconciling[sid]` and is a no-op for the
"dispatch normally" branch (handled by the caller).

### 3.4 Cross-session events flow through

The `if (sid) { ... if pending ... }` gate only intercepts events
whose payload carries `session_id` matching a reconciling session.
Global events (other-persona deletes, etc.) flow through unimpeded.

### 3.5 Idempotency of queued events

When `dispatchChatStreamEvent` replays queued events after REST
hydration:

- `CHAT_MESSAGE_CREATED` with a `message_id` already in the
  hydrated bundle: the swap-or-append paths from d-6 §2 handle the
  duplicate idempotently (swap to optimistic if it matches; otherwise
  the existing `appendMessage` would double-append, but the bundle's
  setMessages-then-append never produces the same `message_id`
  twice because hydrated messages aren't optimistic).
- `CHAT_CONTENT_DELTA`: stream-slot updates idempotent; replay
  just re-applies the delta to a slot that may already be in the
  right state. Worst case: the stream view briefly flickers and
  settles.
- `CHAT_MESSAGE_DELETED` for a message that's already gone from the
  bundle: existing handler is no-op for unknown ids.

No additional dedup layer is required for the drain.

### 3.6 Tests

Extend `frontend/src/features/chat/__tests__/useChatStream.test.ts`
(or new `reconcile.test.ts`):

- Switch to session A while WS delivers `CHAT_MESSAGE_CREATED` for A
  mid-REST: assert the new message lands AFTER the REST snapshot's
  messages and the bundle is intact.
- Switch to A while WS delivers `CHAT_CONTENT_DELTA` for A: assert
  the stream slot is populated after REST hydration (not silently
  dropped).
- Switch to A; WS delivers an event for session **B** during A's
  REST: B's event flows through unimpeded.
- Cancellation: switch to A, then to B before A's REST returns.
  A's pending queue is discarded (cancellation path calls
  `endReconciliation` with a no-op handler). B's reconciliation
  starts cleanly.

---

## 4. Backwards compatibility

- **d-6**: additive fallback. Existing match path (`client_message_id`)
  is unchanged. The new branch only fires when fallback 0 misses.
- **d-13**: the reconciliation queue is empty outside the REST
  window. Outside that window, the event handler dispatches normally.

No persistence changes, no event topic changes, no API changes.

---

## 5. Implementation order

1. **d-6** (smaller, single-handler change): add the fallback,
   write tests.
2. **d-13** (more invasive: touches the store + ChatView lifecycle):
   - Extend `chatStore` with `reconciling` state + actions.
   - Extract `dispatchChatStreamEvent` from `useChatStream` for use
     by ChatView's drain.
   - Wire `beginReconciliation` / `endReconciliation` into
     ChatView's `getMessages` flow.
   - Add the queue check at the top of `useChatStream`'s event
     handler.
   - Write tests.
3. INSIGHTS.md entry (next free INS number — INS-051 probably).
4. `pnpm tsc --noEmit` clean; `pnpm test` clean.

---

## 6. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| d-6 false positive: same user message accidentally collapsed | Very low | One optimistic stays, harmless | Exact content match + `is_optimistic` gate |
| d-13 drain replays an event that the bundle already represents | Low | Idempotent handlers; flicker max | §3.5 covers each event type |
| d-13 cancellation leaves a stale `reconciling[sid]` | Low | Future events for sid are queued forever | ChatView cleanup function calls `endReconciliation` with a no-op handler |
| Forgotten event topic in the drain | Possible | New events bypass the queue | The queue is by sid in the payload; ANY event with `session_id` is queued |

---

## 7. What this unblocks

- **Branching**: branch-switch is a frequent session-switch under
  live streams. d-13's race is exactly that hot path made more
  common. d-6 closes the duplicate-display risk when a branch fork
  creates a synthetic user message without the local tab's
  `client_message_id`.

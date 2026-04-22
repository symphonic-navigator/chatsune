# Response Task Group Architecture

**Status**: Design spec, pre-implementation
**Supersedes**: Tentative-Barge pattern (`audioPlayback.mute()` + `session.cancelled`), ad-hoc cancel paths in text-chat
**Scope**: All chat responses — text-chat and voice-chat alike
**Owner**: Chris

---

## 1. Problem Statement

Today Chatsune has two noticeably different code paths handling "an assistant is replying to me":

### 1.1 Voice-chat symptoms (erratic, visible)

The current voice-barging pipeline has unreliable behaviour:

1. **Barge sometimes fails to interrupt** — the user speaks, gets transcribed, but the running TTS keeps talking over them.
2. **"Zombie" TTS after confirm** — after `cancelStreamingAutoRead()` fires, new audio chunks still arrive and play.
3. **Interleaved prompts / duplicated content** — the chat view shows `[prompt1][prompt2][resp1][resp2]`, or a response echoes the previous one.

Diagnosis (see session transcript, April 2026): five latent defects converge:

| # | Defect | Evidence |
|---|--------|----------|
| 1 | `audioPlayback.enqueue()` has no correlation/session gate | `audioPlayback.ts:60` |
| 2 | `useEffect([isStreaming])` reacts to edges — batched state updates can swallow them | `ChatView.tsx:800` |
| 3 | Backend cancel is piggy-backed on the next `chat.send`; no explicit cancel at barge-confirm time | `useConversationMode.ts:306` → `chatApi.send` |
| 4 | `chatStore.streamingContent` reset masks the race — new session starts without a live sentencer if the `isStreaming` edge was missed | `chatStore.ts:115` |
| 5 | Phase machine has three writers (explicit `setPhase`, streaming-state effect, 150 ms playback poller) that can flip one another | `useConversationMode.ts:641`, `:664` |

Symptomatic patches (e.g. "always set `muted = true` in `mute()`") address one symptom at a time and leave the architecture fragile.

### 1.2 Text-chat symptoms (subtle, today acceptable)

Text-chat is less visibly broken, but shares the same root cause — no clear "this reply is one cancellable unit" abstraction:

- The `isStreaming` flag and `streamingContent` string in `chatStore` are global per-user mutable state; a second `chat.send` starts overwriting them before the first is guaranteed to be torn down.
- `chat.edit` and `chat.regenerate` rely on the backend to cancel in-flight inference, but the frontend does not explicitly wind down the previous response — it simply expects that no more deltas arrive.
- Correlation IDs are generated server-side and only echo back via `CHAT_STREAM_STARTED`, so there is a window where the client knows "I sent" but has no ID to cancel against.

These aren't bugs users report today, but they are the same class of problem that manifests loudly under voice, and they block clean solutions to features that need per-response lifecycle (e.g. per-message metrics, streaming attachments, explicit "stop" across tabs).

### 1.3 Why one architecture for both

Because the underlying concept — *a response is a named, cancellable bundle of work owned by one correlation ID* — is identical for text and voice. Unifying them gives:

- A single mental model ("every assistant reply is a Group") across the codebase
- Identical, grep-friendly logs for text and voice
- Shared test infrastructure
- Multi-tab correctness for free (registry enforces one-group-per-user, matching backend's per-user inference lock)
- A clean extension surface for future modes (ambient, tool-use variants) — a new mode is a new set of children, not a new code path

---

## 2. Mental Model: Response Task Group

A **Response Task Group** is a named, cancellable unit that owns everything produced on behalf of one assistant reply:

```
ResponseTaskGroup(correlationId)
├── WS listener (filters on correlationId)
└── children: GroupChild[]
     ├── Text-mode:  [chatStoreSink]
     └── Voice-mode: [chatStoreSink, sentencer, pauser, synth, playback]
```

### 2.1 Invariants

- **Exactly one group is active per user at a time.** Creating a new group cancels the previous one. Mirrors the backend's per-user inference lock. Parallel chat sessions per user are an explicit non-goal (healthy UX boundary — see project memory).
- **Every work-item carries the group token** (= `correlationId`). Children silently drop work whose token does not match their own; when the group is cancelled, all in-flight work falls on the floor at the next boundary.
- **Group lifecycle is explicit and logged.** No state transition happens as a side-effect of something else.
- **Children are immutable for the duration of a group.** Switching modes (text ↔ voice) mid-stream does not alter the running group — it affects the next group only. This is deliberate: mode-toggle is preference, cancel-button is destructive action. Separate affordances for separate intents.

### 2.2 Group-level vs. child-internal channels

Children communicate on two levels:

1. **Group-level** (uniform, mandatory): every child receives `onDelta`, `onStreamEnd`, `onCancel`, `teardown`. The Group itself dispatches these; no child can skip them.
2. **Child-internal** (voice-only, via dependency injection): voice children may reference each other to pass along voice-internal events such as sentence-boundary signals from the sentencer to the pauser. The Group does not see this channel — segment concepts stay Voice-internal. This keeps the Group class agnostic of voice.

### 2.3 STT pathway

STT lives *outside* the group and speaks to it through a small verb set (unchanged from the previous voice-only design):

| Trigger | Group call | Rationale |
|---------|-----------|-----------|
| VAD `onSpeechStart` (past 150 ms misfire window) | `group.pause()` | Tentative — might be real, might be noise |
| STT returns non-empty transcript | `group.cancel('barge-cancel')` + new `chat.send` | Confirmed barge |
| STT returns empty transcript | `group.resume()` | Misfire — unpause |
| VAD `onMisfire` before pause committed | (no-op on group) | Misfire cleared before pause fired |

Text-chat triggers look like this instead:

| Trigger | Group call |
|---------|-----------|
| User clicks stop button | `group.cancel('user-stop')` |
| User clicks regenerate/edit on an older message | new `createResponseTaskGroup`; `registerActiveGroup` auto-cancels the previous one with reason `'superseded'` |

Same verb set, different trigger sources.

---

## 3. Group Structure

### 3.1 The `GroupChild` interface

```ts
interface GroupChild {
  readonly name: string     // for logs: 'chatStoreSink' | 'sentencer' | 'pauser' | 'synth' | 'playback'

  onDelta(delta: string, token: string): void
  onStreamEnd(token: string): void | Promise<void>   // resolves when drained
  onCancel(reason: CancelReason, token: string): void
  teardown(): void | Promise<void>

  // optional — default no-op
  onPause?(): void
  onResume?(): void
}
```

Four required callbacks follow the Group lifecycle. Every child verifies `token === ownToken` at the head of each callback and drops silently on mismatch (defence in depth against late-arriving promises).

### 3.2 The `ResponseTaskGroup` class

```ts
interface ResponseTaskGroupDeps {
  correlationId: string
  sessionId: string
  userId: string
  children: GroupChild[]
  sendWsMessage: (msg: WsOutbound) => void
  logger: Logger
}

interface ResponseTaskGroup {
  readonly id: string                    // correlationId
  readonly sessionId: string
  readonly state: GroupState

  // driven by useChatStream on WS events
  onDelta(delta: string): void
  onStreamEnd(): void

  // driven by STT path (voice) or user actions (both)
  pause(): void
  resume(): void
  cancel(reason: CancelReason): void
}

type GroupState     = 'before-first-delta' | 'streaming' | 'tailing' | 'done' | 'cancelled'
type CancelReason   = 'barge-retract' | 'barge-cancel' | 'user-stop' | 'teardown' | 'superseded'
```

### 3.3 The registry — one slot per user

```ts
// module-level state in frontend/src/features/chat/responseTaskGroup.ts
let activeGroup: ResponseTaskGroup | null = null

function registerActiveGroup(g: ResponseTaskGroup): void {
  if (activeGroup && activeGroup.state !== 'done' && activeGroup.state !== 'cancelled') {
    activeGroup.cancel('superseded')
  }
  activeGroup = g
}

function getActiveGroup(): ResponseTaskGroup | null {
  return activeGroup
}

function clearActiveGroup(g: ResponseTaskGroup): void {
  if (activeGroup === g) activeGroup = null
}
```

Groups auto-clear themselves from the registry on terminal transition (`done` or `cancelled` → `clearActiveGroup(this)`).

### 3.4 Internal dispatch logic (pseudocode)

```ts
onDelta(delta) {
  if (this.state === 'before-first-delta') this.transition('streaming')
  if (this.state !== 'streaming') return
  for (const child of this.children) child.onDelta(delta, this.id)
}

async onStreamEnd() {
  if (this.state !== 'streaming') return
  this.transition('tailing')
  const drains = this.children.map(c => c.onStreamEnd(this.id))
  await Promise.allSettled(drains)
  if (this.state !== 'tailing') return   // cancelled during drain
  this.transition('done')
}

cancel(reason) {
  if (this.state === 'done' || this.state === 'cancelled') return
  const wasBeforeDelta = this.state === 'before-first-delta'
  this.transition('cancelled', reason)
  for (const child of this.children) child.onCancel(reason, this.id)

  this.sendWsMessage({
    type: wasBeforeDelta ? 'chat.retract' : 'chat.cancel',
    correlation_id: this.id,
  })

  // teardown in background; do not block caller
  void Promise.allSettled(this.children.map(c => c.teardown()))
}
```

---

## 4. State Machine

```
  before-first-delta ──[CONTENT_DELTA]──▶ streaming ──[STREAM_ENDED]──▶ tailing ──[all children drained]──▶ done
        │                                     │                           │
        └──[cancel]──┐            ┌──[cancel]─┘            ┌──[cancel]─┘
                     ▼            ▼                        ▼
                              cancelled (terminal)
```

### 4.1 State semantics

| State | LLM | Children | `cancel()` effect |
|-------|-----|----------|-------------------|
| `before-first-delta` | inferring | idle | → `cancelled`; sends `chat.retract` |
| `streaming` | streaming | `onDelta` active | → `cancelled`; sends `chat.cancel` |
| `tailing` | done | draining (voice) / instantly finished (text) | → `cancelled`; sends `chat.cancel` |
| `done` | done | done | no-op (terminal) |
| `cancelled` | — | teardown running | no-op (terminal) |

### 4.2 Why `tailing` is kept for text-mode

It is deliberately *not* a voice-only state. Text children also have a "drain phase" — theirs is typically 0 ticks long (`chatStoreSink.onStreamEnd` resolves immediately). Keeping the state uniform avoids branching logic ("if voice then tailing else skip"). It also gives us a named, measurable state for *"LLM is done, only reading out"* which is useful for future analytics — e.g. benchmarking LLM/TTS pairings by measuring how much of total response time is `tailing`.

### 4.3 Drain completion

The transition `tailing → done` happens when all children have resolved their `onStreamEnd` promise. Each child decides what "drained" means for it:

| Child | Resolution criterion |
|---|---|
| `chatStoreSink` | immediate (no drain state) |
| `sentencer` | last segment emitted downstream |
| `pauser` | last inter-sentence pause committed |
| `synth` | last TTS inference promise settled |
| `playback` | queue empty **and** audio source idle |

### 4.4 Cancel during drain

If `cancel()` is called while in `tailing`, the group sets state to `cancelled` and calls `child.onCancel()` on each child. The pending `onStreamEnd` promises are *not* awaited further — children must make `onCancel` idempotent with respect to partial-drain state (a good implementation shares cleanup code between `onCancel` and `teardown`).

### 4.5 Pause / resume

Only playback-level (identical to the previous design): a `pause()` signal is dispatched to all children via the optional `onPause()` hook, but only the `playback` child actually acts on it. `chatStoreSink`, `sentencer`, `pauser`, `synth` implement it as no-op. Valid in `streaming` and `tailing`; no-op elsewhere.

### 4.6 Transition logging (mandatory)

Every state transition emits a console log:

```
[group xyz123ab] created (session=abc, children=chatStoreSink,sentencer,pauser,synth,playback)
[group xyz123ab] before-first-delta → streaming
[group xyz123ab] streaming → tailing
[group xyz123ab] tailing → done
[group xyz123ab] streaming → cancelled (reason=barge-cancel)
[group xyz123ab] paused / resumed
```

where `xyz123ab` is the first 8 chars of the group's `correlationId`.

---

## 5. Token Propagation

### 5.1 The rule

The group's identity is its `correlationId` (UUID4). This token travels with every piece of work:

```ts
sentencer.push(delta, token)
  → segments.forEach(s => s.token = token)
synthesise(segmentText, voice, token)
  → { audio, token }
audioPlayback.enqueue(audio, segment, token)
  → if token !== audioPlayback.currentToken: drop silently
```

Every child holds its own `currentToken` and drops at the head of each callback if the incoming token does not match. This is redundant given the Group's own state check, but cheap and catches late-resolving promises that slipped through.

### 5.2 When a group is cancelled

1. Its `state` flips to `cancelled`.
2. Each child's `onCancel(reason, token)` is called.
3. The playback child, via `onCancel`, bumps `audioPlayback.currentToken` to the new group's token (or `null` if no group follows immediately) and clears the playback queue via `audioPlayback.clearScope(token)`.
4. Any in-flight `synthesise(...)` promise that resolves afterwards is dropped at `enqueue` because its `token` no longer matches.

This makes the previous `mute()` / `mutedEntry` / `resumeFromMute` / `discardMuted` / `session.cancelled` machinery **obsolete**. There is a single source of truth: `child.currentToken === group.token`.

### 5.3 `correlationId` ownership moves to client

**Change**: the client generates `correlationId` at `chat.send`/`chat.edit`/`chat.regenerate` time and sends it to the backend, which adopts it instead of generating its own UUID.

Rationale: the group exists from the instant the user action fires; it needs an identity immediately, not after `STREAM_STARTED` echoes back. This eliminates the "pending cancel" state (cancel before we know the id) and makes every client log entry correlatable with the server side from the first line.

Client-generated IDs are UUID4; collision probability is negligible at our scale.

---

## 6. WebSocket Flows

### 6.1 Happy path (no cancel, no barge) — text or voice

```
Client                                              Backend
  │                                                    │
  │── chat.send { correlation_id=G, content, ... } ──→ │
  │                                                    │── cancel_all_for_user (no-op)
  │                                                    │── persist user message (with correlation_id=G)
  │ ←── CHAT_MESSAGE_CREATED { correlation_id=G } ────│
  │                                                    │── run_inference (acquires per-user lock)
  │ ←── CHAT_STREAM_STARTED { correlation_id=G } ─────│
  │   group: before-first-delta                        │
  │                                                    │
  │ ←── CHAT_CONTENT_DELTA { correlation_id=G, δ } ───│
  │   group.onDelta(δ):                                │
  │     state = before-first-delta → streaming        │
  │     for child in children: child.onDelta(δ, G)    │
  │                                                    │
  │ ←── CHAT_STREAM_ENDED { correlation_id=G } ───────│
  │   group.onStreamEnd():                             │
  │     state = streaming → tailing                    │
  │     await Promise.allSettled(child.onStreamEnd(G)) │
  │     state = tailing → done                         │
```

For text-chat, the `tailing → done` transition happens in the same tick — `chatStoreSink.onStreamEnd` resolves immediately.

### 6.2 Case (a) — Barge before first delta (voice only)

User speaks while LLM is thinking; no content delta has been rendered yet.

```
Client                                              Backend
  │ ... chat.send(G1); CHAT_STREAM_STARTED(G1) ...    │
  │   group1.state: before-first-delta                │
  │                                                    │
  │   [VAD speech-start → pause() → STT runs]          │
  │   STT confirms transcript "Klassische Mechanik"    │
  │   group1.cancel('barge-retract')                   │
  │                                                    │
  │── chat.retract { correlation_id=G1 } ─────────────→│
  │                                                    │── _cancel_events[G1].set()
  │                                                    │── repo.delete_message(user_msg_of_G1)
  │ ←── CHAT_MESSAGE_DELETED { correlation_id=G1 } ───│
  │   chatStore.deleteMessage(...)                     │
  │                                                    │
  │── chat.send { correlation_id=G2, content=new } ──→ │
  │   group2 = new ResponseTaskGroup(G2)               │
  │   group1 already cancelled; nothing to collide     │
```

### 6.3 Case (b) — Cancel during streaming (text or voice)

For voice, triggered by STT confirming barge. For text, triggered by the user clicking the stop button.

```
Client                                              Backend
  │ ... group1.state: streaming ...                   │
  │                                                    │
  │   group1.cancel('barge-cancel' | 'user-stop')     │
  │                                                    │
  │── chat.cancel { correlation_id=G1 } ──────────────→│
  │                                                    │── _cancel_events[G1].set()
  │                                                    │── inference loop breaks at next check
  │                                                    │── persists partial content (status=aborted)
  │ ←── CHAT_STREAM_ENDED { correlation_id=G1,       │
  │                          status=aborted } ────────│
  │   group1 already cancelled; event ignored          │
```

Whether a new `chat.send` follows immediately (voice barge) or not (text stop button) is up to the caller — the group cancel pathway is identical.

### 6.4 Case (c) — Cancel during tailing (voice only)

LLM stream is done, but synth/playback are still draining. Identical to case (b) from the group's perspective: `cancel()` fires, group transitions to `cancelled`, audio stops immediately. The backend's `_cancel_events[G1]` may already have been removed (the run is complete), so `chat.cancel` becomes a no-op on the backend — harmless.

### 6.5 Regenerate or edit during streaming (text or voice)

User clicks "Regenerate" or edits a prior message while group1 is active.

```
Client                                              Backend
  │ ... group1.state: streaming ...                   │
  │                                                    │
  │   const G2 = crypto.randomUUID()                   │
  │   group2 = new ResponseTaskGroup(G2)               │
  │   registerActiveGroup(group2):                     │
  │     → group1.cancel('superseded')                  │
  │       → sends chat.cancel(G1)                      │
  │     → activeGroup = group2                         │
  │── chat.cancel { correlation_id=G1 } ──────────────→│── cancel G1 inference
  │── chat.regenerate { correlation_id=G2, ... } ────→│── start G2 inference
```

Order of `chat.cancel` and `chat.regenerate` matters — the client sends them in that order so the backend sees the cancel first. Both messages flow on the same WebSocket, so ordering is preserved.

### 6.6 STT returns empty (misfire after pause committed)

```
  group1.state: streaming (paused via onPause on playback)
    → STT returns ""
    → decideSttOutcome = 'resume'
    → group1.resume()
    → playback.onResume() → audio flows again
```

No network traffic.

### 6.7 Stale STT result (newer barge began while STT was running)

Handled exactly as today — `decideSttOutcome = 'stale'`, drop the result. The group system does not need to know.

---

## 7. Backend Changes

### 7.1 Accept client-provided `correlation_id` in all response-starting handlers

**File**: `backend/modules/chat/_handlers_ws.py`

Each of the following handlers gets the same one-line change:

- `handle_chat_send`
- `handle_chat_edit`
- `handle_chat_regenerate`
- `handle_chat_incognito_send` (if present as a separate path)

```python
correlation_id = data.get("correlation_id") or str(uuid4())
# (previously: correlation_id = str(uuid4()))
```

Backwards-compatible — clients that do not send `correlation_id` continue to receive a server-generated one. Non-chat flows (memory consolidation, journal extraction) are unaffected.

### 7.2 Persist `correlation_id` on the user message

**File**: `backend/modules/chat/_repository.py` and the user-message Pydantic model.

Add a nullable field `correlation_id: str | None = None` to the user-message document and write it when persisting in `handle_chat_send` / `handle_chat_edit` / `handle_chat_regenerate`. Add an index on `(user_id, correlation_id)` applied at startup (idempotent `create_index`).

Rationale: needed by `handle_chat_retract` to locate the user message to delete. Keeping it persistent (rather than an in-memory dict like `_cancel_events`) avoids races on reconnect/restart and aligns with the "no DB wipes" policy — existing documents deserialise fine with `correlation_id=None`.

### 7.3 New handler: `handle_chat_retract`

**File**: `backend/modules/chat/_handlers_ws.py`

```python
async def handle_chat_retract(user_id: str, data: dict) -> None:
    """Handle chat.retract — cancel in-flight inference and delete its user message."""
    correlation_id = data.get("correlation_id")
    if not correlation_id:
        return

    # 1. Signal cancel (identical to handle_chat_cancel)
    if correlation_id in _cancel_events:
        _cancel_events[correlation_id].set()

    # 2. Lookup user_message_id via correlation_id
    user_message_id = await chat_repo.user_message_by_correlation(user_id, correlation_id)
    if not user_message_id:
        logger.info("retract: no user message for correlation_id=%s", correlation_id)
        return

    # 3. Delete and broadcast
    await chat_repo.delete_message(user_id, user_message_id)
    await event_bus.publish(Topics.CHAT_MESSAGE_DELETED, {
        "user_id": user_id,
        "message_id": user_message_id,
        "correlation_id": correlation_id,
    })
```

**Wiring**: `backend/ws/router.py`:

```python
elif msg_type == "chat.retract":
    await handle_chat_retract(user_id, data)
```

### 7.4 No change to `handle_chat_cancel`

Already correct: sets `_cancel_events[correlation_id]`, no persistence side-effects. Reused as-is by both text-chat and voice-chat paths.

---

## 8. Frontend Changes

### 8.1 New module: `responseTaskGroup.ts`

**File (new)**: `frontend/src/features/chat/responseTaskGroup.ts`

Exports the `GroupChild` interface, the `ResponseTaskGroup` interface, the `GroupState` / `CancelReason` types, the factory `createResponseTaskGroup(deps)`, and the registry functions `registerActiveGroup`, `getActiveGroup`, `clearActiveGroup`.

No imports from `voice/` or `chat/store`. Pure lifecycle machinery. Testable in isolation with mock children.

### 8.2 New children modules (one file each)

```
frontend/src/features/chat/children/chatStoreSink.ts
frontend/src/features/voice/children/sentencer.ts
frontend/src/features/voice/children/pauser.ts
frontend/src/features/voice/children/synth.ts
frontend/src/features/voice/children/playback.ts
```

Each file exports a factory returning a `GroupChild`:

```ts
// chatStoreSink.ts
export function createChatStoreSink(opts: {
  sessionId: string
  correlationId: string
  chatStore: ChatStoreApi
}): GroupChild {
  return {
    name: 'chatStoreSink',
    onDelta(delta, token) {
      if (token !== opts.correlationId) return
      opts.chatStore.appendStreamingContent(delta)
    },
    onStreamEnd(token) {
      if (token !== opts.correlationId) return
      opts.chatStore.finalizeStreaming()   // resolves immediately
    },
    onCancel(_reason, token) {
      if (token !== opts.correlationId) return
      opts.chatStore.cancelStreaming()
    },
    teardown() {},
  }
}
```

The voice children follow the same pattern. They encapsulate today's sentencer/synth/playback logic behind the `GroupChild` boundary, adding token checks at their rims.

Voice children wire up to each other via constructor injection for voice-internal events (sentencer → pauser → synth for segment-boundary flow). The Group itself is unaware of this sub-channel.

### 8.3 Children factory — the one place mode-awareness lives

A single factory in `ChatView.tsx` (or a colocated helper) decides which children go into the group:

```ts
function buildChildren(
  correlationId: string,
  sessionId: string,
  mode: 'text' | 'voice',
): GroupChild[] {
  const children: GroupChild[] = [
    createChatStoreSink({ correlationId, sessionId, chatStore }),
  ]
  if (mode === 'voice') {
    const sentencer = createSentencer({ correlationId, ... })
    const pauser    = createPauser({ correlationId, sentencer, ... })
    const synth     = createSynth({ correlationId, sentencer, pauser, ... })
    const playback  = createPlayback({ correlationId, audioPlayback, ... })
    children.push(sentencer, pauser, synth, playback)
  }
  return children
}
```

This is the only `if (mode === 'voice')` in the new architecture. Everything else is agnostic.

### 8.4 `ChatView.tsx` — handleSend / handleCancel / handleRegenerate / handleEdit

**Old `handleSend`** (simplified):
```ts
sendMessage({ type: 'chat.send', content, ... })
// correlation_id returned later via CHAT_MESSAGE_CREATED
```

**New `handleSend`:**
```ts
const correlationId = crypto.randomUUID()
const group = createResponseTaskGroup({
  correlationId,
  sessionId,
  userId,
  children: buildChildren(correlationId, sessionId, mode),
  sendWsMessage: sendMessage,
  logger,
})
registerActiveGroup(group)   // cancels previous group if present
sendMessage({ type: 'chat.send', correlation_id: correlationId, content, ... })
```

**New `handleCancel`:**
```ts
getActiveGroup()?.cancel('user-stop')
// cancel() internally sends chat.cancel or chat.retract depending on state
```

`handleRegenerate` and `handleEdit` follow the same pattern — new UUID, new group, `registerActiveGroup` auto-cancels the predecessor with reason `'superseded'`.

**Removed effects:**
- `useEffect([isStreaming])` — delta routing is now a group concern
- `useEffect([streamingContent, isStreaming])` — ditto
- Direct calls to `cancelStreamingAutoRead()` in `ChatView.tsx` — redundant

### 8.5 `useChatStream.ts` — event routing

```ts
case 'CHAT_CONTENT_DELTA': {
  const g = getActiveGroup()
  if (!g || g.id !== event.correlation_id) {
    log.debug('drop delta (no matching group)', event.correlation_id)
    return
  }
  g.onDelta(event.payload.delta)
  break
}

case 'CHAT_STREAM_ENDED': {
  const g = getActiveGroup()
  if (!g || g.id !== event.correlation_id) return
  g.onStreamEnd()
  break
}

case 'CHAT_MESSAGE_DELETED': {
  chatStore.deleteMessage(event.payload.message_id)
  // group already cancelled internally
  break
}
```

The `chatStore` is no longer directly written for streaming state from `useChatStream` — that is `chatStoreSink`'s job.

### 8.6 `audioPlayback` — token-aware

**File**: `frontend/src/features/voice/infrastructure/audioPlayback.ts`

Replace `muted` / `mutedEntry` / `mutedOffsetSec` / `pendingResumeOffsetSec` with:

```ts
private currentToken: string | null = null
private paused = false
```

API changes:

```ts
setCurrentToken(token: string | null): void
enqueue(audio, segment, token: string): void    // drops on token mismatch
pause(): void                                    // gates output, keeps queue
resume(): void                                   // ungates; drain continues
clearScope(token: string): void                  // drops queue iff token matches
```

Removed: `mute`, `resumeFromMute`, `discardMuted`, `isMuted`, `skipCurrent`. Tests updated accordingly.

### 8.7 `useConversationMode.ts` — STT verbs

```ts
// executeBarge (tentative pause)
getActiveGroup()?.pause()
tentativeRef.current = true

// transcribeAndSend — outcome 'confirm'
getActiveGroup()?.cancel('barge-cancel')   // group picks retract vs cancel
onSendRef.current(transcript)              // creates a new group via handleSend

// outcome 'resume'
getActiveGroup()?.resume()

// outcome 'stale'  (unchanged — drop)
```

All call sites of `audioPlayback.mute` / `resumeFromMute` / `discardMuted` disappear.

### 8.8 Phase machine — derive, don't write

The `useConversationMode` phase machine stops using `setInterval(150ms)` polling `audioPlayback.isPlaying()`. Instead, `phase` is computed from `activeGroup.state` + VAD flags. Single writer, no write-write races.

### 8.9 Removals summary

- `streamingAutoReadControl.activeSession` (module-level slot)
- `cancelStreamingAutoRead()` public export (replaced by `getActiveGroup()?.cancel('user-stop')`)
- `audioPlayback.mute / resumeFromMute / discardMuted / isMuted / skipCurrent`
- Two flanky `useEffect`s in `ChatView.tsx`
- 150 ms playback poller in `useConversationMode`

---

## 9. Logging & Diagnostics

All group-related logs use the prefix `[group <hash8>]` where `<hash8>` is the first 8 characters of the correlationId. All child-of-group logs carry the same prefix.

Transitions logged at `info`:

```
[group xyz123ab] created (session=abc, children=chatStoreSink,sentencer,pauser,synth,playback)
[group xyz123ab] before-first-delta → streaming
[group xyz123ab] streaming → tailing
[group xyz123ab] tailing → done
[group xyz123ab] <state> → cancelled (reason=<reason>)
[group xyz123ab] paused / resumed
```

Child logs (also at `info`, prefixed):

```
[chatStoreSink xyz123ab] delta +17 chars (total=842)
[TTS-infer     xyz123ab] start "..."
[TTS-infer     xyz123ab] done  "..." 412ms
[TTS-play      xyz123ab] start "..."
[pauser        xyz123ab] pause 180ms after segment 3
```

Drop events (at `debug`):

```
[group xyz123ab] drop CONTENT_DELTA (group cancelled)
[audioPlayback] drop chunk (token mismatch: got=xyz123ab, current=pqr456cd)
[chatStoreSink pqr456cd] drop delta (token mismatch)
```

Text-chat gets the same grep-friendly treatment as voice — every delta, every state change, every drop event has a correlation prefix. Debug transcripts no longer need bespoke tooling.

---

## 10. Test Plan

### 10.1 Unit tests (new)

**`responseTaskGroup.test.ts`** — the heart:
- State-transition matrix: `before-first-delta → streaming → tailing → done`; `cancelled` from each state.
- `cancel()` sends `chat.retract` iff state was `before-first-delta`, otherwise `chat.cancel`.
- `onDelta` in `before-first-delta` triggers transition to `streaming` before dispatching.
- `onStreamEnd` awaits `Promise.allSettled(child.onStreamEnd)` before `done`.
- `cancel()` during `tailing` abandons pending drain promises (not awaited).
- `pause` / `resume` only valid in `streaming` / `tailing`.
- `registerActiveGroup` cancels the predecessor with reason `'superseded'`.
- Terminal states (`done`, `cancelled`) no-op further calls.
- Defence-in-depth: group dispatches even with wrong token; child's own check catches it.

**`chatStoreSink.test.ts`** (new, small): token match → append; token mismatch → drop; cancel → `cancelStreaming`.

**`audioPlayback.test.ts`** (rewritten):
- Token-aware `enqueue` drops on mismatch.
- `pause` / `resume` gate output without clearing queue.
- `clearScope(token)` only when token matches.
- Removed: everything around `mute` / `resumeFromMute` / `discardMuted`.

**`bargeDecision.test.ts`** — unchanged.

### 10.2 Integration tests (new)

**Voice-chat (from original spec):**
- **Case (a)** — barge in `before-first-delta`: `chat.retract` sent, `CHAT_MESSAGE_DELETED` dispatched, store has only new user message.
- **Case (b)** — barge in `streaming`: `chat.cancel(G1)` sent, old user message preserved, partial assistant content preserved, new group for new transcript.
- **Case (c)** — barge in `tailing`: audio stops immediately, full assistant content preserved, new group.
- **Misfire after pause**: VAD fires, group pauses, STT empty, audio resumes.
- **Stale STT**: two rapid barges; first STT finishes last; stale dropped.

**Text-chat (new):**
- **Cancel during streaming**: stop button while deltas arrive. Assert `chat.cancel` sent, `streamingContent` cleared, no further deltas accepted.
- **Retract during `before-first-delta`**: stop button before first delta. Assert `chat.retract` sent, `CHAT_MESSAGE_DELETED` received, user message removed from store.
- **Regenerate during streaming**: trigger regenerate while streaming. Assert old group → `cancelled ('superseded')`, new group with new UUID, no cross-contamination.
- **Edit during streaming**: analogous.
- **Reconnect with stale group**: WS drop + reconnect; catchup delivers events for old correlation_id; assert drops (group already terminal).

### 10.3 Manual verification on real device

Per the project convention — every spec ships with a manual-test section run against actual hardware before the feature is considered done.

**Voice (from original spec):**

1. Enter conversation mode. Ask a long question ("Erzähle mir die Geschichte der Quantenmechanik"). Wait for TTS to start. **Interrupt while TTS plays** — verify audio stops within ~500 ms, new response starts for the interrupting utterance.
2. Same setup, **interrupt while the model is still thinking** (before first token). Verify the original user message disappears from the chat, replaced by the new one.
3. Same setup, **interrupt right at the end** (after `CHAT_STREAM_ENDED` but while TTS is still playing). Verify the full assistant message is preserved; audio stops.
4. **Misfire test**: cough or knock during TTS; verify audio briefly pauses and resumes.
5. **Rapid double-barge**: interrupt, then interrupt again within 1 s. Verify only the latest barge wins.
6. **Multi-tab**: open the same account in two tabs, both in conversation mode. Send from tab A, send from tab B while A is thinking. Verify A's stream is cancelled cleanly (no stuck TTS, no zombie state).

**Text-chat (new):**

7. Text-chat, send long question, click stop button while deltas stream. Audio off — nothing should play. Assistant bubble stops growing; no zombie deltas.
8. Text-chat, send question, click stop **before** first delta arrives. User message disappears from chat history.
9. Text-chat, response streaming, click "Regenerate" on the user message. Previous response cleanly cancelled, new response begins with a fresh correlation ID.
10. **Mode switch mid-stream**: start text response, switch to voice mode while streaming. Verify response continues as text (no TTS kicks in mid-stream). Next user message then uses voice.
11. **Log audit**: run two complete responses (1× text, 1× voice), filter console for `[group `. Both should be fully reconstructable from the logs alone, including state transitions and child activity.

---

## 11. Migration Path

Ordered so that every step leaves the app in a working state. Steps 1–4 are additive and can be parallelised; step 5 is the "flip the switch" moment.

| # | Step | Effort | Result |
|---|------|--------|--------|
| 1 | **Backend**: `correlation_id` field on user message + `(user_id, correlation_id)` index; `correlation_id` acceptance in all 4 chat handlers | ~1 h | Backwards-compatible; old clients still work |
| 2 | **Frontend**: `audioPlayback` token-aware. Temporary shim: old `mute` / `resumeFromMute` / `discardMuted` delegate internally to `pause` / `clearScope` | ~2 h | All voice tests green; no UX change |
| 3 | **Frontend**: `responseTaskGroup.ts` + `chatStoreSink.ts`. Standalone, unit-tested, not yet wired | ~3 h | Module exists; no call sites yet |
| 4 | **Frontend**: voice children (`sentencer.ts`, `pauser.ts`, `synth.ts`, `playback.ts`) extracted from existing code behind the `GroupChild` interface | ~3 h | All existing tests still green; internal refactor only |
| 5 | **Frontend**: `ChatView` + `useChatStream` wire groups. Phase machine derived. `useConversationMode` calls group verbs. Old effects and cancel paths removed | ~4 h | **Voice barging is new. Text-chat flows through groups.** |
| 6 | **Backend**: `handle_chat_retract` + router wiring | ~1.5 h | Retract path available |
| 7 | **Frontend**: enable retract path in `group.cancel()` (sends `chat.retract` when state was `before-first-delta`) | ~30 min | Case (a) barge-before-delta retracts instead of aborts |
| 8 | **Integration tests + manual verification** | ~4 h | Feature complete |
| 9 | **Cleanup**: remove shim from step 2; kill remaining `mute`-API residue | ~30 min | Code clean |

**Total**: ~20 h — one long session or two compact ones.

---

## 12. Open Questions

None blocking implementation. Deferred:

- Whether the client should generate `correlation_id` for non-chat paths (memory consolidation, journal extraction) is orthogonal to this spec.
- Per-session group registry (rather than per-user) is an explicit non-goal — see project memory on single-session UX.

---

## Appendix A — Mapping of current defects to spec

| Defect (see §1.1) | Resolved by |
|-----------------|-------------|
| 1. `audioPlayback` correlation-blind | §5 token propagation; §8.6 token-aware `enqueue` |
| 2. `useEffect` edge race | §8.4 group owns lifecycle; flanky effects removed |
| 3. Backend cancel piggy-backed on new send | §7.4 + §8.7 explicit `chat.cancel` / `chat.retract` inside `group.cancel()` |
| 4. `streamingContent` reset masks race | §8.2 content lives on `chatStoreSink`, not on the store directly |
| 5. Phase machine multi-writer | §8.8 phase derived from group state |
| Text-chat: undefined response ownership (§1.2) | §2 Group is the single owner; §3.3 registry enforces exactly one active per user |
| Text-chat: pre-STARTED cancel window (§1.2) | §5.3 client-generated `correlation_id` from the first user action |

---

## Appendix B — Glossary

- **Group**: short for `ResponseTaskGroup` — the unit of work for one assistant reply.
- **Token**: synonymous with `correlationId` when discussed in the context of routing and drop-on-mismatch.
- **Child**: a module implementing the `GroupChild` interface, subscribed to Group lifecycle events.
- **Tailing**: LLM stream ended, children still draining. Zero-duration for text-chat, non-trivial for voice-chat (TTS playback).
- **Retract**: cancel a group and delete its user message (used for barge-before-delta).
- **Cancel**: cancel a group; keep any persisted partial assistant content.
- **Superseded**: cancel reason used when a new group displaces a running one (regenerate, edit, or new send during streaming).

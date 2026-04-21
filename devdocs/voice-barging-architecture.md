# Voice Barging Architecture — Response Task Group

**Status**: Design spec, pre-implementation
**Supersedes**: Tentative-Barge pattern (`audioPlayback.mute()` + `session.cancelled`)
**Owner**: Chris

---

## 1. Problem Statement

The current voice-barging pipeline has erratic symptoms:

1. **Barge sometimes fails to interrupt** — the user speaks, gets transcribed, but the running TTS keeps talking over them.
2. **"Zombie" TTS after confirm** — after `cancelStreamingAutoRead()` fires, new audio chunks still arrive and play.
3. **Interleaved prompts / duplicated content** — the chat view shows `[prompt1][prompt2][resp1][resp2]` or a response echoes the previous one.

Diagnosis (see session transcript, April 2026): five latent defects converge:

| # | Defect | Evidence |
|---|--------|----------|
| 1 | `audioPlayback.enqueue()` has no correlation/session gate | `audioPlayback.ts:60` |
| 2 | `useEffect([isStreaming])` reacts to edges — batched state updates can swallow them | `ChatView.tsx:800` |
| 3 | Backend cancel is piggy-backed on the next `chat.send`; no explicit cancel at barge-confirm time | `useConversationMode.ts:306` → `chatApi.send` |
| 4 | `chatStore.streamingContent` reset masks the race — new session starts without a live sentencer if the `isStreaming` edge was missed | `chatStore.ts:115` |
| 5 | Phase machine has three writers (explicit `setPhase`, streaming-state effect, 150 ms playback poller) that can flip one another | `useConversationMode.ts:641`, `:664` |

Symptomatic patches (e.g. "always set `muted = true` in `mute()`") address one symptom at a time and leave the architecture fragile.

---

## 2. Mental Model: Response Task Group

A **Response Task Group** is a named, cancellable unit that owns everything produced on behalf of one assistant reply:

```
ResponseTaskGroup(correlationId)
├── WS listener (filters on correlationId)
├── Sentencer            (eats deltas → emits segments)
├── Synth chain          (eats segments → emits audio buffers)
└── Playback scope       (eats buffers → plays on speakers)
```

Invariants:

* **At most one group is active per user at a time.** Creating a new group cancels the previous one. Mirrors the backend's per-user inference lock.
* **Every chunk that enters any child carries the group token.** Children silently drop work whose token does not match the current group. When the group is cancelled, all in-flight work falls on the floor at the next boundary.
* **Group lifecycle is explicit and logged.** No state transition happens as a side-effect of something else.

The STT path lives **outside** the group and speaks to it through a small verb set:

| Trigger | Group call | Rationale |
|---------|-----------|-----------|
| VAD `onSpeechStart` (past 150 ms misfire window) | `group.pause()` | Tentative — might be real, might be noise |
| STT returns non-empty transcript | `group.cancel()` + new `chat.send` | Confirmed barge |
| STT returns empty transcript | `group.resume()` | Misfire — unpause |
| VAD `onMisfire` before pause committed | (no-op on group) | Misfire cleared before pause fired |

---

## 3. State Machine

```
          ┌─────────────────────┐
          │  before-first-delta │
          └──────────┬──────────┘
     first CONTENT_DELTA received
                     │
                     ▼
          ┌─────────────────────┐
          │      streaming      │
          └──────────┬──────────┘
            STREAM_ENDED received
            (LLM done, but synth/playback may still be draining)
                     │
                     ▼
          ┌─────────────────────┐
          │       tailing       │
          └──────────┬──────────┘
       synth queue empty AND
       playback queue empty AND
       playback source idle
                     │
                     ▼
          ┌─────────────────────┐
          │        done         │
          └─────────────────────┘

At any state:
            cancel() invoked
                     │
                     ▼
          ┌─────────────────────┐
          │      cancelled      │
          └─────────────────────┘
```

### State semantics

| State | LLM | Sentencer | Synth | Playback | On `cancel()` |
|-------|-----|-----------|-------|----------|---------------|
| `before-first-delta` | inferring | idle | idle | idle | → `cancelled`; emits `chat.retract` (case a) |
| `streaming` | streaming | active | active | active | → `cancelled`; emits `chat.cancel` (case b) |
| `tailing` | done | flushing | active | active | → `cancelled`; emits `chat.cancel` (case c) |
| `done` | done | done | done | done | no-op (terminal) |
| `cancelled` | cancelling | dropping | dropping | dropping | no-op (terminal) |

### Pause / resume

`pause()` and `resume()` only affect the **playback scope** — they do not stop synthesis or the LLM stream. The synth chain continues to fill the playback queue; only the audio output is gated. Valid in `streaming` and `tailing`; no-op elsewhere.

### Transition logging (mandatory)

Every state transition emits a console log:

```
[group xyz123ab] before-first-delta → streaming
[group xyz123ab] streaming → tailing
[group xyz123ab] tailing → done
[group xyz123ab] streaming → cancelled (reason=barge-confirm)
```

where `xyz123ab` is the first 8 chars of the group's `correlationId`. `reason` accompanies every `cancelled` transition.

---

## 4. Token Propagation ("maximal")

The group's identity is its `correlationId` (UUID). This token travels with every piece of work:

```ts
sentencer.push(delta, token)
  → segments.forEach(s => s.token = token)
synthesise(segmentText, voice, token)
  → { audio, token }
audioPlayback.enqueue(audio, segment, token)
  → if token !== audioPlayback.currentToken: drop silently
```

When a group is cancelled:

1. Its `state` flips to `cancelled`.
2. `audioPlayback.currentToken` is bumped to a sentinel (`null` or the new group's token).
3. The playback queue is cleared (`stopAll()` equivalent, scoped).
4. Any in-flight `synthesise(...)` promise that resolves afterwards is dropped at `enqueue` because its `token` no longer matches.

This makes the previous `mute()` / `mutedEntry` / `resumeFromMute` / `discardMuted` / `session.cancelled` machinery **obsolete**. There is a single source of truth: `audioPlayback.currentToken === group.token`.

Logs from the synth / playback path are prefixed with the group hash:

```
[TTS-infer xyz123ab] start "..." 
[TTS-infer xyz123ab] done  "..." 412ms
[TTS-play  xyz123ab] start "..."
[TTS-play  xyz123ab] done  "..."
```

---

## 5. correlationId Ownership

**Change**: the client generates `correlationId` at `chat.send` time and sends it to the backend, which adopts it instead of generating its own UUID.

Rationale: the group exists from the instant `chat.send` is called; it needs an identity immediately, not after `STREAM_STARTED` echoes back. This eliminates the "pending cancel" state (cancel before we know the id) and makes every client log entry correlatable with the server side from the first line.

Backend change: `_handlers_ws.py:handle_chat_send` accepts an optional `correlation_id` field; if absent, it still generates one (backwards-compatible for non-voice paths that have not been updated).

Client-generated IDs are UUID4 — collision probability is negligible for our scale.

---

## 6. WebSocket Flows

### 6.1 Happy path (no barge)

```
Client                                              Backend
  │                                                    │
  │── chat.send { correlation_id=G, content, ... } ──→ │
  │                                                    │── cancel_all_for_user (no-op) 
  │                                                    │── persist user message
  │ ←── CHAT_MESSAGE_CREATED { correlation_id=G } ────│
  │   group.bindMessageId(...)                         │
  │                                                    │── run_inference (acquires per-user lock)
  │ ←── CHAT_STREAM_STARTED { correlation_id=G } ─────│
  │   group: before-first-delta                        │
  │                                                    │
  │ ←── CHAT_CONTENT_DELTA { correlation_id=G, δ } ───│
  │   group.onDelta(δ):                                │
  │     state = before-first-delta → streaming        │
  │     sentencer.push(δ)                              │
  │     [→ segments → synth → playback]                │
  │                                                    │
  │ ←── CHAT_STREAM_ENDED { correlation_id=G } ───────│
  │   group.onStreamEnd():                             │
  │     state = streaming → tailing                    │
  │     sentencer.flush()                              │
  │                                                    │
  │   [synth drains, playback drains]                  │
  │   group.state = tailing → done                     │
```

### 6.2 Case (a) — Barge before first delta

User speaks while LLM is thinking; no content delta has been rendered yet.

```
Client                                              Backend
  │ ... chat.send(G1); CHAT_STREAM_STARTED(G1) ...    │
  │   group1.state: before-first-delta                │
  │                                                    │
  │   [VAD speech-start → pause() → STT runs]          │
  │                                                    │
  │   STT confirms transcript "Klassische Mechanik"    │
  │   group1.cancel(reason=barge-retract)              │
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

### 6.3 Case (b) — Barge during streaming

User speaks while content is being rendered.

```
Client                                              Backend
  │ ... group1.state: streaming ...                   │
  │                                                    │
  │   [VAD speech-start → group1.pause() → STT]        │
  │   STT confirms → group1.cancel(reason=barge)       │
  │                                                    │
  │── chat.cancel { correlation_id=G1 } ──────────────→│
  │                                                    │── _cancel_events[G1].set()
  │                                                    │── inference loop breaks at next check
  │                                                    │── persists partial content (status=aborted)
  │ ←── CHAT_STREAM_ENDED { correlation_id=G1,       │
  │                          status=aborted } ────────│
  │   group1 already cancelled; event ignored          │
  │                                                    │
  │── chat.send { correlation_id=G2, content=new } ──→ │
  │                                                    │── waits for per-user lock from G1's finally
  │                                                    │── starts G2
  │   group2 = new ResponseTaskGroup(G2)               │
```

### 6.4 Case (c) — Barge during tailing

LLM stream is done, but synth/playback are still draining.

Identical to case (b) from the group's perspective: `cancel()` fires, group transitions to `cancelled`, audio stops immediately. The only difference is that the backend's `_cancel_events[G1]` may already have been removed (the run is complete), so `chat.cancel` becomes a no-op on the backend — harmless.

### 6.5 STT returns empty (misfire after pause committed)

```
  group1.state: streaming (paused)
    → STT returns ""
    → decideSttOutcome = 'resume'
    → group1.resume()
    → state returns to streaming; audio flows again
```

No network traffic.

### 6.6 Stale STT result (newer barge began while STT was running)

Handled exactly as today — `decideSttOutcome = 'stale'`, drop the result. The group system does not need to know.

---

## 7. Backend Changes

### 7.1 Accept client-provided `correlation_id` in `chat.send`

**File**: `backend/modules/chat/_handlers_ws.py`

```python
async def handle_chat_send(user_id: str, data: dict, *, connection_id: str | None = None) -> None:
    ...
    correlation_id = data.get("correlation_id") or str(uuid4())
    # (previously: correlation_id = str(uuid4()))
```

The same change applies to any other `handle_chat_*` that starts an inference (`chat.edit`, `chat.regenerate`, `chat.incognito.send`), so the client always controls the id for its own groups. This is a ~4-line change per handler.

### 7.2 New handler: `handle_chat_retract`

**File**: `backend/modules/chat/_handlers_ws.py`

Analogue of `handle_chat_regenerate`, but removes the **user** message instead of the last assistant message:

```python
async def handle_chat_retract(user_id: str, data: dict) -> None:
    """Handle chat.retract — cancel in-flight inference AND delete its user message."""
    correlation_id = data.get("correlation_id")
    if not correlation_id:
        return
    # 1. Signal cancel (same as handle_chat_cancel)
    if correlation_id in _cancel_events:
        _cancel_events[correlation_id].set()
    # 2. Find and delete the user message that belongs to this correlation_id
    #    (persisted by handle_chat_send with the same correlation_id on CHAT_MESSAGE_CREATED)
    # 3. Publish CHAT_MESSAGE_DELETED so all tabs drop the optimistic/persisted entry
```

Wiring: add to the `chat.*` dispatch table (wherever `chat.cancel` is registered — follow that pattern).

**Note**: the backend must record the mapping `correlation_id → user_message_id` when it persists the user message. Today this mapping is implicit (both share the same session and timing); we need to make it explicit. Candidate: a field on the user message, or a small in-memory dict like `_cancel_events`. Decide during implementation; the spec is neutral.

### 7.3 No change to `handle_chat_cancel`

Already correct: sets `_cancel_events[correlation_id]`, no side-effects on persistence. Reused as-is.

---

## 8. Frontend Changes

### 8.1 New module: `ResponseTaskGroup`

**File (new)**: `frontend/src/features/chat/responseTaskGroup.ts`

A module-level registry holds at most one active group per session (keyed by `sessionId`). The registry exposes:

```ts
interface ResponseTaskGroup {
  readonly id: string                    // correlationId
  readonly sessionId: string
  readonly state: GroupState             // see §3
  readonly hasReceivedContent: boolean

  pause(): void
  resume(): void
  cancel(reason: CancelReason): void     // 'barge-retract' | 'barge-cancel' | 'user-stop' | 'teardown'

  onDelta(delta: string): void           // called by useChatStream on CHAT_CONTENT_DELTA
  onStreamEnd(): void                    // called on CHAT_STREAM_ENDED
}

type GroupState = 'before-first-delta' | 'streaming' | 'tailing' | 'done' | 'cancelled'
```

Lifecycle:

```ts
// Created at chat.send time
const group = createResponseTaskGroup({
  correlationId: clientGeneratedUuid,
  sessionId,
  // dependencies injected (tts, sentencer factory, audioPlayback)
})
registerActiveGroup(group)   // cancels any previous group for the same user first

// At cancel:
group.cancel('barge-cancel')
// If state was 'before-first-delta' → group itself issues chat.retract
// Otherwise                         → group itself issues chat.cancel
// Then: tearDownChildren(), bump audioPlayback.currentToken, log transition
```

### 8.2 `audioPlayback` — token-aware

**File**: `frontend/src/features/voice/infrastructure/audioPlayback.ts`

Replace the `muted` / `mutedEntry` / `mutedOffsetSec` / `pendingResumeOffsetSec` machinery with two fields:

```ts
private currentToken: string | null = null
private paused = false
```

API changes:

```ts
setCurrentToken(token: string | null): void     // bump when a new group activates
enqueue(audio, segment, token: string): void    // drops if token !== currentToken
pause(): void                                    // gate the output; keep the queue
resume(): void                                   // ungate; drain continues
clearScope(token: string): void                  // drop queue if token matches (cancel path)
```

Removed: `mute`, `resumeFromMute`, `discardMuted`, `isMuted`, `skipCurrent`. Tests updated accordingly.

### 8.3 Remove `streamingAutoReadControl.activeSession`

The module-level `activeSession` slot is replaced by the Response Task Group registry. `cancelStreamingAutoRead()` becomes `activeGroup?.cancel('user-stop')`.

### 8.4 `ChatView.tsx` — group creation and wiring

* `handleSend` generates a UUID4 and creates the group **before** sending:
  ```ts
  const correlationId = crypto.randomUUID()
  const group = createResponseTaskGroup({ correlationId, sessionId, ... })
  registerActiveGroup(group)
  sendMessage({ type: 'chat.send', correlation_id: correlationId, ... })
  ```
* The two flanky `useEffect([isStreaming])` and `useEffect([streamingContent, isStreaming])` are removed. Delta feeding and stream-end flushing happen inside the group.
* The `useChatStream` WS handlers route events to `getActiveGroup()?.onDelta(...)` / `.onStreamEnd()` instead of the chat store directly. The chat store still receives user-facing state for UI rendering (`isStreaming`, `streamingContent`), derived from the group.

### 8.5 `useConversationMode.ts` — STT → group verbs

The `executeBarge` / `transcribeAndSend` paths replace their current calls:

```ts
// executeBarge
getActiveGroup()?.pause()
tentativeRef.current = true   // still needed to differentiate resume vs cancel

// transcribeAndSend, outcome 'confirm':
getActiveGroup()?.cancel('barge-cancel')   // group decides retract vs cancel internally
onSendRef.current(transcript)              // creates a new group via handleSend

// outcome 'resume':
getActiveGroup()?.resume()

// outcome 'stale':  (unchanged — drop)
```

`audioPlayback.mute` / `resumeFromMute` / `discardMuted` call sites disappear.

### 8.6 Phase machine — derive, don't write

The `useConversationMode` phase machine stops using `setInterval(150ms)` polling `audioPlayback.isPlaying()`. Instead, `phase` is computed from `activeGroup.state` + VAD flags. Single writer, no write-write races.

---

## 9. Logging & Diagnostics

All group-related logs use the prefix `[group <hash8>]` where `<hash8>` is the first 8 characters of the correlationId. All child-of-group logs carry the same prefix.

Transitions logged at `info`:

```
[group xyz123ab] created (session=abc, from=handleSend)
[group xyz123ab] before-first-delta → streaming
[group xyz123ab] streaming → tailing
[group xyz123ab] tailing → done
[group xyz123ab] <state> → cancelled (reason=<reason>)
[group xyz123ab] paused  / resumed
```

Child logs (also at `info`, prefixed):

```
[TTS-infer xyz123ab] start "..." 
[TTS-play  xyz123ab] start "..."
```

Drop events (at `debug`):

```
[group xyz123ab] drop CONTENT_DELTA (group cancelled)
[audioPlayback] drop chunk (token mismatch: got=xyz123ab, current=pqr456cd)
```

This is enough to reconstruct any session from the console without additional tooling.

---

## 10. Test Plan

### 10.1 Unit tests (new)

* `responseTaskGroup.test.ts` — state-transition matrix, cancel dispatches correct WS message based on state, pause/resume only affect playback.
* `audioPlayback.test.ts` — updated: token-aware enqueue drops mismatched tokens; pause/resume gate output without clearing queue.
* `bargeDecision.test.ts` — unchanged, still a pure function.

### 10.2 Integration tests (new, conversation-mode scoped)

* **Case (a)** — barge in `before-first-delta`:
  Send, stall first delta, barge, confirm STT. Assert: `chat.retract` sent, CHAT_MESSAGE_DELETED dispatched, chatStore has only the new user message, no assistant bubble from G1.
* **Case (b)** — barge in `streaming`:
  Send, let two deltas through, barge, confirm STT. Assert: `chat.cancel(G1)` sent, old user message remains, partial assistant content preserved, new group created for new transcript.
* **Case (c)** — barge in `tailing`:
  Send, let stream end, playback starts, barge, confirm STT. Assert: audio stops immediately, full assistant content preserved, new group created.
* **Misfire after pause**: VAD fires, group pauses, STT returns empty. Assert: audio resumes, group still in `streaming`.
* **Stale STT**: two rapid barges, first STT finishes last. Assert: stale result dropped, second barge decides.

### 10.3 Manual verification on real device

Per the project convention: every spec ships with a manual-test section run against the actual hardware before the feature is considered done.

1. Enter conversation mode. Ask a long question ("Erzähle mir die Geschichte der Quantenmechanik"). Wait for TTS to start. **Interrupt while TTS plays** — verify audio stops within ~500 ms, new response starts for the interrupting utterance.
2. Same setup, but **interrupt while the model is still thinking** (before first token). Verify the original user message disappears from the chat, replaced by the new one.
3. Same setup, but **interrupt right at the end** (after CHAT_STREAM_ENDED but while TTS is still playing). Verify the full assistant message is preserved in the chat history; audio stops.
4. **Misfire test**: cough or knock during TTS; verify audio briefly pauses and resumes.
5. **Rapid double-barge**: interrupt, then interrupt again within 1 s. Verify only the latest barge wins; no duplicate responses.
6. **Multi-tab**: open the same account in two tabs, both in conversation mode. Send from tab A, send from tab B while A is thinking. Verify tab A's stream is cancelled cleanly (no stuck TTS, no zombie state).

---

## 11. Migration Path

The refactor touches several files but can be staged:

1. **Backend — accept client `correlation_id`** (≤1 hour). Forward-compatible; existing calls that do not send `correlation_id` fall through to UUID generation.
2. **Frontend — `audioPlayback` token-aware** (≤2 hours). Keep old `mute` API alive as a thin shim that delegates to `pause` until the group layer replaces all call sites. Then remove.
3. **Frontend — `ResponseTaskGroup` module** (≤4 hours). Standalone, unit-tested. No wiring yet.
4. **Frontend — wire `ChatView` to groups** (≤4 hours). Replace flanky useEffects; `useChatStream` handlers route to group.
5. **Frontend — wire `useConversationMode` to group verbs** (≤2 hours). Replace `mute` / `cancelStreamingAutoRead` call sites. Remove shim.
6. **Backend — `handle_chat_retract`** (≤2 hours). Register dispatch; publish `CHAT_MESSAGE_DELETED`.
7. **Integration tests + manual verification** (≤4 hours).

Total: roughly one good session. Each step is independently reviewable and leaves the app in a working state (though steps 4–5 must land close together).

---

## 12. Open Questions

None blocking implementation. Questions for later:

* If, post-launch, we want per-session groups (rather than per-user) to support multi-tab power use, the group registry can be keyed differently without touching the internals. Deferred until there is demand.
* Whether the client should generate `correlation_id` for non-chat paths (memory consolidation, journal extraction) is orthogonal to this spec.

---

## Appendix A — Mapping of current defects to spec

| Defect (see §1) | Resolved by |
|-----------------|-------------|
| 1. audioPlayback correlation-blind | §4 token propagation; §8.2 token-aware `enqueue` |
| 2. useEffect edge race | §8.4 group owns lifecycle; flanky effects removed |
| 3. Backend cancel piggy-backed on new send | §7.3 + §8.5 explicit `chat.cancel` / `chat.retract` inside `group.cancel()` |
| 4. streamingContent reset masks race | §8.4 content lives on the group, not the store |
| 5. Phase machine multi-writer | §8.6 phase derived from group state |

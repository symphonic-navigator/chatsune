# Voice-Barge Structural Redesign

**Status**: Design spec, pre-implementation
**Supersedes**: The Voice-side state handling in `response-task-group-architecture.md` §8.7 and §8.8
**Leaves intact**: ResponseTaskGroup itself, Children, Registry, Token propagation, WebSocket flows
**Scope**: Frontend only — `useConversationMode`, phase derivation, and a new `bargeController` module
**Owner**: Chris

---

## 1. Why this document exists

The ResponseTaskGroup architecture (`response-task-group-architecture.md`) is largely implemented and the core machinery is sound:

- State machine and transitions behave as specified
- Every Child checks its token at the entry of every callback
- The Registry correctly supersedes its predecessor
- `audioPlayback` is token-aware, `mute` / `resumeFromMute` / `discardMuted` have been removed

Nevertheless, voice-chat barging is **state-dependent unreliable**: sometimes it interrupts cleanly, sometimes the old TTS plays on, sometimes messages interleave in the chat view. Text-chat cancel, by contrast, is deterministic.

A static code analysis (see April 2026 session transcript) identified that the unreliability does **not** come from inside the Group — it comes from the bridge that the Voice hook builds on top of the Group. Four structural defects in that bridge, each traceable to a specific piece of state that lives outside the Group and drifts out of sync with it:

| # | Defect | Where | Why it hurts |
|---|--------|-------|--------------|
| D1 | `tentativeRef` is a boolean flag parallel to Group state | `useConversationMode.ts:405,486-489,304` | Can be flipped by `handleMisfire` while STT is still running; the later confirm branch then silently skips `cancel()` but still sends the new message |
| D2 | `bargeIdRef` is only incremented inside `executeBarge` | `useConversationMode.ts:401` | Re-triggered VAD without a new pending-timer does not bump the id; stale STT results can slip past the staleness check |
| D3 | Phase has 5+ writers; the spec wants one | `useConversationMode.ts:641-657,664-681` and every `setPhase` call site | `executeBarge:403` gates on `phaseRef.current`; if a writer got there first, the pause never fires |
| D4 | Cancel-old + register-new is two non-atomic calls with an async gap | `transcribeAndSend` → `getActiveGroup()?.cancel(...)` then `onSendRef.current()` → `createAndRegisterGroup(...)` | Between the two, the old Group can go terminal, the Registry can be null, and the two outbound WS messages can slip past each other |

These are not four independent bugs. They are one class of problem: **the Voice path carries its own parallel state that has to be kept in sync with the Group, and the synchronisation points are implicit and easy to miss.**

The fix is not to synchronise harder. It is to **delete the parallel state** and route every voice-barge decision through a single object whose lifetime matches the barge attempt.

---

## 2. The Barge object

### 2.1 Mental model

A **Barge** is a named attempt by the user to interrupt the active Group. It is born when VAD confirms real speech (past the 150 ms misfire window) and dies in exactly one of four ways: confirmed (barge wins, Group cancelled, new message sent), resumed (STT empty, audio un-paused), stale (superseded by a newer Barge), or abandoned (conv-mode exits, session changes, page unloads).

```
Barge(id)
  state: 'pending-stt' | 'confirmed' | 'resumed' | 'stale' | 'abandoned'
  pausedGroupId: string | null       // id of the Group we paused, or null if no Group was running
  createdAt: number                  // for logs
```

The Barge is the replacement for **both** `tentativeRef` and `bargeIdRef`. It lives exactly as long as one user-speech attempt and is referenced, not copied, by the STT promise that was kicked off on its behalf.

### 2.2 Lifecycle

```
          VAD.speechStart
                │
                ▼
       pendingBargeTimer(150 ms)
                │
                ├── VAD.onMisfire (before timer fires)
                │      → timer cleared, no Barge created
                │
                ▼
          executeBarge()
                │
                ├── new Barge { state='pending-stt', pausedGroupId=G? }
                ├── activeGroup?.pause()             // idempotent; no-op if Group is null or in before-first-delta
                ├── currentBarge := this Barge       // module-level slot
                │
                ▼
             STT run
                │
                ├── transcript non-empty, this===currentBarge ──▶ confirm(transcript)
                │                                                  ├── state='confirmed'
                │                                                  └── bargeController.commit(transcript)
                │
                ├── transcript empty, this===currentBarge ───────▶ resume()
                │                                                  ├── state='resumed'
                │                                                  └── activeGroup?.resume() iff pausedGroupId matches activeGroup.id
                │
                ├── this !== currentBarge ───────────────────────▶ stale()
                │                                                  └── state='stale'   (result dropped silently)
                │
                └── VAD.onMisfire arrives while STT in flight ───▶ stale()
                                                                    ├── state='stale'
                                                                    └── activeGroup?.resume() iff pausedGroupId matches activeGroup.id
```

Every state has exactly one writer: the `bargeController`. No other module mutates Barge state.

### 2.3 Replacing `tentativeRef` and `bargeIdRef`

`tentativeRef.current` ≡ "there is a Barge whose `pausedGroupId` equals the current active Group". We stop asking "is there a tentative barge" — we ask "does `currentBarge` exist, and does its `pausedGroupId` still match `activeGroup?.id`". That question has a deterministic answer at every moment; a boolean flag does not.

`bargeIdRef.current` ≡ "the id of the current Barge, or 0 if none". Instead of a monotonic int snapshot, the STT promise holds a **direct reference** to its Barge. Staleness is `barge !== currentBarge`, not a numeric compare. Referential identity is impossible to drift.

---

## 3. The bargeController module

### 3.1 File and public API

**File (new)**: `frontend/src/features/voice/bargeController.ts`

```ts
export interface Barge {
  readonly id: string                    // UUID4, for logs
  readonly pausedGroupId: string | null
  readonly createdAt: number
  state: 'pending-stt' | 'confirmed' | 'resumed' | 'stale' | 'abandoned'
}

export interface BargeController {
  /** Called from executeBarge. Creates and registers a new Barge. Pauses the active Group as a side-effect. */
  start(): Barge

  /** Called from transcribeAndSend when STT confirms a non-empty transcript.
   *  Performs the atomic cancel-old + register-new + send handoff. */
  commit(barge: Barge, transcript: string): void

  /** Called from transcribeAndSend when STT returns empty. Un-pauses the Group iff still the paused one. */
  resume(barge: Barge): void

  /** Called when a newer Barge superseded this one, or VAD retracted after pause. */
  stale(barge: Barge): void

  /** Called from teardown. Marks the current Barge abandoned and cancels the active Group. */
  abandonAll(): void

  /** Readonly view of current Barge state, for derivation into phase. */
  readonly current: Barge | null
}
```

### 3.2 `commit` is the atomic handoff

This is the single function that replaces the current sequence

```ts
// current, non-atomic:
getActiveGroup()?.cancel('barge-cancel')
onSendRef.current(result.text)   // which eventually calls createAndRegisterGroup
```

with one synchronous block:

```ts
commit(barge, transcript) {
  if (barge !== currentBarge || barge.state !== 'pending-stt') {
    // The STT result arrived for a Barge that is no longer current, or was
    // already transitioned (misfire, teardown). Drop silently.
    return
  }
  barge.state = 'confirmed'

  // 1. Build the new group *before* touching the registry, so the handoff is
  //    prepared in memory and cannot half-fail.
  const newCorrelationId = crypto.randomUUID()
  const newGroup = buildGroupForVoiceSend({ correlationId: newCorrelationId, transcript, ... })

  // 2. Atomic registry flip — registerActiveGroup cancels the predecessor with
  //    reason 'superseded' and installs the new one in the same call, same tick.
  registerActiveGroup(newGroup)   // this sends chat.cancel(old) as a side-effect of the old group's cancel()

  // 3. Send chat.send for the new group. Order is guaranteed: the
  //    predecessor's chat.cancel (or chat.retract) was dispatched synchronously
  //    inside registerActiveGroup → oldGroup.cancel → sendWsMessage, before
  //    we get here.
  sendWsMessage({ type: 'chat.send', correlation_id: newCorrelationId, content: transcript, ... })

  currentBarge = null
}
```

Two consequences:

1. There is no window between cancel and register where `activeGroup` is null. A stray WS event that arrived in that window would previously drop on `getActiveGroup() === null`; now it correctly routes to the new Group or drops on id mismatch, depending on timing.

2. There is exactly one cancel reason used here: `'superseded'`. The explicit `'barge-cancel'` reason disappears from this path — barge is now modelled as "a new Group supersedes the old one", which is exactly the same model as regenerate and edit. This matches the spec's §2.3 invariant and erases one of the two "reason" branches we had to reason about.

### 3.3 `resume` only un-pauses if the Group is still the one we paused

```ts
resume(barge) {
  if (barge !== currentBarge || barge.state !== 'pending-stt') return
  barge.state = 'resumed'
  const active = getActiveGroup()
  if (active && active.id === barge.pausedGroupId) active.resume()
  currentBarge = null
}
```

If the Group we paused went terminal during STT, its playback is already drained; there is nothing to resume. If a newer Group has been registered in the meantime, we would not want to un-pause it — so the `id === pausedGroupId` check is necessary and sufficient.

### 3.4 `abandonAll` for teardown

```ts
abandonAll() {
  if (currentBarge) {
    currentBarge.state = 'abandoned'
    currentBarge = null
  }
  getActiveGroup()?.cancel('teardown')
}
```

Called from `useConversationMode.teardown`, replaces the three lines at `useConversationMode.ts:517-519` (which today touch `tentativeRef`, `bargeIdRef`, and the Group).

---

## 4. Phase: derived, not written

### 4.1 The rule

Phase becomes a pure function of three inputs:

```ts
type Phase =
  | 'idle'
  | 'listening'
  | 'user-speaking'
  | 'transcribing'
  | 'thinking'
  | 'speaking'

function derivePhase(
  group: ResponseTaskGroup | null,
  barge: Barge | null,
  vad: { active: boolean; holding: boolean }
): Phase {
  // The Barge wins: if the user is mid-barge we are always either user-speaking
  // (pre-STT) or transcribing (STT in flight). The Group being paused underneath
  // does not change what the user is doing.
  if (barge?.state === 'pending-stt') {
    return sttInFlight ? 'transcribing' : 'user-speaking'
  }

  // No Barge: phase follows Group state.
  switch (group?.state) {
    case 'before-first-delta': return 'thinking'
    case 'streaming':
    case 'tailing':            return 'speaking'     // audio is (or will be) playing
    case 'done':
    case 'cancelled':
    case undefined:            return vad.active || vad.holding ? 'user-speaking' : 'listening'
  }
}
```

(`sttInFlight` is itself derived from `barge.state === 'pending-stt'` plus a `barge.sttStartedAt` timestamp, or a separate boolean on the Barge — to be settled in implementation.)

### 4.2 Consequences

- **Delete** both useEffects in `useConversationMode.ts:641-657` and `:664-681`.
- **Delete** every call to `setPhase(...)` inside `executeBarge`, `handleSpeechStart`, `handleSpeechEnd`, `handleMisfire`, `transcribeAndSend`, `teardown`. All of them.
- **Delete** the `phase` / `setPhase` pair from `useConversationModeStore`. Phase is no longer stored; it is selected.
- Replace every read of `phase` in the React tree with `usePhase()` — a hook that subscribes to `activeGroup.state` (via a small pub-sub on the registry), `bargeController.current`, and the VAD flags, and returns the derived value.

The 150 ms interval poller disappears. So does the race between the `isStreaming` effect and the Barge effects. Phase becomes a read-only projection, and `executeBarge`'s phase guard (`if (current === 'thinking' || current === 'speaking')`) disappears too — it was only there to decide whether to call `pause()`, and that decision now lives inside `bargeController.start()` (which idempotently calls `pause()` and relies on the Group's own state guard to no-op when inappropriate).

### 4.3 Registry pub-sub

`responseTaskGroup.ts` gains a tiny subscription hook so React can react to state changes without polling:

```ts
type GroupListener = (group: ResponseTaskGroup | null) => void
const listeners = new Set<GroupListener>()

export function subscribeActiveGroup(fn: GroupListener): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

function notify() { for (const l of listeners) l(activeGroup) }

// registerActiveGroup, clearActiveGroup, and every state transition inside
// the Group calls notify() at the end.
```

This is non-invasive: the Group itself is unchanged except for a `notify()` call at the bottom of `transition()`. The rest of the codebase can keep using `getActiveGroup()` synchronously.

---

## 5. What stays the same

To be explicit — this redesign does **not** touch:

- ResponseTaskGroup class, state machine, or transitions
- GroupChild interface or any of the five Children
- Token propagation and drop-on-mismatch semantics
- Registry semantics (`registerActiveGroup` still cancels the predecessor, `clearActiveGroup` on terminal transition)
- `audioPlayback` token-awareness, `pause`/`resume`/`clearScope` semantics, the `paused` reset in `clearScope` from commit `06ff10d`
- Backend: `handle_chat_send`, `handle_chat_cancel`, `handle_chat_retract`, correlation_id persistence. No backend change in this document.
- WebSocket flows from §6 of the original spec. The wire format is untouched.
- Text-chat paths (`ChatView.handleSend`, `handleCancel`, `handleRegenerate`, `handleEdit`). They already work.

The entire change is scoped to the Voice hook and the new `bargeController` module.

---

## 6. Mapping defects → fixes

| Defect | Lives in | Fixed by |
|--------|----------|----------|
| D1 `tentativeRef` can be flipped while STT runs | `useConversationMode.ts:405, 486-489, 304` | §3: Barge state is the single source; `stale()` is the only mid-STT transition, and it sets `state='stale'`, which the later confirm branch checks. |
| D2 `bargeIdRef` not incremented on every VAD event | `useConversationMode.ts:401` | §2: referential identity replaces numeric id. Every `executeBarge` creates a new Barge object; the STT promise holds a direct reference. |
| D3 Phase has 5+ writers | `useConversationMode.ts:641-657, 664-681`, every `setPhase` | §4: phase is derived. Zero writers. |
| D4 Cancel-old + register-new non-atomic | `transcribeAndSend` lines 304-310 | §3.2: `bargeController.commit` packages both into one synchronous call, using `registerActiveGroup`'s built-in supersede semantics. |

---

## 7. Migration path

One cohesive patch. Every step compiles and the app stays usable, but the redesign is meaningful only once the voice path is fully cut over — there is no value in shipping a half-migrated Voice hook. Expected total: ~6–8 h.

| # | Step | Notes |
|---|------|-------|
| 1 | Add `subscribeActiveGroup` + `notify()` to `responseTaskGroup.ts`. | Tiny, unit-tested addition. No call sites yet. |
| 2 | Add `bargeController.ts` with `start`, `commit`, `resume`, `stale`, `abandonAll`, `current`. Unit-test in isolation with a fake Group registry. | No wiring yet. |
| 3 | Add `derivePhase` + `usePhase` hook. Unit-test the truth table. | Still not wired. |
| 4 | Replace `useConversationMode`'s body: delete `tentativeRef`, `bargeIdRef`, all `setPhase` calls, both useEffects, the `phaseRef` readback in `executeBarge`. Route through `bargeController`. | Single large commit; easier to review as a diff than piecemeal. |
| 5 | Replace every component-level read of `phase` with `usePhase()`. Remove `phase` and `setPhase` from `useConversationModeStore`. | Follow TypeScript errors; should be mechanical. |
| 6 | Update tests: new `bargeController.test.ts`; remove tests that asserted on `tentativeRef`/`bargeIdRef`/`setPhase` call sequences; add phase-derivation truth-table tests. | |
| 7 | Manual verification on device (§9). | |
| 8 | Cleanup: delete the now-unused `BARGE_DELAY_MS` snapshot logic inside `transcribeAndSend`; delete the `resumeReset` / `consecutiveResumeRef` machinery **if** the new model makes it unnecessary (open question §10). | |

---

## 8. Test plan

### 8.1 Unit tests (new)

**`bargeController.test.ts`**:
- `start()` creates a Barge with `state='pending-stt'` and captures `pausedGroupId` from the current active Group.
- `start()` with no active Group creates a Barge with `pausedGroupId=null` and does not throw.
- `commit(barge, transcript)` no-ops if `barge !== currentBarge`.
- `commit(barge, transcript)` no-ops if `barge.state !== 'pending-stt'`.
- `commit(barge, transcript)` on a valid Barge: the old Group transitions to `cancelled` with reason `'superseded'`, a `chat.send` is dispatched with the new correlationId, and `currentBarge` is null after.
- `resume(barge)` only calls `activeGroup.resume()` iff `barge.pausedGroupId === activeGroup.id`.
- `resume(barge)` on a stale Barge is a silent no-op.
- `stale(barge)` marks state correctly and, if `pausedGroupId` still matches the active Group, resumes it (matches current `handleMisfire` behaviour).
- `abandonAll()` cancels the active Group with reason `'teardown'` and nulls `currentBarge`.

**`derivePhase.test.ts`**:
- Truth table: every (Group.state, Barge.state, vad) triple maps to the expected phase.
- A fast state flip (Group `streaming` → `done` in one tick with no Barge) yields `speaking` → `listening`.
- `Barge.state='pending-stt'` dominates Group state.

**Existing `responseTaskGroup.test.ts`**: add one test that `subscribeActiveGroup` fires on every `transition` and on `registerActiveGroup`/`clearActiveGroup`.

### 8.2 Integration tests

New in `useConversationMode.integration.test.ts` (or extension of whatever exists):

- **Classic barge mid-speaking**: Group in `streaming`, user speaks, STT returns non-empty → old Group `cancelled('superseded')`, new Group exists, `chat.send` dispatched after `chat.cancel`.
- **Barge before first delta**: Group in `before-first-delta`, user speaks, STT returns non-empty → old Group receives `chat.retract` (not `chat.cancel`), new Group exists.
- **Misfire after pause**: user speaks, VAD pauses Group, VAD onMisfire before STT returns → Barge goes `stale`, Group resumes, no WS traffic.
- **Stale STT after rapid re-barge**: Barge B1 in flight; user re-triggers VAD → B2 created, B1 marked `stale`; B1's STT result arrives → `commit` no-ops because `B1 !== currentBarge`.
- **Barge on a Group that went terminal during STT**: Group drains while STT runs → Group in `done`, Registry cleared → STT returns non-empty → `commit` still registers the new Group (no predecessor to cancel, so no `chat.cancel` fires; `chat.send` goes out as usual).
- **Teardown during pending Barge**: conv-mode exit while Barge is `pending-stt` → `abandonAll`, Barge goes `abandoned`, active Group is cancelled, subsequent STT result is a no-op.

### 8.3 Regression tests (must still pass unchanged)

- Text-chat send → stop → `chat.cancel` sent.
- Text-chat send → before first delta stop → `chat.retract` sent.
- Regenerate during streaming → `'superseded'` on predecessor, new Group active.
- Edit during streaming → same.

---

## 9. Manual verification on real device

Every spec ships with hands-on verification steps. Run these on the actual hardware (headphones, desktop Firefox, and phone Safari minimum) before marking the work complete.

1. **Long answer barge, mid-speech**. Ask a long question in conv-mode. Once the assistant is audibly speaking, interrupt. **Expected**: audio stops within ~500 ms of you starting to talk; assistant replies to the interruption. No audio should leak past the stop point.

2. **Barge while model is still thinking**. Ask a question, barge before any audio starts. **Expected**: the original user message disappears from the chat (retract path), replaced by the new utterance.

3. **Barge near the end of playback**. Start a reply; barge during the last sentence. **Expected**: the full assistant message is preserved in the chat history; audio stops where you spoke.

4. **Misfire during playback**. Cough or tap the mic while TTS plays. **Expected**: audio briefly pauses (you may not notice), then resumes within ~200 ms. No message is sent.

5. **Misfire after pause committed**. Same as above but make the burst slightly longer so the 150 ms window elapses. **Expected**: audio briefly pauses audibly, then resumes.

6. **Rapid double-barge**. Speak, then speak again within ~1 s. **Expected**: only the later utterance is sent; the earlier STT result (if it lands) is silently dropped.

7. **Barge on an already-finishing Group**. Ask a short question. As the final sentence plays, start speaking immediately. **Expected**: no zombie audio; the new utterance is sent; the old message remains in the chat with its full text.

8. **Leave conv-mode mid-barge**. Start speaking, then tap the conv-mode exit button during STT. **Expected**: no message is sent; the previous assistant reply is preserved; no pending STT result lingers.

9. **Multi-tab**. Open the app in two tabs, both in conv-mode. Speak in tab A; while tab A is thinking, speak in tab B. **Expected**: tab A's Group is cleanly cancelled; no zombie state in either tab.

10. **Log audit**. With the dev console open, run three back-to-back conv-mode exchanges (one mid-speaking barge, one misfire, one clean reply). Filter on `[group ` and `[barge `. **Expected**: every event is reconstructable from the logs — every Barge has its start/commit (or stale/abandoned), every Group has all its state transitions, every cancel carries a reason.

---

## 10. Open questions

Non-blocking; to be resolved in implementation:

- **`consecutiveResumeRef` / `MAX_CONSECUTIVE_RESUMES`**: the current code escalates to a cancel after N consecutive empty-STT resumes, presumably to protect against VAD pathologies where the mic picks up something repeatedly. Does this behaviour belong on the Barge (each Barge carries a resume-count), on the controller (cross-Barge counter), or should it be removed altogether on the grounds that the underlying VAD issue is the thing to fix? Decide during step 4.

- **`sttInFlight` for phase derivation**: §4.1 sketches this as a derived value. Cheapest implementation is a boolean field on Barge (`state === 'pending-stt' && sttStartedAt != null`), but making it an explicit state (`'pending-pause' | 'pending-stt'`) might read cleaner. Decide during step 2.

- **Backwards-compatibility during step 4**: we may want a feature flag so the old and new paths can coexist briefly for side-by-side diff on real sessions. Or we commit to one atomic flip and rely on the test suite + manual verification. Chris to decide based on risk appetite when we get there.

---

## Appendix A — Before/after sketch of `transcribeAndSend`

**Before** (`useConversationMode.ts:229-310`, condensed):

```ts
const transcribeAndSend = useCallback(async (audio) => {
  if (!activeRef.current) return
  const sttBargeId = bargeIdRef.current
  // ...empty-audio short-circuit using tentativeRef...
  setPhase('transcribing')
  const result = await stt.transcribe(audio)
  if (!activeRef.current) return
  const outcome = decideSttOutcome({ transcript: result.text, sttBargeId, currentBargeId: bargeIdRef.current })
  if (outcome === 'stale') return
  if (outcome === 'resume') {
    if (tentativeRef.current) {
      tentativeRef.current = false
      // ...resume-counter dance, possibly calls cancel...
      getActiveGroup()?.resume()
      setPhase('speaking')
    } else setPhase('listening')
    return
  }
  // outcome === 'confirm'
  if (tentativeRef.current) {
    tentativeRef.current = false
    getActiveGroup()?.cancel('barge-cancel')
  }
  setPhase('thinking')
  onSendRef.current(result.text.trim())
}, [setPhase])
```

**After**:

```ts
const transcribeAndSend = useCallback(async (audio, barge: Barge) => {
  if (barge.state !== 'pending-stt') return   // already stale/abandoned
  const result = await stt.transcribe(audio)
  if (barge.state !== 'pending-stt') return   // became stale/abandoned during STT
  if (result.text.trim() === '') {
    bargeController.resume(barge)
  } else {
    bargeController.commit(barge, result.text.trim())
  }
}, [])
```

The function shrinks from ~80 lines to ~10. Every control decision moves into `bargeController`, where it is testable in isolation. The only thing that stays in the hook is "run STT, then tell the controller what happened".

**Before** (`executeBarge`, lines 399-408):

```ts
const executeBarge = useCallback(() => {
  pendingBargeRef.current = null
  bargeIdRef.current += 1
  const current = phaseRef.current
  if (current === 'thinking' || current === 'speaking') {
    getActiveGroup()?.pause()
    tentativeRef.current = true
  }
  setPhase('user-speaking')
}, [setPhase])
```

**After**:

```ts
const executeBarge = useCallback(() => {
  pendingBargeRef.current = null
  const barge = bargeController.start()   // pauses the Group internally if applicable
  currentBargeRef.current = barge         // only so handleMisfire can call bargeController.stale(barge)
}, [])
```

No phase write. No parallel boolean. One call, one returned object.

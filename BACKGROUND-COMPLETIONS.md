# Background Completions — Notes for Decision

Working notes on a feature request raised by multiple users. Not a spec.
Captured to let the idea rest a few days before deciding whether to act.

## Use Case

User talks in chat **A**. Model starts answering. User suddenly remembers
something and switches to chat **B** mid-stream.

- **Today:** the in-flight response for chat A is discarded.
- **Wanted:** the response keeps processing in the backend and is
  persisted to chat A's history. Live voice for A is shut off.

## Most Important Finding

The Response Task Group architecture is **already designed for exactly
this behaviour**. From `frontend/src/features/chat/responseTaskGroup.ts:110-114`:

> `teardown`: the React tree is being unmounted (navigation away …).
> The backend inference must continue and persist its result, so the
> user can come back to a full assistant reply on remount. Sending
> neither `chat.cancel` nor `chat.retract` is intentional.

And `ChatView.tsx:469-474` does call `cancelCurrentActiveGroup('teardown')`
on session switch, which sends no WS frame. Backend skips persistence
only when `cancel_event` is set
(`backend/modules/chat/_inference.py:235-240`,
`backend/modules/chat/_orchestrator.py:935-943`), which requires a
`chat.cancel` to arrive. So in the simplest case, persistence should
already happen.

That means the gap is most likely a **bug or edge case**, not a
missing architecture.

## Hypotheses for the Discard Effect (most likely first)

1. **`registerActiveGroup` cancels predecessor with `'superseded'`**
   (`responseTaskGroup.ts:267-273`). When the user sends a new message
   in chat B, group A is superseded → that path **does** emit
   `chat.cancel` → A is discarded. Most likely culprit.

2. **Per-user inference lock** (`_inference.py:147`). Even if A keeps
   running, B's new message blocks until A finishes. From the user's
   POV that is indistinguishable from "A was cancelled" because B
   appears to do nothing for seconds.

3. **Race on pure switch (no new message in B).** `chatStore.reset()`
   clears UI state, but backend should still persist. If it does not,
   that is a real bug somewhere in the streaming or save path.

→ Before implementing, **reproduce all three cases separately** and
check backend logs for whether the assistant message landed in MongoDB.
Cases 1 and 3 have very different fixes; case 2 is structural.

## Effort Tiers

| Tier | Scope | Estimate |
|---|---|---|
| **S** | Fix the bug if pure switch already does not persist. Ensure session switch never emits `chat.cancel` (treat switch as `'teardown'`, never `'superseded'`). | 2–4 h |
| **M** | Tier S + frontend: when user sends a new message in B while A is still streaming, do not supersede A. Run A as a detached background group with its own correlation id, no longer in the `activeGroup` slot. | 1 day |
| **L** | Tier M + backend: relax per-user lock (per-session lock, or small bounded concurrency cap). Define error handling for failures in non-active sessions. UI notification when an off-screen completion finishes. | 2–3 days |

## Risks

1. **Conflict with existing memory rule "one chat at a time"** *(structural,
   high)*. The principle was set deliberately and rejects parallel-chat
   patterns even when technically feasible. Background completion is not
   "two active chats from the user's POV", but technically it is parallel
   backend work. This is the kind of slow drift the rule was meant to
   prevent. Decide explicitly whether the rule is being amended or upheld.

2. **Tool calls in background inference** *(high)*. If A's response
   includes tool calls (web search, MCP, memory writes), those run with
   no visible UI feedback. Errors raise an `ErrorEvent` that arrives at
   the user while they are in B. Need a clear story for surfacing those
   errors (toast? sidebar badge?) — silence is the worst answer.

3. **Per-user lock blocks tier S/M** *(high)*. As long as the lock holds,
   sending in B waits for A to finish. The lock exists for a reason
   (rate limits, token cost control, provider concurrency limit). Loosening
   it is not free.

4. **Silent persistence UX** *(medium)*. User switches to B, forgets A.
   Hours later opens A and is confused by an unprompted answer. Needs
   either a notification/unread indicator or an explicit decision that
   silent persistence is fine.

5. **Wish-driven priority check** *(meta)*. "From multiple sides" sounds
   like real user pain. Worth checking whether it is "happens often,
   really annoys" (justifies tier M/L) or "happened once, annoyed in
   hindsight" (tier S + a clearer toast on cancel may be enough).

6. **Voice side is the easy part** *(low)*. `playbackChild.onCancel('teardown')`
   already cleans up TTS and synth/sentencer children. Live voice
   automatically shuts down via group teardown. Nothing extra needed.

## Open Questions Before Writing a Spec

1. **What happens when the user sends a new message in B while A is
   still streaming?**
   - (a) B waits until A is done
   - (b) A keeps running in background, B starts in parallel
   - (c) A is auto-cancelled (current behaviour)
2. **When A finishes off-screen — notify the user how?**
   - Sidebar unread badge / dot
   - Toast "Reply ready in chat A"
   - Silent (just there next time A is opened)
3. **Which of the three hypotheses above actually causes the discard?**
   Reproduce: (a) pure switch, no message in B; (b) switch + message in
   B; (c) switch back to A before A's stream would have finished. Check
   MongoDB after each.
4. **Is the per-user inference lock load-bearing for cost / rate-limit
   reasons, or incidental?** Determines whether tier L is realistic.
5. **Does the existing "one chat at a time" rule still hold, or does
   this use case justify amending it?** Needs an explicit answer, not
   a quiet drift.

## Files Touched in This Analysis

- `frontend/src/features/chat/responseTaskGroup.ts` — group lifecycle, cancel reasons, registry
- `frontend/src/features/chat/ChatView.tsx:469-474` — session-switch cleanup (calls `'teardown'`)
- `frontend/src/features/chat/ChatView.tsx:614-706` — group construction
- `backend/modules/chat/_orchestrator.py:507, 671, 824, 865, 935-943` — inference orchestration, cancel registration, persistence gate
- `backend/modules/chat/_inference.py:147, 156, 235-240` — per-user lock, cancel polling, status on cancel
- `backend/modules/chat/_handlers_ws.py:566-570` — `chat.cancel` handler

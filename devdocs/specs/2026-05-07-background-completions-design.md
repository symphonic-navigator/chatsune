# Background Completions — Design

**Date:** 2026-05-07
**Status:** Draft, awaiting user review.

## Problem

When a user navigates away from a chat while inference is still streaming —
switching personas in the same tab, opening a historical chat, closing the
tab, reloading, or losing the WebSocket — the in-flight inference is killed
and its response is lost. Multiple beta testers have reported this. The
common case is "I switched persona to glance at something, came back, and
my answer was gone."

The intent of this design is: **once an inference has started, it always
finishes and persists, unless the user explicitly stops it or starts a new
one in the same session.**

## Mental Model

An inference is bound to exactly three life-events:

1. **Born** — by `chat.send`, `chat.edit`, or `chat.regenerate`.
2. **Dies naturally** — when the LLM finishes streaming and the assistant
   message is persisted with status `completed`.
3. **Dies prematurely** — only by:
   - explicit user Stop button (`chat.cancel` WS frame), or
   - a new `chat.send` / `chat.edit` / `chat.regenerate` **in the same
     session**.

Everything else — persona switch, opening a historical chat, tab close,
reload, mobile backgrounding, flaky network, full WS disconnect — lets the
inference keep running. Its tokens stream into MongoDB as today, and its
events keep flowing through Redis Streams (existing 24 h TTL).

## Cancel-Trigger Matrix

| Event                                           | Today                           | After this design                              |
| ----------------------------------------------- | ------------------------------- | ---------------------------------------------- |
| User presses Stop                               | cancel correlation              | unchanged                                      |
| `chat.send` in **same** session as inflight     | cancel via `cancel_all_for_user`| cancel via `cancel_inflight_for_session`       |
| `chat.send` in **different** session            | cancels (collateral damage)     | leaves running                                 |
| Persona switch in same tab                      | nothing on backend              | unchanged (frontend `'teardown'` keeps no-op)  |
| Open historical chat                            | nothing on backend              | unchanged                                      |
| Tab close / reload / mobile background          | cancel after 10 s grace         | leaves running until natural completion        |
| WS disconnect for any other reason              | cancel after 10 s grace         | leaves running                                 |

The unifying change: cancel granularity goes from **user** to **session**,
and WS-disconnect-driven cancels disappear entirely.

## Backend Changes

### `backend/modules/chat/_orchestrator.py`

- Replace `_cancel_user_ids: dict[str, str]` (mapping `correlation_id ->
  user_id`) with a richer mapping that also tracks the session:
  `_inflight: dict[str, tuple[str, str]]` — `correlation_id ->
  (user_id, session_id)`. Written by `run_inference` and
  `handle_incognito_send`, cleaned up in their respective `finally` blocks.
- Add `cancel_inflight_for_session(user_id: str, session_id: str) -> int`
  that signals the cancel event for every correlation matching both keys.
  Mirrors the existing `cancel_all_for_user` shape.
- Keep `cancel_all_for_user` (used elsewhere — admin tooling, tests). Stop
  using it from the WS-disconnect path.
- `request_cancel(correlation_id, user_id)` is unchanged — single-correlation
  cancel still works for the explicit Stop button.

### `backend/modules/chat/_handlers_ws.py`

Three call sites swap `cancel_all_for_user(user_id)` for
`cancel_inflight_for_session(user_id, session_id)`:

- `handle_chat_send` — line 230
- `handle_chat_edit` — line 431
- `handle_chat_regenerate` — line 524

Comment block ("Per-user single-stream policy") is updated to "Per-session
single-stream policy".

### `backend/ws/router.py`

Inside `_delayed_disconnect_cleanup` (around line 281):

- **Remove** the `cancel_all_for_user(user_id)` call. Inferences now survive
  WS disconnect.
- **Replace** `client_dispatcher.cancel_for_user(user_id)` with a softer
  resolution: every pending client-tool future for this user resolves with
  a sentinel error `"client_offline"`. The inference's tool loop sees this
  the same way it sees any other tool error — it surfaces the failure into
  the assistant turn instead of hanging. Concrete change in
  `backend/modules/tools/_client_dispatcher.py` (or wherever
  `cancel_for_user` lives): add `resolve_for_user_with_error(user_id,
  error_code: str)` and call it from the disconnect path.
- **Keep** `remove_mcp_registry(connection_id)`. MCP servers attached to
  this WS connection are gone with it.
- **Move** `trigger_disconnect_extraction(user_id)` out of this 10-second
  cleanup. It now triggers from the inference-cleanup path (see below) —
  this preserves the invariant "memory extraction sees the final answer".

### Disconnect-Extraction Anchor (Variant B)

The trigger moves from "10 s after WS disconnect" to "the user has no
connections AND no inflight inferences". Implementation:

- At the end of every inference (in the `finally` block of `run_inference`,
  after the entry has been removed from `_inflight`), check:
  ```python
  async with _disconnect_extraction_lock_for(user_id):
      if (not manager.has_connections(user_id)
              and not _user_has_inflight(user_id)):
          await trigger_disconnect_extraction(user_id)
  ```
- `_disconnect_extraction_lock_for(user_id)` is a per-user `asyncio.Lock`
  to avoid a race when two inferences finish simultaneously and both pass
  the check.
- The 10-second grace timer in `_delayed_disconnect_cleanup` no longer
  exists for extraction; the check above runs when each inference completes.
  If the user is still online when the last inference finishes, no
  extraction triggers — that is correct.
- An additional safety net: a single deferred check `asyncio.create_task`
  scheduled from `_delayed_disconnect_cleanup` after 30 s, that runs the
  same `if not has_connections and not _user_has_inflight: trigger`
  block. This handles the case "user disconnects while no inference is
  running" (otherwise the trigger would never fire). The 30 s aligns with
  the previous grace-window order of magnitude — short enough that the
  user feels the extraction promptly on reconnect, long enough to absorb
  routine network blips.

### `_filter_usable_history` (no change)

Aborted and refused messages stay filtered from LLM context
(`_orchestrator.py:64`). User-initiated Stop still produces an `aborted`
status; nothing changes there.

## Frontend Changes

### Per-session streaming state

`frontend/src/core/store/chatStore.ts` currently keeps a single global
streaming slot and `reset(sessionId)` (line 283) discards it on session
switch. This is incompatible with background completions.

- New shape: `streamsBySession: Map<sessionId, StreamingState>` where
  `StreamingState` holds the current correlation, partial content, slow
  flag, etc.
- `reset(sessionId)` no longer clears the streaming state; it only
  switches `activeSessionId`.
- The chat-rendering components read `streamsBySession.get(activeSessionId)`
  instead of the previous global slot.
- The `chatStoreSink` child (in `responseTaskGroup` children) writes into
  the map keyed by the Group's `sessionId`, not into a single global slot.

### Multi-Group registry

`frontend/src/features/chat/responseTaskGroup.ts` keeps a single
`activeGroup` and supersedes any predecessor on `registerActiveGroup`
(lines 267-273). Replace this with:

- `groupsBySession: Map<sessionId, Group>`
- `registerActiveGroup(g)`:
  - If `groupsBySession.has(g.sessionId)`, cancel the existing entry with
    reason `'superseded'` (this maps cleanly to the backend "same session,
    new send cancels old" rule).
  - `groupsBySession.set(g.sessionId, g)`.
- `getActiveGroup()` is removed in favour of `getActiveGroupForSession(sid)`.
  Audit existing call sites:
  - `ChatView.tsx:471, 1025, 1030, 1047` — pass the current session id.
  - `bargeController.ts:163` — needs the session id at call site.
  - `useConversationMode.ts:562` — same.
- `cancelCurrentActiveGroup(reason)` becomes
  `cancelGroupForSession(sessionId, reason)`. Most teardown paths know
  their session.
- `subscribeActiveGroup` becomes `subscribeGroupsBySession` (notifies on
  any change, listeners filter by session id).

### `'teardown'` reason — semantic clarification

`'teardown'` already sends no WS frame (correct behaviour). What it must
**not** do under the new design: tear down children that are still
required for background persistence. Concretely:

- `chatStoreSink` child: keeps writing into `streamsBySession[sessionId]`
  until `onStreamEnd` or explicit cancel. Teardown just detaches its UI
  binding, not its store binding.
- Voice children (sentencer, audioPlayback, audioParser): tear down
  fully on `'teardown'` — see Voice Interaction below.

This means we likely split the existing `teardown()` method on `GroupChild`
into something finer-grained (e.g. `detachUi()` vs `dispose()`), or make
the chatStoreSink child idempotent against teardown so it survives. The
plan should pick one approach during implementation; I lean toward making
chatStoreSink survive teardown because it has no UI-specific state.

## UI Indicator + Stop Paths

### Sidebar pulse-dot

A small (≈6 px) animated pulse-dot appears next to any session row whose
`streamsBySession` slot has an active stream. Subtle monochrome accent —
same restraint as the inline voice-tag pills.

- Driven directly by the `streamsBySession` map; sidebar component
  subscribes and re-renders affected rows.
- For sessions belonging to a different persona, the same dot also
  appears on the persona entry in the unified sidebar / persona switcher
  — so the user can spot the activity even when the parent persona is
  collapsed.

No global "X completions running" counter. The per-row dot is enough; an
extra header counter would be chrome without payoff.

### Stop from sidebar

- Right-click on a session row exposes a "Stop generation" menu item when
  a stream is active there. Sends `chat.cancel` with the corresponding
  `correlation_id`.
- (Optional, plan-time decision) A small × button reveals on hover next
  to the pulse-dot for the same action. The right-click menu is the
  authoritative path; the × is a discoverability aid.

The in-session Stop button (composer/cockpit) is unchanged — it already
sends `chat.cancel` for the active correlation.

### Resume on return

When the user navigates back to a session whose stream is still active,
nothing special happens at the WS layer:

- The WS connection has been receiving the stream's events all along
  (events are scoped `session:abc`, the user's WS subscribes globally).
- Those events were written into `streamsBySession[abc]` by the
  chatStoreSink child as they arrived.
- The chat view renders from `streamsBySession.get(activeSessionId)` and
  picks up where it stands — partial content visible, new tokens append
  live.

After a full reload (no WS at all during streaming), the existing
Reconnect/Catchup over Redis Streams (`BaseEvent.sequence` + 24 h TTL)
replays missed events on login; same end result.

No toast, no "completion finished" banner. The sidebar's natural
re-sorting (by `last_activity_at`) is signal enough.

## Voice Interaction

When the user is in continuous-voice mode in persona A, an answer is
streaming (with TTS audio), and they switch to persona B:

- **Voice cancels.** TTS audio stops. The voice children
  (sentencer, audioPlayback, audioParser) are torn down.
- **LLM inference continues.** The text-side child (`chatStoreSink`)
  stays attached to the Group and keeps writing tokens to MongoDB.
- **No WS frame is sent** (still `'teardown'` semantics, just with a
  variant marker so children can decide to tear down or persist).

When the user returns to persona A, they see the (possibly already
finished) text answer in the transcript. No re-narration. Voice mode is
**not** auto-resumed — the user starts voice anew if they want it.

Implementation note: this is the first concrete need for
finer-grained child teardown (`detachUi` vs `dispose`). The plan should
specify the contract precisely.

## Resource & Safety Limits

- **No per-user inflight cap** in this round. Adapter-level `max_parallel`
  on each Connection already throttles concurrent requests, and realistic
  beta usage is < 5 simultaneous.
- **Tool-call timeouts** stay as today; client-side tools resolve with
  `client_offline` instead of being silently cancelled, so a stalled tool
  call surfaces as a tool error in the persisted response rather than an
  invisible hang.
- **MCP servers** attached to a disconnected WS are removed
  (`remove_mcp_registry` stays). If the inference depended on an
  MCP-registered tool that vanishes mid-flight, the tool call returns an
  error — same path as `client_offline`.

## Migration Notes

- No schema migration. No new fields on session or message documents.
  Aborted/refused/completed status semantics unchanged.
- Hot deploy: in-flight inferences from the old build run to completion
  under the old single-stream rules. The new rules apply only to
  inferences started after the deploy. No coordination required.
- The `cancel_all_for_user` function stays callable for tests and
  one-off admin tooling but is no longer invoked from the WS-disconnect
  cleanup path.

## Manual Verification

Run these at the deployed staging build before merging. Each step
expects a specific observable behaviour — call out any deviation.

### Persona-switch survival

1. Open a chat, ask the model a long-form question that takes ≥ 30 s to
   stream.
2. While tokens are visibly streaming, switch to a different persona.
3. Wait for the original persona's pulse-dot to disappear in the sidebar.
4. Switch back to the original persona.
5. **Expected:** the assistant answer is fully persisted in the
   transcript, no "[aborted]" status, no missing message.

### Sidebar pulse-dot

1. Same starting condition as above.
2. After the persona switch, look at the sidebar.
3. **Expected:** a pulse-dot is present next to the original session row
   while it streams. Dot disappears within ~1 s of the stream finishing.
4. Right-click that row.
5. **Expected:** "Stop generation" entry is present. Clicking it
   cancels the stream and the dot disappears.

### Same-session cancel still works

1. Start a long-form answer, wait for tokens to appear.
2. While streaming, type a new message in **the same chat** and press
   send.
3. **Expected:** the old answer is cut at its current position with
   `aborted` status, the new answer starts streaming. Both messages
   exist in the transcript in the right order.

### Cross-session non-interference

1. Start a long-form answer in session A.
2. Open session B (different persona) and send a message there too.
3. **Expected:** both inferences run in parallel. Session A's answer
   completes uncut. Session B's answer streams normally.

### Tab reload survives

1. Start a long-form answer.
2. Hit `Ctrl+R` while it's streaming.
3. After the app reloads, navigate back to that session.
4. **Expected:** if the answer is still streaming, it picks up live (via
   Redis Stream catchup); if it has finished, it's fully there in the
   transcript.

### Mobile background survives (PWA)

1. On the iOS PWA, start a long-form answer.
2. Press the Home button or swipe up — background the app for ~30 s.
3. Bring the app back to foreground.
4. **Expected:** answer is either still streaming or already complete in
   the transcript. Nothing aborted, nothing missing.

### Voice + persona switch

1. Enter continuous-voice mode in persona A.
2. Speak a prompt that triggers a long answer.
3. While TTS audio is playing, switch to persona B.
4. **Expected:** TTS audio stops immediately. Sidebar dot remains on A
   until the inference finishes.
5. Switch back to A.
6. **Expected:** text answer is persisted in the transcript. No audio
   replays. Voice mode is off (user must re-enable).

### Disconnect-extraction timing

1. Start a long-form answer.
2. Close the browser tab while streaming.
3. Watch backend logs.
4. **Expected:** the assistant message is persisted to MongoDB with
   `completed` status. `disconnect_extraction` for this user fires
   **after** the inference finishes, not at the 10-s grace mark.

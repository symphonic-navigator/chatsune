# QA Paket B — Chat list state synchronisation

Date: 2026-05-06
Status: Draft, ready for implementation

This spec covers two related frontend bugs reported by Ksena (QA) on
2026-05-06. Both concern chat-list state that is not in sync with the
rest of the app — one about delete propagation, one about a query
filter that hides project-bound chats from the persona history view.

The bugs share a theme but live in different code paths and could be
delivered independently. They are bundled because both are
mid-complexity, both involve `useChatSessions` and the
`HistoryTab` family of components, and both fit naturally in a single
plan.

---

## 1. Deleting the open chat from a settings menu does not close the chat view

**Symptom.** When the user has chat X currently open and deletes
chat X via any of three "settings"-style UI surfaces — User Area >
Chats > History (inside `UserModal`), Persona settings > History
(inside `PersonaOverlay`), or Project settings > Chats > History
(inside `ProjectDetailOverlay`) — the chat view stays mounted at
`/chat/{persona}/{session}` even though the underlying session is
gone. Deleting chat X from the sidebar's chat list works correctly:
the view clears.

**Root cause.** The sidebar's delete handler is *imperative* — it
calls `chatApi.deleteSession()` and then conditionally navigates
away with `if (wasActive) navigate('/personas')`
(`Sidebar.tsx:304-334`). The three settings paths call the same
`chatApi.deleteSession()` but do not navigate. The
`CHAT_SESSION_DELETED` WebSocket event arrives in all cases and
updates the session list via `useChatSessions`, but no listener
exists at the chat-view level that says "if my active session was
deleted, leave". The sidebar's manual `navigate(...)` is essentially
a workaround for this missing reactive piece.

**Fix.** Add a single reactive listener in `ChatView` that
subscribes directly to the `CHAT_SESSION_DELETED` event bus topic.
When the event payload's `session_id` matches the currently active
session, the chat view navigates away to `/personas` (the same
target the sidebar uses). The three settings-menu delete handlers
become correct without modification because the WS event already
fires.

**Important: subscribe to the event bus, not to a session-list
store.** `useChatSessions` is intentionally global-non-project
(see `useChatSessions.ts:32-34` and the project-chat filtering on
line 35), and project-bound chats live in a separate
project-detail-overlay store. Watching either store for "is my
session still present?" would either miss project chats entirely
or require coordinating two stores. The `CHAT_SESSION_DELETED`
event is fired regardless of project-membership, so a single
event-bus subscription correctly handles both project and
non-project active sessions.

This aligns with the project's hard requirement in `CLAUDE.md`:
"Every state change publishes an event. The frontend is a view, not
a participant." The reactive listener is exactly that — the chat
view reacting to its own session being deleted, regardless of where
the delete was triggered.

**Sidebar interaction.** The sidebar's existing imperative
`navigate('/personas')` is left in place. It races harmlessly with
the new reactive listener — both target `/personas`, the second
navigate becomes a no-op. The duplication is acknowledged here so
later cleanup is not surprising; removing the sidebar's imperative
navigation is a follow-up that is not required to fix this bug.

**Files.**
- `frontend/src/features/chat/ChatView.tsx` — add a `useEffect`
  that subscribes to `Topics.CHAT_SESSION_DELETED` via the
  `eventBus` (`core/websocket/eventBus`, mirror the subscription
  pattern from `useChatSessions.ts:55-58`). In the handler:
  ```tsx
  if (event.payload.session_id === sessionId && !isIncognito) {
    navigate('/personas')
  }
  ```
  Return the `unsub` function from the effect so the listener
  detaches on unmount or session change. Skip when `isIncognito`
  is true — incognito sessions use an ephemeral local UUID that is
  never persisted, so no real `CHAT_SESSION_DELETED` event will
  ever name it; the guard is defence in depth.

**Implementation note.** No store-readiness discrimination needed
— event-bus subscription is naturally edge-triggered: the listener
fires only when an actual delete event arrives. Initial load and
"haven't fetched yet" states are not concerns.

**Out of scope.**
- Refactoring the sidebar to drop its imperative `navigate(...)`.
- A shared `deleteSessionAndCloseIfActive` helper across all four
  delete entry points.
- Any change to the three settings-menu delete handlers.

**Manual verification.**
1. Open chat X. Open User Area > Chats > History. Delete chat X
   from the list. Expect: chat view closes and navigates to
   `/personas`. Sidebar list also no longer shows chat X.
2. Open chat X. Open Persona settings > History. Delete chat X.
   Expect: same as step 1.
3. Open chat X (a project-bound chat). Open Project settings >
   Chats > History. Delete chat X. Expect: same as step 1.
4. Open chat X. Delete chat X from the sidebar list (the existing
   working path). Expect: still works as before — chat view
   closes, no double-navigation glitch.
5. Open chat X. From a different surface, delete chat Y (a
   non-active chat). Expect: chat X stays open (only the active
   session triggers navigation).
6. Open an Incognito chat (`?incognito=1`). Manually trigger an
   irrelevant delete event for some other session. Expect: the
   incognito view is not affected — the watch must not navigate
   away just because some non-incognito session disappeared.

---

## 2. Persona history hides chats that belong to a project

**Symptom.** In the Persona-overlay history view, chats that belong
to a project do not appear. They are visible in the project's own
history view but not in the persona's. The user expects to see all
of the persona's chats in one place, with a marker indicating which
project each one belongs to (if any).

**Root cause.** The persona-overlay HistoryTab uses
`useChatSessions()` which calls `chatApi.listSessions()` with no
parameters (`useChatSessions.ts:14`). The backend default for
`include_project_chats` is `false`, so project-bound sessions never
reach the component. The session DTO already carries
`project_id: string | null` (`chat.ts:21-40`), so once the data is
fetched, the project pill can render without an extra round-trip.

**Constraint discovered during design.** `useChatSessions` is
intentionally hard-coded to "global, non-project history" — the
inline comments at `useChatSessions.ts:32-34, 92-98` make this
explicit, and its lifecycle-event handlers actively drop project
chats (e.g. line 35: `if (projectId !== null) return`). Adding a
parameter would entangle the global-history semantics with a
persona-scoped variant. The user-modal HistoryTab handles this by
doing its own dedicated fetch via `chatApi.listSessions({
include_project_chats: true })` whenever the toggle is on
(`HistoryTab.tsx:140-142`) and falling back to `useChatSessions`
only when no project chats are involved. The persona-overlay
HistoryTab follows the same precedent.

**Fix.** Two changes:

1. The persona-overlay `HistoryTab` stops using `useChatSessions`
   and instead does its own dedicated fetch via
   `chatApi.listSessions({ include_project_chats: true })`,
   filtering the result client-side by `session.persona_id ===
   persona.id` (the same filter applied today at
   `persona-overlay/HistoryTab.tsx:94`). The component subscribes
   to `CHAT_SESSION_DELETED` (and optionally
   `CHAT_SESSION_TITLE_UPDATED`) to keep the local list in sync
   with live deletions and title changes — at minimum the delete
   handler is required, because Bug #3's reactive listener will
   navigate the chat view away after a delete and the list must
   reflect the removal in the same moment. Other lifecycle events
   (created/restored/pinned/project_updated) can be handled the
   same way the user-modal HistoryTab handles them, but the
   minimum bar is delete.

2. Each row that has `session.project_id !== null` renders the
   existing project-pill pattern from
   `app/components/user-modal/HistoryTab.tsx:535-543`:
   ```tsx
   <span
     data-testid="history-project-pill"
     className="ml-1 flex-shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px] text-white/65"
     style={{ background: 'rgba(255,255,255,0.05)' }}
   >
     {projectPill.emoji ?? '—'} {projectPill.title}
   </span>
   ```
   Reuse this pattern verbatim — same testid, same classes, same
   inline style. The lookup to resolve `project_id` to
   `{ emoji, title }` should mirror the existing user-modal
   HistoryTab logic (read from the projects store).

**Sorting.** Project chats are mixed inline with non-project chats,
sorted chronologically by the same key the persona-overlay
HistoryTab already uses (last activity / created-at, whatever the
existing default is). No grouping, no separate "project" section.

**No new toggle.** The user-modal HistoryTab has an
`includeProjectChats` toggle. The persona-overlay HistoryTab does
not get one — project chats are always shown there. Rationale:
filter-controls memory says "multi-select filters are
overengineering"; project pill on each row is the marker that makes
the source visible.

**Files.**
- `frontend/src/app/components/persona-overlay/HistoryTab.tsx` —
  swap `useChatSessions()` for a dedicated `chatApi.listSessions({
  include_project_chats: true })` fetch on mount (and on
  persona-id change), filter client-side by `persona_id`, manage
  the resulting list in local component state, and subscribe at
  least to `CHAT_SESSION_DELETED` via the event bus to remove rows
  on delete. Add the project-pill render to each row whose
  `session.project_id !== null`, resolving the pill data from the
  existing projects store the same way the user-modal HistoryTab
  does (`HistoryTab.tsx:535-543` for the JSX, surrounding lines
  for the lookup).

`useChatSessions.ts` is **not** modified.

**Out of scope.**
- Adding an `includeProjectChats` toggle to the persona-overlay
  HistoryTab.
- Re-grouping or re-sorting the list (chronological inline only).
- Backend changes — the `include_project_chats` parameter already
  exists.

**Manual verification.**
1. Persona P1 has at least one chat outside any project and at
   least one chat bound to a project. Open Persona P1 settings >
   History. Expect: both chats appear in chronological order; the
   project-bound chat shows the project pill (emoji + title) on
   its row.
2. Click a project-bound chat row. Expect: navigates to that chat
   correctly.
3. Sanity check: the user-modal HistoryTab still works as before
   — its toggle still toggles, its project pills still render,
   nothing regresses.
4. Sidebar history zone: still excludes project chats by default
   (its current behaviour). The shared hook's default must not
   have changed.

---

## Build verification

- `pnpm run build` (frontend) clean — `tsc -b` strict check.
- No backend changes — no `uv run python -m py_compile` needed.

## Implementation notes

- Both fixes are frontend-only. No new dependencies.
- No automated tests are required for these surface-level
  state-sync fixes; manual verification on a real device is the
  primary check, matching the convention used in QA Paket A.
- Follow the standard subagent constraint per project memory: do
  not merge, do not push, do not switch branches.

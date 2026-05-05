# Projects feature — bug fixes (round 1)

Date: 2026-05-05
Status: Draft, ready for implementation

This spec covers six issues observed in the Projects (Mindspace) feature
post-merge. Two are missing UI affordances, two are timing/state bugs
introduced by the browser-back-closes-overlay mechanism, one is a
session-state ownership bug that surfaces in the in-chat project
switcher, and one is a localisation polish.

The fixes are independent at file level and can be implemented in
parallel by separate subagents. They share one test surface only — the
chat top-bar `ProjectSwitcher` — which interacts with the active-session
state change in §4.

---

## 1. User-overlay → Projects page: pin/unpin control (issue a)

**Symptom.** The User overlay's Projects page (`ProjectsTab`) shows a
"Pinned" badge on already-pinned project rows but offers no UI to
toggle pin state. The Personas page in the same overlay has a context
menu / pin button.

**Root cause.** `ProjectsTab.tsx` was implemented before the per-row
context menu pattern landed for projects. The backend already supports
the operation (`PATCH /api/projects/{id}/pinned`, emits
`PROJECT_PINNED_UPDATED`). The frontend `projectsApi.setProjectPinned`
call already exists.

**Fix.** Mirror the pin affordance from `PersonaItem` /
`PersonasTab` PersonaRow. The simplest implementation: add a small pin
toggle button to each project row in `ProjectsTab`, positioned analogue
to the persona row's pin button. Click toggles via
`projectsApi.setProjectPinned(projectId, !pinned)`. The store updates
itself from `PROJECT_PINNED_UPDATED` so the badge / button state
re-renders without a follow-up fetch.

**Files.**
- `frontend/src/app/components/user-modal/ProjectsTab.tsx` — add pin
  button to each row.

**Manual verification.**
1. Open User overlay → Projects tab.
2. Click pin button on an unpinned project. Badge / icon flips to
   pinned. Sidebar Projects section gains the project.
3. Click pin again. Badge flips back. Project leaves the sidebar
   pinned-list.
4. With multiple users / sessions: pin on session A, observe pin state
   reflected on session B without manual refresh.

---

## 2. Sidebar Projects section: non-pinned fill + "More…" button (issues c, d)

**Symptom.** The sidebar's Projects section only renders pinned
projects. Personas and History sections additionally fill remaining
slots with most-recent non-pinned items and offer a "More…" button to
open the full list. Projects lacks both behaviours.

**Root cause.** The Projects ZoneSection in `Sidebar.tsx` was wired to
`useFilteredPinnedProjects()` only; the equivalent
`useFilteredProjects()` selector exists in `useProjectsStore.ts` but is
not used here. The `ZoneSection` "More…" button is rendered when
`!isEmpty`, so it'll show automatically once non-pinned data is
threaded through.

**Fix.** Within the Projects ZoneSection in `Sidebar.tsx`:

1. Pull `useFilteredProjects()` for the full sanitised-aware list.
2. Build the rendered list as: pinned projects (sorted by recency) +
   non-pinned projects (sorted by recency), capped at `visibleCount`.
3. Pass the same "More…" trigger as the Personas/History sections —
   reuses the existing User-overlay → Projects tab as the destination.

The ordering rule mirrors Personas: pinned always first, non-pinned
fill the rest of the slots.

**Files.**
- `frontend/src/app/components/sidebar/Sidebar.tsx` — replace the
  `useFilteredPinnedProjects` slice with a combined list.

**Manual verification.**
1. Have ≥ 1 pinned and ≥ 2 non-pinned projects.
2. Open sidebar. Projects section shows pinned first, then non-pinned,
   limited by available slots.
3. Click "More…" — User overlay opens to the Projects tab.
4. With 0 pinned + 0 non-pinned the section behaves exactly as today
   (empty state).

---

## 3. Overlay-then-navigate race: `startRouteTransition` (issue b)

**Symptom.** "Start chat here" in the project's Personas tab and "New
chat" in the persona overlay both succeed at backend session creation
(POST `/api/chat/sessions` returns 201 with the right `project_id`)
but no chat opens. The overlay closes; the URL appears unchanged.

**Root cause.** `useBackButtonClose` (Phase: browser-back-closes-overlay)
pushes a phantom `history` entry on overlay open and fires
`window.history.back()` from its cleanup when the overlay closes. The
mechanism has a sibling `startOverlayTransition()` for
overlay-to-overlay swaps that converts the next push into a
`replaceState`, but no equivalent for overlay-to-route transitions.

So the sequence

1. `await chatApi.createSession(...)` → 201
2. `onClose()` (overlay state cleared, unmount queued)
3. `navigate('/chat/<persona>/<session>')` → `pushState`
4. React commits, cleanup runs → `window.history.back()`
5. Browser pops the new chat entry; URL reverts.

…leaves the user where they started.

**Fix.** Introduce a `startRouteTransition()` helper analogous to
`startOverlayTransition`, in `useBackButtonClose.ts`. When a caller is
about to navigate to a new route AND close the overlay, it calls
`startRouteTransition(overlayId)` first. The overlay's cleanup, when
it sees the matching pending transition, skips the `history.back()`
call (the route change has already replaced the phantom entry's slot
in spirit).

Apply the helper at three call-sites:

1. `frontend/src/features/projects/tabs/ProjectPersonasTab.tsx` —
   `handleStartChat`, before the navigate.
2. `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx` —
   `onNewChat`, `onContinue`, `onNewIncognitoChat`, before the
   `onNavigate(...)` call.
3. Audit other overlay callers that do
   `onNavigate(...) → onClose()` for the same pattern (search:
   `onNavigate?.(\`/chat`).

A single helper avoids per-overlay if-tracking; one global flag with a
`setTimeout(0)` self-clear (matching `startOverlayTransition`) keeps
the API trivial.

**Files.**
- `frontend/src/core/hooks/useBackButtonClose.ts` — add
  `startRouteTransition`, branch in cleanup.
- Three callers above.

**Manual verification.**
1. Open project detail overlay → Personas tab → click "Start chat
   here" on a persona. Overlay closes, chat URL is `/chat/<persona>/
   <session>`, the new chat shows.
2. Open User overlay → Personas → click a persona row → Persona
   overlay → "New chat". Persona overlay closes, chat URL changes to
   the new chat.
3. Open the same Persona overlay → "Continue". Same outcome with
   most-recent session.
4. Browser back from the new chat returns to the page where the user
   was before opening the overlay (i.e., back behaviour did not
   double-pop).

---

## 4. Active-session project state ownership (issue e3, fixes e1/e2/e6 too)

**Symptom.** For a chat that is already project-bound, the chat
top-bar's `ProjectSwitcher` displays the chip as "No project" and
clicks on dropdown entries appear to do nothing. After reload the
state is the same. New global chats (no project) work fine; switching
them to a project works on the first switch in the same session.

**Root cause.** `useChatSessions()` calls `chatApi.listSessions()`
without parameters, and the backend's default behaviour excludes
project-bound chats (`exclude_in_projects=True`) so the global sidebar
list stays clean. `Topbar.tsx` looks up the active session in
`sessions.find((s) => s.id === sessionId)`. For project-bound chats
that lookup returns `undefined`, the switcher receives
`currentProjectId={null}`, and the `CHAT_SESSION_PROJECT_UPDATED` event
handler on `useChatSessions` no-ops because the session isn't in
`prev` to map over.

The event-bus path is fine; the bug is that the topbar's only source
of truth for `project_id` is a list that excludes the very entry it
needs.

**Fix.** Surface the active-session `project_id` through the chat
store (which ChatView already populates from `chatApi.getSession`).

1. Add `activeProjectId: string | null` to `useChatStore`
   (`frontend/src/core/store/chatStore.ts`), with setter
   `setActiveProjectId`.
2. In `ChatView.tsx`, where `getSession(sessionId)` resolves and the
   other fields are pushed into `useChatStore` (`setSessionTitle`,
   `setToolsEnabled`, …), also call
   `setActiveProjectId(session.project_id ?? null)`. Reset to `null`
   when ChatView unmounts or when sessionId changes.
3. Subscribe in the store (or in ChatView) to
   `CHAT_SESSION_PROJECT_UPDATED` and update `activeProjectId` when
   the event's `session_id` matches the active session.
4. In `Topbar.tsx`, replace `session?.project_id ?? null` with
   `useChatStore((s) => s.activeProjectId)`. The fallback "session
   isn't in the list yet" path is no longer needed because the store
   is now the source of truth.

The global `useChatSessions` keeps its current default-exclusion
behaviour (sidebar/history-tab semantics unchanged).

**Files.**
- `frontend/src/core/store/chatStore.ts` — new state slice + setter.
- `frontend/src/features/chat/ChatView.tsx` — set on session load,
  reset on unmount.
- `frontend/src/app/components/topbar/Topbar.tsx` — read from store.
- Optionally `frontend/src/core/hooks/useChatSessions.ts` — leave as
  is (its event handler still keeps non-active project assignments
  fresh in the global list for HistoryTab fallback).

**Manual verification.**
1. Open a chat that is already in a project (project-bound, was set
   yesterday). Top-bar chip shows the correct project emoji + title,
   ▾ picker has that project marked as selected.
2. Use ▾ picker to switch the chat to a different project. Chip
   updates, picker selection updates, project-detail-overlay's chats
   list reflects the change in both source and destination project.
3. Use ▾ picker to detach to "No project". Chip switches to "—" /
   "No project". Sidebar starts showing the chat (next refetch). The
   project's chats list no longer contains it.
4. Refresh the page on a project-bound chat — chip remains correct
   immediately on load.
5. Open a global chat (no project), switch into a project. Chip
   updates immediately (regression check for the previously-working
   path).

---

## 5. HistoryTab: render timestamps in local time (issue e4)

**Symptom.** Project-detail-overlay → Chats tab and User-overlay →
History show timestamps such as "5. Mai, 04:39" that are UTC, not the
client's local time.

**Root cause.** Wherever the row's date is formatted, the formatter is
either calling `toLocaleString` with an explicit UTC timezone option,
slicing the ISO string by index, or otherwise short-circuiting locale
behaviour.

**Fix.** Format with the user's local timezone — i.e., construct a
`Date` from the ISO string and call `toLocaleString` (or
`toLocaleTimeString` / `toLocaleDateString`) without a `timeZone`
override. Locale defaults to the browser's; that matches the user's
expectation.

**Files.**
- `frontend/src/app/components/user-modal/HistoryTab.tsx` (formatter
  in row render or the `groupSessions` helper, whichever owns the
  display).
- Audit any nearby utility that formats `updated_at` for the same
  treatment.

**Manual verification.**
1. With browser timezone set to CEST (UTC+2): a chat last updated at
   `2026-05-05T02:39:00Z` shows "04:39" (or matching locale style).
2. Switch browser timezone to UTC and reload — same chat shows
   "02:39".
3. Date grouping ("Today", "Yesterday", earlier) honours the local day
   boundary, not the UTC one.

---

## 6. Neutral-trigger session creation: persona-loaded race (issue e5)

**Symptom.** Starting a new chat with a persona whose
`default_project_id` points at a project — via the sidebar, persona
overlay "New chat", or User-overlay → Personas → row → New chat —
sometimes lands the new session in "global / no project" instead of
the persona's default project.

**Root cause.** The `?new=1` flow on `ChatView.tsx:174` reads
`persona?.default_project_id ?? null`. `persona` is derived from
`usePersonas()` and is `null` until that fetch completes. If the
resolve effect runs while `persona` is still `null`, `defaultProjectId`
is `null` and `chatApi.createSession(personaId, null)` creates a
project-less session. The effect re-runs once persona arrives, but by
then `sessionId` is in the URL and `forceNew` is false — so the
already-created session keeps its empty `project_id`.

The dependency array does include `persona?.default_project_id`, which
prevents the effect re-running with stale data, but the *first* run
happens before persona resolution.

**Fix.** Defer the `forceNew` branch until persona has loaded. Two
acceptable shapes:

(A) Gate on `persona !== null`: in the `forceNew` branch, return early
if `persona` is `null` so the effect re-fires once `persona` becomes
available.

(B) Keep the same gate, but additionally clear an explicit
`personaResolved` ref after first non-null observation so a subsequent
prop flip back to `null` (rare but possible during persona deletes)
doesn't deadlock.

(A) is simpler; pick that unless audit reveals (B) is necessary.

The non-`forceNew` branch (resume-or-create-latest) has the same race;
gate it too.

**Files.**
- `frontend/src/features/chat/ChatView.tsx` — gate the resolve effect.
- Cover with a Vitest unit test that mounts ChatView with `persona =
  null`, then transitions to `persona = { default_project_id: 'p1' }`,
  and asserts `createSession` was called with `'p1'`.

**Manual verification.**
1. From a clean page reload, click a sidebar persona-pin that has a
   `default_project_id`. The new chat is in that project (verify via
   the topbar `ProjectSwitcher` chip, after fix §4 is also applied).
2. Same from User overlay → Personas → row → Persona overlay → New
   chat. Same outcome.
3. From the project-detail-overlay → Personas tab → "Start chat here"
   path (this one already passes `projectId` directly to
   `createSession`, so no regression expected — confirm anyway).

---

## Cross-cutting notes

- **Module boundaries.** All changes are within already-public APIs.
  No module imports an internal of another. `chatStore` already lives
  in `core/store`, so cross-feature use is allowed.
- **Backwards compatibility.** No data-model changes, no migrations.
  All chats keep their existing `project_id` values.
- **Build verification.** `pnpm run build` (full `tsc -b`, not just
  `--noEmit`) and the relevant `vitest` tests must pass before merge.
  See CLAUDE.md note about the strict-build difference.
- **Subagent dispatch.** Most fixes are standalone, but §4 and §6 both
  touch `ChatView.tsx`, so they must be serialised against each other
  (or merged into one subagent). §3 also touches
  `PersonaOverlay.tsx`; §4 doesn't, but the test surface overlaps so
  serialise §3 → §4 to make verification straightforward. Final order
  and parallelism is decided in the implementation plan. Every
  dispatch prompt MUST include "do not merge, do not push, do not
  switch branches" (per recurring guidance).

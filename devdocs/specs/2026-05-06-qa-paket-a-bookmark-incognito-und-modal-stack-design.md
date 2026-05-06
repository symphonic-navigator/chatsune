# QA Paket A — Bookmark in Incognito + UserModal stays open after Start Chat

Date: 2026-05-06
Status: Draft, ready for implementation

This spec covers two unrelated, small frontend bugs reported by Ksena
(QA) on 2026-05-06. They are bundled because both are quick, isolated
changes with no shared surface, suitable for a single subagent dispatch.

The two bugs are not architecturally related. They are grouped by
delivery cadence only.

---

## 1. Bookmark option appears in Incognito chat, but bookmarks are unusable later

**Symptom.** In an incognito chat (URL search param `?incognito=1`),
the bookmark control appears under each assistant message and lets the
user save a bookmark. Later, opening that bookmark from the bookmark
menu errors because the underlying session does not exist — incognito
sessions are not persisted.

**Root cause.** `ChatView.tsx` passes the bookmark callback to
`MessageList` / `AssistantMessage` unconditionally. `AssistantMessage`
renders the bookmark button whenever its `onBookmark` prop is set
(`AssistantMessage.tsx:302-310`). There is no incognito gate on this
prop. The save handler (`ChatView.tsx:1600-1608`) writes a bookmark
referencing `effectiveSessionId`, which in incognito mode is the
ephemeral incognito UUID held in `incognitoIdRef.current` — that ID is
never persisted server-side, so the bookmark refers to a session that
will not exist on read-back. The incognito banner already lists what
incognito mode does not do ("No messages stored", "No memory updated",
"No journal entries") but does not currently mention bookmarks.

**Fix.** Block bookmark UI in incognito mode and make the banner
honest about it. No data migration, no soft-hide, no graceful-failure
on read of legacy broken bookmarks — existing broken bookmarks from
testers' incognito sessions stay in the database. Testers will be told
via Discord to delete them manually.

**Files.**
- `frontend/src/features/chat/ChatView.tsx` — at the call site that
  passes `onBookmark` down to `MessageList`, gate the prop on
  `!isIncognito`. When incognito, pass `undefined` (or omit) so the
  button is not rendered.
- `frontend/src/features/chat/ChatView.tsx:145` — the incognito banner
  text. Add "No bookmarks" to the existing list of disabled
  capabilities, in the same style and position as the other entries.

**Out of scope.**
- Cleanup of existing broken bookmarks in MongoDB.
- Filtering broken bookmarks out of the bookmark menu list.
- Graceful "this bookmark is no longer available" UI on open failure.

If a future report indicates the manual-cleanup story is too painful
in the field, revisit with one of the soft-hide / cleanup options.

**Manual verification.**
1. Open an incognito chat (`?incognito=1`). Send a message, receive an
   assistant reply. Confirm the bookmark control is absent from the
   action row under the assistant message.
2. Confirm the incognito banner now lists "No bookmarks" alongside
   the existing "No messages stored" / "No memory updated" / "No
   journal entries" items.
3. Open a normal (non-incognito) chat. Confirm the bookmark button is
   still present and saving a bookmark works as before.
4. From the bookmark menu, open a bookmark on a still-existing
   non-incognito session. Confirm scroll-to-message still works.

---

## 2. UserModal stays open after starting a chat from inside it

**Symptom.** Flow: USER button (bottom-left) opens UserModal → Chats
tab → Projects sub-tab → click a project (opens ProjectDetailOverlay
on top of UserModal) → Personas tab inside that overlay → click
"START CHAT HERE". The ProjectDetailOverlay closes (correct), the
route navigates to `/chat/:personaId/:sessionId`, and the chat appears
— but UserModal stays mounted on top, so the new chat is partially
hidden behind it. The user has to close UserModal manually.

The same bug class likely affects any path that starts a chat from
inside UserModal (e.g. picking an existing chat from the History tab
in the modal). The fix is generic.

**Root cause.** UserModal's open state is local `useState` in
`AppLayout.tsx:141` (`const [modalOpen, setModalOpen] = useState(false)`).
ProjectDetailOverlay's open state lives in a Zustand store
(`useProjectOverlayStore`). The `handleStartChat` callback in
`ProjectPersonasTab.tsx:94-116` calls `onClose()` for
ProjectDetailOverlay only — it has no reference to the UserModal
close handler. There is no central "dismiss-all-overlays" mechanism.

**Fix.** Add a route-based auto-close in `AppLayout`. Whenever the
location pathname changes to a path that starts with `/chat/`, set
`modalOpen` to false. This is a single `useEffect` on
`location.pathname`. It fixes the reported flow and, by being generic,
fixes any other Start-Chat-from-UserModal path that may exist now or
later.

The route-based approach was chosen over (a) prop-drilling
`closeUserModal` through ProjectDetailOverlay → ProjectPersonasTab and
(b) migrating UserModal to a Zustand store with a `dismissAll()`
helper. (a) only fixes this one path and adds prop drilling.
(b) is cleaner architecturally but is a larger refactor than the bug
warrants; the existing pattern split (UserModal local state,
ProjectOverlay Zustand) is acceptable until a different pressure
demands consolidation.

**Files.**
- `frontend/src/app/layouts/AppLayout.tsx` — add a `useEffect` on
  `[location.pathname]` (location already in scope or fetched via
  `useLocation()`), with body
  `if (location.pathname.startsWith('/chat/')) setModalOpen(false)`.

**Out of scope.**
- Any other modal/overlay close behaviour.
- Migrating UserModal state to a Zustand store.
- Introducing a global dismiss-all mechanism.

**Edge cases handled by the chosen approach.**
- User opens UserModal while already inside a chat (`/chat/X`):
  pathname does not change on open, so the effect does not fire,
  modal stays open. Correct.
- User opens UserModal at `/chat/X`, navigates to a different chat
  `/chat/Y` from within: pathname changes, effect fires, modal
  closes. Correct.
- User opens UserModal outside any chat (e.g. on `/`), then starts a
  chat: pathname changes from `/` to `/chat/...`, effect fires,
  modal closes. Correct.
- User opens UserModal, clicks a non-routing button (settings tab,
  tab switch inside modal): pathname does not change, modal stays
  open. Correct.

**Manual verification.**
1. From any non-chat route, open UserModal → Chats → Projects → pick
   any project → Personas tab inside ProjectDetailOverlay → click
   "START CHAT HERE". UserModal must close, ProjectDetailOverlay must
   close, and the new chat must be fully visible.
2. While inside a chat (`/chat/X`), open UserModal → History tab →
   click a different existing chat. Confirm the modal closes on
   navigation to `/chat/Y`.
3. While inside a chat, open UserModal → click around (Memory tab,
   Personas tab inside the modal, etc.) without triggering chat
   navigation. Confirm the modal stays open.
4. Open UserModal at `/`, switch tabs inside the modal without
   navigating to a chat. Confirm the modal stays open.

---

## Build verification

- `pnpm run build` (frontend) clean — per CLAUDE.md, `tsc -b` in
  `pnpm run build` catches stricter type errors than `pnpm tsc
  --noEmit`.
- No backend changes in this spec — no `uv run python -m py_compile`
  needed.

## Implementation notes

- Both fixes are frontend-only.
- No new dependencies.
- No new tests required for these surface-level UI gates; rely on
  manual verification above. Adding a unit test for the route-based
  auto-close in AppLayout is acceptable but not required.
- Subagent dispatch must include the standard "do not merge, do not
  push, do not switch branches" constraint per project memory.

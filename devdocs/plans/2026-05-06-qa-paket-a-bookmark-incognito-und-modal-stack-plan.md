# QA Paket A — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two unrelated frontend bugs reported by Ksena (QA): the
bookmark control appearing inside Incognito chats (which produces
unusable bookmarks), and the UserModal staying open behind a freshly
started chat when "Start Chat" is triggered from inside the modal stack.

**Architecture:** Both fixes are frontend-only. Bug #1 is a one-line
prop gate plus a one-line banner addition. Bug #5 is a single
`useEffect` in `AppLayout` that mirrors the existing pattern at
`AppLayout.tsx:56-66` (drawer-close-on-route-change), watching
`location.pathname` and closing the UserModal when the user navigates
into `/chat/...`.

**Tech Stack:** React + TypeScript (TSX), Vite, react-router-dom v6
(`useLocation`), pnpm.

**Spec:** `devdocs/specs/2026-05-06-qa-paket-a-bookmark-incognito-und-modal-stack-design.md`

**Subagent constraint:** Per project memory, subagents must NOT
merge, push, or switch branches. Implement on the current branch,
commit per task, stop. The dispatching agent will handle merge.

---

## File map

```
frontend/src/
  features/
    chat/ChatView.tsx          [MODIFY] — Task 1
  app/
    layouts/AppLayout.tsx      [MODIFY] — Task 2
```

The two tasks touch separate files and can run in parallel if
dispatched as separate subagents. Sequential execution is also fine.

No automated tests are added for these changes. Both are tiny UI
gates (one prop conditional, one `useEffect` mirroring an existing
pattern) and component-level integration tests for `ChatView` /
`AppLayout` would require heavy mocking out of proportion to the
change. Manual verification on a real device is the primary check —
this matches the project's standing convention for surface-level UI
fixes.

---

## Task 1: Block bookmarks in Incognito + extend the Incognito banner (Bug #1)

**Files:**
- Modify: `frontend/src/features/chat/ChatView.tsx`

- [ ] **Step 1: Locate the two change sites in `ChatView.tsx`**

Search for the existing landmarks. Expected locations (line numbers
may shift slightly — match by content):

- `onBookmark` prop on the `<MessageList>` element, currently around
  line 1520:
  ```tsx
  onBookmark={(msgId) => setBookmarkTargetMsgId(msgId)}
  ```
- The Incognito info popup `<ul>` listing disabled capabilities,
  currently around lines 1274-1278:
  ```tsx
  <ul ...>
    <li>No messages stored</li>
    <li>No memory updated</li>
    <li>No journal entries</li>
  </ul>
  ```

The `isIncognito` flag is already in scope at this level
(`ChatView.tsx:137`: `const isIncognito = searchParams.get('incognito') === '1'`).

- [ ] **Step 2: Gate the `onBookmark` prop on `!isIncognito`**

Change the line:
```tsx
onBookmark={(msgId) => setBookmarkTargetMsgId(msgId)}
```
to:
```tsx
onBookmark={isIncognito ? undefined : (msgId) => setBookmarkTargetMsgId(msgId)}
```

Rationale: `AssistantMessage` already gates rendering on the
presence of the `onBookmark` callback (`AssistantMessage.tsx:302-310`,
`{onBookmark && (...)}`), so passing `undefined` removes the button
without further changes. If TypeScript complains that the prop is
non-optional on `MessageListProps` or `AssistantMessageProps`, make
it optional (`onBookmark?: (msgId: string) => void`) — this matches
the existing render gate in `AssistantMessage.tsx`.

- [ ] **Step 3: Add the "No bookmarks" line to the Incognito banner**

Change the `<ul>`:
```tsx
<ul ...>
  <li>No messages stored</li>
  <li>No memory updated</li>
  <li>No journal entries</li>
</ul>
```
to:
```tsx
<ul ...>
  <li>No messages stored</li>
  <li>No memory updated</li>
  <li>No journal entries</li>
  <li>No bookmarks</li>
</ul>
```

Preserve whatever className / spacing styling the surrounding `<li>`
elements use — copy from a sibling. No other text changes.

- [ ] **Step 4: Build verification**

Run from `frontend/`:
```bash
pnpm run build
```
Expected: clean build, no TypeScript errors. (`pnpm tsc --noEmit`
is insufficient — `tsc -b` inside `pnpm run build` catches stricter
errors that CI uses.)

- [ ] **Step 5: Manual verification (real device or browser)**

Start the dev server (`pnpm run dev` from `frontend/`) and walk
through:

1. Open an Incognito chat (`?incognito=1` on the chat URL, or via
   whatever Incognito entry the UI exposes). Send a message, get an
   assistant reply. **Expect:** no bookmark control under the
   assistant message action row.
2. Hover/tap the Incognito info icon at the top of the chat.
   **Expect:** the popup `<ul>` now lists four items including
   "No bookmarks".
3. Open a normal (non-Incognito) chat. Send/receive a message.
   **Expect:** the bookmark button is present and clicking it opens
   the bookmark-save dialog as before.
4. From the bookmark menu, open an existing bookmark on a normal
   session. **Expect:** scroll-to-message still works — no
   regression on the read path.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/chat/ChatView.tsx
git commit -m "Block bookmarks in incognito chat and add 'No bookmarks' to the incognito banner"
```

---

## Task 2: Auto-close UserModal on navigation into a chat route (Bug #5)

**Files:**
- Modify: `frontend/src/app/layouts/AppLayout.tsx`

- [ ] **Step 1: Locate the existing pattern and the UserModal state**

Open `frontend/src/app/layouts/AppLayout.tsx` and confirm two
landmarks:

- `useLocation()` is already imported and used:
  ```ts
  const location = useLocation()  // around line 51
  ```
- The UserModal `useState` flag is around line 141:
  ```ts
  const [modalOpen, setModalOpen] = useState(false)
  ```
- The existing drawer-close-on-route-change `useEffect` is at lines
  56-66 (the new effect should sit near it for visual proximity, or
  near the `modalOpen` state — pick whichever keeps `setModalOpen`
  in scope without forward references; the `modalOpen` state is
  declared at line 141, so place the new effect AFTER that line):
  ```ts
  useEffect(() => {
    if (!isDesktop && drawerOpen) {
      closeDrawer()
    }
  }, [location.pathname, isDesktop, drawerOpen, closeDrawer])
  ```

- [ ] **Step 2: Add the route-based UserModal auto-close effect**

Add the following `useEffect` immediately after the `setModalOpen`
state declaration (so `setModalOpen` is in scope):

```tsx
// Close the UserModal when the user navigates into any chat route.
// This covers Start-Chat actions triggered from inside the modal
// stack (e.g. Project Personas tab, History tab) — the modal would
// otherwise stay mounted on top of the freshly opened chat.
useEffect(() => {
  if (location.pathname.startsWith('/chat/')) {
    setModalOpen(false)
  }
}, [location.pathname])
```

ESLint may warn about an exhaustive-deps miss for `setModalOpen`;
React's `setState` setters are stable identities and adding them is
cosmetic. If the project's lint config insists, add `setModalOpen`
to the deps array — both forms are correct.

- [ ] **Step 3: Build verification**

Run from `frontend/`:
```bash
pnpm run build
```
Expected: clean build, no TypeScript errors.

- [ ] **Step 4: Manual verification (real device or browser)**

With dev server running:

1. From the home / non-chat route, open UserModal → Chats tab →
   Projects sub-tab → click any project → Personas tab inside the
   ProjectDetailOverlay → "START CHAT HERE". **Expect:** the
   ProjectDetailOverlay closes (existing behaviour), the new chat
   appears, and UserModal is closed — the chat is fully visible.
2. While inside an existing chat (`/chat/X/...`), open UserModal →
   History tab → click a different existing chat. **Expect:** the
   route changes to `/chat/Y/...` and UserModal closes.
3. While inside a chat, open UserModal and click around inside it
   (Memory tab, Personas tab, Settings, etc.) without triggering
   any chat navigation. **Expect:** UserModal stays open the whole
   time.
4. From the home route, open UserModal and switch tabs inside it
   without navigating to a chat. **Expect:** UserModal stays open.
5. Sanity check: do the two existing in-chat overlays (PersonaOverlay,
   AdminModal) still open and close correctly? They are independent
   state and should be unaffected, but a quick check protects against
   accidental cross-effects.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/layouts/AppLayout.tsx
git commit -m "Auto-close UserModal when navigating into a chat route"
```

---

## Self-review (already performed during plan writing)

- Spec coverage: §1 of the spec maps to Task 1 (both prop gate and
  banner extension), §2 maps to Task 2 (route-based auto-close).
- Placeholder scan: clean — no TBDs, all code blocks complete,
  exact file paths.
- Type consistency: `onBookmark` is referenced consistently
  throughout; the new effect's deps array is explicit.
- The Explore agent originally pointed at `ChatView.tsx:145` for
  the banner, which is wrong (that line is a guard inside an
  unrelated `useEffect`). Task 1 Step 1 corrects this and points
  the implementer at the actual `<ul>` site (~line 1274) via
  content match.

# Projects feature bug fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix six bugs / gaps in the Projects (Mindspace) feature: pin
control on the User-overlay Projects page, sidebar projects fill +
"More…" button, overlay-then-navigate race, in-chat project switcher
not reflecting state for project-bound chats, UTC vs. local timestamps
in HistoryTab, and a persona-loaded race in the neutral-trigger session
create flow.

**Architecture:** All changes are scoped to the frontend. They follow
existing patterns: pin button mirrors `PersonaItem`, sidebar fill
mirrors the personas zone, route-transition helper mirrors the
existing `startOverlayTransition` helper, active-session project state
goes through `useChatStore` (which already owns active session
properties such as title, toolsEnabled, etc.), and the time formatter
uses the browser locale.

**Tech Stack:** React + TypeScript (TSX), Vite, Tailwind, Vitest,
react-router-dom v6, Zustand store.

**Spec:** `devdocs/specs/2026-05-05-projects-bugs-fixes-design.md`

---

## File map

```
frontend/src/
  core/
    hooks/useBackButtonClose.ts                 [MODIFY] — Task 3
    hooks/__tests__/useBackButtonClose.test.tsx [MODIFY] — Task 3
    store/chatStore.ts                          [MODIFY] — Task 4
  app/
    components/user-modal/ProjectsTab.tsx       [MODIFY] — Task 1
    components/user-modal/HistoryTab.tsx        [MODIFY] — Task 5
    components/sidebar/Sidebar.tsx              [MODIFY] — Task 2
    components/topbar/Topbar.tsx                [MODIFY] — Task 4
    components/persona-overlay/PersonaOverlay.tsx [MODIFY] — Task 3
  features/
    chat/ChatView.tsx                            [MODIFY] — Task 4 + Task 6
    projects/tabs/ProjectPersonasTab.tsx        [MODIFY] — Task 3
```

**Serialisation note.** Tasks 4 and 6 both touch `ChatView.tsx`. Run
Task 4 to completion (commit) before starting Task 6, or merge them in
a single subagent. Other tasks have no overlapping files and may run
in parallel.

---

## Task 1: Pin / unpin control on User-overlay Projects page (issue a)

**Files:**
- Modify: `frontend/src/app/components/user-modal/ProjectsTab.tsx`
- Test: there are no Vitest tests on this file today; rely on manual
  verification (frontend lacks integration coverage here, in line with
  similar UI tasks in this codebase). If a `__tests__/ProjectsTab.test.tsx`
  exists at implementation time, extend it instead.

- [ ] **Step 1: Read existing pattern**

Reference for the pin affordance: the persona row pin button in
`frontend/src/app/components/user-modal/PersonasTab.tsx:139-155`
(orange-tinted icon with click → `onTogglePin`, `e.stopPropagation()`
to keep the row click intact). Mirror its visual weight and ARIA
labelling. The project pinned-badge currently lives at
`ProjectsTab.tsx:221-228` — keep the badge for consistency or remove
it if the toggle button visually replaces it; pick one in step 3 and
note the choice in the commit message.

- [ ] **Step 2: Add the pin button**

In the project row component (the `<button data-testid="project-row">`
at `ProjectsTab.tsx:200-241`), the outer element is itself a `<button>`.
A nested `<button>` for pin is invalid HTML, so first restructure the
row body to be a `<div>` with the row click handler, OR keep the outer
`<button>` and put the pin button absolutely positioned (mirror
`PersonaItem.tsx`).

Mirror the persona-tab pattern:
- Outer wrapper switches to a `<div>` styled identically.
- Two children: a clickable area (covers most of the row, calls
  `onOpen`) and a small fixed-position pin button at the right that
  calls `onTogglePin` with `e.stopPropagation()`.
- Pin button uses `projectsApi.setPinned(project.id, !project.pinned)`.
- ARIA label `Pin project` / `Unpin project`.
- `data-testid="project-pin-toggle"` for future tests.

The store updates itself from the `PROJECT_PINNED_UPDATED` event so no
local state mutation is needed.

- [ ] **Step 3: Decide on the badge**

Either leave the existing `project-pinned-badge` in place (informative,
matches persona row's chakra-coloured ring style), or remove it — the
pin button colour now signals state. Recommendation: keep the badge,
mirrors persona row.

- [ ] **Step 4: Build verification**

Run from repo root:

```bash
cd frontend && pnpm run build
```

Expected: clean `tsc -b` output and successful Vite build.

- [ ] **Step 5: Manual verification**

Follow steps 1–4 of "Manual verification" in spec §1. If pin state
doesn't reflect across sessions, check that the `PROJECT_PINNED_UPDATED`
subscription in `useProjectsStore.ts` is intact.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/components/user-modal/ProjectsTab.tsx
git commit -m "Add pin toggle to user-overlay Projects-tab rows"
```

---

## Task 2: Sidebar Projects section — non-pinned fill + "More…" (issues c, d)

**Files:**
- Modify: `frontend/src/app/components/sidebar/Sidebar.tsx` (around
  lines 811–840 for the Projects ZoneSection; line 171 for the
  `useFilteredPinnedProjects()` import)

- [ ] **Step 1: Confirm hook availability**

Confirm `useFilteredProjects` is exported from
`frontend/src/features/projects/useProjectsStore.ts` and returns the
NSFW-filtered list of all projects (pinned + non-pinned). If only
`useFilteredPinnedProjects` exists, add `useFilteredProjects` first
(mirror the personas store; the spec assumes it exists already per
the explorer's earlier finding).

- [ ] **Step 2: Read the personas zone for reference**

Reference: how the Personas ZoneSection in `Sidebar.tsx` combines
pinned + non-pinned + "More…" — find it in the same file (search for
`useFilteredPersonas` or the personas ZoneSection block). Mirror its
slicing, ordering, and trigger.

- [ ] **Step 3: Replace the data source in the Projects zone**

Inside the Projects ZoneSection rendering block:

```tsx
const allProjects = useFilteredProjects()
const pinned = allProjects.filter((p) => p.pinned)
  .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
const nonPinned = allProjects.filter((p) => !p.pinned)
  .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
const ordered = [...pinned, ...nonPinned]
const visible = ordered.slice(0, visibleCount)
```

Render each entry with `ProjectSidebarItem`, just like before. The
ZoneSection's own "More…" trigger fires when the section is
non-empty; wire its `onMore` to open the User overlay → Projects tab
(mirror what the personas zone does for "More…").

- [ ] **Step 4: Build + manual verification**

```bash
cd frontend && pnpm run build
```

Then follow spec §2 manual verification (≥1 pinned + ≥2 non-pinned
projects, "More…" opens the User overlay → Projects tab).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/sidebar/Sidebar.tsx
git commit -m "Fill sidebar Projects with non-pinned and add More button"
```

---

## Task 3: `startRouteTransition` for overlay-then-navigate (issue b)

**Files:**
- Modify: `frontend/src/core/hooks/useBackButtonClose.ts`
- Modify: `frontend/src/core/hooks/useBackButtonClose.test.tsx`
- Modify: `frontend/src/features/projects/tabs/ProjectPersonasTab.tsx`
- Modify: `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx`
- Audit and possibly modify other call-sites — see step 6.

- [ ] **Step 1: Write the failing test**

Add a test in `frontend/src/core/hooks/useBackButtonClose.test.tsx`
that asserts: when `startRouteTransition(overlayId)` was called and
then the overlay closes, `window.history.back` is NOT invoked.

Skeleton (adjust to whatever testing harness the existing file uses,
likely Vitest + Testing Library renderHook):

```tsx
import { renderHook } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useBackButtonClose, startRouteTransition } from './useBackButtonClose'
import { useHistoryStackStore } from '../store/historyStackStore'

describe('useBackButtonClose — startRouteTransition', () => {
  beforeEach(() => {
    useHistoryStackStore.getState().clear()
    vi.spyOn(window.history, 'back').mockImplementation(() => {})
    vi.spyOn(window.history, 'pushState').mockImplementation(() => {})
    vi.spyOn(window.history, 'replaceState').mockImplementation(() => {})
  })

  it('skips history.back() when route transition is pending', async () => {
    const onClose = vi.fn()
    const { rerender, unmount } = renderHook(
      ({ open }: { open: boolean }) =>
        useBackButtonClose(open, onClose, 'test-overlay'),
      { initialProps: { open: true } },
    )
    // microtask queue runs the deferred push
    await Promise.resolve()
    startRouteTransition('test-overlay')
    rerender({ open: false })
    unmount()
    expect(window.history.back).not.toHaveBeenCalled()
  })

  it('still calls history.back() when no transition pending', async () => {
    const onClose = vi.fn()
    const { rerender, unmount } = renderHook(
      ({ open }: { open: boolean }) =>
        useBackButtonClose(open, onClose, 'test-overlay-2'),
      { initialProps: { open: true } },
    )
    await Promise.resolve()
    rerender({ open: false })
    unmount()
    expect(window.history.back).toHaveBeenCalledTimes(1)
  })
})
```

- [ ] **Step 2: Run the failing test**

```bash
cd frontend && pnpm vitest run src/core/hooks/useBackButtonClose.test.tsx
```

Expected: FAIL, `startRouteTransition is not exported`.

- [ ] **Step 3: Implement `startRouteTransition`**

In `frontend/src/core/hooks/useBackButtonClose.ts`, add a sibling
export to `startOverlayTransition` and check it in the cleanup:

```ts
let pendingRouteTransitionFrom: string | null = null

/**
 * Mark that a programmatic overlay close is happening because the user
 * navigated to a new route. The overlay's own cleanup will skip its
 * `window.history.back()` call when it sees a matching pending
 * transition — react-router has already pushed a new entry, and an
 * extra history.back() would race with it and revert the URL.
 *
 * Auto-clears via setTimeout(0) if no overlay claims it.
 */
export function startRouteTransition(fromOverlayId: string): void {
  pendingRouteTransitionFrom = fromOverlayId
  setTimeout(() => {
    if (pendingRouteTransitionFrom === fromOverlayId) {
      pendingRouteTransitionFrom = null
    }
  }, 0)
}
```

Then in the cleanup branch (currently around lines 87–98):

```ts
return () => {
  cancelled = true
  if (registeredRef.current) {
    registeredRef.current = false
    const { wasTop } = useHistoryStackStore
      .getState()
      .remove(overlayIdRef.current)
    const consuming =
      pendingRouteTransitionFrom === overlayIdRef.current
    if (consuming) {
      pendingRouteTransitionFrom = null
    }
    if (wasTop && !consuming) {
      window.history.back()
    }
  }
}
```

- [ ] **Step 4: Run the test, verify both cases pass**

```bash
cd frontend && pnpm vitest run src/core/hooks/useBackButtonClose.test.tsx
```

Expected: PASS for both cases.

- [ ] **Step 5: Apply at the ProjectPersonasTab call-site**

In `frontend/src/features/projects/tabs/ProjectPersonasTab.tsx`,
update `handleStartChat` (currently lines 93–111). The overlay's
`overlayId` for `useBackButtonClose` registration in
`ProjectDetailOverlay` lives in that file — find the literal id (e.g.
`'project-detail'`) before writing the call.

```ts
import { startRouteTransition } from '../../../core/hooks/useBackButtonClose'

async function handleStartChat(persona: PersonaDto) {
  setBusy(true)
  try {
    const session = await chatApi.createSession(persona.id, projectId)
    startRouteTransition('project-detail')   // exact id from ProjectDetailOverlay
    onClose()
    navigate(`/chat/${persona.id}/${session.id}`)
  } catch {
    addNotification({
      level: 'error',
      title: 'Could not start chat',
      message: 'Creating the new chat session failed.',
    })
  } finally {
    setBusy(false)
  }
}
```

- [ ] **Step 6: Apply at the PersonaOverlay call-sites**

In `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx`,
the overlay registers `useBackButtonClose` with its own id (find it,
likely `'persona-overlay'`). Update three handlers:

```tsx
onContinue={() => {
  const last = ...
  if (last) {
    startRouteTransition('persona-overlay')
    onNavigate?.(`/chat/${resolved.id}/${last.id}`)
    onClose()
  }
}}
onNewChat={() => {
  startRouteTransition('persona-overlay')
  onNavigate?.(`/chat/${resolved.id}?new=1`)
  onClose()
}}
onNewIncognitoChat={() => {
  startRouteTransition('persona-overlay')
  onNavigate?.(`/chat/${resolved.id}?incognito=1`)
  onClose()
}}
```

- [ ] **Step 7: Audit other overlay-then-navigate call-sites**

```bash
cd frontend && rg -n "onClose\(\)" src --type ts --type tsx -A 1 -B 2 | rg -A 2 -B 2 "navigate"
```

For each candidate, confirm whether the surrounding component is
inside an overlay registered with `useBackButtonClose`. If so, add a
`startRouteTransition(<overlayId>)` immediately before the navigate.
If not, leave it untouched.

- [ ] **Step 8: Build + manual verification**

```bash
cd frontend && pnpm run build && pnpm vitest run src/core/hooks/useBackButtonClose.test.tsx
```

Then walk through spec §3 manual verification (steps 1–4).

- [ ] **Step 9: Commit**

```bash
git add frontend/src/core/hooks/useBackButtonClose.ts \
        frontend/src/core/hooks/useBackButtonClose.test.tsx \
        frontend/src/features/projects/tabs/ProjectPersonasTab.tsx \
        frontend/src/app/components/persona-overlay/PersonaOverlay.tsx
git commit -m "Add startRouteTransition to fix overlay-then-navigate race"
```

---

## Task 4: Active-session `project_id` in `useChatStore` (issue e3 → fixes e1/e2/e6 too)

**Files:**
- Modify: `frontend/src/core/store/chatStore.ts`
- Modify: `frontend/src/features/chat/ChatView.tsx`
- Modify: `frontend/src/app/components/topbar/Topbar.tsx`
- Test: `frontend/src/core/store/__tests__/chatStore.test.ts` (or
  similar — check existing test structure)

- [ ] **Step 1: Write the failing store test**

Add to `frontend/src/features/chat/__tests__/chatStore.test.ts`
(existing file):

```ts
import { describe, it, expect, beforeEach } from 'vitest'
import { useChatStore } from '../../../core/store/chatStore'

describe('useChatStore — activeProjectId', () => {
  beforeEach(() => {
    useChatStore.getState().reset()
  })

  it('starts as null', () => {
    expect(useChatStore.getState().activeProjectId).toBeNull()
  })

  it('setActiveProjectId stores a project id', () => {
    useChatStore.getState().setActiveProjectId('p-1')
    expect(useChatStore.getState().activeProjectId).toBe('p-1')
  })

  it('setActiveProjectId(null) clears it', () => {
    useChatStore.getState().setActiveProjectId('p-1')
    useChatStore.getState().setActiveProjectId(null)
    expect(useChatStore.getState().activeProjectId).toBeNull()
  })

  it('reset() clears active project', () => {
    useChatStore.getState().setActiveProjectId('p-1')
    useChatStore.getState().reset()
    expect(useChatStore.getState().activeProjectId).toBeNull()
  })
})
```

- [ ] **Step 2: Run failing test**

```bash
cd frontend && pnpm vitest run src/features/chat/__tests__/chatStore.test.ts
```

Expected: FAIL — `activeProjectId` / `setActiveProjectId` undefined.

- [ ] **Step 3: Add to chatStore**

In `frontend/src/core/store/chatStore.ts`:

1. In the `ChatState` interface, add:
   ```ts
   activeProjectId: string | null
   setActiveProjectId: (projectId: string | null) => void
   ```
2. In `INITIAL_STATE`, add:
   ```ts
   activeProjectId: null as string | null,
   ```
3. In the store body (after the other setters), add:
   ```ts
   setActiveProjectId: (projectId) => set({ activeProjectId: projectId }),
   ```
4. The existing `reset` already spreads `INITIAL_STATE`, so reset will
   clear it automatically.

- [ ] **Step 4: Run test, verify pass**

```bash
cd frontend && pnpm vitest run src/features/chat/__tests__/chatStore.test.ts
```

Expected: PASS.

- [ ] **Step 5: Wire it from `ChatView.tsx`**

Find the `getSession(sessionId)` block in
`frontend/src/features/chat/ChatView.tsx` (around line 393). After the
existing `setSessionTitle`, `setToolsEnabled`, `setAutoRead`,
`setReasoningOverride` calls, add:

```ts
useChatStore.getState().setActiveProjectId(session.project_id ?? null)
```

When the session changes (sessionId becomes null on unmount or new
session), the existing `reset(sessionId?)` call in chatStore zeroes
`activeProjectId` automatically. No extra cleanup needed.

- [ ] **Step 6: Subscribe to `CHAT_SESSION_PROJECT_UPDATED`**

In the same `ChatView.tsx` file, near the other event-bus
subscriptions (the `setSessionPinned` event listener around line 433
is a good neighbour), add:

```ts
useEffect(() => {
  if (!sessionId) return
  const unsub = eventBus.on(
    Topics.CHAT_SESSION_PROJECT_UPDATED,
    (event: BaseEvent) => {
      if (event.payload.session_id === sessionId) {
        const next = (event.payload.project_id as string | null | undefined) ?? null
        useChatStore.getState().setActiveProjectId(next)
      }
    },
  )
  return () => unsub()
}, [sessionId])
```

Imports: `eventBus` from `core/websocket/eventBus`, `Topics` and
`BaseEvent` from `core/types/events` — match the imports already used
in the file.

- [ ] **Step 7: Read from chatStore in Topbar**

In `frontend/src/app/components/topbar/Topbar.tsx`, around line 224–238
where the `ProjectSwitcher` is rendered, replace the lookup:

Before:
```tsx
const sessionId = chatMatch.params.sessionId
const session = sessions.find((s) => s.id === sessionId)
return (
  <div className="ml-auto flex-shrink-0">
    <ProjectSwitcher
      sessionId={sessionId}
      currentProjectId={session?.project_id ?? null}
    />
  </div>
)
```

After:
```tsx
const sessionId = chatMatch.params.sessionId
const currentProjectId = useChatStore((s) => s.activeProjectId)
return (
  <div className="ml-auto flex-shrink-0">
    <ProjectSwitcher
      sessionId={sessionId}
      currentProjectId={currentProjectId}
    />
  </div>
)
```

Note: `useChatStore` must be called at the component top level, not
inside the IIFE expression. Restructure so the hook lives at the
component body level and the IIFE just renders. If the IIFE pattern
makes that awkward, replace it with a direct conditional render.

Also import `useChatStore` from `core/store/chatStore`.

The `sessions` prop is no longer needed for this branch but other
parts of `Topbar` may still use it — leave the prop in place.

- [ ] **Step 8: Build + Topbar Vitest tests**

```bash
cd frontend && pnpm run build
cd frontend && pnpm vitest run src/app/components/topbar
```

Expected: clean build; existing topbar tests should still pass (the
prop signature didn't change). If existing tests assert
`currentProjectId` resolution from the sessions array, update them to
seed `useChatStore.setState({ activeProjectId: '...' })` instead.

- [ ] **Step 9: Manual verification**

Walk through spec §4 steps 1–5. Pay particular attention to:
- Reload on a project-bound chat → chip immediately correct.
- Switching project on a project-bound chat → chip updates.
- Detaching to "No project" → chip updates.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/core/store/chatStore.ts \
        frontend/src/features/chat/__tests__/chatStore.test.ts \
        frontend/src/features/chat/ChatView.tsx \
        frontend/src/app/components/topbar/Topbar.tsx
git commit -m "Surface active-session project_id via useChatStore for in-chat switcher"
```

---

## Task 5: Local-time formatting in HistoryTab (issue e4)

**Files:**
- Modify: `frontend/src/app/components/user-modal/HistoryTab.tsx`

- [ ] **Step 1: Find the formatter**

Inside `HistoryTab.tsx`, locate where each session row's date /
time is rendered. Likely a small helper at the top of the file or
inline JSX using `new Date(updated_at)` or a substring slice.

```bash
cd frontend && rg -n "updated_at|toLocale|UTC|toISOString|new Date\(" src/app/components/user-modal/HistoryTab.tsx
```

Possible patterns to fix:
1. `new Date(s.updated_at).toLocaleString('en-GB', { timeZone: 'UTC' })`
2. Manual ISO string slicing: `s.updated_at.slice(11,16)`
3. Using a date-fns / dayjs helper with explicit UTC.

Pick the simplest fix that produces local-time output.

- [ ] **Step 2: Replace with locale defaults**

For day labels (Today / Yesterday / specific date), use a Date built
from the ISO string and compare to the local-day boundary:

```ts
const d = new Date(s.updated_at)         // ISO Z parses as UTC, Date stores instant
const local = d                          // toLocaleDateString uses local TZ by default
const today = new Date()
const todayKey = today.toLocaleDateString()
const yesterday = new Date(today)
yesterday.setDate(today.getDate() - 1)
const yesterdayKey = yesterday.toLocaleDateString()
const dayKey = local.toLocaleDateString()
const dayLabel =
  dayKey === todayKey ? 'Today'
  : dayKey === yesterdayKey ? 'Yesterday'
  : local.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
const timeLabel = local.toLocaleTimeString(undefined, {
  hour: '2-digit',
  minute: '2-digit',
})
```

If a `groupSessions` helper exists, push the change down into it so
both the group header and the row time agree on the local-day
boundary.

- [ ] **Step 3: Build + manual verification**

```bash
cd frontend && pnpm run build
```

Then follow spec §5 manual verification (timezone toggle, day-boundary
correctness).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/user-modal/HistoryTab.tsx
git commit -m "Render HistoryTab timestamps in client local time"
```

---

## Task 6: Persona-loaded race in neutral-trigger session create (issue e5)

> Run after Task 4 has committed (both touch `ChatView.tsx`).

**Files:**
- Modify: `frontend/src/features/chat/ChatView.tsx`
- Test: add to `frontend/src/features/chat/__tests__/ChatView.test.tsx`
  if it exists; otherwise create a focused new test for this behaviour.

- [ ] **Step 1: Write the failing test**

In a new or existing ChatView test file:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { ChatView } from '../ChatView'
import { chatApi } from '../../../core/api/chat'

vi.mock('../../../core/api/chat', () => ({
  chatApi: {
    createSession: vi.fn().mockResolvedValue({
      id: 's1', persona_id: 'p1', project_id: 'proj-1',
    }),
    listSessions: vi.fn().mockResolvedValue([]),
    getSession: vi.fn().mockResolvedValue({
      id: 's1', persona_id: 'p1', project_id: 'proj-1',
      title: null, pinned: false, tools_enabled: false,
      auto_read: false, reasoning_override: null,
    }),
  },
}))

describe('ChatView neutral-trigger persona race', () => {
  beforeEach(() => vi.clearAllMocks())

  it('waits for persona before creating a forceNew session', async () => {
    function Harness({ persona }: { persona: any }) {
      return (
        <MemoryRouter initialEntries={['/chat/p1?new=1']}>
          <Routes>
            <Route path="/chat/:personaId" element={<ChatView persona={persona} />} />
          </Routes>
        </MemoryRouter>
      )
    }
    const { rerender } = render(<Harness persona={null} />)
    // First effect run: persona is null. createSession must NOT be called yet.
    await new Promise((r) => setTimeout(r, 10))
    expect(chatApi.createSession).not.toHaveBeenCalled()
    // Persona arrives.
    rerender(<Harness persona={{ id: 'p1', default_project_id: 'proj-1' }} />)
    await waitFor(() => expect(chatApi.createSession).toHaveBeenCalledTimes(1))
    expect(chatApi.createSession).toHaveBeenCalledWith('p1', 'proj-1')
  })
})
```

If the existing test file mocks more dependencies (websocket store,
voice store, etc.) match the existing setup or add the missing mocks
until the test renders without crashing.

- [ ] **Step 2: Run failing test**

```bash
cd frontend && pnpm vitest run src/features/chat/__tests__/ChatView.test.tsx -t "persona race"
```

Expected: FAIL — `createSession` called with `null` project (persona
was null at first effect run).

- [ ] **Step 3: Gate the resolve effect on persona**

In `ChatView.tsx`, around the resolve effect that contains
`if (forceNew) { chatApi.createSession(...) }`, add an early return at
the top of the effect that bails when the persona is unresolved AND a
`forceNew` (or implicit-create-latest) path would be taken:

```ts
const personaId = ... // existing
const sessionId = ... // existing
const forceNew = searchParams.get('new') === '1'

useEffect(() => {
  // ... existing setup ...

  // Mindspace: defer creation until persona has loaded so its
  // default_project_id is available — otherwise the session is
  // created with project_id=null and stays project-less.
  if (!persona && (forceNew || !sessionId)) {
    return
  }

  // ... existing body unchanged ...
}, [searchParams, personaId, sessionId, navigate, isIncognito,
    resolveAttempt, persona /* whole persona, not just default_project_id */])
```

Replacing `persona?.default_project_id` with `persona` in the dep
array means any persona shape change re-runs the effect — that's the
correct behaviour (the effect should re-evaluate as soon as persona
exists).

- [ ] **Step 4: Run test, verify pass**

```bash
cd frontend && pnpm vitest run src/features/chat/__tests__/ChatView.test.tsx -t "persona race"
```

Expected: PASS.

- [ ] **Step 5: Build + full vitest sweep on chat**

```bash
cd frontend && pnpm run build
cd frontend && pnpm vitest run src/features/chat
```

Existing ChatView tests must still pass. If a regression appears,
investigate: most likely the early return needs a narrower condition
(only gate when `forceNew` or implicit-create paths apply).

- [ ] **Step 6: Manual verification**

Walk through spec §6 manual verification (steps 1–3). Verify the
chip in the topbar shows the correct project for newly-created
neutral-trigger chats — this is end-to-end coverage of Task 4 + Task
6 together.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/chat/ChatView.tsx \
        frontend/src/features/chat/__tests__/ChatView.test.tsx
git commit -m "Defer ChatView neutral-trigger create until persona resolves"
```

---

## Self-Review

**Spec coverage check:**

| Spec section | Plan task |
|---|---|
| §1 Pin control | Task 1 |
| §2 Sidebar fill + More | Task 2 |
| §3 startRouteTransition | Task 3 |
| §4 activeProjectId in chatStore | Task 4 |
| §5 Local time HistoryTab | Task 5 |
| §6 Persona race | Task 6 |
| Cross-cutting: build verification | Each task step "Build verification" |
| Cross-cutting: subagent dispatch note | Top-level "Serialisation note" |

All six spec sections are covered.

**Type / signature consistency:** `setActiveProjectId(projectId: string | null)` is consistent in Task 4 step 3, step 5, and step 6. `startRouteTransition(fromOverlayId: string)` is consistent across Task 3 steps 3, 5, 6.

**Open assumption:** Task 2 step 1 asks the implementer to confirm whether `useFilteredProjects` already exists; if not, add it before continuing. The explorer found the hook earlier so it should be present, but flagged as a verification step rather than relied upon blindly.

**No placeholders found.** Every step has either complete code or an exact reference (file:line) to an existing pattern.

---

## Execution

Plan complete. Goal: subagent-driven dispatch per CLAUDE.md ("use
subagent driven implementation always"). One subagent per task with
the constraint "do not merge, do not push, do not switch branches".
Tasks 4 and 6 must be serialised (Task 4 first); the others can run
in parallel with each other and Task 4. After all tasks land,
implementation will be merged to master per CLAUDE.md ("always merge
to master after implementation") — that step is performed by the
human-supervised parent session, not by the subagents themselves.

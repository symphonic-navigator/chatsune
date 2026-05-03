# Browser Back Closes Overlays — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the browser back button close any open overlay, drawer, or
lightbox without changing the underlying route.

**Architecture:** A small Zustand store tracks open overlays as a stack. A
`useBackButtonClose(open, onClose, overlayId)` hook synchronises each
overlay's open state with phantom `history.pushState` entries (same URL,
state-only marker). A single global `popstate` listener mounted in
`AppLayout` invokes `onClose` of the topmost stack entry on browser back.
URL is never changed.

**Tech Stack:** React 18, TypeScript, Zustand, React Router v6, Vitest +
@testing-library/react.

**Spec:** `devdocs/specs/2026-05-03-browser-back-overlays-design.md`

---

## File map

**New files:**

- `frontend/src/core/store/historyStackStore.ts` — Zustand store with
  `stack: OverlayEntry[]`, `push`, `popTop`, `peek`, `clear`.
- `frontend/src/core/store/historyStackStore.test.ts` — Vitest unit tests.
- `frontend/src/core/hooks/useBackButtonClose.ts` — the per-overlay hook.
- `frontend/src/core/hooks/useBackButtonClose.test.tsx` — Vitest hook tests.
- `frontend/src/core/back-button/BackButtonProvider.tsx` — global popstate
  listener and logout-clearing subscription. Pass-through component.

**Modified files (one or two lines each, no logic change):**

- `frontend/src/app/layouts/AppLayout.tsx` — wrap children in
  `<BackButtonProvider>`; add hook call for the mobile drawer.
- `frontend/src/app/components/user-modal/UserModal.tsx` — hook call.
- `frontend/src/app/components/admin-modal/AdminModal.tsx` — hook call.
- `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx` — hook call.
- `frontend/src/features/artefact/ArtefactOverlay.tsx` — hook call.
- `frontend/src/features/images/chat/ImageLightbox.tsx` — hook call.
- `frontend/src/features/images/gallery/GalleryLightbox.tsx` — hook call.

---

## Conventions for all subagents

- **Working directory:** `/home/chris/workspace/chatsune`
- **Branch:** stay on the current branch (`master`). **Do NOT merge, push,
  or switch branches.** Commit after each task.
- **Frontend build check after every task that touches `.ts/.tsx`:**
  `cd frontend && pnpm run build` (NOT just `pnpm tsc --noEmit` — the
  former runs `tsc -b` which catches stricter errors).
- **Vitest run scope:** `cd frontend && pnpm vitest run <path>` for a
  single file, `pnpm vitest run` for the whole suite. Unit tests must
  pass before commit.
- **Commit style:** imperative, free-form (e.g. `Add historyStackStore`).
- **British English in code/comments** as per CLAUDE.md.
- **No emojis.**

---

## Task 1: historyStackStore

**Files:**
- Create: `frontend/src/core/store/historyStackStore.ts`
- Test: `frontend/src/core/store/historyStackStore.test.ts`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/core/store/historyStackStore.test.ts`:

```ts
import { beforeEach, describe, expect, it } from 'vitest'
import { useHistoryStackStore } from './historyStackStore'

beforeEach(() => {
  useHistoryStackStore.getState().clear()
})

describe('historyStackStore', () => {
  it('starts with an empty stack', () => {
    expect(useHistoryStackStore.getState().stack).toEqual([])
    expect(useHistoryStackStore.getState().peek()).toBeNull()
  })

  it('push adds to the top', () => {
    const onClose = () => {}
    useHistoryStackStore.getState().push('user-modal', onClose)
    expect(useHistoryStackStore.getState().stack).toHaveLength(1)
    expect(useHistoryStackStore.getState().peek()?.overlayId).toBe('user-modal')
  })

  it('preserves stack order across multiple pushes', () => {
    const noop = () => {}
    useHistoryStackStore.getState().push('a', noop)
    useHistoryStackStore.getState().push('b', noop)
    useHistoryStackStore.getState().push('c', noop)
    expect(useHistoryStackStore.getState().stack.map((e) => e.overlayId)).toEqual(['a', 'b', 'c'])
    expect(useHistoryStackStore.getState().peek()?.overlayId).toBe('c')
  })

  it('popTop removes and returns the top entry', () => {
    const noop = () => {}
    useHistoryStackStore.getState().push('a', noop)
    useHistoryStackStore.getState().push('b', noop)
    const popped = useHistoryStackStore.getState().popTop()
    expect(popped?.overlayId).toBe('b')
    expect(useHistoryStackStore.getState().stack.map((e) => e.overlayId)).toEqual(['a'])
  })

  it('popTop returns null on empty stack', () => {
    expect(useHistoryStackStore.getState().popTop()).toBeNull()
  })

  it('duplicate push of same overlayId replaces, does not duplicate', () => {
    const first = () => {}
    const second = () => {}
    useHistoryStackStore.getState().push('user-modal', first)
    useHistoryStackStore.getState().push('user-modal', second)
    expect(useHistoryStackStore.getState().stack).toHaveLength(1)
    expect(useHistoryStackStore.getState().peek()?.onClose).toBe(second)
  })

  it('clear empties the stack', () => {
    const noop = () => {}
    useHistoryStackStore.getState().push('a', noop)
    useHistoryStackStore.getState().push('b', noop)
    useHistoryStackStore.getState().clear()
    expect(useHistoryStackStore.getState().stack).toEqual([])
  })
})
```

- [ ] **Step 2: Run tests, confirm failure**

```
cd frontend && pnpm vitest run src/core/store/historyStackStore.test.ts
```

Expected: all tests fail with module-not-found error for `./historyStackStore`.

- [ ] **Step 3: Implement the store**

Create `frontend/src/core/store/historyStackStore.ts`:

```ts
import { create } from 'zustand'

/**
 * Tracks the stack of currently open overlays for the back-button close
 * mechanism. Each entry pairs an overlay id with the close handler the
 * popstate listener should invoke when that entry leaves the browser
 * history.
 *
 * The store is the authoritative truth — browser history entries pushed
 * by `useBackButtonClose` are markers only. On logout or other reset
 * paths, callers should `clear()` to avoid stale entries firing onClose
 * against unmounted components.
 */
export interface OverlayEntry {
  overlayId: string
  onClose: () => void
}

interface HistoryStackState {
  stack: OverlayEntry[]
  push: (overlayId: string, onClose: () => void) => void
  popTop: () => OverlayEntry | null
  peek: () => OverlayEntry | null
  clear: () => void
}

export const useHistoryStackStore = create<HistoryStackState>((set, get) => ({
  stack: [],
  push: (overlayId, onClose) =>
    set((state) => {
      // If the same id is already present, replace its entry rather than
      // duplicating. Hook contract guarantees only one push per
      // open-transition, but defensive replace keeps the stack honest if
      // a component re-mounts under odd timings.
      const filtered = state.stack.filter((e) => e.overlayId !== overlayId)
      return { stack: [...filtered, { overlayId, onClose }] }
    }),
  popTop: () => {
    const { stack } = get()
    if (stack.length === 0) return null
    const top = stack[stack.length - 1]
    set({ stack: stack.slice(0, -1) })
    return top
  },
  peek: () => {
    const { stack } = get()
    return stack.length === 0 ? null : stack[stack.length - 1]
  },
  clear: () => set({ stack: [] }),
}))
```

- [ ] **Step 4: Run tests, confirm pass**

```
cd frontend && pnpm vitest run src/core/store/historyStackStore.test.ts
```

Expected: all 7 tests pass.

- [ ] **Step 5: Build check**

```
cd frontend && pnpm run build
```

Expected: clean build, no TS errors.

- [ ] **Step 6: Commit**

```
git add frontend/src/core/store/historyStackStore.ts frontend/src/core/store/historyStackStore.test.ts
git commit -m "Add historyStackStore for back-button overlay tracking"
```

---

## Task 2: useBackButtonClose hook

**Files:**
- Create: `frontend/src/core/hooks/useBackButtonClose.ts`
- Test: `frontend/src/core/hooks/useBackButtonClose.test.tsx`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/core/hooks/useBackButtonClose.test.tsx`:

```tsx
import { renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useBackButtonClose } from './useBackButtonClose'
import { useHistoryStackStore } from '../store/historyStackStore'

beforeEach(() => {
  useHistoryStackStore.getState().clear()
  vi.restoreAllMocks()
})

describe('useBackButtonClose', () => {
  it('does nothing while open is false', () => {
    const pushSpy = vi.spyOn(window.history, 'pushState')
    const onClose = vi.fn()
    renderHook(() => useBackButtonClose(false, onClose, 'a'))
    expect(pushSpy).not.toHaveBeenCalled()
    expect(useHistoryStackStore.getState().stack).toHaveLength(0)
  })

  it('pushes state and registers store entry on open=false→true', () => {
    const pushSpy = vi.spyOn(window.history, 'pushState')
    const onClose = vi.fn()
    const { rerender } = renderHook(
      ({ open }) => useBackButtonClose(open, onClose, 'a'),
      { initialProps: { open: false } },
    )
    rerender({ open: true })
    expect(pushSpy).toHaveBeenCalledTimes(1)
    expect(pushSpy.mock.calls[0][0]).toEqual({ __overlayId: 'a' })
    expect(useHistoryStackStore.getState().peek()?.overlayId).toBe('a')
  })

  it('pops store and calls history.back on programmatic open=true→false', () => {
    const pushSpy = vi.spyOn(window.history, 'pushState')
    const backSpy = vi.spyOn(window.history, 'back').mockImplementation(() => {})
    const onClose = vi.fn()
    const { rerender } = renderHook(
      ({ open }) => useBackButtonClose(open, onClose, 'a'),
      { initialProps: { open: true } },
    )
    // Hook ran with open=true → state should already be pushed.
    expect(pushSpy).toHaveBeenCalledTimes(1)
    expect(useHistoryStackStore.getState().stack).toHaveLength(1)
    rerender({ open: false })
    expect(useHistoryStackStore.getState().stack).toHaveLength(0)
    expect(backSpy).toHaveBeenCalledTimes(1)
  })

  it('does not call history.back if entry already absent (popstate path)', () => {
    const backSpy = vi.spyOn(window.history, 'back').mockImplementation(() => {})
    const onClose = vi.fn()
    const { rerender } = renderHook(
      ({ open }) => useBackButtonClose(open, onClose, 'a'),
      { initialProps: { open: true } },
    )
    // Simulate popstate handler having already removed our store entry.
    useHistoryStackStore.getState().clear()
    rerender({ open: false })
    expect(backSpy).not.toHaveBeenCalled()
  })

  it('treats unmount while open as programmatic close', () => {
    const backSpy = vi.spyOn(window.history, 'back').mockImplementation(() => {})
    const onClose = vi.fn()
    const { unmount } = renderHook(() => useBackButtonClose(true, onClose, 'a'))
    expect(useHistoryStackStore.getState().stack).toHaveLength(1)
    unmount()
    expect(useHistoryStackStore.getState().stack).toHaveLength(0)
    expect(backSpy).toHaveBeenCalledTimes(1)
  })

  it('ignores overlayId changes while open stays true', () => {
    const pushSpy = vi.spyOn(window.history, 'pushState')
    const onClose = vi.fn()
    const { rerender } = renderHook(
      ({ id }) => useBackButtonClose(true, onClose, id),
      { initialProps: { id: 'a' } },
    )
    expect(pushSpy).toHaveBeenCalledTimes(1)
    rerender({ id: 'b' })
    // Still exactly one push.
    expect(pushSpy).toHaveBeenCalledTimes(1)
    // Stack still has the original id.
    expect(useHistoryStackStore.getState().peek()?.overlayId).toBe('a')
  })
})
```

- [ ] **Step 2: Run tests, confirm failure**

```
cd frontend && pnpm vitest run src/core/hooks/useBackButtonClose.test.tsx
```

Expected: module-not-found errors.

- [ ] **Step 3: Implement the hook**

Create `frontend/src/core/hooks/useBackButtonClose.ts`:

```ts
import { useEffect, useRef } from 'react'
import { useHistoryStackStore } from '../store/historyStackStore'

/**
 * Synchronises an overlay's open state with a phantom browser-history
 * entry, so pressing browser back closes the overlay without changing
 * the route.
 *
 * Only the `open` transitions trigger history actions:
 *   - false → true: push a phantom history entry and register the
 *     overlay's onClose with `useHistoryStackStore`.
 *   - true → false (programmatic close): pop the store entry, then call
 *     `history.back()` to keep browser history in sync.
 *
 * Changes to `overlayId` while `open` stays true are intentionally
 * ignored — a Lightbox cycling through images does not deserve a new
 * back-button layer per image.
 *
 * The hook does not register a popstate listener of its own; the global
 * `BackButtonProvider` owns that responsibility.
 *
 * `overlayId` should be a stable string per overlay type (e.g.
 * `'user-modal'`, `'lightbox-chat'`).
 */
export function useBackButtonClose(
  open: boolean,
  onClose: () => void,
  overlayId: string,
): void {
  // Track whether THIS hook instance is currently registered, so we can
  // tell when we go from open=true to open=false (or unmount while open).
  const registeredRef = useRef(false)
  // Always read the latest onClose without re-firing the open effect.
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  const overlayIdRef = useRef(overlayId)
  // Only reflect the id captured at registration time — see contract above.
  if (!registeredRef.current) {
    overlayIdRef.current = overlayId
  }

  useEffect(() => {
    if (open && !registeredRef.current) {
      // false → true transition.
      window.history.pushState({ __overlayId: overlayIdRef.current }, '')
      useHistoryStackStore
        .getState()
        .push(overlayIdRef.current, () => onCloseRef.current())
      registeredRef.current = true
      return
    }
    if (!open && registeredRef.current) {
      // true → false transition: programmatic close.
      registeredRef.current = false
      const removed = removeOwnEntry(overlayIdRef.current)
      if (removed) {
        // We popped the entry ourselves; keep browser history aligned.
        window.history.back()
      }
      // If `removed` is false the global popstate handler already
      // cleaned up — nothing to do.
      return
    }
  }, [open])

  // Cleanup on unmount: same as programmatic close.
  useEffect(() => {
    return () => {
      if (registeredRef.current) {
        registeredRef.current = false
        const removed = removeOwnEntry(overlayIdRef.current)
        if (removed) {
          window.history.back()
        }
      }
    }
  }, [])
}

function removeOwnEntry(overlayId: string): boolean {
  const top = useHistoryStackStore.getState().peek()
  if (!top || top.overlayId !== overlayId) {
    // Already gone (popstate handler ran first) or another overlay sits
    // on top — let the global handler deal with it.
    return false
  }
  useHistoryStackStore.getState().popTop()
  return true
}
```

- [ ] **Step 4: Run tests, confirm pass**

```
cd frontend && pnpm vitest run src/core/hooks/useBackButtonClose.test.tsx
```

Expected: all 6 tests pass.

- [ ] **Step 5: Build check**

```
cd frontend && pnpm run build
```

Expected: clean build.

- [ ] **Step 6: Commit**

```
git add frontend/src/core/hooks/useBackButtonClose.ts frontend/src/core/hooks/useBackButtonClose.test.tsx
git commit -m "Add useBackButtonClose hook for overlay-aware back navigation"
```

---

## Task 3: BackButtonProvider + AppLayout mount

**Files:**
- Create: `frontend/src/core/back-button/BackButtonProvider.tsx`
- Modify: `frontend/src/app/layouts/AppLayout.tsx` (wrap children, no overlay hooks yet)

- [ ] **Step 1: Write the provider**

Create `frontend/src/core/back-button/BackButtonProvider.tsx`:

```tsx
import { useEffect, type ReactNode } from 'react'
import { useHistoryStackStore } from '../store/historyStackStore'
import { useAuthStore } from '../store/authStore'

interface BackButtonProviderProps {
  children: ReactNode
}

/**
 * Mounts the single global popstate listener that drives overlay closes
 * on browser back. Also clears the overlay stack on logout so stale
 * onClose handlers cannot fire against unmounted components.
 *
 * This component renders its children unchanged — its only side-effect
 * is the listener. Mount it once near the root of the authenticated app.
 */
export function BackButtonProvider({ children }: BackButtonProviderProps) {
  useEffect(() => {
    function onPopState(event: PopStateEvent) {
      const top = useHistoryStackStore.getState().peek()
      const newStateId =
        (event.state && typeof event.state === 'object'
          ? (event.state as { __overlayId?: unknown }).__overlayId
          : undefined)

      if (top && top.overlayId !== newStateId) {
        // Browser left the overlay still on top of our stack →
        // user-initiated back. Close it.
        useHistoryStackStore.getState().popTop()
        try {
          top.onClose()
        } catch (err) {
          // An overlay's onClose throwing must not break the listener.
          console.error('[BackButtonProvider] onClose threw', err)
        }
        return
      }

      if (!top && typeof newStateId === 'string') {
        // Forward navigation into a phantom entry whose store side is
        // gone (we explicitly do not re-open closed overlays). Skip past it.
        window.history.forward()
        return
      }
      // Either both empty (normal route navigation) or top.overlayId
      // matches new state (we self-triggered the back via the hook).
      // Nothing to do.
    }

    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  // Clear the stack on logout. We subscribe rather than poll so the
  // effect is correctly re-run if auth state changes.
  useEffect(() => {
    return useAuthStore.subscribe((state, prev) => {
      if (prev.isAuthenticated && !state.isAuthenticated) {
        useHistoryStackStore.getState().clear()
      }
    })
  }, [])

  return <>{children}</>
}
```

- [ ] **Step 2: Verify authStore exposes the fields used above**

Read `frontend/src/core/store/authStore.ts` and confirm
`useAuthStore.subscribe` is the standard Zustand subscription and
`isAuthenticated` is a boolean field on state. If the field name differs
(e.g. `authenticated`, `loggedIn`), adjust the equality check in
`BackButtonProvider` accordingly. If the auth store does not yet support
`subscribe`-by-listener (Zustand v3 vs v4), use the equivalent
`useAuthStore.subscribe((s) => s.isAuthenticated)` slicing API and check
the boolean transition manually. Commit the adjusted file.

- [ ] **Step 3: Mount the provider in AppLayout**

Open `frontend/src/app/layouts/AppLayout.tsx`. At the top, add the import:

```ts
import { BackButtonProvider } from '../../core/back-button/BackButtonProvider'
```

In the JSX returned from `AppLayout`, wrap the existing top-level `<div>`
with `<BackButtonProvider>` so the listener is mounted whenever the
authenticated layout is rendered:

```tsx
return (
  <BackButtonProvider>
    <div className="flex h-full overflow-hidden bg-base text-white">
      {/* ...existing children unchanged... */}
    </div>
  </BackButtonProvider>
)
```

No other changes in this task. The provider is a no-op until overlays
register entries.

- [ ] **Step 4: Build check**

```
cd frontend && pnpm run build
```

Expected: clean build.

- [ ] **Step 5: Smoke test (manual)**

Start the dev server. Navigate around the app. Confirm:

- Routing still works.
- Pressing browser back leaves the app or navigates routes as before
  (no overlay hooks wired yet, so back button still has its old
  behaviour everywhere).

If any visible behaviour changed, the provider or its mounting is wrong.
Investigate before continuing.

- [ ] **Step 6: Commit**

```
git add frontend/src/core/back-button/BackButtonProvider.tsx frontend/src/app/layouts/AppLayout.tsx
git commit -m "Mount BackButtonProvider in AppLayout (no-op without wired overlays)"
```

---

## Task 4: Wire mobile drawer

The mobile sidebar drawer is driven by `useDrawerStore.sidebarOpen` and
its open/close are surfaced in `AppLayout`. Add the back-button hook
there so back closes the drawer on `< lg` viewports only.

**Files:**
- Modify: `frontend/src/app/layouts/AppLayout.tsx`

- [ ] **Step 1: Add the hook call**

In `AppLayout.tsx`, near the existing drawer state lines (search for
`const drawerOpen = useDrawerStore...`), add:

```ts
import { useBackButtonClose } from '../../core/hooks/useBackButtonClose'
```

Below the drawer effects (after the `useEffect` that locks body scroll):

```ts
// Browser back closes the off-canvas drawer on mobile only. On desktop
// the drawer is always "open" as a permanent rail, so we never push
// a history entry for it there.
useBackButtonClose(!isDesktop && drawerOpen, closeDrawer, 'mobile-drawer')
```

- [ ] **Step 2: Build check**

```
cd frontend && pnpm run build
```

- [ ] **Step 3: Manual verification on mobile viewport**

In the dev server, open the responsive devtools at a `< lg` width.

1. Open the mobile drawer.
2. Press browser back.
3. Confirm: drawer closes; URL unchanged; route unchanged.
4. Open drawer, then click any nav item that closes the drawer (route
   change). Press back once.
5. Confirm: route navigates back to where you were before the click,
   not "drawer reopens" or "stays put".
6. Resize to desktop width. Confirm browser back behaves as before
   (no phantom entries).

- [ ] **Step 4: Commit**

```
git add frontend/src/app/layouts/AppLayout.tsx
git commit -m "Browser back closes mobile drawer"
```

---

## Task 5: Wire ImageLightbox (chat)

**Files:**
- Modify: `frontend/src/features/images/chat/ImageLightbox.tsx`

- [ ] **Step 1: Add the hook**

Open `frontend/src/features/images/chat/ImageLightbox.tsx`. Add the import:

```ts
import { useBackButtonClose } from '@/core/hooks/useBackButtonClose'
```

(If `@/` aliasing is not set up here, use the relative path
`../../../core/hooks/useBackButtonClose` — match whichever style the
existing imports in this file use.)

Inside the `ImageLightbox` function body, before the existing Escape
`useEffect`, add:

```tsx
// The lightbox is rendered only while the parent decides to show it,
// so its mere existence equals "open=true". When the parent unmounts
// us we treat that as a programmatic close.
useBackButtonClose(true, onClose, 'lightbox-chat')
```

- [ ] **Step 2: Build check**

```
cd frontend && pnpm run build
```

- [ ] **Step 3: Manual verification**

1. In a chat session, tap an image attachment to open the lightbox.
2. Press browser back. Confirm: lightbox closes, chat is visible, URL
   unchanged.
3. Open lightbox; press Escape. Confirm: closes, and if you press back
   again, you should navigate to the previous route (no stale phantom).
4. Open lightbox; click backdrop. Same expectation as Escape.

- [ ] **Step 4: Commit**

```
git add frontend/src/features/images/chat/ImageLightbox.tsx
git commit -m "Browser back closes chat ImageLightbox"
```

---

## Task 6: Wire GalleryLightbox

**Files:**
- Modify: `frontend/src/features/images/gallery/GalleryLightbox.tsx`

- [ ] **Step 1: Add the hook**

Open `frontend/src/features/images/gallery/GalleryLightbox.tsx`. Mirror
the pattern from Task 5 — add import and one hook call inside the
component body:

```tsx
import { useBackButtonClose } from '@/core/hooks/useBackButtonClose'

// ...inside GalleryLightbox(...)
useBackButtonClose(true, onClose, 'lightbox-gallery')
```

Use the same import style as the file's existing imports.

- [ ] **Step 2: Build check**

```
cd frontend && pnpm run build
```

- [ ] **Step 3: Manual verification**

1. Open the persona gallery (wherever GalleryLightbox is hosted —
   typically the Persona Overlay's images tab).
2. Click an image to open the lightbox.
3. Press browser back. Confirm: lightbox closes, gallery still visible.
4. Stack test: open gallery via PersonaOverlay → open GalleryLightbox →
   press back twice. First back closes lightbox; second back closes
   PersonaOverlay (this works once Task 10 lands; until then the second
   back will still leave the route — that is expected for now).

- [ ] **Step 4: Commit**

```
git add frontend/src/features/images/gallery/GalleryLightbox.tsx
git commit -m "Browser back closes GalleryLightbox"
```

---

## Task 7: Wire ArtefactOverlay

**Files:**
- Modify: `frontend/src/features/artefact/ArtefactOverlay.tsx`

This component is always rendered; "open" equals
`useArtefactStore((s) => s.activeArtefact) !== null`.

- [ ] **Step 1: Add the hook**

In `ArtefactOverlay.tsx`, add the import (match the file's existing
relative-import style):

```ts
import { useBackButtonClose } from '../../core/hooks/useBackButtonClose'
```

Inside the component body, near the existing artefact-store reads:

```tsx
const artefact = useArtefactStore((s) => s.activeArtefact)
const closeOverlay = useArtefactStore((s) => s.closeOverlay)
// ...
useBackButtonClose(artefact !== null, closeOverlay, 'artefact-overlay')
```

(The existing `closeOverlay` selector should already be present — see
`ArtefactOverlay.tsx:44` in the current code. Reuse it; do not redeclare.)

- [ ] **Step 2: Build check**

```
cd frontend && pnpm run build
```

- [ ] **Step 3: Manual verification**

1. In a chat session containing an artefact, click the artefact pill to
   open the ArtefactOverlay.
2. Press browser back. Confirm: overlay closes, chat still visible,
   route unchanged.
3. Open overlay → press X / Escape / backdrop. Confirm normal close.
   Then press back: should navigate routes (no stale phantom).

- [ ] **Step 4: Commit**

```
git add frontend/src/features/artefact/ArtefactOverlay.tsx
git commit -m "Browser back closes ArtefactOverlay"
```

---

## Task 8: Wire UserModal

**Files:**
- Modify: `frontend/src/app/components/user-modal/UserModal.tsx`

`UserModal` is rendered conditionally by `AppLayout` (`{modalOpen && <UserModal ... />}`)
and receives an `onClose: () => void` prop. The component is mounted iff
the modal is open, so we pass `true` as the open flag and rely on
unmount cleanup for the close path — same pattern as AdminModal and
PersonaOverlay.

- [ ] **Step 1: Add the hook**

Add the import (match existing import style):

```ts
import { useBackButtonClose } from '../../../core/hooks/useBackButtonClose'
```

Inside the `UserModal` function body, as the first line after the
opening brace:

```tsx
useBackButtonClose(true, onClose, 'user-modal')
```

- [ ] **Step 2: Build check**

```
cd frontend && pnpm run build
```

- [ ] **Step 3: Manual verification**

1. Open the UserModal from the sidebar / topbar.
2. Press browser back. Confirm: closes, route unchanged.
3. Open UserModal → switch internal tabs (e.g. "About me" → "Display").
   Press back. Confirm: closes the WHOLE modal (tabs are not their own
   layer).
4. Open UserModal → click sidebar to navigate to /chat. Confirm: modal
   closes, route changes, no leftover phantom (one back goes to /personas
   or wherever you came from, not "reopen modal").

- [ ] **Step 4: Commit**

```
git add frontend/src/app/components/user-modal/UserModal.tsx
git commit -m "Browser back closes UserModal"
```

---

## Task 9: Wire AdminModal

**Files:**
- Modify: `frontend/src/app/components/admin-modal/AdminModal.tsx`

`AdminModal` is rendered conditionally by `AppLayout` based on
`adminTab !== null`, and receives `activeTab`, `onClose`, `onTabChange`
props (see `AdminModal.tsx:23-31`). The simplest signal for "open" is
that the component is mounted at all.

- [ ] **Step 1: Add the hook**

Add the import (match existing import style):

```ts
import { useBackButtonClose } from '../../../core/hooks/useBackButtonClose'
```

Inside the `AdminModal` function body, as the first line after the
opening brace:

```tsx
useBackButtonClose(true, onClose, 'admin-modal')
```

The hook will register on mount and clean up on unmount, which matches
"AdminModal is rendered iff `adminTab !== null`".

- [ ] **Step 2: Build check**

```
cd frontend && pnpm run build
```

- [ ] **Step 3: Manual verification**

1. Open the AdminModal from the sidebar.
2. Press browser back. Confirm: closes.
3. Switch tabs inside (Users → Invitations → Settings). Press back.
   Confirm: closes the whole modal.
4. Open AdminModal → open UserModal from inside if reachable, or
   navigate routes. Confirm clean state on return.

- [ ] **Step 4: Commit**

```
git add frontend/src/app/components/admin-modal/AdminModal.tsx
git commit -m "Browser back closes AdminModal"
```

---

## Task 10: Wire PersonaOverlay

**Files:**
- Modify: `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx`

Same pattern as AdminModal. `PersonaOverlay` is rendered conditionally
by `AppLayout` based on `personaOverlay !== null`, and receives an
`onClose` prop (see `PersonaOverlay.tsx:24-75`).

- [ ] **Step 1: Add the hook**

Add the import:

```ts
import { useBackButtonClose } from '../../../core/hooks/useBackButtonClose'
```

Inside `PersonaOverlay` function body, as the first line:

```tsx
useBackButtonClose(true, onClose, 'persona-overlay')
```

- [ ] **Step 2: Build check**

```
cd frontend && pnpm run build
```

- [ ] **Step 3: Manual verification**

1. Open a Persona Overlay from the sidebar.
2. Press browser back. Confirm: closes.
3. Stacking: Open Persona Overlay → click an artefact pill if reachable,
   or trigger ArtefactOverlay another way → 2× back unwinds artefact
   then persona overlay.
4. Open Persona Overlay → click a different persona's overlay (this
   replaces the open one). Confirm: stack stays at 1 entry — pressing
   back closes it cleanly without lingering phantom.

- [ ] **Step 4: Commit**

```
git add frontend/src/app/components/persona-overlay/PersonaOverlay.tsx
git commit -m "Browser back closes PersonaOverlay"
```

---

## Task 11: Final cross-overlay manual verification

**Files:** none (validation only)

This task is a punch list. Run all 9 checks against the running app on
a real Android device (or the closest emulation: Chrome devtools mobile
viewport with touch input). Each scenario lists the expected result —
report any deviation, do NOT silently treat partial successes as done.

- [ ] **Scenario 1: Drawer alone**

Open mobile drawer → browser back → drawer closes, route unchanged.

- [ ] **Scenario 2: UserModal alone**

Open UserModal → back → closes.

- [ ] **Scenario 3: PersonaOverlay tab change**

Open PersonaOverlay → switch a tab → back → whole overlay closes (tabs
are not their own layer).

- [ ] **Scenario 4: Chat ImageLightbox**

In a chat with images, tap an image → lightbox opens → back → closes,
chat visible.

- [ ] **Scenario 5: Triple stack**

Open PersonaOverlay → open ArtefactOverlay (or any second-tier overlay
reachable from inside) → open a Lightbox if accessible → 3× back unwinds
top to bottom. After three backs, you are at the original route with no
overlay.

- [ ] **Scenario 6: Route change with overlay open**

Open UserModal → click sidebar to navigate to `/chat/...` → modal
closes, route changes. Press back ONCE → navigates to the previous
route (NOT "modal reopens"). No leftover phantom.

- [ ] **Scenario 7: Forward button after back-close**

Open any overlay → back to close → press forward → overlay does NOT
re-open. The browser may visibly jump forward then back as the handler
calls `history.forward()` to skip the orphan; that single jump is
acceptable.

- [ ] **Scenario 8: Reload mid-state**

Open an overlay → reload (F5 / pull-to-refresh) → overlay is closed,
route is the same, browser back behaves like a normal route back.

- [ ] **Scenario 9: Logout while overlay open**

Open an overlay → trigger logout (or expire session). After login,
press back. Confirm: nothing reopens, no console errors about unmounted
components calling `onClose`.

- [ ] **Step 10: Desktop cross-check**

Repeat scenarios 1–9 on Chrome Desktop and Firefox Desktop. Document
any cross-browser deviations.

- [ ] **Step 11: Final build verification**

```
cd frontend && pnpm run build
cd frontend && pnpm vitest run
```

Both must pass clean before declaring the feature done.

- [ ] **Step 12: No commit needed**

This task is verification only. If any scenario fails, file a follow-up
task or fix in a new commit.

---

## Out of scope (explicitly NOT in this plan)

- Form-sheet dialogs (`BookmarkModal`, `ExportPersonaModal`,
  `PersonaCloneDialog`, `GatewayEditDialog`, `InvitationLinkDialog`).
- Confirm dialogs ("Are you sure?").
- Unsaved-changes warning when back closes an overlay with dirty form
  state.
- URL-based overlay state (deep links, refresh-preservation).
- Forward-button restoration of closed overlays.

# Mobile UX Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three mobile UX issues on Android/Vivaldi: unreadable/stacking toasts, chat viewport scroll jank, and the missing "reload" affordance inside an installed PWA.

**Architecture:** Three independent frontend changes. A new mobile-only toast renderer gated by `useViewport().isMobile`. A viewport-lock wrapper (`h-[100dvh] overflow-hidden` + flex column) on the Chat route only. A `useIsPwa()` hook plus a manual reload button in User Settings and auto-reload on service-worker update deferred while voice or streaming is active.

**Tech Stack:** React + TypeScript + Tailwind (frontend/src), Vitest + @testing-library/react for tests. No backend changes.

**Design reference:** `devdocs/superpowers/specs/2026-04-20-mobile-ux-fixes-design.md`.

---

## File Structure

New files:

- `frontend/src/app/components/toast/MobileToast.tsx` — single mobile toast card, solid surface, tap + swipe-down dismiss, auto-dismiss.
- `frontend/src/app/components/toast/MobileToastContainer.tsx` — renders the most recent notification, gated on `useViewport().isMobile`.
- `frontend/src/app/components/toast/__tests__/MobileToast.test.tsx`
- `frontend/src/app/components/toast/__tests__/MobileToastContainer.test.tsx`
- `frontend/src/core/hooks/useIsPwa.ts` — thin hook reading `usePwaInstallStore.isInstalled`.
- `frontend/src/core/hooks/__tests__/useIsPwa.test.tsx`
- `frontend/src/core/pwa/__tests__/registerPwa.test.ts`

Modified files:

- `frontend/src/app/components/toast/ToastContainer.tsx` — early return on `isMobile`.
- `frontend/src/app/layouts/AppLayout.tsx` — mount `MobileToastContainer` alongside the existing `ToastContainer`.
- `frontend/src/features/chat/ChatView.tsx` — root wrapper from `h-full` to `h-[100dvh] overflow-hidden`.
- `frontend/src/features/chat/ChatInput.tsx` — remove `sticky bottom-0 z-10 … lg:static` from the wrapper.
- `frontend/index.html` — extend viewport meta with `interactive-widget=resizes-content`.
- `frontend/src/app/components/pwa/InstallHint.tsx` — drop duplicated install-detection, use `useIsPwa`.
- `frontend/src/app/components/user-modal/SettingsTab.tsx` — append "App neu laden" button, PWA-gated.
- `frontend/src/core/pwa/registerPwa.ts` — replace update-toast with auto-reload plus deferral.

---

## Task 1: `MobileToast` component

**Files:**
- Create: `frontend/src/app/components/toast/MobileToast.tsx`
- Create: `frontend/src/app/components/toast/__tests__/MobileToast.test.tsx`

- [ ] **Step 1: Write the failing test**

`frontend/src/app/components/toast/__tests__/MobileToast.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { MobileToast } from '../MobileToast'
import { useNotificationStore } from '../../../../core/store/notificationStore'
import type { AppNotification } from '../../../../core/store/notificationStore'

function makeNotification(overrides: Partial<AppNotification> = {}): AppNotification {
  return {
    id: 'n1',
    level: 'info',
    title: 'Hello',
    message: 'World',
    dismissed: false,
    timestamp: Date.now(),
    ...overrides,
  }
}

describe('MobileToast', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    useNotificationStore.setState({ notifications: [] })
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders title and message', () => {
    render(<MobileToast notification={makeNotification()} />)
    expect(screen.getByText('Hello')).toBeInTheDocument()
    expect(screen.getByText('World')).toBeInTheDocument()
  })

  it('dismisses on tap', () => {
    const dismissSpy = vi.fn()
    useNotificationStore.setState({ dismissToast: dismissSpy } as unknown as Partial<ReturnType<typeof useNotificationStore.getState>>)
    render(<MobileToast notification={makeNotification()} />)
    fireEvent.click(screen.getByRole('status'))
    // MobileToast delays actual store dismiss by the exit animation (200ms)
    act(() => { vi.advanceTimersByTime(250) })
    expect(dismissSpy).toHaveBeenCalledWith('n1')
  })

  it('dismisses on swipe-down past threshold', () => {
    const dismissSpy = vi.fn()
    useNotificationStore.setState({ dismissToast: dismissSpy } as unknown as Partial<ReturnType<typeof useNotificationStore.getState>>)
    render(<MobileToast notification={makeNotification()} />)
    const el = screen.getByRole('status')
    fireEvent.pointerDown(el, { clientY: 100, pointerId: 1 })
    fireEvent.pointerMove(el, { clientY: 160, pointerId: 1 })
    fireEvent.pointerUp(el, { clientY: 160, pointerId: 1 })
    act(() => { vi.advanceTimersByTime(250) })
    expect(dismissSpy).toHaveBeenCalledWith('n1')
  })

  it('does not dismiss on short swipe', () => {
    const dismissSpy = vi.fn()
    useNotificationStore.setState({ dismissToast: dismissSpy } as unknown as Partial<ReturnType<typeof useNotificationStore.getState>>)
    render(<MobileToast notification={makeNotification()} />)
    const el = screen.getByRole('status')
    fireEvent.pointerDown(el, { clientY: 100, pointerId: 1 })
    fireEvent.pointerMove(el, { clientY: 110, pointerId: 1 })
    fireEvent.pointerUp(el, { clientY: 110, pointerId: 1 })
    act(() => { vi.advanceTimersByTime(250) })
    expect(dismissSpy).not.toHaveBeenCalled()
  })

  it('auto-dismisses after duration', () => {
    const dismissSpy = vi.fn()
    useNotificationStore.setState({ dismissToast: dismissSpy } as unknown as Partial<ReturnType<typeof useNotificationStore.getState>>)
    render(<MobileToast notification={makeNotification({ level: 'success' })} />)
    // success default duration is 4000ms; +200ms exit
    act(() => { vi.advanceTimersByTime(4500) })
    expect(dismissSpy).toHaveBeenCalledWith('n1')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --dir frontend test src/app/components/toast/__tests__/MobileToast.test.tsx`

Expected: FAIL — module `../MobileToast` not found.

- [ ] **Step 3: Implement `MobileToast.tsx`**

`frontend/src/app/components/toast/MobileToast.tsx`:

```tsx
import { useCallback, useEffect, useRef, useState } from "react"
import type { AppNotification } from "../../../core/store/notificationStore"
import { useNotificationStore } from "../../../core/store/notificationStore"

const LEVEL_COLOURS: Record<AppNotification["level"], string> = {
  success: "34,197,94",
  info: "124,92,191",
  warning: "201,168,76",
  error: "248,113,113",
}

const LEVEL_ICONS: Record<AppNotification["level"], string> = {
  success: "\u2713",
  info: "\u2139",
  warning: "\u26A0",
  error: "\u2717",
}

const DEFAULT_DURATIONS: Record<AppNotification["level"], number | null> = {
  success: 4000,
  info: 4000,
  warning: 6000,
  error: 10000,
}

const SWIPE_DISMISS_THRESHOLD_PX = 40
const EXIT_ANIMATION_MS = 200

interface MobileToastProps {
  notification: AppNotification
}

export function MobileToast({ notification }: MobileToastProps) {
  const dismissToast = useNotificationStore((s) => s.dismissToast)
  const [exiting, setExiting] = useState(false)
  const [dragY, setDragY] = useState(0)
  const pointerStartY = useRef<number | null>(null)
  const pointerMoved = useRef(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const rgb = LEVEL_COLOURS[notification.level]
  const icon = LEVEL_ICONS[notification.level]
  const duration = notification.duration ?? DEFAULT_DURATIONS[notification.level]

  const dismiss = useCallback(() => {
    if (exiting) return
    setExiting(true)
    setTimeout(() => dismissToast(notification.id), EXIT_ANIMATION_MS)
  }, [dismissToast, exiting, notification.id])

  useEffect(() => {
    if (duration === null) return
    timerRef.current = setTimeout(dismiss, duration)
    return () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current)
    }
  }, [dismiss, duration])

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    pointerStartY.current = e.clientY
    pointerMoved.current = false
    ;(e.currentTarget as HTMLDivElement).setPointerCapture?.(e.pointerId)
  }

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (pointerStartY.current === null) return
    const dy = e.clientY - pointerStartY.current
    if (Math.abs(dy) > 2) pointerMoved.current = true
    setDragY(Math.max(0, dy))
  }

  const onPointerUp = () => {
    if (pointerStartY.current !== null && dragY >= SWIPE_DISMISS_THRESHOLD_PX) {
      dismiss()
    }
    pointerStartY.current = null
    setDragY(0)
  }

  const onClick = () => {
    if (!pointerMoved.current) dismiss()
  }

  return (
    <div
      role="status"
      aria-live="polite"
      className={`pointer-events-auto flex w-[calc(100vw-2rem)] max-w-md items-start gap-3 rounded-xl border-l-4 px-4 py-3 shadow-2xl transition-transform ${exiting ? "animate-toast-exit" : "animate-toast-enter"}`}
      style={{
        background: "#0b0a08",
        borderLeftColor: `rgb(${rgb})`,
        border: `1px solid rgba(${rgb}, 0.35)`,
        borderLeftWidth: "4px",
        transform: dragY > 0 ? `translateY(${dragY}px)` : undefined,
        opacity: dragY > 0 ? Math.max(0.3, 1 - dragY / 200) : 1,
      }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onClick={onClick}
    >
      <span
        className="flex-shrink-0 pt-0.5 text-lg"
        style={{ color: `rgb(${rgb})` }}
      >
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[14px] font-semibold text-white/95">
          {notification.title}
        </div>
        {notification.message && (
          <div className="mt-0.5 text-[12px] text-white/70">
            {notification.message}
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --dir frontend test src/app/components/toast/__tests__/MobileToast.test.tsx`

Expected: PASS (all 5 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/toast/MobileToast.tsx \
        frontend/src/app/components/toast/__tests__/MobileToast.test.tsx
git commit -m "Add MobileToast component"
```

---

## Task 2: `MobileToastContainer` component

**Files:**
- Create: `frontend/src/app/components/toast/MobileToastContainer.tsx`
- Create: `frontend/src/app/components/toast/__tests__/MobileToastContainer.test.tsx`

- [ ] **Step 1: Write the failing test**

`frontend/src/app/components/toast/__tests__/MobileToastContainer.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MobileToastContainer } from '../MobileToastContainer'
import { useNotificationStore } from '../../../../core/store/notificationStore'

vi.mock('../../../../core/hooks/useViewport', () => ({
  useViewport: () => mockViewport,
}))

let mockViewport = { isMobile: true, isDesktop: false, isTablet: false, isLandscape: false, isSm: true, isMd: false, isLg: false, isXl: false }

function seed(ns: Array<{ id: string; title: string }>) {
  // notificationStore prepends new notifications, so the first entry is the
  // newest. Seed in the same order: first element = most recent.
  useNotificationStore.setState({
    notifications: ns.map((n, i) => ({
      id: n.id,
      level: 'info' as const,
      title: n.title,
      message: '',
      dismissed: false,
      timestamp: Date.now() - i,
    })),
  })
}

describe('MobileToastContainer', () => {
  beforeEach(() => {
    mockViewport = { isMobile: true, isDesktop: false, isTablet: false, isLandscape: false, isSm: true, isMd: false, isLg: false, isXl: false }
    useNotificationStore.setState({ notifications: [] })
  })

  it('renders nothing when not mobile', () => {
    mockViewport = { isMobile: false, isDesktop: true, isTablet: false, isLandscape: false, isSm: true, isMd: true, isLg: true, isXl: false }
    seed([{ id: 'a', title: 'First' }])
    const { container } = render(<MobileToastContainer />)
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when there are no notifications', () => {
    const { container } = render(<MobileToastContainer />)
    expect(container.firstChild).toBeNull()
  })

  it('renders only the most recent notification when mobile', () => {
    // First in array = newest (store prepends).
    seed([
      { id: 'c', title: 'Third' },
      { id: 'b', title: 'Second' },
      { id: 'a', title: 'First' },
    ])
    render(<MobileToastContainer />)
    expect(screen.queryByText('First')).not.toBeInTheDocument()
    expect(screen.queryByText('Second')).not.toBeInTheDocument()
    expect(screen.getByText('Third')).toBeInTheDocument()
  })

  it('skips dismissed notifications', () => {
    // Newest (dismissed) first, older (visible) second.
    useNotificationStore.setState({
      notifications: [
        { id: 'b', level: 'info', title: 'Second', message: '', dismissed: true, timestamp: 2 },
        { id: 'a', level: 'info', title: 'First', message: '', dismissed: false, timestamp: 1 },
      ],
    })
    render(<MobileToastContainer />)
    expect(screen.getByText('First')).toBeInTheDocument()
    expect(screen.queryByText('Second')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --dir frontend test src/app/components/toast/__tests__/MobileToastContainer.test.tsx`

Expected: FAIL — module `../MobileToastContainer` not found.

- [ ] **Step 3: Implement `MobileToastContainer.tsx`**

`frontend/src/app/components/toast/MobileToastContainer.tsx`:

```tsx
import { useNotificationStore } from "../../../core/store/notificationStore"
import { useViewport } from "../../../core/hooks/useViewport"
import { MobileToast } from "./MobileToast"

/**
 * Mobile-only toast renderer. Shows a single, solid, bottom-anchored toast.
 * New notifications replace the current one; there is no queue and no
 * stacking. The desktop renderer (`ToastContainer`) remains the source of
 * stacked, glassy toasts on `>= lg`.
 */
export function MobileToastContainer() {
  const { isMobile } = useViewport()
  const notifications = useNotificationStore((s) => s.notifications)

  if (!isMobile) return null

  const visible = notifications.filter((n) => !n.dismissed)
  if (visible.length === 0) return null

  // Store prepends new entries, so the first visible notification is the
  // most recent one.
  const top = visible[0]

  return (
    <div
      className="pointer-events-none fixed left-1/2 z-[60] flex -translate-x-1/2 justify-center"
      style={{
        bottom: "calc(env(safe-area-inset-bottom) + 1rem)",
      }}
    >
      <MobileToast key={top.id} notification={top} />
    </div>
  )
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --dir frontend test src/app/components/toast/__tests__/MobileToastContainer.test.tsx`

Expected: PASS (all 4 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/toast/MobileToastContainer.tsx \
        frontend/src/app/components/toast/__tests__/MobileToastContainer.test.tsx
git commit -m "Add MobileToastContainer with viewport-gated rendering"
```

---

## Task 3: Gate desktop `ToastContainer` and wire mobile container into `AppLayout`

**Files:**
- Modify: `frontend/src/app/components/toast/ToastContainer.tsx`
- Modify: `frontend/src/app/layouts/AppLayout.tsx`

- [ ] **Step 1: Inspect `AppLayout.tsx` to find where `ToastContainer` is mounted**

Run: `grep -n "ToastContainer" frontend/src/app/layouts/AppLayout.tsx`

Note the file path(s) and line number(s) where the import and JSX use appear. The existing usage is approximately at `AppLayout.tsx:324` but confirm.

- [ ] **Step 2: Write a failing test for desktop gating**

Add to `frontend/src/app/components/toast/__tests__/MobileToastContainer.test.tsx` a new `describe('ToastContainer', …)` block — or create a sibling file `ToastContainer.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import { ToastContainer } from '../ToastContainer'
import { useNotificationStore } from '../../../../core/store/notificationStore'

vi.mock('../../../../core/hooks/useViewport', () => ({
  useViewport: () => mockViewport,
}))

let mockViewport = { isMobile: true, isDesktop: false, isTablet: false, isLandscape: false, isSm: true, isMd: false, isLg: false, isXl: false }

describe('ToastContainer (desktop-only gating)', () => {
  beforeEach(() => {
    useNotificationStore.setState({
      notifications: [
        { id: 'a', level: 'info', title: 'Hi', message: '', dismissed: false, timestamp: 1 },
      ],
    })
  })

  it('returns null on mobile', () => {
    mockViewport = { isMobile: true, isDesktop: false, isTablet: false, isLandscape: false, isSm: true, isMd: false, isLg: false, isXl: false }
    const { container } = render(<ToastContainer />)
    expect(container.firstChild).toBeNull()
  })

  it('renders toasts on desktop', () => {
    mockViewport = { isMobile: false, isDesktop: true, isTablet: false, isLandscape: false, isSm: true, isMd: true, isLg: true, isXl: false }
    const { container } = render(<ToastContainer />)
    expect(container.firstChild).not.toBeNull()
  })
})
```

Save as `frontend/src/app/components/toast/__tests__/ToastContainer.test.tsx`.

- [ ] **Step 3: Run tests to verify failure**

Run: `pnpm --dir frontend test src/app/components/toast/__tests__/ToastContainer.test.tsx`

Expected: FAIL — on mobile, `ToastContainer` still renders (no gating yet).

- [ ] **Step 4: Modify `ToastContainer.tsx` to early-return on mobile**

Replace the content of `frontend/src/app/components/toast/ToastContainer.tsx` with:

```tsx
import { useEffect } from "react"
import { useNotificationStore } from "../../../core/store/notificationStore"
import { useViewport } from "../../../core/hooks/useViewport"
import { Toast } from "./Toast"

const MAX_VISIBLE = 3

export function ToastContainer() {
  const { isMobile } = useViewport()
  const notifications = useNotificationStore((s) => s.notifications)
  const dismissToast = useNotificationStore((s) => s.dismissToast)

  const visible = notifications.filter((n) => !n.dismissed)

  // Auto-dismiss notifications beyond MAX_VISIBLE (keep effect so history is
  // pruned even while the desktop container is hidden on mobile).
  useEffect(() => {
    visible.slice(MAX_VISIBLE).forEach((n) => dismissToast(n.id))
  }, [visible, dismissToast])

  if (isMobile) return null

  const displayed = visible.slice(0, MAX_VISIBLE)
  if (displayed.length === 0) return null

  return (
    <div className="pointer-events-none fixed top-14 left-1/2 z-[60] flex -translate-x-1/2 flex-col gap-3 p-4">
      {displayed.map((n) => (
        <Toast key={n.id} notification={n} />
      ))}
    </div>
  )
}
```

- [ ] **Step 5: Mount `MobileToastContainer` in `AppLayout.tsx`**

Open `frontend/src/app/layouts/AppLayout.tsx`, find the existing `ToastContainer` import and JSX usage.

Add the mobile container import next to it:

```tsx
import { ToastContainer } from "../components/toast/ToastContainer"
import { MobileToastContainer } from "../components/toast/MobileToastContainer"
```

Next to `<ToastContainer />` in JSX, add `<MobileToastContainer />` on the following line:

```tsx
<ToastContainer />
<MobileToastContainer />
```

Both are self-gating via `useViewport` — only one renders for a given viewport.

- [ ] **Step 6: Run the toast test suite**

Run: `pnpm --dir frontend test src/app/components/toast/`

Expected: PASS — all tests (MobileToast, MobileToastContainer, ToastContainer) green.

- [ ] **Step 7: Typecheck**

Run: `pnpm --dir frontend tsc --noEmit`

Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/app/components/toast/ToastContainer.tsx \
        frontend/src/app/components/toast/__tests__/ToastContainer.test.tsx \
        frontend/src/app/layouts/AppLayout.tsx
git commit -m "Gate desktop ToastContainer and mount MobileToastContainer"
```

---

## Task 4: Viewport meta tag for Android keyboard resize

**Files:**
- Modify: `frontend/index.html`

No unit test — this is a single-line configuration change and is verified manually on device (see Task 5).

- [ ] **Step 1: Modify `frontend/index.html`**

Locate line 8:

```html
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
```

Replace with:

```html
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content" />
```

- [ ] **Step 2: Commit**

```bash
git add frontend/index.html
git commit -m "Make Android keyboard resize the layout viewport"
```

---

## Task 5: Chat viewport lock

**Files:**
- Modify: `frontend/src/features/chat/ChatView.tsx` (line ~1046)
- Modify: `frontend/src/features/chat/ChatInput.tsx` (line ~140)

These are CSS/layout changes. Layout is not easily unit-testable in jsdom, so this task relies on a compile check and manual verification.

- [ ] **Step 1: Edit `ChatView.tsx` root wrapper**

Open `frontend/src/features/chat/ChatView.tsx` and find the JSX near line 1046:

```tsx
return (
  <div className="flex h-full flex-col">
    <div className="flex items-center justify-between border-b border-white/6 px-4 py-2">
```

Change the root `<div>` className:

```tsx
return (
  <div className="flex h-[100dvh] flex-col overflow-hidden">
    <div className="flex items-center justify-between border-b border-white/6 px-4 py-2">
```

Rationale: `h-[100dvh]` shrinks with the Android soft keyboard; `overflow-hidden` prevents window-level scroll. The inner flex column keeps the top bar (`flex-none` by default), the message-row wrapper at line ~1300 (already `flex flex-1 min-h-0`), and the input at line ~1338 properly partitioned.

- [ ] **Step 2: Edit `ChatInput.tsx` wrapper**

Open `frontend/src/features/chat/ChatInput.tsx` and find line 140:

```tsx
<div
  className="sticky bottom-0 z-10 border-t border-white/6 bg-surface px-4 py-3 pb-[calc(env(safe-area-inset-bottom)+0.75rem)] lg:static lg:pb-3"
```

Replace with:

```tsx
<div
  className="z-10 border-t border-white/6 bg-surface px-4 py-3 pb-[calc(env(safe-area-inset-bottom)+0.75rem)] lg:pb-3"
```

Removed: `sticky bottom-0` and `lg:static`. The input is now a natural flex child of the ChatView shell. `z-10` stays so attachment popovers etc. layer predictably; the safe-area padding stays.

- [ ] **Step 3: Typecheck and build**

Run: `pnpm --dir frontend tsc --noEmit && pnpm --dir frontend run build`

Expected: no errors, build succeeds.

- [ ] **Step 4: Smoke-run existing Chat tests**

Run: `pnpm --dir frontend test src/features/chat/`

Expected: PASS — existing tests unaffected.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/chat/ChatView.tsx frontend/src/features/chat/ChatInput.tsx
git commit -m "Lock chat viewport with dvh and flex shell"
```

---

## Task 6: `useIsPwa` hook

**Files:**
- Create: `frontend/src/core/hooks/useIsPwa.ts`
- Create: `frontend/src/core/hooks/__tests__/useIsPwa.test.tsx`

- [ ] **Step 1: Write the failing test**

`frontend/src/core/hooks/__tests__/useIsPwa.test.tsx`:

```tsx
import { describe, it, expect, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useIsPwa } from '../useIsPwa'
import { usePwaInstallStore } from '../../pwa/installPrompt'

describe('useIsPwa', () => {
  beforeEach(() => {
    usePwaInstallStore.setState({ isInstalled: false })
  })

  it('returns false when not installed', () => {
    const { result } = renderHook(() => useIsPwa())
    expect(result.current).toBe(false)
  })

  it('returns true when installed flag is set', () => {
    usePwaInstallStore.setState({ isInstalled: true })
    const { result } = renderHook(() => useIsPwa())
    expect(result.current).toBe(true)
  })

  it('updates when the store flag flips', () => {
    const { result } = renderHook(() => useIsPwa())
    expect(result.current).toBe(false)
    act(() => {
      usePwaInstallStore.setState({ isInstalled: true })
    })
    expect(result.current).toBe(true)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --dir frontend test src/core/hooks/__tests__/useIsPwa.test.tsx`

Expected: FAIL — module `../useIsPwa` not found.

- [ ] **Step 3: Implement `useIsPwa.ts`**

`frontend/src/core/hooks/useIsPwa.ts`:

```ts
import { usePwaInstallStore } from "../pwa/installPrompt"

/**
 * Returns `true` if the app is currently running as an installed PWA
 * (display-mode: standalone). Wraps the already-maintained `isInstalled`
 * flag in `usePwaInstallStore`, which is initialised from
 * `matchMedia('(display-mode: standalone)')` and updated on the
 * `appinstalled` window event.
 *
 * Callers should use this hook rather than duplicating the matchMedia
 * check so the single source of truth stays in the store.
 */
export function useIsPwa(): boolean {
  return usePwaInstallStore((s) => s.isInstalled)
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm --dir frontend test src/core/hooks/__tests__/useIsPwa.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/hooks/useIsPwa.ts \
        frontend/src/core/hooks/__tests__/useIsPwa.test.tsx
git commit -m "Add useIsPwa hook wrapping install-store flag"
```

---

## Task 7: Refactor `InstallHint` to consume `useIsPwa`

**Files:**
- Modify: `frontend/src/app/components/pwa/InstallHint.tsx`

No behaviour change — only removes a duplicate path of the install check.

- [ ] **Step 1: Edit `InstallHint.tsx`**

Change the line:

```tsx
const isInstalled = usePwaInstallStore((s) => s.isInstalled)
```

to:

```tsx
const isInstalled = useIsPwa()
```

Add the import:

```tsx
import { useIsPwa } from "../../../core/hooks/useIsPwa"
```

The `usePwaInstallStore` import stays because the component still uses `promptEvent`, `dismissed`, `visitCount`, `install`, `dismiss`.

- [ ] **Step 2: Typecheck**

Run: `pnpm --dir frontend tsc --noEmit`

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/components/pwa/InstallHint.tsx
git commit -m "Consume useIsPwa in InstallHint"
```

---

## Task 8: "App neu laden" button in Settings tab

**Files:**
- Modify: `frontend/src/app/components/user-modal/SettingsTab.tsx`

- [ ] **Step 1: Edit `SettingsTab.tsx`**

At the top of the file, add the import:

```tsx
import { useIsPwa } from "../../../core/hooks/useIsPwa"
```

Inside the `SettingsTab` component, after the existing hook calls (`useDisplaySettings`, `useHapticsStore`), add:

```tsx
const isPwa = useIsPwa()
```

In the JSX, at the **end** of the outer `<div className="flex flex-col gap-6 p-6 max-w-xl overflow-y-auto">` (just before the closing `</div>`), add:

```tsx
{isPwa && (
  <div>
    <label className={LABEL}>App</label>
    <button
      type="button"
      onClick={() => window.location.reload()}
      className="px-3.5 py-1.5 rounded-lg text-[11px] font-mono transition-all border border-white/8 bg-transparent text-white/60 hover:text-white/90 hover:border-white/20"
    >
      App neu laden
    </button>
  </div>
)}
```

- [ ] **Step 2: Typecheck**

Run: `pnpm --dir frontend tsc --noEmit`

Expected: no errors.

- [ ] **Step 3: Smoke-test existing `UserModal` tests**

Run: `pnpm --dir frontend test src/app/components/user-modal/`

Expected: PASS — existing tests unaffected.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/user-modal/SettingsTab.tsx
git commit -m "Add PWA-only reload button to Settings tab"
```

---

## Task 9: Auto-reload on service-worker update, deferred during voice/streaming

**Files:**
- Modify: `frontend/src/core/pwa/registerPwa.ts`
- Create: `frontend/src/core/pwa/__tests__/registerPwa.test.ts`

We test the **deferral helper** in isolation because the surrounding `registerSW` flow depends on the `virtual:pwa-register` module which only exists in production builds. Extract the decision logic into an exported function, then unit-test that function.

- [ ] **Step 1: Write the failing test**

`frontend/src/core/pwa/__tests__/registerPwa.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { reloadWhenIdle } from '../registerPwa'
import { useChatStore } from '../../store/chatStore'
import { useConversationModeStore } from '../../../features/voice/stores/conversationModeStore'

describe('reloadWhenIdle', () => {
  let reloadSpy: ReturnType<typeof vi.fn>
  beforeEach(() => {
    vi.useFakeTimers()
    reloadSpy = vi.fn()
    useChatStore.setState({ isStreaming: false } as Partial<ReturnType<typeof useChatStore.getState>>)
    useConversationModeStore.setState({ active: false } as Partial<ReturnType<typeof useConversationModeStore.getState>>)
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('reloads immediately when idle', () => {
    reloadWhenIdle(reloadSpy)
    expect(reloadSpy).toHaveBeenCalledTimes(1)
  })

  it('defers while streaming', () => {
    useChatStore.setState({ isStreaming: true } as Partial<ReturnType<typeof useChatStore.getState>>)
    reloadWhenIdle(reloadSpy)
    expect(reloadSpy).not.toHaveBeenCalled()
  })

  it('defers while conversation mode is active', () => {
    useConversationModeStore.setState({ active: true } as Partial<ReturnType<typeof useConversationModeStore.getState>>)
    reloadWhenIdle(reloadSpy)
    expect(reloadSpy).not.toHaveBeenCalled()
  })

  it('reloads after streaming ends and the settle window elapses', () => {
    useChatStore.setState({ isStreaming: true } as Partial<ReturnType<typeof useChatStore.getState>>)
    reloadWhenIdle(reloadSpy)
    expect(reloadSpy).not.toHaveBeenCalled()

    useChatStore.setState({ isStreaming: false } as Partial<ReturnType<typeof useChatStore.getState>>)
    // Still deferred during the 500ms settle window.
    expect(reloadSpy).not.toHaveBeenCalled()
    vi.advanceTimersByTime(500)
    expect(reloadSpy).toHaveBeenCalledTimes(1)
  })

  it('cancels the settle timer if a new stream starts inside the window', () => {
    useChatStore.setState({ isStreaming: true } as Partial<ReturnType<typeof useChatStore.getState>>)
    reloadWhenIdle(reloadSpy)

    useChatStore.setState({ isStreaming: false } as Partial<ReturnType<typeof useChatStore.getState>>)
    vi.advanceTimersByTime(200)
    useChatStore.setState({ isStreaming: true } as Partial<ReturnType<typeof useChatStore.getState>>)
    vi.advanceTimersByTime(500)
    expect(reloadSpy).not.toHaveBeenCalled()

    useChatStore.setState({ isStreaming: false } as Partial<ReturnType<typeof useChatStore.getState>>)
    vi.advanceTimersByTime(500)
    expect(reloadSpy).toHaveBeenCalledTimes(1)
  })

  it('waits for both conversation mode and streaming to be false', () => {
    useChatStore.setState({ isStreaming: true } as Partial<ReturnType<typeof useChatStore.getState>>)
    useConversationModeStore.setState({ active: true } as Partial<ReturnType<typeof useConversationModeStore.getState>>)
    reloadWhenIdle(reloadSpy)

    useChatStore.setState({ isStreaming: false } as Partial<ReturnType<typeof useChatStore.getState>>)
    vi.advanceTimersByTime(500)
    expect(reloadSpy).not.toHaveBeenCalled() // conversation still active

    useConversationModeStore.setState({ active: false } as Partial<ReturnType<typeof useConversationModeStore.getState>>)
    vi.advanceTimersByTime(500)
    expect(reloadSpy).toHaveBeenCalledTimes(1)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --dir frontend test src/core/pwa/__tests__/registerPwa.test.ts`

Expected: FAIL — `reloadWhenIdle` is not exported yet.

- [ ] **Step 3: Modify `registerPwa.ts`**

Replace the contents of `frontend/src/core/pwa/registerPwa.ts` with:

```ts
import { useNotificationStore } from "../store/notificationStore"
import { useChatStore } from "../store/chatStore"
import { useConversationModeStore } from "../../features/voice/stores/conversationModeStore"
import { initInstallPrompt } from "./installPrompt"

const SETTLE_MS = 500

/**
 * Reload the page as soon as both the chat stream and Conversational Mode
 * are idle. If both are already idle, reload immediately. The caller owns
 * the actual reload action (`doReload`) so tests can inject a spy.
 *
 * Exported for unit testing.
 */
export function reloadWhenIdle(doReload: () => void): void {
  const isBusy = () =>
    useChatStore.getState().isStreaming ||
    useConversationModeStore.getState().active

  if (!isBusy()) {
    doReload()
    return
  }

  let settleTimer: ReturnType<typeof setTimeout> | null = null

  const clearSettle = () => {
    if (settleTimer !== null) {
      clearTimeout(settleTimer)
      settleTimer = null
    }
  }

  const tryScheduleReload = () => {
    if (isBusy()) {
      clearSettle()
      return
    }
    clearSettle()
    settleTimer = setTimeout(() => {
      if (!isBusy()) {
        unsubChat()
        unsubConversation()
        doReload()
      }
    }, SETTLE_MS)
  }

  const unsubChat = useChatStore.subscribe(tryScheduleReload)
  const unsubConversation = useConversationModeStore.subscribe(tryScheduleReload)
}

/**
 * Registers the service worker generated by vite-plugin-pwa.
 *
 * Only runs in production builds — the dev server intentionally has no
 * service worker so Vite HMR keeps working and stale caches don't confuse
 * local development.
 *
 * On update: reload automatically. If the user is in Conversational Mode
 * or an LLM response is streaming, the reload is deferred until both are
 * idle for 500ms (no timeout — the reload waits as long as needed).
 */
export function registerPwa(): void {
  initInstallPrompt()

  if (!import.meta.env.PROD) return

  void import("virtual:pwa-register").then(({ registerSW }) => {
    const updateSW = registerSW({
      onNeedRefresh() {
        // Activate the waiting service worker, then reload when idle.
        void updateSW(true)
        reloadWhenIdle(() => window.location.reload())
      },
      onOfflineReady() {
        useNotificationStore.getState().addNotification({
          level: "success",
          title: "Offline bereit",
          message: "Chatsune ist jetzt auch offline verfügbar.",
        })
      },
    })
  })
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --dir frontend test src/core/pwa/__tests__/registerPwa.test.ts`

Expected: PASS (all 6 tests).

- [ ] **Step 5: Typecheck and build**

Run: `pnpm --dir frontend tsc --noEmit && pnpm --dir frontend run build`

Expected: no errors, build succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/core/pwa/registerPwa.ts \
        frontend/src/core/pwa/__tests__/registerPwa.test.ts
git commit -m "Auto-reload on SW update, deferred while voice or streaming active"
```

---

## Task 10: Final checks and manual verification

- [ ] **Step 1: Full test run**

Run: `pnpm --dir frontend test`

Expected: all tests pass.

- [ ] **Step 2: Build**

Run: `pnpm --dir frontend run build`

Expected: clean build.

- [ ] **Step 3: Deploy to reference VPS and verify on device**

Per the spec, run through the 12 manual verification steps on a Galaxy S20 Ultra + Vivaldi (both plain browser and installed PWA):

*Toast:*
1. Trigger a toast (e.g. copy a share link). Verify bottom placement, solid surface, readable.
2. Swipe the toast down → dismissed.
3. Trigger two toasts quickly → second replaces first (no stack).
4. Progress toast followed by success toast → only one visible at a time.

*Chat viewport:*
5. Type "Hi" and Enter → top bar and input stay in place; only the message list scrolls.
6. Tap input, keyboard opens → input remains visible above keyboard, top bar visible, message list shrinks.
7. Type multi-line input → input grows, message list shrinks; text never hides behind keyboard.
8. Send via button → same result as step 5.

*PWA reload:*
9. In plain browser (not installed): User → Settings → no "App neu laden" button.
10. In installed PWA: User → Settings → "App neu laden" present; tapping it reloads.
11. Trigger a deploy while PWA open on idle chat → silent reload within a few seconds, no toast.
12. Trigger a deploy while in Conversational Mode → no reload; after exiting Conversational Mode, reload occurs shortly after.

Document any regressions and fix before merging.

- [ ] **Step 4: Merge to master**

Per project convention (`CLAUDE.md`: "Please always merge to master after implementation"), merge the branch once all checks pass:

```bash
git checkout master
git merge --no-ff <working-branch>
```

(If working directly on master, this step is a no-op.)

---

## Scope reminders

- No iOS-specific handling in this plan.
- No refactor of `notificationStore`.
- No global viewport lock — only the Chat route.
- No new settings to opt out of auto-reload.
- No timeout on deferral — reload waits as long as voice/streaming stays busy.

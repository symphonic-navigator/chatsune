# Toast Notification System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a visual toast notification system that renders feedback for user actions, errors, and system events, consuming the existing `notificationStore`.

**Architecture:** Extend the Zustand notification store with `warning` level, optional `action` and `duration` fields. Create two new components (`ToastContainer`, `Toast`) that read from the store. Add CSS keyframe animations. Mount `ToastContainer` in `AppLayout`.

**Tech Stack:** React, Zustand, Tailwind CSS 4, CSS keyframes

**Spec:** `docs/superpowers/specs/2026-04-06-toast-system-design.md`

---

### Task 1: Extend the notification store

**Files:**
- Modify: `frontend/src/core/store/notificationStore.ts`

- [ ] **Step 1: Update the `AppNotification` interface**

Add `warning` to the level union, add optional `action` and `duration` fields:

```typescript
import { create } from "zustand"

export interface NotificationAction {
  label: string
  onClick: () => void
}

export interface AppNotification {
  id: string
  level: "success" | "error" | "info" | "warning"
  title: string
  message: string
  action?: NotificationAction
  duration?: number
  timestamp: number
  dismissed: boolean
}

type NewNotification = Pick<AppNotification, "level" | "title" | "message"> &
  Partial<Pick<AppNotification, "action" | "duration">>

interface NotificationState {
  notifications: AppNotification[]
  addNotification: (n: NewNotification) => void
  dismissToast: (id: string) => void
}

const MAX_NOTIFICATIONS = 20

export const useNotificationStore = create<NotificationState>((set) => ({
  notifications: [],

  addNotification: (n) =>
    set((state) => ({
      notifications: [
        {
          ...n,
          id: crypto.randomUUID(),
          timestamp: Date.now(),
          dismissed: false,
        },
        ...state.notifications,
      ].slice(0, MAX_NOTIFICATIONS),
    })),

  dismissToast: (id) =>
    set((state) => ({
      notifications: state.notifications.map((n) =>
        n.id === id ? { ...n, dismissed: true } : n,
      ),
    })),
}))
```

- [ ] **Step 2: Verify the frontend builds**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/core/store/notificationStore.ts
git commit -m "Extend notification store with warning level, action, and duration"
```

---

### Task 2: Add toast CSS animations

**Files:**
- Modify: `frontend/src/index.css` (after line 119, after `.animate-think-pulse`)

- [ ] **Step 1: Add toast keyframes and utility classes**

Insert after the `.animate-think-pulse` block (after line 119):

```css
/* Toast animations */
@keyframes toastEnter {
  from {
    opacity: 0;
    transform: translateY(-8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes toastExit {
  from {
    opacity: 1;
    transform: translateY(0);
  }
  to {
    opacity: 0;
    transform: translateY(-8px);
  }
}

.animate-toast-enter {
  animation: toastEnter 0.2s ease-out;
}

.animate-toast-exit {
  animation: toastExit 0.2s ease-out forwards;
}
```

- [ ] **Step 2: Verify the frontend builds**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm run build`
Expected: Build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/index.css
git commit -m "Add toast enter/exit CSS keyframe animations"
```

---

### Task 3: Create the Toast component

**Files:**
- Create: `frontend/src/app/components/toast/Toast.tsx`

- [ ] **Step 1: Create the Toast component**

```tsx
import { useCallback, useEffect, useRef, useState } from "react"
import type { AppNotification } from "../../../core/store/notificationStore"
import { useNotificationStore } from "../../../core/store/notificationStore"

const LEVEL_COLOURS: Record<AppNotification["level"], string> = {
  success: "34,197,94",   // --color-live
  info: "124,92,191",     // --color-purple
  warning: "201,168,76",  // --color-gold
  error: "248,113,113",   // red-400
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
  error: null,
}

interface ToastProps {
  notification: AppNotification
}

export function Toast({ notification }: ToastProps) {
  const dismissToast = useNotificationStore((s) => s.dismissToast)
  const [exiting, setExiting] = useState(false)

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const remainingRef = useRef<number | null>(null)
  const startedAtRef = useRef<number>(0)

  const duration = notification.duration ?? DEFAULT_DURATIONS[notification.level]

  const dismiss = useCallback(() => {
    setExiting(true)
    setTimeout(() => dismissToast(notification.id), 200)
  }, [dismissToast, notification.id])

  const startTimer = useCallback(
    (ms: number) => {
      remainingRef.current = ms
      startedAtRef.current = Date.now()
      timerRef.current = setTimeout(dismiss, ms)
    },
    [dismiss],
  )

  const pauseTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current)
      timerRef.current = null
      const elapsed = Date.now() - startedAtRef.current
      remainingRef.current = Math.max((remainingRef.current ?? 0) - elapsed, 0)
    }
  }, [])

  const resumeTimer = useCallback(() => {
    if (remainingRef.current !== null && remainingRef.current > 0) {
      startTimer(remainingRef.current)
    }
  }, [startTimer])

  useEffect(() => {
    if (duration !== null) {
      startTimer(duration)
    }
    return () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current)
    }
  }, [duration, startTimer])

  const rgb = LEVEL_COLOURS[notification.level]
  const icon = LEVEL_ICONS[notification.level]

  const handleAction = () => {
    notification.action?.onClick()
    dismiss()
  }

  return (
    <div
      className={`pointer-events-auto flex max-w-md items-center gap-3 rounded-lg px-4 py-3 shadow-lg backdrop-blur-sm ${exiting ? "animate-toast-exit" : "animate-toast-enter"}`}
      style={{
        background: `rgba(${rgb}, 0.08)`,
        border: `1px solid rgba(${rgb}, 0.25)`,
      }}
      onMouseEnter={pauseTimer}
      onMouseLeave={resumeTimer}
    >
      <span
        className="flex-shrink-0 text-lg"
        style={{ color: `rgb(${rgb})` }}
      >
        {icon}
      </span>

      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-semibold text-white/90">
          {notification.title}
        </div>
        {notification.message && (
          <div className="mt-0.5 text-[11px] text-white/50">
            {notification.message}
          </div>
        )}
      </div>

      {notification.action && (
        <button
          className="flex-shrink-0 cursor-pointer rounded-md px-2.5 py-1 text-[11px] transition-colors"
          style={{
            color: `rgb(${rgb})`,
            background: `rgba(${rgb}, 0.15)`,
            border: `1px solid rgba(${rgb}, 0.3)`,
          }}
          onClick={handleAction}
        >
          {notification.action.label}
        </button>
      )}

      <button
        className="flex-shrink-0 cursor-pointer text-sm text-white/30 transition-colors hover:text-white/60"
        onClick={dismiss}
      >
        {"\u00D7"}
      </button>
    </div>
  )
}
```

- [ ] **Step 2: Verify the frontend builds**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/components/toast/Toast.tsx
git commit -m "Add Toast component with timer, action support, and animations"
```

---

### Task 4: Create the ToastContainer component

**Files:**
- Create: `frontend/src/app/components/toast/ToastContainer.tsx`

- [ ] **Step 1: Create the ToastContainer component**

```tsx
import { useEffect } from "react"
import { useNotificationStore } from "../../../core/store/notificationStore"
import { Toast } from "./Toast"

const MAX_VISIBLE = 3

export function ToastContainer() {
  const notifications = useNotificationStore((s) => s.notifications)
  const dismissToast = useNotificationStore((s) => s.dismissToast)

  const visible = notifications.filter((n) => !n.dismissed)

  // Auto-dismiss notifications beyond MAX_VISIBLE
  useEffect(() => {
    visible.slice(MAX_VISIBLE).forEach((n) => dismissToast(n.id))
  }, [visible, dismissToast])

  const displayed = visible.slice(0, MAX_VISIBLE)

  if (displayed.length === 0) return null

  return (
    <div className="pointer-events-none fixed top-14 left-1/2 z-50 flex -translate-x-1/2 flex-col gap-3 p-4">
      {displayed.map((n) => (
        <Toast key={n.id} notification={n} />
      ))}
    </div>
  )
}
```

- [ ] **Step 2: Verify the frontend builds**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/components/toast/ToastContainer.tsx
git commit -m "Add ToastContainer with max-3 visible toast limit"
```

---

### Task 5: Mount ToastContainer in AppLayout

**Files:**
- Modify: `frontend/src/app/layouts/AppLayout.tsx`

- [ ] **Step 1: Add the import**

Add at the top of the file, with the other component imports (after line 14):

```typescript
import { ToastContainer } from "../components/toast/ToastContainer"
```

- [ ] **Step 2: Add ToastContainer to the JSX**

In the return statement, add `<ToastContainer />` as the last child of the outermost `div` (after the closing `</div>` of the content wrapper, before the final `</div>`). The JSX should look like:

```tsx
    </div>
    <ToastContainer />
  </div>
```

Specifically, insert `<ToastContainer />` between `AppLayout.tsx:225` (the closing `</div>` of the content area) and `AppLayout.tsx:226` (the final `</div>`).

- [ ] **Step 3: Verify the frontend builds**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm run build`
Expected: Build succeeds with no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/layouts/AppLayout.tsx
git commit -m "Mount ToastContainer in AppLayout"
```

---

### Task 6: Manual smoke test

- [ ] **Step 1: Start the frontend dev server**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm dev`

- [ ] **Step 2: Open the browser console and trigger test toasts**

In the browser dev console, run each of these to verify all four levels render correctly:

```javascript
// Access the store
const store = window.__ZUSTAND_STORES__?.notification

// If the above doesn't work, use this approach in the React DevTools or
// add a temporary test button. Alternatively, trigger a real action that
// calls addNotification.

// Test all 4 levels:
// 1. Success with action
document.dispatchEvent(new CustomEvent('test-toast', { detail: { level: 'success', title: 'Session deleted', message: 'The chat session has been removed.', action: { label: 'Undo', onClick: () => console.log('Undo clicked') } } }))

// 2. Info
// 3. Warning
// 4. Error (should NOT auto-dismiss)
```

Since the store is not exposed on `window`, the simplest smoke test is to temporarily add a call to `addNotification` in `AppLayout.tsx` inside a `useEffect` with an empty dependency array, verify the toast appears, then remove it.

- [ ] **Step 3: Verify**

- Toast appears top-centre, below the Topbar
- Correct colours per level (green/purple/gold/red)
- Success/info dismiss after ~4s, warning after ~6s, error stays
- Hover pauses the timer
- X button dismisses immediately
- Action button calls the callback and dismisses
- Enter animation slides down, exit animation slides up and fades

- [ ] **Step 4: Remove any temporary test code and commit if needed**

```bash
git add -A
git commit -m "Complete toast notification system (UX-002)"
```

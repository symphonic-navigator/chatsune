# Toast Notification System — Design Spec

**Date:** 2026-04-06
**Status:** Approved
**Addresses:** UX-002 (primary), enables UX-004, UX-025, UX-027

---

## Overview

A toast notification system that renders visual feedback for user actions, errors, and system events. Built as a custom component consuming the existing `notificationStore`, positioned top-centre below the Topbar.

---

## Store Changes

### File: `frontend/src/core/store/notificationStore.ts`

**Extended notification levels:**

```typescript
level: "success" | "error" | "info" | "warning"
```

**New optional fields on `AppNotification`:**

```typescript
action?: {
  label: string
  onClick: () => void
}
duration?: number  // ms, overrides level default
```

**`NewNotification` type** gains the same optional fields (`action`, `duration`).

**No other store changes.** `addNotification` and `dismissToast` remain as-is. Timer logic lives in the Toast component, not in the store.

---

## Auto-Dismiss Behaviour

| Level     | Default timeout | Dismiss  |
|-----------|----------------|----------|
| `success` | 4 000 ms       | Auto + X |
| `info`    | 4 000 ms       | Auto + X |
| `warning` | 6 000 ms       | Auto + X |
| `error`   | None           | X only   |

- `duration` field on a notification overrides the level default.
- Timer **pauses** on `mouseenter`, **resumes** on `mouseleave`.
- Toasts with an `action` button follow the same rules (timer still runs, pauses on hover).

---

## Components

### `frontend/src/app/components/toast/ToastContainer.tsx`

- Reads `notifications` from `useNotificationStore`
- Filters to non-dismissed notifications
- Renders at most **3 visible toasts** (newest first); older ones are auto-dismissed
- Positioned: `fixed top-14 left-1/2 -translate-x-1/2 z-50`
- `pointer-events-none` on container, `pointer-events-auto` on individual toasts
- Flex column with `gap-3`, toasts stack downward

### `frontend/src/app/components/toast/Toast.tsx`

Single toast component. Receives an `AppNotification` and renders:

```
[ Icon ]  [ Title          ]  [ Action? ]  [ X ]
          [ Message (opt.) ]
```

**Layout:**
- Flex row, `items-center`, `gap-3`
- Padding: `px-4 py-3`
- Border-radius: `rounded-lg`
- Background: level colour at 8% opacity
- Border: level colour at 25% opacity
- Max width: `max-w-md` (28rem / 448px)

**Colour mapping:**

| Level     | Colour variable | Hex       |
|-----------|----------------|-----------|
| `success` | `--color-live` | `#22c55e` |
| `info`    | `--color-purple` | `#7c5cbf` |
| `warning` | `--color-gold` | `#c9a84c` |
| `error`   | `red-400`      | `#f87171` |

**Icons (Unicode):**
- success: ✓ (U+2713)
- info: ℹ (U+2139)
- warning: ⚠ (U+26A0)
- error: ✗ (U+2717)

**Action button:**
- Level-coloured text on level-coloured background (15% opacity)
- Level-coloured border (30% opacity)
- `rounded-md`, `px-2.5 py-1`, `text-[11px]`
- Calls `action.onClick()` then `dismissToast(id)`

**Dismiss X:**
- `text-white/30`, hover `text-white/60`
- Calls `dismissToast(id)`

**Timer logic:**
- `useEffect` sets a timeout based on duration (level default or override)
- `onMouseEnter`: clears timeout, stores remaining time
- `onMouseLeave`: sets new timeout with remaining time
- Error toasts with no `duration` override: no timeout set

---

## Animations

### New keyframes in `frontend/src/index.css`

```css
@keyframes toast-enter {
  from {
    opacity: 0;
    transform: translateY(-8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes toast-exit {
  from {
    opacity: 1;
    transform: translateY(0);
  }
  to {
    opacity: 0;
    transform: translateY(-8px);
  }
}
```

- Enter: `animation: toast-enter 0.2s ease-out`
- Exit: triggered by adding an `exiting` class, then removing the element after the animation completes (200ms)
- Tailwind utility classes registered: `animate-toast-enter`, `animate-toast-exit`

---

## Integration

### File: `frontend/src/app/layouts/AppLayout.tsx`

Add `<ToastContainer />` as a direct child of the outermost `div`, after `<Sidebar>` and the content wrapper:

```tsx
<div className="flex h-full overflow-hidden bg-base text-white">
  <Sidebar ... />
  <div className="relative flex min-w-0 flex-1 flex-col">
    ...
  </div>
  <ToastContainer />
</div>
```

No props needed — the component is self-contained via the store.

---

## Constraints

- No third-party dependencies
- No React portals — `z-50` is sufficient since ToastContainer is a sibling of all content
- Maximum 20 notifications retained in store (existing `MAX_NOTIFICATIONS`)
- Maximum 3 visible toasts rendered at once
- Toast component handles its own timer lifecycle — store stays simple

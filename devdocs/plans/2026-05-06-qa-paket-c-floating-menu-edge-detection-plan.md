# QA Paket C — FloatingMenu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the three sidebar row context menus (PersonaItem,
ProjectSidebarItem, HistoryItem) from being clipped by the
sidebar's `overflow-hidden` ancestors and add edge-aware
positioning, by introducing one shared `<FloatingMenu>` component
that portals to `document.body` and migrating the three call sites
to use it.

**Architecture:** New component
`frontend/src/app/components/floating/FloatingMenu.tsx` owns
portalling, edge-aware position computation (default below+right,
flips on viewport-overflow with 8 px margin), and dismiss
behaviour (click-outside, Escape, window resize, window scroll).
Consumers pass `open`, `onClose`, an `anchorRef` to the trigger
button, an optional `width`, and the menu items as children. Each
of the three sidebar row components migrates by adding a ref to
its trigger button, replacing its inline `<div>` menu with a
`<FloatingMenu>` invocation, and dropping its local mousedown
click-outside `useEffect`.

**Tech Stack:** React 18 (`useLayoutEffect`, `useRef`, `useState`,
`useEffect`), `react-dom` (`createPortal`), Tailwind, TypeScript
strict, pnpm, Vitest (no tests added — manual verification per the
project's standing convention for surface UI).

**Spec:** `devdocs/specs/2026-05-06-qa-paket-c-floating-menu-edge-detection-design.md`

**Subagent constraint:** Per project memory, subagents must NOT
merge, push, or switch branches. Implement on the feature branch
the controller created. The dispatching agent will handle merging.

---

## File map

```
frontend/src/
  app/components/
    floating/FloatingMenu.tsx                  [CREATE] — Task 1
    sidebar/PersonaItem.tsx                    [MODIFY] — Task 2
    sidebar/ProjectSidebarItem.tsx             [MODIFY] — Task 3
    sidebar/HistoryItem.tsx                    [MODIFY] — Task 4
```

Tasks 2-4 depend on Task 1 (they import the new component). They
must run sequentially after Task 1, and per the
subagent-driven-development skill rule "never dispatch multiple
implementer subagents in parallel" they also run sequentially with
respect to each other. They touch different files so there are no
merge conflicts between them.

No automated tests added — both the component and the migrations
are surface-level UI; manual verification on a real device is the
primary check, matching the convention from QA Paket A and B.

---

## Task 1: Create the `FloatingMenu` component

**Files:**
- Create: `frontend/src/app/components/floating/FloatingMenu.tsx`

- [ ] **Step 1: Create the directory and file**

Run from the repo root:
```bash
mkdir -p frontend/src/app/components/floating
```

(If `frontend/src/app/components/floating` already exists, this is
a no-op — proceed.)

- [ ] **Step 2: Write the component**

Create `frontend/src/app/components/floating/FloatingMenu.tsx`
with the following exact contents:

```tsx
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

export interface FloatingMenuProps {
  /** Whether the menu is open. The menu is unmounted when false. */
  open: boolean
  /** Called when the menu should close (click-outside, Escape, resize, scroll). */
  onClose: () => void
  /** Ref to the trigger element. Used to anchor the menu and to keep
   *  click-outside detection from firing on the trigger itself. */
  anchorRef: React.RefObject<HTMLElement>
  /** Menu width in pixels. Default 192 (Tailwind w-48). */
  width?: number
  /** Optional ARIA role override. Default `menu`. */
  role?: string
  /** Menu items. */
  children: React.ReactNode
}

const VIEWPORT_MARGIN = 8

/**
 * Renders a floating menu portalled to `document.body` with
 * edge-aware positioning. Default placement is below the anchor,
 * with the menu's right edge aligned to the anchor's right edge.
 * Flips upward when below would overflow the viewport bottom and
 * leftward becomes rightward when the menu would overflow the
 * viewport's left edge. All flips keep an 8 px margin from the
 * viewport edges.
 *
 * Closes on click outside (anchor and menu both excluded), Escape,
 * window resize, and window scroll. The latter two avoid having to
 * recompute on every layout event — the user can re-open after.
 */
export function FloatingMenu({
  open,
  onClose,
  anchorRef,
  width = 192,
  role = 'menu',
  children,
}: FloatingMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null)

  useLayoutEffect(() => {
    if (!open) {
      setPosition(null)
      return
    }
    const compute = () => {
      const anchor = anchorRef.current
      if (!anchor) return
      const a = anchor.getBoundingClientRect()
      const menuHeight = menuRef.current?.offsetHeight ?? 200
      const vw = window.innerWidth
      const vh = window.innerHeight

      // Default: below the anchor, right edges aligned.
      let top = a.bottom + 4
      let left = a.right - width

      // Vertical flip: open above when below would overflow.
      if (top + menuHeight > vh - VIEWPORT_MARGIN) {
        top = a.top - menuHeight - 4
      }
      // Horizontal flip: align to anchor's left edge when default
      // would overflow the viewport's left edge.
      if (left < VIEWPORT_MARGIN) {
        left = a.left
      }
      // Defensive clamp so the menu always stays inside the
      // viewport with the configured margin.
      top = Math.max(VIEWPORT_MARGIN, Math.min(top, vh - menuHeight - VIEWPORT_MARGIN))
      left = Math.max(VIEWPORT_MARGIN, Math.min(left, vw - width - VIEWPORT_MARGIN))

      setPosition({ top, left })
    }
    // First compute uses the height fallback (200) before the menu
    // is in the DOM; the rAF compute uses the real measured height.
    compute()
    const raf = requestAnimationFrame(compute)
    return () => cancelAnimationFrame(raf)
  }, [open, anchorRef, width])

  useEffect(() => {
    if (!open) return
    const onMouseDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (anchorRef.current?.contains(t)) return
      if (menuRef.current?.contains(t)) return
      onClose()
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    const onResize = () => onClose()
    const onScroll = () => onClose()
    document.addEventListener('mousedown', onMouseDown)
    document.addEventListener('keydown', onKeyDown)
    window.addEventListener('resize', onResize)
    // capture so that scroll inside any scrollable ancestor closes the menu.
    window.addEventListener('scroll', onScroll, true)
    return () => {
      document.removeEventListener('mousedown', onMouseDown)
      document.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('resize', onResize)
      window.removeEventListener('scroll', onScroll, true)
    }
  }, [open, anchorRef, onClose])

  if (!open) return null

  return createPortal(
    <div
      ref={menuRef}
      role={role}
      className="z-50 rounded-lg border border-white/10 bg-elevated py-1 shadow-xl"
      style={{
        position: 'fixed',
        top: position?.top ?? -9999,
        left: position?.left ?? -9999,
        width,
        visibility: position === null ? 'hidden' : 'visible',
      }}
      onClick={(e) => e.stopPropagation()}
    >
      {children}
    </div>,
    document.body,
  )
}
```

Notes for the implementer:
- The `position: fixed` is critical — combined with portalling to
  `document.body`, it isolates the menu from any ancestor's
  overflow, transform, or scroll context.
- The `position === null` initial state with off-screen coords +
  `visibility: hidden` prevents the menu from briefly appearing at
  (-9999, -9999) before the real position is computed.
- The rAF after the initial sync `compute()` re-measures the menu
  once it has been mounted with content, so the vertical-flip
  decision uses the real height instead of the fallback `200`.
- Capture-phase scroll listener ensures scrolling inside any
  scrollable ancestor (e.g. the sidebar's own scroll container)
  also dismisses the menu.

- [ ] **Step 3: Build verification**

Run from `frontend/`:
```bash
pnpm run build
```
Expected: clean build, no TS errors. The component is unused at
this point — that's fine; TS does not warn on unused exports.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/floating/FloatingMenu.tsx
git commit -m "Add FloatingMenu component with portal and edge-aware positioning"
```

---

## Task 2: Migrate `PersonaItem` to FloatingMenu

**Files:**
- Modify: `frontend/src/app/components/sidebar/PersonaItem.tsx`

- [ ] **Step 1: Locate the landmarks**

Open `frontend/src/app/components/sidebar/PersonaItem.tsx` and
confirm:
- Line 1: `import { useState, useRef, useEffect } from "react"`
- Line 47: `const menuRef = useRef<HTMLDivElement>(null)`
- Lines 55-64: the local mousedown click-outside `useEffect` for
  `menuOpen`.
- Lines 128-138: the trigger button (the `···` button with
  `onClick={(e) => { e.stopPropagation(); setMenuOpen(true) }}`).
- Lines 141-163: the conditional inline menu `<div>`.
- The container `<div>` at line 81-86 has `relative` positioning;
  this is no longer required for the menu (it portals to body) but
  keep it — other elements still rely on it.

- [ ] **Step 2: Update imports**

Change line 1 from:
```tsx
import { useState, useRef, useEffect } from "react"
```
to:
```tsx
import { useState, useRef } from "react"
```
(`useEffect` is no longer needed in this file after Step 4; the
import drop happens here so the build is clean after every step.)

Add the FloatingMenu import alongside the existing relative
imports (e.g. after the `KissMarkIcon` import on line 8):
```tsx
import { FloatingMenu } from "../floating/FloatingMenu"
```

- [ ] **Step 3: Add a trigger ref**

Replace line 47:
```tsx
const menuRef = useRef<HTMLDivElement>(null)
```
with:
```tsx
const triggerRef = useRef<HTMLButtonElement>(null)
```
(`menuRef` is no longer used after Step 4 — remove it now to keep
the diff coherent.)

- [ ] **Step 4: Drop the local click-outside `useEffect`**

Delete lines 55-64 in their entirety:
```tsx
useEffect(() => {
  if (!menuOpen) return
  const handler = (e: MouseEvent) => {
    if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
      setMenuOpen(false)
    }
  }
  document.addEventListener("mousedown", handler)
  return () => document.removeEventListener("mousedown", handler)
}, [menuOpen])
```

`FloatingMenu` handles click-outside internally.

- [ ] **Step 5: Attach the trigger ref to the button**

In the trigger button at lines 128-138, add `ref={triggerRef}` to
the `<button>` element. The full updated block should read:

```tsx
<button
  ref={triggerRef}
  type="button"
  aria-label="More options"
  title="More options"
  aria-haspopup="menu"
  aria-expanded={menuOpen}
  className="flex h-5 w-5 items-center justify-center rounded text-sm text-white/60 opacity-0 transition-all hover:bg-white/10 hover:text-white/85 group-hover:opacity-100 focus:opacity-100 group-focus-within:opacity-100 [@media(hover:none)]:opacity-100"
  onClick={(e) => { e.stopPropagation(); setMenuOpen(true) }}
>
  ···
</button>
```

- [ ] **Step 6: Replace the inline menu with FloatingMenu**

Replace the entire conditional menu block (lines 141-163):

```tsx
{menuOpen && (
  <div
    ref={menuRef}
    className="absolute right-2 top-8 z-50 w-48 rounded-lg border border-white/10 bg-elevated py-1 shadow-xl"
    onClick={(e) => e.stopPropagation()}
  >
    {menuItems.map((item, idx) => {
      if ("divider" in item) {
        return <div key={`div-${idx}`} className="h-px bg-white/10 my-1 mx-2" aria-hidden />
      }
      return (
        <button
          key={item.label}
          type="button"
          onClick={item.action}
          className="w-full px-3 py-1.5 text-left text-[13px] text-white/70 transition-colors hover:bg-white/6"
        >
          {item.label}
        </button>
      )
    })}
  </div>
)}
```

with:

```tsx
<FloatingMenu
  open={menuOpen}
  onClose={() => setMenuOpen(false)}
  anchorRef={triggerRef}
  width={192}
>
  {menuItems.map((item, idx) => {
    if ("divider" in item) {
      return <div key={`div-${idx}`} className="h-px bg-white/10 my-1 mx-2" aria-hidden />
    }
    return (
      <button
        key={item.label}
        type="button"
        onClick={item.action}
        className="w-full px-3 py-1.5 text-left text-[13px] text-white/70 transition-colors hover:bg-white/6"
      >
        {item.label}
      </button>
    )
  })}
</FloatingMenu>
```

The menu items themselves are unchanged — the divider, button
className, and item actions all stay identical. Only the wrapping
container is replaced.

- [ ] **Step 7: Build verification**

Run from `frontend/`:
```bash
pnpm run build
```
Expected: clean build, no TS errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/app/components/sidebar/PersonaItem.tsx
git commit -m "Migrate PersonaItem context menu to FloatingMenu"
```

---

## Task 3: Migrate `ProjectSidebarItem` to FloatingMenu

**Files:**
- Modify: `frontend/src/app/components/sidebar/ProjectSidebarItem.tsx`

- [ ] **Step 1: Locate the landmarks**

Open `frontend/src/app/components/sidebar/ProjectSidebarItem.tsx`
and confirm:
- Line 1: `import { useEffect, useRef, useState } from "react"`
- Line 42: `const menuRef = useRef<HTMLDivElement>(null)`
- Lines 46-55: the local mousedown click-outside `useEffect`.
- Lines 141-154: the trigger button.
- Lines 156-180: the conditional inline menu `<div>`.

- [ ] **Step 2: Update imports**

Change line 1 from:
```tsx
import { useEffect, useRef, useState } from "react"
```
to:
```tsx
import { useRef, useState } from "react"
```

Add the FloatingMenu import alongside the existing relative
imports (e.g. after the `ProjectDto` import on line 4):
```tsx
import { FloatingMenu } from "../floating/FloatingMenu"
```

- [ ] **Step 3: Replace `menuRef` with `triggerRef`**

Replace line 42:
```tsx
const menuRef = useRef<HTMLDivElement>(null)
```
with:
```tsx
const triggerRef = useRef<HTMLButtonElement>(null)
```

- [ ] **Step 4: Drop the local click-outside `useEffect`**

Delete lines 46-55 in their entirety:
```tsx
useEffect(() => {
  if (!menuOpen) return
  const handler = (e: MouseEvent) => {
    if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
      setMenuOpen(false)
    }
  }
  document.addEventListener("mousedown", handler)
  return () => document.removeEventListener("mousedown", handler)
}, [menuOpen])
```

The right-click and long-press triggers (`onContextMenu`,
`onTouchStart` etc. on the row container at lines 121-128) keep
their existing behaviour — they still call `setMenuOpen(true)`,
and FloatingMenu still anchors to `triggerRef`. (The right-click
position is anchored to the kebab button, not to the cursor —
this matches the existing inline-menu behaviour, which also
anchored to a fixed offset rather than cursor coords.)

- [ ] **Step 5: Attach the trigger ref to the button**

In the trigger button at lines 141-154, add `ref={triggerRef}`.
Full updated block:

```tsx
<button
  ref={triggerRef}
  type="button"
  aria-label="More options"
  title="More options"
  aria-haspopup="menu"
  aria-expanded={menuOpen}
  className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded text-sm text-white/60 opacity-0 transition-all hover:bg-white/10 hover:text-white/85 group-hover:opacity-100 focus:opacity-100 group-focus-within:opacity-100 [@media(hover:none)]:opacity-100"
  onClick={(e) => {
    e.stopPropagation()
    setMenuOpen(true)
  }}
>
  ···
</button>
```

- [ ] **Step 6: Replace the inline menu with FloatingMenu**

Replace the entire conditional menu block (lines 156-180):

```tsx
{menuOpen && (
  <div
    ref={menuRef}
    role="menu"
    className="absolute right-2 top-8 z-50 w-44 rounded-lg border border-white/10 bg-elevated py-1 shadow-xl"
    onClick={(e) => e.stopPropagation()}
  >
    {menuItems.map((item, idx) => {
      if ("divider" in item) {
        return <div key={`div-${idx}`} className="mx-2 my-1 h-px bg-white/10" aria-hidden />
      }
      return (
        <button
          key={item.label}
          type="button"
          role="menuitem"
          onClick={item.action}
          className="w-full px-3 py-1.5 text-left text-[13px] text-white/70 transition-colors hover:bg-white/6"
        >
          {item.label}
        </button>
      )
    })}
  </div>
)}
```

with:

```tsx
<FloatingMenu
  open={menuOpen}
  onClose={() => setMenuOpen(false)}
  anchorRef={triggerRef}
  width={176}
  role="menu"
>
  {menuItems.map((item, idx) => {
    if ("divider" in item) {
      return <div key={`div-${idx}`} className="mx-2 my-1 h-px bg-white/10" aria-hidden />
    }
    return (
      <button
        key={item.label}
        type="button"
        role="menuitem"
        onClick={item.action}
        className="w-full px-3 py-1.5 text-left text-[13px] text-white/70 transition-colors hover:bg-white/6"
      >
        {item.label}
      </button>
    )
  })}
</FloatingMenu>
```

`width={176}` matches the existing `w-44` (44 × 4 = 176 px).

- [ ] **Step 7: Build verification**

Run from `frontend/`:
```bash
pnpm run build
```
Expected: clean build, no TS errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/app/components/sidebar/ProjectSidebarItem.tsx
git commit -m "Migrate ProjectSidebarItem context menu to FloatingMenu"
```

---

## Task 4: Migrate `HistoryItem` to FloatingMenu

**Files:**
- Modify: `frontend/src/app/components/sidebar/HistoryItem.tsx`

- [ ] **Step 1: Locate the landmarks**

Open `frontend/src/app/components/sidebar/HistoryItem.tsx` and
confirm:
- Line 1: `import { useState, useRef, useEffect } from "react"`
- Line 36: `const menuRef = useRef<HTMLDivElement>(null)`
- Lines 41-45: the route-change `useEffect` that closes the menu —
  **keep this**, it is independent of FloatingMenu's dismiss logic.
- Lines 47-52: the focus `useEffect` for the rename input — keep.
- Lines 74-84: the local mousedown click-outside `useEffect` for
  `menuOpen` — to be removed.
- Lines 136-143: the trigger button.
- Lines 145-199: the conditional inline menu `<div>` with its
  Pin/Rename/Delete (with confirm-state) buttons.

- [ ] **Step 2: Update imports**

`useEffect` stays (still used for the route-change and rename-focus
effects). Only add the FloatingMenu import alongside the existing
relative imports (e.g. after the `PINNED_STRIPE_STYLE` import on
line 6):
```tsx
import { FloatingMenu } from "../floating/FloatingMenu"
```

- [ ] **Step 3: Replace `menuRef` with `triggerRef`**

Replace line 36:
```tsx
const menuRef = useRef<HTMLDivElement>(null)
```
with:
```tsx
const triggerRef = useRef<HTMLButtonElement>(null)
```

- [ ] **Step 4: Drop the local click-outside `useEffect`**

Delete lines 74-84 in their entirety:
```tsx
useEffect(() => {
  if (!menuOpen) return
  const handler = (e: MouseEvent) => {
    if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
      setMenuOpen(false)
      setConfirmDelete(false)
    }
  }
  document.addEventListener("mousedown", handler)
  return () => document.removeEventListener("mousedown", handler)
}, [menuOpen])
```

The route-change effect at lines 41-45 also resets
`setConfirmDelete(false)`, so the loss of the inline reset on
click-outside is acceptable: when FloatingMenu calls `onClose`,
`menuOpen` becomes false; on next open, `confirmDelete` is reset
by the route-change effect (or the user manually clicks Delete
once to enter confirm state, which is the existing two-click
flow). To preserve the exact previous behaviour where
click-outside also reset confirm state, change the `onClose`
prop in Step 6 to a small inline closure that resets both — see
that step.

- [ ] **Step 5: Attach the trigger ref to the button**

In the trigger button at lines 136-143, add `ref={triggerRef}`.
Full updated block:

```tsx
<button
  ref={triggerRef}
  type="button"
  aria-label="More options"
  className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded text-sm text-white/30 opacity-0 transition-all hover:bg-white/10 hover:text-white/70 group-hover:opacity-100 [@media(hover:none)]:opacity-100"
  onClick={(e) => { e.stopPropagation(); setMenuOpen(true) }}
>
  ···
</button>
```

- [ ] **Step 6: Replace the inline menu with FloatingMenu**

Replace the entire conditional menu block (lines 145-199):

```tsx
{menuOpen && (
  <div
    ref={menuRef}
    className="absolute right-2 top-8 z-50 w-40 rounded-lg border border-white/10 bg-elevated py-1 shadow-xl"
    onClick={(e) => e.stopPropagation()}
  >
    {/* Pin / Unpin */}
    {onTogglePin && (
      <button
        type="button"
        onClick={() => {
          onTogglePin(session, !isPinned)
          setMenuOpen(false)
        }}
        className="w-full px-3 py-1.5 text-left text-[13px] text-white/50 transition-colors hover:bg-white/6"
      >
        {isPinned ? "Unpin" : "Pin"}
      </button>
    )}

    {/* Rename */}
    {onRename && (
      <button
        type="button"
        onClick={startRename}
        className="w-full px-3 py-1.5 text-left text-[13px] text-white/50 transition-colors hover:bg-white/6"
      >
        Rename
      </button>
    )}

    {/* Delete */}
    {confirmDelete ? (
      <button
        type="button"
        onClick={() => {
          onDelete(session)
          setMenuOpen(false)
          setConfirmDelete(false)
        }}
        className="w-full px-3 py-1.5 text-left text-[13px] text-red-400 transition-colors hover:bg-red-400/10"
      >
        Confirm delete?
      </button>
    ) : (
      <button
        type="button"
        onClick={() => setConfirmDelete(true)}
        className="w-full px-3 py-1.5 text-left text-[13px] text-white/50 transition-colors hover:bg-white/6"
      >
        Delete
      </button>
    )}
  </div>
)}
```

with:

```tsx
<FloatingMenu
  open={menuOpen}
  onClose={() => {
    setMenuOpen(false)
    setConfirmDelete(false)
  }}
  anchorRef={triggerRef}
  width={160}
>
  {/* Pin / Unpin */}
  {onTogglePin && (
    <button
      type="button"
      onClick={() => {
        onTogglePin(session, !isPinned)
        setMenuOpen(false)
      }}
      className="w-full px-3 py-1.5 text-left text-[13px] text-white/50 transition-colors hover:bg-white/6"
    >
      {isPinned ? "Unpin" : "Pin"}
    </button>
  )}

  {/* Rename */}
  {onRename && (
    <button
      type="button"
      onClick={startRename}
      className="w-full px-3 py-1.5 text-left text-[13px] text-white/50 transition-colors hover:bg-white/6"
    >
      Rename
    </button>
  )}

  {/* Delete */}
  {confirmDelete ? (
    <button
      type="button"
      onClick={() => {
        onDelete(session)
        setMenuOpen(false)
        setConfirmDelete(false)
      }}
      className="w-full px-3 py-1.5 text-left text-[13px] text-red-400 transition-colors hover:bg-red-400/10"
    >
      Confirm delete?
    </button>
  ) : (
    <button
      type="button"
      onClick={() => setConfirmDelete(true)}
      className="w-full px-3 py-1.5 text-left text-[13px] text-white/50 transition-colors hover:bg-white/6"
    >
      Delete
    </button>
  )}
</FloatingMenu>
```

The `onClose` closure resets both `menuOpen` and `confirmDelete`,
preserving the existing behaviour where dismissing the menu also
exits confirm-delete state. `width={160}` matches the existing
`w-40` (40 × 4 = 160 px).

- [ ] **Step 7: Build verification**

Run from `frontend/`:
```bash
pnpm run build
```
Expected: clean build, no TS errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/app/components/sidebar/HistoryItem.tsx
git commit -m "Migrate HistoryItem context menu to FloatingMenu"
```

---

## Self-review

**Spec coverage:**
- Spec §2 ("shared FloatingMenu component"): Task 1 implements
  exactly the interface described — portal, edge-aware position,
  default below+right with vertical and horizontal flips at 8 px
  margin, click-outside / Escape / resize / scroll dismiss,
  shared container styling.
- Spec §3 ("integration: three call sites"): Tasks 2, 3, 4 each
  migrate one of the three identified components, preserve menu
  items unchanged, drop the local mousedown effect, and use the
  spec-mandated widths (192, 176, 160).
- Spec §5 ("out of scope"): plan doesn't touch other floating
  elements, doesn't change parent overflow rules, doesn't add
  tests, doesn't change z-index hierarchy.
- Spec §7 ("manual verification"): plan defers manual verification
  to the controller (per the project's standard for the subagent
  flow).

**Placeholder scan:** None — all code blocks are complete, every
line reference is content-anchored where line numbers might shift
(e.g. "the trigger button at lines 128-138" plus the full code
block to disambiguate).

**Type consistency:** `FloatingMenuProps` defined in Task 1 is
referenced consistently in Tasks 2-4 with `open`, `onClose`,
`anchorRef`, `width`, `role` (Task 3 only), `children`. The
trigger ref is typed `React.RefObject<HTMLButtonElement>` and
attached to `<button>` elements throughout — no mismatches.

# QA Paket C — Sidebar context menu edge detection (FloatingMenu)

Date: 2026-05-06
Status: Draft, ready for implementation

This spec covers Bug #2 from Ksena's QA list (2026-05-06): sidebar
row context menus disappear behind other elements / get clipped at
container edges. Concretely the persona-row context menu reproduces
the bug; the project-row and history-row menus share the exact same
pattern and are silently affected.

---

## 1. Problem

Three sidebar row context menus get clipped:

- `frontend/src/app/components/sidebar/PersonaItem.tsx:141-163`
- `frontend/src/app/components/sidebar/ProjectSidebarItem.tsx:156-180`
- `frontend/src/app/components/sidebar/HistoryItem.tsx:145-198`

All three render their menu as a sibling `<div>` inside the row,
positioned `absolute right-2 top-8 z-50`. Two ancestors carry
`overflow: hidden` — `ZoneSection.tsx:126` (the items container in
each sidebar zone) and `Sidebar.tsx:656` (the sidebar root). Because
`overflow: hidden` physically clips descendants regardless of
z-index, a high z-index does not help — the menu is removed from
the rendered output the moment it crosses the parent's bounds.
Bottom-of-zone rows are the worst case: the menu would extend
beneath the zone's bottom edge and is visibly cut off.

There is also no edge detection: the menu opens at a fixed
`right-2 top-8` regardless of where the row sits relative to the
viewport, so a row at the bottom of the sidebar can produce a menu
that runs off the bottom of the screen even after the
overflow-clipping is solved.

**Other floating elements** (topbar tooltips, project/persona
pickers, knowledge dropdown, jobs pill, etc.) are NOT in
overflow-hidden ancestors and are not part of this fix. They keep
their current positioning. Edge-detection on those is a
nice-to-have, not a reported bug.

---

## 2. Approach: shared `<FloatingMenu>` component

Add a new component `frontend/src/app/components/floating/FloatingMenu.tsx`
that the three sidebar row menus consume. It provides:

1. **Portal to `document.body`.** This places the menu outside the
   sidebar's overflow-hidden subtree, so clipping is structurally
   impossible.
2. **Edge-aware positioning.** The component measures the anchor's
   `getBoundingClientRect()` and its own rect, then chooses a
   placement that fits within the viewport with an 8 px margin
   from each edge.
3. **Standard container styling.** The visual shell — same border,
   background, shadow, rounded corners, and vertical padding the
   three current menus already share — lives in the component.
4. **Click-outside / Escape close.** Mousedown outside both the
   anchor and the menu closes it; pressing Escape closes it;
   window resize and window scroll close it (rather than
   recomputing position mid-interaction — keeps the implementation
   tiny and the UX predictable).

### Component API

```tsx
interface FloatingMenuProps {
  open: boolean
  onClose: () => void
  anchorRef: React.RefObject<HTMLElement>
  width?: number          // px; default 192 (== Tailwind w-48)
  children: React.ReactNode
}
```

Usage at a call site:

```tsx
const triggerRef = useRef<HTMLButtonElement>(null)
const [menuOpen, setMenuOpen] = useState(false)

<button ref={triggerRef} onClick={() => setMenuOpen((v) => !v)}>⋯</button>
<FloatingMenu
  open={menuOpen}
  onClose={() => setMenuOpen(false)}
  anchorRef={triggerRef}
  width={192}
>
  <button onClick={...}>Pin</button>
  <button onClick={...}>Edit</button>
  <button onClick={...}>Delete</button>
</FloatingMenu>
```

The consumer keeps full control of the menu items' content and
event handlers — `FloatingMenu` only owns positioning, portalling,
and dismiss behaviour.

### Default placement

Menu opens **below** the anchor with its **right edge aligned to
the anchor's right edge**. This matches the current
`absolute right-2 top-8` visual exactly when the anchor is the
trigger button itself (rather than the row), so the perceived
position does not move for users who already know the menus.

### Edge detection / flip rules

After measuring, apply these flips with an 8 px viewport margin:

- If the default placement would put the menu's bottom edge below
  `viewportHeight - 8` → flip vertically: anchor menu's **bottom
  edge to anchor's top edge** (open above instead of below).
- If the default placement would put the menu's left edge below 8
  → flip horizontally: anchor menu's **left edge to anchor's left
  edge** (extend rightward instead of leftward).
- Both flips can apply simultaneously (corner case: row near
  bottom-left of viewport, menu opens upward and rightward).

After flips, clamp the final coordinates so the menu always stays
within `[8, viewportWidth - 8]` × `[8, viewportHeight - 8]` —
defence in depth in case the menu is wider than half the viewport
on a very small screen.

### Position computation timing

Computed once on `open` becoming true, and once on every window
resize while open (rare). On window scroll, the menu **closes**
rather than recomputing — the user can re-open after they scroll.
This avoids needing scroll listeners on every ancestor and keeps
the implementation small. In practice the user rarely scrolls
while a context menu is open.

### Click-outside detection with portal

Standard pattern: subscribe to `document` `mousedown`. The handler
calls `onClose()` when the event target is **outside both** the
anchor element (so clicking the trigger itself doesn't immediately
close — the trigger's onClick is the toggler) and the menu element.

### Z-index

`z-50` matches the current menus' z-index. Sheets sit at z-50/z-51
and toast at z-60 — that hierarchy is intentional, the row context
menu should sit at the existing z-50 level. We do **not** raise
the z-index above what the existing menus used.

### Container styling

The portal renders this container by default, matching what the
three current menus all share:

```tsx
<div
  ref={menuRef}
  className="rounded-lg border border-white/10 bg-elevated py-1 shadow-xl"
  style={{ position: 'fixed', top: ..., left: ..., width: ... }}
  onClick={(e) => e.stopPropagation()}
>
  {children}
</div>
```

The `position: fixed` is critical — combined with portalling to
body, it isolates the menu from any ancestor's transform or scroll.

---

## 3. Integration: three call sites

After the component lands, migrate the three row menus. Each
migration is small and isolated:

### `PersonaItem.tsx`

Replace lines 141-163 (the inline `<div>` menu) with a
`<FloatingMenu>` invocation. Add a `triggerRef` to the kebab/dots
button that toggles `menuOpen`. Pass `width={192}` to match
existing `w-48`. Remove the local `useEffect` that listens for
`mousedown` outside `menuRef` (lines 55-64); FloatingMenu handles
this itself.

### `ProjectSidebarItem.tsx`

Same migration. Width `176` (`w-44`). The existing
right-click and long-press triggers (lines 64-69, 121-124) keep
their roles — they just toggle `menuOpen` instead of imperatively
positioning.

### `HistoryItem.tsx`

Same migration. Width `160` (`w-40`). The existing dynamic
"Confirm delete?" content (lines 177-188) is part of the children
and migrates as-is.

In all three: keep the existing menu items and their handlers
unchanged. The migration is purely about how the menu is
rendered/positioned, not what it contains.

---

## 4. Files

- **Create**: `frontend/src/app/components/floating/FloatingMenu.tsx`
  — the new component (~80-100 lines).
- **Modify**: `frontend/src/app/components/sidebar/PersonaItem.tsx`
  — migrate menu to FloatingMenu, add trigger ref, drop local
  click-outside.
- **Modify**: `frontend/src/app/components/sidebar/ProjectSidebarItem.tsx`
  — same migration.
- **Modify**: `frontend/src/app/components/sidebar/HistoryItem.tsx`
  — same migration.

No other files affected. No changes to ZoneSection or Sidebar
overflow rules — portal sidesteps them entirely.

---

## 5. Out of scope

- Migrating the other ~7 floating elements (topbar tooltips,
  pickers, dropdowns) — they don't have the overflow-clipping bug
  and edge detection on them is not reported as a problem.
- Changing the parent `overflow-hidden` rules. Those exist for
  layout reasons and the portal sidesteps the issue cleanly.
- Replacing the click-outside / escape pattern globally. Each
  component keeps its own dismiss logic; FloatingMenu handles its
  own.
- Animation / transitions on open. The current menus open
  instantly; the migrated ones open instantly too. Animation can
  be added later as a polish pass.
- Mobile-specific full-screen sheets for the menus. Long-press on
  mobile already triggers the menu (see ProjectSidebarItem); this
  spec keeps that behaviour and does NOT swap to a full-screen
  sheet on small screens.
- A11y improvements (ARIA roles, focus trap inside the menu). The
  current menus do not have these and adding them is a separate
  pass.
- Tests for the new component. Per the project's standing
  convention for surface-level UI components, manual verification
  is the primary check.

---

## 6. Build verification

- `pnpm run build` (frontend) clean.
- No backend changes.

## 7. Manual verification

On a real device, with the dev server running:

1. **Persona row, default placement.** Open sidebar, hover over a
   persona row near the top of the personas zone, click the
   kebab/⋯ button. Menu opens below + right-aligned with the
   trigger. All items visible.
2. **Persona row, vertical flip.** Scroll the personas zone so a
   row sits near the bottom of the visible viewport. Open its
   menu. Menu must flip upward (open above the trigger) so it
   stays inside the viewport with at least 8 px margin from the
   bottom.
3. **Persona row, no clipping in zone.** Same as step 2 but
   confirm the menu is NOT clipped by the sidebar's overflow —
   it should overlap the zone boundary cleanly because it
   renders in `document.body` via portal.
4. **Project row.** Repeat steps 1-3 with a project row in the
   sidebar's projects zone.
5. **History row.** Repeat steps 1-3 with a chat history row in
   the sidebar's history zone.
6. **Click-outside dismiss.** Open any menu, click anywhere
   outside it. Menu closes.
7. **Escape dismiss.** Open any menu, press Escape. Menu closes.
8. **Resize dismiss / reposition.** Open any menu, resize the
   browser window. Menu closes (resize is a close trigger; the
   spec calls this acceptable for simplicity). Re-open after the
   resize and confirm the new placement is correct.
9. **Scroll dismiss.** Open any menu, scroll inside the sidebar
   or main content. Menu closes.
10. **Right-click trigger (project row).** Right-click a project
    row to open the menu via the desktop secondary trigger. Menu
    opens, edge detection works, dismiss works.
11. **Long-press trigger (project row, mobile).** On a touch
    device, long-press a project row. Menu opens correctly.
12. **Cross-stacking.** Open a User-area modal (or any sheet),
    confirm sidebar context menus cannot be triggered while the
    sheet is open (existing behaviour — sheets block the
    sidebar). No regression.
13. **No double-menu.** Opening one row's menu while another is
    open closes the first. (Current behaviour relies on local
    `menuOpen` state per row plus the click-outside; verify no
    regression.)

## 8. Implementation notes

- React Portal: `import { createPortal } from 'react-dom'`.
- `position: fixed` on the menu container (not absolute) — fixed
  is relative to viewport, which is exactly what we want after
  portalling.
- Measure timing: on `open` becoming true, the menu must be in
  the DOM before `getBoundingClientRect()` returns useful
  numbers. Pattern: render the menu hidden (or off-screen) first,
  measure with a ref + `useLayoutEffect`, then commit the final
  position. Or: compute the position from anchor rect + `width`
  prop without measuring the menu (we know its width, and its
  height we approximate from item count or a typical max). The
  simpler path is to use the `width` prop for horizontal math and
  do a single post-mount `useLayoutEffect` to measure the height
  for the vertical-flip decision. Pick whichever is cleaner at
  implementation time.
- Subagent constraint per project memory: do not merge, do not
  push, do not switch branches.

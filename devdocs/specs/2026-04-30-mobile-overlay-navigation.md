# Mobile Overlay Navigation — Outline Dropdown

**Status:** Design accepted, plan pending.
**Date:** 2026-04-30.
**Affects:** `UserModal`, `AdminModal`, `PersonaOverlay`.

---

## Problem

The three full-screen overlays (`UserModal`, `AdminModal`, `PersonaOverlay`)
each render their navigation as one or two flex-wrapping rows of pill / tab
buttons. On viewports below `lg` (1024 px) these rows wrap onto two or three
lines and consume a large slice of the available vertical height before the
user has even seen the content.

`UserModal` is the worst offender: it has a two-level structure
(`TABS_TREE` in `userModalTree.ts`) so on a phone it shows up to seven
top-level pills wrapped to two rows plus a sub-row with up to seven sub-pills
on the active branch. `PersonaOverlay` (eight flat tabs, several with
chakra subtitles) and `AdminModal` (four flat tabs) are less extreme but
hit the same wrapping problem and visually fight the content for attention.

The goal is a single, calm, space-efficient navigation primitive that works
on phones and tablets, replaces the wrapping tab rows below the `lg`
breakpoint, and leaves the existing desktop layout untouched.

## Solution at a glance

Below `lg`, hide the existing tab rows and render a single new control row
under the overlay header:

- A full-width **dropdown trigger** that shows the current location as a
  one-line path (`Settings – LLM Providers` for hierarchical overlays,
  bare leaf name for flat ones, leaf name only when the active node is a
  leaf-only top tab).
- Tapping the trigger opens an **outline panel** anchored under it with
  every navigable destination in a single scrollable list. Top-level
  parents that themselves have children render as small uppercase
  section headers (greyed, non-clickable). Top-level entries that ARE
  leaves render as ordinary clickable rows. Children render indented.
- The active leaf is highlighted in the overlay's accent colour (gold by
  default, chakra hex for `PersonaOverlay`).
- A simple `▾` caret on the trigger rotates / colours when open. No
  separate menu icon — the existing burger icon in `AppLayout` is
  preserved for its own purpose.

At and above `lg`, nothing changes. The existing tab rows render as today.

A single shared component, `OverlayMobileNav`, is used by all three
overlays.

## Behaviour

### Trigger

- Closed: `1px` neutral border, subtle background, caret in `▾` shape.
- Open: border switches to the accent colour, caret rotates to `▴`.
- Path label rendered as a single line:
  - **Hierarchical (UserModal, active is a sub-leaf):**
    `<parent dimmed> – <leaf>` (real En-Dash `–`, U+2013, *not* a hyphen).
  - **Hierarchical, active is a leaf-only top tab (e.g. `About me`):**
    leaf name only.
  - **Flat (Admin, Persona):** leaf name only.
- If the path overflows, the leaf truncates with ellipsis; the parent stays
  visible in full.
- Clicking the trigger toggles the panel.

### Outline panel

- Anchored directly below the trigger inside the same nav row container.
- Background `#13101e`, `1px` neutral border, subtle drop shadow.
- `max-height: min(70vh, 460px)` — own vertical scroll; the overlay
  content below does not scroll along.
- Rendered nodes (the component never assumes hierarchy depth — it walks
  a flat array of nodes and decides per node):
  - **`NavSection`** — uppercase, small caps, dimmed white, `cursor: default`,
    not focusable, not clickable, `role="presentation"`. Used for top-level
    parents that have children.
  - **`NavLeaf` at top level (no parent section)** — normal weight, full
    contrast, clickable, `role="option"`.
  - **`NavLeaf` under a `NavSection`** — indented (~24 px from the left),
    slightly lower contrast than top-level leaves, clickable,
    `role="option"`.
- Active leaf: tinted background using the accent colour at low opacity,
  text in accent colour, `aria-selected="true"`.
- Badges: a small red `!` to the right of any flagged leaf. If a flagged
  leaf lives under a `NavSection`, the section header also shows a `!`.
  Propagation is automatic inside `OverlayMobileNav` (the caller passes
  `badges` keyed by leaf id).

### Open / close

- **Open:** click the trigger.
- **Close:**
  - Click the trigger again.
  - Click the backdrop (transparent, covers the rest of the overlay
    behind the panel; clicks outside close, clicks inside the panel do
    not).
  - `Escape` key.
  - Selecting any clickable leaf (auto-close after `onSelect`).

### Keyboard

- Arrow `Down` / `Up` while panel is open: move focus through clickable
  leaves only (skip `NavSection` headers).
- `Enter` / `Space`: select the focused leaf.
- `Tab`: cycles within trigger + panel while open (focus-trap analogous to
  the existing modal trap). On close, focus returns to the trigger.
- Initial focus on open: the active leaf, or the first clickable leaf if
  none is active. The active leaf is also brought into view via
  `scrollIntoView({ block: 'nearest' })` so a user who opens the panel on
  the seventh sub-tab doesn't see only the top of the list.

## Architecture

### New shared component

Lives at `frontend/src/app/components/overlay-mobile-nav/` (kebab-case
per the existing folder convention — e.g. `admin-modal/`, `user-modal/`,
`persona-overlay/`):

```
overlay-mobile-nav/
  OverlayMobileNav.tsx
  types.ts
  resolveCrumb.ts
  OverlayMobileNav.test.tsx
```

### Types

```ts
// types.ts
export interface NavLeaf {
  id: string
  label: string
  badge?: boolean
}

export interface NavSection {
  id: string
  label: string
  children: NavLeaf[]
}

export type NavNode = NavLeaf | NavSection

export function isSection(n: NavNode): n is NavSection {
  return 'children' in n
}
```

### Component contract

```ts
interface OverlayMobileNavProps {
  tree: NavNode[]
  activeId: string
  onSelect: (id: string) => void
  /** Override the default gold; PersonaOverlay passes chakra.hex. */
  accentColour?: string
  /** Optional aria-label override for the trigger. */
  ariaLabel?: string
}
```

Internal state: `open: boolean`. The component owns its own popover state;
the caller only owns the active id and reacts to `onSelect`.

### Path resolver helper

`resolveCrumb(tree: NavNode[], activeId: string): { parent?: string; leaf: string }`

- Walks the tree once; if `activeId` matches a top-level `NavLeaf` returns
  `{ leaf: label }`.
- If it matches a child of a `NavSection` returns `{ parent: section.label,
  leaf: child.label }`.
- If `activeId` is the id of a `NavSection` itself (defensive — should not
  happen in practice because sections are not selectable), returns the
  section label as the leaf.

### Mapping from existing structures

- **UserModal** — extend `userModalTree.ts` with a converter that emits
  `NavNode[]` directly from `TABS_TREE`. The two shapes are nearly
  identical (`children` lives only on parents that are sections), so the
  converter is a `map` with a `children?` check.
- **AdminModal** — inline mapping in `AdminModal.tsx`, four `NavLeaf`
  entries from the existing `TABS` constant.
- **PersonaOverlay** — inline mapping in `PersonaOverlay.tsx`, applies
  the existing filters (`isCreating` excludes everything but `edit`,
  `voice` only when `voiceEnabled` or already active) before mapping to
  `NavLeaf`. Filtering stays in the caller — the navigation component
  itself is generic.

### Render integration

Each overlay keeps its current desktop tab bars and adds the mobile
control row in parallel:

```tsx
{/* Desktop tab rows — unchanged */}
<div className="hidden lg:flex ...">
  {/* existing top-tab row */}
</div>
<div className="hidden lg:flex ...">
  {/* existing sub-tab row, where applicable */}
</div>

{/* New mobile control row */}
<div className="lg:hidden border-b border-white/6 px-4 py-2 flex-shrink-0 bg-white/2">
  <OverlayMobileNav
    tree={mobileTree}
    activeId={activeLeafId}
    onSelect={handleMobileSelect}
    accentColour={accentColour}
  />
</div>
```

`activeLeafId` is whichever id represents the user's current location:
the active sub-tab when one exists, otherwise the active top-tab.
`handleMobileSelect` reuses the same handlers as the desktop click paths
(notably `setLastSub` in `UserModal`) so the existing "Settings remembers
which sub you were on" behaviour is preserved.

## Accessibility

- Trigger: `<button type="button" aria-haspopup="listbox" aria-expanded={open}
  aria-controls={panelId}>`.
- Panel: `role="listbox" id={panelId}`.
- `NavLeaf` rows: `role="option" aria-selected={id === activeId}` and
  `tabIndex={id === activeId ? 0 : -1}` while panel is open.
- `NavSection` headers: `role="presentation"`, `aria-hidden="true"` on the
  text since they are decorative within the listbox semantics.
- Focus-trap mirrors the existing overlay trap (`UserModal.tsx:82`,
  `AdminModal.tsx:32`, `PersonaOverlay.tsx:82`) — no new global handlers.

## Visual specifics (for the implementer)

- Trigger height: `~40 px` (`px-3 py-2.5`, line height ~`13 px`). The
  control row total height is `~60 px` (`py-2` outer padding plus the
  trigger). That replaces today's `~52 px` top-tab row and, for the
  UserModal, the additional `~36 px` sub-tab row — a net win of `~28 px`
  even before wrapping kicks in.
- Trigger background: `rgba(255,255,255,0.04)`, border
  `rgba(255,255,255,0.12)` closed, `rgba(<accent>, 0.45)` open.
- Path text: leaf in `rgba(255,255,255,0.92)` weight 500, parent in
  `rgba(255,255,255,0.5)` weight 400, separator `–` in
  `rgba(255,255,255,0.35)` with `0 6px` margin.
- Panel: `margin-top: 6px`, border `rgba(255,255,255,0.12)`,
  `border-radius: 8px`, `box-shadow: 0 8px 24px rgba(0,0,0,0.35)`.
- Section header rows: `text-transform: uppercase`, `font-size: 10px`,
  `letter-spacing: 0.5px`, padding `14px 14px 6px`, no bottom border.
- Leaf rows: `padding: 10px 14px`, font-size `13px` (top-level) or
  `12.5px` (under section), child indent `padding-left: 24px`,
  `border-bottom: 1px solid rgba(255,255,255,0.04)` between rows.
- Active leaf row: `background: rgba(<accent>, 0.08)`, text in accent.
- Caret: `▾` closed, `▴` open. `transition: transform 120ms` on the
  trigger if you want it animated; static is fine too.
- En-Dash separator: literal `–` (U+2013), never `-`. Lives in the
  component as a constant so it cannot be accidentally retyped as a
  hyphen.

## Tests

### Vitest — `OverlayMobileNav.test.tsx`

- Trigger renders the correct path:
  - flat `NavLeaf` only → leaf label.
  - `NavLeaf` nested in a `NavSection` → `parent – leaf`.
  - active id matches a top-level `NavLeaf` (i.e. leaf-only top of the
    UserModal tree) → leaf only.
- Clicking the trigger toggles `aria-expanded`.
- Clicking a `NavLeaf` calls `onSelect(id)` and closes the panel.
- Clicking a `NavSection` header does nothing (no `onSelect`, panel
  stays open).
- `Escape` closes the panel; backdrop click closes the panel; clicks
  inside the panel do not close it.
- ARIA attributes match the contract (haspopup, controls, role=listbox,
  aria-selected on active row).
- `accentColour` prop overrides the default border / active-row tint.
- Badge propagation: a flagged leaf inside a section flags the section
  header.

No new tests inside `UserModal.test.tsx`, `AdminModal` (no test file
exists), or `PersonaOverlay` — the integration is a one-line render of a
component covered by its own tests, and the existing `UserModal.test.tsx`
keeps covering the active-id wiring.

## Manual verification

To be performed by Chris on a real device before merging.

### Setup

- Pull the branch.
- `pnpm install` and `pnpm run dev` from `frontend/`.
- Open the app in a real phone browser (preferred) and at `width: 320px`
  and `width: 800px` in Chrome DevTools.

### UserModal

1. Open the user area on a `< 1024 px` viewport. Confirm the desktop tab
   rows are not visible and the new control row with a single dropdown
   trigger is rendered under the header.
2. Without opening the panel, navigate (via URL or by reopening) to the
   `LLM Providers` sub. Trigger should read `Settings – LLM Providers`,
   with `Settings` dimmed and the En-Dash visibly an En-Dash (slightly
   wider than a hyphen).
3. Tap the trigger. The outline panel opens. Confirm:
   - Section headers (`Chats`, `My data`, `Settings`) are uppercase and
     dimmed; tapping them does nothing.
   - Top-level leaves (`About me`, `Personas`, `Knowledge`, `Job-Log`)
     are normal weight and tappable.
   - Children are indented; the active leaf (`LLM Providers`) is gold.
   - The list scrolls if longer than the panel; the active leaf is
     visible without manual scrolling.
4. Tap `Display`. Panel closes, content switches to `Display`, the
   trigger now reads `Settings – Display` (i.e. the `Settings` last-sub
   memory was updated).
5. Switch top-level by tapping `Knowledge`. Panel closes, content
   switches, trigger reads `Knowledge`.
6. Reopen the panel and tap `Settings` heading — nothing happens. Tap
   `LLM Providers`. The panel closes and content reflects the change.
7. Provoke the LLM-providers `!` flag (delete all connections / no
   premium account). Confirm `!` appears on both the `Settings` section
   header and the `LLM Providers` leaf.
8. With the panel open, press `Escape`. Panel closes, focus returns to
   the trigger.
9. With the panel open, tap outside the panel but inside the overlay.
   Panel closes.

### AdminModal

1. Open the admin overlay on a `< 1024 px` viewport. New control row is
   present, trigger reads the active leaf only (e.g. `System`), no En-Dash.
2. Tap the trigger; the four leaves render flat (no section headers).
3. Switching tabs through the panel works and closes the panel each time.

### PersonaOverlay

1. Open a persona overlay on a `< 1024 px` viewport.
2. Trigger uses the persona's chakra colour for the open-state border
   and the active row tint instead of gold.
3. The `Voice` entry is hidden when the persona has no resolvable
   STT/TTS engine and the user is not currently on the Voice tab,
   matching the desktop filter rule.
4. In `New Persona` (creation) mode, the panel shows only `Edit`.

### Cross-cutting

1. Resize the window through `1024 px`. The layout flips between the
   desktop tab rows and the mobile control row at exactly that
   breakpoint, with no overlap and no flash.
2. With a screen reader (TalkBack on Android, VoiceOver on iOS, or
   Orca / NVDA in DevTools emulator), confirm that the trigger
   announces as a button with `expanded`/`collapsed` state and that the
   active leaf announces as the selected option.
3. At `width: 320px`, the path stays on one line. If a particularly
   long leaf label is added in the future, ellipsis kicks in only on
   the leaf — the parent never truncates.

## Out of scope

- Animation polish on the panel (slide / fade in). Keep it instant or
  use a single `transition` line; not the focus of this work.
- Replacing the burger icon in `AppLayout`. The new dropdown is its own
  trigger, in its own row, in the overlays only.
- Touching the desktop tab styling. The desktop view does not change.
- Adding a tablet-specific tier. Per project convention, `< lg` is one
  treatment and `>= lg` is the other; no third tier.
- Replacing or extending `userModalTree.ts`'s top-level sub-tab memory
  store. The mobile nav reuses it via the existing handlers.

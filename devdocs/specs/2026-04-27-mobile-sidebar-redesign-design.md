# Spec: Mobile-Sidebar Redesign

**Status:** Draft
**Date:** 2026-04-27
**Owner:** Chris

---

## Context & Motivation

The current sidebar works well on desktop but is overloaded on mobile. On the smallest
target device (iPhone SE, 375 × 667 px) the sidebar requires scrolling, takes only
~85 % of the viewport width (leaving an awkward strip of underlying content visible),
and exposes many controls — pinned/other personas with DnD, history list with inline
actions, projects scaffolding, multiple data tabs (Uploads/Artefacts/Images), settings
shortcut on the avatar — that are not all useful or even comfortable on a phone.

This redesign is mobile-only. The desktop sidebar (`>= lg`, i.e. 1024 px and up) is
unchanged in look, behaviour, and code paths. On mobile we keep the navigational role
of the sidebar but shed everything that is better lived elsewhere (persona reordering
on the Personas page, history actions on `History`, settings on `About me / Settings`).
Heavy lists move into in-sidebar overlays (full-width "subpages") that the user reaches
by tapping a row with a chevron.

The goal: on the smallest target phone the sidebar's main view fits without scrolling,
and the overlays use the existing User-Modal tab components (with a small responsive
tune-up) instead of growing a parallel implementation.

---

## Out of Scope

- Desktop sidebar (`>= lg`) — unchanged.
- Reorganising / redesigning the User-Modal tabs themselves. The History- and Bookmarks-
  Tab components get a minor responsive tweak (filter beneath search instead of next to
  it on narrow viewports, slightly tighter padding); no functional changes, no visual
  overhaul on desktop.
- Tablet-specific layout (`md` to `< lg`). These viewports get the same fullscreen
  mobile sidebar — same as most native mobile apps on tablet today. If beta feedback
  asks for a tablet-tuned drawer, that is a follow-up.
- Browser-Back integration with the in-sidebar stack. Browser-Back continues to navigate
  page routes; it does not pop the sidebar's internal stack. Same as today's User-Modal.
- Persona DnD reordering, persona pin/unpin, persona edit, incognito-chat — all stays
  on the Personas page.
- Search inside the New-Chat persona list. (Deliberately omitted to encourage users to
  keep their persona list tidy.)

---

## Architecture Overview

### Two viewport tiers

The split is binary, gated on `useViewport().isDesktop`:

- `>= lg` — **desktop sidebar.** Existing code paths in `Sidebar.tsx`. No changes.
- `< lg` — **mobile sidebar.** The `Sidebar` component renders a different tree: the
  new mobile shell with header + main view + (when active) an in-sidebar overlay.

`renderCollapsed` (the desktop rail) stays desktop-only as today.

### In-sidebar stack

A local `useState` in `Sidebar.tsx` tracks which view is showing inside the mobile
sidebar:

```ts
type MobileView = 'main' | 'new-chat' | 'history' | 'bookmarks'
const [mobileView, setMobileView] = useState<MobileView>('main')
```

Stack depth is exactly 2 (`'main'` ↔ one overlay). No history, no push-stack, no store.
When the drawer closes (any reason — `✕`, item selection, route change) we reset
`mobileView` to `'main'`, so the next open lands on the main view.

The `useDrawerStore` is unchanged; only its consumers in `Sidebar.tsx` change.

### Container layout

In the mobile branch the sidebar container becomes:

- `w-screen` (was `w-[85vw] max-w-[320px]`) — true fullscreen, no underlying strip.
- Slide-in / slide-out from the left remains: `-translate-x-full` ↔ `translate-x-0`,
  same duration (`duration-200 ease-out`).
- Backdrop element is removed in the mobile branch — it has nothing to dim behind a
  fullscreen overlay. (Desktop never had a backdrop anyway.)

### New components

All under `frontend/src/app/components/sidebar/`:

- `MobileSidebarHeader.tsx` — the shared 50 px top bar.
  - When `mobileView === 'main'`: shows fox + "Chatsune" as a single clickable area
    that closes the drawer, plus a `✕` button on the right that also closes.
  - When `mobileView !== 'main'`: shows `‹ <Title>` (back-area, returns to main),
    plus the same `✕` button.
- `MobileMainView.tsx` — the content shown when `mobileView === 'main'`.
- `MobileNewChatView.tsx` — the persona-list overlay shown when
  `mobileView === 'new-chat'`. Pinned + Other sections, single-row tap = start chat.

The existing `HistoryTab` and `BookmarksTab` components are reused directly inside the
sidebar for `mobileView === 'history'` and `'bookmarks'`. They receive the same
`onClose` prop they already accept; in the mobile sidebar context this maps to
`setMobileView('main')`.

### Overlay transitions

Inside the sidebar, switching between `main` and any overlay uses a horizontal slide
of ~150 ms `ease-out`:

- Going forward (`main` → overlay): main view slides left out, overlay slides in from
  right.
- Going back (overlay → main): overlay slides right out, main view slides in from left.

Implementation: render both views inside a 200 % wide flex container, translate the
container by `-50 %` when an overlay is active. CSS-only, `transition-transform`. No
animation library.

### Closing behaviour

`✕` in the header always:

1. Resets `mobileView` to `'main'`.
2. Calls `useDrawerStore.getState().close()`.

Likewise the existing close-on-navigate logic (`closeDrawerIfMobile`) stays in place,
plus the same reset of `mobileView` when the drawer closes. No `useEffect` chain — the
existing handlers (`handlePersonaSelect`, `handleSessionClick`, etc.) gain the reset.

---

## Main-View Layout (iPhone SE: 375 × 667)

Vertical structure, top to bottom. Each row is `~36 px` high (touch-comfortable).
Rows ordered exactly as listed:

**Header (50 px)**
- Logo area (fox + "Chatsune") — closes drawer
- `✕` — closes drawer

**Top section (`flex-shrink-0`, attached to top)**
1. **Admin** — gold banner, `isAdmin === true` only
2. divider (only present if Admin shown)
3. **Continue** — `▶️` + "Continue", visible only when `!isInChat && lastSession`
4. **New Chat** — `💬` + "New Chat" + chevron `›` (opens overlay)
5. **Personas** — `💞` + "Personas" (navigates to `/personas`, closes drawer)
6. divider
7. **History** — `📖` + "History" + chevron `›` (opens overlay)
8. **Bookmarks** — `🔖` + "Bookmarks" + chevron `›` (opens overlay)

**Spacer** — `flex-1`, fills remaining space so bottom section is anchored.

**Bottom section (`flex-shrink-0`, attached to bottom, separated by `border-t`)**
1. **Knowledge** — `🎓` + "Knowledge" (opens User-Modal `knowledge` leaf, closes drawer)
2. **My Data** — `📂` + "My Data" (opens User-Modal `my-data` top-tab, last-visited
   sub-tab applies; closes drawer)
3. divider
4. **Sanitised toggle** — `🔒` + "Sanitised", same affordance as today (icon styled by
   active state, gold label when on)
5. divider
6. **User row** — avatar + name + role, single clickable area; opens `about-me` (or
   `api-keys` when `hasApiKeyProblem`); red `!` indicator on avatar when problem.
   No `···` settings shortcut.
7. **Log out** — single-row text link `↪ Log out` beneath the user row.

### Height check (worst case, all rows shown)

```
50  header
36  admin + 7 = 43
36  continue
36  new chat
36  personas
8   divider
36  history
36  bookmarks
─── (top section: ~270 px)
─── flex-1 spacer
36  knowledge
36  my data
8   divider
36  sanitised
8   divider
50  user row
30  logout
─── (bottom section: ~204 px)
─── total fixed ≈ 474 px
```

Available iPhone SE viewport ≈ 553 px (after Safari URL bar). Spacer absorbs
~80 px. Comfortable margin even at maximum density.

### Width

Persona/Bookmark/History rows truncate long labels with `text-overflow: ellipsis`, no
wrap. Verified target widths: monogram 36 px + 12 gap + label area + 8 right padding
fits NSFW pill comfortably.

---

## Header Behaviour

`MobileSidebarHeader` props:

```ts
interface MobileSidebarHeaderProps {
  title?: string         // 'New Chat' | 'History' | 'Bookmarks' — undefined on main
  onBack?: () => void    // when overlay active
  onClose: () => void    // always close-everything
}
```

- On main view (`title` undefined): renders fox + "Chatsune" left-aligned, the whole
  area is one button with `onClick={onClose}`. Right side: `✕` button, also calls
  `onClose`.
- On overlay (`title` set): renders `‹ <title>` left-aligned, the whole area is one
  button with `onClick={onBack}`. Right side: `✕` button, calls `onClose`.

Both interactive areas are `min-h-[44px]` for touch targets. `‹` is rendered at
~18 px so it reads as a back-affordance, not a small chevron.

---

## New-Chat Overlay

Persona list sourced from `personas` (the same prop the sidebar already receives).
Sanitised mode applies — NSFW personas are filtered out when active.

```
[← New Chat]            [✕]
─────────────────────────
PINNED
A   Aria
L   Lyra            [NSFW]
V   Vox
OTHER
M   Marcus the Stoic
N   Nova
S   Sage of the Old Republic…
T   Thorne          [NSFW]
…
```

### Behaviour

- Manual ordering is respected — the same `pinnedPersonas` / `unpinnedPersonas`
  arrays already computed in `Sidebar.tsx` are passed in.
- Section header `PINNED` only rendered if pinned personas exist (after sanitised
  filter).
- Section header `OTHER` only rendered if other personas exist.
- Empty state (no personas at all): `No personas yet` text + a single button "Create
  persona" linking to `/personas`.
- Tap on row → `navigate(/chat/${persona.id}?new=1)`, drawer closes, stack resets.
- Long persona names truncate with ellipsis, single line, monogram never truncates.

### What is **not** present

- No search field.
- No DnD reorder.
- No pin/unpin actions.
- No edit shortcut.
- No incognito variant.

All of those live on the Personas page (and persona overlay), reachable via the
"Personas" row in the main view.

---

## History & Bookmarks Overlays — Reuse with Responsive Tune-up

Both overlays render the existing `HistoryTab` and `BookmarksTab` components from
`frontend/src/app/components/user-modal/`, with their existing `onClose` prop wired
to `setMobileView('main')`.

### Responsive tweaks (apply at `< sm`, i.e. `< 640 px`)

In `HistoryTab.tsx` and `BookmarksTab.tsx`, the filter row currently reads:

```tsx
<div className="px-4 pt-4 pb-2 flex-shrink-0 flex gap-2">
  <input ... />
  <select ... />
</div>
```

It becomes:

```tsx
<div className="px-4 pt-4 pb-2 flex-shrink-0 flex flex-col sm:flex-row gap-2">
  <input ... className="... flex-1 sm:flex-1" />
  <select ... className="... w-full sm:w-auto" />
</div>
```

Effect: at `< 640 px` the persona-filter dropdown sits on its own row beneath search,
each takes full width, both stay touch-friendly. At `>= 640 px` (User-Modal context
on tablet/desktop) layout is identical to today.

Padding inside list rows is left as-is. They already render acceptably in 375 px
testing — the only crowding came from search+filter side-by-side.

**No other functional or visual changes** to these components. Logic — search
debouncing, sanitised filter, persona filter, date grouping, inline edit/delete,
DnD (Bookmarks) — is unchanged. A bug fix anywhere applies to both consumers.

### Item-tap behaviour

Today, `HistoryTab` and `BookmarksTab` already call `onClose()` plus `navigate(...)`
on item selection. In the User-Modal context, `onClose` closes the modal. In the
mobile-sidebar context, `onClose` does `setMobileView('main')` AND closes the drawer
(via the existing `closeDrawerIfMobile`). The mobile sidebar wraps `onClose` to do
both:

```ts
const closeOverlayAndDrawer = () => {
  setMobileView('main')
  useDrawerStore.getState().close()
}
```

Then `<HistoryTab onClose={closeOverlayAndDrawer} />`.

---

## Animation Detail

CSS-only, no library. The two views (`main` and the active overlay) share a flex
container that is `200%` wide; transform-translate `0` for main, `-50%` for overlay:

```tsx
<div
  className="flex w-[200%] h-full transition-transform duration-150 ease-out"
  style={{ transform: mobileView === 'main' ? 'translateX(0)' : 'translateX(-50%)' }}
>
  <div className="w-1/2 flex-shrink-0">
    <MobileMainView ... />
  </div>
  <div className="w-1/2 flex-shrink-0">
    {mobileView === 'new-chat'  && <MobileNewChatView ... />}
    {mobileView === 'history'   && <HistoryTab onClose={closeOverlayAndDrawer} />}
    {mobileView === 'bookmarks' && <BookmarksTab onClose={closeOverlayAndDrawer} />}
  </div>
</div>
```

Why `200 % + translate-50%` rather than two absolutely-positioned panes:

- both panes are real flow children — they get the screen height naturally.
- internal scrolling (e.g. History list when there are many sessions) works without
  extra `position: relative` plumbing.
- back/forward animation is a single `transform` change.

The header is rendered **outside** the sliding container so it only rerenders when
`title` / `onBack` / `onClose` change — not on every animation frame.

---

## Edge Cases

- **No personas:** main view's "Continue" hidden, "New Chat" still visible (taps to
  empty-state in overlay).
- **No sessions:** "Continue" hidden.
- **In-chat (`isInChat` true):** "Continue" hidden — current chat already shows what
  Continue would resolve to, so it'd be redundant.
- **Sanitised mode toggled while in an overlay:** lists react via existing reactive
  hooks; no special handling. The Sanitised toggle is only on the main view, but its
  effect is global.
- **API-key problem:** red `!` shows on the avatar dot (main view, bottom section).
  Tapping the user row routes to `api-keys` instead of `about-me`.
- **Drawer closed mid-overlay:** `mobileView` resets to `'main'` so next open lands
  on main. The drawer itself fully slides out left.
- **Browser-back while drawer open:** unchanged from today — page navigates, `Sidebar`
  unmounts/remounts as the routed component does, internal state is dropped. No
  Browser-Back integration with the in-sidebar stack.
- **Tablet (`md` to `< lg`):** uses the same fullscreen mobile sidebar. No tablet-
  specific layout in this iteration.
- **Landscape mobile:** sidebar still fullscreen. Header height stays 50 px so it
  remains usable; spacer absorbs less, but the bottom section is anchored, so layout
  stays correct.

---

## Components and Files

### New files

- `frontend/src/app/components/sidebar/MobileSidebarHeader.tsx`
- `frontend/src/app/components/sidebar/MobileMainView.tsx`
- `frontend/src/app/components/sidebar/MobileNewChatView.tsx`

### Modified files

- `frontend/src/app/components/sidebar/Sidebar.tsx` — split mobile vs. desktop branch;
  introduce `mobileView` state; render new components in the mobile branch; preserve
  existing desktop branch and `renderCollapsed` behaviour verbatim.
- `frontend/src/app/components/user-modal/HistoryTab.tsx` — filter row becomes
  `flex-col sm:flex-row`; inputs full-width below `sm`.
- `frontend/src/app/components/user-modal/BookmarksTab.tsx` — same change to filter row.

### Unchanged files

- `frontend/src/core/store/drawerStore.ts` — public API and behaviour unchanged.
- `frontend/src/core/store/sidebarStore.ts` — desktop-only collapse state, unchanged.
- All persona/session/history APIs.

---

## Testing

### Unit / component

- `MobileSidebarHeader.test.tsx`
  - Main view: clicking the logo area calls `onClose`. Clicking `✕` calls `onClose`.
  - Overlay: clicking the back-area calls `onBack`. Clicking `✕` calls `onClose`,
    not `onBack`.
- `MobileNewChatView.test.tsx`
  - Renders `PINNED` section only when pinned personas exist.
  - Renders `OTHER` section only when others exist.
  - Sanitised mode hides NSFW personas.
  - NSFW pill renders for NSFW personas (when not sanitised).
  - Tap on a row calls the `onSelect(persona)` prop with the right persona.
  - Empty state renders the "No personas yet" copy and link to `/personas`.
- `Sidebar.test.tsx` (extension of existing)
  - Below `lg`: `mobileView` starts at `'main'`.
  - Tapping "New Chat" row sets `mobileView` to `'new-chat'`.
  - In overlay, tapping back resets to `'main'`. Tapping `✕` calls drawer close.
  - When drawer closes (any reason), `mobileView` is `'main'` on next open.

### Manual verification (real iPhone SE / 375 × 667 emulator)

- [ ] Open the drawer. Main view fits the screen with no scrolling. Bottom row
      (logout) is visible without scrolling.
- [ ] Header logo area closes the drawer.
- [ ] `✕` closes the drawer.
- [ ] "New Chat" row opens overlay with horizontal slide. Overlay shows pinned + other
      sections. NSFW pills render. Long persona name truncates with ellipsis.
- [ ] Tap a persona → drawer closes, navigates to new chat.
- [ ] Re-open drawer — back on main view (state reset).
- [ ] "History" → existing History list inside the sidebar overlay; search + persona-
      filter stack vertically and each is full-width. Tap a session → drawer closes,
      navigates.
- [ ] "Bookmarks" → existing Bookmarks list; same responsive filter layout. Tap a
      bookmark → drawer closes, navigates.
- [ ] "Knowledge" / "My Data" → User-Modal opens correctly (`my-data` opens last-
      visited sub-tab).
- [ ] Sanitised toggle on/off — NSFW personas show/hide in New-Chat overlay; NSFW
      sessions show/hide in History.
- [ ] Continue row visible only when not in chat AND a session exists.
- [ ] Admin banner visible only for admins.
- [ ] Avatar `!` indicator visible when API-key problem; tapping it routes to
      api-keys.
- [ ] Tap user row (no API-key problem) → opens About-me.
- [ ] Logout works.
- [ ] Rotate to landscape — layout stays correct, no overflow.

### Manual verification (Desktop, `>= lg`)

- [ ] Sidebar appearance and behaviour identical to before.
- [ ] Rail collapse works identically.
- [ ] User-Modal History tab and Bookmarks tab look identical (filter row remains
      side-by-side at `>= sm`).

### Manual verification (User-Modal on mobile)

- [ ] Open User-Modal History tab on a 375 px viewport. Search input and persona
      filter stack vertically, both full-width. List renders normally.
- [ ] Same for Bookmarks tab.

---

## Decisions Recap

| Decision                                       | Choice                                            |
|-----------------------------------------------|---------------------------------------------------|
| "My Data" entry destination                    | User-Modal `my-data` top-tab (last-visited sub)   |
| Continue visibility                            | Only when `!isInChat && lastSession`              |
| Header on mobile                               | Logo area + `✕` both close drawer; no `<<`        |
| Settings shortcut on user row                  | Removed (`···` gone). API-key indicator stays.    |
| Overlay model                                  | Stack inside the sidebar (depth 2)                |
| History / Bookmarks reuse                      | Reuse existing tabs + small responsive tweak      |
| New-Chat search field                          | None (encourage tidy persona lists)               |
| New-Chat sections                              | Pinned + Other, manual order, NSFW pill           |
| Animation                                      | Horizontal slide ~150 ms                          |
| Tablet handling                                | Same fullscreen mobile sidebar (single `< lg` tier) |

---

## Migration / Rollout

No data-model change, no migration. Frontend-only.

---

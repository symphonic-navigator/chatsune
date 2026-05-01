# Mobile Viewport Height Fix

## Problem

On Pixel Tablet (Chrome, in browser, not PWA), the mobile sidebar
drawer is cut off at the bottom — the lowest items are hidden under
the browser address bar. The persona list on the personas page shows
the same symptom: the last card is partially clipped.

PWA mode on the same device works fine. Galaxy S20 Ultra in browser
also works (the sidebar contents are short enough that the clipped
zone is empty). The problem is therefore platform-specific: any
Chrome-on-Android browser session where the address bar is visible
and the sidebar/list is long enough to fill the visible area runs
into clipping.

### Root cause

`frontend/src/index.css` sets the body height to `100vh`:

```css
body {
  width: calc(100vw / var(--ui-scale, 1));
  height: calc(100vh / var(--ui-scale, 1));
  transform: scale(var(--ui-scale, 1));
  ...
}
```

`100vh` in mobile browsers refers to the viewport height **without**
the address bar — i.e. the *largest* possible visible area, which
only exists once the user has scrolled and the address bar has
collapsed. While the address bar is visible, the actually-visible
viewport is smaller than `100vh`. Body is therefore taller than
the visible area, and anything anchored to the body's bottom
(sidebar, persona-grid, etc.) ends up behind the address bar.

PWA has no address bar, so `100vh` is correct in that mode.

The same root cause affects every other use of `100vh` in the
codebase:

- Login, Register, ChangePassword, DeletionComplete pages —
  `min-h-screen` (Tailwind alias for `min-height: 100vh`).
- `Sheet.tsx` — `lg:max-h-[calc(100vh-2rem)]` for the desktop sheet
  panel (less critical but still affected by the same semantics on
  mobile-on-desktop windows; consistent fix).

## Goal

The body and any other layout-anchoring viewport height correctly
reflects the **currently visible** viewport on Chrome-on-Android,
regardless of whether the address bar is shown or hidden. PWA
behaviour stays unchanged.

## Design

Replace every occurrence of `100vh` (and the Tailwind alias
`min-h-screen` / `h-screen`) with the dynamic equivalent:

| Old | New |
|---|---|
| `100vh` (in CSS) | `100dvh` |
| `min-h-screen` (Tailwind) | `min-h-dvh` |
| `h-screen` (Tailwind) | `h-dvh` |
| `calc(100vh - X)` | `calc(100dvh - X)` |

`dvh` is the **dynamic viewport height** — it always reflects the
currently-visible viewport. When the address bar is visible, `100dvh`
equals the smaller height; when it collapses, `100dvh` grows live.

### Why `dvh` and not `svh`

- `svh` (small viewport height) is permanently the smallest possible
  height (always counts the address bar as present). Layout would
  never use the extra space when the address bar collapses, leaving
  a visible empty strip at the bottom in browser mode. Bad UX for an
  always-on conversation app.
- `dvh` matches the visible viewport at all times. The cost is a
  potential layout shift when the address bar slides in/out — but in
  this app, body has `overflow: hidden` and all content scrolling
  happens inside child containers (`<main>`, `MessageList`), so the
  page-level scroll that triggers address-bar collapse barely
  applies. Layout shift in practice will be minimal or non-existent.
- `lvh` (large viewport height) equals the legacy `vh` semantics —
  doesn't help.

### Browser support

`dvh` is supported by Chrome 108+ (Dec 2022), Safari 15.4+ (Mar
2022), Firefox 101+ (May 2022). All target browsers (the user's
testers are on modern Chrome, Safari, and PWA wrappers around them)
are well clear of these versions.

### Tailwind v4 utilities

The project uses Tailwind v4 (`tailwindcss@^4.2.2`). Tailwind v4
ships `h-dvh`, `min-h-dvh`, `max-h-dvh` as built-in utilities. No
config changes needed.

For arbitrary-value cases (e.g. `lg:max-h-[calc(100vh-2rem)]`), the
arbitrary value is updated to use `dvh`:
`lg:max-h-[calc(100dvh-2rem)]`.

### Files affected

- `frontend/src/index.css`:
  - Body `height: calc(100vh / ...)` → `height: calc(100dvh / ...)`
- `frontend/src/app/pages/LoginPage.tsx` (4 occurrences):
  - `min-h-screen` → `min-h-dvh`
- `frontend/src/app/pages/RegisterPage.tsx` (1 occurrence):
  - `min-h-screen` → `min-h-dvh`
- `frontend/src/app/pages/ChangePasswordPage.tsx` (1 occurrence):
  - `min-h-screen` → `min-h-dvh`
- `frontend/src/app/pages/DeletionCompletePage.tsx` (1 occurrence):
  - `min-h-screen` → `min-h-dvh`
- `frontend/src/core/components/Sheet.tsx`:
  - `lg:max-h-[calc(100vh-2rem)]` → `lg:max-h-[calc(100dvh-2rem)]`

No backend changes. No new files. No store-shape or component-API
changes.

### Out of scope

- `100vw` → `100dvw` translation. Horizontal viewport doesn't
  change with address-bar visibility, so the behaviour is the same.
  Keep the existing `100vw` references in `index.css` and elsewhere.
- Conditional logic to use `100vh` in PWA mode and `100dvh` in
  browser. `100dvh` works equally well in PWA (no address bar to
  hide) — there's no upside to branching.
- A JavaScript fallback (`--vh` custom property pattern) for old
  browsers. Browser support is comfortable; YAGNI.
- The Cockpit sizing variables and other pixel-specific layout
  numbers that don't depend on viewport height.

## Manual verification

The product owner runs these on the deployed environment:

### Pixel Tablet, Chrome, browser mode (the original bug)

1. Open Chatsune in Chrome on the Pixel Tablet.
2. Wait until the page is fully loaded; address bar is visible.
3. Open the sidebar drawer (hamburger).
4. **Expected:** all sidebar items including the bottom-most are
   fully visible above the address bar. No clipping.
5. Navigate to the personas page. Scroll to the bottom of the
   list (or look at the last card without scrolling if it fits).
6. **Expected:** the last persona card is fully visible, not
   partially clipped.
7. Scroll up/down a bit so the address bar collapses, then scroll
   the opposite direction so it reappears.
8. **Expected:** the layout adjusts smoothly. No content trapped
   behind the address bar in either state.

### PWA mode (regression check)

9. Open Chatsune as PWA on any device.
10. **Expected:** layout looks identical to before — no extra
    space at the bottom, no clipping.

### Login flow (regression check)

11. Logout, land on the login page on the Pixel Tablet in browser
    mode.
12. **Expected:** the login form is centred vertically in the
    visible area, not pushed below the address bar.

### Galaxy S20 Ultra (regression check)

13. Open Chatsune in Chrome on the S20 Ultra.
14. **Expected:** behaviour is identical to before — sidebar fits,
    no new visual artefacts.

If any scenario fails, do NOT proceed; report which step and what
was observed.

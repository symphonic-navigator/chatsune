# Spectrum HitStrip — Scope to Main Content Area

## Problem

`VoiceVisualiserHitStrip` is the invisible click-catcher that toggles voice
pause when the user clicks the spectrum analyser. It is currently rendered
as a global-layer sibling in `AppLayout` with `position: fixed; left: 0;
width: 100%; top: 35%; height: 30%; zIndex: 2`.

Because it spans the full viewport width, it captures clicks over the
sidebar on desktop (where the sidebar is `lg:static; w-[232px]`, no
stacking context). The sidebar therefore becomes unusable during live
voice mode — every click on a sidebar item is intercepted by the
HitStrip and pauses voice instead.

The visual spectrum bars are not affected: the canvas is also full-viewport
fixed, but the renderer (`visualiserRenderers.ts`) clips bar drawing to the
measured `chatview` / `textColumn` bounds. Only the click overlay is wrong.

## Goal

Clicks on the sidebar (desktop) and on the mobile drawer or its backdrop
must never trigger voice pause. The HitStrip should only receive clicks
in the area where the spectrum is visually shown — the main content area.

## Approach: Move HitStrip into `<main>`

Relocate `VoiceVisualiserHitStrip` from `AppLayout` (global-layer sibling
of Sidebar/Topbar/main) into `<main>` as a child. Switch its CSS from
`position: fixed` to `position: absolute`. `<main>` already has
`position: relative`, so absolute positioning is anchored to the main
content box.

Canvas (`VoiceVisualiser`) and countdown pie (`VoiceCountdownPie`) stay
where they are — their renderer logic already clips correctly to
chatview bounds, and refactoring them would touch `useReportBounds`,
the layout store, and the renderer geometry without any user-visible
benefit. YAGNI.

### Why this fixes both desktop and mobile

- **Desktop:** sidebar is `lg:static` and lives outside `<main>`. The
  HitStrip, now anchored to `<main>`, only spans the content area. No
  overlap.
- **Mobile (drawer closed):** sidebar is off-screen. HitStrip in `<main>`
  spans the full main width — same as today. No regression.
- **Mobile (drawer open):** drawer is `position: fixed; z-40` and its
  backdrop is `z-30`, both stacked above `<main>`. The HitStrip
  (`zIndex: 2` inside `<main>`) is visually and pointer-wise below them
  — clicks on drawer or backdrop go to those elements, not the
  HitStrip. No state tracking needed.
- **Future sidebar width changes:** the HitStrip follows `<main>`
  automatically; no constants to chase.

### Y-position semantics

Currently `top: 35%; height: 30%` is relative to the viewport.
After the move, the same percentages are relative to `<main>` (viewport
minus topbar). The clickable band moves down by roughly the topbar
height. This is closer to where the spectrum bars are actually drawn
(also inside the main content box), so the change is a slight
improvement, not a regression.

## Files affected

- `frontend/src/features/voice/components/VoiceVisualiserHitStrip.tsx`
  — change `position: 'fixed'` to `position: 'absolute'`. No other style
  changes.
- `frontend/src/app/layouts/AppLayout.tsx`
  — remove `<VoiceVisualiserHitStrip />` from the global-layer siblings
  (currently around line 353) and render it as the last child inside
  `<main>` (after `<Outlet />` and any modals that already live there).

No changes to the canvas, the countdown pie, the renderer, the layout
store, or the report-bounds hook.

## Manual verification

Run `pnpm run build` first to confirm clean compilation. Then on a
real deployment (or local dev server) in Chrome:

### Desktop (lg+ viewport)

1. Start a voice session so the spectrum is active.
2. Click on a sidebar item (e.g. a chat session in the list).
   - **Expected:** sidebar action runs, voice does NOT pause.
3. Click on the spectrum area in the centre of the screen.
   - **Expected:** voice pauses.
4. Click again on the spectrum area.
   - **Expected:** voice resumes.

### Mobile (drawer closed)

1. Start a voice session.
2. Click in the centre content area where the spectrum is visible.
   - **Expected:** voice pauses.
3. Click again to resume.
   - **Expected:** voice resumes.

### Mobile (drawer open)

1. Start a voice session.
2. Open the sidebar drawer (hamburger).
3. Click on a sidebar item inside the drawer.
   - **Expected:** sidebar action runs, voice does NOT pause.
4. Click on the dark backdrop area to the right of the drawer.
   - **Expected:** drawer closes, voice does NOT pause.

### Regression check

5. With drawer closed and voice paused, click on the spectrum area again
   to confirm the resume path still works.
6. Check that the spectrum bars themselves still render in the main
   content column (no visual change vs. before).

## Out of scope

- Refactoring canvas / countdown pie into the same container (B-Voll).
- Adding a CSS variable for sidebar width.
- Any state tracking of drawer-open state (handled by z-index layering
  alone).

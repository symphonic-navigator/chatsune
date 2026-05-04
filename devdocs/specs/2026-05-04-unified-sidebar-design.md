# Unified Sidebar — Desktop and Mobile Button Order

**Date:** 2026-05-04
**Status:** Design approved, ready for implementation plan
**Scope:** Frontend only (`frontend/src/app/components/sidebar/`)

---

## Goal

Align the navigation buttons of the desktop sidebar and the mobile drawer
sidebar so that they appear in the **same order in both views**, while
preserving:

- The desktop accordion-zone redesign from 2026-05-03 (Personas / History
  zones with inline lists, dynamic item-limit, accordion behaviour).
- The mobile principle: **no inline lists in the sidebar** — entity
  navigation entries open as overlays (in-drawer slide-in for History /
  Bookmarks, route navigation for Personas).

The desktop layout wins as the master order — testers explicitly praised
it after the 2026-05-03 redesign.

---

## Canonical button order

The order below applies to both views. Desktop shows Personas / History as
accordion zones with inline lists; mobile shows them as overlay-opening
buttons. Everything else is a button or a small group in identical order.

```
[Admin banner] (conditional, both views)
─────────────────────────────────
New Chat
New Incognito Chat        ← Desktop: own row
                              Mobile: transient toggle in picker
Continue                   (conditional)
─────────────────────────────────
Personas                  ← Desktop: accordion zone with list
                              Mobile: button → /personas route
History                   ← Desktop: accordion zone with list
                              Mobile: button → in-drawer overlay
─────────────────────────────────
[flex spacer]
─────────────────────────────────
Knowledge
Bookmarks                  ← moved down from mobile-mid to footer
My data
─────────────────────────────────
Sanitised toggle
User row + ··· Settings    ← Settings button added on mobile
Log out
```

---

## Changes per file

### `MobileMainView.tsx`

- Remove `Bookmarks` from the top group (it currently sits between History
  and the spacer).
- Insert `Bookmarks` into the bottom group between `Knowledge` and
  `My Data`. Resulting bottom group: Knowledge → Bookmarks → My Data.
- Add a `···` Settings button alongside the user row (right-hand side, same
  layout as desktop `FooterBlock`). New prop `onOpenSettings: () => void`.
- The user row continues to open `avatarTab` (about-me, or api-keys when a
  problem is flagged). The new `···` button opens `'settings'` directly.

### `MobileNewChatView.tsx`

- Add a transient **Incognito** toggle button to the picker chrome. Visible
  on every open of the picker. Toggle state is local component state, **not
  persisted** — every fresh open of the picker resets it to `off`.
- When the toggle is `on` and the user picks a persona, the picker calls
  `onSelect(persona, { incognito: true })`; when `off`, the existing
  `onSelect(persona)` path is used.
- The toggle should read as "Incognito" / "Incognito mode on" with a clear
  visual on/off state. Treatment matches existing pill-style toggles in the
  app (subtle background/foreground swap, no shouty colour).

### `Sidebar.tsx`

- `handleNewChatFromMobileOverlay` gains an `incognito?: boolean` parameter.
  When `incognito === true`, navigate to `/chat/${persona.id}?incognito=1`;
  otherwise keep the existing `/chat/${persona.id}?new=1`.
- Wire the mobile branch to pass an `onOpenSettings` callback to
  `MobileMainView` (mirrors desktop `FooterBlock`'s settings entry point).

### Tests

- `MobileMainView.test.tsx` — update assertions so Bookmarks is found in
  the bottom group, not the top group. Add an assertion for the `···`
  Settings button and its click handler.
- `MobileNewChatView.test.tsx` — assert the Incognito toggle exists, defaults
  to `off`, and that selecting a persona while it is `on` produces an
  incognito navigation. Assert that closing and reopening the picker resets
  the toggle to `off` (transient behaviour).

---

## Non-goals

- **No changes to the desktop sidebar.** Yesterday's redesign stays exactly
  as it is. Desktop is the reference.
- **No changes to the inline-list principle on mobile.** Personas / History
  remain as overlay-opening buttons; this spec does not add inline lists to
  the mobile drawer.
- **No changes to the underlying overlay containers.** Mobile keeps its
  in-drawer 200%-flex slide animation; desktop keeps its modals. The
  mechanism per side stays as it is — only the order of the entry points is
  unified.
- **No changes to the Persona-picker shape.** The picker stays the same
  except for the new transient Incognito toggle.

---

## Risk and verification

### Risks

- **Tap target on small phones**: the `···` Settings button next to the
  user row is harder to hit on iPhone SE-class devices. Accepted trade-off
  for consistency; the user row itself remains the primary tap target and
  stays large.
- **Transient toggle expectation**: users who expect "Incognito" to stick
  across opens will find it surprising. Decision is deliberate — incognito
  should be an explicit per-chat opt-in, never a persistent mode that can
  be left on accidentally.

### Manual verification steps

Run on real devices, not just devtools, since drawer / picker animations
are touch-driven:

1. **Mobile — order check**: Open the drawer on a phone-sized viewport.
   Verify the visible order from top to bottom matches the canonical order
   above. Bookmarks must appear above My Data, **not** between History and
   the spacer.
2. **Mobile — Bookmarks tap**: Tap Bookmarks in the new footer position.
   The Bookmarks overlay must slide in within the drawer (same behaviour
   as before, just from a different button position).
3. **Mobile — Incognito picker, transient**: Tap `New Chat`, toggle
   Incognito on, pick any persona — verify URL ends with `?incognito=1`.
   Then close the picker (back / drawer close), reopen `New Chat`, observe
   the Incognito toggle is **off** again.
4. **Mobile — Incognito picker, off path**: Tap `New Chat`, leave Incognito
   off, pick a persona — verify URL ends with `?new=1` (existing behaviour
   preserved).
5. **Mobile — Settings ···**: Tap the `···` button next to the user row.
   The Settings modal must open (not About-Me).
6. **Mobile — User row still works**: Tap the user-row text/avatar (not the
   `···`). About-Me opens. If `hasApiKeyProblem` is true, the API-keys
   leaf opens instead — same as today.
7. **Desktop — no regression**: Open the desktop sidebar, verify the order
   is unchanged from the 2026-05-03 redesign. The Personas / History
   accordion zones still expand and collapse as before. Bookmarks is still
   in the footer between Knowledge and My Data.
8. **Cross-device parity check**: Open the sidebar on desktop and on a
   phone side-by-side; the entry points must read in the same order on
   both screens.

---

## Out of scope follow-ups (not part of this spec)

- Aligning the underlying overlay mechanism (mobile in-drawer slide vs
  desktop modal) — the user has explicitly said the current per-side
  containers stay.
- Hiding `New Incognito Chat` entirely on Mobile — also explicitly rejected;
  the transient picker toggle is the chosen mechanism.
- Any animation polish on the Incognito toggle. Treat it as a stock pill
  toggle for now; aesthetic refinement is a separate concern.

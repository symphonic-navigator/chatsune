# Browser Back Closes Overlays — Design

**Date:** 2026-05-03
**Status:** Spec, awaiting implementation plan
**Owner:** Chris

---

## Problem

Beta testers report — repeatedly and loudly — that pressing the browser
back button does not behave as they expect. They expect "back" to mean
**"go back in app state"**: close the currently open overlay, drawer, or
lightbox. Today, every overlay is purely component-local state with no
history integration, so back navigates away from the route (or leaves the
app), often discarding context the tester wanted to keep visible.

Image lightboxes in chat were called out specifically — testers tap an
image, hit back to dismiss it, and lose their entire chat route instead.

## Goal

When an overlay-class UI element is open, browser back closes it without
changing the underlying route. When nothing is open, browser back behaves
as before (route navigation, leave app).

## Non-Goals

- Refresh-preserving overlays (would require URL state — not asked for, gold-plating)
- Deep-linkable overlays (`?modal=user-settings` URLs) — same reason
- Restoring overlay state via forward button (rare interaction, no clean UX
  without URL state)
- Confirm-dialog behaviour — those keep current Escape-only behaviour
- Form-sheet dialogs nested inside other overlays (deferred to a later iteration)

---

## Scope

### In scope — browser back closes these

| # | Overlay | File | Today's open-state source |
|---|---|---|---|
| 1 | UserModal | `app/components/user-modal/UserModal.tsx` | `AppLayout.modalOpen` (useState) |
| 2 | AdminModal | `app/components/admin-modal/AdminModal.tsx` | `AppLayout.adminTab` (useState) |
| 3 | PersonaOverlay | `app/components/persona-overlay/PersonaOverlay.tsx` | `AppLayout.personaOverlay` (useState) |
| 4 | ArtefactOverlay | `features/artefact/ArtefactOverlay.tsx` | `useArtefactStore.activeArtefact` |
| 5 | ImageLightbox (chat) | `features/images/chat/ImageLightbox.tsx` | Parent useState |
| 6 | GalleryLightbox | `features/images/gallery/GalleryLightbox.tsx` | Parent useState |
| 7 | Mobile Drawer | `app/components/overlay-mobile-nav/OverlayMobileNav.tsx` | `useDrawerStore.drawerOpen` |

### Out of scope — Escape-only, no history integration

- `BookmarkModal` (small chat-side form)
- `ExportPersonaModal`, `PersonaCloneDialog` (form sheets inside PersonaOverlay)
- `GatewayEditDialog`, `InvitationLinkDialog` (form dialogs inside Admin / Persona)
- Generic "are you sure?" confirms

Rationale: form-style sub-dialogs would lose half-entered input on a back
press, which is more startling than helpful. If testers later push back on
this, we add them in a follow-up iteration; the architecture supports it
without refactor.

---

## Architecture

Three building blocks, all lightweight:

```
┌───────────────────────────────┐
│ historyStackStore (Zustand)   │  Authoritative truth for what overlays
│   stack: OverlayEntry[]       │  are currently open, in stack order.
│   push(id, onClose)           │
│   popTop()                    │
│   clear()                     │
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│ useBackButtonClose(           │  Per-overlay hook. One line of integration
│   open, onClose, overlayId)   │  per overlay. Synchronises component
│                               │  open-state with browser history.
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│ <BackButtonProvider/>         │  Single global popstate listener mounted
│   popstate → invoke onClose   │  in AppLayout. Calls onClose() of the
│   of top stack entry          │  topmost stack entry, then pops.
└───────────────────────────────┘
```

### Phantom history entries

When an overlay opens, the hook calls
`window.history.pushState({ __overlayId: <id> }, '')` — same URL, only the
state object is meaningful. React Router does nothing on this push (URL
unchanged). On popstate, React Router still does nothing (URL unchanged).
Our `BackButtonProvider` filters by the `__overlayId` marker and acts only
when it matches a known stack entry.

### Stack semantics

Overlays stack in mount-order. Multiple overlays can be open at once
(e.g. PersonaOverlay → ArtefactOverlay → Lightbox). Each pushes its own
phantom entry. Each browser-back pops one, top to bottom.

### Authoritative truth

The `historyStackStore` is the source of truth, browser history is a
marker. If they fall out of sync (logout, edge cases, bugs), the store is
cleared and recovers gracefully — overlays close, no zombie entries.

---

## Hook contract

```ts
useBackButtonClose(open: boolean, onClose: () => void, overlayId: string): void
```

Behaviour:

- `open` transitions `false → true`:
  - Push `{ __overlayId: overlayId }` via `history.pushState`
  - Register `{ overlayId, onClose }` on top of the store stack
- `open` transitions `true → false` (programmatic close — X, backdrop, escape, route change):
  - If `history.state?.__overlayId === overlayId`:
    1. Remove our entry from the store (`store.popTop()`)
    2. Call `history.back()` to pop the phantom entry from browser history
  - The order matters: by the time popstate fires, our store entry is
    already gone, which is how the global handler distinguishes a
    self-triggered close from a user-triggered back (see "Popstate handler"
    below).
  - If `history.state?.__overlayId !== overlayId` (popstate already fired
    and removed our entry), do nothing.
- Component unmount: same as programmatic close.
- The hook ignores changes to `overlayId` while `open` stays `true` — only
  `open` transitions trigger pushes / pops. This means a Lightbox showing
  a sequence of images (next-button) keeps the same single phantom entry
  even as `imageRef` changes. Use stable IDs.
- `overlayId` is a stable string per overlay type. We never need
  per-instance IDs because only one overlay of each type can be open at a
  time. IDs:
  - `'user-modal'`, `'admin-modal'`, `'persona-overlay'`, `'artefact-overlay'`,
    `'mobile-drawer'`, `'lightbox-chat'`, `'lightbox-gallery'`

### Integration cost per overlay

```tsx
function UserModal({ open, onClose }: Props) {
  useBackButtonClose(open, onClose, 'user-modal')
  // ...rest unchanged
}
```

One line. Existing Escape handlers stay — Escape calls `onClose()`, the
hook then takes care of the history side.

### Global setup (once, in `AppLayout`)

```tsx
<BackButtonProvider>
  <Routes>...</Routes>
</BackButtonProvider>
```

`BackButtonProvider` mounts the single `popstate` listener and a
`useAuthStore` subscription that clears the store on logout.

### Popstate handler logic

```
on popstate(event):
  topEntry = store.peek()
  newStateId = event.state?.__overlayId

  if topEntry && topEntry.overlayId !== newStateId:
    # Browser left an overlay that is still in our store →
    # user-initiated back. Pop the store and close the overlay.
    store.popTop()
    topEntry.onClose()
  elif !topEntry && newStateId:
    # Browser is forward-navigating into an entry whose store side
    # was already cleaned up → orphan. Skip past it.
    history.forward()
  else:
    # Either both empty (normal route navigation) or store top
    # matches new state (we self-triggered the back via the hook).
    # Nothing to do.
    pass
```

This makes the self-triggered case a no-op: by the time popstate fires,
the hook has already removed the store entry, so `topEntry` no longer
points at the closing overlay. The handler sees store top match new state
and does nothing.

---

## Edge cases & semantics

| # | Scenario | Behaviour |
|---|---|---|
| 1 | Route change while overlay open (sidebar click) | Host sets overlay state to `false` first → hook calls `history.back()` to clean phantom → React Router then runs `navigate(...)`. Existing route-change effects already close overlays in `AppLayout`. |
| 2 | Stacked overlays | Each pushes its own entry; backs unwind top to bottom (see datafluss example below). |
| 3 | Programmatic close (X / backdrop / Escape) | `onClose()` runs → hook detects `open: true→false` → calls `history.back()` to pop phantom. |
| 4 | Page reload | Phantom entries are gone, store starts empty, overlays start closed (current behaviour). No issue. |
| 5 | Modal opens modal (drawer opens UserModal) | Drawer closes itself before opening modal (today's behaviour) → hook fires `history.back()` for drawer → immediately `pushState` for modal. Net: one phantom entry on the stack. |
| 6 | Browser back with no overlays open | Stack empty → our handler ignores → React Router does normal back navigation. |
| 7 | Auth logout while overlay open | `AuthGuard` redirects with `<Navigate to="/login" replace />`. `BackButtonProvider`'s `useAuthStore` subscription clears the store explicitly to avoid stale entries. |
| 8 | Two lightboxes in sequence (next-image button inside Lightbox) | The component stays mounted with `open=true` — only `imageRef` changes. We do **not** push a new entry per image. Back closes the lightbox entirely. |
| 9 | Forward button after a back-close | We do not re-open. Forward popstate sees an `__overlayId` whose store entry is gone → handler calls `history.forward()` once to skip past the orphaned phantom. (Forward is rare; this keeps semantics consistent.) |
| 10 | Existing `replaceState` in `ChatView.tsx:446` | Only runs on route mount, before any overlay opens — safe. No interaction. |
| 11 | Nested form-sheet inside in-scope overlay (e.g. ExportPersonaModal in PersonaOverlay) | Form-sheet has no phantom entry → browser back closes the **whole** PersonaOverlay including the open form. Half-entered form data is lost. Accepted for v1; revisit in a follow-up iteration if testers complain. |

### Stack data flow (Persona → Artefact → Lightbox example)

```
1. User opens PersonaOverlay
   pushState({__overlayId: 'persona-overlay'})    Stack: [persona]
2. User clicks artefact pill
   pushState({__overlayId: 'artefact-overlay'})   Stack: [persona, artefact]
3. User opens lightbox inside artefact
   pushState({__overlayId: 'lightbox-7'})         Stack: [persona, artefact, lightbox-7]
4. Browser back
   popstate → top = lightbox-7 → onClose()        Stack: [persona, artefact]
5. Browser back
   popstate → top = artefact → onClose()          Stack: [persona]
6. Browser back
   popstate → top = persona → onClose()           Stack: []
7. Browser back
   popstate → stack empty → React Router         (route navigation / leave app)
```

---

## Implementation plan

### New files

| File | Purpose |
|---|---|
| `frontend/src/core/store/historyStackStore.ts` | Zustand store: `stack`, `push`, `popTop`, `clear`. ~40 lines. |
| `frontend/src/core/hooks/useBackButtonClose.ts` | The hook described above. ~50 lines. |
| `frontend/src/core/back-button/BackButtonProvider.tsx` | Global popstate listener; clears store on logout. ~30 lines. |

### Modified files (one hook call each, no logic changes)

| File | Change |
|---|---|
| `frontend/src/app/AppLayout.tsx` | Wrap children in `<BackButtonProvider>`; call hook for UserModal / AdminModal / PersonaOverlay (state lives here). |
| `frontend/src/features/artefact/ArtefactOverlay.tsx` | Hook call with id `'artefact-overlay'`. |
| `frontend/src/features/images/chat/ImageLightbox.tsx` | Hook call with id `'lightbox-chat'`. |
| `frontend/src/features/images/gallery/GalleryLightbox.tsx` | Hook call with id `'lightbox-gallery'`. |
| `frontend/src/app/components/overlay-mobile-nav/OverlayMobileNav.tsx` | Hook call with id `'mobile-drawer'`, reading `useDrawerStore.drawerOpen`. |

### Build order (smallest blast radius first)

1. Write store + hook + provider with Vitest specs (TDD).
2. Mount `BackButtonProvider` in `AppLayout`. No overlays wired yet — must
   be a no-op in this state. Run `pnpm run build`.
3. Wire overlays one at a time, in this order, manually verifying each:
   1. Mobile drawer
   2. ImageLightbox (chat)
   3. GalleryLightbox
   4. ArtefactOverlay
   5. UserModal
   6. AdminModal
   7. PersonaOverlay
4. After each wiring: `pnpm run build` and run the relevant manual test
   from the list below.

Reasoning for order: smallest, most isolated overlays first, so any
stacking or popstate-coordination bug is caught against a single overlay
before adding the next layer of complexity.

---

## Testing

### Vitest (unit)

- `historyStackStore`:
  - `push` adds to top
  - `popTop` removes top entry and returns it
  - `clear` empties stack
  - duplicate push of same `overlayId` replaces, does not duplicate
- `useBackButtonClose`:
  - calls `pushState` once on `open: false → true`
  - calls `store.popTop()` then `history.back()` on programmatic `open: true → false`
  - does **not** call `history.back()` if `history.state?.__overlayId !== overlayId`
    (popstate already removed the entry)
  - cleanup on unmount behaves as programmatic close
  - changes to `overlayId` while `open=true` do not trigger any history action

### Manual verification (real device — Android Chrome, primary tester platform)

1. Open mobile drawer → browser back → drawer closes, route unchanged.
2. Open UserModal → browser back → closes.
3. Open PersonaOverlay → switch internal tab → browser back → closes the
   whole overlay (tabs are not their own layer).
4. ChatView → tap chat image → ImageLightbox opens → back → lightbox
   closes, chat visible.
5. Stack: PersonaOverlay → click artefact → ArtefactOverlay → if a
   lightbox can be opened from artefact context, open it → 3× back unwinds
   in order from top to bottom.
6. Route change with overlay open: UserModal open → click sidebar to
   `/chat/...` → modal closes, route changes, no leftover phantom (verify
   by hitting back once and confirming you go to the previous route, not
   reopen the modal).
7. Press forward after a back-close → overlay does **not** re-open.
8. Close app tab and reopen → no overlays open, clean state.
9. Logout while overlay open → login page renders cleanly, no zombie
   entries (verify by logging in again and pressing back — should not
   reopen anything).

### Desktop cross-check

Run the same nine-step list on Chrome Desktop and Firefox Desktop. Popstate
behaviour is normally consistent across browsers, but we verify because
this is a low-level integration.

---

## Out of scope / future iterations

- Form-sheet dialogs (BookmarkModal, ExportPersonaModal, etc.) — keep
  Escape-only for v1.
- Unsaved-changes confirmation when back closes an overlay with dirty form
  state.
- URL-state for overlays (deep links, refresh preservation).
- Forward-button restoration of closed overlays.

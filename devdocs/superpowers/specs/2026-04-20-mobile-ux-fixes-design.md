# Mobile UX Fixes — Design

**Date:** 2026-04-20
**Status:** Approved, ready for implementation planning
**Scope:** Frontend only

## Motivation

Three mobile UX problems surface on a Galaxy S20 Ultra running Vivaldi (both
plain browser and the installed PWA). Each is individually small but
together they make the app hard to use on the primary mobile target:

1. **Toasts are unreadable and block the UI.** The current toast component
   sits at `top-14` with a semi-transparent glass background. On mobile,
   the translucency makes the text hard to read against busy content, and
   stacked toasts (up to three) can cover controls the user needs.
2. **Chat page scrolls as a whole.** Hitting Enter in the input scrolls the
   entire window, so the input itself disappears below the fold and the
   user must manually scroll up to type again. Typing a multi-line input
   pushes the text behind the soft keyboard.
3. **No escape hatch in the PWA.** An installed PWA has no URL bar and no
   browser refresh button. When something gets wedged, the user has no
   way to force-reload without closing the app.

## Approach summary

- **Mobile toasts:** render a separate `MobileToast` renderer under
  `< lg`; solid background, bottom-anchored, single slot, swipe/tap
  dismiss. Desktop experience is left untouched.
- **Chat viewport lock:** switch the Chat route to an `h-[100dvh]
  overflow-hidden` container, with the message list as the only internal
  scroll region; drop the `sticky bottom-0` on `ChatInput`. Extend the
  viewport meta tag with `interactive-widget=resizes-content`.
- **PWA reload:** add a `useIsPwa()` hook; place an explicit "App neu
  laden" button in the User modal (PWA-only). Replace the current
  update-available toast with automatic reload, deferred while the user
  is in Conversational Mode or an LLM stream is in flight.

---

## Fix 1 — Mobile toast renderer

### Current state

- `frontend/src/app/components/toast/ToastContainer.tsx` positions toasts
  at `top-14 left-1/2 -translate-x-1/2 z-[60]` with glass styling, max 3
  visible, older ones auto-dismissed.
- `frontend/src/app/components/toast/Toast.tsx` renders the individual
  card with the glass surface.
- Notifications are stored in `useNotificationStore` (`store/notificationStore.ts`).

### Design

Introduce a `MobileToastContainer` that renders only when
`useViewport().isMobile` is true (the existing viewport hook already
exposes `isMobile` as "under `lg`"), and suppresses the desktop
`ToastContainer` on the same viewport. The desktop renderer stays exactly
as it is today.

- **Single slot.** `MobileToastContainer` shows the most recent
  notification from the store and nothing else. New notifications replace
  the current one with a short crossfade. Older notifications that were
  pushed out are *not* queued — they are dropped. The notification store
  already discards beyond its own cap; the mobile renderer simply reads
  the top of the list.
- **Position.** `fixed` at the bottom, centred, with
  `bottom: calc(env(safe-area-inset-bottom) + 1rem)`. This sits above
  system gesture bars on Android and above the home indicator on iOS
  (the latter is not a current target but costs nothing to handle).
- **Surface.** Solid background matching the Sheet/Modal surface
  (`bg-surface-900` or the existing token used by `Sheet`), rounded,
  with a 1px subtle border. No backdrop blur. Level-based accent
  (success = green border, error = red, info/warning = current defaults).
- **Dismissal.** Tap anywhere on the toast, or swipe it downward past a
  threshold (e.g. 40px). Auto-dismiss timings are the same as today
  (read from the store entry, as currently).
- **Z-index.** Same layer as the desktop toast (`z-[60]`), so it stays
  above Sheets and modals.

### Why not stacking?

Stacking on mobile is the root cause of the "blocks the UI" complaint.
With only ~360px of usable width and limited vertical space, three
stacked toasts can consume most of the above-the-fold area. The trade-off
— losing access to a short history of recent toasts — is acceptable
because:

- The vast majority of Chatsune toasts are ephemeral ("Link kopiert",
  "Memory aktualisiert", "Chat gelöscht") — there is no information in
  them that the user needs to revisit.
- Errors that *must* be seen are already surfaced inline in the affected
  UI area where relevant (e.g. the chat error banner).

### Files touched

- **New:** `frontend/src/app/components/toast/MobileToastContainer.tsx`
- **New:** `frontend/src/app/components/toast/MobileToast.tsx`
- **Modified:** `frontend/src/app/layouts/AppLayout.tsx` — render
  `MobileToastContainer` instead of `ToastContainer` when
  `isMobile` is true. Simplest form: render both, have each gate itself
  on viewport.
- **Modified:** `frontend/src/app/components/toast/ToastContainer.tsx` —
  add an `if (isMobile) return null` guard so the desktop container
  never competes with the mobile renderer.

No changes to `useNotificationStore` or any caller of `addNotification`.

---

## Fix 2 — Chat viewport lock

### Current state

- `frontend/src/features/chat/ChatView.tsx:1046` uses `<div className="flex h-full flex-col">`.
- `ChatInput` uses `sticky bottom-0 z-10` with `pb-[calc(env(safe-area-inset-bottom)+0.75rem)]`.
- The app uses `100vh` / `h-full` throughout; there is no `dvh` usage and
  no `visualViewport` handling.
- `frontend/index.html` viewport meta is
  `width=device-width, initial-scale=1, viewport-fit=cover`.

### Symptom chain

On Android Chromium (Vivaldi) after pressing Enter to send a message:

1. A new message is appended to the list.
2. The scroll-to-bottom logic calls `scrollIntoView` / assigns
   `scrollTop`.
3. Because the actual scroll container is the window (the chat flex
   column is inside an `h-full` layer that itself can overflow), the
   scroll action scrolls the *window*, not an inner container.
4. `ChatInput`'s `sticky bottom-0` is relative to its own scroll
   container — which is the window — but the window is now scrolled such
   that the input sits below the visible viewport.
5. Opening the soft keyboard shrinks the Android viewport. With
   `100vh`-based sizing, nothing recomputes, so content overhangs.

### Design

Scope the fix to the Chat route only — other routes work fine today and
should keep their natural window-scroll behaviour. The change is
structural rather than cosmetic.

- Wrap the entire ChatView in a container with
  `h-[100dvh] overflow-hidden`. `dvh` (dynamic viewport height)
  automatically tracks keyboard open/close on Android Chromium.
- Inside that wrapper, a flex column with three children:
  - **TopBar** — `flex-none`.
  - **MessageList** — `flex-1 min-h-0 overflow-auto`. The `min-h-0` is
    load-bearing: without it, the flex child refuses to shrink below its
    content height and the whole layout breaks. This is the *only*
    scrollable region on the chat route.
  - **ChatInput** — `flex-none`. The existing `sticky bottom-0 z-10` is
    removed; the input is now a natural flex child that sits at the
    bottom of the locked container. The `safe-area-inset-bottom` padding
    stays.
- Extend `frontend/index.html` viewport meta to:
  `width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content`.
  On Chromium-based Android browsers this makes the virtual keyboard
  resize the layout viewport instead of overlaying it — so `100dvh`
  shrinks correctly and the chat layout recomputes around the keyboard.

### Why not `visualViewport`?

On Android Chromium, `dvh` + `interactive-widget=resizes-content` is
enough: the viewport shrinks when the keyboard opens and expands when it
closes. `visualViewport` handling is primarily needed on iOS Safari,
which is not the current target. If iOS becomes a target later, a
dedicated `useKeyboardInset()` hook can layer on top — but shipping that
now would be unearned complexity.

### Other routes

The `dvh` / `overflow-hidden` / flex-lock pattern is *not* propagated to
other routes. Settings, profile, artefacts, etc. stay with their
current window-scroll behaviour, which is fine for content longer than a
viewport.

### Files touched

- **Modified:** `frontend/src/features/chat/ChatView.tsx` — swap root
  container to `h-[100dvh] overflow-hidden`, adjust internal flex
  classes on the top-bar / message-list / input containers.
- **Modified:** `frontend/src/features/chat/ChatInput.tsx` (or
  wherever the input root lives) — remove `sticky bottom-0 z-10`, keep
  `pb-[calc(env(safe-area-inset-bottom)+…)]`.
- **Modified:** `frontend/index.html` — add
  `, interactive-widget=resizes-content` to the viewport meta content.

---

## Fix 3 — PWA reload button and auto-reload on update

### Current state

- `frontend/src/app/components/pwa/InstallHint.tsx` inlines the
  `display-mode: standalone` check (also checks
  `navigator.standalone` for iOS).
- `frontend/src/core/pwa/registerPwa.ts:21–34` currently surfaces an
  "Update verfügbar" toast with a manual "Neu laden" action when
  `onNeedRefresh` fires.
- The User modal is at `frontend/src/app/components/user-modal/UserModal.tsx`
  and already has a Settings tab.

### Design

Three small additions that work together:

#### 3a — `useIsPwa()` hook

New `frontend/src/core/hooks/useIsPwa.ts`:

```ts
export function useIsPwa(): boolean
```

Returns `true` if the app is running in PWA (standalone) mode. Reuses the
exact detection logic currently inlined in `InstallHint.tsx`
(`matchMedia('(display-mode: standalone)').matches`
|| `(navigator as any).standalone === true`). Subscribes to the match
media change event so value updates if the mode changes at runtime.

`InstallHint.tsx` is refactored to consume this hook, removing its
duplicate detection code.

#### 3b — Manual reload button

In the User modal's Settings tab, add a button labelled
**"App neu laden"** that calls `window.location.reload()`. The button is
only rendered when `useIsPwa()` returns `true`; in a plain browser it
does not show, because the user has the browser refresh button.

Placement: as a secondary action in the settings tab, visually separated
from destructive actions (logout, delete account). Style: outline/ghost
button, not a primary call-to-action.

#### 3c — Auto-reload on service worker update, with deferral

Replace the current `onNeedRefresh` toast in `registerPwa.ts` with
automatic reload:

- When `onNeedRefresh` fires, call `void updateSW(true)` to activate
  the new service worker (`skipWaiting`), then attempt to
  `location.reload()`.
- Before reloading, check two conditions:
  1. `useConversationModeStore.getState().active === true` — the user is
     in Conversational Mode.
  2. `useChatStore.getState().isStreaming === true` — an LLM response is
     currently being streamed (`frontend/src/core/store/chatStore.ts:32`).
- If either is true, the reload is **deferred**. Subscribe to both
  stores; as soon as both conditions are false for a 500ms settle
  window (to avoid reloading inside a gap between two rapid streams),
  call `location.reload()`.
- If both are already false, reload immediately.

No toast, no UI indicator. The reload itself is the signal.

The deferral has **no timeout**. If the user happens to hold a
Conversational Mode session open for two hours straight, the reload
waits two hours. That is acceptable — updates are infrequent, and the
worst case (a user who never idles) is "runs the old version a bit
longer", not a functional defect.

### Files touched

- **New:** `frontend/src/core/hooks/useIsPwa.ts`
- **Modified:** `frontend/src/app/components/pwa/InstallHint.tsx` — use
  the new hook, remove inlined detection.
- **Modified:** `frontend/src/app/components/user-modal/UserModal.tsx`
  (or the specific settings-tab file it delegates to) — add the
  "App neu laden" button, PWA-gated.
- **Modified:** `frontend/src/core/pwa/registerPwa.ts` — remove the
  update toast, add the deferred-auto-reload logic.

No changes to `initInstallPrompt`, the manifest, or the service worker
itself.

---

## Testing

### Unit tests (Vitest + `@testing-library/react`)

- `MobileToast` renders the current top-of-store notification, swipe-down
  triggers dismiss, tap triggers dismiss, auto-dismiss fires after the
  configured duration.
- `MobileToastContainer` returns null when `useViewport().isMobile` is
  false; renders a single toast when it is true; replaces the current
  toast when a newer one arrives (crossfade class applied).
- `ToastContainer` returns null when `useViewport().isMobile` is true.
- `useIsPwa` returns `true` when `matchMedia('(display-mode: standalone)')`
  matches; `false` otherwise; updates on the media query change event.
- `registerPwa` deferral logic: with `conversationActive = true`, no
  reload is called; flipping to `false` triggers reload after the
  settle delay. Verified with a mocked `location.reload` and fake
  timers.

### Manual verification (Galaxy S20 Ultra + Vivaldi, both plain browser and installed PWA)

**Toast:**

1. On the profile page, trigger any action that emits a toast (e.g.
   copy a share link). Observe: toast appears at the bottom, solid
   background, fully readable.
2. Swipe the toast downward — it dismisses.
3. Trigger a second toast quickly; the first one is replaced by the
   second (not stacked).
4. Trigger a long-running action that emits a "…" progress toast
   followed by a "done" toast. Only one is visible at a time.

**Chat viewport:**

5. Open a chat. Type "Hi" and press Enter. Verify: top bar stays put,
   input stays put, only the message list scrolls to show the new
   message.
6. Tap the input. The keyboard opens. Verify: input remains above the
   keyboard, top bar is still visible, message list has shrunk to fill
   the remaining space.
7. Type a long multi-line message (Shift+Enter or whatever inserts
   newlines on your IME). Verify: input grows, message list shrinks;
   input text never disappears behind the keyboard.
8. Press the send button. Verify same result as step 5.

**PWA reload:**

9. In plain browser: open the User modal → Settings. Verify: no
   "App neu laden" button present.
10. In the installed PWA: same path. Verify: button is present, clicking
    it reloads the app.
11. Deploy a new version while the PWA is open on an idle chat. Verify:
    the app silently reloads within a few seconds, no toast appears.
12. Deploy a new version while the PWA is actively in Conversational
    Mode. Verify: no reload happens. Exit Conversational Mode. Verify:
    the app reloads shortly after.

---

## Scope non-goals

- **No iOS Safari work.** Current mobile target is Android Chromium
  (Vivaldi). iOS-specific `visualViewport` or keyboard-inset handling
  is deferred.
- **No unification of Toast for desktop.** Desktop keeps its glass
  top-centred style. The cross-cut change would be larger in scope and
  would affect a UX that is already fine.
- **No toast history / notification centre.** Dropping older toasts on
  mobile is a deliberate trade-off.
- **No settings / preferences** to opt out of auto-reload on update.
  The goal is zero friction.
- **No timeout on reload deferral.** Idle-wait is sufficient.
- **No global viewport lock.** Only the Chat route gets the locked
  shell; all other routes keep window-scroll.
- **No refactor of `notificationStore`.** The store's contract is fine.

## Files touched — summary

New:

- `frontend/src/app/components/toast/MobileToastContainer.tsx`
- `frontend/src/app/components/toast/MobileToast.tsx`
- `frontend/src/core/hooks/useIsPwa.ts`

Modified:

- `frontend/src/app/components/toast/ToastContainer.tsx`
- `frontend/src/app/layouts/AppLayout.tsx`
- `frontend/src/features/chat/ChatView.tsx`
- `frontend/src/features/chat/ChatInput.tsx` (or the file that owns the
  input root with the `sticky` class)
- `frontend/src/app/components/pwa/InstallHint.tsx`
- `frontend/src/app/components/user-modal/UserModal.tsx` (or its
  settings-tab child)
- `frontend/src/core/pwa/registerPwa.ts`
- `frontend/index.html`

No backend changes. No store schema changes. No manifest changes.

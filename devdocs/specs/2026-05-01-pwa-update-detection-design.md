# PWA Update Detection

## Problem

`vite-plugin-pwa` is configured in `"prompt"` mode. When a new
service worker is published, it lands in the user's browser as
"waiting" and only takes over once an explicit activation happens.
Today the activation logic in `frontend/src/core/pwa/registerPwa.ts`
calls `updateSW(true)` on the `onNeedRefresh` callback and then
defers the resulting reload via `reloadWhenIdle()` — which waits
for `chatStore.isStreaming === false` AND
`conversationModeStore.active === false`, plus a 500 ms settle
window.

That works in theory. In practice testers report two recurring
symptoms:

1. **The reload never fires during long sessions.** If a user is
   continuously chatting or in continuous voice mode, idle never
   arrives, the waiting SW never activates, and the user keeps
   running the old version. There is no UI signal that an update is
   waiting, so the user has no way to know.
2. **Re-opening the app does not always pick up the latest
   version.** When the PWA shell starts, the previously cached
   service worker serves the previously cached assets first. The
   in-background update check eventually finds the new SW, marks it
   waiting, and `onNeedRefresh` fires — but by then the user has
   already started using the old version. On platforms like iOS
   Safari that hold the PWA container in memory, the issue is
   amplified because the old SW lifecycle isn't always cleanly
   torn down between sessions.

The user has worked around this by adding a manual "Reload app"
button in Settings (`SettingsTab.tsx:200-211`). That works, but it
shifts the burden onto the user to remember and act.

## Goal

Two invariants:

- **Fresh starts always converge to the latest version.** When a
  user opens the PWA (or hard-reloads the page), they end up
  running the most recent published frontend within seconds, with
  no manual action required.
- **Mid-session updates are visible.** When a new version is
  published while a user is already using the app, the user gets
  a clear, non-interrupting signal and can choose when to reload.

## Design

The `onNeedRefresh` callback in `registerPwa.ts` becomes
context-aware: it picks one of two paths based on how long ago
the app booted.

### Boot-window path (≤ 5 s since app mount)

When `onNeedRefresh` fires within 5 seconds of the app's first
render, the user has just opened the app. The update was found
during the early registration handshake. We want to swallow the
"first impression" by loading the new version before the user
notices.

```ts
const BOOT_GRACE_MS = 5_000
const bootedAt = performance.now()

onNeedRefresh: () => {
  const sinceBoot = performance.now() - bootedAt
  if (sinceBoot <= BOOT_GRACE_MS) {
    // Fresh start; user hasn't engaged yet. Activate the waiting
    // SW and reload immediately — no toast.
    void updateSW(true)
    return
  }

  // Mid-session path follows...
}
```

`updateSW(true)` calls `skipWaiting()` on the waiting SW and
triggers a reload via the `controllerchange` listener that
vite-plugin-pwa wires up internally. The page reloads with the new
assets.

We also pass `immediate: true` to the `registerSW` options so the
plugin asks the browser to check for updates as soon as the SW is
registered, rather than waiting on the browser's default update
cadence. This shortens the boot-window race for users where the SW
update isn't already cached.

### Mid-session path (> 5 s since app mount)

When `onNeedRefresh` fires after the boot window, the user has
already engaged. We show a sticky toast and let them decide:

```ts
useNotificationStore.getState().addNotification({
  level: "info",
  title: "Neue Version verfügbar",
  message: "Klicke auf 'Jetzt neu laden', um zu aktualisieren.",
  duration: 0,  // sticky — see below
  action: {
    label: "Jetzt neu laden",
    onClick: () => {
      void updateSW(true)  // skipWaiting + reload, no idle defer
    },
  },
})
```

In parallel, the existing background path runs: `updateSW()` (no
argument) marks the new SW as waiting (already done by
vite-plugin-pwa internally), and we kick `reloadWhenIdle()` so the
idle-reload path keeps working as a fallback.

If the user clicks "Jetzt neu laden", the reload is **immediate**
(`updateSW(true)`), even mid-stream. The user accepted the
consequence by clicking. Streaming-state loss is acceptable —
messages are persisted server-side.

If the user dismisses the toast (manual X), no further toast is
shown for this update. The idle-reload background path stays
active. If they never go idle, they keep running the old version
until they reload manually (Settings button) or close and re-open
the app.

### Sticky toast support

The current `notificationStore` auto-dismisses notifications based
on `duration` (defaulting per-level: 4 s for info, 10 s for error).
There's no documented way to opt out. We add a small extension:
`duration: 0` (or any non-positive value) means "do not
auto-dismiss". The toast component already pauses the timer on
hover via `setTimeout`; we extend the same logic to skip starting
the timer when `duration <= 0`.

This is a minimal, backward-compatible change. Existing callers
keep working unchanged.

### Things we explicitly do NOT change

- The `reloadWhenIdle()` helper stays. It's the safety net for the
  mid-session path: even if the user ignores the toast, the reload
  eventually happens when they pause.
- The Settings "Reload app" button stays. Backup channel.
- We do not switch to network-first for `index.html`. App-shell
  caching is part of the offline story.
- We do not add a frontend version constant for backend ⇄ frontend
  version compatibility checks. That's a separate concern (out of
  scope) — today the marker header value is `1`, no version
  comparison is meaningful.

## Manual verification

The product owner runs these. Some require deploying a new build
to the staging instance to trigger the SW update path.

### Boot-window auto-reload

1. Deploy build N. Open the PWA, log in, leave it idle. Confirm the
   app is running build N.
2. Deploy build N+1.
3. Close the PWA shell completely (or hard-reload the page in the
   browser).
4. Open the PWA again.
5. **Expected:** within ~3-6 seconds of opening, the app reloads
   itself once, and the resulting page is build N+1. No toast
   appears. The user just sees a single small reload flicker on
   first start.

### Mid-session toast + manual reload

6. With build N+1 active, leave the app open and idle on a chat
   page.
7. Deploy build N+2.
8. Wait until the SW background-update check picks up the new
   version (typically 60 seconds, depending on browser).
9. **Expected:** a sticky toast appears with title "Neue Version
   verfügbar" and an action button "Jetzt neu laden". The toast
   does not auto-dismiss.
10. Click "Jetzt neu laden".
11. **Expected:** immediate page reload, app comes back as build
    N+2.

### Mid-session toast + idle path (no manual click)

12. Repeat steps 7-9 with a fresh build N+3.
13. Do NOT click the action button; just let the app sit idle for
    ~10 seconds.
14. **Expected:** because `chatStore.isStreaming` is false and
    `conversationMode.active` is false, `reloadWhenIdle` triggers,
    the page reloads, the toast disappears with the reload, the
    app comes back as build N+3.

### Mid-session toast dismissal

15. Repeat steps 7-9 with a fresh build N+4.
16. Dismiss the toast manually (X button).
17. **Expected:** no further toast for this update. The
    idle-reload safety net still triggers if/when the user goes
    idle. If the user is continuously active, the app continues
    running build N+3 (the previously installed version) until
    they manually reload via Settings or restart.

### Mid-session click during active streaming

18. Start a long LLM response so streaming is active.
19. Have a new build N+5 published while streaming. Toast appears.
20. Click "Jetzt neu laden" mid-stream.
21. **Expected:** immediate reload — the streaming response is
    abandoned. The user sees build N+5 on return; the in-flight
    message is gone from the UI but available in chat history
    (server-persisted).

## Files affected

- `frontend/src/core/pwa/registerPwa.ts` — split `onNeedRefresh`
  into boot-window and mid-session paths; add the
  `BOOT_GRACE_MS` constant and `bootedAt` reference; add
  `immediate: true` to the `registerSW` options; emit the toast
  with the action callback in the mid-session path.
- `frontend/src/core/store/notificationStore.ts` — accept
  `duration: 0` (or non-positive) as "sticky".
- `frontend/src/app/components/toast/Toast.tsx` — skip auto-dismiss
  timer when notification's effective duration is `<= 0`.

No backend changes. No new files.

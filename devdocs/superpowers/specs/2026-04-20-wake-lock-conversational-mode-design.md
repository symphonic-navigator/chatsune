# Wake Lock in Conversational Mode — Design

**Date:** 2026-04-20
**Status:** Approved, ready for implementation planning
**Scope:** Frontend only

## Motivation

On mobile (PWA), when the screen turns off the browser suspends the tab and
the WebSocket connection drops. **Conversational Mode** — the live,
hands-free voice mode driven by `useConversationMode` + VAD — becomes
unusable as soon as the user puts the device down.

The desired use case: hands-free conversation during other activities (e.g.
washing up, cooking). Conversational Mode is the one Chatsune mode that is
*long-running and does not involve the user actively holding the device*.
All other interactions (text chat, push-to-talk voice capture) already keep
the device awake through normal user input.

> **Naming note:** An older `voiceSettingsStore.inputMode === 'continuous'`
> path has been retired (see `voiceSettingsStore.ts:33-39`). This spec
> targets Conversational Mode only. The two must not be conflated.

## Approach

Use the [Screen Wake Lock API](https://developer.mozilla.org/en-US/docs/Web/API/Screen_Wake_Lock_API).
While Conversational Mode is active, request a `'screen'` wake lock so the
operating system does not auto-dim or sleep the display. Release the lock
the moment the mode exits.

The screen stays lit — the phone does not go into standby — which keeps the
tab foregrounded and the WebSocket alive. No silent-audio hacks, no service
worker tricks, no native wrapper.

## Design rules

- **Only in Conversational Mode.** Push-to-talk voice capture does nothing
  different. Regular text chat does nothing different.
- **No setting, no toggle.** Conversational Mode implicitly keeps the
  screen awake. If the user entered Conversational Mode, they want to
  converse — a dimmed screen defeats the feature.
- **No UI indicator.** Users are not told "the screen is being kept awake".
  It is invisible behaviour that "just works". Adding a badge would only
  raise questions.
- **Silent fallback on unsupported browsers.** No toast, no warning. The
  feature simply does not activate; Conversational Mode still runs.

## Architecture

### New file: `frontend/src/core/hooks/useWakeLock.ts`

A small, generic React hook:

```ts
export function useWakeLock(shouldHold: boolean): void
```

Behaviour:

- When `shouldHold` transitions to `true`: request
  `navigator.wakeLock.request('screen')` and store the returned
  `WakeLockSentinel`.
- When `shouldHold` transitions to `false`: call `sentinel.release()` and
  clear the stored handle.
- On `document.visibilitychange` to `visible`: if `shouldHold` is still
  `true` but the stored sentinel has been released by the browser (this
  happens automatically when the tab is hidden), re-request.
- On unmount: release any held sentinel.
- If `'wakeLock' in navigator` is `false`: the hook is a no-op — no
  request, no error thrown. A single debug-level log entry at first
  activation is acceptable for diagnostics but not required.

The hook's only dependency is `shouldHold`. It knows nothing about voice,
Conversational Mode, settings, or pipelines — deliberately generic so
future "long-session" features can compose it too.

### Integration

In `frontend/src/features/chat/ChatView.tsx`, immediately adjacent to the
existing `useConversationMode({ ... })` call (currently at line 981):

```tsx
import { useConversationModeStore } from '../voice/stores/conversationModeStore'
import { useWakeLock } from '../../core/hooks/useWakeLock'

// ... inside the component, near the useConversationMode call:
const conversationActive = useConversationModeStore(s => s.active)
useWakeLock(conversationActive)
```

The activation condition is exactly:

```
useConversationModeStore.active === true
```

When the user enters Conversational Mode, `active` flips to `true` and the
lock is requested. When they exit (manually, via navigating away, via
availability loss, or via `teardown`), `active` flips to `false` and the
lock is released. The existing conversation-mode lifecycle does all the
work — the wake lock just mirrors `active`.

### Interaction with existing WebSocket reconnect

The existing `useWebSocket` hook at
`frontend/src/core/hooks/useWebSocket.ts:34-58` already handles reconnection
on `visibilitychange` and `focus`. This design composes cleanly with it:

- User taps away to another app → screen can turn off → OS may close the
  WebSocket. The browser releases the wake lock as part of hiding the tab.
- User returns to Chatsune → `visibilitychange` fires → existing hook
  re-connects the WebSocket, `useWakeLock` re-acquires the lock.

No changes to `useWebSocket` are needed.

## Testing

### Unit tests (Vitest + `@testing-library/react`)

Test the hook in isolation with a mocked `navigator.wakeLock`:

- `shouldHold: false` → no request is made.
- `shouldHold: false → true` → exactly one request is made.
- `shouldHold: true → false` → the sentinel's `release()` is called.
- Tab hidden (simulate `visibilitychange` with `document.hidden = true` and
  sentinel marked released by mock) → on `visibilitychange` back to
  visible with `shouldHold` still `true`, a new request is made.
- `'wakeLock' in navigator` is `false` → no calls, no errors thrown.
- Component unmounts while holding a lock → `release()` is called.

### Manual verification

On a real Android mobile device (screen timeout set to, e.g., 30 seconds):

1. Open Chatsune PWA, start a conversation.
2. Enter Conversational Mode (the live voice chat UI).
3. Put the phone face-up on a table without locking it.
4. Wait past the normal screen timeout; verify the screen stays on.
5. Exit Conversational Mode.
6. Verify the screen now dims on its usual schedule.
7. Re-enter Conversational Mode, then switch to another app for ~30
   seconds, then return. Verify the screen is kept awake again.

This manual check is required before declaring the feature done — unit
tests cannot verify that the OS actually honours the lock.

## Scope non-goals

Explicitly out of scope for this spec:

- No UI element indicating "screen is being kept awake".
- No user-facing setting to disable this behaviour.
- No behaviour change in push-to-talk voice capture.
- No behaviour change in text chat (including during long streaming LLM
  responses — a separate question, not covered here).
- No desktop-specific handling. Desktop browsers honour the request
  harmlessly; desktop screen-sleep during active sessions is rarely a
  problem in practice.
- No backend changes of any kind.
- No resurrection of the retired `inputMode === 'continuous'` path.

## Files touched

- **New:** `frontend/src/core/hooks/useWakeLock.ts`
- **New:** `frontend/src/core/hooks/useWakeLock.test.tsx`
- **Modified:** `frontend/src/features/chat/ChatView.tsx` — two new
  imports plus two lines near the existing `useConversationMode` call.

No changes to `voicePipeline.ts`, `voicePipelineStore.ts`,
`voiceSettingsStore.ts`, `conversationModeStore.ts`, `useConversationMode.ts`,
`useWebSocket.ts`, the PWA config, the manifest, the service worker, or
the backend.

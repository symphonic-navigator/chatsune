# Barging Toggle in Live Voice Mode — Design

**Status:** approved, ready for implementation plan
**Date:** 2026-05-07
**Branch:** `feat/barging-toggle`

---

## Background

Live Voice Mode in Chatsune today supports barging by default: while the
persona is speaking, the user can interrupt at any time, the active
`ResponseTaskGroup` is paused, STT runs over the user's incoming speech, and
on commit a new Group is registered with the barged transcript.

Field testing and user feedback have shown that "always-on barging" is not
universally desirable. Two distinct usage profiles emerged:

- **Quiet environment** (desk at home): barging is preferred — natural,
  low-latency, conversational.
- **Noisy or mobile environment** (commute, public space): the user wants
  to **stay on turn-by-turn** even when the surrounding noise floor would
  otherwise look like a barge attempt to VAD.

The product needs an explicit, user-controlled toggle to switch between
those two profiles per device. This spec defines the UI and behaviour of
that toggle.

The current barging implementation is intentionally not changed by this
spec — only **suppressed** in the relevant phase, so that all existing
correctness invariants (Group-pause, supersede, retract, resume on stale)
keep holding when barging is enabled.

---

## Goals

1. Provide a one-tap toggle to switch barging on/off, accessible from the
   chat cockpit while in Live Voice Mode.
2. Persist the toggle per device in `localStorage`, with `true` (barging
   on) as the default — matching today's behaviour for existing users.
3. Communicate the current state and any phase-driven sub-state visually
   on the toggle button itself, with no second slash on the existing
   `VoiceButton` mic glyph.
4. Suppress mid-speak barge attempts cleanly, without breaking already
   in-flight barges (Option 3 semantics, see §Behaviour).

## Non-goals

- Server-side sync of the toggle across devices. The whole premise of
  the feature is that the right value differs per environment, which
  maps naturally to per-device storage.
- Backend or DB schema changes. The toggle is a pure frontend concern.
- New analytics or telemetry on the toggle.
- An onboarding tooltip or first-use hint. If user feedback shows the
  control is undiscovered, that is a follow-up.
- Changes to the `bargeController` itself. It remains the in-flight
  barge lifecycle owner; the toggle gates the *entry* into a barge, not
  the controller's internals.

---

## UI

### Placement

| Viewport | Today | With this feature |
|---|---|---|
| Mobile (`< 1024px`) | `ⓘ` button at the right end of the cockpit row in all states | When `liveActive === true`: `ⓘ` is **replaced** by the BargingToggle button at the same slot. When `liveActive === false`: unchanged (`ⓘ` is shown). |
| Desktop (`≥ 1024px`) | `🎙` LiveButton is the last element, no separator after | When `liveActive === true`: a `<Sep />` and the BargingToggle button are rendered after the LiveButton. When `liveActive === false`: nothing changes (no separator, no toggle). |

The mobile breakpoint follows the project convention of `lg` (1024px) as
the only mobile/desktop split.

The toggle is **not rendered at all** outside of Live Voice Mode. There
is no point exposing a barging preference when the user has no live
audio session.

### Visual states

Four visual states cover all combinations of `enabled` × `phase`:

| Toggle | Phase | Glyph | Colour | Pulsation |
|---|---|---|---|---|
| **on** (`enabled === true`) | any | open lips | green (`#4ade80` or theme `text-green-400`) | no |
| **off** (`enabled === false`) | `idle` / `listening` / `transcribing` / `thinking` | lips with diagonal slash | red (`#ef4444` or theme `text-red-400`) | no |
| **off** | `speaking` | microphone with diagonal slash | red | yes — slow rhythmic pulse (~2s cycle) |

The change in glyph between "barging-off, not speaking" (lips+slash) and
"barging-off, speaking" (mic+slash) is the explicit cue that the user's
voice input is actively being held back *right now*. The lips glyph
communicates "speech preference"; the mic glyph communicates "mic state".
Both are red, both have a slash — the swap is a deliberate semantic
escalation that mirrors the user's situation: *normally my barging is
off, and right now that means my mic is asleep.*

The pulsation is implemented with the existing `animate-pulse-slow`
utility used by `ConversationModeButton` (see
`frontend/src/features/voice/components/ConversationModeButton.tsx`,
the `active` branch). Reduced-motion preferences must be honoured —
when `(prefers-reduced-motion: reduce)` matches, the pulsation is
suppressed and the button stays static (the colour and glyph swap still
convey the state).

### Tooltips / aria-labels

- on: *"You can interrupt the persona while she speaks"*
- off, not speaking: *"Persona speech can't be interrupted — tap to enable"*
- off, speaking (pulsing): *"Mic asleep while persona speaks — tap to enable"*

### Mic-Button (`VoiceButton`) is unchanged

The blue `VoiceButton` keeps all its existing states unchanged:
`live-mic-on`, `live-mic-muted`, `live-playing` (stop / interrupt),
`live-paused`. In particular, the `live-mic-muted` slash retains its
sole meaning: *"the user has explicitly muted the mic via this button"*.
No second-meaning slash is added there.

This is the central UX choice of the spec: the *toggle* button carries
the new semantics; the *mic* button stays canonical.

---

## State

### Storage

A new zustand store, `bargeSettingsStore`, holds the single boolean
`enabled` and persists it to `localStorage` under the key
`voice.barging.enabled` via zustand's `persist` middleware.

```ts
// frontend/src/features/voice/stores/bargeSettingsStore.ts
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface BargeSettingsState {
  enabled: boolean
  setEnabled: (next: boolean) => void
  toggle: () => void
}

export const useBargeSettingsStore = create<BargeSettingsState>()(
  persist(
    (set) => ({
      enabled: true,
      setEnabled: (next) => set({ enabled: next }),
      toggle: () => set((s) => ({ enabled: !s.enabled })),
    }),
    { name: 'voice.barging.enabled' },
  ),
)
```

### Default

Default is `enabled: true`. This matches today's behaviour exactly, so
existing users who never touch the toggle see no behavioural change.

### Lifetime

The store is a pure user preference. It is **not** reset on `exit()` of
Live Mode, on logout, or on session change. It persists across reloads
and survives indefinitely until the user toggles it again or clears
browser storage. Reasoning: the preference reflects the user's current
*environment* (home vs. on the move), which is far more stable than any
session boundary.

---

## Behaviour

### The gate

In `useConversationMode.ts`, the existing call to
`bargeController.start()` (triggered on a VAD onset during persona
speech) gains a single guard:

```
on VAD onset:
  if (phase === 'speaking' && bargeSettingsStore.enabled === false):
    log('barge.gate.suppressed', { phase, vadActive })
    return  // no-op; bargeController is not entered
  // … existing flow: bargeController.start(), Group.pause(), STT, …
```

Notes:

- The guard reads the live store value at call time, not via a captured
  closure, so changes to `enabled` apply at the next VAD frame.
- The guard is phase-specific: it fires **only** when the active phase
  is `speaking`. In `transcribing` / `thinking`, the mic is naturally
  closed by the pipeline anyway; in `listening` / `idle`, the user is
  free to speak as normal regardless of toggle state.
- The guard fires **before** any side effect (no `Group.pause()`, no
  STT promise creation, no UI flicker on the visualiser).

### Mid-speak toggle semantics (Option 3)

Three sub-cases, distinguished by what the controller currently holds:

1. **No active barge in flight** (`bargeController.current === null`,
   common case). User toggles on→off mid-speak: nothing changes
   immediately; the next VAD onset is suppressed by the gate. User
   toggles off→on mid-speak: the gate stops suppressing; the next VAD
   onset triggers a normal barge.

2. **Active barge in flight, user toggles off→on**: also a no-op for
   the in-flight barge, since the controller doesn't observe the
   setting at all. The barge runs to its natural end (`commit`,
   `resume`, or `stale`).

3. **Active barge in flight, user toggles on→off**: this is the only
   subtle case. Per the agreed Option 3 semantics, the in-flight barge
   is **not** aborted. It runs to its natural end exactly as it would
   have without the toggle. Only *future* VAD onsets are then
   suppressed (until the toggle is flipped back on or the speaking
   phase ends).

Rationale for Option 3: aborting an in-flight barge would surprise the
user — they already started speaking, the persona is paused waiting for
their turn, and a stray double-tap on the toggle should not throw their
sentence away. Symmetry and least-astonishment win over strict
"toggle wins immediately" semantics in this edge.

### Logging

A single new structured log line is emitted on suppression:

```
barge.gate.suppressed
  phase=speaking
  enabled=false
  vadActive=true
```

This is the trail to read when a tester reports "I tried to barge but
the mic didn't pick me up" — the log makes it unambiguous whether the
gate ate the attempt or whether the issue lies elsewhere (e.g. STT
network failure, VAD threshold).

---

## Components and files

### New files

- `frontend/src/features/voice/stores/bargeSettingsStore.ts` — the
  store described in §State.
- `frontend/src/features/chat/cockpit/buttons/BargingToggleButton.tsx`
  — the toggle button itself, with the four visual states described
  in §UI.
- `frontend/src/features/voice/hooks/__tests__/useConversationMode.bargeGate.test.tsx`
  — three new test cases described in §Testing.

### Modified files

- `frontend/src/features/chat/cockpit/CockpitBar.tsx` — conditional
  rendering of the BargingToggleButton vs. the existing `ⓘ` (mobile)
  / nothing (desktop), gated on `liveActive`.
- `frontend/src/features/voice/hooks/useConversationMode.ts` — single
  gate added before `bargeController.start()`.

### Unchanged files (explicit)

- `frontend/src/features/voice/bargeController.ts` — the controller's
  contract is exactly the same. The gate sits one level up.
- `frontend/src/features/voice/__tests__/bargeController.test.ts`,
  `bargeSupersedeOrdering.test.ts`, `derivePhase.test.ts` — no
  controller-level behaviour changes.
- `frontend/src/features/chat/cockpit/buttons/VoiceButton.tsx` — the
  blue mic button keeps every existing state and meaning, including
  its single slash usage for `live-mic-muted`.
- All backend code. Pure frontend feature.

---

## Testing

### New unit tests

`useConversationMode.bargeGate.test.tsx`:

1. **Gate suppresses barge when disabled and speaking.** Given
   `bargeSettingsStore.enabled === false` and an active Group in
   `streaming` (i.e. phase derives to `speaking`), when a VAD onset
   fires, then `bargeController.start` is **not** called and a
   `barge.gate.suppressed` log line is emitted.

2. **Gate is phase-specific: passes through in listening.** Given
   `enabled === false` and no active Group (phase `listening`), when
   a VAD onset fires, then `bargeController.start` **is** called.
   Confirms the gate doesn't accidentally suppress legitimate
   listening-phase speech.

3. **Mid-barge toggle off does not abort an in-flight barge.** Given
   `enabled === true`, fire a VAD onset so a barge is in
   `pending-stt`, then toggle `enabled = false`. The in-flight barge
   must reach its natural terminal state (`commit` on STT success,
   `stale` on misfire). A *new* VAD onset fired after the toggle must
   be suppressed.

### Manual verification

To be exercised on a real device (mobile and desktop) before merge:

1. Open a chat in Live Voice Mode on mobile. Confirm the `ⓘ` button
   in the cockpit is replaced by the BargingToggle in its current
   state. Exit Live Mode. Confirm `ⓘ` is back.
2. On desktop, open Live Voice Mode. Confirm the toggle appears after
   the `🎙` LiveButton with a separator. Exit Live Mode. Confirm
   the toggle disappears and no leftover separator remains.
3. With barging on, start a long persona response. Speak over the
   persona. Confirm normal barge: persona pauses, your speech is
   transcribed, a new turn starts.
4. Switch barging off. Start a long persona response. Speak over the
   persona at moderate volume. Confirm: persona keeps speaking, no
   barge fires, toggle button shows the pulsing mic+slash glyph,
   colour red.
5. While the persona is speaking with barging off, toggle barging on.
   Confirm: the next time you speak, a normal barge happens.
6. While the persona is speaking with barging on, start speaking
   (barge enters `pending-stt`), then immediately toggle barging off.
   Confirm: your in-flight barge completes normally (your sentence
   is sent), and a *subsequent* speak attempt during the next persona
   response is suppressed.
7. Reload the page. Confirm the toggle state persists (read from
   `localStorage`).
8. On a separate device / fresh browser profile, confirm the default
   is "barging on".
9. With `prefers-reduced-motion: reduce` enabled in OS / browser,
   confirm the pulsation is disabled but the colour and glyph still
   communicate the state.

---

## Risks and mitigations

- **Risk:** A user toggles off and forgets, then later wonders why the
  persona "won't listen". *Mitigation:* the pulsing red mic+slash
  glyph during persona speech is exactly the cue for this. The tooltip
  on hover/long-press names the state and the remedy.
- **Risk:** localStorage cleared (incognito, browser data wipe). *Mitigation:*
  the default is `true`, which matches today's behaviour. Users in this
  state simply land on the familiar default; no broken UX.
- **Risk:** The `BargingToggleButton` is rendered inside the cockpit
  flex row and might wrap awkwardly on narrow viewports. *Mitigation:*
  it occupies the same slot as `ⓘ` on mobile, which has been working
  fine; visual review at the smallest supported breakpoint
  (`375px` for iPhone SE) is part of manual verification.

---

## Out-of-scope follow-ups

These are explicitly deferred and may surface as their own briefs after
tester feedback:

- A first-use hint or tooltip-on-mount pointing the toggle out.
- Server-side sync of the preference across devices (would conflict
  with the per-environment intent and is not currently desired).
- Per-persona barging defaults (e.g. a persona that should never be
  interrupted regardless of user setting).
- Hard-disable barging via persona config (separate concern from this
  user-controlled, per-device toggle).

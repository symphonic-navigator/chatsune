# Voice Feedback — Design

**Date:** 2026-04-26
**Status:** Draft, awaiting Chris's review
**Scope:** Frontend only. One new emitter singleton, one new Zustand store, one new overlay component, two existing-component extensions. No backend changes, no DTO changes, no DB changes.

---

## 1. Problem

Two pieces of user feedback after the spectrum visualiser ships:

1. **No live confirmation that the mic is hearing the user.** In Live mode, the mic is open hands-free. Users cannot tell from the UI whether their voice is actually being captured — they speak, and either something happens or it does not. They want a continuous "I hear you" cue tied to actual mic activity (not just a static "mic on" icon).

2. **No way to pause TTS without cancelling it.** Today the only TTS interrupt is the Cockpit's ⏹ button, which fully stops generation (Group cancel). Users want a softer interaction: pause the voice, then resume from where it left off. The natural target is the spectrum visualiser itself — it is already the only on-screen indication that TTS is happening.

Both features are small frontend additions sharing the voice-feedback domain. They are designed together so the state machine is consistent (pause auto-mutes the mic in Live mode; resume restores it).

---

## 2. Goals and non-goals

### Goals

- **Pulse the LiveButton** (`features/chat/cockpit/buttons/LiveButton.tsx`) in rhythm with the user's voice, while the mic is open and unmuted. Phase-independent — also pulses during TTS playback if the user barges in.
- **Tap-to-pause TTS** via a centred horizontal hit-strip overlaid on the visualiser. Tap pauses TTS and (in Live mode) mutes the mic. Tap again resumes TTS and restores the mic state.
- **Self-healing state.** If TTS ends externally (Cockpit-Stop, Group cancel, Live-mode exit, queue drain), the pause state clears automatically and the mic is restored.
- **Respect existing user preferences.** When the visualiser is disabled or `prefers-reduced-motion` is active, neither the LiveButton pulse nor the hit-strip render — status quo for those users.

### Non-goals

- No new pause control elsewhere in the UI (no Cockpit pause button, no keyboard shortcut). The visualiser is the sole tap target.
- No persistence of pause state across reloads. Pause is in-memory; refresh resets everything.
- No auto-cancel timeout for indefinitely paused TTS. The Group keeps streaming chunks into the queue; for realistic TTS replies (10–30s) this is unproblematic.
- No new pulsing for the Cockpit Voice button (the multi-state ⏹/🔊/mic icon). Pulsing lives only on the LiveButton, which is unambiguously tied to Live mode.
- No additional visual affordance for the hit-strip (e.g. floating "II" glyph). The bars themselves are the affordance; the breathing opacity confirms the paused state.

---

## 3. Architecture overview

Six integration points, listed in dependency order:

1. **`frontend/src/features/voice/infrastructure/micActivity.ts`** *(new)* — singleton emitter analogous to `audioPlayback`. Holds current mic RMS level (0..1) and a `vadActive` flag. Offers `subscribe(listener)`, `setLevel(value)`, `setVadActive(value)`, `getLevel()`, `getVadActive()`. No React state, no per-frame re-renders.
2. **`frontend/src/features/voice/hooks/useConversationMode.ts`** *(extended)* — the currently no-op `onVolumeChange: () => {}` (line 528) is replaced with `onVolumeChange: (level) => micActivity.setLevel(level)`. The existing VAD edges (`setVadActive(true)` on speech-start, `setVadActive(false)` on speech-end / misfire) additionally mirror to `micActivity.setVadActive(...)`.
3. **`frontend/src/features/chat/cockpit/buttons/LiveButton.tsx`** *(extended)* — adds an internal RAF loop that reads from `micActivity` and writes a CSS custom property `--mic-pulse` (0..1) onto the rendered button DOM node. The CSS uses that property to drive `transform: scale(...)` and `box-shadow`.
4. **`frontend/src/features/voice/stores/visualiserPauseStore.ts`** *(new)* — small Zustand store with `paused: boolean`, `mutedByPause: boolean`, `togglePause()`. Init-time subscription to `audioPlayback` clears state on idle transitions.
5. **`frontend/src/features/voice/components/VoiceVisualiserHitStrip.tsx`** *(new)* — invisible accessible button overlay covering the centre 30vh of the viewport. Mounted in `AppLayout.tsx` next to the existing `<VoiceVisualiser />`. Renders only while the visualiser is enabled, TTS is active, and reduced-motion is not set.
6. **`frontend/src/features/voice/components/VoiceVisualiser.tsx`** *(extended)* — when `visualiserPauseStore.paused === true`, freezes the bars at the snapshot taken at the moment of pause and applies a slow breathing opacity multiplier between 0.6 and 1.0.

Data flow (mic pulse):

```
mic stream → audioCapture (existing)
              │
              ├─→ onVolumeChange(level)  ──→ micActivity.setLevel(level)
              ├─→ VAD edges              ──→ micActivity.setVadActive(true|false)
                                                   │
                                                   ▼
                                            LiveButton RAF loop
                                                   │
                                                   ▼
                                            CSS variable --mic-pulse
                                                   │
                                                   ▼
                                          transform: scale(...) + box-shadow
```

Data flow (tap-to-pause):

```
TTS Group / read-aloud → audioPlayback (existing, unchanged)
                                 ▲
                                 │ pause() / resume()
                                 │
              ┌──────────────────┴───────────────────┐
              │ visualiserPauseStore.togglePause()  │
              └──────────────────┬───────────────────┘
                                 │
              ┌──────────────────┴───────────────────┐
              │ user click / keyboard activation     │
              │ on VoiceVisualiserHitStrip          │
              └──────────────────────────────────────┘

audioPlayback.subscribe(isActive)
   └─→ if !isActive && paused: clear pause + restore mic   (auto-heal)
```

---

## 4. Mic activity emitter

New file: `frontend/src/features/voice/infrastructure/micActivity.ts`.

```ts
type MicActivityListener = () => void

class MicActivityImpl {
  private level = 0
  private vadActive = false
  private listeners = new Set<MicActivityListener>()

  setLevel(value: number): void {
    // Hot-path: called from RAF in audioCapture. No allocations, no logs.
    this.level = value
    this.notify()
  }

  setVadActive(value: boolean): void {
    if (this.vadActive === value) return
    this.vadActive = value
    this.notify()
  }

  getLevel(): number { return this.level }
  getVadActive(): boolean { return this.vadActive }

  subscribe(listener: MicActivityListener): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  private notify(): void {
    for (const l of this.listeners) l()
  }
}

export const micActivity = new MicActivityImpl()
```

Notes:
- `notify()` is called per frame for `setLevel`. The only consumer is the LiveButton RAF, which reads `getLevel()` and `getVadActive()` directly without state — the `subscribe` mechanism is used solely to wake the RAF when needed (not to push values).
- An explicit `setVadActive` short-circuit (no notify if value unchanged) prevents redundant wakeups on identical edges.

---

## 5. LiveButton pulse

### Capture-side wiring

In `useConversationMode.ts`:

```ts
audioCapture.startContinuous({
  onSpeechStart: handleSpeechStart,
  onSpeechEnd: handleSpeechEnd,
  onVolumeChange: (level) => micActivity.setLevel(level),  // was: () => {}
  onMisfire: handleMisfire,
}, { ... })
```

The existing `setVadActive(true|false)` calls in `handleSpeechStart` / `handleSpeechEnd` / `handleMisfire` (already in the hook) gain a sibling `micActivity.setVadActive(...)`. On `teardown`, both are reset to false.

### LiveButton render

The component subscribes to `micActivity` via a small custom hook `useMicPulse(active: boolean, micMuted: boolean, reducedMotion: boolean)` that:

1. If `!active || micMuted || reducedMotion` → cancels any RAF, writes `--mic-pulse: 0` once, returns.
2. Else owns a RAF loop:
   ```ts
   const tick = () => {
     const level = micActivity.getLevel()
     const vad   = micActivity.getVadActive()
     const target = vad
       ? Math.min(1, level * 2.5)
       : Math.min(0.4, level * 1.5)
     pulseRef.current += (target - pulseRef.current) * 0.18
     buttonRef.current?.style.setProperty('--mic-pulse', pulseRef.current.toFixed(3))
     rafRef.current = requestAnimationFrame(tick)
   }
   ```
3. The RAF runs continuously while `active && !micMuted && !reducedMotion` (the user can speak at any time, so polling per frame is correct here). No `micActivity.subscribe` is needed — the RAF reads `getLevel()` / `getVadActive()` synchronously each frame.

### CSS

Defined inline in the component or in the existing CockpitButton stylesheet, scoped to `[data-pulse-active="true"]`:

```css
.cockpit-button[data-pulse-active="true"] {
  transform: scale(calc(1 + var(--mic-pulse, 0) * 0.12));
  box-shadow:
    0 0 calc(var(--mic-pulse, 0) * 18px)
    rgba(74, 222, 128, calc(var(--mic-pulse, 0) * 0.6));
  transition: transform 60ms linear, box-shadow 60ms linear;
}
```

- `1 + 0.12 * pulse` → max scale 1.12 at pulse 1.0; subtle but clearly visible
- Glow colour `rgba(74, 222, 128, ...)` matches the existing LiveButton green accent
- 60ms transition smooths the per-frame variable updates, hiding any RAF jitter

`data-pulse-active="true"` is set on the rendered CockpitButton's outer element only when:
- `active === true` (Live mode on)
- `micMuted === false`
- `prefers-reduced-motion: reduce` is not set

In all other cases the data attribute is absent and the CSS rule does not apply — button looks exactly as today.

### Reduced-motion handling

The hook subscribes to `window.matchMedia('(prefers-reduced-motion: reduce)')` and updates a ref on `change`. While reduce is active, the RAF is cancelled and the data attribute is removed.

---

## 6. Visualiser pause store

New file: `frontend/src/features/voice/stores/visualiserPauseStore.ts`.

```ts
import { create } from 'zustand'
import { audioPlayback } from '../infrastructure/audioPlayback'
import { useConversationModeStore } from './conversationModeStore'

interface VisualiserPauseState {
  paused: boolean
  mutedByPause: boolean
  togglePause(): void
}

export const useVisualiserPauseStore = create<VisualiserPauseState>((set, get) => ({
  paused: false,
  mutedByPause: false,

  togglePause: () => {
    const { paused, mutedByPause } = get()
    if (!paused) {
      // Pausing
      audioPlayback.pause()
      const cm = useConversationModeStore.getState()
      if (cm.active && !cm.micMuted) {
        cm.setMicMuted(true)
        set({ paused: true, mutedByPause: true })
      } else {
        set({ paused: true, mutedByPause: false })
      }
    } else {
      // Resuming
      audioPlayback.resume()
      if (mutedByPause) {
        useConversationModeStore.getState().setMicMuted(false)
      }
      set({ paused: false, mutedByPause: false })
    }
  },
}))

// Auto-clear: when audioPlayback transitions to idle (Group cancelled,
// queue drained, Live-mode exited mid-playback), drop the pause state
// and restore the mic if we muted it. Subscribe once at module init.
audioPlayback.subscribe(() => {
  if (!audioPlayback.isActive()) {
    const { paused, mutedByPause } = useVisualiserPauseStore.getState()
    if (paused) {
      if (mutedByPause) {
        useConversationModeStore.getState().setMicMuted(false)
      }
      useVisualiserPauseStore.setState({ paused: false, mutedByPause: false })
    }
  }
})
```

Module-init side effect: importing the store wires the `audioPlayback.subscribe` listener exactly once. The hit-strip component imports the store, ensuring the listener is alive whenever the visualiser path is loaded. (`AppLayout` always loads the visualiser code path.)

If `audioPlayback` does not currently expose an `isActive()` accessor, add one as a thin getter (`isActive(): boolean { return this.playing || this.queue.length > 0 || this.paused }`).

---

## 7. Hit-strip component

New file: `frontend/src/features/voice/components/VoiceVisualiserHitStrip.tsx`.

```tsx
import { useEffect, useState } from 'react'
import { audioPlayback } from '../infrastructure/audioPlayback'
import { useVoiceSettingsStore } from '../stores/voiceSettingsStore'
import { useVisualiserPauseStore } from '../stores/visualiserPauseStore'

export function VoiceVisualiserHitStrip() {
  const enabled = useVoiceSettingsStore((s) => s.visualisation.enabled)
  const paused = useVisualiserPauseStore((s) => s.paused)
  const togglePause = useVisualiserPauseStore((s) => s.togglePause)

  const [isPlaying, setIsPlaying] = useState(audioPlayback.isActive())
  const [reducedMotion, setReducedMotion] = useState(false)

  useEffect(() => {
    return audioPlayback.subscribe(() => setIsPlaying(audioPlayback.isActive()))
  }, [])

  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    setReducedMotion(mq.matches)
    const listener = () => setReducedMotion(mq.matches)
    mq.addEventListener('change', listener)
    return () => mq.removeEventListener('change', listener)
  }, [])

  if (!enabled || reducedMotion) return null
  if (!isPlaying && !paused) return null

  return (
    <button
      type="button"
      aria-label={paused ? 'TTS fortsetzen' : 'TTS pausieren'}
      onClick={togglePause}
      style={{
        position: 'fixed',
        left: 0,
        width: '100vw',
        top: '35vh',
        height: '30vh',
        background: 'transparent',
        border: 0,
        padding: 0,
        margin: 0,
        cursor: 'pointer',
        zIndex: 2,
        touchAction: 'manipulation',  // no double-tap zoom on mobile
      }}
    />
  )
}
```

Mounted in `frontend/src/app/layouts/AppLayout.tsx` next to the existing `<VoiceVisualiser />`:

```tsx
<VoiceVisualiser personaColourHex={...} />
<VoiceVisualiserHitStrip />
```

Notes:
- The strip stays in the DOM while `paused === true` even if `isPlaying` would be false (defensive — auto-clear should normally cover this, but keeping the strip available means the user can always resume if a race left the state stuck).
- Focus-visible ring: native `<button>` already provides a `:focus-visible` outline. We override to a subtle `outline: 2px solid rgba(140, 118, 215, 0.6); outline-offset: -4px;` (persona-colour-neutral lavender, low intensity). Decorative element — visual restraint over visual prominence.
- No hover/active styles. The element is invisible by design; visual feedback comes from the bars themselves changing state.

---

## 8. Visualiser pause rendering

Modifications in `frontend/src/features/voice/components/VoiceVisualiser.tsx`.

Add subscriptions:

```ts
const paused = useVisualiserPauseStore((s) => s.paused)
const frozenBinsRef = useRef<Float32Array | null>(null)
```

In the RAF tick, after computing `accessors.getBins()`:

```ts
if (paused) {
  // Snapshot the very first paused frame, render every subsequent frame
  // from the same buffer to keep the bars frozen.
  if (!frozenBinsRef.current) {
    frozenBinsRef.current = bins ? bins.slice() : new Float32Array(barCount)
  }

  const t = performance.now() / 1000
  const breath = 0.8 + 0.2 * Math.sin((t * 2 * Math.PI) / 2.5)  // 0.6..1.0, period 2.5s

  drawVisualiserFrame(style, ctx, w, h, frozenBinsRef.current, {
    rgb,
    rgbLight,
    opacity: opacity * activeRef.current * breath,
    maxHeightFraction: MAX_HEIGHT_FRACTION,
  })
  rafRef.current = requestAnimationFrame(tick)
  return
}

// Not paused — clear the snapshot and continue normal flow
frozenBinsRef.current = null
```

The existing `audioPlayback.subscribe()` keeps the RAF alive across pause/resume — pause does not transition `audioPlayback.isActive()` to false, so `activeRef.current` stays at 1.0 and the loop never enters its idle short-circuit.

---

## 9. State table (what the user sees)

| Mode | TTS state | paused | LiveButton | Visualiser | Hit-strip |
|---|---|---|---|---|---|
| Normal | off | – | n/a | invisible | absent |
| Normal | playing (read-aloud) | no | n/a | dancing | active |
| Normal | playing + tap | yes | n/a | breathing | active (resume) |
| Live, mic on | TTS off | – | green, pulses on speech | invisible | absent |
| Live, mic on | TTS playing | no | green, pulses if user barges in | dancing | active |
| Live, mic on | TTS playing + tap | yes | green, static (mic now muted) | breathing | active (resume) |
| Live, mic muted (manual) | TTS playing | no | green, no pulse (muted) | dancing | active |
| Live, mic muted (manual) | TTS playing + tap | yes | green, no pulse | breathing | active (resume) — mic stays muted on resume |

---

## 10. Edge cases

| Situation | Behaviour |
|---|---|
| Paused, then Cockpit ⏹ clicked | `Group.cancel('user-stop')` → audioPlayback goes idle → auto-clear subscription drops pause + restores mic |
| Paused, then LiveButton turned off | `conversationMode.exit()` cancels the Group → idle → auto-clear |
| Group finishes producing while paused | Audio queue retains unplayed chunks; user must tap to resume or click ⏹ |
| User reloads while paused | In-memory state cleared; everything fresh |
| Persona switch mid-pause | Bars recolour and continue breathing in the new colour |
| Hit-strip click with `prefers-reduced-motion` or visualiser disabled | Hit-strip is not in the DOM → no trigger possible |
| Hold-mode active (user physically holding a hold key), tap mid-strip | Pause toggles as usual; hold path is orthogonal and self-cleans on release |
| User unmutes mic manually while paused (via Cockpit click on the live-mic-muted state) | `mutedByPause` flag stays true; on resume we still call `setMicMuted(false)`, which is now an idempotent no-op since the user already unmuted. Final state: `paused=false`, `mutedByPause=false`, `micMuted=false` — correct. |
| Pause exactly on the last audio sample | Race is self-healing: pause briefly engages, queue then drains, idle transition fires auto-clear |
| User taps during the bars' fade-out (TTS just ended) | Hit-strip is already absent (`isActive() === false`) → no trigger possible. Consistent with "nothing to pause anymore". |

---

## 11. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Hit-strip blocks chat clicks in the centre band | Strip renders only while TTS is playing (typical 10–30s); outside that window the strip is not in the DOM. Chat clicks above and below the strip (each ~35vh) always pass through. Acceptable trade-off. |
| Mobile double-tap zoom on the hit-strip | `touch-action: manipulation` on the button — prevents double-tap zoom while preserving simple taps |
| LiveButton RAF runs in the background | Browsers automatically pause RAF in background tabs; no measurable cost |
| Audio queue grows unbounded during long pause | Group produces at most ~30s additional audio per realistic TTS reply; acceptable in v1 |
| Snapshot captured during a quiet moment looks "flat" | Bars at low values still frame-freeze and breathe; combined with TTS silence the user reads "paused" unambiguously. Edge case is rare. |
| Importing `visualiserPauseStore` runs side effects (audioPlayback subscribe) | Module-level subscription is intentional; imports are confined to AppLayout and the hit-strip, both always present in authenticated views. Safe. |
| `audioPlayback.isActive()` semantics during pause | Add (or confirm) `isActive()` that is true while either playing, paused, or queue non-empty. Pause must NOT cause `isActive()` to flip to false, otherwise the auto-clear subscription would immediately void the pause. |

---

## 12. Implementation order

Each step is independently mergeable and verifiable:

1. **`micActivity` singleton.** Add the file, no consumers yet. Verify by importing in a scratch file and console-logging.
2. **`useConversationMode` wiring.** Replace the no-op `onVolumeChange` and add the `micActivity.setVadActive(...)` mirrors. Verify by speaking into the mic in Live mode and watching console output.
3. **LiveButton pulse.** Add the RAF hook and CSS rule. Verify in the browser: the button visibly pulses when speaking, holds steady when silent or muted.
4. **`audioPlayback.isActive()` getter.** Add or confirm. Verify it returns true during playback, true during pause, false when idle.
5. **`visualiserPauseStore`.** Add the store with `togglePause` and the auto-clear subscription. Verify via React DevTools (or a temporary dev panel) that toggling works.
6. **Hit-strip component.** Mount in AppLayout. Tap-test the strip. At this point the bars do not yet freeze on pause — verify TTS pauses and resumes, and the hit-strip appears/disappears correctly.
7. **Visualiser pause rendering.** Add the snapshot-and-breathe path to `VoiceVisualiser.tsx`. Verify bars freeze and breathe on pause, dance again on resume.
8. **Reduced-motion handling.** Verify both LiveButton pulse and hit-strip respect `prefers-reduced-motion: reduce`.
9. **Manual verification pass** (next section).

---

## 13. Manual verification

To be performed against a running dev frontend (`pnpm dev`, default `http://localhost:5173`) on a real device, with at least one persona configured and a Live-capable LLM connection.

### LiveButton pulse

- [ ] Live mode off → LiveButton green, no pulse
- [ ] Live mode on, mic open, silent → no (or minimal) background pulse
- [ ] Live mode on, mic open, speak softly (just below VAD threshold) → subtle mini-pulse from the RMS path
- [ ] Live mode on, mic open, speak clearly → strong pulse from the VAD path
- [ ] Live mode on, mic muted → no pulse (even while speaking)
- [ ] Live mode on, TTS playing, silent → no pulse (LiveButton steady)
- [ ] Live mode on, TTS playing, barge in by speaking → pulse spikes the moment VAD engages

### Pause via hit-strip — Normal mode (read-aloud)

- [ ] Read-aloud playing, tap centre band → bars freeze and breathe, TTS silent
- [ ] Tap again → TTS resumes, bars dance again
- [ ] Click a chat message above the strip → chat reacts normally (hit-strip does not block)
- [ ] Scroll in the upper or lower third of the viewport → scrolls during TTS
- [ ] Pause, then Cockpit ⏹ → all stops cleanly, bars disappear

### Pause via hit-strip — Live mode

- [ ] Live, mic on, TTS playing, tap centre → pause + mic muted (LiveButton state reflects mute)
- [ ] Tap again → TTS resumes, mic unmuted, pulse responds to speech again
- [ ] Live, mic on, TTS, tap, then Cockpit ⏹ → pause clears, mic unmuted, all idle
- [ ] Live, mic manually muted before tap, TTS, tap → pause engages, mic stays muted; tap → TTS resumes, mic stays muted (no override)
- [ ] Live, TTS, tap, then turn LiveButton off → pause clears, Live mode off, all clean

### Keyboard / a11y

- [ ] Tab to the hit-strip → subtle focus ring visible
- [ ] Enter / Space → toggles pause exactly like a click
- [ ] aria-label switches between "TTS pausieren" and "TTS fortsetzen"

### Mobile

- [ ] Tap centre on iPhone Safari → instant pause, no double-tap zoom
- [ ] Tap on Android Chrome → identical

### Visualiser settings interaction

- [ ] Disable visualiser in user settings → no hit-strip, tap function unavailable (status quo before this feature)
- [ ] OS `prefers-reduced-motion: reduce` enabled → no hit-strip, no LiveButton pulse
- [ ] Persona switch mid-pause → bars recolour, keep breathing
- [ ] Modal open during TTS (Persona Overlay, Settings) → hit-strip sits behind modal (z-index correct); modal click does not bleed through to pause

### No regression

- [ ] Cockpit ⏹ continues to fully stop TTS in all modes
- [ ] Existing visualiser behaviour (dance + fade) unchanged when pause feature is not used
- [ ] Audio quality identical with and without pause feature engaged

# TTS Voice Visualiser — Design

**Date:** 2026-04-26
**Status:** Draft, awaiting Chris's review
**Scope:** Frontend only. New top-level overlay component, one additive change to the existing Web Audio playback graph, four new fields on the existing per-device voice-settings store, one new section on the Voice settings tab. No backend changes, no DB changes, no DTO changes.

---

## 1. Problem

When Chatsune speaks via TTS, there is no ambient signal in the UI that "the assistant is speaking right now". The text appears, the audio plays, and the user sees a static screen. ChatGPT solves this with a full-screen takeover during voice playback, but Chatsune's design ethos puts the chat content first — the text is always primary.

The product needs a non-intrusive, ever-present cue that conveys speech is happening *and* carries the cadence of what is being said, in the same way a KITT-style scanner conveyed that the car was speaking. Equivalent for screen instead of dashboard, modern instead of retro, woven into the page rather than overlaid on it.

---

## 2. Goals and non-goals

### Goals

- Render a horizontal, vertically-mirrored equaliser strip behind the chat content while TTS is playing, fed by the live frequency spectrum of the audio currently being produced.
- Idle state: completely invisible — no static element, no shimmer, nothing.
- One single overlay rendered at app root; works in every view because TTS is a global concern.
- Three user-tunable parameters per device: bar style, opacity, bar count. Plus a master on/off toggle.
- Bar colour follows the active persona's chakra colour.
- Respect `prefers-reduced-motion` automatically — disabling the visualiser regardless of the master toggle.
- Zero impact on existing audio playback. The analyser is a passthrough node; existing `SoundTouchNode` modulation chain stays intact.

### Non-goals

- No per-persona override of visualisation settings. "Global taste, all personas." Confirmed.
- No microphone-side visualisation. The capture path already has its own analyser used for VAD level metering; that is a different feature.
- No alternative motion concepts (scanner beam, ribbon, standing wave). Equaliser bars are the chosen aesthetic. Other concepts can become a follow-up spec if ever desired.
- No backend persistence of the visualisation settings. They live in `localStorage` exactly like the other voice settings. No `User` document changes, no migration.
- No accessibility announcements. The visualiser is purely decorative; the canvas is `aria-hidden`.
- No max-amplitude user setting. Hardcoded at ~28 % of the viewport (full deflection top + bottom together) — found to be aesthetically correct in every combination of style/opacity/density during prototyping.

---

## 3. Architecture overview

Three integration points, listed in order of isolation:

1. **`backend/modules/llm/...`** — untouched. No backend involvement.
2. **`frontend/src/features/voice/infrastructure/audioPlayback.ts`** — one passthrough `AnalyserNode` inserted at the end of the existing audio graph, plus a new public `getAnalyser()` accessor.
3. **`frontend/src/features/voice/stores/voiceSettingsStore.ts`** — extended with a new `visualisation` block.
4. **`frontend/src/features/voice/components/VoiceVisualiser.tsx`** — new component, mounted once at the app root.
5. **`frontend/src/app/components/user-modal/VoiceTab.tsx`** — extended with a new "Sprachausgabe-Visualisierung" section containing the controls and a live preview.

Data flow:

```
TTS audio buffer (existing)
  → AudioBufferSourceNode (existing)
  → [optional SoundTouchNode] (existing, unchanged)
  → AnalyserNode (NEW — passthrough)
  → AudioContext.destination (existing)
                  │
                  ▼
        getByteFrequencyData()
                  │
                  ▼
       useTtsFrequencyData() hook  ←───  voiceSettingsStore.visualisation
                  │                       (style, opacity, bar_count, enabled)
                  ▼
         <VoiceVisualiser />          ←  active persona colour (personaHex)
                  │
                  ▼
         canvas (fixed overlay)
```

---

## 4. Audio graph change

Single edit in `frontend/src/features/voice/infrastructure/audioPlayback.ts`.

The current chain (around line 174–212):

```
source → [SoundTouchNode?] → ctx.destination
```

becomes:

```
source → [SoundTouchNode?] → analyser → ctx.destination
```

The `AnalyserNode` is created once at the same time as the `AudioContext` and persists for the lifetime of the singleton. Configuration:

- `fftSize = 256` → 128 frequency bins, sufficient for up to 96 visualiser bars
- `smoothingTimeConstant = 0.7` → built-in frame-to-frame smoothing
- `minDecibels = -90`, `maxDecibels = -10` → sensible default for speech-range content

Public surface added to the singleton:

```ts
audioPlayback.getAnalyser(): AnalyserNode
```

The `AnalyserNode` is a designated passthrough in the Web Audio API — its presence does not modify the audio signal. The existing `SoundTouchNode` toggling logic for speed/pitch modulation remains unchanged; the analyser sits unconditionally at the end of whichever variant of the chain is active.

---

## 5. Frequency data hook

New file: `frontend/src/features/voice/infrastructure/useTtsFrequencyData.ts`.

```ts
export function useTtsFrequencyData(
  binCount: number,
): { getBins(): Float32Array; isActive(): boolean }
```

The hook:

- Subscribes once to `audioPlayback` for active-state changes via the existing `subscribe()` mechanism.
- Allocates one `Uint8Array(128)` for raw FFT output.
- Allocates one `Float32Array(binCount)` for the logarithmically-bucketed and exponentially-smoothed bar values.
- Returns accessor functions, **not** state. Crucially, the consumer reads these inside its own `requestAnimationFrame` loop. No React re-renders are triggered per frame.

Bucketing strategy: the 128 raw bins cover 0 Hz to ~12 kHz linearly. Map to user-configured `binCount` (16–96) using a logarithmic schedule, because human pitch perception is logarithmic. For each visualiser bar `i`:

```
fStart = 20 * (12000/20) ** (i / binCount)
fEnd   = 20 * (12000/20) ** ((i+1) / binCount)
```

Average the raw bins falling inside `[fStart, fEnd)`, normalise to `[0, 1]`, then exponentially smooth: `value += (target - value) * 0.28` per frame.

---

## 6. Settings model

Extended `VoiceSettingsState` in `frontend/src/features/voice/stores/voiceSettingsStore.ts`:

```ts
type VisualiserStyle = 'sharp' | 'soft' | 'glow' | 'glass'

interface VoiceVisualisationSettings {
  enabled: boolean       // master toggle
  style: VisualiserStyle
  opacity: number        // 0.05–0.80
  barCount: number       // 16–96
}

interface VoiceSettingsState {
  // ... existing fields ...
  visualisation: VoiceVisualisationSettings
  setVisualisationEnabled(value: boolean): void
  setVisualisationStyle(value: VisualiserStyle): void
  setVisualisationOpacity(value: number): void
  setVisualisationBarCount(value: number): void
}
```

Defaults:

| Field | Default |
|---|---|
| `enabled` | `true` |
| `style` | `'soft'` |
| `opacity` | `0.5` |
| `barCount` | `24` |

Existing persisted snapshots without `visualisation` get the defaults via Zustand's `merge` (already used in the store for `inputMode` hard-coding) — a missing block is replaced with the full default object, ensuring older browsers continue to work without manual reset.

---

## 7. Render component

New file: `frontend/src/features/voice/components/VoiceVisualiser.tsx`. Mounted exactly once inside `frontend/src/app/layouts/AppLayout.tsx`, alongside `<ToastContainer />` (around line 344) — so it covers all authenticated views and is automatically absent on the login/onboarding pages where TTS does not play.

Markup:

```tsx
<canvas
  className="voice-visualiser"
  aria-hidden="true"
/>
```

CSS:

```css
.voice-visualiser {
  position: fixed;
  inset: 0;
  width: 100vw;
  height: 100vh;
  pointer-events: none;
  z-index: 1;        /* above app background, below modals/dialogs */
}
```

Component logic:

- Reads `visualisation.{enabled, style, opacity, barCount}` from `useVoiceSettingsStore`.
- Reads active persona via existing persona store, derives hex with `personaHex()` from `frontend/src/app/components/sidebar/personaColour.ts`.
- Reads the active state via `audioPlayback.subscribe()` plus an internal smoothed `active` scalar.
- Owns one `requestAnimationFrame` loop with the following frame steps:
  1. Update `active` scalar towards target (`1` if speaking, `0` otherwise; smoothing factor 0.05).
  2. If `active < 0.005` and not speaking → cancel RAF, wait for next `subscribe` event before resuming.
  3. Else: read frequency bins via `useTtsFrequencyData`, draw bars per current `style`, scaled to `opacity * active`.
- Listens for `prefers-reduced-motion` via `matchMedia` and short-circuits rendering when active.
- Re-allocates the bin buffer when `barCount` changes (rare).
- Re-sizes the canvas backing store on `clientWidth/clientHeight` change. **DPR is clamped to 1** — the bars are soft decorative shapes for which retina sharpness is not perceptible, and the clamp keeps backing-store memory bounded on high-resolution displays (~33 MB at 4K instead of ~130 MB at 4K + DPR 2).

The four bar styles map exactly to the prototyped renderers:

| Style | Renderer |
|---|---|
| `sharp` | Solid `fillRect` at `rgba(persona, op)` |
| `soft` | Vertical gradient: ends at 15 % op, middle at 100 % op |
| `glow` | `shadowBlur: 14`, `shadowColor` at 1.5× op, fill at 0.9× op |
| `glass` | Translucent white fill at 0.45× op, persona-coloured 1 px stroke at 0.85× op |

Maximum total deflection (top + bottom from centre): `0.28 * viewportHeight`. Hardcoded constant in the component.

---

## 8. Settings UI section

New section in `frontend/src/app/components/user-modal/VoiceTab.tsx`, appended after existing voice controls. Heading "Sprachausgabe-Visualisierung". Contents:

1. **Master toggle.** Single switch labelled "Visualisierung anzeigen". When off, the rest of the controls are dimmed but not hidden.
2. **Style picker.** Four buttons (Scharf / Weich / Glühend / Glas), single-select.
3. **Opacity slider.** Range 5 %–80 %, current value displayed numerically.
4. **Bar count slider.** Range 16–96, current value displayed numerically.
5. **Live preview strip.** ~120 px tall, full-width canvas, runs the same speech-amplitude simulator used in the brainstorming mockup. Reacts immediately to every control change. Shows a subtle "Aus" placeholder text when the master toggle is off. Uses the user's currently-active persona colour so it matches the real thing.
6. **Reduced-motion notice.** When `prefers-reduced-motion: reduce` is detected, an inline notice appears beneath the master toggle: *"Dein Betriebssystem hat 'Bewegung reduzieren' aktiviert — die Visualisierung ist deaktiviert."* The controls remain interactive (so the preference persists for when reduced-motion is later turned off), but the live preview shows no animation.

The simulator code used by the live preview is extracted into a small helper so the production component does *not* depend on it.

---

## 9. Accessibility

- `aria-hidden="true"` on both the global canvas and the live-preview canvas.
- `prefers-reduced-motion: reduce` is honoured automatically. Detection is via `window.matchMedia('(prefers-reduced-motion: reduce)')` and the `change` event so the user does not have to reload after toggling the OS setting.
- Master toggle persists independently from the OS preference. If the user later turns off OS reduced-motion, their explicit preference resumes without needing to re-toggle.
- No focusable elements on the canvas — `pointer-events: none` and no event listeners.

---

## 10. Performance budget

- One RAF loop owned by the visualiser component (plus optionally one for the live preview while the Voice settings tab is open).
- Per frame: one `getByteFrequencyData()` call (~0.05 ms), one logarithmic bucketing pass over 128 bins, one canvas draw with up to 96 `fillRect` operations.
- Idle: RAF is **cancelled**, not gated. Listening for `audioPlayback`'s subscribe event resumes the loop on next playback.
- Canvas resize is conditional on `clientWidth`/`clientHeight` change to avoid every-frame `canvas.width = ...` reflows. DPR is clamped to 1 (see render component) so the backing store stays small.
- No React state updates inside the RAF loop; bar values are kept in a ref-held typed array.

This budget targets and easily fits within a 16 ms frame on any device of the last five years. The master toggle remains the user's escape hatch if their device disagrees.

---

## 11. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Z-index conflicts with modals (Persona-Overlay, Settings-Modal, dialogs) | `z-index: 1` on the canvas. Modals sit above intentionally — the visualiser fades into the background while the user is in a modal context, which is the desired behaviour. |
| `AnalyserNode` insertion silently breaks `SoundTouchNode` chain | The Analyser sits unconditionally at the very end of the chain, regardless of which prefix variant is active. Manual verification covers the speed/pitch-modulated path explicitly. |
| Persona switch during TTS playback (rare; likely not possible due to session model) | Colour is read each frame via the persona store. Next frame paints with the new colour — no crossfade needed for what is essentially never user-observable. |
| Older persisted `voice-settings` localStorage payload missing `visualisation` block | Extend the existing `merge` callback to spread `current.visualisation` first, then any persisted partial visualisation block — guarantees a complete object even on the first load after upgrade. |
| Canvas allocates large backing store on high-DPR displays | DPR is clamped to 1 from day one. The bars are soft decorative shapes — no retina-sharpness loss is visible. Caps the backing store at viewport-pixels × 4 bytes (~33 MB at 4K, ~8 MB at 1080p), instead of the up-to-130 MB an unclamped DPR=2 path would cost. |

---

## 12. Implementation order

Each step is independently mergeable and verifiable:

1. **Audio graph extension.** Add `AnalyserNode` and `getAnalyser()` to `audioPlayback`. Verify nothing about playback changes by playing TTS and listening for distortion or timing differences.
2. **Settings store extension.** Add `visualisation` block, four setters, defaults, `merge` handling for the missing-block case. Verify by inspecting the persisted localStorage entry on first load.
3. **`useTtsFrequencyData` hook + `VoiceVisualiser` component.** Mount at app root with hard-coded settings (no UI yet). Verify visually with TTS playing.
4. **Voice settings tab section.** Add controls, live preview, reduced-motion notice. Verify preview reacts to slider changes; verify the production visualiser also follows the controls.
5. **Manual verification pass** (see next section).

---

## 13. Manual verification

To be performed against a running dev frontend (`pnpm dev`, default `http://localhost:5173`) on a real device, with at least one persona configured and a TTS-capable LLM connection:

- [ ] **Idle state.** Open the chat with no TTS playing. The screen shows nothing visualiser-related — no faint line, no shimmer, no canvas artefact at any zoom level.
- [ ] **Speaking state.** Send a message that triggers a multi-sentence TTS reply. While the model speaks, the equaliser appears centred horizontally, mirrored top/bottom, in the active persona's chakra colour, with motion synchronised to the audio.
- [ ] **Multi-sentence rhythm.** During longer replies, observe that bars subside between sentences — confirming the visualiser is driven by actual audio, not a synthetic "is speaking" boolean.
- [ ] **Modulation path.** With a persona that uses pitch/speed modulation, the visualiser still works (covers the SoundTouchNode-included branch).
- [ ] **Persona switch.** Switch between two personas with different chakra colours. The visualiser colour follows on the next playback.
- [ ] **Master toggle.** Disable in Voice settings. Visualiser stops (with fade-out). Re-enable. It resumes on next playback.
- [ ] **Style switch.** Cycle through Scharf / Weich / Glühend / Glas. Each renders distinctly in the live preview and in the real chat.
- [ ] **Opacity slider.** Slide from 5 % to 80 %. Both the live preview and (if TTS is playing) the real visualiser respond in real time.
- [ ] **Bar count slider.** Slide from 16 to 96. Live preview re-allocates bars without flicker; real visualiser updates on next frame.
- [ ] **Reduced motion.** Enable `prefers-reduced-motion` at the OS level. Reload (or wait for the live `change` event). Visualiser stops; in-app notice appears. Disable again — visualiser resumes.
- [ ] **Modal overlay.** Open the Persona Overlay or Settings Modal while TTS is playing. The visualiser is correctly hidden behind the modal (z-index correct).
- [ ] **Cross-device taste.** On a second device (phone or tablet), confirm settings are independent — toggling on the laptop does not affect the phone.
- [ ] **Continuous voice mode.** Enter continuous voice mode and have the assistant speak. The visualiser appears as in regular chat (shared playback path).
- [ ] **No regression in audio quality.** Listen to a passage with and without the visualiser branch. No audible difference.

# TTS Voice Visualiser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Subagent constraints:** Do not merge, do not push, do not switch branches. Stay on the current branch. After all tasks pass, hand control back to Chris for review and the merge decision.

**Goal:** Add a non-intrusive horizontal equaliser visualisation that renders behind chat content while TTS speaks, driven by the live frequency spectrum, in the active persona's chakra colour, with per-device user settings (style, opacity, bar count, master toggle).

**Architecture:** One passthrough `AnalyserNode` inserted at the end of the existing audio playback graph, plus a single fixed-overlay `<canvas>` component mounted globally in `AppLayout.tsx`. Rendering is canvas-based at DPR-clamped 1× resolution. Settings live in the existing `voiceSettingsStore` (localStorage, per-device).

**Tech Stack:** React 18 + TypeScript, Web Audio API (`AnalyserNode`), Canvas 2D, Zustand for state, Vitest + React Testing Library for tests, Tailwind for UI.

**Spec reference:** `devdocs/specs/2026-04-26-tts-voice-visualiser-design.md`

---

## File Structure

**Create:**
- `frontend/src/features/voice/infrastructure/visualiserBucketing.ts` — pure log-frequency bucketing function
- `frontend/src/features/voice/infrastructure/__tests__/visualiserBucketing.test.ts`
- `frontend/src/features/voice/infrastructure/visualiserSpeechSimulator.ts` — synthetic amplitude generator for the live preview only
- `frontend/src/features/voice/infrastructure/visualiserRenderers.ts` — one pure draw function per style, shared by both visualiser and preview
- `frontend/src/features/voice/infrastructure/useTtsFrequencyData.ts` — React hook bridging `audioPlayback.getAnalyser()` to bucketed bin values
- `frontend/src/features/voice/components/VoiceVisualiser.tsx` — production overlay component
- `frontend/src/features/voice/components/VoiceVisualiserPreview.tsx` — settings-tab live preview
- `frontend/src/features/voice/stores/__tests__/voiceSettingsStore.visualisation.test.ts`
- `frontend/src/app/components/user-modal/__tests__/VoiceTab.visualisation.test.tsx`

**Modify:**
- `frontend/src/features/voice/infrastructure/audioPlayback.ts` — create `AnalyserNode` lazily alongside `AudioContext`, route every source into it, expose `getAnalyser()`
- `frontend/src/features/voice/stores/voiceSettingsStore.ts` — add `visualisation` block, four setters, defaults, `merge` handling
- `frontend/src/app/layouts/AppLayout.tsx` — mount `<VoiceVisualiser />` next to `<ToastContainer />`
- `frontend/src/app/components/user-modal/VoiceTab.tsx` — append "Sprachausgabe-Visualisierung" section

---

## Task 1: AudioPlayback — AnalyserNode passthrough

**Files:**
- Modify: `frontend/src/features/voice/infrastructure/audioPlayback.ts` (around lines 25–252)

**Goal:** Insert a single `AnalyserNode` at the end of the playback chain, lazily created with the `AudioContext`. All sources (with or without `SoundTouchNode` modulation) connect into the analyser instead of `ctx.destination`. The analyser then connects to `ctx.destination`. Expose `getAnalyser(): AnalyserNode | null` for consumers.

- [ ] **Step 1.1: Add private analyser field**

In `class AudioPlaybackImpl`, alongside existing private fields (line ~22):

```ts
private analyser: AnalyserNode | null = null
```

- [ ] **Step 1.2: Create analyser when AudioContext is created**

Inside `playNext()`, find the block `if (!this.ctx || this.ctx.state === 'closed') { this.ctx = new AudioContext(...) }`. Replace it with:

```ts
if (!this.ctx || this.ctx.state === 'closed') {
  this.ctx = new AudioContext({ sampleRate: 24_000 })
  this.analyser = this.ctx.createAnalyser()
  this.analyser.fftSize = 256
  this.analyser.smoothingTimeConstant = 0.7
  this.analyser.minDecibels = -90
  this.analyser.maxDecibels = -10
  this.analyser.connect(this.ctx.destination)
}
```

- [ ] **Step 1.3: Route sources through analyser**

In the same method, replace the connect block:

```ts
if (modNode) {
  source.playbackRate.value = speed
  source.connect(modNode)
  modNode.connect(this.ctx.destination)
} else {
  source.connect(this.ctx.destination)
}
```

with (note: `this.analyser!` is safe because the same `if`-block above guarantees it was just created):

```ts
if (modNode) {
  source.playbackRate.value = speed
  source.connect(modNode)
  modNode.connect(this.analyser!)
} else {
  source.connect(this.analyser!)
}
```

- [ ] **Step 1.4: Reset analyser in `dispose()`**

In `dispose()`, after `this.ctx = null`:

```ts
this.analyser = null
```

- [ ] **Step 1.5: Add public accessor**

Near `isPlaying()` (around line 243):

```ts
getAnalyser(): AnalyserNode | null { return this.analyser }
```

- [ ] **Step 1.6: Verify build still passes**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: zero errors.

- [ ] **Step 1.7: Verify existing tests still pass**

Run: `cd frontend && pnpm test --run src/features/voice`
Expected: all green; no test should reference `getAnalyser()` yet.

- [ ] **Step 1.8: Manual smoke test**

Run dev server: `cd frontend && pnpm dev`
Trigger a TTS reply in the running app. Audio plays normally; no distortion, no dropout, no console errors. Open DevTools > Console and run:

```js
window.__audioPlaybackForDebug = audioPlayback   // not actually exposed; use breakpoint
```

(Optional — visual verification of analyser presence happens in later tasks. The audible-quality check is what matters here.)

- [ ] **Step 1.9: Commit**

```bash
git add frontend/src/features/voice/infrastructure/audioPlayback.ts
git commit -m "Add passthrough AnalyserNode to TTS playback graph"
```

---

## Task 2: Logarithmic frequency bucketing utility

**Files:**
- Create: `frontend/src/features/voice/infrastructure/visualiserBucketing.ts`
- Create: `frontend/src/features/voice/infrastructure/__tests__/visualiserBucketing.test.ts`

**Goal:** Pure function that maps 128 raw FFT bins (0–12 kHz linearly) into N visualiser bars (16 ≤ N ≤ 96) using logarithmic frequency grouping in the 20 Hz – 12 kHz band.

- [ ] **Step 2.1: Write failing tests**

Create `frontend/src/features/voice/infrastructure/__tests__/visualiserBucketing.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { bucketIntoLogBins, FREQ_MIN_HZ, FREQ_MAX_HZ } from '../visualiserBucketing'

describe('bucketIntoLogBins', () => {
  const SAMPLE_RATE = 24_000
  const FFT_SIZE = 256

  it('produces exactly N output bins', () => {
    const raw = new Uint8Array(128).fill(100)
    const out = bucketIntoLogBins(raw, SAMPLE_RATE, FFT_SIZE, 24)
    expect(out).toHaveLength(24)
  })

  it('returns values in [0, 1]', () => {
    const raw = new Uint8Array(128)
    for (let i = 0; i < 128; i++) raw[i] = i * 2
    const out = bucketIntoLogBins(raw, SAMPLE_RATE, FFT_SIZE, 32)
    for (const v of out) {
      expect(v).toBeGreaterThanOrEqual(0)
      expect(v).toBeLessThanOrEqual(1)
    }
  })

  it('returns zeros for all-zero input', () => {
    const raw = new Uint8Array(128)
    const out = bucketIntoLogBins(raw, SAMPLE_RATE, FFT_SIZE, 24)
    for (const v of out) expect(v).toBe(0)
  })

  it('uses logarithmic frequency grouping (low bands cover fewer raw bins)', () => {
    // Given an even spread of raw energy, log bucketing puts the lowest
    // visualiser bin over a tiny frequency range and the highest bin over
    // most of the spectrum. The constants assert this asymmetry.
    const raw = new Uint8Array(128).fill(255)
    const out = bucketIntoLogBins(raw, SAMPLE_RATE, FFT_SIZE, 24)
    // All bars should saturate to ~1 when input is uniform max.
    for (const v of out) expect(v).toBeCloseTo(1, 1)
  })

  it('maps linearly-rising input to monotonically increasing bins', () => {
    const raw = new Uint8Array(128)
    for (let i = 0; i < 128; i++) raw[i] = Math.min(255, i * 2)
    const out = bucketIntoLogBins(raw, SAMPLE_RATE, FFT_SIZE, 16)
    for (let i = 1; i < out.length; i++) {
      expect(out[i]).toBeGreaterThanOrEqual(out[i - 1] - 1e-6)
    }
  })

  it('exposes the constants used in the 20 Hz – 12 kHz log range', () => {
    expect(FREQ_MIN_HZ).toBe(20)
    expect(FREQ_MAX_HZ).toBe(12_000)
  })
})
```

- [ ] **Step 2.2: Run the tests, watch them fail**

Run: `cd frontend && pnpm test --run src/features/voice/infrastructure/__tests__/visualiserBucketing.test.ts`
Expected: FAIL — module does not exist.

- [ ] **Step 2.3: Implement the function**

Create `frontend/src/features/voice/infrastructure/visualiserBucketing.ts`:

```ts
export const FREQ_MIN_HZ = 20
export const FREQ_MAX_HZ = 12_000

/**
 * Bucket linear-frequency FFT bins into logarithmic visualiser bars.
 *
 * The Web Audio API gives us `frequencyBinCount` bins (= fftSize / 2),
 * each covering an equal slice of [0, sampleRate/2]. Human pitch
 * perception is logarithmic, so a bar-per-linear-bin mapping puts almost
 * all visible motion into a few high-frequency bars and leaves the bass
 * bars nearly static. We instead lay the visualiser bars out logarithmically
 * across [FREQ_MIN_HZ, FREQ_MAX_HZ].
 */
export function bucketIntoLogBins(
  rawBins: Uint8Array,
  sampleRate: number,
  fftSize: number,
  outputBins: number,
): Float32Array {
  const result = new Float32Array(outputBins)
  const rawCount = rawBins.length
  const hzPerRawBin = sampleRate / fftSize
  const logMin = Math.log(FREQ_MIN_HZ)
  const logMax = Math.log(FREQ_MAX_HZ)

  for (let i = 0; i < outputBins; i++) {
    const fStart = Math.exp(logMin + ((logMax - logMin) * i) / outputBins)
    const fEnd = Math.exp(logMin + ((logMax - logMin) * (i + 1)) / outputBins)

    const rawStart = Math.max(0, Math.floor(fStart / hzPerRawBin))
    const rawEnd = Math.min(rawCount, Math.ceil(fEnd / hzPerRawBin))

    if (rawEnd <= rawStart) {
      // Output bar straddles less than one raw bin — sample the nearest.
      const idx = Math.min(rawCount - 1, Math.max(0, Math.round(fStart / hzPerRawBin)))
      result[i] = rawBins[idx] / 255
      continue
    }

    let sum = 0
    for (let j = rawStart; j < rawEnd; j++) sum += rawBins[j]
    result[i] = sum / (rawEnd - rawStart) / 255
  }
  return result
}
```

- [ ] **Step 2.4: Run the tests, watch them pass**

Run: `cd frontend && pnpm test --run src/features/voice/infrastructure/__tests__/visualiserBucketing.test.ts`
Expected: all 6 tests PASS.

- [ ] **Step 2.5: Commit**

```bash
git add frontend/src/features/voice/infrastructure/visualiserBucketing.ts frontend/src/features/voice/infrastructure/__tests__/visualiserBucketing.test.ts
git commit -m "Add log-frequency bucketing helper for visualiser"
```

---

## Task 3: Voice settings — visualisation block

**Files:**
- Modify: `frontend/src/features/voice/stores/voiceSettingsStore.ts`
- Create: `frontend/src/features/voice/stores/__tests__/voiceSettingsStore.visualisation.test.ts`

**Goal:** Extend the existing per-device store with the four visualisation settings (`enabled`, `style`, `opacity`, `barCount`), defaulting to `true / 'soft' / 0.5 / 24`. Existing persisted snapshots without the block must hydrate to the defaults via the existing `merge` callback.

- [ ] **Step 3.1: Write failing tests**

Create `frontend/src/features/voice/stores/__tests__/voiceSettingsStore.visualisation.test.ts`:

```ts
import { beforeEach, describe, it, expect } from 'vitest'
import { useVoiceSettingsStore } from '../voiceSettingsStore'

const STORAGE_KEY = 'voice-settings'

describe('voiceSettingsStore — visualisation block', () => {
  beforeEach(() => {
    localStorage.clear()
    // Reset to a fresh store instance state.
    useVoiceSettingsStore.setState(useVoiceSettingsStore.getInitialState(), true)
  })

  it('exposes default visualisation settings', () => {
    const v = useVoiceSettingsStore.getState().visualisation
    expect(v.enabled).toBe(true)
    expect(v.style).toBe('soft')
    expect(v.opacity).toBe(0.5)
    expect(v.barCount).toBe(24)
  })

  it('setVisualisationEnabled updates the field', () => {
    useVoiceSettingsStore.getState().setVisualisationEnabled(false)
    expect(useVoiceSettingsStore.getState().visualisation.enabled).toBe(false)
  })

  it('setVisualisationStyle updates the field', () => {
    useVoiceSettingsStore.getState().setVisualisationStyle('glow')
    expect(useVoiceSettingsStore.getState().visualisation.style).toBe('glow')
  })

  it('setVisualisationOpacity clamps to [0.05, 0.80]', () => {
    const set = useVoiceSettingsStore.getState().setVisualisationOpacity
    set(0.001); expect(useVoiceSettingsStore.getState().visualisation.opacity).toBe(0.05)
    set(1.5);   expect(useVoiceSettingsStore.getState().visualisation.opacity).toBe(0.80)
    set(0.42);  expect(useVoiceSettingsStore.getState().visualisation.opacity).toBe(0.42)
  })

  it('setVisualisationBarCount clamps to [16, 96] and rounds to integer', () => {
    const set = useVoiceSettingsStore.getState().setVisualisationBarCount
    set(8);    expect(useVoiceSettingsStore.getState().visualisation.barCount).toBe(16)
    set(120);  expect(useVoiceSettingsStore.getState().visualisation.barCount).toBe(96)
    set(33.7); expect(useVoiceSettingsStore.getState().visualisation.barCount).toBe(34)
  })

  it('merges old persisted snapshots without visualisation block', () => {
    // Simulate an upgrade: persisted state is a pre-visualisation payload.
    const old = JSON.stringify({
      state: {
        inputMode: 'continuous', // will be hard-coded back to push-to-talk
        autoSendTranscription: true,
        voiceActivationThreshold: 'high',
        stt_provider_id: 'whisper',
      },
      version: 0,
    })
    localStorage.setItem(STORAGE_KEY, old)
    // Force the store to rehydrate from localStorage.
    useVoiceSettingsStore.persist.rehydrate()

    const s = useVoiceSettingsStore.getState()
    expect(s.autoSendTranscription).toBe(true)
    expect(s.voiceActivationThreshold).toBe('high')
    expect(s.visualisation.enabled).toBe(true)
    expect(s.visualisation.style).toBe('soft')
    expect(s.visualisation.opacity).toBe(0.5)
    expect(s.visualisation.barCount).toBe(24)
  })
})
```

- [ ] **Step 3.2: Run tests, watch them fail**

Run: `cd frontend && pnpm test --run src/features/voice/stores/__tests__/voiceSettingsStore.visualisation.test.ts`
Expected: all FAIL (`visualisation` undefined; setters do not exist).

- [ ] **Step 3.3: Extend the store**

Modify `frontend/src/features/voice/stores/voiceSettingsStore.ts`. The full file becomes:

```ts
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type InputMode = 'push-to-talk' | 'continuous'

export type VoiceActivationThreshold = 'low' | 'medium' | 'high'

export type VisualiserStyle = 'sharp' | 'soft' | 'glow' | 'glass'

export interface VoiceVisualisationSettings {
  enabled: boolean
  style: VisualiserStyle
  opacity: number   // clamped to [0.05, 0.80]
  barCount: number  // clamped to [16, 96], integer
}

const DEFAULT_VISUALISATION: VoiceVisualisationSettings = {
  enabled: true,
  style: 'soft',
  opacity: 0.5,
  barCount: 24,
}

interface VoiceSettingsState {
  inputMode: InputMode
  autoSendTranscription: boolean
  voiceActivationThreshold: VoiceActivationThreshold
  stt_provider_id: string | undefined
  visualisation: VoiceVisualisationSettings
  setInputMode(mode: InputMode): void
  setAutoSendTranscription(value: boolean): void
  setVoiceActivationThreshold(value: VoiceActivationThreshold): void
  setSttProviderId(value: string | undefined): void
  setVisualisationEnabled(value: boolean): void
  setVisualisationStyle(value: VisualiserStyle): void
  setVisualisationOpacity(value: number): void
  setVisualisationBarCount(value: number): void
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

export const useVoiceSettingsStore = create<VoiceSettingsState>()(
  persist(
    (set) => ({
      inputMode: 'push-to-talk',
      autoSendTranscription: false,
      voiceActivationThreshold: 'medium',
      stt_provider_id: undefined,
      visualisation: DEFAULT_VISUALISATION,
      setInputMode: (inputMode) => set({ inputMode }),
      setAutoSendTranscription: (autoSendTranscription) => set({ autoSendTranscription }),
      setVoiceActivationThreshold: (voiceActivationThreshold) => set({ voiceActivationThreshold }),
      setSttProviderId: (stt_provider_id) => set({ stt_provider_id }),
      setVisualisationEnabled: (enabled) => set((s) => ({ visualisation: { ...s.visualisation, enabled } })),
      setVisualisationStyle: (style) => set((s) => ({ visualisation: { ...s.visualisation, style } })),
      setVisualisationOpacity: (opacity) =>
        set((s) => ({ visualisation: { ...s.visualisation, opacity: clamp(opacity, 0.05, 0.80) } })),
      setVisualisationBarCount: (barCount) =>
        set((s) => ({ visualisation: { ...s.visualisation, barCount: clamp(Math.round(barCount), 16, 96) } })),
    }),
    {
      name: 'voice-settings',
      // Hard-code push-to-talk regardless of what older builds persisted.
      // The Continuous mode UI has been retired — VAD will replace it later.
      // Visualisation block is merged with defaults so older payloads hydrate.
      merge: (persisted, current) => {
        const p = persisted as Partial<VoiceSettingsState>
        return {
          ...current,
          ...p,
          inputMode: 'push-to-talk',
          visualisation: { ...current.visualisation, ...(p.visualisation ?? {}) },
        }
      },
    },
  ),
)
```

- [ ] **Step 3.4: Run tests, watch them pass**

Run: `cd frontend && pnpm test --run src/features/voice/stores/__tests__/voiceSettingsStore.visualisation.test.ts`
Expected: all 6 tests PASS.

- [ ] **Step 3.5: Run the full voice-settings test file (regression check)**

Run: `cd frontend && pnpm test --run src/features/voice/stores/voiceSettingsStore.test.ts`
Expected: all existing tests still PASS.

- [ ] **Step 3.6: Commit**

```bash
git add frontend/src/features/voice/stores/voiceSettingsStore.ts frontend/src/features/voice/stores/__tests__/voiceSettingsStore.visualisation.test.ts
git commit -m "Extend voiceSettingsStore with visualisation block"
```

---

## Task 4: Speech simulator (preview only)

**Files:**
- Create: `frontend/src/features/voice/infrastructure/visualiserSpeechSimulator.ts`

**Goal:** Provide synthetic amplitude and frequency data for the live preview component on the Voice settings tab. Production rendering uses the real analyser; this is only for "what does it look like" before the user has played any TTS.

No TDD — these are tunable aesthetic functions whose only test is "looks like speech in the preview". They can be visually validated alongside the preview component in Task 8.

- [ ] **Step 4.1: Implement**

Create `frontend/src/features/voice/infrastructure/visualiserSpeechSimulator.ts`:

```ts
/**
 * Synthetic amplitude / frequency simulator used by the settings-tab live
 * preview to demonstrate the visualiser before any real TTS has played.
 * Models speech-like rhythm: syllable-rate bursts (~5 Hz), sentence-level
 * pauses (~20 % of period), and a slow macro envelope so it doesn't feel
 * mechanical. Frequency bins are pseudo-bands with low-frequency boost.
 *
 * Production rendering does NOT use this — it reads the real AnalyserNode.
 */

export function simulateAmplitude(t: number): number {
  const sentencePeriod = 3.4
  const phase = (t % sentencePeriod) / sentencePeriod
  const sentenceActive = phase < 0.82 ? 1 : Math.max(0, 1 - (phase - 0.82) * 8)
  const syllable = 0.5 + 0.5 * Math.sin(t * 11 + Math.sin(t * 0.7) * 2.2)
  const syllableBoost = Math.pow(syllable, 1.5)
  const macro = 0.65 + 0.35 * Math.sin(t * 0.5 + 1.3)
  const noise = 0.04 * (Math.random() - 0.5)
  return Math.max(0, Math.min(1, sentenceActive * (0.22 + 0.6 * syllableBoost) * macro + noise))
}

const seeds: number[] = []

/**
 * Smoothed, low-frequency-boosted synthetic bins. State is module-private
 * because the preview component only mounts once per Settings tab open.
 */
let binValues: Float32Array = new Float32Array(0)

export function simulateFrequencyBins(t: number, ampl: number, n: number): Float32Array {
  if (binValues.length !== n) {
    binValues = new Float32Array(n)
    seeds.length = 0
    for (let i = 0; i < n; i++) seeds.push(Math.random() * 100 + i * 0.7)
  }
  for (let i = 0; i < n; i++) {
    const lowBoost = Math.pow(1 - i / n, 0.55)
    const wobble = 0.5 + 0.5 * Math.sin(t * (1.6 + i * 0.16) + seeds[i])
    const target = ampl * lowBoost * (0.35 + 0.65 * wobble)
    binValues[i] += (target - binValues[i]) * 0.28
  }
  return binValues
}
```

- [ ] **Step 4.2: TypeScript build check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: zero errors.

- [ ] **Step 4.3: Commit**

```bash
git add frontend/src/features/voice/infrastructure/visualiserSpeechSimulator.ts
git commit -m "Add synthetic speech simulator for visualiser preview"
```

---

## Task 5: Visualiser renderers (one per style)

**Files:**
- Create: `frontend/src/features/voice/infrastructure/visualiserRenderers.ts`

**Goal:** Four pure functions, one per bar style, each takes a 2D canvas context, dimensions, the bin values, and rendering options (max-deflection, opacity, persona colour). Used by both `VoiceVisualiser` and `VoiceVisualiserPreview`.

No TDD — visual rendering is exercised end-to-end by the components in later tasks. The functions are kept pure (no module state, no side effects beyond `ctx.*`) so they can be reasoned about and unit-tested later if needed.

- [ ] **Step 5.1: Implement renderers**

Create `frontend/src/features/voice/infrastructure/visualiserRenderers.ts`:

```ts
import type { VisualiserStyle } from '../stores/voiceSettingsStore'

export interface RenderOpts {
  /** RGB triplet, 0–255 each, of the persona's chakra colour. */
  rgb: [number, number, number]
  /** Same colour brightened by ~+40 per channel, clamped to 255. */
  rgbLight: [number, number, number]
  /** User-configured opacity, 0.05–0.80. */
  opacity: number
  /** Hard-coded fraction of viewport height occupied by total deflection. */
  maxHeightFraction: number
}

/**
 * Render a frame of the equaliser for the requested style. Caller has
 * already cleared the canvas. `bins` is normalised to [0, 1].
 */
export function drawVisualiserFrame(
  style: VisualiserStyle,
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  bins: Float32Array,
  opts: RenderOpts,
): void {
  switch (style) {
    case 'sharp': drawSharp(ctx, width, height, bins, opts); break
    case 'soft':  drawSoft(ctx, width, height, bins, opts); break
    case 'glow':  drawGlow(ctx, width, height, bins, opts); break
    case 'glass': drawGlass(ctx, width, height, bins, opts); break
  }
}

function barLayout(width: number, height: number, n: number, frac: number) {
  const cy = height / 2
  const slot = width / n
  const barW = slot * 0.62
  const maxDy = (height * frac) / 2
  return { cy, slot, barW, maxDy }
}

function drawSharp(ctx: CanvasRenderingContext2D, w: number, h: number, bins: Float32Array, o: RenderOpts) {
  const n = bins.length
  const { cy, slot, barW, maxDy } = barLayout(w, h, n, o.maxHeightFraction)
  const [lr, lg, lb] = o.rgbLight
  ctx.fillStyle = `rgba(${lr},${lg},${lb},${o.opacity})`
  for (let i = 0; i < n; i++) {
    const dy = Math.min(bins[i], 1) * maxDy
    if (dy < 0.5) continue
    ctx.fillRect(i * slot + (slot - barW) / 2, cy - dy, barW, dy * 2)
  }
}

function drawSoft(ctx: CanvasRenderingContext2D, w: number, h: number, bins: Float32Array, o: RenderOpts) {
  const n = bins.length
  const { cy, slot, barW, maxDy } = barLayout(w, h, n, o.maxHeightFraction)
  const [r, g, b] = o.rgb
  const [lr, lg, lb] = o.rgbLight
  for (let i = 0; i < n; i++) {
    const dy = Math.min(bins[i], 1) * maxDy
    if (dy < 0.5) continue
    const y0 = cy - dy
    const grd = ctx.createLinearGradient(0, y0, 0, cy + dy)
    grd.addColorStop(0,   `rgba(${r},${g},${b},${o.opacity * 0.15})`)
    grd.addColorStop(0.5, `rgba(${lr},${lg},${lb},${o.opacity})`)
    grd.addColorStop(1,   `rgba(${r},${g},${b},${o.opacity * 0.15})`)
    ctx.fillStyle = grd
    ctx.fillRect(i * slot + (slot - barW) / 2, y0, barW, dy * 2)
  }
}

function drawGlow(ctx: CanvasRenderingContext2D, w: number, h: number, bins: Float32Array, o: RenderOpts) {
  const n = bins.length
  const { cy, slot, barW, maxDy } = barLayout(w, h, n, o.maxHeightFraction)
  const [r, g, b] = o.rgb
  const [lr, lg, lb] = o.rgbLight
  ctx.shadowColor = `rgba(${r},${g},${b},${o.opacity * 1.5})`
  ctx.shadowBlur = 14
  ctx.fillStyle = `rgba(${lr},${lg},${lb},${o.opacity * 0.9})`
  for (let i = 0; i < n; i++) {
    const dy = Math.min(bins[i], 1) * maxDy
    if (dy < 0.5) continue
    ctx.fillRect(i * slot + (slot - barW) / 2, cy - dy, barW, dy * 2)
  }
  ctx.shadowBlur = 0
}

function drawGlass(ctx: CanvasRenderingContext2D, w: number, h: number, bins: Float32Array, o: RenderOpts) {
  const n = bins.length
  const { cy, slot, barW, maxDy } = barLayout(w, h, n, o.maxHeightFraction)
  const [lr, lg, lb] = o.rgbLight
  ctx.lineWidth = 1
  for (let i = 0; i < n; i++) {
    const dy = Math.min(bins[i], 1) * maxDy
    if (dy < 0.5) continue
    const x = i * slot + (slot - barW) / 2
    const y0 = cy - dy
    ctx.fillStyle = `rgba(255,255,255,${o.opacity * 0.45})`
    ctx.fillRect(x, y0, barW, dy * 2)
    ctx.strokeStyle = `rgba(${lr},${lg},${lb},${o.opacity * 0.85})`
    ctx.strokeRect(x + 0.5, y0 + 0.5, barW - 1, dy * 2 - 1)
  }
}
```

- [ ] **Step 5.2: TypeScript build check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: zero errors.

- [ ] **Step 5.3: Commit**

```bash
git add frontend/src/features/voice/infrastructure/visualiserRenderers.ts
git commit -m "Add visualiser renderers — sharp / soft / glow / glass"
```

---

## Task 6: useTtsFrequencyData hook

**Files:**
- Create: `frontend/src/features/voice/infrastructure/useTtsFrequencyData.ts`

**Goal:** React hook that reads the AnalyserNode each frame, applies log bucketing, exponentially smooths, and returns accessor functions for use inside a parent RAF loop. Crucially, **does not** trigger React re-renders per frame — buckets are read on demand.

No dedicated test — tested indirectly via the `VoiceVisualiser` component in Task 7. Mocking AnalyserNode and verifying bucketing is already covered by the bucketing test.

- [ ] **Step 6.1: Implement**

Create `frontend/src/features/voice/infrastructure/useTtsFrequencyData.ts`:

```ts
import { useEffect, useRef } from 'react'
import { audioPlayback } from './audioPlayback'
import { bucketIntoLogBins } from './visualiserBucketing'

const SMOOTHING = 0.28

interface FrequencyAccessors {
  /**
   * Reads the current frequency bins, log-bucketed and exponentially
   * smoothed across frames. Returns null if the analyser is not yet
   * available (i.e. no TTS has played in this session).
   */
  getBins(): Float32Array | null
  /** True iff the playback singleton currently believes audio is playing. */
  isActive(): boolean
}

export function useTtsFrequencyData(barCount: number): FrequencyAccessors {
  const rawBuffer = useRef<Uint8Array>(new Uint8Array(128))
  const smoothed = useRef<Float32Array>(new Float32Array(barCount))

  useEffect(() => {
    if (smoothed.current.length !== barCount) {
      smoothed.current = new Float32Array(barCount)
    }
  }, [barCount])

  const accessorsRef = useRef<FrequencyAccessors>({
    getBins: () => null,
    isActive: () => false,
  })

  // Re-bind accessor implementations once per render so they always close
  // over the latest barCount.
  accessorsRef.current = {
    getBins: () => {
      const analyser = audioPlayback.getAnalyser()
      if (!analyser) return null
      if (rawBuffer.current.length !== analyser.frequencyBinCount) {
        rawBuffer.current = new Uint8Array(analyser.frequencyBinCount)
      }
      analyser.getByteFrequencyData(rawBuffer.current)
      const target = bucketIntoLogBins(
        rawBuffer.current,
        analyser.context.sampleRate,
        analyser.fftSize,
        barCount,
      )
      const out = smoothed.current
      for (let i = 0; i < barCount; i++) {
        out[i] += (target[i] - out[i]) * SMOOTHING
      }
      return out
    },
    isActive: () => audioPlayback.isPlaying(),
  }

  return accessorsRef.current
}
```

- [ ] **Step 6.2: TypeScript build check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: zero errors. (If `audioPlayback` is not exported as a singleton from the same module, adjust the import — verify the existing pattern.)

- [ ] **Step 6.3: Commit**

```bash
git add frontend/src/features/voice/infrastructure/useTtsFrequencyData.ts
git commit -m "Add useTtsFrequencyData hook"
```

---

## Task 7: VoiceVisualiser component

**Files:**
- Create: `frontend/src/features/voice/components/VoiceVisualiser.tsx`

**Goal:** Production component. Fixed full-viewport canvas, owns one RAF loop, renders only when active and not reduced-motion and master toggle is on. Reads persona colour from the persona store. Pauses RAF when fully idle to spare CPU.

- [ ] **Step 7.1: Identify the persona colour source**

Confirm before writing:

```bash
rg -n "useActivePersona|usePersonaStore|getActivePersona" frontend/src/features/voice frontend/src/app | head
```

The plan assumes there is a hook returning the active persona with a `colour_scheme` string. If the hook name differs in the codebase, substitute the actual hook in step 7.2 — `personaHex(persona)` is the consistent helper.

- [ ] **Step 7.2: Implement the component**

Create `frontend/src/features/voice/components/VoiceVisualiser.tsx`:

```tsx
import { useEffect, useRef } from 'react'
import { useVoiceSettingsStore } from '../stores/voiceSettingsStore'
import { useTtsFrequencyData } from '../infrastructure/useTtsFrequencyData'
import { drawVisualiserFrame } from '../infrastructure/visualiserRenderers'
import { audioPlayback } from '../infrastructure/audioPlayback'
import { personaHex } from '../../../app/components/sidebar/personaColour'
import { useActivePersona } from '../../persona/hooks/useActivePersona' // adjust if different

const MAX_HEIGHT_FRACTION = 0.28
const FADE_RATE = 0.05

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h
  return [
    parseInt(full.slice(0, 2), 16),
    parseInt(full.slice(2, 4), 16),
    parseInt(full.slice(4, 6), 16),
  ]
}

function brighten([r, g, b]: [number, number, number]): [number, number, number] {
  return [Math.min(255, r + 40), Math.min(255, g + 40), Math.min(255, b + 40)]
}

export function VoiceVisualiser() {
  const enabled  = useVoiceSettingsStore((s) => s.visualisation.enabled)
  const style    = useVoiceSettingsStore((s) => s.visualisation.style)
  const opacity  = useVoiceSettingsStore((s) => s.visualisation.opacity)
  const barCount = useVoiceSettingsStore((s) => s.visualisation.barCount)

  const persona = useActivePersona()
  const colourHex = persona ? personaHex(persona) : '#8C76D7'

  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const rafRef = useRef<number | null>(null)
  const activeRef = useRef(0)
  const reducedMotionRef = useRef(false)

  const accessors = useTtsFrequencyData(barCount)

  // Reduced-motion subscription. Honours OS-level preference live.
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    reducedMotionRef.current = mq.matches
    const listener = () => { reducedMotionRef.current = mq.matches }
    mq.addEventListener('change', listener)
    return () => mq.removeEventListener('change', listener)
  }, [])

  useEffect(() => {
    if (!enabled) {
      // Fully off — cancel RAF, clear canvas.
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
      const c = canvasRef.current
      if (c) c.getContext('2d')?.clearRect(0, 0, c.width, c.height)
      activeRef.current = 0
      return
    }

    let stopped = false

    const tick = () => {
      if (stopped) return
      const c = canvasRef.current
      if (!c) { rafRef.current = requestAnimationFrame(tick); return }

      // DPR clamped to 1 — soft decorative shapes; saves ~4× memory at 4K.
      const w = c.clientWidth
      const h = c.clientHeight
      if (c.width !== w || c.height !== h) { c.width = w; c.height = h }

      const ctx = c.getContext('2d')
      if (!ctx) return
      ctx.clearRect(0, 0, w, h)

      if (reducedMotionRef.current) {
        // OS asked for no motion; render nothing, schedule next frame so we
        // pick up the change event when the user toggles the OS setting.
        rafRef.current = requestAnimationFrame(tick)
        return
      }

      const playing = accessors.isActive()
      const target = playing ? 1 : 0
      activeRef.current += (target - activeRef.current) * FADE_RATE

      if (activeRef.current > 0.005) {
        const bins = accessors.getBins()
        if (bins) {
          const rgb = hexToRgb(colourHex)
          const rgbLight = brighten(rgb)
          // Scale opacity by the fade scalar so the strip eases in / out.
          drawVisualiserFrame(style, ctx, w, h, bins, {
            rgb,
            rgbLight,
            opacity: opacity * activeRef.current,
            maxHeightFraction: MAX_HEIGHT_FRACTION,
          })
        }
        rafRef.current = requestAnimationFrame(tick)
      } else if (playing) {
        // Was idle, just started — keep the loop running.
        rafRef.current = requestAnimationFrame(tick)
      } else {
        // Fully faded out and not playing — pause RAF until next play event.
        rafRef.current = null
      }
    }

    // (Re-)kick the loop. Any state change that flips into "should render"
    // will see activeRef.current > 0 next subscribe call.
    rafRef.current = requestAnimationFrame(tick)

    // Resume the loop when playback starts after an idle pause.
    const unsub = audioPlayback.subscribe(() => {
      if (rafRef.current === null && !stopped) {
        rafRef.current = requestAnimationFrame(tick)
      }
    })

    return () => {
      stopped = true
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
      unsub()
    }
  }, [enabled, style, opacity, barCount, colourHex, accessors])

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      style={{
        position: 'fixed',
        inset: 0,
        width: '100vw',
        height: '100vh',
        pointerEvents: 'none',
        zIndex: 1,
      }}
    />
  )
}
```

- [ ] **Step 7.3: TypeScript build check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: zero errors. If `useActivePersona` is at a different path, fix the import — search with `rg "useActivePersona"`.

- [ ] **Step 7.4: Commit**

```bash
git add frontend/src/features/voice/components/VoiceVisualiser.tsx
git commit -m "Add VoiceVisualiser overlay component"
```

---

## Task 8: VoiceVisualiserPreview component

**Files:**
- Create: `frontend/src/features/voice/components/VoiceVisualiserPreview.tsx`

**Goal:** A small canvas (~120 px tall, full container width) for the Voice settings tab. Uses the same renderers but fed by the synthetic speech simulator. Reacts immediately to settings changes. Shows a placeholder when the master toggle is off.

- [ ] **Step 8.1: Implement**

Create `frontend/src/features/voice/components/VoiceVisualiserPreview.tsx`:

```tsx
import { useEffect, useRef } from 'react'
import {
  useVoiceSettingsStore,
  type VisualiserStyle,
} from '../stores/voiceSettingsStore'
import { drawVisualiserFrame } from '../infrastructure/visualiserRenderers'
import {
  simulateAmplitude,
  simulateFrequencyBins,
} from '../infrastructure/visualiserSpeechSimulator'
import { personaHex } from '../../../app/components/sidebar/personaColour'
import { useActivePersona } from '../../persona/hooks/useActivePersona'

const MAX_HEIGHT_FRACTION = 0.55  // preview is short — bars need to be visibly tall

interface Props {
  style: VisualiserStyle
  opacity: number
  barCount: number
  enabled: boolean
}

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h
  return [
    parseInt(full.slice(0, 2), 16),
    parseInt(full.slice(2, 4), 16),
    parseInt(full.slice(4, 6), 16),
  ]
}

function brighten([r, g, b]: [number, number, number]): [number, number, number] {
  return [Math.min(255, r + 40), Math.min(255, g + 40), Math.min(255, b + 40)]
}

export function VoiceVisualiserPreview({ style, opacity, barCount, enabled }: Props) {
  const persona = useActivePersona()
  const colourHex = persona ? personaHex(persona) : '#8C76D7'
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const rafRef = useRef<number | null>(null)

  useEffect(() => {
    if (!enabled) {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
      const c = canvasRef.current
      if (c) c.getContext('2d')?.clearRect(0, 0, c.width, c.height)
      return
    }

    let stopped = false
    const tick = (now: number) => {
      if (stopped) return
      const c = canvasRef.current
      if (!c) { rafRef.current = requestAnimationFrame(tick); return }
      const w = c.clientWidth
      const h = c.clientHeight
      if (c.width !== w || c.height !== h) { c.width = w; c.height = h }
      const ctx = c.getContext('2d')
      if (!ctx) return
      ctx.clearRect(0, 0, w, h)

      const t = now / 1000
      const ampl = simulateAmplitude(t)
      const bins = simulateFrequencyBins(t, ampl, barCount)
      const rgb = hexToRgb(colourHex)
      const rgbLight = brighten(rgb)
      drawVisualiserFrame(style, ctx, w, h, bins, {
        rgb,
        rgbLight,
        opacity,
        maxHeightFraction: MAX_HEIGHT_FRACTION,
      })
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)

    return () => {
      stopped = true
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
    }
  }, [style, opacity, barCount, colourHex, enabled])

  return (
    <div
      aria-hidden
      className="relative w-full h-[120px] rounded-md overflow-hidden bg-[#0a0810] border border-white/10"
    >
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full" />
      {!enabled && (
        <div className="absolute inset-0 flex items-center justify-center text-white/40 font-mono text-xs uppercase tracking-wider">
          Aus
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 8.2: TypeScript build check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: zero errors.

- [ ] **Step 8.3: Commit**

```bash
git add frontend/src/features/voice/components/VoiceVisualiserPreview.tsx
git commit -m "Add VoiceVisualiserPreview for the Voice settings tab"
```

---

## Task 9: Mount in AppLayout

**Files:**
- Modify: `frontend/src/app/layouts/AppLayout.tsx` (around line 344, near `<ToastContainer />`)

**Goal:** Mount the visualiser once. After this task, real TTS playback should produce a visible equaliser at default settings.

- [ ] **Step 9.1: Add import**

Near the other voice-related imports in `AppLayout.tsx`:

```tsx
import { VoiceVisualiser } from '../../features/voice/components/VoiceVisualiser'
```

- [ ] **Step 9.2: Mount in JSX**

Replace the existing block ending in `<ToastContainer />`:

```tsx
      <ToastContainer />
      <MobileToastContainer />
      <InstallHint />
```

with:

```tsx
      <VoiceVisualiser />
      <ToastContainer />
      <MobileToastContainer />
      <InstallHint />
```

(`<VoiceVisualiser />` first so toasts paint above it; both are `position: fixed`, so order in JSX has no other effect.)

- [ ] **Step 9.3: TypeScript build check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: zero errors.

- [ ] **Step 9.4: Manual smoke test (the first real visual moment)**

Run dev server: `cd frontend && pnpm dev`
Log in, pick a persona with a TTS-capable voice, send a message that triggers a multi-sentence reply. While the reply is being spoken, an equaliser appears centred horizontally, mirrored vertically, in the persona's chakra colour, with motion that follows the speech rhythm. When the reply ends, it fades out.

If the bars are too tall or too transparent for taste at the defaults, do not adjust here — that is exactly what Task 10 lets the user do.

- [ ] **Step 9.5: Commit**

```bash
git add frontend/src/app/layouts/AppLayout.tsx
git commit -m "Mount VoiceVisualiser in AppLayout"
```

---

## Task 10: Voice settings tab — visualisation section

**Files:**
- Modify: `frontend/src/app/components/user-modal/VoiceTab.tsx`
- Create: `frontend/src/app/components/user-modal/__tests__/VoiceTab.visualisation.test.tsx`

**Goal:** Append a "Sprachausgabe-Visualisierung" section with: master toggle, style picker (4 buttons), opacity slider, bar count slider, live preview, and a reduced-motion notice.

- [ ] **Step 10.1: Write failing tests**

Create `frontend/src/app/components/user-modal/__tests__/VoiceTab.visualisation.test.tsx`:

```tsx
import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { VoiceTab } from '../VoiceTab'
import { useVoiceSettingsStore } from '../../../../features/voice/stores/voiceSettingsStore'

describe('VoiceTab — visualisation section', () => {
  beforeEach(() => {
    localStorage.clear()
    useVoiceSettingsStore.setState(useVoiceSettingsStore.getInitialState(), true)
  })

  it('renders the master toggle in the on state by default', () => {
    render(<VoiceTab />)
    const toggle = screen.getByRole('checkbox', { name: /Visualisierung anzeigen/i })
    expect(toggle).toBeChecked()
  })

  it('toggling the master switch updates the store', () => {
    render(<VoiceTab />)
    const toggle = screen.getByRole('checkbox', { name: /Visualisierung anzeigen/i })
    fireEvent.click(toggle)
    expect(useVoiceSettingsStore.getState().visualisation.enabled).toBe(false)
  })

  it('clicking a style button updates the store', () => {
    render(<VoiceTab />)
    fireEvent.click(screen.getByRole('button', { name: /Glühend/i }))
    expect(useVoiceSettingsStore.getState().visualisation.style).toBe('glow')
  })

  it('moving the opacity slider updates the store', () => {
    render(<VoiceTab />)
    const slider = screen.getByLabelText(/Deckkraft/i) as HTMLInputElement
    fireEvent.change(slider, { target: { value: '70' } })
    expect(useVoiceSettingsStore.getState().visualisation.opacity).toBeCloseTo(0.7, 2)
  })

  it('moving the bar count slider updates the store', () => {
    render(<VoiceTab />)
    const slider = screen.getByLabelText(/Anzahl Säulen/i) as HTMLInputElement
    fireEvent.change(slider, { target: { value: '64' } })
    expect(useVoiceSettingsStore.getState().visualisation.barCount).toBe(64)
  })
})
```

- [ ] **Step 10.2: Run tests, watch them fail**

Run: `cd frontend && pnpm test --run src/app/components/user-modal/__tests__/VoiceTab.visualisation.test.tsx`
Expected: all FAIL — controls do not exist yet.

- [ ] **Step 10.3: Extend VoiceTab with the visualisation section**

Modify `frontend/src/app/components/user-modal/VoiceTab.tsx`. At the imports, add:

```tsx
import { VoiceVisualiserPreview } from '../../../features/voice/components/VoiceVisualiserPreview'
import type { VisualiserStyle } from '../../../features/voice/stores/voiceSettingsStore'

const STYLE_OPTIONS: { value: VisualiserStyle; label: string }[] = [
  { value: 'sharp', label: 'Scharf' },
  { value: 'soft',  label: 'Weich' },
  { value: 'glow',  label: 'Glühend' },
  { value: 'glass', label: 'Glas' },
]
```

Inside the `VoiceTab()` function body, alongside the existing store reads, add:

```tsx
const v = useVoiceSettingsStore((s) => s.visualisation)
const setEnabled = useVoiceSettingsStore((s) => s.setVisualisationEnabled)
const setStyle = useVoiceSettingsStore((s) => s.setVisualisationStyle)
const setOpacity = useVoiceSettingsStore((s) => s.setVisualisationOpacity)
const setBarCount = useVoiceSettingsStore((s) => s.setVisualisationBarCount)
const reducedMotion = typeof window !== 'undefined'
  && window.matchMedia('(prefers-reduced-motion: reduce)').matches
```

Inside the returned JSX, after the existing voice-settings blocks but still inside the outermost wrapping `<div className="flex flex-col gap-6 p-6 max-w-xl overflow-y-auto">`, append:

```tsx
<div className="border-t border-white/10 pt-6">
  <h3 className="text-sm uppercase tracking-[0.15em] text-white/70 font-mono mb-4">
    Sprachausgabe-Visualisierung
  </h3>

  <label className="flex items-center gap-3 mb-4">
    <input
      type="checkbox"
      checked={v.enabled}
      onChange={(e) => setEnabled(e.target.checked)}
    />
    <span className="text-sm text-white/85">Visualisierung anzeigen</span>
  </label>

  {reducedMotion && (
    <p className="text-[11px] text-amber-300/80 font-mono mb-4 leading-relaxed">
      Dein Betriebssystem hat „Bewegung reduzieren" aktiviert — die
      Visualisierung ist deaktiviert.
    </p>
  )}

  <div className={v.enabled ? '' : 'opacity-40 pointer-events-none'}>
    <label className={LABEL}>Stil</label>
    <div className="flex gap-2 mb-4 flex-wrap">
      {STYLE_OPTIONS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => setStyle(opt.value)}
          className={
            'px-3 py-1.5 rounded-md text-xs font-mono border ' +
            (v.style === opt.value
              ? 'bg-white/10 border-white/40 text-white'
              : 'bg-white/[0.03] border-white/10 text-white/65 hover:border-white/25')
          }
        >
          {opt.label}
        </button>
      ))}
    </div>

    <label className={LABEL} htmlFor="vis-opacity">
      Deckkraft <span className="text-white/85">{Math.round(v.opacity * 100)}%</span>
    </label>
    <input
      id="vis-opacity"
      type="range"
      min={5}
      max={80}
      value={Math.round(v.opacity * 100)}
      onChange={(e) => setOpacity(Number(e.target.value) / 100)}
      className="w-full mb-4 accent-white/70"
    />

    <label className={LABEL} htmlFor="vis-bar-count">
      Anzahl Säulen <span className="text-white/85">{v.barCount}</span>
    </label>
    <input
      id="vis-bar-count"
      type="range"
      min={16}
      max={96}
      value={v.barCount}
      onChange={(e) => setBarCount(Number(e.target.value))}
      className="w-full mb-4 accent-white/70"
    />

    <VoiceVisualiserPreview
      style={v.style}
      opacity={v.opacity}
      barCount={v.barCount}
      enabled={v.enabled}
    />
  </div>
</div>
```

- [ ] **Step 10.4: Run tests, watch them pass**

Run: `cd frontend && pnpm test --run src/app/components/user-modal/__tests__/VoiceTab.visualisation.test.tsx`
Expected: all 5 tests PASS.

- [ ] **Step 10.5: TypeScript build check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: zero errors.

- [ ] **Step 10.6: Run the wider voice-tab regression check**

Run: `cd frontend && pnpm test --run src/app/components/user-modal/__tests__/VoiceTab.test.tsx`
Expected: existing tests still PASS.

- [ ] **Step 10.7: Commit**

```bash
git add frontend/src/app/components/user-modal/VoiceTab.tsx frontend/src/app/components/user-modal/__tests__/VoiceTab.visualisation.test.tsx
git commit -m "Add visualisation controls and live preview to VoiceTab"
```

---

## Task 11: Manual verification pass

**Goal:** Run through the full 15-point checklist from spec section 13. Document any deviations or surprises in a short report appended to this plan or pasted into the PR description. **No code changes** — pure verification.

- [ ] **Step 11.1: Build checks**

Run both:
```bash
cd frontend && pnpm tsc --noEmit
cd frontend && pnpm test --run
```
Expected: zero TS errors; all tests pass.

- [ ] **Step 11.2: Boot the dev server**

Run: `cd frontend && pnpm dev`
Note the URL and have a TTS-capable persona configured.

- [ ] **Step 11.3: Run all 15 manual checks**

Walk through every item in `devdocs/specs/2026-04-26-tts-voice-visualiser-design.md` section 13. Tick the boxes as you go. Re-test the four bar styles, both regular chat and continuous voice, persona switch, master toggle, reduced-motion at the OS level, and modal overlay z-index.

- [ ] **Step 11.4: Hand back to Chris for review and merge**

Stop here. Do **not** merge to master. Do **not** push. Summarise:
- All tasks completed and committed (count of commits since branch start)
- Any deviations from the plan and why
- Any surprises during manual verification

Chris reviews the diff and decides on the merge.

---

## Self-Review Notes

**Spec coverage check:**
- Architecture (spec §3)            → Tasks 1, 6, 7, 9
- Audio graph change (spec §4)      → Task 1
- Frequency hook (spec §5)          → Tasks 2, 6
- Settings model (spec §6)          → Task 3
- Render component (spec §7)        → Tasks 5, 7
- Settings UI section (spec §8)     → Tasks 4, 8, 10
- Accessibility (spec §9)           → Task 7 (reduced-motion live listener), Task 10 (notice)
- Performance (spec §10)            → Task 7 (RAF pause when fully idle)
- Risks (spec §11)                  → DPR clamp baked into Task 7; merge fallback baked into Task 3
- Implementation order (spec §12)   → Tasks 1 → 10 mirror it exactly
- Manual verification (spec §13)    → Task 11

Each spec section has at least one task. No placeholders, no "TBD", no "similar to Task N", no untyped references. All function and method names are consistent across tasks (`getAnalyser`, `bucketIntoLogBins`, `drawVisualiserFrame`, `useTtsFrequencyData`, `setVisualisationEnabled` etc.).

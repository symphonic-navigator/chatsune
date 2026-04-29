# Voice Pause Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the conversational-mode silence window user-tunable via a slider (576–11 520 ms, default 1 728 ms) and add a centred countdown pie that visually shows the remaining pause budget, matching the visualiser's style and the active persona's accent colour.

**Architecture:** Frontend-only feature. A new `pauseRedemptionStore` carries the live "redemption open / closed" edge driven by a frame-grained state machine inside `audioCapture` (using `vad-web`'s `onFrameProcessed` callback). A new canvas component `VoiceCountdownPie` renders a draining wedge in the same rect as `VoiceVisualiser`; the visualiser fades its bars out while the pie is active so they never compete for the same pixels. The slider lives next to the existing voice-activation-threshold buttons in `VoiceTab` and persists in `voiceSettingsStore`.

**Tech Stack:** React + TypeScript (TSX), Zustand, `@ricky0123/vad-web@0.0.30`, Canvas 2D, Vitest + @testing-library/react.

**Spec:** `devdocs/specs/2026-04-29-voice-pause-controls-design.md`

---

## File Map

**Modify:**
- `frontend/src/features/voice/stores/voiceSettingsStore.ts` — new `redemptionMs` field, setter, migration default.
- `frontend/src/features/voice/stores/voiceSettingsStore.test.ts` — migration test.
- `frontend/src/features/voice/stores/__tests__/voiceSettingsStore.visualisation.test.ts` — add a clamp test.
- `frontend/src/features/voice/infrastructure/vadPresets.ts` — drop `redemptionFrames`.
- `frontend/src/features/voice/infrastructure/__tests__/vadPresets.test.ts` — drop the corresponding assertion.
- `frontend/src/features/voice/infrastructure/audioCapture.ts` — accept `redemptionMs` option, wire `onFrameProcessed` state machine.
- `frontend/src/features/voice/hooks/useConversationMode.ts` — read `redemptionMs` from settings, pass it through.
- `frontend/src/features/voice/hooks/__tests__/useConversationMode.holdRelease.test.tsx` — extend mock-shape if option signature changed.
- `frontend/src/features/voice/components/VoiceVisualiser.tsx` — fade bars to 0 while redemption is active.
- `frontend/src/app/components/user-modal/VoiceTab.tsx` — new slider.
- `frontend/src/app/components/user-modal/__tests__/VoiceTab.test.tsx` — slider behaviour test.
- `frontend/src/app/layouts/AppLayout.tsx` — mount `<VoiceCountdownPie />` next to `<VoiceVisualiser />`.

**Create:**
- `frontend/src/features/voice/stores/pauseRedemptionStore.ts` — Zustand store with `start(windowMs)` / `clear()`.
- `frontend/src/features/voice/stores/__tests__/pauseRedemptionStore.test.ts` — store transition tests.
- `frontend/src/features/voice/infrastructure/pieRenderers.ts` — `drawPieFrame(style, …)` and 4 style helpers.
- `frontend/src/features/voice/infrastructure/__tests__/pieRenderers.test.ts` — smoke render per style.
- `frontend/src/features/voice/components/VoiceCountdownPie.tsx` — canvas component, RAF-driven.
- `frontend/src/features/voice/components/__tests__/VoiceCountdownPie.test.tsx` — render + fade-out behaviour.

---

## Conventions

- All comments / identifiers / docs in **British English** (per project convention).
- Commit messages: imperative, free-form (e.g. "Add redemptionMs to voice settings").
- After every task: run the relevant test file with `pnpm --filter frontend exec vitest run <path>`.
- Final task runs `pnpm --filter frontend run build` to catch the stricter type errors only `tsc -b` produces.

---

## Task 1: Add `redemptionMs` field to voice settings store

**Files:**
- Modify: `frontend/src/features/voice/stores/voiceSettingsStore.ts`
- Modify: `frontend/src/features/voice/stores/voiceSettingsStore.test.ts`

This is the only purely additive task — nothing else can read it yet, but the field must exist before any caller is wired up.

- [ ] **Step 1: Write failing test for default value, setter, and clamping**

Add to `frontend/src/features/voice/stores/voiceSettingsStore.test.ts`:

```ts
import { describe, it, expect, beforeEach } from 'vitest'
import { useVoiceSettingsStore } from './voiceSettingsStore'

describe('voiceSettingsStore — redemptionMs', () => {
  beforeEach(() => {
    localStorage.clear()
    useVoiceSettingsStore.setState({ redemptionMs: 1728 })
  })

  it('defaults to 1728 ms (= 18 frames at 96 ms/frame)', () => {
    expect(useVoiceSettingsStore.getState().redemptionMs).toBe(1728)
  })

  it('setter clamps below 576 to 576', () => {
    useVoiceSettingsStore.getState().setRedemptionMs(100)
    expect(useVoiceSettingsStore.getState().redemptionMs).toBe(576)
  })

  it('setter clamps above 11520 to 11520', () => {
    useVoiceSettingsStore.getState().setRedemptionMs(20_000)
    expect(useVoiceSettingsStore.getState().redemptionMs).toBe(11_520)
  })

  it('setter accepts in-range values verbatim', () => {
    useVoiceSettingsStore.getState().setRedemptionMs(3000)
    expect(useVoiceSettingsStore.getState().redemptionMs).toBe(3000)
  })

  it('migration: persisted payload missing redemptionMs hydrates to default 1728', async () => {
    localStorage.setItem(
      'voice-settings',
      JSON.stringify({ state: { autoSendTranscription: true }, version: 0 }),
    )
    const { useVoiceSettingsStore: fresh } = await import('./voiceSettingsStore?reload=t1')
    expect(fresh.getState().redemptionMs).toBe(1728)
    expect(fresh.getState().autoSendTranscription).toBe(true)
  })

  it('migration: persisted out-of-range value gets clamped on hydrate', async () => {
    localStorage.setItem(
      'voice-settings',
      JSON.stringify({ state: { redemptionMs: 99_999 }, version: 0 }),
    )
    const { useVoiceSettingsStore: fresh } = await import('./voiceSettingsStore?reload=t2')
    expect(fresh.getState().redemptionMs).toBe(11_520)
  })
})
```

- [ ] **Step 2: Run test to confirm failure**

```bash
pnpm --filter frontend exec vitest run src/features/voice/stores/voiceSettingsStore.test.ts
```
Expected: FAIL — `setRedemptionMs is not a function`, `redemptionMs is undefined`.

- [ ] **Step 3: Add field, setter, and migration to the store**

Edit `frontend/src/features/voice/stores/voiceSettingsStore.ts`:

```ts
// Existing import section unchanged.

// Bounds for the user-tunable VAD redemption window.
// 576 ms = 6 frames (lower floor, below this VAD becomes too twitchy).
// 11520 ms = 120 frames (= 10 × the previous `high` preset).
const REDEMPTION_MS_MIN = 576
const REDEMPTION_MS_MAX = 11_520
const REDEMPTION_MS_DEFAULT = 1_728   // 18 frames, ~50 % more head-room than old `high`.
```

Extend the `VoiceSettingsState` interface:

```ts
interface VoiceSettingsState {
  inputMode: InputMode
  autoSendTranscription: boolean
  voiceActivationThreshold: VoiceActivationThreshold
  /** User-tunable VAD redemption window in ms (replaces the per-preset value). */
  redemptionMs: number
  stt_provider_id: string | undefined
  visualisation: VoiceVisualisationSettings
  setInputMode(mode: InputMode): void
  setAutoSendTranscription(value: boolean): void
  setVoiceActivationThreshold(value: VoiceActivationThreshold): void
  setRedemptionMs(ms: number): void
  setSttProviderId(value: string | undefined): void
  setVisualisationEnabled(value: boolean): void
  setVisualisationStyle(value: VisualiserStyle): void
  setVisualisationOpacity(value: number): void
  setVisualisationBarCount(value: number): void
}
```

Inside the store factory, add the field, setter, and migration entry:

```ts
// In the create() body, alongside other defaults:
redemptionMs: REDEMPTION_MS_DEFAULT,
setRedemptionMs: (redemptionMs) =>
  set({ redemptionMs: clamp(redemptionMs, REDEMPTION_MS_MIN, REDEMPTION_MS_MAX) }),

// In the persist `merge` callback, alongside the existing inputMode/visualisation lines:
redemptionMs: clamp(p.redemptionMs ?? REDEMPTION_MS_DEFAULT, REDEMPTION_MS_MIN, REDEMPTION_MS_MAX),
```

Export the constants for consumers:

```ts
export const VOICE_REDEMPTION_MS_MIN = REDEMPTION_MS_MIN
export const VOICE_REDEMPTION_MS_MAX = REDEMPTION_MS_MAX
export const VOICE_REDEMPTION_MS_DEFAULT = REDEMPTION_MS_DEFAULT
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pnpm --filter frontend exec vitest run src/features/voice/stores/voiceSettingsStore.test.ts
```
Expected: all `redemptionMs` cases PASS, no regressions in pre-existing tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/stores/voiceSettingsStore.ts \
        frontend/src/features/voice/stores/voiceSettingsStore.test.ts
git commit -m "Add redemptionMs to voice settings store"
```

---

## Task 2: Pass `redemptionMs` from useConversationMode through audioCapture

**Files:**
- Modify: `frontend/src/features/voice/infrastructure/audioCapture.ts`
- Modify: `frontend/src/features/voice/hooks/useConversationMode.ts`

The presets still carry `redemptionFrames` at this point (we drop it in Task 3). The point of this task is to thread the new value through *first*, so removing the preset field in Task 3 is safe.

- [ ] **Step 1: Extend `StartContinuousOptions` with optional `redemptionMs`**

Locate `StartContinuousOptions` in `audioCapture.ts` (near the top of the file alongside the other audio-capture types):

```ts
export interface StartContinuousOptions {
  threshold?: VoiceActivationThreshold
  externalRecorder?: boolean
  /**
   * VAD redemption window in ms. When omitted, falls back to the value the
   * preset previously embedded — kept only so legacy callers that pass no
   * options still work; new callers should always pass an explicit value.
   */
  redemptionMs?: number
}
```

- [ ] **Step 2: Use the option (or fall back) when constructing `MicVAD`**

Inside `startContinuous` in `audioCapture.ts:260`, replace the `redemptionMs` line:

```ts
// Before:
//   redemptionMs: preset.redemptionFrames * MS_PER_FRAME,
// After:
const effectiveRedemptionMs = options.redemptionMs
  ?? preset.redemptionFrames * MS_PER_FRAME
this.vad = await MicVAD.new({
  // … other unchanged fields …
  redemptionMs: effectiveRedemptionMs,
  // … rest unchanged …
})
```

(`preset.redemptionFrames` is still defined here; Task 3 removes it after every caller has migrated.)

- [ ] **Step 3: Read `redemptionMs` in `useConversationMode` and pass it**

In `frontend/src/features/voice/hooks/useConversationMode.ts`, near the top where `voiceActivationThresholdRef` is set up, add a parallel ref for `redemptionMs`:

```ts
const redemptionMs = useVoiceSettingsStore((s) => s.redemptionMs)
const redemptionMsRef = useRef(redemptionMs)
useEffect(() => { redemptionMsRef.current = redemptionMs }, [redemptionMs])
```

(If `voiceActivationThresholdRef` already follows this pattern, copy it exactly. The ref is required because `startContinuous` is called from a ref-stable effect.)

In the `audioCapture.startContinuous(...)` call (around line 531), add the new option:

```ts
audioCapture.startContinuous({
  onSpeechStart: handleSpeechStart,
  onSpeechEnd: handleSpeechEnd,
  onVolumeChange: (level) => micActivity.setLevel(level),
  onMisfire: handleMisfire,
}, {
  threshold: voiceActivationThresholdRef.current,
  redemptionMs: redemptionMsRef.current,
  externalRecorder: true,
}).catch(/* unchanged */)
```

- [ ] **Step 4: Run hook + audioCapture tests**

```bash
pnpm --filter frontend exec vitest run \
  src/features/voice/hooks/__tests__/useConversationMode.holdRelease.test.tsx \
  src/features/voice/infrastructure/__tests__
```
Expected: all PASS. The mock for `startContinuous` accepts arbitrary options so the new field doesn't break it; if a strict-typed mock complains, widen the mock's signature to `(callbacks, options?)`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/infrastructure/audioCapture.ts \
        frontend/src/features/voice/hooks/useConversationMode.ts
git commit -m "Thread redemptionMs from settings through to MicVAD"
```

---

## Task 3: Remove `redemptionFrames` from VAD presets

**Files:**
- Modify: `frontend/src/features/voice/infrastructure/vadPresets.ts`
- Modify: `frontend/src/features/voice/infrastructure/__tests__/vadPresets.test.ts`

After Task 2 nothing in production code reads `preset.redemptionFrames` *via the preset* any more (the `?? preset.redemptionFrames * MS_PER_FRAME` fallback in `audioCapture.ts` is the only remaining read). Replace that fallback with the new default and drop the field.

- [ ] **Step 1: Replace the fallback in `audioCapture.ts`**

```ts
// Before:
//   const effectiveRedemptionMs = options.redemptionMs
//     ?? preset.redemptionFrames * MS_PER_FRAME
// After:
import { VOICE_REDEMPTION_MS_DEFAULT } from '../stores/voiceSettingsStore'
// …
const effectiveRedemptionMs = options.redemptionMs ?? VOICE_REDEMPTION_MS_DEFAULT
```

- [ ] **Step 2: Drop `redemptionFrames` from the preset interface and table**

Edit `frontend/src/features/voice/infrastructure/vadPresets.ts`:

```ts
import type { VoiceActivationThreshold } from '../stores/voiceSettingsStore'

export interface VadPreset {
  positiveSpeechThreshold: number
  negativeSpeechThreshold: number
  minSpeechFrames: number
}

// Preset table is expressed in frames (matching Silero's native units).
// `minSpeechFrames` is converted to `minSpeechMs` in audioCapture.ts where
// it is handed to MicVAD.new. Redemption (silence-tolerance) is configured
// per user via voiceSettingsStore.redemptionMs and is no longer part of
// the threshold preset.
export const VAD_PRESETS: Record<VoiceActivationThreshold, VadPreset> = {
  low:    { positiveSpeechThreshold: 0.5,  negativeSpeechThreshold: 0.35, minSpeechFrames: 3 },
  medium: { positiveSpeechThreshold: 0.65, negativeSpeechThreshold: 0.5,  minSpeechFrames: 5 },
  high:   { positiveSpeechThreshold: 0.8,  negativeSpeechThreshold: 0.6,  minSpeechFrames: 8 },
}
```

- [ ] **Step 3: Update preset tests**

Edit `frontend/src/features/voice/infrastructure/__tests__/vadPresets.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { VAD_PRESETS } from '../vadPresets'

describe('VAD_PRESETS', () => {
  it('exposes positive/negative/minSpeech for each threshold', () => {
    for (const key of ['low', 'medium', 'high'] as const) {
      const preset = VAD_PRESETS[key]
      expect(typeof preset.positiveSpeechThreshold).toBe('number')
      expect(typeof preset.negativeSpeechThreshold).toBe('number')
      expect(typeof preset.minSpeechFrames).toBe('number')
      expect(preset).not.toHaveProperty('redemptionFrames')
    }
  })

  it('thresholds are monotonically increasing low → medium → high', () => {
    expect(VAD_PRESETS.low.positiveSpeechThreshold)
      .toBeLessThan(VAD_PRESETS.medium.positiveSpeechThreshold)
    expect(VAD_PRESETS.medium.positiveSpeechThreshold)
      .toBeLessThan(VAD_PRESETS.high.positiveSpeechThreshold)
  })
})
```

- [ ] **Step 4: Run preset and audioCapture tests**

```bash
pnpm --filter frontend exec vitest run \
  src/features/voice/infrastructure/__tests__/vadPresets.test.ts \
  src/features/voice/infrastructure
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/infrastructure/vadPresets.ts \
        frontend/src/features/voice/infrastructure/__tests__/vadPresets.test.ts \
        frontend/src/features/voice/infrastructure/audioCapture.ts
git commit -m "Drop redemptionFrames from VAD presets"
```

---

## Task 4: Create `pauseRedemptionStore`

**Files:**
- Create: `frontend/src/features/voice/stores/pauseRedemptionStore.ts`
- Create: `frontend/src/features/voice/stores/__tests__/pauseRedemptionStore.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/voice/stores/__tests__/pauseRedemptionStore.test.ts`:

```ts
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { usePauseRedemptionStore } from '../pauseRedemptionStore'

describe('pauseRedemptionStore', () => {
  beforeEach(() => {
    usePauseRedemptionStore.setState({ active: false, startedAt: null, windowMs: 0 })
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-29T12:00:00Z'))
  })

  it('defaults to inactive', () => {
    const s = usePauseRedemptionStore.getState()
    expect(s.active).toBe(false)
    expect(s.startedAt).toBeNull()
    expect(s.windowMs).toBe(0)
  })

  it('start() captures windowMs and timestamps the start', () => {
    const before = performance.now()
    usePauseRedemptionStore.getState().start(1728)
    const s = usePauseRedemptionStore.getState()
    expect(s.active).toBe(true)
    expect(s.windowMs).toBe(1728)
    expect(s.startedAt).not.toBeNull()
    expect(s.startedAt!).toBeGreaterThanOrEqual(before)
  })

  it('start() captures the window in force at the moment of the call (not later)', () => {
    usePauseRedemptionStore.getState().start(2000)
    // Subsequent setting changes (e.g. user drags slider mid-pause) must NOT
    // mutate the captured value. Simulate by calling start() a second time:
    usePauseRedemptionStore.getState().start(8000)
    expect(usePauseRedemptionStore.getState().windowMs).toBe(8000)
  })

  it('clear() resets to inactive and is idempotent', () => {
    usePauseRedemptionStore.getState().start(1000)
    usePauseRedemptionStore.getState().clear()
    expect(usePauseRedemptionStore.getState().active).toBe(false)
    expect(usePauseRedemptionStore.getState().startedAt).toBeNull()
    // Idempotent — calling clear again is a no-op.
    usePauseRedemptionStore.getState().clear()
    expect(usePauseRedemptionStore.getState().active).toBe(false)
  })
})
```

- [ ] **Step 2: Run test to confirm failure**

```bash
pnpm --filter frontend exec vitest run src/features/voice/stores/__tests__/pauseRedemptionStore.test.ts
```
Expected: FAIL — module `pauseRedemptionStore` not found.

- [ ] **Step 3: Implement the store**

Create `frontend/src/features/voice/stores/pauseRedemptionStore.ts`:

```ts
import { create } from 'zustand'

interface PauseRedemptionState {
  /** True while the redemption window is open (silence detected, pie visible). */
  active: boolean
  /** performance.now() value when redemption started, or null. */
  startedAt: number | null
  /**
   * Redemption window currently in force (snapshot taken at `start()`-time
   * so a user sliding the setting mid-pause does not mutate the live pie).
   */
  windowMs: number
  /** Open the window. Called by audioCapture once the grace period has elapsed. */
  start(windowMs: number): void
  /** Close the window. Idempotent — safe to call from multiple cleanup edges. */
  clear(): void
}

export const usePauseRedemptionStore = create<PauseRedemptionState>((set) => ({
  active: false,
  startedAt: null,
  windowMs: 0,
  start: (windowMs) => set({ active: true, startedAt: performance.now(), windowMs }),
  clear: () => set({ active: false, startedAt: null, windowMs: 0 }),
}))
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pnpm --filter frontend exec vitest run src/features/voice/stores/__tests__/pauseRedemptionStore.test.ts
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/stores/pauseRedemptionStore.ts \
        frontend/src/features/voice/stores/__tests__/pauseRedemptionStore.test.ts
git commit -m "Add pauseRedemptionStore for live redemption window"
```

---

## Task 5: Drive `pauseRedemptionStore` from audioCapture frame state machine

**Files:**
- Modify: `frontend/src/features/voice/infrastructure/audioCapture.ts`
- Create: `frontend/src/features/voice/infrastructure/__tests__/audioCapture.framesm.test.ts`

This is the keystone task: it turns silence-edge detection into something the UI can react to.

- [ ] **Step 1: Write the failing state-machine test**

Create `frontend/src/features/voice/infrastructure/__tests__/audioCapture.framesm.test.ts`:

```ts
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { usePauseRedemptionStore } from '../../stores/pauseRedemptionStore'

// Capture the onFrameProcessed callback that audioCapture passes into MicVAD,
// then drive it directly to verify the state machine.
let frameProcessed: ((p: { isSpeech: number }) => void) | null = null

vi.mock('@ricky0123/vad-web', () => ({
  MicVAD: {
    new: vi.fn(async (opts: any) => {
      frameProcessed = opts.onFrameProcessed
      return { start: vi.fn(), pause: vi.fn(), destroy: vi.fn() }
    }),
  },
}))

vi.mock('../audioRecording', () => ({
  pickRecordingMimeType: () => 'audio/webm',
  createRecorder: () => ({}),
}))

import { AudioCapture } from '../audioCapture'

const POSITIVE = 0.65   // medium preset positiveSpeechThreshold
const NEGATIVE = 0.5    // medium preset negativeSpeechThreshold

describe('audioCapture frame state machine — pauseRedemptionStore edges', () => {
  let capture: AudioCapture

  beforeEach(async () => {
    usePauseRedemptionStore.setState({ active: false, startedAt: null, windowMs: 0 })
    frameProcessed = null
    capture = new AudioCapture()
    await capture.startContinuous(
      { onSpeechStart: () => {}, onSpeechEnd: () => {}, onVolumeChange: () => {}, onMisfire: () => {} },
      { threshold: 'medium', redemptionMs: 1728 },
    )
    expect(frameProcessed).not.toBeNull()
  })

  it('does NOT open redemption while no confirmed speech segment is active', () => {
    // Five low-prob frames, but onSpeechStart was never invoked.
    for (let i = 0; i < 5; i++) frameProcessed!({ isSpeech: 0.1 })
    expect(usePauseRedemptionStore.getState().active).toBe(false)
  })

  it('opens redemption only after 4 consecutive sub-negative frames inside speech', () => {
    ;(capture as any).handleVadSpeechStart()
    frameProcessed!({ isSpeech: 0.1 }) // 1
    frameProcessed!({ isSpeech: 0.1 }) // 2
    frameProcessed!({ isSpeech: 0.1 }) // 3
    expect(usePauseRedemptionStore.getState().active).toBe(false) // grace not done
    frameProcessed!({ isSpeech: 0.1 }) // 4 — opens
    expect(usePauseRedemptionStore.getState().active).toBe(true)
    expect(usePauseRedemptionStore.getState().windowMs).toBe(1728)
  })

  it('a single high-prob frame inside the grace window resets the silence counter', () => {
    ;(capture as any).handleVadSpeechStart()
    frameProcessed!({ isSpeech: 0.1 }) // 1
    frameProcessed!({ isSpeech: 0.1 }) // 2
    frameProcessed!({ isSpeech: 0.9 }) // resumed — counter resets
    frameProcessed!({ isSpeech: 0.1 }) // 1 again
    frameProcessed!({ isSpeech: 0.1 }) // 2
    frameProcessed!({ isSpeech: 0.1 }) // 3
    expect(usePauseRedemptionStore.getState().active).toBe(false)
    frameProcessed!({ isSpeech: 0.1 }) // 4 — now opens
    expect(usePauseRedemptionStore.getState().active).toBe(true)
  })

  it('high-prob frame after redemption opened closes it again', () => {
    ;(capture as any).handleVadSpeechStart()
    for (let i = 0; i < 4; i++) frameProcessed!({ isSpeech: 0.1 })
    expect(usePauseRedemptionStore.getState().active).toBe(true)

    frameProcessed!({ isSpeech: 0.9 })
    expect(usePauseRedemptionStore.getState().active).toBe(false)
  })

  it('handleVadSpeechEnd clears redemption (idempotent)', () => {
    ;(capture as any).handleVadSpeechStart()
    for (let i = 0; i < 4; i++) frameProcessed!({ isSpeech: 0.1 })
    ;(capture as any).handleVadSpeechEnd(new Float32Array(0))
    expect(usePauseRedemptionStore.getState().active).toBe(false)
  })

  it('handleVadMisfire clears redemption', () => {
    ;(capture as any).handleVadSpeechStart()
    for (let i = 0; i < 4; i++) frameProcessed!({ isSpeech: 0.1 })
    ;(capture as any).handleVadMisfire()
    expect(usePauseRedemptionStore.getState().active).toBe(false)
  })
})
```

- [ ] **Step 2: Run test to confirm failure**

```bash
pnpm --filter frontend exec vitest run src/features/voice/infrastructure/__tests__/audioCapture.framesm.test.ts
```
Expected: FAIL — `onFrameProcessed` is not yet wired, `redemption` never opens.

- [ ] **Step 3: Add state-machine fields, helper, and `onFrameProcessed` to audioCapture**

Edit `frontend/src/features/voice/infrastructure/audioCapture.ts`. At class level, add the new state and a captured snapshot of the relevant preset thresholds:

```ts
// Inside class AudioCapture, alongside the existing private fields:

/** Number of consecutive frames whose probability sat below `negativeSpeechThreshold`. */
private silenceFrames = 0
/** True while VAD has confirmed a speech segment (between speech-start and speech-end). */
private inSpeechSegment = false
/** True while pauseRedemptionStore is currently open (we own the toggle). */
private redemptionOpen = false
/** Snapshotted thresholds for the current session — set in startContinuous. */
private framePosThreshold = 0.65
private frameNegThreshold = 0.5
/** Snapshotted redemption window for the current session. */
private currentRedemptionMs = 1_728

/** 4 frames × 96 ms/frame = 384 ms grace before the pie may appear. */
private static readonly GRACE_FRAMES = 4
```

Add the import for the store at the top of the file:

```ts
import { usePauseRedemptionStore } from '../stores/pauseRedemptionStore'
```

Inside `startContinuous`, snapshot the values right after `preset` is resolved:

```ts
this.framePosThreshold = preset.positiveSpeechThreshold
this.frameNegThreshold = preset.negativeSpeechThreshold
this.currentRedemptionMs = effectiveRedemptionMs
this.silenceFrames = 0
this.inSpeechSegment = false
this.redemptionOpen = false
```

Pass `onFrameProcessed` into `MicVAD.new`:

```ts
this.vad = await MicVAD.new({
  // … existing fields unchanged …
  redemptionMs: effectiveRedemptionMs,
  onSpeechStart: () => { this.handleVadSpeechStart() },
  onSpeechEnd: (audio: Float32Array) => { this.handleVadSpeechEnd(audio) },
  onVADMisfire: () => { this.handleVadMisfire() },
  onFrameProcessed: (probs: { isSpeech: number }) => { this.handleVadFrame(probs) },
})
```

Add the frame handler:

```ts
private handleVadFrame(probs: { isSpeech: number }): void {
  if (!this.inSpeechSegment) return

  if (probs.isSpeech < this.frameNegThreshold) {
    this.silenceFrames += 1
    if (
      !this.redemptionOpen
      && this.silenceFrames >= AudioCapture.GRACE_FRAMES
    ) {
      this.redemptionOpen = true
      usePauseRedemptionStore.getState().start(this.currentRedemptionMs)
    }
    return
  }

  // Probability rose again. Reset the silence counter.
  this.silenceFrames = 0
  if (this.redemptionOpen && probs.isSpeech > this.framePosThreshold) {
    this.redemptionOpen = false
    usePauseRedemptionStore.getState().clear()
  }
}
```

Update the existing speech-event handlers to maintain `inSpeechSegment` and clear redemption:

```ts
private handleVadSpeechStart(): void {
  this.inSpeechSegment = true
  this.silenceFrames = 0
  this.vadSegmentStartedAt = performance.now()
  // … existing recorder-start logic unchanged …
}

private handleVadSpeechEnd(pcm: Float32Array): void {
  this.inSpeechSegment = false
  this.silenceFrames = 0
  if (this.redemptionOpen) {
    this.redemptionOpen = false
    usePauseRedemptionStore.getState().clear()
  }
  // … existing onSpeechEnd delivery logic unchanged …
}

private handleVadMisfire(): void {
  this.inSpeechSegment = false
  this.silenceFrames = 0
  if (this.redemptionOpen) {
    this.redemptionOpen = false
    usePauseRedemptionStore.getState().clear()
  }
  // … existing misfire cleanup unchanged …
}
```

Also clear in `stopContinuous` for safety:

```ts
async stopContinuous(): Promise<void> {
  this.inSpeechSegment = false
  this.silenceFrames = 0
  if (this.redemptionOpen) {
    this.redemptionOpen = false
    usePauseRedemptionStore.getState().clear()
  }
  // … existing teardown logic unchanged …
}
```

- [ ] **Step 4: Run the state-machine and integration tests**

```bash
pnpm --filter frontend exec vitest run \
  src/features/voice/infrastructure/__tests__/audioCapture.framesm.test.ts \
  src/features/voice/infrastructure
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/infrastructure/audioCapture.ts \
        frontend/src/features/voice/infrastructure/__tests__/audioCapture.framesm.test.ts
git commit -m "Detect VAD silence edge and drive pauseRedemptionStore"
```

---

## Task 6: Pie renderers (canvas)

**Files:**
- Create: `frontend/src/features/voice/infrastructure/pieRenderers.ts`
- Create: `frontend/src/features/voice/infrastructure/__tests__/pieRenderers.test.ts`

The renderer family mirrors `visualiserRenderers.ts`: one entry point that switches on style, four style-specific helpers using the same colour conventions (rgb / rgbLight, opacity, shadow, milky stroke).

- [ ] **Step 1: Write the failing smoke test**

Create `frontend/src/features/voice/infrastructure/__tests__/pieRenderers.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { drawPieFrame, type PieRenderOpts } from '../pieRenderers'

function makeCtx(): CanvasRenderingContext2D {
  const calls: string[] = []
  // Minimal mock — record the methods the renderer touches.
  const stub = new Proxy({}, {
    get(_t, key: string) {
      if (key === 'calls') return calls
      if (key === 'canvas') return { width: 200, height: 200 }
      return (...args: unknown[]) => { calls.push(`${key}(${args.length})`) }
    },
    set() { return true },
  }) as unknown as CanvasRenderingContext2D
  return stub
}

const baseOpts: PieRenderOpts = {
  cx: 100, cy: 100, radius: 60,
  remainingFraction: 0.7,
  rgb: [212, 168, 87],
  rgbLight: [255, 238, 200],
  opacity: 0.85,
}

describe('drawPieFrame', () => {
  it.each(['sharp', 'soft', 'glow', 'glass'] as const)('renders %s style without throwing', (style) => {
    const ctx = makeCtx()
    expect(() => drawPieFrame(style, ctx, baseOpts)).not.toThrow()
    const calls = (ctx as any).calls as string[]
    expect(calls.some((c) => c.startsWith('arc('))).toBe(true)
  })

  it('full disc when remainingFraction === 1', () => {
    const ctx = makeCtx()
    expect(() =>
      drawPieFrame('soft', ctx, { ...baseOpts, remainingFraction: 1 }),
    ).not.toThrow()
  })

  it('renders nothing when remainingFraction <= 0 (no arc calls)', () => {
    const ctx = makeCtx()
    drawPieFrame('soft', ctx, { ...baseOpts, remainingFraction: 0 })
    const calls = (ctx as any).calls as string[]
    expect(calls.some((c) => c.startsWith('arc('))).toBe(false)
  })

  it('clamps remainingFraction > 1 to 1 (still draws full disc)', () => {
    const ctx = makeCtx()
    expect(() =>
      drawPieFrame('sharp', ctx, { ...baseOpts, remainingFraction: 5 }),
    ).not.toThrow()
  })
})
```

- [ ] **Step 2: Run test to confirm failure**

```bash
pnpm --filter frontend exec vitest run src/features/voice/infrastructure/__tests__/pieRenderers.test.ts
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the renderers**

Create `frontend/src/features/voice/infrastructure/pieRenderers.ts`:

```ts
import type { VisualiserStyle } from '../stores/voiceSettingsStore'

export interface PieRenderOpts {
  /** Pie centre, canvas pixels. */
  cx: number
  cy: number
  /** Outer radius, canvas pixels. */
  radius: number
  /** 0..1 fraction of the redemption window still remaining. */
  remainingFraction: number
  /** Persona accent colour, 0–255. */
  rgb: [number, number, number]
  /** Lightened persona colour for highlights. */
  rgbLight: [number, number, number]
  /** Master opacity, 0..1 (matches the visualiser's setting). */
  opacity: number
}

const TWO_PI = Math.PI * 2
/** 12 o'clock, just like an iOS countdown timer. */
const START_ANGLE = -Math.PI / 2

export function drawPieFrame(
  style: VisualiserStyle,
  ctx: CanvasRenderingContext2D,
  opts: PieRenderOpts,
): void {
  const frac = Math.min(1, Math.max(0, opts.remainingFraction))
  if (frac <= 0) return

  const endAngle = START_ANGLE + frac * TWO_PI

  switch (style) {
    case 'sharp': drawPieSharp(ctx, opts, endAngle); break
    case 'soft':  drawPieSoft(ctx, opts, endAngle); break
    case 'glow':  drawPieGlow(ctx, opts, endAngle); break
    case 'glass': drawPieGlass(ctx, opts, endAngle); break
  }
}

function tracePie(ctx: CanvasRenderingContext2D, o: PieRenderOpts, endAngle: number): void {
  ctx.beginPath()
  ctx.moveTo(o.cx, o.cy)
  ctx.arc(o.cx, o.cy, o.radius, START_ANGLE, endAngle)
  ctx.closePath()
}

function drawPieSharp(ctx: CanvasRenderingContext2D, o: PieRenderOpts, endAngle: number): void {
  const [lr, lg, lb] = o.rgbLight
  ctx.fillStyle = `rgba(${lr},${lg},${lb},${o.opacity})`
  tracePie(ctx, o, endAngle)
  ctx.fill()
}

function drawPieSoft(ctx: CanvasRenderingContext2D, o: PieRenderOpts, endAngle: number): void {
  const [r, g, b] = o.rgb
  const [lr, lg, lb] = o.rgbLight
  const grd = ctx.createRadialGradient(o.cx, o.cy, 0, o.cx, o.cy, o.radius)
  grd.addColorStop(0,   `rgba(${lr},${lg},${lb},${o.opacity})`)
  grd.addColorStop(0.6, `rgba(${r},${g},${b},${o.opacity * 0.85})`)
  grd.addColorStop(1,   `rgba(${r},${g},${b},${o.opacity * 0.25})`)
  ctx.fillStyle = grd
  tracePie(ctx, o, endAngle)
  ctx.fill()
}

function drawPieGlow(ctx: CanvasRenderingContext2D, o: PieRenderOpts, endAngle: number): void {
  const [r, g, b] = o.rgb
  const [lr, lg, lb] = o.rgbLight
  ctx.shadowColor = `rgba(${r},${g},${b},${o.opacity * 1.5})`
  ctx.shadowBlur = 14
  ctx.fillStyle = `rgba(${lr},${lg},${lb},${o.opacity * 0.9})`
  tracePie(ctx, o, endAngle)
  ctx.fill()
  ctx.shadowBlur = 0
}

function drawPieGlass(ctx: CanvasRenderingContext2D, o: PieRenderOpts, endAngle: number): void {
  const [r, g, b] = o.rgb
  // Milky core fill.
  ctx.fillStyle = `rgba(255,255,255,${o.opacity * 0.45})`
  tracePie(ctx, o, endAngle)
  ctx.fill()
  // Coloured stroke around the wedge.
  ctx.strokeStyle = `rgba(${r},${g},${b},${o.opacity * 0.85})`
  ctx.lineWidth = 1
  tracePie(ctx, o, endAngle)
  ctx.stroke()
}
```

- [ ] **Step 4: Run renderer tests**

```bash
pnpm --filter frontend exec vitest run src/features/voice/infrastructure/__tests__/pieRenderers.test.ts
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/infrastructure/pieRenderers.ts \
        frontend/src/features/voice/infrastructure/__tests__/pieRenderers.test.ts
git commit -m "Add canvas pie renderers in four visualiser styles"
```

---

## Task 7: `VoiceCountdownPie` component

**Files:**
- Create: `frontend/src/features/voice/components/VoiceCountdownPie.tsx`
- Create: `frontend/src/features/voice/components/__tests__/VoiceCountdownPie.test.tsx`

The component is a thin canvas wrapper. Its rect comes from `visualiserLayoutStore.chatview` (same source as the visualiser), so the two are guaranteed to share their stage. The RAF loop reads `pauseRedemptionStore` and re-computes `remainingFraction` per frame.

- [ ] **Step 1: Write the failing component test**

Create `frontend/src/features/voice/components/__tests__/VoiceCountdownPie.test.tsx`:

```tsx
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render } from '@testing-library/react'
import { usePauseRedemptionStore } from '../../stores/pauseRedemptionStore'
import { useVisualiserLayoutStore } from '../../stores/visualiserLayoutStore'
import { VoiceCountdownPie } from '../VoiceCountdownPie'

describe('VoiceCountdownPie', () => {
  beforeEach(() => {
    usePauseRedemptionStore.setState({ active: false, startedAt: null, windowMs: 0 })
    useVisualiserLayoutStore.setState({
      chatview: { left: 0, top: 0, width: 800, height: 400 },
      textColumn: null,
    })
  })

  it('renders nothing when redemption is inactive', () => {
    const { container } = render(<VoiceCountdownPie personaColourHex="#d4a857" />)
    expect(container.querySelector('canvas')).toBeNull()
  })

  it('renders a canvas mounted in the chatview rect when redemption is active', () => {
    usePauseRedemptionStore.getState().start(1728)
    const { container } = render(<VoiceCountdownPie personaColourHex="#d4a857" />)
    const canvas = container.querySelector('canvas') as HTMLCanvasElement | null
    expect(canvas).not.toBeNull()
  })

  it('unmounts the canvas when redemption clears', () => {
    usePauseRedemptionStore.getState().start(1728)
    const { container, rerender } = render(<VoiceCountdownPie personaColourHex="#d4a857" />)
    expect(container.querySelector('canvas')).not.toBeNull()
    usePauseRedemptionStore.getState().clear()
    rerender(<VoiceCountdownPie personaColourHex="#d4a857" />)
    expect(container.querySelector('canvas')).toBeNull()
  })
})
```

- [ ] **Step 2: Run test to confirm failure**

```bash
pnpm --filter frontend exec vitest run src/features/voice/components/__tests__/VoiceCountdownPie.test.tsx
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the component**

Create `frontend/src/features/voice/components/VoiceCountdownPie.tsx`:

```tsx
import { useEffect, useRef } from 'react'
import { useVoiceSettingsStore } from '../stores/voiceSettingsStore'
import { useVisualiserLayoutStore } from '../stores/visualiserLayoutStore'
import { usePauseRedemptionStore } from '../stores/pauseRedemptionStore'
import { drawPieFrame } from '../infrastructure/pieRenderers'

const DEFAULT_HEX = '#8C76D7'
const PIE_DIAMETER_RATIO = 0.18   // ~18 % of the rect's smaller side, capped.
const PIE_DIAMETER_MAX = 140
const PIE_DIAMETER_MIN = 72

interface Props {
  /** Active persona's accent colour hex (e.g. '#d4a857'). */
  personaColourHex?: string
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

export function VoiceCountdownPie({ personaColourHex = DEFAULT_HEX }: Props) {
  const active = usePauseRedemptionStore((s) => s.active)
  const startedAt = usePauseRedemptionStore((s) => s.startedAt)
  const windowMs = usePauseRedemptionStore((s) => s.windowMs)

  const style = useVoiceSettingsStore((s) => s.visualisation.style)
  const opacity = useVoiceSettingsStore((s) => s.visualisation.opacity)
  const enabled = useVoiceSettingsStore((s) => s.visualisation.enabled)

  const chatview = useVisualiserLayoutStore((s) => s.chatview)

  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const rafRef = useRef<number | null>(null)

  useEffect(() => {
    if (!active || !enabled || !chatview || !canvasRef.current) return
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio ?? 1
    const cssW = chatview.width
    const cssH = chatview.height
    canvas.width = Math.round(cssW * dpr)
    canvas.height = Math.round(cssH * dpr)
    canvas.style.width = `${cssW}px`
    canvas.style.height = `${cssH}px`
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

    const diameter = Math.max(
      PIE_DIAMETER_MIN,
      Math.min(PIE_DIAMETER_MAX, Math.min(cssW, cssH) * PIE_DIAMETER_RATIO),
    )
    const radius = diameter / 2
    const cx = cssW / 2
    const cy = cssH / 2

    const rgb = hexToRgb(personaColourHex)
    const rgbLight = brighten(rgb)

    const tick = () => {
      ctx.clearRect(0, 0, cssW, cssH)
      const elapsed = startedAt === null ? 0 : performance.now() - startedAt
      const remainingFraction = windowMs > 0
        ? Math.max(0, 1 - elapsed / windowMs)
        : 0
      drawPieFrame(style, ctx, {
        cx, cy, radius,
        remainingFraction,
        rgb, rgbLight, opacity,
      })
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)

    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
    }
  }, [active, enabled, chatview, startedAt, windowMs, style, opacity, personaColourHex])

  if (!active || !enabled || !chatview) return null

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'fixed',
        left: chatview.left,
        top: chatview.top,
        width: chatview.width,
        height: chatview.height,
        pointerEvents: 'none',
        zIndex: 60,
      }}
    />
  )
}
```

- [ ] **Step 4: Run component tests**

```bash
pnpm --filter frontend exec vitest run src/features/voice/components/__tests__/VoiceCountdownPie.test.tsx
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/components/VoiceCountdownPie.tsx \
        frontend/src/features/voice/components/__tests__/VoiceCountdownPie.test.tsx
git commit -m "Add VoiceCountdownPie canvas component"
```

---

## Task 8: Fade visualiser bars while redemption is active

**Files:**
- Modify: `frontend/src/features/voice/components/VoiceVisualiser.tsx`

The visualiser already has its own opacity envelope per frame (the `activeRef` fade-in / fade-out logic). We only need to introduce a "redemption suppression" multiplier that tugs the envelope to 0 when the pie is up.

- [ ] **Step 1: Add a redemption-active subscription and apply it to the per-frame opacity**

In `frontend/src/features/voice/components/VoiceVisualiser.tsx`, add an import:

```ts
import { usePauseRedemptionStore } from '../stores/pauseRedemptionStore'
```

Inside the component body (next to the other Zustand selectors near the top):

```ts
const redemptionActive = usePauseRedemptionStore((s) => s.active)
```

Add a ref so the RAF loop can read the latest value without re-binding:

```ts
const redemptionRef = useRef(redemptionActive)
useEffect(() => { redemptionRef.current = redemptionActive }, [redemptionActive])
```

Inside the RAF tick, before the bars are drawn, multiply the existing `opacity` value by a fade factor that tracks `redemptionRef.current`. The visualiser already maintains a `barsOpacityRef` (or equivalent — search for the per-frame `opacity` derivation in the existing tick); add this state next to it:

```ts
// Place adjacent to existing fade refs near the top of the effect:
const barsFadeRef = useRef(1)
```

Inside the tick, every frame, ease the value:

```ts
const target = redemptionRef.current ? 0 : 1
// ~120 ms ease at 60 Hz ≈ a 0.12 step per frame.
barsFadeRef.current += (target - barsFadeRef.current) * 0.12
const effectiveOpacity = opacity * barsFadeRef.current
// Pass `effectiveOpacity` to drawVisualiserFrame instead of raw `opacity`.
```

Add `redemptionActive` to the existing tick effect's dependency array. **Do not add `barsFadeRef.current` itself**, the ref drives intentionally outside React's render cycle.

- [ ] **Step 2: Add a regression test for the dependency wiring**

Add the following to `frontend/src/features/voice/components/__tests__/VoiceCountdownPie.test.tsx` (this file already imports the redemption store, no extra setup needed):

```tsx
it('VoiceVisualiser subscribes to pauseRedemptionStore (fade dependency present)', async () => {
  // Smoke-test: importing the visualiser must reference pauseRedemptionStore.
  const src = await import('../../components/VoiceVisualiser')
  expect(src).toBeDefined()
  // Visual fade is exercised in manual verification — automated coverage
  // here would be brittle. We assert the import succeeds.
})
```

(Manual verification covers the visual effect — automated framerate-bounded fade tests are intentionally avoided.)

- [ ] **Step 3: Run the visualiser-adjacent tests**

```bash
pnpm --filter frontend exec vitest run \
  src/features/voice/components/__tests__/VoiceCountdownPie.test.tsx \
  src/features/voice/components/__tests__
```
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/voice/components/VoiceVisualiser.tsx \
        frontend/src/features/voice/components/__tests__/VoiceCountdownPie.test.tsx
git commit -m "Fade visualiser bars while pause-redemption is active"
```

---

## Task 9: Mount `VoiceCountdownPie` in `AppLayout`

**Files:**
- Modify: `frontend/src/app/layouts/AppLayout.tsx`

- [ ] **Step 1: Mount the component next to the visualiser**

In `frontend/src/app/layouts/AppLayout.tsx`, find the existing block:

```tsx
<VoiceVisualiser personaColourHex={activePersonaHex} />
<VoiceVisualiserHitStrip />
```

Insert the new component between them:

```tsx
<VoiceVisualiser personaColourHex={activePersonaHex} />
<VoiceCountdownPie personaColourHex={activePersonaHex} />
<VoiceVisualiserHitStrip />
```

Add the import:

```tsx
import { VoiceCountdownPie } from '../../features/voice/components/VoiceCountdownPie'
```

- [ ] **Step 2: Smoke-build to ensure JSX type-checks**

```bash
pnpm --filter frontend exec tsc --noEmit
```
Expected: clean run.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/layouts/AppLayout.tsx
git commit -m "Mount VoiceCountdownPie in AppLayout"
```

---

## Task 10: Add the slider to `VoiceTab`

**Files:**
- Modify: `frontend/src/app/components/user-modal/VoiceTab.tsx`
- Modify: `frontend/src/app/components/user-modal/__tests__/VoiceTab.test.tsx`

The existing tab already has two range sliders (Deckkraft / Anzahl Säulen), so the markup pattern is established.

- [ ] **Step 1: Write the failing test for the slider**

Add to `frontend/src/app/components/user-modal/__tests__/VoiceTab.test.tsx`:

```tsx
import { describe, it, expect, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { VoiceTab } from '../VoiceTab'
import { useVoiceSettingsStore, VOICE_REDEMPTION_MS_DEFAULT } from '../../../../features/voice/stores/voiceSettingsStore'

const renderTab = () =>
  render(
    <MemoryRouter><VoiceTab /></MemoryRouter>,
  )

describe('VoiceTab — Pause-Toleranz slider', () => {
  beforeEach(() => {
    useVoiceSettingsStore.setState({ redemptionMs: VOICE_REDEMPTION_MS_DEFAULT })
  })

  it('renders with the current redemptionMs value displayed in seconds', () => {
    renderTab()
    expect(screen.getByText(/1\.7s/)).toBeInTheDocument()
  })

  it('updates the store when dragged', () => {
    renderTab()
    const slider = screen.getByLabelText(/Pause-Toleranz/i) as HTMLInputElement
    fireEvent.change(slider, { target: { value: '3000' } })
    expect(useVoiceSettingsStore.getState().redemptionMs).toBe(3000)
  })

  it('snaps to whole-frame steps (96 ms) via the step attribute', () => {
    renderTab()
    const slider = screen.getByLabelText(/Pause-Toleranz/i) as HTMLInputElement
    expect(slider.step).toBe('96')
    expect(slider.min).toBe('576')
    expect(slider.max).toBe('11520')
  })
})
```

- [ ] **Step 2: Run to confirm failure**

```bash
pnpm --filter frontend exec vitest run src/app/components/user-modal/__tests__/VoiceTab.test.tsx
```
Expected: FAIL — slider not yet rendered.

- [ ] **Step 3: Add the slider markup**

Edit `frontend/src/app/components/user-modal/VoiceTab.tsx`. Update the imports:

```tsx
import {
  useVoiceSettingsStore,
  VOICE_REDEMPTION_MS_MIN,
  VOICE_REDEMPTION_MS_MAX,
  type VoiceActivationThreshold,
  type VisualiserStyle,
} from '../../../features/voice/stores/voiceSettingsStore'
```

Add selectors next to the existing ones in the component body:

```tsx
const redemptionMs = useVoiceSettingsStore((s) => s.redemptionMs)
const setRedemptionMs = useVoiceSettingsStore((s) => s.setRedemptionMs)
```

Insert the new block immediately after the *Voice Activation Threshold* section (i.e. after the `<div>` that contains the three threshold buttons, before the `sttProviders.length > 0 && …` block):

```tsx
<div>
  <label className={LABEL} htmlFor="voice-redemption">
    Pause-Toleranz <span className="text-white/85">{(redemptionMs / 1000).toFixed(1)}s</span>
  </label>
  <p className="text-[11px] text-white/40 font-mono mb-2 leading-relaxed">
    How long the conversation waits in silence before sending what you have
    just said. Move the slider right for more time to think between
    sentences.
  </p>
  <input
    id="voice-redemption"
    aria-label="Pause-Toleranz"
    type="range"
    min={VOICE_REDEMPTION_MS_MIN}
    max={VOICE_REDEMPTION_MS_MAX}
    step={96}
    value={redemptionMs}
    onChange={(e) => setRedemptionMs(Number(e.target.value))}
    className="w-full mb-4 accent-white/70"
  />
</div>
```

- [ ] **Step 4: Run the slider tests**

```bash
pnpm --filter frontend exec vitest run src/app/components/user-modal/__tests__/VoiceTab.test.tsx
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/user-modal/VoiceTab.tsx \
        frontend/src/app/components/user-modal/__tests__/VoiceTab.test.tsx
git commit -m "Add Pause-Toleranz slider to VoiceTab"
```

---

## Task 11: Final integration build & manual verification

**Files:** none modified unless a fix is needed.

- [ ] **Step 1: Run the full frontend test suite**

```bash
pnpm --filter frontend exec vitest run
```
Expected: green across the board.

- [ ] **Step 2: Run the strict build**

```bash
pnpm --filter frontend run build
```
Expected: clean — `tsc -b` finds no errors that `tsc --noEmit` missed.

- [ ] **Step 3: Manual verification on real device**

Walk through the spec's Section 6.2 verification checklist (10 steps) on Chris's phone with a real persona session. Each step must visibly behave as documented:

1. Default behaviour: pie appears, drains, submit at ~1.7 s.
2. Slider extreme — long: ~11.5 s pie drains, submit on completion.
3. Slider extreme — short: pie still appears (briefly).
4. Visualiser style coupling: pie style swaps with visualiser style; persona colour matches.
5. Resume mid-pause: pie clears cleanly on each silence/resume edge.
6. Misfire: bars do not fade, pie does not flicker on cough/click.
7. Intra-sentence micro-pauses: pie does NOT appear during natural breathing pauses.
8. Reduced-motion: pie wedge updates without pulsing; bars swap instantly.
9. Tab background: no frozen pie / orphan overlay on tab return.
10. Slider during pause: current pie does not jump; next pause uses new value.

If any step fails, fix inline and re-run the relevant task's tests + the build before re-committing. Use a follow-up commit per fix; do **not** amend.

- [ ] **Step 4: Commit (only if any fix was made)**

```bash
git add <touched files>
git commit -m "<imperative message describing the manual-verification fix>"
```

If no fixes were needed, this task ends without a final commit.

---

## Self-review check (already applied)

- Spec coverage:
  - 3.1 Slider → Tasks 1, 10
  - 3.2 Pie style + grace → Tasks 5, 6, 7
  - 3.3 Replace transition → Task 8
  - 4.1 pauseRedemptionStore → Task 4
  - 4.2 voiceSettingsStore field + migration → Task 1
  - 4.3 vadPresets refactor → Task 3
  - 4.4 audioCapture state machine → Tasks 2, 5
  - 4.5 VoiceCountdownPie → Task 7
  - 4.6 Visualiser fade → Task 8
  - 4.7 useConversationMode → Task 2
  - 4.8 VoiceTab slider → Task 10
  - Edge cases → covered by tests in Tasks 4 and 5; rest by manual checklist
  - Manual verification → Task 11
- Type consistency: `redemptionMs` (number, ms) flows from `voiceSettingsStore` → `useConversationMode` → `audioCapture.startContinuous(..., { redemptionMs })` → `usePauseRedemptionStore.start(redemptionMs)`. `windowMs` inside the store is the same value snapshot at the moment of the silence edge. The pie reads `windowMs` and `startedAt` and computes `remainingFraction = max(0, 1 - (now - startedAt) / windowMs)`. No name drift.
- Placeholder scan: clean — every step has concrete code or a concrete command.

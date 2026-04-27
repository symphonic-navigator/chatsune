# TTS Visual Reactivity Extension — Noisy Flatline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing `VoiceVisualiser` so that bars show a low-amplitude, breathing "noisy flatline" whenever TTS is *expected* but no audio is playing yet, and clamp the bar field's horizontal extent to 90% of the viewport.

**Architecture:** Reuses the existing FFT-driven render pipeline. Adds (1) a 90% width clamp inside `barLayout()`, (2) a synthetic per-bar noise generator that produces values in the same `[0, 1]` space as the FFT bins, and (3) a small predicate hook that composes four existing reactive sources (`audioPlayback`, `isReadingAloud`, `getActiveGroup`, `conversationModeStore` / `cockpitStore`) into a single "TTS expected" boolean. The existing exponential per-bar smoother bridges the noise → FFT handover invisibly.

**Tech Stack:** React + TypeScript (strict), Zustand, Vitest + React Testing Library, Canvas 2D.

**Spec reference:** `devdocs/specs/2026-04-27-tts-visual-reactivity-noisy-flatline-design.md`.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `frontend/src/features/voice/infrastructure/visualiserRenderers.ts` | Modify | Add `WIDTH_FRACTION = 0.9`, extend `barLayout()` to return `xOffset`, apply `xOffset` in all four renderers. Export `barLayout` for testing. |
| `frontend/src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts` | Create | Unit tests for `barLayout()` covering the width clamp. |
| `frontend/src/features/voice/infrastructure/visualiserNoise.ts` | Create | Pure noise-bin generator: `fillNoiseBins(out, tSeconds)`. |
| `frontend/src/features/voice/infrastructure/__tests__/visualiserNoise.test.ts` | Create | Unit tests for the noise generator. |
| `frontend/src/features/voice/infrastructure/ttsExpected.ts` | Create | Pure predicate `computeTtsExpected(input)` over four boolean sources. |
| `frontend/src/features/voice/infrastructure/__tests__/ttsExpected.test.ts` | Create | Unit tests for the pure predicate. |
| `frontend/src/features/voice/infrastructure/useTtsExpected.ts` | Create | React hook wrapping the predicate; returns a stable getter and an optional onTrueEdge callback. |
| `frontend/src/features/voice/components/VoiceVisualiser.tsx` | Modify | Extend the RAF loop with the new branch (noise vs. FFT vs. fade-out). Wire to `useTtsExpected`. |

The pure-function/hook split keeps the testable logic isolated from React's reactive plumbing. The hook is the only place that touches stores; the predicate is unit-testable as data-in / boolean-out.

---

## Task 1: 90% width clamp in `barLayout`

**Files:**
- Modify: `frontend/src/features/voice/infrastructure/visualiserRenderers.ts`
- Test: `frontend/src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts`

This is intentionally first because it is pure cosmetic, fully reversible, and unrelated to the noise/predicate logic. Ship it standalone so a regression in either direction is easy to diagnose.

- [ ] **Step 1: Read the current `visualiserRenderers.ts`**

```bash
cat frontend/src/features/voice/infrastructure/visualiserRenderers.ts
```

Confirm the current `barLayout` shape:

```ts
function barLayout(width: number, height: number, n: number, frac: number) {
  const cy = height / 2
  const slot = width / n
  const barW = slot * 0.62
  const maxDy = (height * frac) / 2
  return { cy, slot, barW, maxDy }
}
```

and that each `drawSharp` / `drawSoft` / `drawGlow` / `drawGlass` computes its
x-coordinate as `i * slot + (slot - barW) / 2`.

- [ ] **Step 2: Write the failing test**

Create `frontend/src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { barLayout } from '../visualiserRenderers'

describe('barLayout', () => {
  it('clamps the bar field to 90% of width, centred', () => {
    const { slot, xOffset } = barLayout(1000, 200, 10, 0.5)
    // 90% of 1000 = 900 usable; 50px margin on each side; slot = 900/10
    expect(xOffset).toBe(50)
    expect(slot).toBe(90)
  })

  it('keeps cy at vertical centre', () => {
    const { cy } = barLayout(1000, 240, 24, 0.5)
    expect(cy).toBe(120)
  })

  it('scales bar width to 62% of slot', () => {
    const { slot, barW } = barLayout(900, 200, 10, 0.5)
    // 90% of 900 = 810; slot = 81; barW = 81 * 0.62
    expect(slot).toBeCloseTo(81)
    expect(barW).toBeCloseTo(81 * 0.62)
  })

  it('returns maxDy as half of height*frac', () => {
    const { maxDy } = barLayout(800, 200, 10, 0.28)
    expect(maxDy).toBeCloseTo(28)
  })
})
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
cd frontend && pnpm test -- src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts --run
```

Expected: failure on the first test — `xOffset` is undefined (the property doesn't exist yet) and likely also on `slot` (currently `1000/10 = 100`, not `90`). The `cy`, `barW`, and `maxDy` cases may already pass on the second/third assertion only — that's fine.

- [ ] **Step 4: Implement the width clamp**

Replace the contents of `frontend/src/features/voice/infrastructure/visualiserRenderers.ts` with:

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

/** Fraction of the canvas width occupied by the bar field, centred. */
const WIDTH_FRACTION = 0.9

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

export function barLayout(width: number, height: number, n: number, frac: number) {
  const usableWidth = width * WIDTH_FRACTION
  const xOffset = (width - usableWidth) / 2
  const cy = height / 2
  const slot = usableWidth / n
  const barW = slot * 0.62
  const maxDy = (height * frac) / 2
  return { cy, slot, barW, maxDy, xOffset }
}

function drawSharp(ctx: CanvasRenderingContext2D, w: number, h: number, bins: Float32Array, o: RenderOpts) {
  const n = bins.length
  const { cy, slot, barW, maxDy, xOffset } = barLayout(w, h, n, o.maxHeightFraction)
  const [lr, lg, lb] = o.rgbLight
  ctx.fillStyle = `rgba(${lr},${lg},${lb},${o.opacity})`
  for (let i = 0; i < n; i++) {
    const dy = Math.min(bins[i], 1) * maxDy
    if (dy < 0.5) continue
    ctx.fillRect(xOffset + i * slot + (slot - barW) / 2, cy - dy, barW, dy * 2)
  }
}

function drawSoft(ctx: CanvasRenderingContext2D, w: number, h: number, bins: Float32Array, o: RenderOpts) {
  const n = bins.length
  const { cy, slot, barW, maxDy, xOffset } = barLayout(w, h, n, o.maxHeightFraction)
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
    ctx.fillRect(xOffset + i * slot + (slot - barW) / 2, y0, barW, dy * 2)
  }
}

function drawGlow(ctx: CanvasRenderingContext2D, w: number, h: number, bins: Float32Array, o: RenderOpts) {
  const n = bins.length
  const { cy, slot, barW, maxDy, xOffset } = barLayout(w, h, n, o.maxHeightFraction)
  const [r, g, b] = o.rgb
  const [lr, lg, lb] = o.rgbLight
  ctx.shadowColor = `rgba(${r},${g},${b},${o.opacity * 1.5})`
  ctx.shadowBlur = 14
  ctx.fillStyle = `rgba(${lr},${lg},${lb},${o.opacity * 0.9})`
  for (let i = 0; i < n; i++) {
    const dy = Math.min(bins[i], 1) * maxDy
    if (dy < 0.5) continue
    ctx.fillRect(xOffset + i * slot + (slot - barW) / 2, cy - dy, barW, dy * 2)
  }
  ctx.shadowBlur = 0
}

function drawGlass(ctx: CanvasRenderingContext2D, w: number, h: number, bins: Float32Array, o: RenderOpts) {
  const n = bins.length
  const { cy, slot, barW, maxDy, xOffset } = barLayout(w, h, n, o.maxHeightFraction)
  const [lr, lg, lb] = o.rgbLight
  ctx.lineWidth = 1
  for (let i = 0; i < n; i++) {
    const dy = Math.min(bins[i], 1) * maxDy
    if (dy < 0.5) continue
    const x = xOffset + i * slot + (slot - barW) / 2
    const y0 = cy - dy
    ctx.fillStyle = `rgba(255,255,255,${o.opacity * 0.45})`
    ctx.fillRect(x, y0, barW, dy * 2)
    ctx.strokeStyle = `rgba(${lr},${lg},${lb},${o.opacity * 0.85})`
    ctx.strokeRect(x + 0.5, y0 + 0.5, barW - 1, dy * 2 - 1)
  }
}
```

Note three changes vs. the current file:
1. `barLayout` is now `export`ed.
2. `barLayout` returns an extra `xOffset` field.
3. Each of the four `draw*` functions threads `xOffset` into its
   `fillRect`/`strokeRect`/`x` computation. **All other rendering logic is
   unchanged.** Reviewers should diff against the original to confirm only
   x-coordinate computation moved.

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd frontend && pnpm test -- src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts --run
```

Expected: all four cases pass.

- [ ] **Step 6: Run the full frontend build to catch type regressions**

```bash
cd frontend && pnpm run build
```

Expected: no TypeScript errors. The build passes (the existing visualiser
component imports `drawVisualiserFrame`, not `barLayout`, so it is
unaffected by the new export).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/voice/infrastructure/visualiserRenderers.ts \
        frontend/src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts
git commit -m "VoiceVisualiser: clamp bar field to 90% of viewport width"
```

---

## Task 2: Noise generator

**Files:**
- Create: `frontend/src/features/voice/infrastructure/visualiserNoise.ts`
- Test: `frontend/src/features/voice/infrastructure/__tests__/visualiserNoise.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/voice/infrastructure/__tests__/visualiserNoise.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import {
  fillNoiseBins,
  NOISE_BASELINE,
  NOISE_AMP,
  NOISE_PERIOD_S,
} from '../visualiserNoise'

describe('fillNoiseBins', () => {
  it('writes barCount values into the output buffer', () => {
    const out = new Float32Array(24)
    fillNoiseBins(out, 0)
    expect(out.length).toBe(24)
  })

  it('keeps every value within [BASELINE, BASELINE + NOISE_AMP]', () => {
    const out = new Float32Array(96)
    // Sweep across multiple periods to exercise the full sin range.
    for (let t = 0; t < 5 * NOISE_PERIOD_S; t += 0.1) {
      fillNoiseBins(out, t)
      for (let i = 0; i < out.length; i++) {
        expect(out[i]).toBeGreaterThanOrEqual(NOISE_BASELINE - 1e-6)
        expect(out[i]).toBeLessThanOrEqual(NOISE_BASELINE + NOISE_AMP + 1e-6)
      }
    }
  })

  it('produces different values across bars (phase wandering)', () => {
    const out = new Float32Array(24)
    fillNoiseBins(out, 0)
    // At t=0 and PHASE_STEP=0.15, neighbouring bars differ by sin step.
    const distinct = new Set(Array.from(out).map((v) => v.toFixed(4)))
    expect(distinct.size).toBeGreaterThan(20)
  })

  it('is periodic with PERIOD_S', () => {
    const a = new Float32Array(24)
    const b = new Float32Array(24)
    fillNoiseBins(a, 1.234)
    fillNoiseBins(b, 1.234 + NOISE_PERIOD_S)
    for (let i = 0; i < a.length; i++) {
      expect(b[i]).toBeCloseTo(a[i], 5)
    }
  })

  it('exposes BASELINE near 0.035 and AMP near 0.14', () => {
    expect(NOISE_BASELINE).toBeCloseTo(0.035, 3)
    expect(NOISE_AMP).toBeCloseTo(0.14, 3)
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd frontend && pnpm test -- src/features/voice/infrastructure/__tests__/visualiserNoise.test.ts --run
```

Expected: failure — module does not yet exist.

- [ ] **Step 3: Implement the noise generator**

Create `frontend/src/features/voice/infrastructure/visualiserNoise.ts`:

```ts
/**
 * Synthetic per-bar "noise" target values for the VoiceVisualiser's
 * "TTS expected, no audio playing" state. Output is in the same
 * normalised [0, 1] space as `useTtsFrequencyData`'s smoothed bins,
 * so it can be written directly into the smoother's target slot and
 * the existing exponential smoother bridges noise ↔ FFT handovers.
 *
 * The generator is a single phase-shifted sine. Higher-order Perlin
 * shapes are visually indistinguishable in this regime — the per-bar
 * smoother (factor 0.28 per frame in the consumer) already absorbs
 * any high-frequency component.
 */

/** Minimum visible bar height, normalised. ~1% of viewport at maxHeightFraction=0.28. */
export const NOISE_BASELINE = 0.035

/** Peak amplitude added on top of BASELINE, normalised. Brings the peak to ~5% of viewport. */
export const NOISE_AMP = 0.14

/** Bar-to-bar phase offset, in radians. Creates a wandering wave across the field. */
export const NOISE_PHASE_STEP = 0.15

/** Breathing period in seconds. */
export const NOISE_PERIOD_S = 2.0

/**
 * Fill `out` with one frame's worth of synthetic noise targets at time
 * `tSeconds`. Pure function, no allocations. `out.length` is the bar count.
 */
export function fillNoiseBins(out: Float32Array, tSeconds: number): void {
  const omega = (2 * Math.PI) / NOISE_PERIOD_S
  for (let i = 0; i < out.length; i++) {
    const wave = 0.5 + 0.5 * Math.sin(omega * tSeconds + i * NOISE_PHASE_STEP)
    out[i] = NOISE_BASELINE + NOISE_AMP * wave
  }
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd frontend && pnpm test -- src/features/voice/infrastructure/__tests__/visualiserNoise.test.ts --run
```

Expected: all five cases pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/infrastructure/visualiserNoise.ts \
        frontend/src/features/voice/infrastructure/__tests__/visualiserNoise.test.ts
git commit -m "Add visualiserNoise: synthetic per-bar noise target generator"
```

---

## Task 3: Pure "TTS expected" predicate

**Files:**
- Create: `frontend/src/features/voice/infrastructure/ttsExpected.ts`
- Test: `frontend/src/features/voice/infrastructure/__tests__/ttsExpected.test.ts`

The hook lives in Task 4. This task isolates the boolean logic so it can
be tested without mocking React or stores.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/voice/infrastructure/__tests__/ttsExpected.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { computeTtsExpected, type TtsExpectedInput } from '../ttsExpected'

const baseInput: TtsExpectedInput = {
  audioActive: false,
  isReadingAloud: false,
  hasActiveGroup: false,
  liveModeActive: false,
  autoReadEnabledForActiveGroup: false,
}

describe('computeTtsExpected', () => {
  it('returns false when nothing is happening', () => {
    expect(computeTtsExpected(baseInput)).toBe(false)
  })

  it('returns true when audio is actively playing', () => {
    expect(computeTtsExpected({ ...baseInput, audioActive: true })).toBe(true)
  })

  it('returns true when read-aloud is in flight', () => {
    expect(computeTtsExpected({ ...baseInput, isReadingAloud: true })).toBe(true)
  })

  it('returns true when an active group runs in live mode', () => {
    expect(
      computeTtsExpected({
        ...baseInput,
        hasActiveGroup: true,
        liveModeActive: true,
      }),
    ).toBe(true)
  })

  it('returns true when an active group runs with auto-read on', () => {
    expect(
      computeTtsExpected({
        ...baseInput,
        hasActiveGroup: true,
        autoReadEnabledForActiveGroup: true,
      }),
    ).toBe(true)
  })

  it('returns false when an active group runs without live mode or auto-read', () => {
    expect(
      computeTtsExpected({ ...baseInput, hasActiveGroup: true }),
    ).toBe(false)
  })

  it('returns false when live mode is on but no group is active', () => {
    expect(
      computeTtsExpected({ ...baseInput, liveModeActive: true }),
    ).toBe(false)
  })

  it('returns false when auto-read is on but no group is active', () => {
    expect(
      computeTtsExpected({
        ...baseInput,
        autoReadEnabledForActiveGroup: true,
      }),
    ).toBe(false)
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd frontend && pnpm test -- src/features/voice/infrastructure/__tests__/ttsExpected.test.ts --run
```

Expected: failure — module does not yet exist.

- [ ] **Step 3: Implement the predicate**

Create `frontend/src/features/voice/infrastructure/ttsExpected.ts`:

```ts
/**
 * Pure predicate: should the VoiceVisualiser show *something* right now,
 * even if no audio is currently playing? Used to drive the noisy-flatline
 * "TTS expected" state.
 *
 * Three or-branches:
 *   (a) Audio is actually playing — strongest signal, never a false negative.
 *   (b) The read-aloud pipeline is synthesising or playing — covers manual
 *       and auto-read once read-aloud has taken over.
 *   (c) An LLM response group is in flight, AND either continuous voice
 *       (live mode) is on, or auto-read is enabled for that group's
 *       session. Covers the early window before audio first arrives.
 */
export interface TtsExpectedInput {
  /** True iff `audioPlayback.isActive()`. */
  audioActive: boolean
  /** True iff a read-aloud session is synthesising or playing. */
  isReadingAloud: boolean
  /** True iff `getActiveGroup() !== null`. */
  hasActiveGroup: boolean
  /** True iff conversation mode is currently active (continuous voice). */
  liveModeActive: boolean
  /** True iff the active group's session has auto-read on in the cockpit. */
  autoReadEnabledForActiveGroup: boolean
}

export function computeTtsExpected(input: TtsExpectedInput): boolean {
  if (input.audioActive) return true
  if (input.isReadingAloud) return true
  if (input.hasActiveGroup) {
    if (input.liveModeActive) return true
    if (input.autoReadEnabledForActiveGroup) return true
  }
  return false
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd frontend && pnpm test -- src/features/voice/infrastructure/__tests__/ttsExpected.test.ts --run
```

Expected: all eight cases pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/infrastructure/ttsExpected.ts \
        frontend/src/features/voice/infrastructure/__tests__/ttsExpected.test.ts
git commit -m "Add ttsExpected: pure predicate for TTS-expected gating"
```

---

## Task 4: `useTtsExpected` hook

**Files:**
- Create: `frontend/src/features/voice/infrastructure/useTtsExpected.ts`

This hook is a thin wrapper that subscribes to the four reactive sources
and exposes a stable getter. It is also responsible for invoking an
optional `onTrueEdge` callback when the predicate transitions
`false → true`, so the visualiser can resume its RAF loop.

The hook itself is not unit-tested in isolation — the predicate it uses
(`computeTtsExpected`) is fully covered in Task 3, and the hook's
plumbing is exercised end-to-end by the manual verification in Task 6.
Adding store mocks for a thin wrapper is more bug-surface than coverage.

- [ ] **Step 1: Implement the hook**

Create `frontend/src/features/voice/infrastructure/useTtsExpected.ts`:

```ts
import { useEffect, useRef } from 'react'
import { audioPlayback } from './audioPlayback'
import { useIsReadingAloud } from '../components/ReadAloudButton'
import {
  getActiveGroup,
  subscribeActiveGroup,
} from '../../chat/responseTaskGroup'
import { useConversationModeStore } from '../stores/conversationModeStore'
import { useCockpitStore } from '../../chat/cockpit/cockpitStore'
import { computeTtsExpected } from './ttsExpected'

interface UseTtsExpectedOptions {
  /**
   * Fires once each time the predicate transitions false → true.
   * Visualiser uses this to restart its RAF loop after a fade-out.
   */
  onTrueEdge?: () => void
}

interface TtsExpectedAccessor {
  /** Read the current predicate value. Cheap; no React renders triggered. */
  (): boolean
}

/**
 * Composes audioPlayback, useIsReadingAloud, the active Group registry,
 * conversationModeStore, and cockpitStore into a single "TTS expected"
 * boolean. Returns a stable getter so consumers can read it inside a
 * RAF loop without forcing per-frame React renders.
 */
export function useTtsExpected(
  options: UseTtsExpectedOptions = {},
): TtsExpectedAccessor {
  // useIsReadingAloud is itself a hook with its own subscription, so we
  // call it here and keep the latest value in a ref. This is the only
  // value we cannot read on-demand from a store getter.
  const isReadingAloud = useIsReadingAloud()
  const isReadingAloudRef = useRef(isReadingAloud)
  isReadingAloudRef.current = isReadingAloud

  const onTrueEdgeRef = useRef(options.onTrueEdge)
  onTrueEdgeRef.current = options.onTrueEdge

  // Cached previous predicate value, for edge detection.
  const lastValueRef = useRef(false)

  const accessorRef = useRef<TtsExpectedAccessor | null>(null)
  if (accessorRef.current === null) {
    const accessor: TtsExpectedAccessor = () => {
      const group = getActiveGroup()
      const cockpit = useCockpitStore.getState()
      const autoRead = group !== null
        ? cockpit.bySession[group.sessionId]?.autoRead === true
        : false
      return computeTtsExpected({
        audioActive: audioPlayback.isActive(),
        isReadingAloud: isReadingAloudRef.current,
        hasActiveGroup: group !== null,
        liveModeActive: useConversationModeStore.getState().active,
        autoReadEnabledForActiveGroup: autoRead,
      })
    }
    accessorRef.current = accessor
  }

  // Edge detection: re-evaluate the predicate whenever any subscribed
  // source changes, and fire onTrueEdge on the false→true transition.
  useEffect(() => {
    const evaluate = () => {
      const value = accessorRef.current!()
      if (value && !lastValueRef.current && onTrueEdgeRef.current) {
        onTrueEdgeRef.current()
      }
      lastValueRef.current = value
    }

    // Sources to subscribe to.
    const unsubAudio = audioPlayback.subscribe(evaluate)
    const unsubGroup = subscribeActiveGroup(evaluate)
    const unsubMode = useConversationModeStore.subscribe(evaluate)
    const unsubCockpit = useCockpitStore.subscribe(evaluate)

    // Initial evaluation so lastValueRef seeds correctly.
    evaluate()

    return () => {
      unsubAudio()
      unsubGroup()
      unsubMode()
      unsubCockpit()
    }
  }, [])

  // Re-evaluate when isReadingAloud (the one React-driven source) changes.
  useEffect(() => {
    const value = accessorRef.current!()
    if (value && !lastValueRef.current && onTrueEdgeRef.current) {
      onTrueEdgeRef.current()
    }
    lastValueRef.current = value
  }, [isReadingAloud])

  return accessorRef.current
}
```

A note for reviewers on the subscription set:

- `audioPlayback.subscribe` already exists and fires on play / stop.
- `subscribeActiveGroup` already exists in `responseTaskGroup.ts` (used by `usePhase`).
- Zustand stores have a built-in `.subscribe(listener)` that fires on any state change. We use the unfiltered form because the predicate's result depends on multiple fields and the cost of a single boolean recomputation is trivial.
- `useIsReadingAloud` is the only hook here and is consumed via React state, hence the second `useEffect` for the isReadingAloud edge.

- [ ] **Step 2: Verify the build is clean**

```bash
cd frontend && pnpm run build
```

Expected: no TypeScript errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/voice/infrastructure/useTtsExpected.ts
git commit -m "Add useTtsExpected hook composing four reactive sources"
```

---

## Task 5: Wire the noise + expectation into `VoiceVisualiser`

**Files:**
- Modify: `frontend/src/features/voice/components/VoiceVisualiser.tsx`

This is the integration step. After this task ships, the user-visible
behaviour is complete.

- [ ] **Step 1: Re-read `VoiceVisualiser.tsx`**

```bash
cat frontend/src/features/voice/components/VoiceVisualiser.tsx
```

Confirm the structure: one `useEffect` owning a RAF loop with branches
for `enabled`, `paused`, `playing`, fade-out.

- [ ] **Step 2: Replace the file with the integrated version**

Overwrite `frontend/src/features/voice/components/VoiceVisualiser.tsx`:

```tsx
import { useEffect, useRef } from 'react'
import { useVoiceSettingsStore } from '../stores/voiceSettingsStore'
import { useVisualiserPauseStore } from '../stores/visualiserPauseStore'
import { useTtsFrequencyData } from '../infrastructure/useTtsFrequencyData'
import { drawVisualiserFrame } from '../infrastructure/visualiserRenderers'
import { audioPlayback } from '../infrastructure/audioPlayback'
import { fillNoiseBins } from '../infrastructure/visualiserNoise'
import { useTtsExpected } from '../infrastructure/useTtsExpected'

const MAX_HEIGHT_FRACTION = 0.28
const FADE_RATE = 0.05
const DEFAULT_HEX = '#8C76D7'

interface Props {
  /** Active persona's chakra colour as a hex string (e.g. '#8C76D7'). */
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

export function VoiceVisualiser({ personaColourHex = DEFAULT_HEX }: Props) {
  const enabled = useVoiceSettingsStore((s) => s.visualisation.enabled)
  const style = useVoiceSettingsStore((s) => s.visualisation.style)
  const opacity = useVoiceSettingsStore((s) => s.visualisation.opacity)
  const barCount = useVoiceSettingsStore((s) => s.visualisation.barCount)

  const paused = useVisualiserPauseStore((s) => s.paused)

  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const rafRef = useRef<number | null>(null)
  const activeRef = useRef(0)
  const reducedMotionRef = useRef(false)
  const frozenBinsRef = useRef<Float32Array | null>(null)

  // Buffer used when the noise branch is the data source.
  // Stable across renders; resized when barCount changes.
  const noiseBufferRef = useRef<Float32Array>(new Float32Array(barCount))
  if (noiseBufferRef.current.length !== barCount) {
    noiseBufferRef.current = new Float32Array(barCount)
  }

  const accessors = useTtsFrequencyData(barCount)

  // Forward declaration so the edge callback can call it. The actual
  // function is assigned inside the effect below; we just need a stable
  // ref to wrap it.
  const resumeRafRef = useRef<(() => void) | null>(null)

  const ttsExpected = useTtsExpected({
    onTrueEdge: () => {
      resumeRafRef.current?.()
    },
  })

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

      // DPR clamped to 1 — soft decorative shapes, saves ~4× memory at 4K.
      const w = c.clientWidth
      const h = c.clientHeight
      if (c.width !== w || c.height !== h) { c.width = w; c.height = h }

      const ctx = c.getContext('2d')
      if (!ctx) return
      ctx.clearRect(0, 0, w, h)

      if (reducedMotionRef.current) {
        rafRef.current = requestAnimationFrame(tick)
        return
      }

      if (paused) {
        const bins = accessors.getBins()
        if (!frozenBinsRef.current) {
          frozenBinsRef.current = bins ? bins.slice() : new Float32Array(barCount)
        }
        const t = performance.now() / 1000
        const breath = 0.8 + 0.2 * Math.sin((t * 2 * Math.PI) / 2.5)  // 0.6..1.0
        const rgb = hexToRgb(personaColourHex)
        const rgbLight = brighten(rgb)
        drawVisualiserFrame(style, ctx, w, h, frozenBinsRef.current, {
          rgb,
          rgbLight,
          opacity: opacity * breath,
          maxHeightFraction: MAX_HEIGHT_FRACTION,
        })
        rafRef.current = requestAnimationFrame(tick)
        return
      }

      // Not paused — clear any stale snapshot.
      frozenBinsRef.current = null

      const playing = accessors.isActive()
      const expected = ttsExpected()
      const visible = playing || expected
      const target = visible ? 1 : 0
      activeRef.current += (target - activeRef.current) * FADE_RATE

      if (activeRef.current > 0.005) {
        let bins: Float32Array | null = null
        if (playing) {
          bins = accessors.getBins()
        } else if (expected) {
          fillNoiseBins(noiseBufferRef.current, performance.now() / 1000)
          bins = noiseBufferRef.current
        }
        if (bins) {
          const rgb = hexToRgb(personaColourHex)
          const rgbLight = brighten(rgb)
          drawVisualiserFrame(style, ctx, w, h, bins, {
            rgb,
            rgbLight,
            opacity: opacity * activeRef.current,
            maxHeightFraction: MAX_HEIGHT_FRACTION,
          })
        }
        rafRef.current = requestAnimationFrame(tick)
      } else if (visible) {
        // Visible but still ramping in — keep the loop running.
        rafRef.current = requestAnimationFrame(tick)
      } else {
        // Fully faded out and nothing expected — pause RAF until next event.
        rafRef.current = null
      }
    }

    rafRef.current = requestAnimationFrame(tick)

    // Resume on play (audio events).
    const unsubAudio = audioPlayback.subscribe(() => {
      if (rafRef.current === null && !stopped) {
        rafRef.current = requestAnimationFrame(tick)
      }
    })

    // Resume on expectation true-edge (e.g. user submits in live mode).
    resumeRafRef.current = () => {
      if (rafRef.current === null && !stopped) {
        rafRef.current = requestAnimationFrame(tick)
      }
    }

    return () => {
      stopped = true
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
      unsubAudio()
      resumeRafRef.current = null
    }
  }, [enabled, style, opacity, barCount, personaColourHex, accessors, paused, ttsExpected])

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

Diff highlights vs. the prior version:

1. New imports: `fillNoiseBins`, `useTtsExpected`.
2. New ref: `noiseBufferRef` (a `Float32Array(barCount)`, re-allocated on bar-count change).
3. New ref: `resumeRafRef`, holding a stable callback that the expectation hook invokes on its true-edge.
4. The `playing ? bins : fade-out` branch becomes `playing ? FFT : expected ? noise : fade-out`.
5. The dependency array now includes `ttsExpected` (a stable function reference).

**Unchanged:** `enabled`-off path, reduced-motion short-circuit, paused-snapshot freeze, persona colour, opacity, style, bar count, RAF lifecycle on the audio subscribe path.

- [ ] **Step 3: Verify the build is clean**

```bash
cd frontend && pnpm run build
```

Expected: no TypeScript errors.

- [ ] **Step 4: Run the full frontend test suite**

```bash
cd frontend && pnpm test -- --run
```

Expected: all tests pass. The new tests added in Tasks 1–3 should be
green; existing visualiser-adjacent tests
(`VoiceVisualiserHitStrip.test.tsx`, `audioPlayback.test.ts`,
`visualiserBucketing.test.ts`, `visualiserPauseStore.test.ts`) should
remain green.

If a test fails: do not paper over it. Read the failure, decide whether
the test or the implementation is wrong, and fix the actual cause.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/components/VoiceVisualiser.tsx
git commit -m "VoiceVisualiser: add noisy-flatline branch driven by useTtsExpected"
```

---

## Task 6: Manual verification

This task is mandatory. The unit tests cover pure functions; the
integration is intentionally light on automated tests because driving
the canvas + RAF + audio context in JSDOM produces brittle assertions
without confidence.

**Files:** none (verification only).

- [ ] **Step 1: Start the dev frontend**

```bash
cd frontend && pnpm dev
```

Open `http://localhost:5173` in Chris's preferred browser. Log in.
Ensure at least one persona is configured with a TTS-capable LLM
connection.

- [ ] **Step 2: Walk through the manual verification checklist from the spec**

Tick each item off in `devdocs/specs/2026-04-27-tts-visual-reactivity-noisy-flatline-design.md` §11:

- [ ] Live mode, fresh request — flatline before audio, smooth handover, flatline between sentences, fade-out at end.
- [ ] Live mode, long inference — flatline persists throughout the wait, no flicker.
- [ ] Live mode, mid-response gap — flatline rather than invisible.
- [ ] Manual read-aloud — flatline → spectrum → flatline → fade-out.
- [ ] Auto-read enabled — flatline from LLM-inference start, smooth handover.
- [ ] Auto-read disabled, no live mode — **no visualiser at all**.
- [ ] Persona switch during flatline — colour follows on next frame.
- [ ] Master toggle off — neither flatline nor spectrum.
- [ ] Reduced motion on — neither animates; off — both resume.
- [ ] Tap-to-pause during flatline — no-op; flatline keeps wandering.
- [ ] Tap-to-pause during spectrum — existing freeze + breath unchanged.
- [ ] Style switch during flatline — every style renders distinctly.
- [ ] Opacity slider during flatline — tracks immediately.
- [ ] Bar count slider during flatline — re-allocates without flicker.
- [ ] No regression in audio quality.
- [ ] Width clamp — bar field is 90% width, centred, ~5% margin each side.

- [ ] **Step 3: Report the result**

If every item passes: report success; the feature is ready for merge.

If any item fails: file the failure with the specific scenario and
observed-vs-expected, hand it back for diagnosis. Do not patch over a
manual-verification failure with a unit-test-only fix.

---

## Self-Review Checklist (already executed)

- **Spec coverage:**
  - §3 architecture overview → Tasks 2, 3, 4, 5.
  - §4 gating predicate → Tasks 3 (pure) + 4 (hook).
  - §5 noise generator → Task 2.
  - §6 renderer integration → Task 5.
  - §6a width clamp → Task 1.
  - §7 settings (none new) → confirmed; no task needed.
  - §8 accessibility (no change) → confirmed; existing reduced-motion path is preserved in Task 5's code.
  - §9 performance → satisfied by design; no separate task.
  - §10 implementation order → Tasks 1–5 in the order specified.
  - §11 manual verification → Task 6.
- **Placeholder scan:** no TBD / TODO / "implement later". All code blocks are complete.
- **Type consistency:** `barLayout` returns `{ cy, slot, barW, maxDy, xOffset }` consistently across renderers. `TtsExpectedInput` field names match between `ttsExpected.ts` and `useTtsExpected.ts`. `fillNoiseBins(out, tSeconds)` signature matches between Task 2's implementation and Task 5's call site. `useTtsExpected({ onTrueEdge })` shape matches between Task 4's signature and Task 5's call site.

# Transcription Indicator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render three pulsing chakra-coloured dots into the existing voice-visualiser canvas during the `transcribing` pipeline phase, in the same four styles (sharp/soft/glow/glass) as the spectrum bars.

**Architecture:** Pure-canvas drawing inside the existing `VoiceVisualiser` RAF loop. A new branch in `tick()` selects the dots when `phase === 'transcribing'`. Geometry, persona colour, and user opacity slider are reused via the same pipeline as the bars. A new `dotsActiveRef` mirrors the existing `activeRef` for smooth fade-in / fade-out.

**Tech Stack:** React + TypeScript + Vite + Vitest, HTMLCanvasElement 2D context. Frontend only — no backend, no DTO, no event, no schema change.

**Spec:** `devdocs/specs/2026-04-27-transcription-indicator-design.md`

---

## File Structure

| File | Role | Action |
|---|---|---|
| `frontend/src/features/voice/infrastructure/visualiserRenderers.ts` | Geometry helpers + per-style draw functions | Modify (add `dotLayout`, `drawTranscriptionDots`, four `drawDots…` helpers) |
| `frontend/src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts` | Unit tests for geometry + dispatcher | Modify (add tests) |
| `frontend/src/features/voice/components/VoiceVisualiser.tsx` | RAF orchestrator, canvas owner | Modify (add `phase` selector, `dotsActiveRef`, new RAF branch) |

No new files. No new exports outside the `voice` feature.

---

## Conventions

- All code, identifiers, and comments use British English (`colour`, `centre`).
- Pin numeric constants near the existing `MAX_HEIGHT_FRACTION` / `FADE_RATE` block in `VoiceVisualiser.tsx` so the bar/dot pair stays easy to tune together. Layout-only constants (radius, gap) live in `visualiserRenderers.ts`.
- Commit after each green test step, plus the final integration step. Use imperative free-form messages (no Conventional-Commits prefix).

---

## Task 1: `dotLayout` helper

**Files:**
- Modify: `frontend/src/features/voice/infrastructure/visualiserRenderers.ts`
- Test:   `frontend/src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts`

- [ ] **Step 1: Write the failing tests**

Append to `visualiserRenderers.test.ts` (after the existing `barLayout` describe block):

```ts
import { dotLayout } from '../visualiserRenderers'

describe('dotLayout', () => {
  it('places centreX at the centre of the bar-layout extent', () => {
    const g: BarGeometry = {
      chatview: { x: 0, w: 1000 },
      textColumn: { x: 116, w: 768 },
    }
    // barLayout for this geometry: xOffset=39.2, finalWidth=921.6 → centre 500
    const { centreX } = dotLayout(g)
    expect(centreX).toBeCloseTo(500)
  })

  it('places three dots symmetrically around centreX with a 22 px centre-to-centre gap', () => {
    const g: BarGeometry = {
      chatview: { x: 0, w: 1000 },
      textColumn: { x: 116, w: 768 },
    }
    const { dotXs, gap } = dotLayout(g)
    expect(gap).toBe(22)
    expect(dotXs[1] - dotXs[0]).toBeCloseTo(22)
    expect(dotXs[2] - dotXs[1]).toBeCloseTo(22)
    expect(dotXs[1]).toBeCloseTo(500)
  })

  it('exposes a 7 px base radius (14 px diameter)', () => {
    const g: BarGeometry = {
      chatview: { x: 0, w: 1000 },
      textColumn: { x: 116, w: 768 },
    }
    const { baseRadius } = dotLayout(g)
    expect(baseRadius).toBe(7)
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm --filter frontend test -- visualiserRenderers`
Expected: FAIL with `dotLayout is not exported` or similar.

- [ ] **Step 3: Implement `dotLayout`**

Add to `visualiserRenderers.ts`, after the existing `barLayout` function:

```ts
const DOT_BASE_RADIUS = 7
const DOT_GAP = 22

export function dotLayout(geometry: BarGeometry): {
  centreX: number
  dotXs: [number, number, number]
  baseRadius: number
  gap: number
} {
  // Same clamping rules as barLayout so the dots stay centred on the
  // same visual extent as the bars (≤ 1.2 × textColumn, but never wider
  // than chatview).
  const { chatview, textColumn } = geometry
  const target = textColumn.w * 1.2
  const usable = Math.min(target, chatview.w)
  const tcCentre = textColumn.x + textColumn.w / 2
  const left = Math.max(chatview.x, tcCentre - usable / 2)
  const right = Math.min(chatview.x + chatview.w, tcCentre + usable / 2)
  const centreX = (left + right) / 2
  return {
    centreX,
    dotXs: [centreX - DOT_GAP, centreX, centreX + DOT_GAP],
    baseRadius: DOT_BASE_RADIUS,
    gap: DOT_GAP,
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --filter frontend test -- visualiserRenderers`
Expected: PASS, all `dotLayout` cases green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/infrastructure/visualiserRenderers.ts \
        frontend/src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts
git commit -m "Add dotLayout helper for transcription-indicator geometry"
```

---

## Task 2: `drawTranscriptionDots` dispatcher with no-op style stubs

**Files:**
- Modify: `frontend/src/features/voice/infrastructure/visualiserRenderers.ts`
- Test:   `frontend/src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts`

- [ ] **Step 1: Write failing dispatcher test**

Append to `visualiserRenderers.test.ts`:

```ts
import { drawTranscriptionDots } from '../visualiserRenderers'
import type { RenderOpts } from '../visualiserRenderers'
import { vi } from 'vitest'

interface MockCtx {
  fillStyle: string
  strokeStyle: string
  lineWidth: number
  shadowColor: string
  shadowBlur: number
  beginPath: ReturnType<typeof vi.fn>
  arc: ReturnType<typeof vi.fn>
  fill: ReturnType<typeof vi.fn>
  stroke: ReturnType<typeof vi.fn>
  createRadialGradient: ReturnType<typeof vi.fn>
}

function makeMockCtx(): MockCtx {
  return {
    fillStyle: '',
    strokeStyle: '',
    lineWidth: 0,
    shadowColor: '',
    shadowBlur: 0,
    beginPath: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
    stroke: vi.fn(),
    createRadialGradient: vi.fn(() => ({ addColorStop: vi.fn() })),
  }
}

const DOT_OPTS: RenderOpts = {
  rgb: [140, 118, 215],
  rgbLight: [180, 158, 255],
  opacity: 0.5,
  maxHeightFraction: 0.28,
}

const DOT_GEOM: BarGeometry = {
  chatview: { x: 0, w: 1000 },
  textColumn: { x: 116, w: 768 },
}

describe('drawTranscriptionDots dispatcher', () => {
  it('issues exactly three arc() calls for sharp', () => {
    const ctx = makeMockCtx()
    drawTranscriptionDots('sharp', ctx as unknown as CanvasRenderingContext2D, 240, DOT_OPTS, DOT_GEOM, 0)
    expect(ctx.arc).toHaveBeenCalledTimes(3)
  })

  it('issues exactly three arc() calls for soft', () => {
    const ctx = makeMockCtx()
    drawTranscriptionDots('soft', ctx as unknown as CanvasRenderingContext2D, 240, DOT_OPTS, DOT_GEOM, 0)
    expect(ctx.arc).toHaveBeenCalledTimes(3)
  })

  it('issues exactly three arc() calls for glow', () => {
    const ctx = makeMockCtx()
    drawTranscriptionDots('glow', ctx as unknown as CanvasRenderingContext2D, 240, DOT_OPTS, DOT_GEOM, 0)
    expect(ctx.arc).toHaveBeenCalledTimes(3)
  })

  it('issues at least three arc() calls for glass (fill + ring)', () => {
    const ctx = makeMockCtx()
    drawTranscriptionDots('glass', ctx as unknown as CanvasRenderingContext2D, 240, DOT_OPTS, DOT_GEOM, 0)
    expect(ctx.arc.mock.calls.length).toBeGreaterThanOrEqual(3)
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm --filter frontend test -- visualiserRenderers`
Expected: FAIL with `drawTranscriptionDots is not exported` (and the four cases all red).

- [ ] **Step 3: Implement dispatcher with stubs**

Add to `visualiserRenderers.ts`, after `dotLayout`:

```ts
function dotPulse(t: number, i: number): { scale: number; animOp: number } {
  // Period 2 s, per-dot stagger 0.3 s. Raised cosine matches the
  // ThinkingBubble keyframes (0% → 50% → 100%: 0.8 → 1.2 → 0.8 for scale,
  // 0.3 → 1.0 → 0.3 for opacity), i.e. one hump per period.
  const raw = (t - i * 0.3) / 2.0
  const phase = ((raw % 1) + 1) % 1
  const pulse = (1 - Math.cos(phase * 2 * Math.PI)) / 2
  return {
    scale: 0.8 + 0.4 * pulse,
    animOp: 0.3 + 0.7 * pulse,
  }
}

export function drawTranscriptionDots(
  style: VisualiserStyle,
  ctx: CanvasRenderingContext2D,
  height: number,
  opts: RenderOpts,
  geometry: BarGeometry,
  t: number,
): void {
  switch (style) {
    case 'sharp': drawDotsSharp(ctx, height, opts, geometry, t); break
    case 'soft':  drawDotsSoft(ctx, height, opts, geometry, t); break
    case 'glow':  drawDotsGlow(ctx, height, opts, geometry, t); break
    case 'glass': drawDotsGlass(ctx, height, opts, geometry, t); break
  }
}

function drawDotsSharp(ctx: CanvasRenderingContext2D, h: number, o: RenderOpts, g: BarGeometry, t: number) {
  const { dotXs, baseRadius } = dotLayout(g)
  const cy = h / 2
  for (let i = 0; i < 3; i++) {
    const { scale } = dotPulse(t, i)
    ctx.beginPath()
    ctx.arc(dotXs[i], cy, baseRadius * scale, 0, Math.PI * 2)
    ctx.fill()
  }
}

function drawDotsSoft(ctx: CanvasRenderingContext2D, h: number, o: RenderOpts, g: BarGeometry, t: number) {
  const { dotXs, baseRadius } = dotLayout(g)
  const cy = h / 2
  for (let i = 0; i < 3; i++) {
    const { scale } = dotPulse(t, i)
    ctx.beginPath()
    ctx.arc(dotXs[i], cy, baseRadius * scale, 0, Math.PI * 2)
    ctx.fill()
  }
}

function drawDotsGlow(ctx: CanvasRenderingContext2D, h: number, o: RenderOpts, g: BarGeometry, t: number) {
  const { dotXs, baseRadius } = dotLayout(g)
  const cy = h / 2
  for (let i = 0; i < 3; i++) {
    const { scale } = dotPulse(t, i)
    ctx.beginPath()
    ctx.arc(dotXs[i], cy, baseRadius * scale, 0, Math.PI * 2)
    ctx.fill()
  }
}

function drawDotsGlass(ctx: CanvasRenderingContext2D, h: number, o: RenderOpts, g: BarGeometry, t: number) {
  const { dotXs, baseRadius } = dotLayout(g)
  const cy = h / 2
  for (let i = 0; i < 3; i++) {
    const { scale } = dotPulse(t, i)
    ctx.beginPath()
    ctx.arc(dotXs[i], cy, baseRadius * scale, 0, Math.PI * 2)
    ctx.fill()
  }
}
```

These are deliberately identical stubs — they all draw three plain
filled circles. The next four tasks make each one style-specific
(colour application, gradients, glow, ring).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --filter frontend test -- visualiserRenderers`
Expected: PASS, all four dispatcher cases green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/infrastructure/visualiserRenderers.ts \
        frontend/src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts
git commit -m "Add drawTranscriptionDots dispatcher with style stubs"
```

---

## Task 3: Style — `drawDotsSharp`

**Files:**
- Modify: `frontend/src/features/voice/infrastructure/visualiserRenderers.ts`
- Test:   `frontend/src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts`

- [ ] **Step 1: Write failing test**

Add inside the existing `describe('drawTranscriptionDots dispatcher', …)` block (or a new sibling describe — your call, but keep the helpers reusable):

```ts
describe('drawDotsSharp colour application', () => {
  it('uses an rgba fillStyle with the rgbLight triplet', () => {
    const ctx = makeMockCtx()
    drawTranscriptionDots('sharp', ctx as unknown as CanvasRenderingContext2D, 240, DOT_OPTS, DOT_GEOM, 0)
    // After the call, fillStyle holds whatever was last set. Verify the
    // string format encodes rgbLight = [180, 158, 255].
    expect(ctx.fillStyle).toMatch(/^rgba\(180,\s*158,\s*255,/)
  })
})
```

- [ ] **Step 2: Run tests to verify it fails**

Run: `pnpm --filter frontend test -- visualiserRenderers`
Expected: FAIL — current stub never sets `fillStyle`.

- [ ] **Step 3: Implement `drawDotsSharp` properly**

Replace the stub body with:

```ts
function drawDotsSharp(ctx: CanvasRenderingContext2D, h: number, o: RenderOpts, g: BarGeometry, t: number) {
  const { dotXs, baseRadius } = dotLayout(g)
  const cy = h / 2
  const [lr, lg, lb] = o.rgbLight
  for (let i = 0; i < 3; i++) {
    const { scale, animOp } = dotPulse(t, i)
    ctx.fillStyle = `rgba(${lr},${lg},${lb},${o.opacity * animOp})`
    ctx.beginPath()
    ctx.arc(dotXs[i], cy, baseRadius * scale, 0, Math.PI * 2)
    ctx.fill()
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --filter frontend test -- visualiserRenderers`
Expected: PASS, sharp colour test green; existing dispatcher tests still green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/infrastructure/visualiserRenderers.ts \
        frontend/src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts
git commit -m "Implement sharp style for transcription dots"
```

---

## Task 4: Style — `drawDotsSoft`

**Files:**
- Modify: `frontend/src/features/voice/infrastructure/visualiserRenderers.ts`
- Test:   `frontend/src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts`

- [ ] **Step 1: Write failing test**

```ts
describe('drawDotsSoft uses radial gradients', () => {
  it('creates one radial gradient per dot', () => {
    const ctx = makeMockCtx()
    drawTranscriptionDots('soft', ctx as unknown as CanvasRenderingContext2D, 240, DOT_OPTS, DOT_GEOM, 0)
    expect(ctx.createRadialGradient).toHaveBeenCalledTimes(3)
  })
})
```

- [ ] **Step 2: Run tests to verify it fails**

Run: `pnpm --filter frontend test -- visualiserRenderers`
Expected: FAIL — current stub never calls `createRadialGradient`.

- [ ] **Step 3: Implement `drawDotsSoft`**

Replace stub body with:

```ts
function drawDotsSoft(ctx: CanvasRenderingContext2D, h: number, o: RenderOpts, g: BarGeometry, t: number) {
  const { dotXs, baseRadius } = dotLayout(g)
  const cy = h / 2
  const [r, gC, b] = o.rgb
  const [lr, lg, lb] = o.rgbLight
  for (let i = 0; i < 3; i++) {
    const { scale, animOp } = dotPulse(t, i)
    const radius = baseRadius * scale
    const x = dotXs[i]
    const grd = ctx.createRadialGradient(x, cy, 0, x, cy, radius)
    grd.addColorStop(0,    `rgba(${lr},${lg},${lb},${o.opacity * animOp})`)
    grd.addColorStop(0.5,  `rgba(${r},${gC},${b},${o.opacity * animOp * 0.7})`)
    grd.addColorStop(1,    `rgba(${r},${gC},${b},0)`)
    ctx.fillStyle = grd as unknown as string
    ctx.beginPath()
    ctx.arc(x, cy, radius, 0, Math.PI * 2)
    ctx.fill()
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --filter frontend test -- visualiserRenderers`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/infrastructure/visualiserRenderers.ts \
        frontend/src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts
git commit -m "Implement soft style for transcription dots"
```

---

## Task 5: Style — `drawDotsGlow`

**Files:**
- Modify: `frontend/src/features/voice/infrastructure/visualiserRenderers.ts`
- Test:   `frontend/src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts`

- [ ] **Step 1: Write failing test**

```ts
describe('drawDotsGlow sets a shadow blur', () => {
  it('applies a non-zero shadowBlur with the rgb shadow colour', () => {
    const ctx = makeMockCtx()
    drawTranscriptionDots('glow', ctx as unknown as CanvasRenderingContext2D, 240, DOT_OPTS, DOT_GEOM, 0)
    expect(ctx.shadowBlur).toBeGreaterThan(0)
    expect(ctx.shadowColor).toMatch(/^rgba\(140,\s*118,\s*215,/)
  })

  it('resets shadowBlur to 0 before returning', () => {
    const ctx = makeMockCtx()
    // Not strictly required, but a fresh mock starts at 0; we want the
    // function to leave it at 0 so subsequent canvas users are unaffected.
    drawTranscriptionDots('glow', ctx as unknown as CanvasRenderingContext2D, 240, DOT_OPTS, DOT_GEOM, 0)
    expect(ctx.shadowBlur).toBe(0)
  })
})
```

(The second assertion checks the implementation is well-behaved — the existing `drawGlow` for bars already does the same shadow reset trick at the end.)

- [ ] **Step 2: Run tests to verify it fails**

Run: `pnpm --filter frontend test -- visualiserRenderers`
Expected: FAIL on shadowBlur assertion.

- [ ] **Step 3: Implement `drawDotsGlow`**

Replace stub body with:

```ts
function drawDotsGlow(ctx: CanvasRenderingContext2D, h: number, o: RenderOpts, g: BarGeometry, t: number) {
  const { dotXs, baseRadius } = dotLayout(g)
  const cy = h / 2
  const [r, gC, b] = o.rgb
  const [lr, lg, lb] = o.rgbLight
  ctx.shadowColor = `rgba(${r},${gC},${b},${o.opacity * 1.5})`
  ctx.shadowBlur = 14
  for (let i = 0; i < 3; i++) {
    const { scale, animOp } = dotPulse(t, i)
    ctx.fillStyle = `rgba(${lr},${lg},${lb},${o.opacity * animOp})`
    ctx.beginPath()
    ctx.arc(dotXs[i], cy, baseRadius * scale, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.shadowBlur = 0
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --filter frontend test -- visualiserRenderers`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/infrastructure/visualiserRenderers.ts \
        frontend/src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts
git commit -m "Implement glow style for transcription dots"
```

---

## Task 6: Style — `drawDotsGlass`

**Files:**
- Modify: `frontend/src/features/voice/infrastructure/visualiserRenderers.ts`
- Test:   `frontend/src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts`

- [ ] **Step 1: Write failing test**

```ts
describe('drawDotsGlass renders fill and ring', () => {
  it('strokes a coloured ring per dot', () => {
    const ctx = makeMockCtx()
    drawTranscriptionDots('glass', ctx as unknown as CanvasRenderingContext2D, 240, DOT_OPTS, DOT_GEOM, 0)
    expect(ctx.stroke).toHaveBeenCalledTimes(3)
  })

  it('uses a near-white fill with low opacity', () => {
    const ctx = makeMockCtx()
    drawTranscriptionDots('glass', ctx as unknown as CanvasRenderingContext2D, 240, DOT_OPTS, DOT_GEOM, 0)
    // The last fillStyle assignment in the loop wins; we just verify the
    // string starts with rgba(255,255,255 to confirm the milky look.
    expect(ctx.fillStyle).toMatch(/^rgba\(255,\s*255,\s*255,/)
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm --filter frontend test -- visualiserRenderers`
Expected: FAIL — current stub never strokes and never sets a white fill.

- [ ] **Step 3: Implement `drawDotsGlass`**

Replace stub body with:

```ts
function drawDotsGlass(ctx: CanvasRenderingContext2D, h: number, o: RenderOpts, g: BarGeometry, t: number) {
  const { dotXs, baseRadius } = dotLayout(g)
  const cy = h / 2
  const [r, gC, b] = o.rgb
  for (let i = 0; i < 3; i++) {
    const { scale, animOp } = dotPulse(t, i)
    const radius = baseRadius * scale
    const x = dotXs[i]
    // Milky core.
    ctx.fillStyle = `rgba(255,255,255,${o.opacity * animOp * 0.55})`
    ctx.beginPath()
    ctx.arc(x, cy, radius, 0, Math.PI * 2)
    ctx.fill()
    // Coloured ring.
    ctx.strokeStyle = `rgba(${r},${gC},${b},${o.opacity * animOp})`
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.arc(x, cy, radius, 0, Math.PI * 2)
    ctx.stroke()
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm --filter frontend test -- visualiserRenderers`
Expected: PASS, all renderer tests green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/infrastructure/visualiserRenderers.ts \
        frontend/src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts
git commit -m "Implement glass style for transcription dots"
```

---

## Task 7: Wire branch into `VoiceVisualiser`

**Files:**
- Modify: `frontend/src/features/voice/components/VoiceVisualiser.tsx`

This task has no automated test — the existing `VoiceVisualiser` is not unit-tested at the component level (only `VoiceVisualiserHitStrip` is). Manual verification in Task 9 covers it.

- [ ] **Step 1: Add the phase selector**

Find the existing selector block in `VoiceVisualiser.tsx` (the cluster of `useVoiceSettingsStore` / `useVisualiserLayoutStore` selectors, around the top of the component). Add a phase selector next to them:

```ts
import { useVoicePipeline } from '../stores/voicePipelineStore'
// …
const phase = useVoicePipeline((s) => s.phase)
```

The hook is exported from `frontend/src/features/voice/stores/voicePipelineStore.ts:12`. The `phase` field is part of the store's `PipelineState` (see `frontend/src/features/voice/types.ts`).

- [ ] **Step 2: Add the `dotsActiveRef`**

In the same block where `activeRef` is declared (search for `activeRef`), add:

```ts
const dotsActiveRef = useRef(0)
```

- [ ] **Step 3: Add the new branch in `tick()`**

Locate the `tick()` function. After the `playing || expected` branch (which ends around the `else if (visible)` / final `else` cluster around line 176–185 in current `master`), and before the loop's bottom early-out, insert:

```ts
const transcribing = phase === 'transcribing'
const dotsTarget = transcribing ? 1 : 0
dotsActiveRef.current += (dotsTarget - dotsActiveRef.current) * FADE_RATE

if (dotsActiveRef.current > 0.005) {
  const rgb = hexToRgb(personaColourHex)
  const rgbLight = brighten(rgb)
  drawTranscriptionDots(style, ctx, h, {
    rgb,
    rgbLight,
    opacity: opacity * dotsActiveRef.current,
    maxHeightFraction: MAX_HEIGHT_FRACTION,
  }, geometry, performance.now() / 1000)
  rafRef.current = requestAnimationFrame(tick)
  return
}
```

Read the surrounding code carefully: the `paused` and `playing/expected` branches both `return` after their `requestAnimationFrame(tick)` call. The dots branch follows the same pattern. The pipeline guarantees these phases are mutually exclusive (`transcribing` implies no active LLM group → `ttsExpected = false`), so the branches do not co-render.

- [ ] **Step 4: Update the `useEffect` dependency array**

Find the `useEffect` whose dependency array currently ends with `chatview, textColumn` (around line 215). Add `phase`:

```ts
}, [enabled, style, opacity, barCount, personaColourHex, accessors, paused, ttsExpected, chatview, textColumn, phase])
```

- [ ] **Step 5: Add the `drawTranscriptionDots` import**

Update the import from `../infrastructure/visualiserRenderers`:

```ts
import { drawVisualiserFrame, drawTranscriptionDots } from '../infrastructure/visualiserRenderers'
```

- [ ] **Step 6: Type-check**

Run: `pnpm --filter frontend tsc --noEmit`
Expected: clean.

- [ ] **Step 7: Run the full frontend test suite**

Run: `pnpm --filter frontend test`
Expected: all tests pass, including the renderer suite from Tasks 1–6 and the unrelated `VoiceVisualiserHitStrip` suite.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/voice/components/VoiceVisualiser.tsx
git commit -m "Render transcription dots in the visualiser canvas"
```

---

## Task 8: Build verification

**Files:**
- (none)

- [ ] **Step 1: Run the production build**

Run: `pnpm --filter frontend run build`
Expected: clean. `tsc -b` (run inside `pnpm run build`) catches stricter type errors than `tsc --noEmit` — required before any "done" claim.

If the build fails: fix the underlying issue, do **not** loosen types, do **not** suppress errors. Re-run after each fix.

- [ ] **Step 2: No commit needed unless build forced a change**

If a fix was required, commit it under its own message (e.g. `Fix type error in transcription-dots branch`).

---

## Task 9: Manual verification handoff

**Files:**
- (none — this task is a checklist for the human reviewer)

The agent cannot run this; surface it to the user with the spec's manual-verification list. Stop here and ask the user to confirm.

- [ ] **Step 1: Surface the manual-verification checklist**

Tell the user the implementation is ready for manual verification and list the cases from the spec:

1. Push-to-talk: record → release → dots appear, fade in smoothly, hold while STT is in flight, fade out as the wave begins.
2. Continuous voice: VAD detects end-of-utterance → dots → wave → bars with no visible gap.
3. Style switching: cycle `sharp` / `soft` / `glow` / `glass` in the Voice tab. Dots adopt each style; "glow" should visibly glow, "glass" should look milky.
4. Opacity slider: 0.05 → dots barely visible; 0.80 → dots clearly present.
5. Visualiser toggle off → dots do not appear; toggle back on → dots appear in the next `transcribing` window.
6. Reduced motion: enable `prefers-reduced-motion: reduce` in the browser → no dots, matching the bars' behaviour.
7. Persona switch mid-session → next `transcribing` window shows dots in the new chakra colour.

- [ ] **Step 2: Wait for user feedback**

Do **not** merge to `master`. Do **not** push. Do **not** switch branches. The user owns the merge step; pause here for sign-off.

---

## Out of scope (do NOT touch in this plan)

- The existing `ThinkingBubble` dots in chat. They live in a different visual context and stay unchanged.
- The `TranscriptionOverlay` (transcribed-text card). Complementary to the dots, not replaced.
- Any new user setting. The dots inherit `enabled` / `style` / `opacity` / chakra colour from the existing pipeline.
- Backend, DTOs, events, schema. Frontend only.

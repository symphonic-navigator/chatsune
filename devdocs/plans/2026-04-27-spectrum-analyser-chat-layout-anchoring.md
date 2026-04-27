# Spectrum Analyser — Chat-Layout Anchoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Anchor the voice visualiser's bar field to the chat content (text column + chat view), with smooth clamping from desktop overhang to mobile full-width and suppression on non-chat routes.

**Architecture:** Add a small Zustand layout store that ChatView and MessageList populate with bounding-rect data via a generic `useReportBounds` hook (ResizeObserver-backed). VoiceVisualiser subscribes to the store and either short-circuits (when bounds are null) or passes geometry through to a renderer whose `barLayout` is reworked to compute width and offset from the geometry instead of a hard-coded 90% viewport fraction.

**Tech Stack:** React 19, TypeScript, Vite, Zustand, Vitest, `@testing-library/react` (renderHook), Tailwind. Frontend lives under `frontend/`. All code, comments, identifiers, and commit messages in **British English**.

**Reference Spec:** `devdocs/specs/2026-04-27-spectrum-analyser-chat-layout-anchoring-design.md`

---

## File Map

**Created**

- `frontend/src/features/voice/stores/visualiserLayoutStore.ts` — Zustand store holding two nullable `Bounds` slots (`chatview`, `textColumn`) and a single `setBounds(target, bounds)` setter
- `frontend/src/features/voice/stores/__tests__/visualiserLayoutStore.test.ts` — unit tests for the store
- `frontend/src/features/voice/infrastructure/useReportBounds.ts` — hook attaching a `ResizeObserver` to a ref and writing the observed element's `getBoundingClientRect()` into the layout store
- `frontend/src/features/voice/infrastructure/__tests__/useReportBounds.test.ts` — unit tests for the hook (RO + getBoundingClientRect mocking)

**Modified**

- `frontend/src/features/voice/infrastructure/visualiserRenderers.ts` — `barLayout` accepts a new `geometry` argument; `WIDTH_FRACTION` constant removed; xOffset/usableWidth computed from geometry
- `frontend/src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts` — existing `barLayout` tests rewritten for the new signature; four new geometry cases added
- `frontend/src/features/voice/components/VoiceVisualiser.tsx` — subscribes to `visualiserLayoutStore`; short-circuits the RAF loop and clears the canvas when either bounds slot is null; passes geometry through to `drawVisualiserFrame`
- `frontend/src/features/chat/ChatView.tsx` — adds a ref on the outer `absolute inset-0` wrapper and calls `useReportBounds(ref, 'chatview')`
- `frontend/src/features/chat/MessageList.tsx` — adds a ref on the `mx-auto max-w-3xl` container at line 132 and calls `useReportBounds(ref, 'textColumn')`

---

## Task 1: Layout Store

The store holds two independent slots populated by separate report sites. A single setter takes a discriminator so the hook can be generic.

**Files:**
- Create: `frontend/src/features/voice/stores/visualiserLayoutStore.ts`
- Test: `frontend/src/features/voice/stores/__tests__/visualiserLayoutStore.test.ts`

- [ ] **Step 1: Create the store skeleton (types + empty implementation)**

Write `frontend/src/features/voice/stores/visualiserLayoutStore.ts`:

```ts
import { create } from 'zustand'

export interface Bounds {
  /** Viewport-relative left edge in CSS pixels. */
  x: number
  /** Width in CSS pixels. */
  w: number
}

export type LayoutTarget = 'chatview' | 'textColumn'

interface LayoutState {
  chatview: Bounds | null
  textColumn: Bounds | null
  setBounds: (target: LayoutTarget, bounds: Bounds | null) => void
}

export const useVisualiserLayoutStore = create<LayoutState>((set) => ({
  chatview: null,
  textColumn: null,
  setBounds: () => {},
}))
```

- [ ] **Step 2: Write the failing test**

Write `frontend/src/features/voice/stores/__tests__/visualiserLayoutStore.test.ts`:

```ts
import { beforeEach, describe, expect, it } from 'vitest'
import { useVisualiserLayoutStore } from '../visualiserLayoutStore'

function reset() {
  useVisualiserLayoutStore.setState({ chatview: null, textColumn: null })
}

describe('visualiserLayoutStore', () => {
  beforeEach(reset)

  it('starts with both slots null', () => {
    const s = useVisualiserLayoutStore.getState()
    expect(s.chatview).toBeNull()
    expect(s.textColumn).toBeNull()
  })

  it('setBounds writes to the chatview slot', () => {
    useVisualiserLayoutStore.getState().setBounds('chatview', { x: 240, w: 1680 })
    expect(useVisualiserLayoutStore.getState().chatview).toEqual({ x: 240, w: 1680 })
    expect(useVisualiserLayoutStore.getState().textColumn).toBeNull()
  })

  it('setBounds writes to the textColumn slot independently', () => {
    useVisualiserLayoutStore.getState().setBounds('textColumn', { x: 816, w: 768 })
    expect(useVisualiserLayoutStore.getState().textColumn).toEqual({ x: 816, w: 768 })
    expect(useVisualiserLayoutStore.getState().chatview).toBeNull()
  })

  it('setBounds(target, null) clears the slot', () => {
    const s = useVisualiserLayoutStore.getState()
    s.setBounds('chatview', { x: 0, w: 1000 })
    s.setBounds('chatview', null)
    expect(useVisualiserLayoutStore.getState().chatview).toBeNull()
  })

  it('setting one slot does not disturb the other', () => {
    const s = useVisualiserLayoutStore.getState()
    s.setBounds('chatview', { x: 0, w: 1000 })
    s.setBounds('textColumn', { x: 116, w: 768 })
    s.setBounds('chatview', null)
    expect(useVisualiserLayoutStore.getState().chatview).toBeNull()
    expect(useVisualiserLayoutStore.getState().textColumn).toEqual({ x: 116, w: 768 })
  })
})
```

- [ ] **Step 3: Run the tests and verify they fail**

Run: `cd frontend && pnpm vitest run src/features/voice/stores/__tests__/visualiserLayoutStore.test.ts`

Expected: at least the four `setBounds` tests fail (the stub setter is a no-op, so writes never land).

- [ ] **Step 4: Implement the setter**

Edit `frontend/src/features/voice/stores/visualiserLayoutStore.ts`, replace the `setBounds: () => {}` line:

```ts
  setBounds: (target, bounds) => set({ [target]: bounds } as Pick<LayoutState, LayoutTarget>),
```

- [ ] **Step 5: Run the tests and verify they pass**

Run: `cd frontend && pnpm vitest run src/features/voice/stores/__tests__/visualiserLayoutStore.test.ts`

Expected: all five tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/voice/stores/visualiserLayoutStore.ts \
        frontend/src/features/voice/stores/__tests__/visualiserLayoutStore.test.ts
git commit -m "Add visualiser layout store"
```

---

## Task 2: `useReportBounds` Hook

The hook attaches a `ResizeObserver` to the ref's element and writes the element's `getBoundingClientRect()` (as `{ x, w }`) into the store under the named slot. On unmount it clears the slot. It also fires once on mount because some browsers don't fire RO for the initial layout pass.

**Files:**
- Create: `frontend/src/features/voice/infrastructure/useReportBounds.ts`
- Test: `frontend/src/features/voice/infrastructure/__tests__/useReportBounds.test.ts`

- [ ] **Step 1: Write the failing test**

Write `frontend/src/features/voice/infrastructure/__tests__/useReportBounds.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useRef } from 'react'
import { useReportBounds } from '../useReportBounds'
import { useVisualiserLayoutStore } from '../../stores/visualiserLayoutStore'

type ROCallback = (entries: ResizeObserverEntry[]) => void

let observers: { cb: ROCallback; el: Element | null }[] = []
const OriginalRO = globalThis.ResizeObserver
const originalGBCR = Element.prototype.getBoundingClientRect

function mockRect(x: number, w: number) {
  Element.prototype.getBoundingClientRect = vi.fn(() => ({
    x, y: 0, width: w, height: 100,
    top: 0, left: x, right: x + w, bottom: 100,
    toJSON: () => ({}),
  }))
}

function fireAll() {
  for (const { cb, el } of observers) {
    if (!el) continue
    cb([{ target: el } as ResizeObserverEntry])
  }
}

beforeEach(() => {
  observers = []
  globalThis.ResizeObserver = class {
    private cb: ROCallback
    private el: Element | null = null
    constructor(cb: ROCallback) {
      this.cb = cb
      observers.push({ cb, el: null })
    }
    observe(el: Element) {
      this.el = el
      const slot = observers.find((o) => o.cb === this.cb)
      if (slot) slot.el = el
    }
    unobserve() {}
    disconnect() {
      this.el = null
    }
  } as unknown as typeof ResizeObserver
  useVisualiserLayoutStore.setState({ chatview: null, textColumn: null })
})

afterEach(() => {
  globalThis.ResizeObserver = OriginalRO
  Element.prototype.getBoundingClientRect = originalGBCR
})

describe('useReportBounds', () => {
  it('reports bounds for the chatview target on mount', () => {
    mockRect(240, 1680)
    renderHook(() => {
      const ref = useRef<HTMLDivElement>(null)
      // Simulate a real DOM element being attached.
      if (!ref.current) ref.current = document.createElement('div')
      useReportBounds(ref, 'chatview')
      return ref
    })
    expect(useVisualiserLayoutStore.getState().chatview).toEqual({ x: 240, w: 1680 })
  })

  it('reports bounds for the textColumn target', () => {
    mockRect(816, 768)
    renderHook(() => {
      const ref = useRef<HTMLDivElement>(null)
      if (!ref.current) ref.current = document.createElement('div')
      useReportBounds(ref, 'textColumn')
      return ref
    })
    expect(useVisualiserLayoutStore.getState().textColumn).toEqual({ x: 816, w: 768 })
  })

  it('updates bounds when the observer fires', () => {
    mockRect(100, 1000)
    renderHook(() => {
      const ref = useRef<HTMLDivElement>(null)
      if (!ref.current) ref.current = document.createElement('div')
      useReportBounds(ref, 'chatview')
      return ref
    })
    expect(useVisualiserLayoutStore.getState().chatview).toEqual({ x: 100, w: 1000 })
    mockRect(150, 1100)
    fireAll()
    expect(useVisualiserLayoutStore.getState().chatview).toEqual({ x: 150, w: 1100 })
  })

  it('clears the slot to null on unmount', () => {
    mockRect(0, 800)
    const { unmount } = renderHook(() => {
      const ref = useRef<HTMLDivElement>(null)
      if (!ref.current) ref.current = document.createElement('div')
      useReportBounds(ref, 'textColumn')
      return ref
    })
    expect(useVisualiserLayoutStore.getState().textColumn).toEqual({ x: 0, w: 800 })
    unmount()
    expect(useVisualiserLayoutStore.getState().textColumn).toBeNull()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails with module-not-found**

Run: `cd frontend && pnpm vitest run src/features/voice/infrastructure/__tests__/useReportBounds.test.ts`

Expected: fails because `useReportBounds` does not exist.

- [ ] **Step 3: Implement the hook**

Write `frontend/src/features/voice/infrastructure/useReportBounds.ts`:

```ts
import { useEffect, type RefObject } from 'react'
import {
  useVisualiserLayoutStore,
  type LayoutTarget,
} from '../stores/visualiserLayoutStore'

/**
 * Reports the viewport-relative x and width of `ref.current` into the
 * layout store under `target`, both on mount and on every ResizeObserver
 * notification. Clears the slot to `null` on unmount.
 *
 * Uses `getBoundingClientRect()` rather than `entry.contentRect` because
 * we want viewport-relative coordinates (the visualiser canvas is a
 * fixed overlay sized to the viewport), and `contentRect` is
 * element-relative.
 */
export function useReportBounds(
  ref: RefObject<HTMLElement | null>,
  target: LayoutTarget,
): void {
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const setBounds = useVisualiserLayoutStore.getState().setBounds
    const report = () => {
      const r = el.getBoundingClientRect()
      setBounds(target, { x: r.x, w: r.width })
    }
    report()
    const ro = new ResizeObserver(report)
    ro.observe(el)
    return () => {
      ro.disconnect()
      setBounds(target, null)
    }
  }, [ref, target])
}
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `cd frontend && pnpm vitest run src/features/voice/infrastructure/__tests__/useReportBounds.test.ts`

Expected: all four tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/infrastructure/useReportBounds.ts \
        frontend/src/features/voice/infrastructure/__tests__/useReportBounds.test.ts
git commit -m "Add useReportBounds hook for layout reporting"
```

---

## Task 3: Renderer Geometry

`barLayout` is the central geometry function used by all four visualiser styles. Today it clamps the bar field to a fixed 90% of canvas width. We replace that with a geometry argument that carries chatview and textColumn bounds, and compute the bar field from the spec algorithm.

**Files:**
- Modify: `frontend/src/features/voice/infrastructure/visualiserRenderers.ts`
- Test: `frontend/src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts`

- [ ] **Step 1: Rewrite the renderer test for the new signature**

Replace the entire contents of `frontend/src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts` with:

```ts
import { describe, expect, it } from 'vitest'
import { barLayout, type BarGeometry } from '../visualiserRenderers'

const BASE_GEOMETRY: BarGeometry = {
  chatview: { x: 0, w: 1000 },
  textColumn: { x: 116, w: 768 },
}

describe('barLayout', () => {
  it('keeps cy at vertical centre', () => {
    const { cy } = barLayout(1000, 240, 24, 0.5, BASE_GEOMETRY)
    expect(cy).toBe(120)
  })

  it('returns maxDy as half of height*frac', () => {
    const { maxDy } = barLayout(800, 200, 10, 0.28, BASE_GEOMETRY)
    expect(maxDy).toBeCloseTo(28)
  })

  it('scales bar width to 62% of slot', () => {
    const { slot, barW } = barLayout(1000, 200, 10, 0.5, BASE_GEOMETRY)
    expect(barW).toBeCloseTo(slot * 0.62)
  })

  describe('geometry', () => {
    it('overhang case: chatview wide enough → 1.2× textColumn, centred on text column', () => {
      // chatview 1920 with sidebar 240 on the left → starts at x=240
      // textColumn centred in chatview: x=816, w=768 (centre at 1200)
      const g: BarGeometry = {
        chatview: { x: 240, w: 1680 },
        textColumn: { x: 816, w: 768 },
      }
      const { xOffset, slot } = barLayout(1920, 200, 10, 0.5, g)
      // target = 768 * 1.2 = 921.6; min(921.6, 1680) = 921.6
      // centre = 1200; left = max(240, 1200 - 460.8) = 739.2
      expect(xOffset).toBeCloseTo(739.2)
      expect(slot * 10).toBeCloseTo(921.6)
    })

    it('full-width case: chatview equals textColumn → fills chatview', () => {
      const g: BarGeometry = {
        chatview: { x: 0, w: 768 },
        textColumn: { x: 0, w: 768 },
      }
      const { xOffset, slot } = barLayout(768, 200, 10, 0.5, g)
      expect(xOffset).toBe(0)
      expect(slot * 10).toBeCloseTo(768)
    })

    it('clamp case: chatview narrower than 1.2× textColumn → fills chatview', () => {
      // textColumn 768 centred in chatview 800 (off-centre by 16 either side)
      const g: BarGeometry = {
        chatview: { x: 0, w: 800 },
        textColumn: { x: 16, w: 768 },
      }
      const { xOffset, slot } = barLayout(800, 200, 10, 0.5, g)
      // target=921.6, usable=min(921.6,800)=800
      // centre=400, left=max(0,400-400)=0, right=min(800,400+400)=800
      expect(xOffset).toBe(0)
      expect(slot * 10).toBeCloseTo(800)
    })

    it('no-sidebar case: chatview = 1000, textColumn centred → 1.2× textColumn', () => {
      const g: BarGeometry = {
        chatview: { x: 0, w: 1000 },
        textColumn: { x: 116, w: 768 },
      }
      const { xOffset, slot } = barLayout(1000, 200, 10, 0.5, g)
      // target=921.6, usable=921.6, centre=500, left=max(0,500-460.8)=39.2
      expect(xOffset).toBeCloseTo(39.2)
      expect(slot * 10).toBeCloseTo(921.6)
    })
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && pnpm vitest run src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts`

Expected: fails. The signature mismatch (extra arg) and the missing `BarGeometry` export will cause TypeScript errors and assertion failures.

- [ ] **Step 3: Update `visualiserRenderers.ts`: add the type and rewrite `barLayout`**

Edit `frontend/src/features/voice/infrastructure/visualiserRenderers.ts`:

Remove the `WIDTH_FRACTION` constant block (lines 14–15 in the current file, including the comment).

Add a `BarGeometry` type below `RenderOpts`:

```ts
export interface BarGeometry {
  /** Inner-of-sidebars area, viewport-relative. */
  chatview: { x: number; w: number }
  /** Centred message column, viewport-relative. */
  textColumn: { x: number; w: number }
}
```

Replace `barLayout` with:

```ts
export function barLayout(
  width: number,
  height: number,
  n: number,
  frac: number,
  geometry: BarGeometry,
): { cy: number; slot: number; barW: number; maxDy: number; xOffset: number } {
  const { chatview, textColumn } = geometry
  const target = textColumn.w * 1.2
  const usable = Math.min(target, chatview.w)
  const centre = textColumn.x + textColumn.w / 2
  const left = Math.max(chatview.x, centre - usable / 2)
  const right = Math.min(chatview.x + chatview.w, centre + usable / 2)
  const xOffset = left
  const finalWidth = right - left
  const cy = height / 2
  const slot = finalWidth / n
  const barW = slot * 0.62
  const maxDy = (height * frac) / 2
  return { cy, slot, barW, maxDy, xOffset }
}
```

- [ ] **Step 4: Update the four draw functions to thread `geometry` through**

Each of `drawSharp`, `drawSoft`, `drawGlow`, `drawGlass` currently calls `barLayout(w, h, n, o.maxHeightFraction)`. They need to receive and forward `geometry`. Update their signatures and call sites within `visualiserRenderers.ts`.

Change each draw function's signature from:

```ts
function drawSharp(ctx: CanvasRenderingContext2D, w: number, h: number, bins: Float32Array, o: RenderOpts) {
```

to:

```ts
function drawSharp(ctx: CanvasRenderingContext2D, w: number, h: number, bins: Float32Array, o: RenderOpts, g: BarGeometry) {
```

Apply the same change to `drawSoft`, `drawGlow`, `drawGlass`.

In each draw function body, change:

```ts
const { cy, slot, barW, maxDy, xOffset } = barLayout(w, h, n, o.maxHeightFraction)
```

to:

```ts
const { cy, slot, barW, maxDy, xOffset } = barLayout(w, h, n, o.maxHeightFraction, g)
```

- [ ] **Step 5: Update `drawVisualiserFrame` to accept and forward geometry**

Change its signature from:

```ts
export function drawVisualiserFrame(
  style: VisualiserStyle,
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  bins: Float32Array,
  opts: RenderOpts,
): void {
```

to:

```ts
export function drawVisualiserFrame(
  style: VisualiserStyle,
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  bins: Float32Array,
  opts: RenderOpts,
  geometry: BarGeometry,
): void {
```

And update each `case` to forward `geometry`:

```ts
case 'sharp': drawSharp(ctx, width, height, bins, opts, geometry); break
case 'soft':  drawSoft(ctx, width, height, bins, opts, geometry); break
case 'glow':  drawGlow(ctx, width, height, bins, opts, geometry); break
case 'glass': drawGlass(ctx, width, height, bins, opts, geometry); break
```

- [ ] **Step 6: Run renderer tests and verify they pass**

Run: `cd frontend && pnpm vitest run src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts`

Expected: all seven tests pass (3 invariants + 4 geometry cases).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/voice/infrastructure/visualiserRenderers.ts \
        frontend/src/features/voice/infrastructure/__tests__/visualiserRenderers.test.ts
git commit -m "Make barLayout geometry-aware"
```

---

## Task 4: VoiceVisualiser Store Integration

The component now needs to read both layout slots from the store and either short-circuit (when either is null) or forward the geometry to `drawVisualiserFrame`. Short-circuiting means: cancel any pending RAF, clear the canvas once, and skip ticks until both slots reappear.

**Files:**
- Modify: `frontend/src/features/voice/components/VoiceVisualiser.tsx`

- [ ] **Step 1: Add the store import and subscription**

Edit `frontend/src/features/voice/components/VoiceVisualiser.tsx`. After the existing store imports near the top (around line 3), add:

```ts
import { useVisualiserLayoutStore } from '../stores/visualiserLayoutStore'
```

Inside `VoiceVisualiser` (around line 39, alongside the other store reads), add:

```ts
  const chatview = useVisualiserLayoutStore((s) => s.chatview)
  const textColumn = useVisualiserLayoutStore((s) => s.textColumn)
```

- [ ] **Step 2: Short-circuit the effect when either slot is null**

In the main `useEffect` body (currently starting at line 76), replace the existing `if (!enabled) { ... }` block (lines 77–86) with the combined guard below. The replacement preserves the original cleanup logic and folds the new bounds check into the same branch:

```ts
    if (!enabled || !chatview || !textColumn) {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
      const c = canvasRef.current
      if (c) c.getContext('2d')?.clearRect(0, 0, c.width, c.height)
      activeRef.current = 0
      return
    }
```

This collapses the `enabled` guard and the new `bounds` guard into one branch with identical cleanup.

- [ ] **Step 3: Forward geometry to all `drawVisualiserFrame` calls**

There are two `drawVisualiserFrame` call sites in the file (the paused branch around line 126 and the active branch around line 156). Both must pass the geometry. Build the geometry object once per tick (right after the canvas-size check, before the paused branch). Insert this immediately after the `if (c.width !== w || c.height !== h) { c.width = w; c.height = h }` line (around line 98):

```ts
      const geometry = { chatview, textColumn }
```

Then update each `drawVisualiserFrame` call to pass `geometry` as the seventh argument.

Paused branch (around line 126):

```ts
        drawVisualiserFrame(style, ctx, w, h, frozenBinsRef.current, {
          rgb,
          rgbLight,
          opacity: opacity * breath,
          maxHeightFraction: MAX_HEIGHT_FRACTION,
        }, geometry)
```

Active branch (around line 156):

```ts
          drawVisualiserFrame(style, ctx, w, h, bins, {
            rgb,
            rgbLight,
            opacity: opacity * activeRef.current,
            maxHeightFraction: MAX_HEIGHT_FRACTION,
          }, geometry)
```

- [ ] **Step 4: Add `chatview` and `textColumn` to the effect's deps array**

The `useEffect` at the end of its body has a deps array on line 203:

```ts
  }, [enabled, style, opacity, barCount, personaColourHex, accessors, paused, ttsExpected])
```

Replace it with:

```ts
  }, [enabled, style, opacity, barCount, personaColourHex, accessors, paused, ttsExpected, chatview, textColumn])
```

This ensures the effect re-runs when bounds appear or disappear, which restarts the loop.

- [ ] **Step 5: Run frontend build to verify the type changes hold together**

Run: `cd frontend && pnpm run build`

Expected: build succeeds with no TypeScript errors. (`tsc -b` in `pnpm run build` is stricter than `pnpm tsc --noEmit` and matches CI.)

- [ ] **Step 6: Run the full test suite to verify nothing else broke**

Run: `cd frontend && pnpm vitest run`

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/voice/components/VoiceVisualiser.tsx
git commit -m "Subscribe VoiceVisualiser to layout store and forward geometry"
```

---

## Task 5: ChatView Reports Chat-View Bounds

The outer wrapper of ChatView's main render (`ChatView.tsx:1041` — `<div className="absolute inset-0 flex flex-col overflow-hidden">`) sits inside `<main>`, which fills the area between the sidebar and the right edge below the topbar. This is the "chat view" anchor.

**Files:**
- Modify: `frontend/src/features/chat/ChatView.tsx`

- [ ] **Step 1: Add the import**

Edit `frontend/src/features/chat/ChatView.tsx`. Add to the existing imports (group with the other feature imports near the top of the file):

```ts
import { useReportBounds } from '../voice/infrastructure/useReportBounds'
```

- [ ] **Step 2: Add a ref and call the hook**

Inside the `ChatView` component body (top-level, alongside other ref/state declarations — verify the surrounding code by reading the existing component structure first), add:

```ts
  const chatviewRef = useRef<HTMLDivElement>(null)
  useReportBounds(chatviewRef, 'chatview')
```

If `useRef` is not yet imported in this file, add it to the React import.

- [ ] **Step 3: Attach the ref to the outer wrapper at line 1041**

Locate the `return (` block whose first child is the `<div className="absolute inset-0 flex flex-col overflow-hidden">` div. Add the ref:

```tsx
    <div ref={chatviewRef} className="absolute inset-0 flex flex-col overflow-hidden">
```

- [ ] **Step 4: Verify the build**

Run: `cd frontend && pnpm run build`

Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/chat/ChatView.tsx
git commit -m "Report chat-view bounds for visualiser layout"
```

---

## Task 6: MessageList Reports Text-Column Bounds

The text column is the `<div className="mx-auto flex max-w-3xl flex-col gap-4">` at `MessageList.tsx:132`. Its viewport-relative x and w are exactly what the renderer needs.

**Files:**
- Modify: `frontend/src/features/chat/MessageList.tsx`

- [ ] **Step 1: Add the import**

Edit `frontend/src/features/chat/MessageList.tsx`. Add to the imports:

```ts
import { useReportBounds } from '../voice/infrastructure/useReportBounds'
```

If `useRef` is not yet imported, add it to the React import.

- [ ] **Step 2: Add a ref and call the hook**

Inside the component body, alongside other refs (`containerRef` etc.), add:

```ts
  const textColumnRef = useRef<HTMLDivElement>(null)
  useReportBounds(textColumnRef, 'textColumn')
```

- [ ] **Step 3: Attach the ref to the `max-w-3xl` div at line 132**

Change line 132 from:

```tsx
      <div className="mx-auto flex max-w-3xl flex-col gap-4">
```

to:

```tsx
      <div ref={textColumnRef} className="mx-auto flex max-w-3xl flex-col gap-4">
```

- [ ] **Step 4: Verify the build**

Run: `cd frontend && pnpm run build`

Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/chat/MessageList.tsx
git commit -m "Report text-column bounds for visualiser layout"
```

---

## Task 7: Manual Verification

Final verification on the running app. The unit tests cover the geometry math; this catches DOM/integration issues that mocks can't.

**Files:** none modified.

- [ ] **Step 1: Start the dev server**

Run: `cd frontend && pnpm dev`

Open the app in a desktop browser (Chromium or Firefox) at the URL shown.

- [ ] **Step 2: Verify desktop wide layout**

- Resize the window to ≥ 1280px wide
- Open or create a chat session, ensure the sidebar is visible
- Trigger TTS (send a message that the assistant will speak)
- Confirm: bars are centred over the message column, ~120% of column width, and **never** spill onto the sidebar

- [ ] **Step 3: Verify sidebar collapse**

- Collapse the sidebar
- Trigger TTS again
- Confirm: bars shift with the (now re-centred) message column, still ~120% of column width

- [ ] **Step 4: Verify smooth narrowing**

- Drag the window width down through ~900px → ~800px → ~700px
- Trigger TTS at each width
- Confirm: at ~900px bars are still 120% of column; somewhere around 922px window width the bars start clamping to chat-view width; below the breakpoint they fill the chat view edge-to-edge with no visible jump

- [ ] **Step 5: Verify mobile layout**

- Resize to < 768px (or use device emulation)
- Trigger TTS
- Confirm: text column shrinks to fit; bars fill the chat view edge-to-edge

- [ ] **Step 6: Verify route-change suppression**

- While TTS is playing, navigate to `/admin` (or another non-chat route)
- Confirm: visualiser disappears immediately, canvas is blank
- Navigate back to chat
- Confirm: visualiser reappears within one frame once ChatView mounts and reports bounds

- [ ] **Step 7: Verify all four visualiser styles still work**

- Open user settings → Voice tab
- Cycle through `sharp`, `soft`, `glow`, `glass`
- Trigger TTS for each
- Confirm: each style honours the new geometry (centred on text column, clamped to chat view)

- [ ] **Step 8: Final commit (only if any fixes were needed during manual verification)**

If manual verification revealed issues that needed code fixes, commit them with a clear message. Otherwise skip.

---

## Self-Review

This section documents the spec-coverage check the plan author already ran.

**Spec coverage:**
- "Bar-Feld-Breite = `min(1.2 × textColumnWidth, chatviewWidth)`, mittig auf der Textspalte" → Task 3, Step 3 (`barLayout` body)
- "Textspalte = `max-w-3xl mx-auto` Container" → Task 6 attaches the ref to exactly this div
- "Chatview = der Bereich rechts der Sidebar" → Task 5 attaches the ref to ChatView's outer wrapper, which sits inside `<main>` (right of `<nav>`)
- "Außerhalb Chat-Route: Visualiser rendert nichts" → Task 4, Step 2 short-circuits when either slot is null; Tasks 5/6's `useReportBounds` clears slots on unmount
- "ResizeObserver-backed reporting" → Task 2, Step 3 (hook implementation)
- "Mount-Reihenfolge robust" → Task 4, Step 4 adds `chatview`/`textColumn` to deps so the effect re-arms when bounds arrive
- "Renderer-Test mit den vier Geometrie-Cases" → Task 3, Step 1 (test file rewrite)
- "Manuelle Verifikation der sieben Cases" → Task 7

**Type consistency:**
- `Bounds` is defined in `visualiserLayoutStore.ts` and re-shaped (anonymously, same shape) in `BarGeometry` → consistent
- `LayoutTarget = 'chatview' | 'textColumn'` used identically in store, hook, and call sites
- `BarGeometry` exported from `visualiserRenderers.ts` and consumed by `VoiceVisualiser.tsx` (built inline as `{ chatview, textColumn }`)

No placeholders, all code blocks complete.

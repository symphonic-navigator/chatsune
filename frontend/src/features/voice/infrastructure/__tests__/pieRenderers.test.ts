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

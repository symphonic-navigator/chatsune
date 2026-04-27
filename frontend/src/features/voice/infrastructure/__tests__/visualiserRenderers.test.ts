import { describe, expect, it, vi } from 'vitest'
import { barLayout, dotLayout, drawTranscriptionDots, type BarGeometry, type RenderOpts } from '../visualiserRenderers'

const BASE_GEOMETRY: BarGeometry = {
  chatview: { x: 0, w: 1000 },
  textColumn: { x: 116, w: 768 },
}

describe('barLayout', () => {
  it('keeps cy at vertical centre', () => {
    const { cy } = barLayout(240, 24, 0.5, BASE_GEOMETRY)
    expect(cy).toBe(120)
  })

  it('returns maxDy as half of height*frac', () => {
    const { maxDy } = barLayout(200, 10, 0.28, BASE_GEOMETRY)
    expect(maxDy).toBeCloseTo(28)
  })

  it('scales bar width to 62% of slot', () => {
    const { slot, barW } = barLayout(200, 10, 0.5, BASE_GEOMETRY)
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
      const { xOffset, slot } = barLayout(200, 10, 0.5, g)
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
      const { xOffset, slot } = barLayout(200, 10, 0.5, g)
      expect(xOffset).toBe(0)
      expect(slot * 10).toBeCloseTo(768)
    })

    it('clamp case: chatview narrower than 1.2× textColumn → fills chatview', () => {
      // textColumn 768 centred in chatview 800 (off-centre by 16 either side)
      const g: BarGeometry = {
        chatview: { x: 0, w: 800 },
        textColumn: { x: 16, w: 768 },
      }
      const { xOffset, slot } = barLayout(200, 10, 0.5, g)
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
      const { xOffset, slot } = barLayout(200, 10, 0.5, g)
      // target=921.6, usable=921.6, centre=500, left=max(0,500-460.8)=39.2
      expect(xOffset).toBeCloseTo(39.2)
      expect(slot * 10).toBeCloseTo(921.6)
    })
  })
})

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

describe('drawDotsSharp colour application', () => {
  it('uses an rgba fillStyle with the rgbLight triplet', () => {
    const ctx = makeMockCtx()
    drawTranscriptionDots('sharp', ctx as unknown as CanvasRenderingContext2D, 240, DOT_OPTS, DOT_GEOM, 0)
    // After the call, fillStyle holds whatever was last set. Verify the
    // string format encodes rgbLight = [180, 158, 255].
    expect(ctx.fillStyle).toMatch(/^rgba\(180,\s*158,\s*255,/)
  })
})

describe('drawDotsSoft uses radial gradients', () => {
  it('creates one radial gradient per dot', () => {
    const ctx = makeMockCtx()
    drawTranscriptionDots('soft', ctx as unknown as CanvasRenderingContext2D, 240, DOT_OPTS, DOT_GEOM, 0)
    expect(ctx.createRadialGradient).toHaveBeenCalledTimes(3)
  })
})

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
    // Loose bound during the stub phase — Task 6 turns this into a
    // strict equality (6 arcs: 3 fill + 3 stroke) once glass is
    // style-specific. Keeping the bound loose here means the Task 2
    // test stays green when Task 6 doubles the arc count, instead of
    // becoming a regression check that needs simultaneous editing.
    const ctx = makeMockCtx()
    drawTranscriptionDots('glass', ctx as unknown as CanvasRenderingContext2D, 240, DOT_OPTS, DOT_GEOM, 0)
    expect(ctx.arc.mock.calls.length).toBeGreaterThanOrEqual(3)
  })
})

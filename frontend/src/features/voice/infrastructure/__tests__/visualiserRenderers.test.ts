import { describe, expect, it } from 'vitest'
import { barLayout, dotLayout, type BarGeometry } from '../visualiserRenderers'

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

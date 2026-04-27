import { describe, expect, it } from 'vitest'
import { barLayout } from '../visualiserRenderers'

describe('barLayout', () => {
  it('clamps the bar field to 90% of width, centred', () => {
    const { slot, xOffset } = barLayout(1000, 200, 10, 0.5)
    expect(xOffset).toBe(50)
    expect(slot).toBe(90)
  })

  it('keeps cy at vertical centre', () => {
    const { cy } = barLayout(1000, 240, 24, 0.5)
    expect(cy).toBe(120)
  })

  it('scales bar width to 62% of slot', () => {
    const { slot, barW } = barLayout(900, 200, 10, 0.5)
    expect(slot).toBeCloseTo(81)
    expect(barW).toBeCloseTo(81 * 0.62)
  })

  it('returns maxDy as half of height*frac', () => {
    const { maxDy } = barLayout(800, 200, 10, 0.28)
    expect(maxDy).toBeCloseTo(28)
  })
})

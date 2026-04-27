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

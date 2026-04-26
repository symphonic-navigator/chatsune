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

  it('saturates all output bins when input is uniform max', () => {
    const raw = new Uint8Array(128).fill(255)
    const out = bucketIntoLogBins(raw, SAMPLE_RATE, FFT_SIZE, 24)
    for (const v of out) expect(v).toBeCloseTo(1, 1)
  })

  it('concentrates mid-spectrum input in upper output bins (logarithmic mapping)', () => {
    // Only raw bins 60-70 (about 5.6-6.6 kHz at 24 kHz / fftSize=256) are hot.
    // With linear bucketing the peak output bar would be near index 11-13 of 24.
    // With log bucketing, 6 kHz is in the upper quarter of the 20 Hz - 12 kHz
    // range, so the peak output bar must be in the upper third (index >= 16).
    const raw = new Uint8Array(128)
    for (let i = 60; i <= 70; i++) raw[i] = 255
    const out = bucketIntoLogBins(raw, SAMPLE_RATE, FFT_SIZE, 24)
    let maxIdx = 0
    for (let i = 1; i < out.length; i++) if (out[i] > out[maxIdx]) maxIdx = i
    expect(maxIdx).toBeGreaterThanOrEqual(16)
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

/**
 * Synthetic per-bar "noise" target values for the VoiceVisualiser's
 * "TTS expected, no audio playing" state. Output is in the same
 * normalised [0, 1] space as `useTtsFrequencyData`'s smoothed bins,
 * so it can be written directly into the smoother's target slot and
 * the existing exponential smoother bridges noise <-> FFT handovers.
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

/**
 * Synthetic amplitude / frequency simulator used by the settings-tab live
 * preview to demonstrate the visualiser before any real TTS has played.
 * Models speech-like rhythm: syllable-rate bursts (~5 Hz), sentence-level
 * pauses (~20 % of period), and a slow macro envelope so it doesn't feel
 * mechanical. Frequency bins are pseudo-bands with low-frequency boost.
 *
 * Production rendering does NOT use this — it reads the real AnalyserNode.
 */

export function simulateAmplitude(t: number): number {
  const sentencePeriod = 3.4
  const phase = (t % sentencePeriod) / sentencePeriod
  const sentenceActive = phase < 0.82 ? 1 : Math.max(0, 1 - (phase - 0.82) * 8)
  const syllable = 0.5 + 0.5 * Math.sin(t * 11 + Math.sin(t * 0.7) * 2.2)
  const syllableBoost = Math.pow(syllable, 1.5)
  const macro = 0.65 + 0.35 * Math.sin(t * 0.5 + 1.3)
  const noise = 0.04 * (Math.random() - 0.5)
  return Math.max(0, Math.min(1, sentenceActive * (0.22 + 0.6 * syllableBoost) * macro + noise))
}

const seeds: number[] = []

/**
 * Smoothed, low-frequency-boosted synthetic bins. State is module-private
 * because the preview component only mounts once per Settings tab open.
 */
let binValues: Float32Array = new Float32Array(0)

export function simulateFrequencyBins(t: number, ampl: number, n: number): Float32Array {
  if (binValues.length !== n) {
    binValues = new Float32Array(n)
    seeds.length = 0
    for (let i = 0; i < n; i++) seeds.push(Math.random() * 100 + i * 0.7)
  }
  for (let i = 0; i < n; i++) {
    const lowBoost = Math.pow(1 - i / n, 0.55)
    const wobble = 0.5 + 0.5 * Math.sin(t * (1.6 + i * 0.16) + seeds[i])
    const target = ampl * lowBoost * (0.35 + 0.65 * wobble)
    binValues[i] += (target - binValues[i]) * 0.28
  }
  return binValues
}

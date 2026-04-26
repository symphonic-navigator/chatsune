export const FREQ_MIN_HZ = 20
export const FREQ_MAX_HZ = 12_000

/**
 * Bucket linear-frequency FFT bins into logarithmic visualiser bars.
 *
 * The Web Audio API gives us `frequencyBinCount` bins (= fftSize / 2),
 * each covering an equal slice of [0, sampleRate/2]. Human pitch
 * perception is logarithmic, so a bar-per-linear-bin mapping puts almost
 * all visible motion into a few high-frequency bars and leaves the bass
 * bars nearly static. We instead lay the visualiser bars out logarithmically
 * across [FREQ_MIN_HZ, FREQ_MAX_HZ].
 */
export function bucketIntoLogBins(
  rawBins: Uint8Array,
  sampleRate: number,
  fftSize: number,
  outputBins: number,
): Float32Array {
  const result = new Float32Array(outputBins)
  const rawCount = rawBins.length
  const hzPerRawBin = sampleRate / fftSize
  const logMin = Math.log(FREQ_MIN_HZ)
  const logMax = Math.log(FREQ_MAX_HZ)

  for (let i = 0; i < outputBins; i++) {
    const fStart = Math.exp(logMin + ((logMax - logMin) * i) / outputBins)
    const fEnd = Math.exp(logMin + ((logMax - logMin) * (i + 1)) / outputBins)

    const rawStart = Math.max(0, Math.floor(fStart / hzPerRawBin))
    const rawEnd = Math.min(rawCount, Math.ceil(fEnd / hzPerRawBin))

    if (rawEnd <= rawStart) {
      // Defensive fallback for coarser FFT configurations where a single log
      // output bin is narrower than one raw FFT bin. With the project's default
      // 24 kHz / fftSize=256 (93.75 Hz per raw bin) this branch is unreachable,
      // but it keeps the function correct under any future analyser tuning.
      const idx = Math.min(rawCount - 1, Math.max(0, Math.round(fStart / hzPerRawBin)))
      result[i] = rawBins[idx] / 255
      continue
    }

    let sum = 0
    for (let j = rawStart; j < rawEnd; j++) sum += rawBins[j]
    result[i] = sum / (rawEnd - rawStart) / 255
  }
  return result
}

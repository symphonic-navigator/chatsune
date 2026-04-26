import { useEffect, useRef } from 'react'
import { audioPlayback } from './audioPlayback'
import { bucketIntoLogBins } from './visualiserBucketing'

const SMOOTHING = 0.28

interface FrequencyAccessors {
  /**
   * Reads the current frequency bins, log-bucketed and exponentially
   * smoothed across frames. Returns null if the analyser is not yet
   * available (i.e. no TTS has played in this session).
   */
  getBins(): Float32Array | null
  /** True iff the playback singleton currently believes audio is playing. */
  isActive(): boolean
}

export function useTtsFrequencyData(barCount: number): FrequencyAccessors {
  const rawBuffer = useRef<Uint8Array>(new Uint8Array(128))
  const smoothed = useRef<Float32Array>(new Float32Array(barCount))

  useEffect(() => {
    if (smoothed.current.length !== barCount) {
      smoothed.current = new Float32Array(barCount)
    }
  }, [barCount])

  const accessorsRef = useRef<FrequencyAccessors>({
    getBins: () => null,
    isActive: () => false,
  })

  // Re-bind accessor implementations once per render so they always close
  // over the latest barCount.
  accessorsRef.current = {
    getBins: () => {
      const analyser = audioPlayback.getAnalyser()
      if (!analyser) return null
      if (rawBuffer.current.length !== analyser.frequencyBinCount) {
        rawBuffer.current = new Uint8Array(analyser.frequencyBinCount)
      }
      analyser.getByteFrequencyData(rawBuffer.current)
      const target = bucketIntoLogBins(
        rawBuffer.current,
        analyser.context.sampleRate,
        analyser.fftSize,
        barCount,
      )
      const out = smoothed.current
      for (let i = 0; i < barCount; i++) {
        out[i] += (target[i] - out[i]) * SMOOTHING
      }
      return out
    },
    isActive: () => audioPlayback.isPlaying(),
  }

  return accessorsRef.current
}

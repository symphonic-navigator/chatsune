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

/**
 * Hook bridging the TTS playback `AnalyserNode` to log-bucketed, smoothed
 * frequency bins. The returned accessor object has a stable reference
 * across renders — closures read the current `barCount` via an internal
 * ref so we don't need to recreate them, which would force consumers'
 * effects to tear down and restart their RAF loops on every parent render.
 */
export function useTtsFrequencyData(barCount: number): FrequencyAccessors {
  // Explicit ArrayBuffer parameterisation — `getByteFrequencyData` rejects
  // the default `Uint8Array<ArrayBufferLike>` because that union includes
  // `SharedArrayBuffer`, which the Web Audio API does not accept here.
  const rawBuffer = useRef<Uint8Array<ArrayBuffer>>(new Uint8Array(128))
  const smoothed = useRef<Float32Array>(new Float32Array(barCount))
  const barCountRef = useRef(barCount)

  // Keep the buffer + ref in sync with the latest barCount on render. This
  // does not affect the stable reference returned below.
  if (barCountRef.current !== barCount) {
    barCountRef.current = barCount
    if (smoothed.current.length !== barCount) {
      smoothed.current = new Float32Array(barCount)
    }
  }

  // Belt-and-braces: also resize on effect, in case a consumer re-renders
  // without going through the synchronous path above (e.g. StrictMode).
  useEffect(() => {
    barCountRef.current = barCount
    if (smoothed.current.length !== barCount) {
      smoothed.current = new Float32Array(barCount)
    }
  }, [barCount])

  // Initialised once per component lifetime — closures read refs, so this
  // object's identity is stable across renders.
  const accessorsRef = useRef<FrequencyAccessors | null>(null)
  if (accessorsRef.current === null) {
    accessorsRef.current = {
      getBins: () => {
        const analyser = audioPlayback.getAnalyser()
        if (!analyser) return null
        const bc = barCountRef.current
        if (rawBuffer.current.length !== analyser.frequencyBinCount) {
          rawBuffer.current = new Uint8Array(analyser.frequencyBinCount)
        }
        analyser.getByteFrequencyData(rawBuffer.current)
        const target = bucketIntoLogBins(
          rawBuffer.current,
          analyser.context.sampleRate,
          analyser.fftSize,
          bc,
        )
        const out = smoothed.current
        for (let i = 0; i < bc; i++) {
          out[i] += (target[i] - out[i]) * SMOOTHING
        }
        return out
      },
      isActive: () => audioPlayback.isActive(),
    }
  }

  return accessorsRef.current
}

import type { VoicePreset } from '../../../voice/types'
import { listXaiVoices, toVoicePreset } from './api'

export const xaiVoices: { current: VoicePreset[] } = { current: [] }

// Parallel callers share the same inflight promise, so both observe the
// populated module-level cache after awaiting. The generation counter
// guards against invalidation-mid-fetch (onDeactivate during a pending
// request), so a stale response cannot overwrite a cleared cache.
let inflight: Promise<void> | null = null
let currentGeneration = 0

export function invalidateXaiVoicesCache(): void {
  currentGeneration++
  inflight = null
  xaiVoices.current = []
}

export function refreshXaiVoices(): Promise<void> {
  if (inflight) return inflight
  const gen = ++currentGeneration
  inflight = (async () => {
    try {
      const all = await listXaiVoices()
      if (gen !== currentGeneration) return
      xaiVoices.current = all.map(toVoicePreset)
    } catch {
      // Soft-fail: keep the existing list.
    } finally {
      inflight = null
    }
  })()
  return inflight
}

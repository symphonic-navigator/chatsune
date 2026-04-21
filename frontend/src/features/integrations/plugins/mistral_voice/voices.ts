import type { VoicePreset } from '../../../voice/types'
import { listVoices, toVoicePreset } from './api'

// Populated at runtime by the plugin from the Mistral voices list.
// Empty at module load; engines.ts reads via this mutable export.
export const mistralVoices: { current: VoicePreset[] } = { current: [] }

// Parallel callers share the same inflight promise, so both observe the
// populated module-level cache after awaiting. The generation counter
// guards against invalidation-mid-fetch (onDeactivate during a pending
// request), so a stale response cannot overwrite a cleared cache.
let inflight: Promise<void> | null = null
let currentGeneration = 0

export function invalidateVoicesCache(): void {
  currentGeneration++
  inflight = null
  mistralVoices.current = []
}

export function refreshMistralVoices(): Promise<void> {
  if (inflight) return inflight
  const gen = ++currentGeneration
  inflight = (async () => {
    try {
      const all = await listVoices()
      if (gen !== currentGeneration) return
      mistralVoices.current = all.map(toVoicePreset)
    } catch {
      // Soft-fail: keep the existing list.
    } finally {
      inflight = null
    }
  })()
  return inflight
}

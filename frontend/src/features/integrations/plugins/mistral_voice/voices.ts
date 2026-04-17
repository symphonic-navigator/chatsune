import type { VoicePreset } from '../../../voice/types'
import { listVoices } from './api'

// Populated at runtime by the plugin from the Mistral voices list.
// Empty at module load; engines.ts reads via this mutable export.
export const mistralVoices: { current: VoicePreset[] } = { current: [] }

// Generation counter guards against stale refreshes from rapid activate/deactivate cycles.
// Each call to refreshMistralVoices captures the generation at call time; if the generation
// has advanced by the time the network response arrives, the result is discarded.
let refreshGeneration = 0

export function invalidateVoicesCache(): void {
  refreshGeneration++
  mistralVoices.current = []
}

export async function refreshMistralVoices(apiKey: string): Promise<void> {
  const myGen = ++refreshGeneration
  try {
    const all = await listVoices(apiKey)
    if (myGen !== refreshGeneration) return // stale — a newer refresh or invalidate happened
    mistralVoices.current = all.map((v) => ({
      id: v.id,
      name: v.name,
      // Mistral voices are multilingual; default to 'en' as the primary language
      // since the API does not guarantee a single-language label per voice.
      language: 'en',
    }))
  } catch {
    // Soft-fail: keep the existing list if the refresh fails.
  }
}

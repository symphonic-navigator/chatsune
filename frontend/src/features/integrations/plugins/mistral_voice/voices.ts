import type { VoicePreset } from '../../../voice/types'
import { listVoices } from './api'

// Populated at runtime by the plugin from the Mistral voices list.
// Empty at module load; engines.ts reads via this mutable export.
export const mistralVoices: { current: VoicePreset[] } = { current: [] }

export async function refreshMistralVoices(apiKey: string): Promise<void> {
  try {
    const all = await listVoices(apiKey)
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

import type { VoicePreset } from '../../../voice/types'
import { listXaiVoices, toVoicePreset } from './api'

export const xaiVoices: { current: VoicePreset[] } = { current: [] }

let refreshGeneration = 0

export function invalidateXaiVoicesCache(): void {
  refreshGeneration++
  xaiVoices.current = []
}

export async function refreshXaiVoices(): Promise<void> {
  const myGen = ++refreshGeneration
  try {
    const all = await listXaiVoices()
    if (myGen !== refreshGeneration) return // stale — ignore
    xaiVoices.current = all.map(toVoicePreset)
  } catch {
    // Soft-fail: keep the existing list. Matches mistral_voice behaviour.
  }
}

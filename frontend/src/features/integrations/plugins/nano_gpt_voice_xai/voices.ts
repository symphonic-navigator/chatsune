import type { VoicePreset } from '../../../voice/types'
import { listNanoGptXaiVoices, toVoicePreset } from './api'

export const nanoGptXaiVoices: { current: VoicePreset[] } = { current: [] }

let inflight: Promise<void> | null = null
let currentGeneration = 0

export function invalidateNanoGptXaiVoicesCache(): void {
  currentGeneration++
  inflight = null
  nanoGptXaiVoices.current = []
}

export function refreshNanoGptXaiVoices(): Promise<void> {
  if (inflight) return inflight
  const gen = ++currentGeneration
  inflight = (async () => {
    try {
      const all = await listNanoGptXaiVoices()
      if (gen !== currentGeneration) return
      nanoGptXaiVoices.current = all.map(toVoicePreset)
    } catch {
      // Soft-fail: keep the existing list.
    } finally {
      inflight = null
    }
  })()
  return inflight
}

import { useSyncExternalStore } from 'react'
import { audioPlayback } from './audioPlayback'

/**
 * Reactive hook reflecting whether audioPlayback is actively playing audio.
 * Uses useSyncExternalStore so components re-render on every transition
 * without polling.
 */
export function useAudioPlaybackActive(): boolean {
  return useSyncExternalStore(
    (onChange) => audioPlayback.subscribe(onChange),
    () => audioPlayback.isPlaying(),
    () => false, // SSR — not relevant here but required by the signature
  )
}

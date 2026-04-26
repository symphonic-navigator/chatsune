import { create } from 'zustand'
import { audioPlayback } from '../infrastructure/audioPlayback'
import { useConversationModeStore } from './conversationModeStore'

interface VisualiserPauseState {
  paused: boolean
  /** Whether the togglePause path muted the mic (so resume should unmute it). */
  mutedByPause: boolean
  togglePause: () => void
}

export const useVisualiserPauseStore = create<VisualiserPauseState>((set, get) => ({
  paused: false,
  mutedByPause: false,

  togglePause: () => {
    const { paused, mutedByPause } = get()
    if (!paused) {
      audioPlayback.suspend()
      const cm = useConversationModeStore.getState()
      if (cm.active && !cm.micMuted) {
        cm.setMicMuted(true)
        set({ paused: true, mutedByPause: true })
      } else {
        set({ paused: true, mutedByPause: false })
      }
    } else {
      audioPlayback.unsuspend()
      if (mutedByPause) {
        useConversationModeStore.getState().setMicMuted(false)
      }
      set({ paused: false, mutedByPause: false })
    }
  },
}))

// Auto-clear on idle: when audioPlayback transitions from active to idle
// (Cockpit-Stop, Group cancelled, queue drained, Live-mode exited), drop
// the pause state and restore the mic if we muted it. The subscription is
// established once at module import time and lives for the app lifetime.
audioPlayback.subscribe(() => {
  if (audioPlayback.isActive()) return
  const { paused, mutedByPause } = useVisualiserPauseStore.getState()
  if (!paused) return
  if (mutedByPause) {
    useConversationModeStore.getState().setMicMuted(false)
  }
  useVisualiserPauseStore.setState({ paused: false, mutedByPause: false })
})

import { create } from 'zustand'

// Persisted user preference for haptic feedback. Defaults to enabled; the
// actual Vibration API calls are no-ops on platforms that do not support it
// (iOS Safari, desktop browsers), so leaving it on causes no harm there.

const STORAGE_KEY = 'chatsune-haptics-enabled'

function loadEnabled(): boolean {
  if (typeof localStorage === 'undefined') return true
  const raw = localStorage.getItem(STORAGE_KEY)
  if (raw === null) return true
  return raw === '1'
}

function saveEnabled(value: boolean): void {
  if (typeof localStorage === 'undefined') return
  localStorage.setItem(STORAGE_KEY, value ? '1' : '0')
}

interface HapticsState {
  enabled: boolean
  setEnabled: (value: boolean) => void
}

export const useHapticsStore = create<HapticsState>((set) => ({
  enabled: loadEnabled(),
  setEnabled: (value) => {
    saveEnabled(value)
    set({ enabled: value })
  },
}))

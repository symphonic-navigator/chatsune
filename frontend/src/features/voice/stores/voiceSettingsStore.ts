import { create } from 'zustand'
import type { VoiceSettings } from '../types'

const STORAGE_KEY = 'chatsune_voice_settings'

const DEFAULT_SETTINGS: VoiceSettings = { enabled: false, inputMode: 'push-to-talk' }

export function loadVoiceSettings(): VoiceSettings {
  try {
    if (typeof localStorage === 'undefined') return { ...DEFAULT_SETTINGS }
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...DEFAULT_SETTINGS }
    return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) }
  } catch {
    return { ...DEFAULT_SETTINGS }
  }
}

export function saveVoiceSettings(settings: VoiceSettings): void {
  if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
}

interface VoiceSettingsState {
  settings: VoiceSettings
  update: (patch: Partial<VoiceSettings>) => void
}

export const useVoiceSettings = create<VoiceSettingsState>((set, get) => ({
  settings: loadVoiceSettings(),
  update: (patch) => {
    const next = { ...get().settings, ...patch }
    set({ settings: next })
    saveVoiceSettings(next)
  },
}))

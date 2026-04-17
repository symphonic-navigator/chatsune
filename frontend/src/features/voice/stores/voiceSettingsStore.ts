import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type InputMode = 'push-to-talk' | 'continuous'

interface VoiceSettingsState {
  inputMode: InputMode
  setInputMode(mode: InputMode): void
}

export const useVoiceSettingsStore = create<VoiceSettingsState>()(
  persist(
    (set) => ({
      inputMode: 'push-to-talk',
      setInputMode: (inputMode) => set({ inputMode }),
    }),
    { name: 'voice-settings' },
  ),
)

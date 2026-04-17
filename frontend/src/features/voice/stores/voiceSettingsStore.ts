import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type InputMode = 'push-to-talk' | 'continuous'

interface VoiceSettingsState {
  inputMode: InputMode
  autoSendTranscription: boolean
  setInputMode(mode: InputMode): void
  setAutoSendTranscription(value: boolean): void
}

export const useVoiceSettingsStore = create<VoiceSettingsState>()(
  persist(
    (set) => ({
      inputMode: 'push-to-talk',
      autoSendTranscription: false,
      setInputMode: (inputMode) => set({ inputMode }),
      setAutoSendTranscription: (autoSendTranscription) => set({ autoSendTranscription }),
    }),
    {
      name: 'voice-settings',
      // Hard-code push-to-talk regardless of what older builds persisted.
      // The Continuous mode UI has been retired — VAD will replace it later.
      merge: (persisted, current) => ({
        ...current,
        ...(persisted as Partial<VoiceSettingsState>),
        inputMode: 'push-to-talk',
      }),
    },
  ),
)

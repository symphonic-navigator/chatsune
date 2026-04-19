import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type InputMode = 'push-to-talk' | 'continuous'

export type VoiceActivationThreshold = 'low' | 'medium' | 'high'

interface VoiceSettingsState {
  inputMode: InputMode
  autoSendTranscription: boolean
  voiceActivationThreshold: VoiceActivationThreshold
  stt_provider_id: string | undefined
  setInputMode(mode: InputMode): void
  setAutoSendTranscription(value: boolean): void
  setVoiceActivationThreshold(value: VoiceActivationThreshold): void
  setSttProviderId(value: string | undefined): void
}

export const useVoiceSettingsStore = create<VoiceSettingsState>()(
  persist(
    (set) => ({
      inputMode: 'push-to-talk',
      autoSendTranscription: false,
      voiceActivationThreshold: 'medium',
      stt_provider_id: undefined,
      setInputMode: (inputMode) => set({ inputMode }),
      setAutoSendTranscription: (autoSendTranscription) => set({ autoSendTranscription }),
      setVoiceActivationThreshold: (voiceActivationThreshold) => set({ voiceActivationThreshold }),
      setSttProviderId: (stt_provider_id) => set({ stt_provider_id }),
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

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type InputMode = 'push-to-talk' | 'continuous'

export type VoiceActivationThreshold = 'low' | 'medium' | 'high'

export type VisualiserStyle = 'sharp' | 'soft' | 'glow' | 'glass'

export interface VoiceVisualisationSettings {
  enabled: boolean
  style: VisualiserStyle
  opacity: number   // clamped to [0.05, 0.80]
  barCount: number  // clamped to [16, 96], integer
}

const DEFAULT_VISUALISATION: VoiceVisualisationSettings = {
  enabled: true,
  style: 'soft',
  opacity: 0.5,
  barCount: 24,
}

interface VoiceSettingsState {
  inputMode: InputMode
  autoSendTranscription: boolean
  voiceActivationThreshold: VoiceActivationThreshold
  stt_provider_id: string | undefined
  visualisation: VoiceVisualisationSettings
  setInputMode(mode: InputMode): void
  setAutoSendTranscription(value: boolean): void
  setVoiceActivationThreshold(value: VoiceActivationThreshold): void
  setSttProviderId(value: string | undefined): void
  setVisualisationEnabled(value: boolean): void
  setVisualisationStyle(value: VisualiserStyle): void
  setVisualisationOpacity(value: number): void
  setVisualisationBarCount(value: number): void
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

export const useVoiceSettingsStore = create<VoiceSettingsState>()(
  persist(
    (set) => ({
      inputMode: 'push-to-talk',
      autoSendTranscription: false,
      voiceActivationThreshold: 'medium',
      stt_provider_id: undefined,
      visualisation: DEFAULT_VISUALISATION,
      setInputMode: (inputMode) => set({ inputMode }),
      setAutoSendTranscription: (autoSendTranscription) => set({ autoSendTranscription }),
      setVoiceActivationThreshold: (voiceActivationThreshold) => set({ voiceActivationThreshold }),
      setSttProviderId: (stt_provider_id) => set({ stt_provider_id }),
      setVisualisationEnabled: (enabled) => set((s) => ({ visualisation: { ...s.visualisation, enabled } })),
      setVisualisationStyle: (style) => set((s) => ({ visualisation: { ...s.visualisation, style } })),
      setVisualisationOpacity: (opacity) =>
        set((s) => ({ visualisation: { ...s.visualisation, opacity: clamp(opacity, 0.05, 0.80) } })),
      setVisualisationBarCount: (barCount) =>
        set((s) => ({ visualisation: { ...s.visualisation, barCount: clamp(Math.round(barCount), 16, 96) } })),
    }),
    {
      name: 'voice-settings',
      // Hard-code push-to-talk regardless of what older builds persisted.
      // The Continuous mode UI has been retired — VAD will replace it later.
      // Visualisation block is merged with defaults so older payloads hydrate.
      merge: (persisted, current) => {
        const p = persisted as Partial<VoiceSettingsState>
        return {
          ...current,
          ...p,
          inputMode: 'push-to-talk',
          visualisation: { ...current.visualisation, ...(p.visualisation ?? {}) },
        }
      },
    },
  ),
)

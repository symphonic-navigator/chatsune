import { beforeEach, describe, it, expect } from 'vitest'
import { useVoiceSettingsStore } from '../voiceSettingsStore'

const STORAGE_KEY = 'voice-settings'

describe('voiceSettingsStore — visualisation block', () => {
  beforeEach(() => {
    localStorage.clear()
    // Reset to a fresh store instance state.
    useVoiceSettingsStore.setState(useVoiceSettingsStore.getInitialState(), true)
  })

  it('exposes default visualisation settings', () => {
    const v = useVoiceSettingsStore.getState().visualisation
    expect(v.enabled).toBe(true)
    expect(v.style).toBe('soft')
    expect(v.opacity).toBe(0.5)
    expect(v.barCount).toBe(24)
  })

  it('setVisualisationEnabled updates the field', () => {
    useVoiceSettingsStore.getState().setVisualisationEnabled(false)
    expect(useVoiceSettingsStore.getState().visualisation.enabled).toBe(false)
  })

  it('setVisualisationStyle updates the field', () => {
    useVoiceSettingsStore.getState().setVisualisationStyle('glow')
    expect(useVoiceSettingsStore.getState().visualisation.style).toBe('glow')
  })

  it('setVisualisationOpacity clamps to [0.05, 0.80]', () => {
    const set = useVoiceSettingsStore.getState().setVisualisationOpacity
    set(0.001); expect(useVoiceSettingsStore.getState().visualisation.opacity).toBe(0.05)
    set(1.5);   expect(useVoiceSettingsStore.getState().visualisation.opacity).toBe(0.80)
    set(0.42);  expect(useVoiceSettingsStore.getState().visualisation.opacity).toBe(0.42)
  })

  it('setVisualisationBarCount clamps to [16, 96] and rounds to integer', () => {
    const set = useVoiceSettingsStore.getState().setVisualisationBarCount
    set(8);    expect(useVoiceSettingsStore.getState().visualisation.barCount).toBe(16)
    set(120);  expect(useVoiceSettingsStore.getState().visualisation.barCount).toBe(96)
    set(33.7); expect(useVoiceSettingsStore.getState().visualisation.barCount).toBe(34)
  })

  it('merges old persisted snapshots without visualisation block', () => {
    // Simulate an upgrade: persisted state is a pre-visualisation payload.
    const old = JSON.stringify({
      state: {
        inputMode: 'continuous', // will be hard-coded back to push-to-talk
        autoSendTranscription: true,
        voiceActivationThreshold: 'high',
        stt_provider_id: 'whisper',
      },
      version: 0,
    })
    localStorage.setItem(STORAGE_KEY, old)
    // Force the store to rehydrate from localStorage.
    useVoiceSettingsStore.persist.rehydrate()

    const s = useVoiceSettingsStore.getState()
    expect(s.autoSendTranscription).toBe(true)
    expect(s.voiceActivationThreshold).toBe('high')
    expect(s.visualisation.enabled).toBe(true)
    expect(s.visualisation.style).toBe('soft')
    expect(s.visualisation.opacity).toBe(0.5)
    expect(s.visualisation.barCount).toBe(24)
  })
})

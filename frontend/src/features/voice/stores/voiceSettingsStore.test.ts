import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useVoiceSettingsStore } from './voiceSettingsStore'

function resetStore() {
  window.localStorage.clear()
}

describe('voiceSettingsStore', () => {
  beforeEach(() => {
    resetStore()
  })

  it('defaults autoSendTranscription to false', async () => {
    const { useVoiceSettingsStore } = await import('./voiceSettingsStore')
    expect(useVoiceSettingsStore.getState().autoSendTranscription).toBe(false)
  })

  it('setAutoSendTranscription toggles the flag', async () => {
    const { useVoiceSettingsStore } = await import('./voiceSettingsStore')
    useVoiceSettingsStore.getState().setAutoSendTranscription(true)
    expect(useVoiceSettingsStore.getState().autoSendTranscription).toBe(true)
  })

  it('forces inputMode to push-to-talk even if localStorage claims continuous, while preserving other persisted fields', async () => {
    window.localStorage.setItem(
      'voice-settings',
      JSON.stringify({ state: { inputMode: 'continuous', autoSendTranscription: true }, version: 0 }),
    )
    const { useVoiceSettingsStore } = await import('./voiceSettingsStore')
    expect(useVoiceSettingsStore.getState().inputMode).toBe('push-to-talk')
    expect(useVoiceSettingsStore.getState().autoSendTranscription).toBe(true)
  })

  it('defaults stt_provider_id to undefined and persists the value', async () => {
    const { useVoiceSettingsStore } = await import('./voiceSettingsStore')
    expect(useVoiceSettingsStore.getState().stt_provider_id).toBeUndefined()
    useVoiceSettingsStore.getState().setSttProviderId('xai_voice')
    expect(useVoiceSettingsStore.getState().stt_provider_id).toBe('xai_voice')
    // Persist check via localStorage (the store uses persist middleware)
    const raw = window.localStorage.getItem('voice-settings')!
    expect(JSON.parse(raw).state.stt_provider_id).toBe('xai_voice')
  })
})

describe('voiceSettingsStore — redemptionMs', () => {
  beforeEach(() => {
    localStorage.clear()
    useVoiceSettingsStore.setState({ redemptionMs: 1728 })
  })

  it('defaults to 1728 ms (= 18 frames at 96 ms/frame)', () => {
    expect(useVoiceSettingsStore.getState().redemptionMs).toBe(1728)
  })

  it('setter clamps below 576 to 576', () => {
    useVoiceSettingsStore.getState().setRedemptionMs(100)
    expect(useVoiceSettingsStore.getState().redemptionMs).toBe(576)
  })

  it('setter clamps above 11520 to 11520', () => {
    useVoiceSettingsStore.getState().setRedemptionMs(20_000)
    expect(useVoiceSettingsStore.getState().redemptionMs).toBe(11_520)
  })

  it('setter accepts in-range values verbatim', () => {
    useVoiceSettingsStore.getState().setRedemptionMs(3000)
    expect(useVoiceSettingsStore.getState().redemptionMs).toBe(3000)
  })

  it('migration: persisted payload missing redemptionMs hydrates to default 1728', async () => {
    localStorage.setItem(
      'voice-settings',
      JSON.stringify({ state: { autoSendTranscription: true }, version: 0 }),
    )
    vi.resetModules()
    const { useVoiceSettingsStore: fresh } = await import('./voiceSettingsStore')
    expect(fresh.getState().redemptionMs).toBe(1728)
    expect(fresh.getState().autoSendTranscription).toBe(true)
  })

  it('migration: persisted out-of-range value gets clamped on hydrate', async () => {
    localStorage.setItem(
      'voice-settings',
      JSON.stringify({ state: { redemptionMs: 99_999 }, version: 0 }),
    )
    vi.resetModules()
    const { useVoiceSettingsStore: fresh } = await import('./voiceSettingsStore')
    expect(fresh.getState().redemptionMs).toBe(11_520)
  })
})

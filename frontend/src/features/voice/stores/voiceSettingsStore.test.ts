import { beforeEach, describe, expect, it } from 'vitest'

function resetStore() {
  window.localStorage.clear()
}

describe('voiceSettingsStore', () => {
  beforeEach(() => {
    resetStore()
    // @ts-expect-error -- vitest module cache helper
    import.meta.vitest?.resetModules?.()
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

  it('forces inputMode to push-to-talk even if localStorage claims continuous', async () => {
    window.localStorage.setItem(
      'voice-settings',
      JSON.stringify({ state: { inputMode: 'continuous', autoSendTranscription: false }, version: 0 }),
    )
    const { useVoiceSettingsStore } = await import('./voiceSettingsStore')
    expect(useVoiceSettingsStore.getState().inputMode).toBe('push-to-talk')
  })
})

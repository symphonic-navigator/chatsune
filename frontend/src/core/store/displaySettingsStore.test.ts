import { beforeEach, describe, expect, it } from 'vitest'

// Reset modules + localStorage between tests
beforeEach(() => {
  localStorage.clear()
  // Force re-import to reset module-level state
})

describe('loadDisplaySettings', () => {
  it('returns defaults when localStorage is empty', async () => {
    const { loadDisplaySettings } = await import('./displaySettingsStore')
    const settings = loadDisplaySettings()
    expect(settings.chatFontFamily).toBe('serif')
    expect(settings.chatFontSize).toBe('normal')
    expect(settings.whiteScript).toBe(false)
    expect(settings.uiScale).toBe(100)
  })

  it('restores saved values from localStorage', async () => {
    localStorage.setItem(
      'chatsune_display_settings',
      JSON.stringify({ chatFontFamily: 'sans-serif', uiScale: 120 }),
    )
    const { loadDisplaySettings } = await import('./displaySettingsStore')
    const settings = loadDisplaySettings()
    expect(settings.chatFontFamily).toBe('sans-serif')
    expect(settings.uiScale).toBe(120)
    // Other keys still default
    expect(settings.chatFontSize).toBe('normal')
  })
})

describe('saveDisplaySettings', () => {
  it('persists settings to localStorage', async () => {
    const { loadDisplaySettings, saveDisplaySettings } = await import('./displaySettingsStore')
    const current = loadDisplaySettings()
    saveDisplaySettings({ ...current, chatFontFamily: 'sans-serif' })
    const raw = JSON.parse(localStorage.getItem('chatsune_display_settings') ?? '{}')
    expect(raw.chatFontFamily).toBe('sans-serif')
  })
})

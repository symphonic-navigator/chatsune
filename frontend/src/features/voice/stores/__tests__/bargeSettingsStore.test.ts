import { describe, it, expect, beforeEach } from 'vitest'
import { useBargeSettingsStore } from '../bargeSettingsStore'

describe('bargeSettingsStore', () => {
  beforeEach(() => {
    // Reset store to defaults and clear persisted state between tests.
    useBargeSettingsStore.setState({ enabled: true })
    window.localStorage.clear()
  })

  it('defaults to enabled=true', () => {
    expect(useBargeSettingsStore.getState().enabled).toBe(true)
  })

  it('setEnabled writes the given value', () => {
    useBargeSettingsStore.getState().setEnabled(false)
    expect(useBargeSettingsStore.getState().enabled).toBe(false)
    useBargeSettingsStore.getState().setEnabled(true)
    expect(useBargeSettingsStore.getState().enabled).toBe(true)
  })

  it('toggle flips the value', () => {
    expect(useBargeSettingsStore.getState().enabled).toBe(true)
    useBargeSettingsStore.getState().toggle()
    expect(useBargeSettingsStore.getState().enabled).toBe(false)
    useBargeSettingsStore.getState().toggle()
    expect(useBargeSettingsStore.getState().enabled).toBe(true)
  })

  it('persists the value to localStorage under voice.barging.enabled', () => {
    useBargeSettingsStore.getState().setEnabled(false)
    const raw = window.localStorage.getItem('voice.barging.enabled')
    expect(raw).not.toBeNull()
    const parsed = JSON.parse(raw!)
    expect(parsed.state.enabled).toBe(false)
  })
})

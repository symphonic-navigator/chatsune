import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { VoiceTab } from '../VoiceTab'
import { useVoiceSettingsStore } from '../../../../features/voice/stores/voiceSettingsStore'

function renderVoiceTab() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <VoiceTab />
    </MemoryRouter>,
  )
}

describe('VoiceTab — visualisation section', () => {
  beforeEach(() => {
    localStorage.clear()
    useVoiceSettingsStore.setState(useVoiceSettingsStore.getInitialState(), true)
  })

  it('renders the master toggle in the on state by default', () => {
    renderVoiceTab()
    const toggle = screen.getByRole('checkbox', { name: /Visualisierung anzeigen/i })
    expect(toggle).toBeChecked()
  })

  it('toggling the master switch updates the store', () => {
    renderVoiceTab()
    const toggle = screen.getByRole('checkbox', { name: /Visualisierung anzeigen/i })
    fireEvent.click(toggle)
    expect(useVoiceSettingsStore.getState().visualisation.enabled).toBe(false)
  })

  it('clicking a style button updates the store', () => {
    renderVoiceTab()
    fireEvent.click(screen.getByRole('button', { name: /Glühend/i }))
    expect(useVoiceSettingsStore.getState().visualisation.style).toBe('glow')
  })

  it('moving the opacity slider updates the store', () => {
    renderVoiceTab()
    const slider = screen.getByLabelText(/Deckkraft/i) as HTMLInputElement
    fireEvent.change(slider, { target: { value: '70' } })
    expect(useVoiceSettingsStore.getState().visualisation.opacity).toBeCloseTo(0.7, 2)
  })

  it('moving the bar count slider updates the store', () => {
    renderVoiceTab()
    const slider = screen.getByLabelText(/Anzahl Säulen/i) as HTMLInputElement
    fireEvent.change(slider, { target: { value: '64' } })
    expect(useVoiceSettingsStore.getState().visualisation.barCount).toBe(64)
  })
})

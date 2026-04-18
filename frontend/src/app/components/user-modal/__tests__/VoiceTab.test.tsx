import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { VoiceTab } from '../VoiceTab'
import { useVoiceSettingsStore } from '../../../../features/voice/stores/voiceSettingsStore'

describe('VoiceTab', () => {
  beforeEach(() => {
    useVoiceSettingsStore.setState({
      autoSendTranscription: false,
      voiceActivationThreshold: 'medium',
    })
  })

  it('shows the auto-send toggle with the store default (Off)', () => {
    render(<VoiceTab />)
    expect(screen.getByRole('button', { name: /automatically send transcription/i })).toHaveTextContent(/off/i)
  })

  it('flips the store flag when clicked', async () => {
    const user = userEvent.setup()
    render(<VoiceTab />)
    await user.click(screen.getByRole('button', { name: /automatically send transcription/i }))
    expect(useVoiceSettingsStore.getState().autoSendTranscription).toBe(true)
  })

  it('renders Medium as the active Voice Activation Threshold button by default', () => {
    render(<VoiceTab />)
    const medium = screen.getByRole('button', { name: /voice activation threshold medium/i })
    expect(medium).toHaveAttribute('aria-pressed', 'true')
    const low = screen.getByRole('button', { name: /voice activation threshold low/i })
    const high = screen.getByRole('button', { name: /voice activation threshold high/i })
    expect(low).toHaveAttribute('aria-pressed', 'false')
    expect(high).toHaveAttribute('aria-pressed', 'false')
  })

  it('updates the store to "high" when the High button is clicked', async () => {
    const user = userEvent.setup()
    render(<VoiceTab />)
    await user.click(screen.getByRole('button', { name: /voice activation threshold high/i }))
    expect(useVoiceSettingsStore.getState().voiceActivationThreshold).toBe('high')
  })
})

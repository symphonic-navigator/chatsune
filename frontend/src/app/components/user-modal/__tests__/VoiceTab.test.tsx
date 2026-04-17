import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { VoiceTab } from '../VoiceTab'
import { useVoiceSettingsStore } from '../../../../features/voice/stores/voiceSettingsStore'

describe('VoiceTab', () => {
  beforeEach(() => {
    useVoiceSettingsStore.setState({ autoSendTranscription: false })
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
})

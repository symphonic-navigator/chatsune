import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ConversationModeButton } from './ConversationModeButton'
import { useProvidersStore } from '../../../core/store/providersStore'

describe('ConversationModeButton', () => {
  beforeEach(() => {
    useProvidersStore.setState({ accounts: [], catalogue: [] })
  })

  it('renders disabled-looking button when TTS provider has no premium account', () => {
    useProvidersStore.setState({ accounts: [], catalogue: [] })
    render(
      <ConversationModeButton
        persona={{ id: 'p1', tts_provider_id: 'xai_voice' }}
      />,
    )
    const btn = screen.getByRole('button')
    expect(btn.style.textDecoration).toContain('line-through')
  })

  it('renders active button when TTS provider has premium account', () => {
    useProvidersStore.setState({
      accounts: [
        {
          provider_id: 'xai',
          config: {},
          last_test_status: 'ok',
          last_test_error: null,
          last_test_at: null,
        },
      ],
      catalogue: [],
    })
    render(
      <ConversationModeButton
        persona={{ id: 'p1', tts_provider_id: 'xai_voice' }}
      />,
    )
    const btn = screen.getByRole('button')
    expect(btn.style.textDecoration).not.toContain('line-through')
  })

  it('invokes onConfigure when the strikethrough button is clicked', () => {
    useProvidersStore.setState({ accounts: [], catalogue: [] })
    const onConfigure = vi.fn()
    render(
      <ConversationModeButton
        persona={{ id: 'p1', tts_provider_id: 'xai_voice' }}
        onConfigure={onConfigure}
      />,
    )
    screen.getByRole('button').click()
    expect(onConfigure).toHaveBeenCalledTimes(1)
  })

  it('falls back to the legacy unavailable rendering when no persona is supplied', () => {
    render(
      <ConversationModeButton
        active={false}
        available={false}
        phase="idle"
      />,
    )
    const btn = screen.getByRole('button')
    expect(btn).toBeDisabled()
    expect(btn.style.textDecoration).not.toContain('line-through')
  })

  it('blocks an STT premium integration when its account is missing', () => {
    useProvidersStore.setState({
      accounts: [
        {
          provider_id: 'xai',
          config: {},
          last_test_status: 'ok',
          last_test_error: null,
          last_test_at: null,
        },
      ],
      catalogue: [],
    })
    render(
      <ConversationModeButton
        persona={{
          id: 'p1',
          tts_provider_id: 'xai_voice',
          stt_provider_id: 'mistral_voice',
        }}
      />,
    )
    const btn = screen.getByRole('button')
    expect(btn.style.textDecoration).toContain('line-through')
  })
})

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
        persona={{ id: 'p1', voice_config: { tts_provider_id: 'xai_voice' } }}
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
        persona={{ id: 'p1', voice_config: { tts_provider_id: 'xai_voice' } }}
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
        persona={{ id: 'p1', voice_config: { tts_provider_id: 'xai_voice' } }}
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

  // Regression test for the staging bug where a persona bound to xai_voice
  // plus a fully configured xAI premium account still rendered the button
  // as strikethrough. Root cause was a field-path drift — the component
  // read `persona.tts_provider_id` at the top level instead of the real
  // location `persona.voice_config.tts_provider_id`. Keep this test as a
  // guard against the same drift re-appearing.
  it('is not strikethrough for persona with voice_config.tts_provider_id + configured xAI account', () => {
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
        persona={{ id: 'p1', voice_config: { tts_provider_id: 'xai_voice' } }}
      />,
    )
    const btn = screen.getByRole('button')
    expect(btn.style.textDecoration).not.toContain('line-through')
    // And the button must be the "start conversational mode" variant, not
    // the legacy disabled one.
    expect(btn).not.toBeDisabled()
    expect(btn.getAttribute('aria-label')).toBe('Start conversational mode')
  })
})

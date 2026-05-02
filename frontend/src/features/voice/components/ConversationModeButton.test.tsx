import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ConversationModeButton } from './ConversationModeButton'
import { useProvidersStore } from '../../../core/store/providersStore'
import { useIntegrationsStore } from '../../integrations/store'

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

  // Regression test for the test2-persona bug (2026-05-02): a persona that
  // has its voice configured but voice_config.tts_provider_id unset must not
  // render the strikethrough as long as the resolver's fallback (first enabled
  // TTS integration) maps to a configured Premium Provider Account. Mirrors
  // the cockpit Live-button gate.
  it('is not strikethrough when tts_provider_id is unset but the fallback TTS integration has a configured premium account', () => {
    useIntegrationsStore.setState({
      definitions: [
        {
          id: 'mistral_voice',
          capabilities: ['tts_provider'],
        } as never,
      ],
      configs: {
        mistral_voice: { effective_enabled: true } as never,
      },
    })
    useProvidersStore.setState({
      accounts: [
        {
          provider_id: 'mistral',
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
        persona={{ id: 'p1', voice_config: { tts_provider_id: null } }}
      />,
    )
    const btn = screen.getByRole('button')
    expect(btn.style.textDecoration).not.toContain('line-through')
    expect(btn).not.toBeDisabled()
    expect(btn.getAttribute('aria-label')).toBe('Start conversational mode')
  })

  describe('paused lifecycle', () => {
    it('renders amber Paused pill when active && lifecycle=paused', () => {
      render(
        <ConversationModeButton
          active={true}
          available={true}
          lifecycle="paused"
          onResume={() => {}}
          onToggle={() => {}}
        />,
      )
      const btn = screen.getByRole('button')
      expect(btn).toHaveTextContent(/paused/i)
      expect(btn).not.toHaveTextContent(/^Live$/i)
    })

    it('calls onResume (not onToggle) when clicked while paused', () => {
      const onResume = vi.fn()
      const onToggle = vi.fn()
      render(
        <ConversationModeButton
          active={true}
          available={true}
          lifecycle="paused"
          onResume={onResume}
          onToggle={onToggle}
        />,
      )
      screen.getByRole('button').click()
      expect(onResume).toHaveBeenCalledOnce()
      expect(onToggle).not.toHaveBeenCalled()
    })

    it('renders Live pill when active && lifecycle=active (existing path unchanged)', () => {
      render(
        <ConversationModeButton
          active={true}
          available={true}
          lifecycle="active"
          onResume={() => {}}
          onToggle={() => {}}
        />,
      )
      expect(screen.getByRole('button')).toHaveTextContent(/^Live$/i)
    })
  })
})

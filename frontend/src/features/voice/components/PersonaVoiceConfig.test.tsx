import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { PersonaVoiceConfig } from './PersonaVoiceConfig'
import { useIntegrationsStore } from '../../integrations/store'
import { CHAKRA_PALETTE } from '../../../core/types/chakra'

// Minimal persona that satisfies the props shape used by PersonaVoiceConfig.
function makePersona(overrides: Record<string, unknown> = {}) {
  return {
    id: 'p-test',
    name: 'test',
    voice_config: null,
    integration_configs: {
      mistral_voice: { voice_id: 'v-1' },
    },
    ...overrides,
  } as never
}

describe('PersonaVoiceConfig', () => {
  beforeEach(() => {
    useIntegrationsStore.setState({
      definitions: [
        {
          id: 'mistral_voice',
          display_name: 'Mistral',
          capabilities: ['tts_provider'],
          persona_config_fields: [],
        } as never,
      ],
      configs: {
        mistral_voice: { effective_enabled: true } as never,
      },
    })
  })

  it('persists the implicit default tts_provider_id when the user changes the narrator mode without ever touching the provider selector', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined)
    render(
      <PersonaVoiceConfig
        persona={makePersona()}
        chakra={CHAKRA_PALETTE.heart}
        onSave={onSave}
      />,
    )
    // The narrator-mode select is the simplest persistVoiceConfig trigger we
    // can drive without VoiceFormWithPreview side effects. It has no
    // aria-label in production, so we identify it by its option set
    // (off / play / narrate) which is unique within the rendered tree.
    const selects = screen.getAllByRole('combobox') as HTMLSelectElement[]
    const narratorSelect = selects.find(
      (s) =>
        s.querySelector('option[value="off"]') &&
        s.querySelector('option[value="play"]') &&
        s.querySelector('option[value="narrate"]'),
    )
    expect(narratorSelect).toBeDefined()
    fireEvent.change(narratorSelect!, { target: { value: 'play' } })

    await waitFor(() => expect(onSave).toHaveBeenCalled())
    const [, body] = onSave.mock.calls[0]
    expect(body.voice_config.tts_provider_id).toBe('mistral_voice')
  })
})

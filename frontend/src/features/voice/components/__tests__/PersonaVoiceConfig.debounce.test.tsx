import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PersonaVoiceConfig } from '../PersonaVoiceConfig'
import { useIntegrationsStore } from '../../../integrations/store'
import type { PersonaDto } from '../../../../core/types/persona'
import type { ChakraPaletteEntry } from '../../../../core/types/chakra'
import type { IntegrationDefinition, UserIntegrationConfig } from '../../../integrations/types'

// A minimal TTS definition so that `activeTTS` resolves and the modulation
// sliders render. `persona_config_fields` is empty so `GenericConfigForm`
// renders nothing interactive — we only care about the sliders + toggle.
const FAKE_TTS_ID = 'fake-tts'

const FAKE_TTS_DEF: IntegrationDefinition = {
  id: FAKE_TTS_ID,
  display_name: 'Fake TTS',
  description: '',
  icon: '',
  execution_mode: 'frontend',
  config_fields: [],
  has_tools: false,
  has_response_tags: false,
  has_prompt_extension: false,
  capabilities: ['tts_provider'],
  persona_config_fields: [],
}

const FAKE_TTS_CFG: UserIntegrationConfig = {
  integration_id: FAKE_TTS_ID,
  enabled: true,
  config: {},
}

const CHAKRA: ChakraPaletteEntry = {
  hex: '#4CB464',
  glow: 'rgba(76,180,100,0.3)',
  gradient: 'linear-gradient(180deg, rgba(76,180,100,0.08) 0%, transparent 60%)',
  sanskrit: 'anahata',
  label: 'Heart',
}

function makePersona(): PersonaDto {
  return {
    id: 'persona-1',
    user_id: 'u1',
    name: 'Test',
    tagline: '',
    model_unique_id: null,
    system_prompt: '',
    temperature: 0.8,
    reasoning_enabled: false,
    soft_cot_enabled: false,
    vision_fallback_model: null,
    nsfw: false,
    colour_scheme: 'heart',
    display_order: 0,
    monogram: 'T',
    pinned: false,
    profile_image: null,
    profile_crop: null,
    mcp_config: null,
    integrations_config: null,
    voice_config: {
      dialogue_voice: null,
      narrator_voice: null,
      auto_read: false,
      narrator_mode: 'off',
      dialogue_speed: 1.0,
      dialogue_pitch: 0,
      narrator_speed: 1.0,
      narrator_pitch: 0,
    },
    created_at: '',
    updated_at: '',
  }
}

describe('PersonaVoiceConfig — concurrent toggle during debounced slider save', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    useIntegrationsStore.setState({
      definitions: [FAKE_TTS_DEF],
      configs: { [FAKE_TTS_ID]: FAKE_TTS_CFG },
      healthStatus: {},
      loaded: true,
      loading: false,
    })
  })

  afterEach(() => {
    vi.useRealTimers()
    useIntegrationsStore.setState({
      definitions: [],
      configs: {},
      healthStatus: {},
      loaded: false,
      loading: false,
    })
  })

  it('does not revert a concurrent auto-read toggle when the debounced slider save fires', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined)
    const persona = makePersona()

    render(<PersonaVoiceConfig persona={persona} chakra={CHAKRA} onSave={onSave} />)

    // 1. Drag a slider — schedules a debounced persistVoiceConfig in 400 ms.
    const sliders = screen.getAllByRole('slider') as HTMLInputElement[]
    expect(sliders.length).toBeGreaterThan(0)
    fireEvent.change(sliders[0], { target: { value: '1.25' } })

    // 2. At t=100 ms, the user flips the auto-read toggle. This triggers an
    //    immediate write with { auto_read: true }.
    act(() => {
      vi.advanceTimersByTime(100)
    })
    // There is exactly one switch role on this panel (the auto-read toggle);
    // it has no accessible name because its label is a sibling span.
    const toggle = screen.getByRole('switch')
    fireEvent.click(toggle)

    // Flush the microtask queue so the onSave promise chains resolve.
    await act(async () => {
      await Promise.resolve()
    })

    // Sanity: at least one save has carried auto_read: true by now.
    const seenAutoReadTrue = onSave.mock.calls.some(
      ([, payload]) => (payload as { voice_config?: { auto_read?: boolean } }).voice_config?.auto_read === true,
    )
    expect(seenAutoReadTrue).toBe(true)

    // 3. Advance past the 400 ms debounce — the timer now fires, calling the
    //    (stabilised) persistVoiceConfig with the slider patch.
    await act(async () => {
      vi.advanceTimersByTime(400)
      await Promise.resolve()
    })

    // 4. Assert: the MOST RECENT save still has auto_read === true. The
    //    regression this test guards against is the debounced save reading a
    //    stale `autoRead = false` from its closure and silently reverting
    //    the toggle.
    expect(onSave).toHaveBeenCalled()
    const lastCall = onSave.mock.calls[onSave.mock.calls.length - 1]
    const lastPayload = lastCall[1] as { voice_config: { auto_read: boolean; dialogue_speed: number } }
    expect(lastPayload.voice_config.auto_read).toBe(true)
    expect(lastPayload.voice_config.dialogue_speed).toBeCloseTo(1.25, 5)
  })
})

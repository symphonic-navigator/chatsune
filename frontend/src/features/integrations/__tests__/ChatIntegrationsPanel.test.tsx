import { render, screen, fireEvent, act } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { IntegrationDefinition, UserIntegrationConfig } from '../types'

// Stub the plugins' side-effect imports so the test owns the registry.
vi.mock('../plugins/lovense', () => ({}))
vi.mock('../plugins/mistral_voice', () => ({}))

// Avoid React touching the real audioPlayback singleton during the test.
vi.mock('../../voice/infrastructure/useAudioPlaybackActive', () => ({
  useAudioPlaybackActive: () => false,
}))

const fakeGroupCancel = vi.fn()
const fakeGroup = { cancel: fakeGroupCancel, pause: vi.fn(), resume: vi.fn() }
vi.mock('../../chat/responseTaskGroup', () => ({
  getActiveGroup: () => fakeGroup,
}))

function makeDef(id: string, name: string): IntegrationDefinition {
  return {
    id,
    display_name: name,
    description: '',
    icon: '',
    execution_mode: 'frontend',
    config_fields: [],
    has_tools: false,
    has_response_tags: false,
    has_prompt_extension: false,
    capabilities: [],
    persona_config_fields: [],
  }
}

function makeConfig(id: string): UserIntegrationConfig {
  return { integration_id: id, enabled: true, config: {}, effective_enabled: true }
}

beforeEach(() => {
  fakeGroupCancel.mockClear()
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('ChatIntegrationsPanel', () => {
  it('clicking a chip calls only that plugin emergencyStop', async () => {
    // The shared setup hook calls vi.resetModules() per test, so every test
    // must lazy-import the store/registry/panel together — that way they all
    // see the same fresh module graph.
    const { useIntegrationsStore } = await import('../store')
    const { registerPlugin, _resetPluginRegistry } = await import('../registry')
    const { ChatIntegrationsPanel } = await import('../ChatIntegrationsPanel')

    _resetPluginRegistry()

    const lovenseStop = vi.fn().mockResolvedValue(undefined)
    const mistralStop = vi.fn().mockResolvedValue(undefined)
    registerPlugin({ id: 'lovense', emergencyStop: lovenseStop })
    registerPlugin({ id: 'mistral_voice', emergencyStop: mistralStop })

    useIntegrationsStore.setState({
      definitions: [makeDef('lovense', 'Lovense'), makeDef('mistral_voice', 'Mistral Voice')],
      configs: { lovense: makeConfig('lovense'), mistral_voice: makeConfig('mistral_voice') },
    })

    render(<ChatIntegrationsPanel />)

    const lovenseChip = screen.getByRole('button', { name: 'Emergency stop Lovense' })
    await act(async () => { fireEvent.click(lovenseChip) })

    expect(lovenseStop).toHaveBeenCalledTimes(1)
    expect(mistralStop).not.toHaveBeenCalled()
    // Clicking Lovense must not trigger TTS-cancel logic.
    expect(fakeGroupCancel).not.toHaveBeenCalled()
  })
})

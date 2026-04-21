import { describe, expect, it, vi, beforeEach } from 'vitest'
import { useIntegrationsStore } from '../store'
import { useSecretsStore } from '../secretsStore'
import { initPluginLifecycle, _resetPluginStates } from '../pluginLifecycle'
import { registerPlugin, _resetPluginRegistry } from '../registry'
import type { IntegrationDefinition, UserIntegrationConfig } from '../types'

beforeEach(() => {
  useSecretsStore.setState({ secrets: {} })
  useIntegrationsStore.setState({ definitions: [], configs: {}, healthStatus: {}, loaded: false, loading: false })
  _resetPluginRegistry()
  _resetPluginStates()
})

describe('pluginLifecycle', () => {
  it('activates plugin immediately when enabled and has no secret fields', () => {
    const onActivate = vi.fn()
    const onDeactivate = vi.fn()
    registerPlugin({ id: 'lovense', onActivate, onDeactivate })

    const definition: IntegrationDefinition = {
      id: 'lovense',
      display_name: 'Lovense',
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
    const config: UserIntegrationConfig = { integration_id: 'lovense', enabled: true, config: {}, effective_enabled: true }

    useIntegrationsStore.setState({ definitions: [definition], configs: { lovense: config } } as any)

    const cleanup = initPluginLifecycle()
    expect(onActivate).toHaveBeenCalledTimes(1)
    expect(onDeactivate).not.toHaveBeenCalled()

    cleanup()
  })

  it('does not activate plugin when disabled', () => {
    const onActivate = vi.fn()
    registerPlugin({ id: 'lovense', onActivate })

    const definition: IntegrationDefinition = {
      id: 'lovense',
      display_name: 'Lovense',
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
    const config: UserIntegrationConfig = { integration_id: 'lovense', enabled: false, config: {}, effective_enabled: false }

    useIntegrationsStore.setState({ definitions: [definition], configs: { lovense: config } } as any)

    const cleanup = initPluginLifecycle()
    expect(onActivate).not.toHaveBeenCalled()

    cleanup()
  })

  it('activates plugin only after secrets hydrate when integration has secret fields', () => {
    const onActivate = vi.fn()
    const onDeactivate = vi.fn()
    registerPlugin({ id: 'test_plugin', onActivate, onDeactivate })

    // secret field: cast via any since IntegrationConfigField doesn't expose secret yet
    const definition: IntegrationDefinition = {
      id: 'test_plugin',
      display_name: 'Test Plugin',
      description: '',
      icon: '',
      execution_mode: 'frontend',
      config_fields: [{ key: 'api_key', label: 'API Key', field_type: 'text', placeholder: '', required: true, description: '', secret: true } as any],
      has_tools: false,
      has_response_tags: false,
      has_prompt_extension: false,
      capabilities: [],
      persona_config_fields: [],
    }
    const config: UserIntegrationConfig = { integration_id: 'test_plugin', enabled: true, config: {}, effective_enabled: true }

    useIntegrationsStore.setState({ definitions: [definition], configs: { test_plugin: config } } as any)

    const cleanup = initPluginLifecycle()
    expect(onActivate).not.toHaveBeenCalled()  // no secrets yet → stays inactive

    useSecretsStore.getState().setSecrets('test_plugin', { api_key: 'x' })
    expect(onActivate).toHaveBeenCalledTimes(1)

    useSecretsStore.getState().clearSecrets('test_plugin')
    expect(onDeactivate).toHaveBeenCalledTimes(1)

    cleanup()
  })

  it('activates plugin for synthetic linked-premium config (enabled=false, effective_enabled=true)', () => {
    // Regression test for the xai_voice / mistral_voice Voice-Tab invisibility
    // bug: the backend emits a synthetic UserIntegrationConfigDto with
    // `enabled=false, effective_enabled=true` for integrations bound to a
    // Premium Provider Account. The plugin lifecycle must gate activation on
    // `effective_enabled` — otherwise STT/TTS engines never register, the
    // voice-tab disappears, and the Voice list stays empty.
    const onActivate = vi.fn()
    const onDeactivate = vi.fn()
    registerPlugin({ id: 'xai_voice', onActivate, onDeactivate })

    const definition: IntegrationDefinition = {
      id: 'xai_voice',
      display_name: 'xAI Voice',
      description: '',
      icon: '',
      execution_mode: 'backend',
      config_fields: [],
      has_tools: false,
      has_response_tags: false,
      has_prompt_extension: false,
      capabilities: ['tts_provider', 'stt_provider'],
      persona_config_fields: [],
      hydrate_secrets: false,
      linked_premium_provider: 'xai',
    }
    const syntheticConfig: UserIntegrationConfig = {
      integration_id: 'xai_voice',
      enabled: false,
      config: {},
      effective_enabled: true,
    }

    useIntegrationsStore.setState({ definitions: [definition], configs: { xai_voice: syntheticConfig } } as any)

    const cleanup = initPluginLifecycle()
    expect(onActivate).toHaveBeenCalledTimes(1)
    expect(onDeactivate).not.toHaveBeenCalled()

    cleanup()
  })

  it('deactivates plugin when config is disabled after being active', () => {
    const onActivate = vi.fn()
    const onDeactivate = vi.fn()
    registerPlugin({ id: 'lovense', onActivate, onDeactivate })

    const definition: IntegrationDefinition = {
      id: 'lovense',
      display_name: 'Lovense',
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
    const enabledConfig: UserIntegrationConfig = { integration_id: 'lovense', enabled: true, config: {}, effective_enabled: true }
    const disabledConfig: UserIntegrationConfig = { integration_id: 'lovense', enabled: false, config: {}, effective_enabled: false }

    useIntegrationsStore.setState({ definitions: [definition], configs: { lovense: enabledConfig } } as any)

    const cleanup = initPluginLifecycle()
    expect(onActivate).toHaveBeenCalledTimes(1)

    useIntegrationsStore.setState({ configs: { lovense: disabledConfig } } as any)
    expect(onDeactivate).toHaveBeenCalledTimes(1)

    cleanup()
  })
})

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
    }
    const config: UserIntegrationConfig = { integration_id: 'lovense', enabled: true, config: {} }

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
    }
    const config: UserIntegrationConfig = { integration_id: 'lovense', enabled: false, config: {} }

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
    }
    const config: UserIntegrationConfig = { integration_id: 'test_plugin', enabled: true, config: {} }

    useIntegrationsStore.setState({ definitions: [definition], configs: { test_plugin: config } } as any)

    const cleanup = initPluginLifecycle()
    expect(onActivate).not.toHaveBeenCalled()  // no secrets yet → stays inactive

    useSecretsStore.getState().setSecrets('test_plugin', { api_key: 'x' })
    expect(onActivate).toHaveBeenCalledTimes(1)

    useSecretsStore.getState().clearSecrets('test_plugin')
    expect(onDeactivate).toHaveBeenCalledTimes(1)

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
    }
    const enabledConfig: UserIntegrationConfig = { integration_id: 'lovense', enabled: true, config: {} }
    const disabledConfig: UserIntegrationConfig = { integration_id: 'lovense', enabled: false, config: {} }

    useIntegrationsStore.setState({ definitions: [definition], configs: { lovense: enabledConfig } } as any)

    const cleanup = initPluginLifecycle()
    expect(onActivate).toHaveBeenCalledTimes(1)

    useIntegrationsStore.setState({ configs: { lovense: disabledConfig } } as any)
    expect(onDeactivate).toHaveBeenCalledTimes(1)

    cleanup()
  })
})

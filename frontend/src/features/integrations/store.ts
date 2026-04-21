import { create } from 'zustand'
import type { IntegrationDefinition, UserIntegrationConfig, HealthStatus } from './types'
import { integrationsApi } from './api'

interface IntegrationsState {
  definitions: IntegrationDefinition[]
  /** Plain object keyed by integration_id — avoids Map reactivity issues with Zustand. */
  configs: Record<string, UserIntegrationConfig>
  healthStatus: Record<string, HealthStatus>
  loaded: boolean
  loading: boolean

  load: () => Promise<void>
  upsertConfig: (integrationId: string, enabled: boolean, config: Record<string, unknown>) => Promise<void>
  setHealth: (integrationId: string, status: HealthStatus) => void
  getConfig: (integrationId: string) => UserIntegrationConfig | undefined
  getEnabledIds: () => string[]
}

export const useIntegrationsStore = create<IntegrationsState>((set, get) => ({
  definitions: [],
  configs: {},
  healthStatus: {},
  loaded: false,
  loading: false,

  load: async () => {
    if (get().loading) return
    set({ loading: true })
    try {
      const [definitions, rawConfigs] = await Promise.all([
        integrationsApi.listDefinitions(),
        integrationsApi.listConfigs(),
      ])
      const configs: Record<string, UserIntegrationConfig> = {}
      for (const c of rawConfigs) {
        configs[c.integration_id] = c
      }
      set({ definitions, configs, loaded: true })
    } catch (err) {
      console.error('[integrations] Failed to load:', err)
    } finally {
      set({ loading: false })
    }
  },

  upsertConfig: async (integrationId, enabled, config) => {
    const result = await integrationsApi.upsertConfig(integrationId, enabled, config)
    set((s) => ({
      configs: { ...s.configs, [integrationId]: result },
    }))
  },

  setHealth: (integrationId, status) =>
    set((s) => ({
      healthStatus: { ...s.healthStatus, [integrationId]: status },
    })),

  getConfig: (integrationId) => get().configs[integrationId],

  getEnabledIds: () => {
    const configs = get().configs
    return Object.keys(configs).filter((id) => configs[id].effective_enabled)
  },
}))

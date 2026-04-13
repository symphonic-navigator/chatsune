import { create } from 'zustand'
import type { IntegrationDefinition, UserIntegrationConfig, HealthStatus } from './types'
import { integrationsApi } from './api'

interface IntegrationsState {
  definitions: IntegrationDefinition[]
  configs: Map<string, UserIntegrationConfig>
  healthStatus: Map<string, HealthStatus>
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
  configs: new Map(),
  healthStatus: new Map(),
  loaded: false,
  loading: false,

  load: async () => {
    if (get().loading) return
    set({ loading: true })
    try {
      const [definitions, configs] = await Promise.all([
        integrationsApi.listDefinitions(),
        integrationsApi.listConfigs(),
      ])
      const configMap = new Map<string, UserIntegrationConfig>()
      for (const c of configs) {
        configMap.set(c.integration_id, c)
      }
      set({ definitions, configs: configMap, loaded: true })
    } finally {
      set({ loading: false })
    }
  },

  upsertConfig: async (integrationId, enabled, config) => {
    const result = await integrationsApi.upsertConfig(integrationId, enabled, config)
    set((s) => {
      const next = new Map(s.configs)
      next.set(integrationId, result)
      return { configs: next }
    })
  },

  setHealth: (integrationId, status) =>
    set((s) => {
      const next = new Map(s.healthStatus)
      next.set(integrationId, status)
      return { healthStatus: next }
    }),

  getConfig: (integrationId) => get().configs.get(integrationId),

  getEnabledIds: () => {
    const ids: string[] = []
    for (const [id, c] of get().configs) {
      if (c.enabled) ids.push(id)
    }
    return ids
  },
}))

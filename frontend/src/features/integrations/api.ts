import { api } from '../../core/api/client'
import type { IntegrationDefinition, UserIntegrationConfig } from './types'

export const integrationsApi = {
  listDefinitions: () =>
    api.get<IntegrationDefinition[]>('/api/integrations/definitions'),

  listConfigs: () =>
    api.get<UserIntegrationConfig[]>('/api/integrations/configs'),

  upsertConfig: (integrationId: string, enabled: boolean, config: Record<string, unknown>) =>
    api.put<UserIntegrationConfig>(`/api/integrations/configs/${integrationId}`, {
      enabled,
      config,
    }),
}

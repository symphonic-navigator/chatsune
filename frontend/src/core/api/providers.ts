import { api } from './client'
import type {
  PremiumProviderDefinition,
  PremiumProviderAccount,
} from '../types/providers'
import type { ModelMetaDto } from '../types/llm'

export const providersApi = {
  catalogue: () =>
    api.get<PremiumProviderDefinition[]>('/api/providers/catalogue'),

  listAccounts: () =>
    api.get<PremiumProviderAccount[]>('/api/providers/accounts'),

  upsertAccount: (providerId: string, config: Record<string, unknown>) =>
    api.put<PremiumProviderAccount>(
      `/api/providers/accounts/${providerId}`,
      { config },
    ),

  deleteAccount: (providerId: string) =>
    api.delete<void>(`/api/providers/accounts/${providerId}`),

  /**
   * Cached-or-fresh premium-provider model listing (user-scoped).
   * 404 when the provider is unknown or the user has no account.
   */
  listProviderModels: (providerId: string) =>
    api.get<ModelMetaDto[]>(
      `/api/providers/accounts/${providerId}/models`,
    ),

  /**
   * Drop the user's premium model cache, re-fetch, and publish the
   * ``providers.models_refreshed`` event. 502 on upstream adapter error.
   */
  refreshProviderModels: (providerId: string) =>
    api.post<void>(`/api/providers/accounts/${providerId}/refresh`),
}

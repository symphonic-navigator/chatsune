import { api } from './client'
import type {
  PremiumProviderDefinition,
  PremiumProviderAccount,
} from '../types/providers'

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
}

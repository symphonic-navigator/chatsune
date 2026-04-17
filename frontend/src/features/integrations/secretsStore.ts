import { create } from 'zustand'

interface SecretsState {
  // { [integrationId]: { [fieldKey]: value } }
  secrets: Record<string, Record<string, string>>

  setSecrets(integrationId: string, secrets: Record<string, string>): void
  clearSecrets(integrationId: string): void
  getSecret(integrationId: string, fieldKey: string): string | undefined
  hasSecrets(integrationId: string): boolean
}

export const useSecretsStore = create<SecretsState>((set, get) => ({
  secrets: {},

  setSecrets: (integrationId, secrets) =>
    set((state) => ({
      secrets: { ...state.secrets, [integrationId]: secrets },
    })),

  clearSecrets: (integrationId) =>
    set((state) => {
      const next = { ...state.secrets }
      delete next[integrationId]
      return { secrets: next }
    }),

  getSecret: (integrationId, fieldKey) =>
    get().secrets[integrationId]?.[fieldKey],

  hasSecrets: (integrationId) =>
    !!get().secrets[integrationId] &&
    Object.keys(get().secrets[integrationId]).length > 0,
}))

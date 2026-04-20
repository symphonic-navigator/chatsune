import { create } from 'zustand'
import { providersApi } from '../api/providers'
import type {
  PremiumProviderDefinition,
  PremiumProviderAccount,
  Capability,
} from '../types/providers'

interface ProvidersState {
  catalogue: PremiumProviderDefinition[]
  accounts: PremiumProviderAccount[]
  loading: boolean
  error: string | null
  /** True once refresh() has completed successfully at least once. Callers
   *  use this to decide whether a `[]` in `accounts` means "not loaded yet"
   *  or "genuinely empty", which matters for lazy-hydrating consumers
   *  outside the User-Modal (e.g. the ConversationModeButton). */
  hydrated: boolean
  /** Provider ids currently being tested. UI uses this to disable the Test
   *  button and swap its label. A new Set reference is written on every
   *  mutation so shallow-equality subscribers re-render. */
  testingIds: Set<string>

  refresh: () => Promise<void>
  save: (providerId: string, config: Record<string, unknown>) => Promise<void>
  remove: (providerId: string) => Promise<void>
  test: (providerId: string) => Promise<void>

  configuredIds: () => Set<string>
  coveredCapabilities: () => Set<Capability>
}

function upsert(
  list: PremiumProviderAccount[],
  acct: PremiumProviderAccount,
): PremiumProviderAccount[] {
  const i = list.findIndex((a) => a.provider_id === acct.provider_id)
  if (i < 0) return [...list, acct]
  const next = list.slice()
  next[i] = acct
  return next
}

export const useProvidersStore = create<ProvidersState>((set, get) => ({
  catalogue: [],
  accounts: [],
  loading: false,
  error: null,
  hydrated: false,
  testingIds: new Set<string>(),

  refresh: async () => {
    set({ loading: true, error: null })
    try {
      const [catalogue, accounts] = await Promise.all([
        providersApi.catalogue(),
        providersApi.listAccounts(),
      ])
      set({ catalogue, accounts, loading: false, hydrated: true })
    } catch (e) {
      set({
        loading: false,
        error: e instanceof Error ? e.message : 'Load failed',
      })
    }
  },

  save: async (providerId, config) => {
    const acct = await providersApi.upsertAccount(providerId, config)
    set({ accounts: upsert(get().accounts, acct) })
  },

  remove: async (providerId) => {
    await providersApi.deleteAccount(providerId)
    set({
      accounts: get().accounts.filter((a) => a.provider_id !== providerId),
    })
  },

  test: async (providerId) => {
    // Synchronous opt-in — UI must see the inflight flag before the await.
    set({ testingIds: new Set(get().testingIds).add(providerId) })
    try {
      await providersApi.testAccount(providerId)
      // Pull the canonical last_test_* fields from the server — the test
      // response only carries {status, error}, not last_test_at.
      await get().refresh()
    } finally {
      const next = new Set(get().testingIds)
      next.delete(providerId)
      set({ testingIds: next })
    }
  },

  configuredIds: () => new Set(get().accounts.map((a) => a.provider_id)),

  coveredCapabilities: () => {
    const configured = get().configuredIds()
    const covered = new Set<Capability>()
    for (const d of get().catalogue) {
      if (configured.has(d.id)) {
        d.capabilities.forEach((c) => covered.add(c))
      }
    }
    return covered
  },
}))

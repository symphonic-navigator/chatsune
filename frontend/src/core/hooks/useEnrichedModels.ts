import { useCallback, useEffect, useMemo, useState } from 'react'
import { llmApi } from '../api/llm'
import { providersApi } from '../api/providers'
import type {
  Connection,
  EnrichedModelDto,
  ModelMetaDto,
  UserModelConfigDto,
} from '../types/llm'
import type {
  PremiumProviderAccount,
  PremiumProviderDefinition,
} from '../types/providers'
import { eventBus } from '../websocket/eventBus'
import { Topics } from '../types/events'

export interface ConnectionModelGroup {
  connection: Connection
  models: EnrichedModelDto[]
}

export interface UseEnrichedModels {
  groups: ConnectionModelGroup[]
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  findByUniqueId: (uid: string) => EnrichedModelDto | null
}

/**
 * Synthesise a :type:`Connection`-shaped object for a configured Premium
 * Provider. These are *not* real Connection documents — they stand in so
 * the model picker can render them as a group alongside user connections.
 *
 * The ``id`` follows the backend's ``premium:{slug}`` naming; downstream
 * code relying on ``connection.id`` should never call Connection-endpoints
 * with this id. Callers that need to distinguish can check
 * ``is_system_managed`` (true) or the ``premium:`` prefix on ``id``.
 */
function toPseudoConnection(
  defn: PremiumProviderDefinition,
  account: PremiumProviderAccount,
): Connection {
  const now = new Date(0).toISOString()
  return {
    id: `premium:${defn.id}`,
    user_id: '',
    adapter_type: 'premium',
    display_name: defn.display_name,
    slug: defn.id,
    config: {},
    last_test_status: account.last_test_status === 'ok'
      ? 'valid'
      : account.last_test_status === 'error'
        ? 'failed'
        : 'untested',
    last_test_error: account.last_test_error,
    last_test_at: account.last_test_at,
    created_at: now,
    updated_at: now,
    is_system_managed: true,
  }
}

/**
 * Loads all user connections, each connection's models, and the user's
 * per-model configuration. Merges them into grouped, sorted output and
 * keeps itself live via the LLM + user-model-config topics.
 *
 * Premium providers are dispatched through ``/api/providers/accounts/{id}/models``
 * (user-scoped, cached server-side); user connections flow through
 * ``/api/llm/connections/{id}/models`` as before. Groups are sorted by
 * creation time; premium groups sit ahead of user connections because
 * their synthetic ``created_at`` is the epoch.
 */
export function useEnrichedModels(): UseEnrichedModels {
  const [groups, setGroups] = useState<ConnectionModelGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setError(null)
    try {
      // Load Connections, Premium accounts+catalogue, and user-model configs
      // in parallel. Premium accounts may be empty — that's fine, the
      // resulting loop just skips them.
      const [connections, userConfigs, catalogue, accounts] = await Promise.all([
        llmApi.listConnections(),
        llmApi.listUserModelConfigs(),
        providersApi.catalogue().catch(() => [] as PremiumProviderDefinition[]),
        providersApi.listAccounts().catch(() => [] as PremiumProviderAccount[]),
      ])

      const configByUid = new Map<string, UserModelConfigDto>()
      for (const cfg of userConfigs) {
        configByUid.set(cfg.model_unique_id, cfg)
      }

      const sortedConns = [...connections].sort(
        (a, b) => a.created_at.localeCompare(b.created_at),
      )

      // Build the premium pseudo-connections: one entry per configured
      // account whose provider exists in the catalogue.
      const cataloguebyId = new Map(catalogue.map((d) => [d.id, d]))
      const premiumConns: Connection[] = []
      for (const acct of accounts) {
        const defn = cataloguebyId.get(acct.provider_id)
        if (!defn) continue
        premiumConns.push(toPseudoConnection(defn, acct))
      }

      // Fetch models for every group. Premium providers use the providers
      // API; user connections use the llm API. Catch-per-request so a
      // single broken provider never blanks the whole hub.
      const [premiumModels, userModels] = await Promise.all([
        Promise.all(
          premiumConns.map((c) =>
            providersApi.listProviderModels(c.slug).catch((err) => {
              console.warn('listProviderModels failed', c.slug, err)
              return [] as ModelMetaDto[]
            }),
          ),
        ),
        Promise.all(
          sortedConns.map((c) =>
            llmApi.listConnectionModels(c.id).catch((err) => {
              console.warn('listConnectionModels failed', c.id, err)
              return [] as ModelMetaDto[]
            }),
          ),
        ),
      ])

      const premiumGroups: ConnectionModelGroup[] = premiumConns.map(
        (connection, idx) => ({
          connection,
          models: premiumModels[idx]
            .map<EnrichedModelDto>((m) => {
              const cfg = configByUid.get(m.unique_id) ?? null
              const supports_reasoning =
                cfg?.custom_supports_reasoning ?? m.supports_reasoning
              return { ...m, supports_reasoning, user_config: cfg }
            })
            .sort((a, b) => a.display_name.localeCompare(b.display_name)),
        }),
      )

      const userGroups: ConnectionModelGroup[] = sortedConns.map(
        (connection, idx) => ({
          connection,
          models: userModels[idx]
            .map<EnrichedModelDto>((m) => {
              const cfg = configByUid.get(m.unique_id) ?? null
              // Apply the per-user reasoning override so every consumer of
              // ``supports_reasoning`` (filters, persona editor, badges) sees
              // the effective value without a separate lookup.
              const supports_reasoning =
                cfg?.custom_supports_reasoning ?? m.supports_reasoning
              return { ...m, supports_reasoning, user_config: cfg }
            })
            .sort((a, b) => a.display_name.localeCompare(b.display_name)),
        }),
      )

      setGroups([...premiumGroups, ...userGroups])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load models.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    const topics = [
      Topics.LLM_CONNECTION_CREATED,
      Topics.LLM_CONNECTION_UPDATED,
      Topics.LLM_CONNECTION_REMOVED,
      Topics.LLM_CONNECTION_MODELS_REFRESHED,
      Topics.LLM_USER_MODEL_CONFIG_UPDATED,
      Topics.PREMIUM_PROVIDER_ACCOUNT_UPSERTED,
      Topics.PREMIUM_PROVIDER_ACCOUNT_DELETED,
      Topics.PREMIUM_PROVIDER_MODELS_REFRESHED,
    ] as const
    const unsubs = topics.map((t) => eventBus.on(t, () => { void refresh() }))
    return () => unsubs.forEach((u) => u())
  }, [refresh])

  const findByUniqueId = useCallback(
    (uid: string): EnrichedModelDto | null => {
      for (const group of groups) {
        const match = group.models.find((m) => m.unique_id === uid)
        if (match) return match
      }
      return null
    },
    [groups],
  )

  return useMemo(
    () => ({ groups, loading, error, refresh, findByUniqueId }),
    [groups, loading, error, refresh, findByUniqueId],
  )
}

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
  status: 'loading' | 'ready' | 'error'
  error?: string
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
  const generationRef = useRef(0)

  const refresh = useCallback(async () => {
    setError(null)
    setLoading(true)
    const myGeneration = ++generationRef.current
    const isLive = () => generationRef.current === myGeneration
    try {
      // Phase A: list providers
      const [connections, userConfigs, catalogue, accounts] = await Promise.all([
        llmApi.listConnections(),
        llmApi.listUserModelConfigs(),
        providersApi.catalogue().catch(() => [] as PremiumProviderDefinition[]),
        providersApi.listAccounts().catch(() => [] as PremiumProviderAccount[]),
      ])

      // A superseded refresh may have started while this one was awaiting Phase A.
      if (!isLive()) return

      const configByUid = new Map<string, UserModelConfigDto>()
      for (const cfg of userConfigs) configByUid.set(cfg.model_unique_id, cfg)

      const sortedConns = [...connections].sort(
        (a, b) => a.created_at.localeCompare(b.created_at),
      )

      const catalogueById = new Map(catalogue.map((d) => [d.id, d]))
      const premiumConns: Connection[] = []
      for (const acct of accounts) {
        const defn = catalogueById.get(acct.provider_id)
        if (!defn) continue
        premiumConns.push(toPseudoConnection(defn, acct))
      }

      // Commit the skeleton immediately so the UI can render group headers
      // with loading indicators before any per-group model fetch completes.
      const skeleton: ConnectionModelGroup[] = [
        ...premiumConns.map<ConnectionModelGroup>((c) => ({
          connection: c, status: 'loading', models: [],
        })),
        ...sortedConns.map<ConnectionModelGroup>((c) => ({
          connection: c, status: 'loading', models: [],
        })),
      ]
      setGroups(skeleton)

      // loading stays true until every group reaches a terminal status.
      const total = premiumConns.length + sortedConns.length
      if (total === 0) {
        if (isLive()) setLoading(false)
        return
      }
      let settled = 0
      const markSettled = () => {
        settled += 1
        if (settled >= total && isLive()) setLoading(false)
      }

      // Phase B: per-group fetches — each .then writes only its own group.
      const enrichModels = (models: ModelMetaDto[]): EnrichedModelDto[] =>
        models
          .map<EnrichedModelDto>((m) => {
            const cfg = configByUid.get(m.unique_id) ?? null
            // Apply the per-user reasoning override so every consumer of
            // ``supports_reasoning`` (filters, persona editor, badges) sees
            // the effective value without a separate lookup.
            const supports_reasoning =
              cfg?.custom_supports_reasoning ?? m.supports_reasoning
            return { ...m, supports_reasoning, user_config: cfg }
          })
          .sort((a, b) => a.display_name.localeCompare(b.display_name))

      const fetchOne = (c: Connection): Promise<ModelMetaDto[]> =>
        c.id.startsWith('premium:')
          ? providersApi.listProviderModels(c.slug)
          : llmApi.listConnectionModels(c.id)

      for (const c of [...premiumConns, ...sortedConns]) {
        void fetchOne(c)
          .then((models) => {
            if (!isLive()) return
            setGroups((prev) =>
              prev.map((g) =>
                g.connection.id === c.id
                  ? { ...g, status: 'ready', models: enrichModels(models), error: undefined }
                  : g,
              ),
            )
            markSettled()
          })
          .catch((err) => {
            if (!isLive()) return
            const message = err instanceof Error ? err.message : 'Could not load models.'
            setGroups((prev) =>
              prev.map((g) =>
                g.connection.id === c.id
                  ? { ...g, status: 'error', error: message }
                  : g,
              ),
            )
            markSettled()
          })
      }
    } catch (err) {
      if (!isLive()) return
      setError(err instanceof Error ? err.message : 'Could not load models.')
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

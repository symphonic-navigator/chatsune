import { useCallback, useEffect, useMemo, useState } from 'react'
import { llmApi } from '../api/llm'
import type {
  Connection,
  EnrichedModelDto,
  ModelMetaDto,
  UserModelConfigDto,
} from '../types/llm'
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
 * Loads all user connections, each connection's models, and the user's
 * per-model configuration. Merges them into grouped, sorted output and
 * keeps itself live via the LLM + user-model-config topics.
 *
 * Groups are sorted by connection.created_at (stable); models within a
 * group are sorted by display_name.
 */
export function useEnrichedModels(): UseEnrichedModels {
  const [groups, setGroups] = useState<ConnectionModelGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setError(null)
    try {
      const [connections, userConfigs] = await Promise.all([
        llmApi.listConnections(),
        llmApi.listUserModelConfigs(),
      ])

      const configByUid = new Map<string, UserModelConfigDto>()
      for (const cfg of userConfigs) {
        configByUid.set(cfg.model_unique_id, cfg)
      }

      const sortedConns = [...connections].sort(
        (a, b) => a.created_at.localeCompare(b.created_at),
      )

      const modelsByConnection = await Promise.all(
        sortedConns.map((c) =>
          llmApi.listConnectionModels(c.id).catch((err) => {
            // Tolerate per-connection failures — surface an empty group
            // and log for observability. A single broken connection
            // should not blank the entire hub.
            console.warn('listConnectionModels failed', c.id, err)
            return [] as ModelMetaDto[]
          }),
        ),
      )

      const nextGroups: ConnectionModelGroup[] = sortedConns.map((connection, idx) => {
        const models = modelsByConnection[idx]
          .map<EnrichedModelDto>((m) => ({
            ...m,
            user_config: configByUid.get(m.unique_id) ?? null,
          }))
          .sort((a, b) => a.display_name.localeCompare(b.display_name))
        return { connection, models }
      })

      setGroups(nextGroups)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Konnte Modelle nicht laden.')
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

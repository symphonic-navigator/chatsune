import { useCallback, useEffect, useState } from "react"
import { llmApi } from "../api/llm"
import type {
  EnrichedModelDto,
  UserModelConfigDto,
} from "../types/llm"

/**
 * Fetches models from all configured providers, merges with user configs,
 * and returns an enriched list. Filters out admin-hidden models.
 */
export function useEnrichedModels() {
  const [models, setModels] = useState<EnrichedModelDto[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetch = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const [providers, userConfigs] = await Promise.all([
        llmApi.listProviders(),
        llmApi.listUserConfigs(),
      ])

      const configured = providers.filter((p) => p.is_configured)
      const modelLists = await Promise.all(
        configured.map((p) => llmApi.listModels(p.provider_id)),
      )

      const configMap = new Map<string, UserModelConfigDto>()
      for (const c of userConfigs) configMap.set(c.model_unique_id, c)

      const enriched: EnrichedModelDto[] = modelLists
        .flat()
        .filter((m) => !m.curation?.hidden)
        .map((m) => ({
          ...m,
          user_config: configMap.get(m.unique_id) ?? null,
        }))

      setModels(enriched)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load models")
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetch()
  }, [fetch])

  /** Update a single model in the local list. */
  const updateModel = useCallback((uniqueId: string, updater: (m: EnrichedModelDto) => EnrichedModelDto) => {
    setModels((prev) => prev.map((m) => (m.unique_id === uniqueId ? updater(m) : m)))
  }, [])

  return { models, setModels, isLoading, error, refetch: fetch, updateModel }
}

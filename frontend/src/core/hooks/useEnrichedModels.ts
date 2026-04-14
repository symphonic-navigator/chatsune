// TODO Phase 9: rewrite against the new connections/models pipeline.
// For now returns an empty model list — all consumers are stubbed.
import { useCallback } from "react"
import type { EnrichedModelDto } from "../types/llm"

export function useEnrichedModels() {
  const refetch = useCallback(async () => {
    // Intentional no-op until Phase 9.
  }, [])

  const setModels = useCallback((_updater: EnrichedModelDto[] | ((prev: EnrichedModelDto[]) => EnrichedModelDto[])) => {
    // Intentional no-op until Phase 9.
  }, [])

  const updateModel = useCallback(
    (_uniqueId: string, _updater: (m: EnrichedModelDto) => EnrichedModelDto) => {
      // Intentional no-op until Phase 9.
    },
    [],
  )

  return {
    models: [] as EnrichedModelDto[],
    setModels,
    isLoading: false,
    error: null as string | null,
    refetch,
    updateModel,
  }
}

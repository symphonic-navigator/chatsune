import { useState, useEffect, useCallback } from "react"
import type { ModelMetaDto } from "../../../core/types/llm"
import { llmApi } from "../../../core/api/llm"
import { eventBus } from "../../../core/websocket/eventBus"
import { Topics } from "../../../core/types/events"
import { ModelList } from "./ModelList"
import { CurationModal } from "./CurationModal"

export function ModelsTab() {
  const [models, setModels] = useState<ModelMetaDto[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedModel, setSelectedModel] = useState<ModelMetaDto | null>(null)

  const fetchModels = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const providers = await llmApi.listProviders()
      const listable = providers.filter((p) => p.is_configured || !p.requires_key_for_listing)

      const results = await Promise.allSettled(
        listable.map((p) => llmApi.listModels(p.provider_id)),
      )

      const allModels: ModelMetaDto[] = []
      for (const result of results) {
        if (result.status === "fulfilled") {
          allModels.push(...result.value)
        }
      }

      setModels(allModels)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch models")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchModels()
  }, [fetchModels])

  // Subscribe to live LLM events for automatic updates
  useEffect(() => {
    const unsubCurated = eventBus.on(Topics.LLM_MODEL_CURATED, () => {
      fetchModels()
    })

    const unsubRefreshed = eventBus.on(Topics.LLM_MODELS_REFRESHED, () => {
      fetchModels()
    })

    const unsubFetchCompleted = eventBus.on(Topics.LLM_MODELS_FETCH_COMPLETED, () => {
      fetchModels()
    })

    return () => {
      unsubCurated()
      unsubRefreshed()
      unsubFetchCompleted()
    }
  }, [fetchModels])

  function handleCurationSaved(updatedModel: ModelMetaDto) {
    setModels((prev) =>
      prev.map((m) => (m.unique_id === updatedModel.unique_id ? updatedModel : m)),
    )
    setSelectedModel(null)
  }

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <div className="flex items-center gap-3">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-gold/30 border-t-gold" />
          <span className="text-[12px] text-white/60">Loading models...</span>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3">
        <span className="text-[12px] text-red-400">{error}</span>
        <button
          type="button"
          onClick={fetchModels}
          className="rounded-lg border border-white/8 px-3 py-1.5 text-[11px] text-white/60 hover:bg-white/6 hover:text-white/80 transition-colors cursor-pointer"
        >
          Retry
        </button>
      </div>
    )
  }

  if (models.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 text-[12px] text-white/60">
        <span>No models available</span>
        <button
          type="button"
          onClick={fetchModels}
          className="rounded-lg border border-gold/30 bg-gold/10 px-3 py-1.5 text-[11px] font-medium text-gold transition-colors hover:bg-gold/20 cursor-pointer"
        >
          Refresh providers
        </button>
      </div>
    )
  }

  return (
    <>
      <ModelList models={models} onSelectModel={setSelectedModel} />
      {selectedModel && (
        <CurationModal
          model={selectedModel}
          onCurationSaved={handleCurationSaved}
          onClose={() => setSelectedModel(null)}
        />
      )}
    </>
  )
}

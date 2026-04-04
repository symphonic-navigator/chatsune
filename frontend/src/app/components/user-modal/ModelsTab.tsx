import { useCallback, useState } from 'react'
import { llmApi } from '../../../core/api/llm'
import type { EnrichedModelDto } from '../../../core/types/llm'
import { useEnrichedModels } from '../../../core/hooks/useEnrichedModels'
import { ModelBrowser } from '../model-browser/ModelBrowser'
import { ModelConfigModal } from '../model-browser/ModelConfigModal'
import { slugWithoutProvider } from '../model-browser/modelFilters'

export function ModelsTab() {
  const { models, setModels, isLoading, error, refetch } = useEnrichedModels()
  const [configTarget, setConfigTarget] = useState<EnrichedModelDto | null>(null)

  /** Optimistically toggle a model's favourite status. */
  const handleToggleFavourite = useCallback((model: EnrichedModelDto) => {
    const newFav = !model.user_config?.is_favourite
    const providerId = model.provider_id
    const modelSlug = slugWithoutProvider(model.unique_id)

    // Optimistic update
    setModels((prev) =>
      prev.map((m) =>
        m.unique_id === model.unique_id
          ? {
              ...m,
              user_config: {
                model_unique_id: m.unique_id,
                is_favourite: newFav,
                is_hidden: m.user_config?.is_hidden ?? false,
                notes: m.user_config?.notes ?? null,
                system_prompt_addition: m.user_config?.system_prompt_addition ?? null,
              },
            }
          : m,
      ),
    )

    llmApi.setUserConfig(providerId, modelSlug, { is_favourite: newFav }).catch(() => {
      setModels((prev) =>
        prev.map((m) =>
          m.unique_id === model.unique_id
            ? { ...m, user_config: model.user_config }
            : m,
        ),
      )
    })
  }, [setModels])

  const handleConfigSaved = useCallback((updatedModel: EnrichedModelDto) => {
    setModels((prev) =>
      prev.map((m) => (m.unique_id === updatedModel.unique_id ? updatedModel : m)),
    )
    setConfigTarget(null)
  }, [setModels])

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <div className="h-5 w-5 rounded-full border-2 border-white/15 border-t-gold animate-spin" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3">
        <p className="text-[13px] text-white/40">{error}</p>
        <button
          type="button"
          onClick={refetch}
          className="px-3 py-1.5 rounded-lg text-[11px] border border-white/8 text-white/50 hover:text-white/70 hover:border-white/20 transition-colors cursor-pointer"
        >
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      <ModelBrowser
        models={models}
        onToggleFavourite={handleToggleFavourite}
        onEditConfig={setConfigTarget}
      />

      {configTarget && (
        <ModelConfigModal
          model={configTarget}
          onClose={() => setConfigTarget(null)}
          onSaved={handleConfigSaved}
        />
      )}
    </div>
  )
}

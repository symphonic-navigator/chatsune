import { useState, useEffect, useRef } from "react"
import type { EnrichedModelDto } from "../../../core/types/llm"
import { llmApi } from "../../../core/api/llm"
import { useEnrichedModels } from "../../../core/hooks/useEnrichedModels"
import { slugWithoutProvider } from "./modelFilters"
import { ModelBrowser } from "./ModelBrowser"
import { ModelConfigModal } from "./ModelConfigModal"

interface ModelSelectionModalProps {
  currentModelId: string | null
  onSelect: (model: {
    unique_id: string
    display_name: string
    provider_id: string
    supports_reasoning: boolean
    supports_tool_calls: boolean
  }) => void
  onClose: () => void
}

export function ModelSelectionModal({
  currentModelId,
  onSelect,
  onClose,
}: ModelSelectionModalProps) {
  const { models, setModels, isLoading: loading, error } = useEnrichedModels()
  const [configModel, setConfigModel] = useState<EnrichedModelDto | null>(null)
  const backdropRef = useRef<HTMLDivElement>(null)

  // Escape key handling — only close outer modal when config modal is not open
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !configModel) {
        onClose()
      }
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [onClose, configModel])

  function handleBackdropClick(e: React.MouseEvent) {
    if (e.target === backdropRef.current && !configModel) {
      onClose()
    }
  }

  function handleSelect(model: EnrichedModelDto) {
    onSelect({
      unique_id: model.unique_id,
      display_name: model.display_name,
      provider_id: model.provider_id,
      supports_reasoning: model.supports_reasoning,
      supports_tool_calls: model.supports_tool_calls,
    })
  }

  /** Optimistic favourite toggle — update local state immediately, persist in background. */
  function handleToggleFavourite(model: EnrichedModelDto) {
    const newFav = !(model.user_config?.is_favourite ?? false)
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

    // Persist — fire and forget, revert on failure
    llmApi
      .setUserConfig(providerId, modelSlug, { is_favourite: newFav })
      .catch(() => {
        setModels((prev) =>
          prev.map((m) =>
            m.unique_id === model.unique_id
              ? { ...m, user_config: model.user_config }
              : m,
          ),
        )
      })
  }

  function handleConfigSaved(updatedModel: EnrichedModelDto) {
    setModels((prev) =>
      prev.map((m) => (m.unique_id === updatedModel.unique_id ? updatedModel : m)),
    )
    setConfigModel(null)
  }

  return (
    <>
      <div
        ref={backdropRef}
        onClick={handleBackdropClick}
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      >
        <div className="flex h-[80vh] w-full max-w-3xl flex-col rounded-xl border border-white/8 bg-surface shadow-2xl">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-white/6 px-5 py-3">
            <span className="text-[13px] font-semibold text-white/80">Select Model</span>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="flex h-6 w-6 items-center justify-center rounded text-[12px] text-white/40 hover:bg-white/8 hover:text-white/70 transition-colors"
            >
              &#x2715;
            </button>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-hidden">
            {loading && (
              <div className="flex items-center justify-center py-12 text-[12px] text-white/30">
                Loading models...
              </div>
            )}

            {error && (
              <div className="mx-4 mt-4 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-400">
                {error}
              </div>
            )}

            {!loading && !error && (
              <ModelBrowser
                currentModelId={currentModelId}
                models={models}
                onSelect={handleSelect}
                onEditConfig={(m) => setConfigModel(m)}
                onToggleFavourite={handleToggleFavourite}
              />
            )}
          </div>
        </div>
      </div>

      {/* Nested config modal */}
      {configModel && (
        <ModelConfigModal
          model={configModel}
          onClose={() => setConfigModel(null)}
          onSaved={handleConfigSaved}
        />
      )}
    </>
  )
}

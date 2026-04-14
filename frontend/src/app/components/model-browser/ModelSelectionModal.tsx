import { Sheet } from '../../../core/components/Sheet'
import type { EnrichedModelDto } from '../../../core/types/llm'
import { ModelBrowser, type LockedFilters } from './ModelBrowser'

/**
 * Shape that callers (EditTab) still expect. `provider_id` is the
 * connection_id in the new world — the split is the same since the
 * model_unique_id format is `{connection_id}:{model_slug}`.
 */
interface SelectPayload {
  unique_id: string
  display_name: string
  provider_id: string
  supports_reasoning: boolean
  supports_tool_calls: boolean
  supports_vision?: boolean
}

interface ModelSelectionModalProps {
  currentModelId: string | null
  onSelect: (model: SelectPayload) => void
  onClose: () => void
  lockedFilters?: LockedFilters
}

export function ModelSelectionModal({
  currentModelId,
  onSelect,
  onClose,
  lockedFilters,
}: ModelSelectionModalProps) {
  function handleSelect(model: EnrichedModelDto) {
    onSelect({
      unique_id: model.unique_id,
      display_name: model.user_config?.custom_display_name ?? model.display_name,
      provider_id: model.connection_id,
      supports_reasoning: model.supports_reasoning,
      supports_tool_calls: model.supports_tool_calls,
      supports_vision: model.supports_vision,
    })
  }

  return (
    <Sheet
      isOpen
      onClose={onClose}
      size="xl"
      ariaLabel="Modell auswählen"
      className="bg-surface flex flex-col h-full"
    >
      <div className="flex items-center justify-between border-b border-white/6 px-5 py-3">
        <h3 className="text-[15px] font-semibold text-white/85">Modell wählen</h3>
        <button
          type="button"
          onClick={onClose}
          className="rounded px-2 text-white/50 hover:bg-white/5 hover:text-white/80"
          aria-label="Schließen"
        >
          ✕
        </button>
      </div>
      <ModelBrowser
        onSelect={handleSelect}
        currentModelId={currentModelId}
        lockedFilters={lockedFilters}
      />
    </Sheet>
  )
}

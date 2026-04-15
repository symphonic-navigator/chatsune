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
  /**
   * 'standalone' (default): renders as a viewport-level Sheet.
   * 'in-parent': renders as an absolute-positioned overlay inside the nearest
   *   relative-positioned ancestor. On mobile (< lg) it fills the parent
   *   completely; on desktop it is inset to 80% height × 90% width.
   */
  mode?: 'standalone' | 'in-parent'
}

export function ModelSelectionModal({
  currentModelId,
  onSelect,
  onClose,
  lockedFilters,
  mode = 'standalone',
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

  const header = (
    <div className="flex items-center justify-between border-b border-white/6 px-5 py-3 flex-shrink-0">
      <h3 className="text-[15px] font-semibold text-white/85">Choose a model</h3>
      <button
        type="button"
        onClick={onClose}
        className="rounded px-2 text-white/50 hover:bg-white/5 hover:text-white/80"
        aria-label="Close"
      >
        ✕
      </button>
    </div>
  )

  if (mode === 'in-parent') {
    return (
      // Fills the parent on mobile; inset to 80% height × 90% width on desktop.
      // The parent (tab content div) must have `relative` positioning.
      <div
        className={[
          'absolute z-30 flex flex-col overflow-hidden',
          'bg-[#13101e] border border-white/8 shadow-2xl',
          'rounded-none lg:rounded-xl',
          // Mobile: fill the parent entirely
          'inset-0',
          // Desktop: centred at 80% height × 90% width
          'lg:inset-auto lg:top-[10%] lg:left-[5%] lg:right-[5%] lg:bottom-[10%]',
        ].join(' ')}
        role="dialog"
        aria-modal="true"
        aria-label="Select model"
      >
        {header}
        <ModelBrowser
          onSelect={handleSelect}
          currentModelId={currentModelId}
          lockedFilters={lockedFilters}
        />
      </div>
    )
  }

  return (
    <Sheet
      isOpen
      onClose={onClose}
      size="xl"
      ariaLabel="Select model"
      className="bg-surface flex flex-col h-full"
    >
      <div className="flex items-center justify-between border-b border-white/6 px-5 py-3">
        <h3 className="text-[15px] font-semibold text-white/85">Choose a model</h3>
        <button
          type="button"
          onClick={onClose}
          className="rounded px-2 text-white/50 hover:bg-white/5 hover:text-white/80"
          aria-label="Close"
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

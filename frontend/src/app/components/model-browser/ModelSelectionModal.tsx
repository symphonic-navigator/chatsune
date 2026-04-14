// TODO Phase 9: rewrite against the new connections/models pipeline.
import type { LockedFilters } from "./ModelBrowser"

interface ModelSelectionModalProps {
  currentModelId: string | null
  onSelect: (model: {
    unique_id: string
    display_name: string
    provider_id: string
    supports_reasoning: boolean
    supports_tool_calls: boolean
    supports_vision?: boolean
  }) => void
  onClose: () => void
  lockedFilters?: LockedFilters
}

export function ModelSelectionModal(_props: ModelSelectionModalProps) {
  return (
    <div className="p-6 text-white/60">
      Model-Auswahl wird überarbeitet (Phase 9)
    </div>
  )
}

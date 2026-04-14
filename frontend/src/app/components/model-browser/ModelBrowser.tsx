// TODO Phase 9: rewrite against the new connections/models pipeline.
import type { EnrichedModelDto } from "../../../core/types/llm"

export interface LockedFilters {
  capTools?: true
  capVision?: true
  capReason?: true
}

interface ModelBrowserProps {
  onEditConfig?: (model: EnrichedModelDto) => void
  onToggleFavourite?: (model: EnrichedModelDto) => void
  onSelect?: (model: EnrichedModelDto) => void
  currentModelId?: string | null
  models?: EnrichedModelDto[]
  lockedFilters?: LockedFilters
}

export function ModelBrowser(_props: ModelBrowserProps) {
  return (
    <div className="p-6 text-white/60">
      Model-Browser wird überarbeitet (Phase 9)
    </div>
  )
}

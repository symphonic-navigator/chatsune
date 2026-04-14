// TODO Phase 9: rewrite against the new connections/models pipeline.
import type { EnrichedModelDto } from "../../../core/types/llm"

interface ModelConfigModalProps {
  model: EnrichedModelDto
  onClose: () => void
  onSaved: (model: EnrichedModelDto) => void
}

export function ModelConfigModal(_props: ModelConfigModalProps) {
  return (
    <div className="p-6 text-white/60">
      Model-Config wird überarbeitet (Phase 9)
    </div>
  )
}

// TODO Phase 9: curation is being removed (Task 32). Stub retained
// only so AdminModal compiles until the tab itself is deleted.
import type { ModelMetaDto } from "../../../core/types/llm"

interface CurationModalProps {
  model: ModelMetaDto
  onCurationSaved: (model: ModelMetaDto) => void
  onClose: () => void
}

export function CurationModal(_props: CurationModalProps) {
  return (
    <div className="p-6 text-white/60">
      Curation entfällt (Phase 9)
    </div>
  )
}

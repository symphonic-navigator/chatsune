// TODO Phase 9: admin model list is being removed (Task 32).
import type { ModelMetaDto } from "../../../core/types/llm"

interface ModelListProps {
  models: ModelMetaDto[]
  onSelectModel: (model: ModelMetaDto) => void
}

export function ModelList(_props: ModelListProps) {
  return (
    <div className="p-6 text-white/60">
      Admin-Modell-Liste wird überarbeitet (Phase 9)
    </div>
  )
}

import { ollamaLocalApi } from "../../../core/api/ollamaLocal"
import { OllamaModelsPanel } from "../ollama/OllamaModelsPanel"

export function OllamaTab() {
  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <OllamaModelsPanel
        scope="admin-local"
        endpoints={{
          ps: ollamaLocalApi.ps,
          tags: ollamaLocalApi.tags,
          pull: ollamaLocalApi.pull,
          cancelPull: ollamaLocalApi.cancelPull,
          deleteModel: ollamaLocalApi.deleteModel,
          listPulls: ollamaLocalApi.listPulls,
        }}
      />
    </div>
  )
}

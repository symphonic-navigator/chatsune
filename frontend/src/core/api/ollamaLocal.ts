// Shared Ollama HTTP response types. Used by OllamaModelsPanel and the
// connection-scoped llmApi diagnostics/pull/delete endpoints. The original
// admin-scoped ollamaLocalApi has been removed alongside the dedicated
// "Ollama Local" admin tab — Ollama Local is now a regular per-user
// connection of the ollama_http adapter.

export interface OllamaPsModel {
  name: string
  model: string
  size: number
  details: {
    parameter_size: string
    quantization_level: string
  }
  size_vram: number
  context_length: number
}

export interface OllamaPsResponse {
  models: OllamaPsModel[]
}

export interface OllamaTagModel {
  name: string
  model: string
  size: number
  details: {
    parameter_size: string
    quantization_level: string
  }
}

export interface OllamaTagsResponse {
  models: OllamaTagModel[]
}

export interface StartPullResponse {
  pull_id: string
}

export interface PullHandleDto {
  pull_id: string
  slug: string
  status: string
  started_at: string
}

export interface ListPullsResponse {
  pulls: PullHandleDto[]
}

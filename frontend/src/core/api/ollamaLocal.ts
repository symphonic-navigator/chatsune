import { api } from "./client"

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

export const ollamaLocalApi = {
  ps: () => api.get<OllamaPsResponse>("/api/llm/admin/ollama-local/ps"),
  tags: () => api.get<OllamaTagsResponse>("/api/llm/admin/ollama-local/tags"),
  pull: (slug: string) =>
    api.post<StartPullResponse>("/api/llm/admin/ollama-local/pull", { slug }),
  cancelPull: (pullId: string) =>
    api.post<void>(`/api/llm/admin/ollama-local/pull/${pullId}/cancel`),
  deleteModel: (name: string) =>
    api.delete<void>(`/api/llm/admin/ollama-local/models/${encodeURIComponent(name)}`),
  listPulls: () =>
    api.get<ListPullsResponse>("/api/llm/admin/ollama-local/pulls"),
}

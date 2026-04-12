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

export const ollamaLocalApi = {
  ps: () => api.get<OllamaPsResponse>("/api/llm/admin/ollama-local/ps"),
  tags: () => api.get<OllamaTagsResponse>("/api/llm/admin/ollama-local/tags"),
}

import { api } from "./client"
import type {
  Adapter,
  Connection,
  CreateConnectionRequest,
  UpdateConnectionRequest,
  ModelMetaDto,
  UserModelConfigDto,
  SetUserModelConfigRequest,
  TestResultResponse,
} from "../types/llm"
import type { StartPullResponse, ListPullsResponse } from "./ollamaLocal"

export const llmApi = {
  listAdapters: () =>
    api.get<Adapter[]>("/api/llm/adapters"),

  listConnections: () =>
    api.get<Connection[]>("/api/llm/connections"),

  createConnection: (body: CreateConnectionRequest) =>
    api.post<Connection>("/api/llm/connections", body),

  getConnection: (id: string) =>
    api.get<Connection>(`/api/llm/connections/${id}`),

  updateConnection: (id: string, body: UpdateConnectionRequest) =>
    api.patch<Connection>(`/api/llm/connections/${id}`, body),

  deleteConnection: (id: string) =>
    api.delete<void>(`/api/llm/connections/${id}`),

  listConnectionModels: (id: string) =>
    api.get<ModelMetaDto[]>(`/api/llm/connections/${id}/models`),

  /** Returns 202 once the upstream query finishes; emits LLM_CONNECTION_MODELS_REFRESHED. */
  refreshConnectionModels: (id: string) =>
    api.post<void>(`/api/llm/connections/${id}/refresh`),

  /** Adapter sub-router — live test against the remote end. */
  testConnection: (id: string) =>
    api.post<TestResultResponse>(`/api/llm/connections/${id}/adapter/test`),

  getConnectionDiagnostics: (id: string) =>
    api.get<{ ps: unknown; tags: unknown }>(`/api/llm/connections/${id}/adapter/diagnostics`),

  getUserModelConfig: (connectionId: string, modelSlug: string) =>
    api.get<UserModelConfigDto>(
      `/api/llm/connections/${connectionId}/models/${encodeURIComponent(modelSlug)}/user-config`,
    ),

  setUserModelConfig: (
    connectionId: string,
    modelSlug: string,
    body: SetUserModelConfigRequest,
  ) =>
    api.put<UserModelConfigDto>(
      `/api/llm/connections/${connectionId}/models/${encodeURIComponent(modelSlug)}/user-config`,
      body,
    ),

  deleteUserModelConfig: (connectionId: string, modelSlug: string) =>
    api.delete<UserModelConfigDto>(
      `/api/llm/connections/${connectionId}/models/${encodeURIComponent(modelSlug)}/user-config`,
    ),

  listUserModelConfigs: () =>
    api.get<UserModelConfigDto[]>("/api/llm/user-model-configs"),

  pullModel: (connectionId: string, slug: string) =>
    api.post<StartPullResponse>(
      `/api/llm/connections/${connectionId}/adapter/pull`,
      { slug },
    ),

  cancelModelPull: (connectionId: string, pullId: string) =>
    api.post<void>(
      `/api/llm/connections/${connectionId}/adapter/pull/${pullId}/cancel`,
    ),

  deleteConnectionModel: (connectionId: string, name: string) =>
    api.delete<void>(
      `/api/llm/connections/${connectionId}/adapter/models/${encodeURIComponent(name)}`,
    ),

  listConnectionPulls: (connectionId: string) =>
    api.get<ListPullsResponse>(
      `/api/llm/connections/${connectionId}/adapter/pulls`,
    ),
}

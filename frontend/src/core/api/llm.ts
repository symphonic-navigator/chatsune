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

  /** Returns 202 — the refresh is asynchronous; completion flows through events. */
  refreshConnectionModels: (id: string) =>
    api.post<void>(`/api/llm/connections/${id}/models/refresh`),

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
}

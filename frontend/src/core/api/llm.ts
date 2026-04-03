import { api } from "./client"
import type {
  ProviderCredentialDto,
  SetProviderKeyRequest,
  ModelMetaDto,
  ModelCurationDto,
  SetModelCurationRequest,
  UserModelConfigDto,
  SetUserModelConfigRequest,
  TestKeyResponse,
} from "../types/llm"

export const llmApi = {
  listProviders: () =>
    api.get<ProviderCredentialDto[]>("/api/llm/providers"),

  setKey: (providerId: string, data: SetProviderKeyRequest) =>
    api.put<ProviderCredentialDto>(`/api/llm/providers/${providerId}/key`, data),

  removeKey: (providerId: string) =>
    api.delete<{ status: string }>(`/api/llm/providers/${providerId}/key`),

  testKey: (providerId: string, data: SetProviderKeyRequest) =>
    api.post<TestKeyResponse>(`/api/llm/providers/${providerId}/test`, data),

  listModels: (providerId: string) =>
    api.get<ModelMetaDto[]>(`/api/llm/providers/${providerId}/models`),

  setCuration: (providerId: string, modelSlug: string, data: SetModelCurationRequest) =>
    api.put<ModelCurationDto>(`/api/llm/providers/${providerId}/models/${encodeURIComponent(modelSlug)}/curation`, data),

  removeCuration: (providerId: string, modelSlug: string) =>
    api.delete<{ status: string }>(`/api/llm/providers/${providerId}/models/${encodeURIComponent(modelSlug)}/curation`),

  listUserConfigs: () =>
    api.get<UserModelConfigDto[]>("/api/llm/user-model-configs"),

  getUserConfig: (providerId: string, modelSlug: string) =>
    api.get<UserModelConfigDto>(`/api/llm/providers/${providerId}/models/${encodeURIComponent(modelSlug)}/user-config`),

  setUserConfig: (providerId: string, modelSlug: string, data: SetUserModelConfigRequest) =>
    api.put<UserModelConfigDto>(`/api/llm/providers/${providerId}/models/${encodeURIComponent(modelSlug)}/user-config`, data),

  deleteUserConfig: (providerId: string, modelSlug: string) =>
    api.delete<UserModelConfigDto>(`/api/llm/providers/${providerId}/models/${encodeURIComponent(modelSlug)}/user-config`),
}

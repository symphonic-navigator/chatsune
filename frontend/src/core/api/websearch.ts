import { api } from "./client"
import type {
  WebSearchProvider,
  WebSearchCredential,
  TestWebSearchResponse,
} from "../types/websearch"

export const webSearchApi = {
  listWebSearchProviders: () =>
    api.get<WebSearchProvider[]>("/api/websearch/providers"),

  getWebSearchCredential: (providerId: string) =>
    api.get<WebSearchCredential>(`/api/websearch/providers/${providerId}/credential`),

  setWebSearchKey: (providerId: string, apiKey: string) =>
    api.put<WebSearchCredential>(
      `/api/websearch/providers/${providerId}/key`,
      { api_key: apiKey },
    ),

  deleteWebSearchKey: (providerId: string) =>
    api.delete<void>(`/api/websearch/providers/${providerId}/key`),

  testWebSearchKey: (providerId: string, apiKey: string) =>
    api.post<TestWebSearchResponse>(
      `/api/websearch/providers/${providerId}/test`,
      { api_key: apiKey },
    ),
}

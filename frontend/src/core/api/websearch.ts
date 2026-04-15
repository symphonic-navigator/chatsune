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
      `/api/websearch/providers/${providerId}/credential`,
      { api_key: apiKey },
    ),

  deleteWebSearchKey: (providerId: string) =>
    api.delete<void>(`/api/websearch/providers/${providerId}/credential`),

  testWebSearchKey: (providerId: string, apiKey: string | undefined) =>
    api.post<TestWebSearchResponse>(
      `/api/websearch/providers/${providerId}/test`,
      apiKey === undefined ? {} : { api_key: apiKey },
    ),
}

import { api } from "./client"
import type { AppSettingDto, SetSettingRequest } from "../types/settings"

export const settingsApi = {
  list: () =>
    api.get<AppSettingDto[]>("/api/settings"),

  get: (key: string) =>
    api.get<AppSettingDto>(`/api/settings/${encodeURIComponent(key)}`),

  set: (key: string, data: SetSettingRequest) =>
    api.put<AppSettingDto>(`/api/settings/${encodeURIComponent(key)}`, data),

  remove: (key: string) =>
    api.delete<{ status: string }>(`/api/settings/${encodeURIComponent(key)}`),

  getSystemPrompt: () =>
    api.get<{ content: string; updated_at: string | null; updated_by: string | null }>("/api/settings/system-prompt"),

  setSystemPrompt: (content: string) =>
    api.put<{ content: string; updated_at: string; updated_by: string }>("/api/settings/system-prompt", { content }),
}

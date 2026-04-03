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
}

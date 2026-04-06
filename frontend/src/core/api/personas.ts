import { api, currentAccessToken } from "./client"
import { ApiError } from "./client"
import type {
  PersonaDto,
  CreatePersonaRequest,
  UpdatePersonaRequest,
} from "../types/persona"

function baseUrl(): string {
  return import.meta.env.VITE_API_URL ?? ""
}

export const personasApi = {
  list: () =>
    api.get<PersonaDto[]>("/api/personas"),

  get: (personaId: string) =>
    api.get<PersonaDto>(`/api/personas/${personaId}`),

  create: (data: CreatePersonaRequest) =>
    api.post<PersonaDto>("/api/personas", data),

  replace: (personaId: string, data: CreatePersonaRequest) =>
    api.put<PersonaDto>(`/api/personas/${personaId}`, data),

  update: (personaId: string, data: UpdatePersonaRequest) =>
    api.patch<PersonaDto>(`/api/personas/${personaId}`, data),

  remove: (personaId: string) =>
    api.delete<{ status: string }>(`/api/personas/${personaId}`),

  reorder: async (orderedIds: string[]): Promise<void> => {
    await api.patch("/api/personas/reorder", { ordered_ids: orderedIds });
  },

  getSystemPromptPreview: (personaId: string) =>
    api.get<{ preview: string }>(`/api/personas/${personaId}/system-prompt-preview`),

  uploadAvatar: async (personaId: string, blob: Blob, crop?: { x: number; y: number; zoom: number; width: number; height: number }): Promise<PersonaDto> => {
    const form = new FormData()
    form.append("file", blob, "avatar.png")
    if (crop) form.append("crop", JSON.stringify(crop))
    const token = currentAccessToken()
    const headers: Record<string, string> = {}
    if (token) headers["Authorization"] = `Bearer ${token}`
    const res = await fetch(`${baseUrl()}/api/personas/${personaId}/avatar`, {
      method: "POST",
      headers,
      body: form,
      credentials: "include",
    })
    if (!res.ok) {
      const body = await res.json().catch(() => null)
      throw new ApiError(res.status, body?.detail ?? res.statusText, body)
    }
    return res.json()
  },

  updateAvatarCrop: (personaId: string, crop: { x: number; y: number; zoom: number; width: number; height: number }) =>
    api.patch<PersonaDto>(`/api/personas/${personaId}/avatar/crop`, crop),

  deleteAvatar: (personaId: string) =>
    api.delete<PersonaDto>(`/api/personas/${personaId}/avatar`),

  avatarUrl: (personaId: string) =>
    `${baseUrl()}/api/personas/${personaId}/avatar`,

  /** Fetch a short-lived signed avatar URL from the backend for <img src> usage. */
  avatarSrc: async (personaId: string, _updatedAt?: string): Promise<string> => {
    const res = await api.get<{ url: string }>(`/api/personas/${personaId}/avatar-url`)
    return `${baseUrl()}${res.url}`
  },
}

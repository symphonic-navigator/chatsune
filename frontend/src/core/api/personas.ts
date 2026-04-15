import { api, currentAccessToken } from "./client"
import { ApiError } from "./client"
import { parseContentDispositionFilename } from "../utils/download"
import type { DeletionReportDto } from "../types/deletion"
import type {
  PersonaDto,
  CreatePersonaRequest,
  UpdatePersonaRequest,
} from "../types/persona"

function baseUrl(): string {
  return import.meta.env.VITE_API_URL ?? ""
}

const PERSONA_EXPORT_FALLBACK_FILENAME = "persona-export.chatsune-persona.tar.gz"

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
    api.delete<DeletionReportDto>(`/api/personas/${personaId}`),

  clonePersona: (
    personaId: string,
    body: { name: string; clone_memory: boolean },
  ) =>
    api.post<PersonaDto>(`/api/personas/${personaId}/clone`, body),

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

  /**
   * Download a persona archive as a gzip Blob. Returns the raw bytes plus the
   * filename the backend suggested in `Content-Disposition`. If the header
   * cannot be parsed, a generic fallback filename is used.
   */
  exportPersona: async (
    personaId: string,
    includeContent: boolean,
  ): Promise<{ blob: Blob; filename: string }> => {
    const token = currentAccessToken()
    const headers: Record<string, string> = {}
    if (token) headers["Authorization"] = `Bearer ${token}`
    const query = includeContent ? "?include_content=true" : "?include_content=false"
    const res = await fetch(
      `${baseUrl()}/api/personas/${personaId}/export${query}`,
      {
        method: "GET",
        headers,
        credentials: "include",
      },
    )
    if (!res.ok) {
      const body = await res.json().catch(() => null) as { detail?: string } | null
      throw new ApiError(res.status, body?.detail ?? res.statusText, body)
    }
    const blob = await res.blob()
    const filename =
      parseContentDispositionFilename(res.headers.get("Content-Disposition")) ??
      PERSONA_EXPORT_FALLBACK_FILENAME
    return { blob, filename }
  },

  /**
   * Upload a persona archive as multipart/form-data. Returns the created
   * PersonaDto on success. Surfaces HTTP 413 as a readable error so callers
   * can show a toast with a concrete message.
   */
  importPersona: async (file: File): Promise<PersonaDto> => {
    const form = new FormData()
    form.append("file", file)
    const token = currentAccessToken()
    const headers: Record<string, string> = {}
    if (token) headers["Authorization"] = `Bearer ${token}`
    const res = await fetch(`${baseUrl()}/api/personas/import`, {
      method: "POST",
      headers,
      body: form,
      credentials: "include",
    })
    if (!res.ok) {
      const body = await res.json().catch(() => null) as { detail?: string } | null
      if (res.status === 413) {
        throw new ApiError(
          413,
          body?.detail ?? "Archive exceeds the 200 MB upload limit.",
          body,
        )
      }
      throw new ApiError(res.status, body?.detail ?? res.statusText, body)
    }
    return res.json() as Promise<PersonaDto>
  },
}

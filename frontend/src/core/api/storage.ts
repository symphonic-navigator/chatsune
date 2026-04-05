import { currentAccessToken, ApiError, api } from "./client"

export interface AttachmentRefDto {
  file_id: string
  display_name: string
  media_type: string
  size_bytes: number
  thumbnail_b64: string | null
  text_preview: string | null
}

export interface StorageFileDto {
  id: string
  user_id: string
  persona_id: string | null
  original_name: string
  display_name: string
  media_type: string
  size_bytes: number
  thumbnail_b64: string | null
  text_preview: string | null
  created_at: string
  updated_at: string
}

export interface StorageQuotaDto {
  used_bytes: number
  limit_bytes: number
  percentage: number
}

function baseUrl(): string {
  return import.meta.env.VITE_API_URL ?? ""
}

export async function uploadFile(
  file: File,
  personaId?: string,
): Promise<StorageFileDto> {
  const form = new FormData()
  form.append("file", file)
  if (personaId) form.append("persona_id", personaId)

  const token = currentAccessToken()
  const headers: Record<string, string> = {}
  if (token) headers["Authorization"] = `Bearer ${token}`

  const res = await fetch(`${baseUrl()}/api/storage/files`, {
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
}

export const storageApi = {
  listFiles: (params?: {
    persona_id?: string
    sort_by?: "date" | "size"
    order?: "asc" | "desc"
    limit?: number
    offset?: number
  }) => {
    const query = new URLSearchParams()
    if (params?.persona_id) query.set("persona_id", params.persona_id)
    if (params?.sort_by) query.set("sort_by", params.sort_by)
    if (params?.order) query.set("order", params.order)
    if (params?.limit !== undefined) query.set("limit", String(params.limit))
    if (params?.offset !== undefined) query.set("offset", String(params.offset))
    const qs = query.toString()
    return api.get<StorageFileDto[]>(`/api/storage/files${qs ? `?${qs}` : ""}`)
  },

  downloadUrl: (fileId: string) =>
    `${baseUrl()}/api/storage/files/${fileId}/download`,

  renameFile: (fileId: string, displayName: string) =>
    api.patch<StorageFileDto>(`/api/storage/files/${fileId}`, { display_name: displayName }),

  deleteFile: (fileId: string) =>
    api.delete<void>(`/api/storage/files/${fileId}`),

  getQuota: () =>
    api.get<StorageQuotaDto>("/api/storage/quota"),
}

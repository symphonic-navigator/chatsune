import { api, ApiError, currentAccessToken } from './client'
import { parseContentDispositionFilename } from '../utils/download'
import type {
  KnowledgeDocumentDetailDto,
  KnowledgeDocumentDto,
  KnowledgeLibraryDto,
} from '../types/knowledge'

function baseUrl(): string {
  return import.meta.env.VITE_API_URL ?? ''
}

const LIBRARY_EXPORT_FALLBACK_FILENAME = 'knowledge-library.chatsune-knowledge.tar.gz'

export const knowledgeApi = {
  // Libraries
  listLibraries: () =>
    api.get<KnowledgeLibraryDto[]>('/api/knowledge/libraries'),

  createLibrary: (body: { name: string; description?: string; nsfw?: boolean }) =>
    api.post<KnowledgeLibraryDto>('/api/knowledge/libraries', body),

  updateLibrary: (id: string, body: { name?: string; description?: string; nsfw?: boolean }) =>
    api.put<KnowledgeLibraryDto>(`/api/knowledge/libraries/${id}`, body),

  deleteLibrary: (id: string) =>
    api.delete<{ status: string }>(`/api/knowledge/libraries/${id}`),

  // Documents
  listDocuments: (libraryId: string) =>
    api.get<KnowledgeDocumentDto[]>(`/api/knowledge/libraries/${libraryId}/documents`),

  getDocument: (libraryId: string, docId: string) =>
    api.get<KnowledgeDocumentDetailDto>(`/api/knowledge/libraries/${libraryId}/documents/${docId}`),

  createDocument: (libraryId: string, body: { title: string; content: string; media_type?: string }) =>
    api.post<KnowledgeDocumentDto>(`/api/knowledge/libraries/${libraryId}/documents`, body),

  updateDocument: (libraryId: string, docId: string, body: { title?: string; content?: string; media_type?: string }) =>
    api.put<KnowledgeDocumentDto>(`/api/knowledge/libraries/${libraryId}/documents/${docId}`, body),

  deleteDocument: (libraryId: string, docId: string) =>
    api.delete<{ status: string }>(`/api/knowledge/libraries/${libraryId}/documents/${docId}`),

  retryEmbedding: (libraryId: string, docId: string) =>
    api.post<{ status: string }>(`/api/knowledge/libraries/${libraryId}/documents/${docId}/retry`),

  // Assignments
  getPersonaKnowledge: (personaId: string) =>
    api.get<{ library_ids: string[] }>(`/api/personas/${personaId}/knowledge`),

  setPersonaKnowledge: (personaId: string, libraryIds: string[]) =>
    api.put<{ status: string }>(`/api/personas/${personaId}/knowledge`, { library_ids: libraryIds }),

  getSessionKnowledge: (sessionId: string) =>
    api.get<{ library_ids: string[] }>(`/api/chat/sessions/${sessionId}/knowledge`),

  setSessionKnowledge: (sessionId: string, libraryIds: string[]) =>
    api.put<{ status: string }>(`/api/chat/sessions/${sessionId}/knowledge`, { library_ids: libraryIds }),

  /**
   * Download a knowledge-library archive as a gzip Blob. Returns the raw
   * bytes plus the filename the backend suggested in `Content-Disposition`.
   * If the header cannot be parsed a generic fallback filename is used.
   */
  exportLibrary: async (
    libraryId: string,
  ): Promise<{ blob: Blob; filename: string }> => {
    const token = currentAccessToken()
    const headers: Record<string, string> = {}
    if (token) headers['Authorization'] = `Bearer ${token}`
    const res = await fetch(
      `${baseUrl()}/api/knowledge/libraries/${libraryId}/export`,
      {
        method: 'GET',
        headers,
        credentials: 'include',
      },
    )
    if (!res.ok) {
      const body = await res.json().catch(() => null) as { detail?: string } | null
      throw new ApiError(res.status, body?.detail ?? res.statusText, body)
    }
    const blob = await res.blob()
    const filename =
      parseContentDispositionFilename(res.headers.get('Content-Disposition')) ??
      LIBRARY_EXPORT_FALLBACK_FILENAME
    return { blob, filename }
  },

  /**
   * Upload a knowledge-library archive as multipart/form-data. Returns the
   * created library DTO. Surfaces HTTP 413 as a readable error.
   */
  importLibrary: async (file: File): Promise<KnowledgeLibraryDto> => {
    const form = new FormData()
    form.append('file', file)
    const token = currentAccessToken()
    const headers: Record<string, string> = {}
    if (token) headers['Authorization'] = `Bearer ${token}`
    const res = await fetch(`${baseUrl()}/api/knowledge/libraries/import`, {
      method: 'POST',
      headers,
      body: form,
      credentials: 'include',
    })
    if (!res.ok) {
      const body = await res.json().catch(() => null) as { detail?: string } | null
      if (res.status === 413) {
        throw new ApiError(
          413,
          body?.detail ?? 'Archive exceeds the 200 MB upload limit.',
          body,
        )
      }
      throw new ApiError(res.status, body?.detail ?? res.statusText, body)
    }
    return res.json() as Promise<KnowledgeLibraryDto>
  },
}

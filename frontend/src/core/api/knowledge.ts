import { api } from './client'
import type {
  KnowledgeDocumentDetailDto,
  KnowledgeDocumentDto,
  KnowledgeLibraryDto,
} from '../types/knowledge'

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
}

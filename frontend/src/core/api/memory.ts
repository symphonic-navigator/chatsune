import { api } from './client'

export interface JournalEntryDto {
  id: string
  persona_id: string
  content: string
  category: string | null
  state: 'uncommitted' | 'committed' | 'archived'
  is_correction: boolean
  created_at: string
  committed_at: string | null
  auto_committed: boolean
}

export interface MemoryBodyDto {
  persona_id: string
  content: string
  token_count: number
  version: number
  created_at: string
}

export interface MemoryBodyVersionDto {
  version: number
  token_count: number
  entries_processed: number
  created_at: string
}

export interface MemoryContextDto {
  persona_id: string
  uncommitted_count: number
  committed_count: number
  last_extraction_at: string | null
  last_dream_at: string | null
  can_trigger_extraction: boolean
}

export const memoryApi = {
  listJournalEntries: (personaId: string, state?: string) => {
    const query = state ? `?state=${encodeURIComponent(state)}` : ''
    return api.get<JournalEntryDto[]>(`/api/memory/${personaId}/journal${query}`)
  },

  updateEntry: (personaId: string, entryId: string, content: string) =>
    api.patch<JournalEntryDto>(`/api/memory/${personaId}/journal/${entryId}`, { content }),

  commitEntries: (personaId: string, entryIds: string[]) =>
    api.post<void>(`/api/memory/${personaId}/journal/commit`, { entry_ids: entryIds }),

  deleteEntries: (personaId: string, entryIds: string[]) =>
    api.post<void>(`/api/memory/${personaId}/journal/delete`, { entry_ids: entryIds }),

  getMemoryBody: (personaId: string) =>
    api.get<MemoryBodyDto>(`/api/memory/${personaId}/body`),

  listBodyVersions: (personaId: string) =>
    api.get<MemoryBodyVersionDto[]>(`/api/memory/${personaId}/body/versions`),

  getBodyVersion: (personaId: string, version: number) =>
    api.get<MemoryBodyDto>(`/api/memory/${personaId}/body/versions/${version}`),

  rollbackBody: (personaId: string, toVersion: number) =>
    api.post<void>(`/api/memory/${personaId}/body/rollback`, { to_version: toVersion }),

  getContext: (personaId: string) =>
    api.get<MemoryContextDto>(`/api/memory/${personaId}/context`),

  triggerExtraction: (personaId: string) =>
    api.post<void>(`/api/memory/${personaId}/extract`),

  triggerDream: (personaId: string) =>
    api.post<void>(`/api/memory/${personaId}/dream`),
}

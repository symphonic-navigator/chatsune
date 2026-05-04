import { api } from './client'
import type { ArtefactDetail, ArtefactListItem, ArtefactSummary } from '../types/artefact'

const BASE = '/api/chat/sessions'

export const artefactApi = {
  list: (sessionId: string) =>
    api.get<ArtefactSummary[]>(`${BASE}/${sessionId}/artefacts/`),

  listAll: (params?: { project_id?: string }) => {
    const query = new URLSearchParams()
    if (params?.project_id) query.set('project_id', params.project_id)
    const qs = query.toString()
    return api.get<ArtefactListItem[]>(`/api/artefacts/${qs ? `?${qs}` : ''}`)
  },

  get: (sessionId: string, artefactId: string) =>
    api.get<ArtefactDetail>(`${BASE}/${sessionId}/artefacts/${artefactId}`),

  patch: (sessionId: string, artefactId: string, body: { title?: string; content?: string }) =>
    api.patch<ArtefactDetail>(`${BASE}/${sessionId}/artefacts/${artefactId}`, body),

  delete: (sessionId: string, artefactId: string) =>
    api.delete<{ status: string }>(`${BASE}/${sessionId}/artefacts/${artefactId}`),

  undo: (sessionId: string, artefactId: string) =>
    api.post<ArtefactDetail>(`${BASE}/${sessionId}/artefacts/${artefactId}/undo`),

  redo: (sessionId: string, artefactId: string) =>
    api.post<ArtefactDetail>(`${BASE}/${sessionId}/artefacts/${artefactId}/redo`),
}

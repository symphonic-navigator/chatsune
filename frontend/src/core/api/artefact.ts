import { api } from './client'
import type { ArtefactDetail, ArtefactSummary } from '../types/artefact'

const BASE = '/api/chat/sessions'

export const artefactApi = {
  list: (sessionId: string) =>
    api.get<ArtefactSummary[]>(`${BASE}/${sessionId}/artefacts/`),

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

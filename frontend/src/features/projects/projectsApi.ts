// Mindspace projects REST client. Thin wrapper around the shared
// `api` helper; mirrors the convention used by other feature APIs
// (e.g. `core/api/chat.ts`, `features/integrations/api.ts`).
//
// The plan-doc sketch references a hypothetical `apiFetch` helper, but
// the canonical pattern in this codebase is the `api` object exported
// from `core/api/client.ts` — using it keeps auth, refresh, and
// backend-marker handling in one place.

import { api } from '../../core/api/client'
import type {
  ProjectDto,
  ProjectCreateDto,
  ProjectUpdateDto,
  ProjectWithUsage,
} from './types'

export const projectsApi = {
  /** List all projects owned by the current user, sorted server-side. */
  list: () => api.get<ProjectDto[]>('/api/projects'),

  /**
   * Fetch a single project. Pass ``includeUsage=true`` to also return
   * ``usage`` (chat / upload / artefact / image counts) — used by the
   * delete-modal to label the full-purge variant.
   */
  get: (id: string, includeUsage = false) =>
    api.get<ProjectWithUsage>(
      `/api/projects/${id}${includeUsage ? '?include_usage=true' : ''}`,
    ),

  create: (body: ProjectCreateDto) =>
    api.post<ProjectDto>('/api/projects', body),

  patch: (id: string, body: ProjectUpdateDto) =>
    api.patch<ProjectDto>(`/api/projects/${id}`, body),

  /**
   * Delete a project. ``purgeData=false`` is a safe-delete (just the
   * project document and its scoping fields); ``purgeData=true`` cascades
   * to member chats, uploads, artefacts, and images.
   */
  delete: (id: string, purgeData: boolean) =>
    api.delete<{ ok: true }>(
      `/api/projects/${id}?purge_data=${purgeData}`,
    ),

  /** Toggle the sidebar-pin flag. */
  setPinned: (id: string, pinned: boolean) =>
    api.patch<{ ok: true }>(`/api/projects/${id}/pinned`, { pinned }),

  /**
   * Assign or detach a chat session to/from a project. Pass
   * ``projectId === null`` to detach.
   */
  setSessionProject: (sessionId: string, projectId: string | null) =>
    api.patch<{ ok: true }>(
      `/api/chat/sessions/${sessionId}/project`,
      { project_id: projectId },
    ),
}

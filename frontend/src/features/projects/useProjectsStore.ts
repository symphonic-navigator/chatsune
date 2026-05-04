// Mindspace projects store. Owns the canonical client-side view of the
// user's projects: a flat ``Record<id, ProjectDto>`` keyed for O(1)
// upsert / remove, plus selectors that materialise sorted views.
//
// Sorting belongs in the selector, not the store, so that re-sorting on
// every event update is free (selectors recompute lazily). NSFW
// filtering is *not* applied here — per spec §6.7, AppLayout is the
// central filter point and the store stays neutral.
//
// Event subscriptions are registered once at module load. They forward
// the four project-bus topics into store mutations:
//
//   project.created          → upsert(payload)
//   project.updated          → upsert(payload)
//   project.deleted          → remove(payload.id)
//   project.pinned.updated   → patch ``pinned`` only (the payload of
//                              this event is intentionally narrow —
//                              {id, pinned, user_id} — so we must not
//                              clobber the rest of the doc)

import { useMemo } from 'react'
import { create } from 'zustand'
import { eventBus } from '../../core/websocket/eventBus'
import type { BaseEvent } from '../../core/types/events'
import { Topics } from '../../core/types/events'
import { useSanitisedMode } from '../../core/store/sanitisedModeStore'
import { projectsApi } from './projectsApi'
import type { ProjectDto } from './types'

interface ProjectsState {
  projects: Record<string, ProjectDto>
  loaded: boolean
  loading: boolean

  load: () => Promise<void>
  upsert: (project: ProjectDto) => void
  remove: (id: string) => void
}

export const useProjectsStore = create<ProjectsState>((set, get) => ({
  projects: {},
  loaded: false,
  loading: false,

  load: async () => {
    if (get().loading) return
    set({ loading: true })
    try {
      const list = await projectsApi.list()
      const projects: Record<string, ProjectDto> = {}
      for (const project of list) {
        projects[project.id] = project
      }
      set({ projects, loaded: true })
    } catch (err) {
      console.error('[projects] Failed to load:', err)
    } finally {
      set({ loading: false })
    }
  },

  upsert: (project) =>
    set((state) => ({
      projects: { ...state.projects, [project.id]: project },
    })),

  remove: (id) =>
    set((state) => {
      if (!(id in state.projects)) return state
      const next = { ...state.projects }
      delete next[id]
      return { projects: next }
    }),
}))

// --- Event-bus wiring --------------------------------------------------
//
// We coerce ``event.payload`` to the relevant shape inline rather than
// using a generic ``as`` cast so we never silently accept a malformed
// payload. Defensive parsing matters here because event handlers run
// for the lifetime of the app — a single bad cast pollutes the store.

eventBus.on(Topics.PROJECT_CREATED, (event: BaseEvent) => {
  const project = event.payload as unknown as ProjectDto
  if (project && typeof project.id === 'string') {
    useProjectsStore.getState().upsert(project)
  }
})

eventBus.on(Topics.PROJECT_UPDATED, (event: BaseEvent) => {
  const project = event.payload as unknown as ProjectDto
  if (project && typeof project.id === 'string') {
    useProjectsStore.getState().upsert(project)
  }
})

eventBus.on(Topics.PROJECT_DELETED, (event: BaseEvent) => {
  // Backend ``ProjectDeletedEvent`` carries ``project_id`` (matching the
  // other project-bus events). The previous ``id`` lookup silently
  // returned ``undefined`` so the store never removed deleted projects.
  const id = (event.payload as { project_id?: unknown }).project_id
  if (typeof id === 'string') {
    useProjectsStore.getState().remove(id)
  }
})

eventBus.on(Topics.PROJECT_PINNED_UPDATED, (event: BaseEvent) => {
  // Narrow payload — only ``pinned`` changes. Patch in place so the
  // rest of the project document survives.
  // Backend ``ProjectPinnedUpdatedEvent`` carries ``project_id`` (consistent
  // with the rest of the project event family); the previous ``id``
  // lookup silently dropped every pin update.
  const payload = event.payload as { project_id?: unknown; pinned?: unknown }
  if (typeof payload.project_id !== 'string' || typeof payload.pinned !== 'boolean') {
    return
  }
  const existing = useProjectsStore.getState().projects[payload.project_id]
  if (!existing) return
  useProjectsStore.getState().upsert({ ...existing, pinned: payload.pinned })
})

// --- Selectors ---------------------------------------------------------
//
// Both selector hooks subscribe to ``s.projects`` (a stable reference
// that only changes when the map itself changes) and derive the sorted
// list inside ``useMemo``. Returning a freshly-sorted array directly
// from the Zustand selector would re-render on every unrelated store
// change because each call produces a new reference.

/** Compare ``pinned desc, updated_at desc``. */
function sortProjects(a: ProjectDto, b: ProjectDto): number {
  if (a.pinned !== b.pinned) return a.pinned ? -1 : 1
  return b.updated_at.localeCompare(a.updated_at)
}

/**
 * All projects, sorted ``pinned desc, updated_at desc``. The user's
 * project list is small (tens, not thousands), so a sort on every
 * change is cheap.
 */
export function useSortedProjects(): ProjectDto[] {
  const projects = useProjectsStore((s) => s.projects)
  return useMemo(() => Object.values(projects).sort(sortProjects), [projects])
}

/** Pinned projects only — sidebar Projects-zone fodder. */
export function usePinnedProjects(): ProjectDto[] {
  const sorted = useSortedProjects()
  return useMemo(() => sorted.filter((p) => p.pinned), [sorted])
}

/**
 * Mindspace §6.7: shared NSFW filter for every surface that lists
 * projects. Returns ``useSortedProjects`` filtered through the global
 * sanitised flag — when sanitised mode is on, NSFW projects are hidden.
 *
 * Mirrors the pattern AppLayout uses for personas / sessions but is
 * exposed as a hook because the consumer list is large (Sidebar,
 * ProjectPicker, ProjectPickerMobile, ProjectsTab, MobileProjectsView,
 * HistoryTab) — prop-drilling from AppLayout would be heavy and prone
 * to drift.
 *
 * Surfaces that need to keep showing the **active** chat's project even
 * when it is filtered out of discovery (the in-chat ProjectSwitcher
 * chip — spec "what is already open stays open") read the unfiltered
 * ``useProjectsStore.projects`` directly.
 */
export function useFilteredProjects(): ProjectDto[] {
  const sorted = useSortedProjects()
  const isSanitised = useSanitisedMode((s) => s.isSanitised)
  return useMemo(
    () => (isSanitised ? sorted.filter((p) => !p.nsfw) : sorted),
    [sorted, isSanitised],
  )
}

/** Pinned projects, NSFW-filtered. */
export function useFilteredPinnedProjects(): ProjectDto[] {
  const filtered = useFilteredProjects()
  return useMemo(() => filtered.filter((p) => p.pinned), [filtered])
}

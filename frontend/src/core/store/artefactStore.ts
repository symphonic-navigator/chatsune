import { create } from 'zustand'
import type { ArtefactSummary, ArtefactDetail } from '../types/artefact'

interface ArtefactState {
  artefacts: ArtefactSummary[]
  sidebarOpen: boolean
  activeArtefact: ArtefactDetail | null
  activeArtefactLoading: boolean

  setArtefacts: (artefacts: ArtefactSummary[]) => void
  addArtefact: (artefact: ArtefactSummary) => void
  updateArtefact: (handle: string, updates: Partial<ArtefactSummary>) => void
  removeArtefact: (handle: string) => void
  toggleSidebar: () => void
  setSidebarOpen: (open: boolean) => void
  openOverlay: (detail: ArtefactDetail) => void
  closeOverlay: () => void
  setActiveArtefact: (detail: ArtefactDetail | null) => void
  setActiveArtefactLoading: (loading: boolean) => void
  reset: () => void
}

const INITIAL_STATE = {
  artefacts: [] as ArtefactSummary[],
  sidebarOpen: false,
  activeArtefact: null as ArtefactDetail | null,
  activeArtefactLoading: false,
}

export const useArtefactStore = create<ArtefactState>((set) => ({
  ...INITIAL_STATE,

  setArtefacts: (artefacts) => set({ artefacts }),
  addArtefact: (artefact) =>
    set((s) => ({ artefacts: [...s.artefacts, artefact] })),
  updateArtefact: (handle, updates) =>
    set((s) => ({
      artefacts: s.artefacts.map((a) =>
        a.handle === handle ? { ...a, ...updates } : a,
      ),
    })),
  removeArtefact: (handle) =>
    set((s) => ({
      artefacts: s.artefacts.filter((a) => a.handle !== handle),
      activeArtefact:
        s.activeArtefact?.handle === handle ? null : s.activeArtefact,
    })),
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  openOverlay: (detail) => set({ activeArtefact: detail, activeArtefactLoading: false }),
  closeOverlay: () => set({ activeArtefact: null }),
  setActiveArtefact: (detail) => set({ activeArtefact: detail }),
  setActiveArtefactLoading: (loading) => set({ activeArtefactLoading: loading }),
  reset: () => set(INITIAL_STATE),
}))

// Project-Detail-Overlay open-state — a tiny Zustand store so the
// sidebar, the in-chat ProjectSwitcher, and the UserModal Projects
// tab can all open the same overlay without lifting state through
// half a dozen prop chains.
//
// Mirrors the pattern used by ``drawerStore`` and other tiny pieces
// of UI state. The actual mounting still happens in AppLayout —
// this file only owns "is it open, and for which project / tab".

import { create } from 'zustand'
import type { ProjectDetailTab } from './ProjectDetailOverlay'

interface ProjectOverlayState {
  projectId: string | null
  tab: ProjectDetailTab
  open: (projectId: string, tab?: ProjectDetailTab) => void
  close: () => void
  setTab: (tab: ProjectDetailTab) => void
}

export const useProjectOverlayStore = create<ProjectOverlayState>((set) => ({
  projectId: null,
  tab: 'overview',
  open: (projectId, tab = 'overview') => set({ projectId, tab }),
  close: () => set({ projectId: null }),
  setTab: (tab) => set({ tab }),
}))

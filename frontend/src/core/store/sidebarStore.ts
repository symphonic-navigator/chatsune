import { create } from 'zustand'

const STORAGE_KEY = 'chatsune_sidebar_collapsed'

interface SidebarState {
  isCollapsed: boolean
  toggle: () => void
}

export const useSidebarStore = create<SidebarState>((set, get) => ({
  isCollapsed: typeof localStorage !== 'undefined' && localStorage.getItem(STORAGE_KEY) === 'true',
  toggle: () => {
    const next = !get().isCollapsed
    if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, String(next))
    set({ isCollapsed: next })
  },
}))

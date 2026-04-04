import { create } from 'zustand'

const STORAGE_KEY = 'chatsune_sidebar_collapsed'

interface SidebarState {
  isCollapsed: boolean
  toggle: () => void
}

export const useSidebarStore = create<SidebarState>((set, get) => ({
  isCollapsed: localStorage.getItem(STORAGE_KEY) === 'true',
  toggle: () => {
    const next = !get().isCollapsed
    localStorage.setItem(STORAGE_KEY, String(next))
    set({ isCollapsed: next })
  },
}))

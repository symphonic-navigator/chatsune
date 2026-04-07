import { create } from 'zustand'
import { safeLocalStorage } from '../utils/safeStorage'

const STORAGE_KEY = 'chatsune_sidebar_collapsed'

interface SidebarState {
  isCollapsed: boolean
  toggle: () => void
}

export const useSidebarStore = create<SidebarState>((set, get) => ({
  isCollapsed: safeLocalStorage.getItem(STORAGE_KEY) === 'true',
  toggle: () => {
    const next = !get().isCollapsed
    safeLocalStorage.setItem(STORAGE_KEY, String(next))
    set({ isCollapsed: next })
  },
}))

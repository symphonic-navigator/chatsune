import { create } from 'zustand'

/**
 * Drawer store for the mobile off-canvas sidebar.
 *
 * Deliberately not persisted: on every fresh load the drawer should start
 * closed. The existing `useSidebarStore` handles the persistent desktop
 * rail/full toggle — this store is a separate concern for the `< lg`
 * off-canvas drawer introduced with the responsive rework.
 */
interface DrawerState {
  sidebarOpen: boolean
  open: () => void
  close: () => void
  toggle: () => void
}

export const useDrawerStore = create<DrawerState>((set, get) => ({
  sidebarOpen: false,
  open: () => set({ sidebarOpen: true }),
  close: () => set({ sidebarOpen: false }),
  toggle: () => set({ sidebarOpen: !get().sidebarOpen }),
}))

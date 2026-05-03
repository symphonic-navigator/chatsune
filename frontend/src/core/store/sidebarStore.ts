import { create } from 'zustand'
import { safeLocalStorage } from '../utils/safeStorage'

const COLLAPSED_KEY = 'chatsune_sidebar_collapsed'
const OPEN_ZONE_KEY = 'chatsune_sidebar_open_zone'

export type SidebarZone = 'personas' | 'projects' | 'history'

const VALID_ZONES: ReadonlyArray<SidebarZone> = ['personas', 'projects', 'history']

function readOpenZone(): SidebarZone | null {
  const raw = safeLocalStorage.getItem(OPEN_ZONE_KEY)
  if (raw === null) return 'personas'
  if (raw === '') return null
  return (VALID_ZONES as ReadonlyArray<string>).includes(raw)
    ? (raw as SidebarZone)
    : 'personas'
}

interface SidebarState {
  isCollapsed: boolean
  /** Accordion: at most one zone open at a time. null = all collapsed. */
  openZone: SidebarZone | null
  toggle: () => void
  setOpenZone: (zone: SidebarZone | null) => void
}

export const useSidebarStore = create<SidebarState>((set, get) => ({
  isCollapsed: safeLocalStorage.getItem(COLLAPSED_KEY) === 'true',
  openZone: readOpenZone(),
  toggle: () => {
    const next = !get().isCollapsed
    safeLocalStorage.setItem(COLLAPSED_KEY, String(next))
    set({ isCollapsed: next })
  },
  setOpenZone: (zone) => {
    safeLocalStorage.setItem(OPEN_ZONE_KEY, zone ?? '')
    set({ openZone: zone })
  },
}))

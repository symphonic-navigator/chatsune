import { create } from 'zustand'
import { safeLocalStorage } from '../utils/safeStorage'

const COLLAPSED_KEY = 'chatsune_sidebar_collapsed'

export type SidebarZone = 'personas' | 'projects' | 'history'

function zoneKey(zone: SidebarZone): string {
  return `chatsune_sidebar_zone_${zone}_open`
}

function readZoneOpen(zone: SidebarZone): boolean {
  const raw = safeLocalStorage.getItem(zoneKey(zone))
  if (raw === null) return true
  return raw === 'true'
}

interface SidebarState {
  isCollapsed: boolean
  zoneOpen: Record<SidebarZone, boolean>
  toggle: () => void
  toggleZone: (zone: SidebarZone) => void
}

export const useSidebarStore = create<SidebarState>((set, get) => ({
  isCollapsed: safeLocalStorage.getItem(COLLAPSED_KEY) === 'true',
  zoneOpen: {
    personas: readZoneOpen('personas'),
    projects: readZoneOpen('projects'),
    history: readZoneOpen('history'),
  },
  toggle: () => {
    const next = !get().isCollapsed
    safeLocalStorage.setItem(COLLAPSED_KEY, String(next))
    set({ isCollapsed: next })
  },
  toggleZone: (zone) => {
    const cur = get().zoneOpen[zone]
    const next = !cur
    safeLocalStorage.setItem(zoneKey(zone), String(next))
    set({ zoneOpen: { ...get().zoneOpen, [zone]: next } })
  },
}))

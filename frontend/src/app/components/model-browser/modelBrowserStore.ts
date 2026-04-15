import { create } from 'zustand'
import { safeLocalStorage } from '../../../core/utils/safeStorage'

const KEY = 'chatsune_model_browser_collapsed'

function load(): Set<string> {
  try {
    return new Set(JSON.parse(safeLocalStorage.getItem(KEY) || '[]') as string[])
  } catch {
    return new Set()
  }
}

function persist(s: Set<string>): void {
  safeLocalStorage.setItem(KEY, JSON.stringify([...s]))
}

interface CollapsedGroupsState {
  collapsed: Set<string>
  toggle: (id: string) => void
}

export const useCollapsedGroups = create<CollapsedGroupsState>((set, get) => ({
  collapsed: load(),
  toggle: (id) => {
    const next = new Set(get().collapsed)
    if (next.has(id)) {
      next.delete(id)
    } else {
      next.add(id)
    }
    persist(next)
    set({ collapsed: next })
  },
}))

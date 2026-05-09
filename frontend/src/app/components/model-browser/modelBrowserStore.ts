import { create } from 'zustand'
import { safeLocalStorage } from '../../../core/utils/safeStorage'

const KEY = 'chatsune_model_browser_collapsed'
const FIRST_CLASS_KEY = 'chatsune_model_browser_first_class_only'

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

function loadFirstClassOnly(): boolean {
  return safeLocalStorage.getItem(FIRST_CLASS_KEY) === 'true'
}

function persistFirstClassOnly(value: boolean): void {
  safeLocalStorage.setItem(FIRST_CLASS_KEY, value ? 'true' : 'false')
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

interface ModelBrowserFiltersState {
  /**
   * When true, only models whose adapter has first-class (curated)
   * capability knowledge are listed. Best-effort/heuristic models are
   * filtered out. Persisted across sessions.
   */
  firstClassOnly: boolean
  setFirstClassOnly: (value: boolean) => void
}

export const useModelBrowserFilters = create<ModelBrowserFiltersState>((set) => ({
  firstClassOnly: loadFirstClassOnly(),
  setFirstClassOnly: (value) => {
    persistFirstClassOnly(value)
    set({ firstClassOnly: value })
  },
}))

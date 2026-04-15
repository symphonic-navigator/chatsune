import { create } from 'zustand'
import { safeLocalStorage } from '../../../core/utils/safeStorage'
import type { TopTabId, SubTabId } from './userModalTree'

const STORAGE_KEY = 'chatsune_user_modal_subtabs'

type SubtabMap = Partial<Record<TopTabId, SubTabId>>

interface UserModalSubtabState {
  lastSub: SubtabMap
  setLastSub: (top: TopTabId, sub: SubTabId) => void
}

function loadFromStorage(): SubtabMap {
  const raw = safeLocalStorage.getItem(STORAGE_KEY)
  if (!raw) return {}
  try {
    return JSON.parse(raw) as SubtabMap
  } catch {
    return {}
  }
}

export const useSubtabStore = create<UserModalSubtabState>((set, get) => ({
  lastSub: loadFromStorage(),
  setLastSub: (top, sub) => {
    const next = { ...get().lastSub, [top]: sub }
    safeLocalStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    set({ lastSub: next })
  },
}))

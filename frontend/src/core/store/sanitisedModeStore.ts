import { create } from 'zustand'
import { safeLocalStorage } from '../utils/safeStorage'

const STORAGE_KEY = 'chatsune_sanitised_mode'

interface SanitisedModeState {
  isSanitised: boolean
  toggle: () => void
}

export const useSanitisedMode = create<SanitisedModeState>((set, get) => ({
  isSanitised: safeLocalStorage.getItem(STORAGE_KEY) === 'true',
  toggle: () => {
    const next = !get().isSanitised
    safeLocalStorage.setItem(STORAGE_KEY, String(next))
    set({ isSanitised: next })
  },
}))

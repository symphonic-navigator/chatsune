import { create } from 'zustand'

const STORAGE_KEY = 'chatsune_sanitised_mode'

interface SanitisedModeState {
  isSanitised: boolean
  toggle: () => void
}

export const useSanitisedMode = create<SanitisedModeState>((set, get) => ({
  isSanitised: typeof localStorage !== 'undefined' && localStorage.getItem(STORAGE_KEY) === 'true',
  toggle: () => {
    const next = !get().isSanitised
    if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, String(next))
    set({ isSanitised: next })
  },
}))

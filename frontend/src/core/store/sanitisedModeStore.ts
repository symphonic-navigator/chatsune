import { create } from 'zustand'

const STORAGE_KEY = 'chatsune_sanitised_mode'

interface SanitisedModeState {
  isSanitised: boolean
  toggle: () => void
}

export const useSanitisedMode = create<SanitisedModeState>((set, get) => ({
  isSanitised: localStorage.getItem(STORAGE_KEY) === 'true',
  toggle: () => {
    const next = !get().isSanitised
    localStorage.setItem(STORAGE_KEY, String(next))
    set({ isSanitised: next })
  },
}))

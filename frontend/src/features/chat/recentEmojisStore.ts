import { create } from 'zustand'

interface RecentEmojisState {
  emojis: string[]
  set: (emojis: string[]) => void
}

export const useRecentEmojisStore = create<RecentEmojisState>((set) => ({
  emojis: [],
  set: (emojis) => set({ emojis }),
}))

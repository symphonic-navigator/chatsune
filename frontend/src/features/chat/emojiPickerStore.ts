import { create } from 'zustand'

interface EmojiPickerState {
  isOpen: boolean
  open: () => void
  close: () => void
  toggle: () => void
}

export const useEmojiPickerStore = create<EmojiPickerState>((set) => ({
  isOpen: false,
  open: () => set({ isOpen: true }),
  close: () => set({ isOpen: false }),
  toggle: () => set((s) => ({ isOpen: !s.isOpen })),
}))

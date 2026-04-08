import { create } from "zustand"

interface ProviderStatusState {
  statuses: Record<string, boolean>
  setStatus: (providerId: string, available: boolean) => void
  setAll: (statuses: Record<string, boolean>) => void
  isAvailable: (providerId: string) => boolean
}

export const useProviderStatusStore = create<ProviderStatusState>((set, get) => ({
  statuses: {},
  setStatus: (providerId, available) =>
    set((state) => ({ statuses: { ...state.statuses, [providerId]: available } })),
  setAll: (statuses) => set({ statuses: { ...statuses } }),
  isAvailable: (providerId) => get().statuses[providerId] ?? false,
}))

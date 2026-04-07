import { create } from "zustand"

export type ConnectionStatus = "disconnected" | "connecting" | "connected" | "reconnecting"

interface EventState {
  status: ConnectionStatus
  lastSequence: string | null
  setStatus: (status: ConnectionStatus) => void
  setLastSequence: (seq: string | null) => void
}

export const useEventStore = create<EventState>((set) => ({
  status: "disconnected",
  lastSequence: null,
  setStatus: (status) => set({ status }),
  setLastSequence: (lastSequence) => set({ lastSequence }),
}))

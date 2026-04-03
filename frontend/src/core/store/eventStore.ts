import { create } from "zustand"

export type ConnectionStatus = "disconnected" | "connecting" | "connected" | "reconnecting"

interface EventState {
  status: ConnectionStatus
  lastSequence: string
  setStatus: (status: ConnectionStatus) => void
  setLastSequence: (seq: string) => void
}

export const useEventStore = create<EventState>((set) => ({
  status: "disconnected",
  lastSequence: "",
  setStatus: (status) => set({ status }),
  setLastSequence: (lastSequence) => set({ lastSequence }),
}))

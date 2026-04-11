import { create } from "zustand"

export type ConnectionStatus = "disconnected" | "connecting" | "connected" | "reconnecting"

const STORAGE_KEY = "chatsune.lastSequence"

function readPersistedSequence(): string | null {
  // Guard against non-browser environments (SSR, tests without jsdom).
  if (typeof window === "undefined" || typeof window.sessionStorage === "undefined") {
    return null
  }
  try {
    return window.sessionStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function writePersistedSequence(value: string | null): void {
  if (typeof window === "undefined" || typeof window.sessionStorage === "undefined") {
    return
  }
  try {
    if (value === null) {
      window.sessionStorage.removeItem(STORAGE_KEY)
    } else {
      window.sessionStorage.setItem(STORAGE_KEY, value)
    }
  } catch {
    // Quota exceeded or storage disabled — degrade silently.
  }
}

interface EventState {
  status: ConnectionStatus
  lastSequence: string | null
  connectionId: string | null
  setStatus: (status: ConnectionStatus) => void
  setLastSequence: (seq: string | null) => void
  setConnectionId: (id: string | null) => void
}

export const useEventStore = create<EventState>((set) => ({
  status: "disconnected",
  lastSequence: readPersistedSequence(),
  connectionId: null,
  setStatus: (status) => set({ status }),
  setLastSequence: (lastSequence) => {
    writePersistedSequence(lastSequence)
    set({ lastSequence })
  },
  setConnectionId: (connectionId) => set({ connectionId }),
}))

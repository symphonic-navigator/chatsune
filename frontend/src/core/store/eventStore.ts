import { create } from "zustand"
import { useAuthStore } from "./authStore"

export type ConnectionStatus = "disconnected" | "connecting" | "connected" | "reconnecting"

const STORAGE_PREFIX = "chatsune:lastSequence:"

/**
 * Resolve the storage key for the currently signed-in user.
 *
 * Returns `null` when no user is known (pre-login, or the auth store has
 * been cleared). In that case the cursor is held in-memory only and is
 * never written to localStorage — that way one user's cursor cannot leak
 * into another user's session on a shared browser profile.
 */
function currentStorageKey(): string | null {
  // Read lazily — authStore and eventStore form a small import cycle and
  // ``useAuthStore`` may still be a partially-initialised binding while
  // authStore's module body is mid-evaluation. Optional chaining the
  // whole call chain (binding AND method) protects against the binding
  // being truthy-but-not-yet-a-store. In that window we have no user,
  // which is exactly the right answer.
  const userId = useAuthStore?.getState?.()?.user?.id
  return userId ? `${STORAGE_PREFIX}${userId}` : null
}

function readPersistedSequence(): string | null {
  if (typeof window === "undefined" || typeof window.localStorage === "undefined") {
    return null
  }
  const key = currentStorageKey()
  if (key === null) return null
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function writePersistedSequence(value: string | null): void {
  if (typeof window === "undefined" || typeof window.localStorage === "undefined") {
    return
  }
  const key = currentStorageKey()
  // No user known yet — keep the cursor in-memory only.
  if (key === null) return
  try {
    if (value === null) {
      window.localStorage.removeItem(key)
    } else {
      window.localStorage.setItem(key, value)
    }
  } catch (err) {
    // Private mode or quota exceeded — log once and degrade to in-memory.
    console.warn("[eventStore] Failed to persist lastSequence to localStorage", err)
  }
}

/**
 * Remove the persisted cursor for the given user. Called from the logout
 * coordinator so that the next sign-in on the same browser starts fresh
 * if it is a different account.
 */
export function clearPersistedSequenceFor(userId: string | null): void {
  if (typeof window === "undefined" || typeof window.localStorage === "undefined") {
    return
  }
  if (!userId) return
  try {
    window.localStorage.removeItem(`${STORAGE_PREFIX}${userId}`)
  } catch {
    // Nothing we can do; the entry will be overwritten on next login.
  }
}

interface EventState {
  status: ConnectionStatus
  lastSequence: string | null
  connectionId: string | null
  /** Whether the backend is reachable. Set to false on network errors. */
  backendAvailable: boolean
  setStatus: (status: ConnectionStatus) => void
  setLastSequence: (seq: string | null) => void
  setConnectionId: (id: string | null) => void
  setBackendAvailable: (available: boolean) => void
}

export const useEventStore = create<EventState>((set) => ({
  status: "disconnected",
  lastSequence: readPersistedSequence(),
  connectionId: null,
  backendAvailable: true,
  setStatus: (status) => set({ status }),
  setLastSequence: (lastSequence) => {
    writePersistedSequence(lastSequence)
    set({ lastSequence })
  },
  setConnectionId: (connectionId) => set({ connectionId }),
  setBackendAvailable: (backendAvailable) => set({ backendAvailable }),
}))

// Rehydrate the cursor when the signed-in user changes (login, account
// switch). Without this, the store seeded with `null` at module load
// would defeat catchup for a fresh tab even though the cursor exists in
// localStorage. Skip on logout — clearing is the coordinator's job.
//
// authStore and this module form a small import cycle, so a static
// reference to ``useAuthStore`` may still be the temporal-dead-zone
// ``undefined`` while we are at the bottom of our own module body.
// Retry on the microtask queue, but cap the retries so a genuinely
// missing binding cannot cause a busy-wait loop (the previous bug).
function attachAuthListener(remainingTries: number = 5): void {
  if (typeof useAuthStore === "undefined" || !useAuthStore?.subscribe) {
    if (remainingTries > 0) {
      // setTimeout(0) lets the entire ESM cycle complete (including the
      // remainder of the authStore module body) before we retry — a
      // queueMicrotask race can still see ``useAuthStore`` undefined if
      // the binding update happens after the microtask is drained.
      setTimeout(() => attachAuthListener(remainingTries - 1), 0)
    } else {
      console.warn(
        "[eventStore] could not attach auth listener — rehydration disabled",
      )
    }
    return
  }
  useAuthStore.subscribe((state, prev) => {
    const nextId = state.user?.id ?? null
    const prevId = prev.user?.id ?? null
    if (nextId === prevId) return
    if (nextId === null) return
    const persisted = readPersistedSequence()
    if (persisted !== null) {
      useEventStore.setState({ lastSequence: persisted })
    }
  })
}
attachAuthListener()

import { beforeEach, describe, expect, it, vi } from "vitest"
import type { UserDto } from "../types/auth"

const USER_A: UserDto = {
  id: "user-a",
  username: "a",
  email: "a@example.com",
  display_name: "A",
  role: "user",
  is_active: true,
  must_change_password: false,
  created_at: "",
  updated_at: "",
  recent_emojis: [],
}

const USER_B: UserDto = { ...USER_A, id: "user-b", username: "b" }

const KEY_A = "chatsune:lastSequence:user-a"
const KEY_B = "chatsune:lastSequence:user-b"

describe("eventStore lastSequence persistence (per-user)", () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    // resetModules() in setup.ts handles fresh imports between tests.
  })

  it("writes lastSequence under the signed-in user's localStorage key", async () => {
    vi.resetModules()
    const { useAuthStore } = await import("./authStore")
    const { useEventStore } = await import("./eventStore")
    useAuthStore.setState({ user: USER_A, isAuthenticated: true })

    useEventStore.getState().setLastSequence("42")

    expect(localStorage.getItem(KEY_A)).toBe("42")
    expect(localStorage.getItem(KEY_B)).toBeNull()
  })

  it("keeps cursors independent across users", async () => {
    vi.resetModules()
    const { useAuthStore } = await import("./authStore")
    const { useEventStore } = await import("./eventStore")

    useAuthStore.setState({ user: USER_A, isAuthenticated: true })
    useEventStore.getState().setLastSequence("100")

    useAuthStore.setState({ user: USER_B, isAuthenticated: true })
    useEventStore.getState().setLastSequence("7")

    expect(localStorage.getItem(KEY_A)).toBe("100")
    expect(localStorage.getItem(KEY_B)).toBe("7")
  })

  it("rehydrates lastSequence when a user signs in", async () => {
    localStorage.setItem(KEY_A, "55")
    vi.resetModules()
    const { useAuthStore } = await import("./authStore")
    const { useEventStore } = await import("./eventStore")

    // ``attachAuthListener`` uses a ``setTimeout(0)`` retry loop to
    // bridge the TDZ window of the eventStore <-> authStore import
    // cycle. We need at least one task tick before the subscriber is
    // attached. Two ticks is paranoia-safe across vitest workers.
    await new Promise((resolve) => setTimeout(resolve, 0))
    await new Promise((resolve) => setTimeout(resolve, 0))

    // Pre-login: no user, so store seeds with null.
    expect(useEventStore.getState().lastSequence).toBeNull()

    useAuthStore.setState({ user: USER_A, isAuthenticated: true })

    expect(useEventStore.getState().lastSequence).toBe("55")
  })

  it("does not write to localStorage when no user is known", async () => {
    vi.resetModules()
    const { useEventStore } = await import("./eventStore")

    useEventStore.getState().setLastSequence("9")

    expect(localStorage.getItem(KEY_A)).toBeNull()
    // In-memory value is still tracked.
    expect(useEventStore.getState().lastSequence).toBe("9")
  })

  it("clears the persisted entry for a given user", async () => {
    localStorage.setItem(KEY_A, "200")
    vi.resetModules()
    const { clearPersistedSequenceFor } = await import("./eventStore")

    clearPersistedSequenceFor("user-a")

    expect(localStorage.getItem(KEY_A)).toBeNull()
  })
})

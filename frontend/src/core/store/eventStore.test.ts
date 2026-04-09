import { beforeEach, describe, expect, it } from "vitest"
import { useEventStore } from "./eventStore"

describe("eventStore lastSequence persistence", () => {
  beforeEach(() => {
    sessionStorage.clear()
    useEventStore.setState({ lastSequence: null, status: "disconnected" })
  })

  it("writes lastSequence to sessionStorage on update", () => {
    useEventStore.getState().setLastSequence("42")
    expect(sessionStorage.getItem("chatsune.lastSequence")).toBe("42")
  })

  it("clears sessionStorage when lastSequence is reset to null", () => {
    useEventStore.getState().setLastSequence("42")
    useEventStore.getState().setLastSequence(null)
    expect(sessionStorage.getItem("chatsune.lastSequence")).toBeNull()
  })

  it("seeds lastSequence from sessionStorage on store hydration", async () => {
    sessionStorage.setItem("chatsune.lastSequence", "99")
    // Re-import the store module to trigger fresh hydration.
    const mod = await import("./eventStore?t=" + Date.now())
    expect(mod.useEventStore.getState().lastSequence).toBe("99")
  })
})

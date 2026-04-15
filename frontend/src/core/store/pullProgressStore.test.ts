import { beforeEach, describe, expect, it } from "vitest"
import { usePullProgressStore } from "./pullProgressStore"
import type { BaseEvent } from "../types/events"

function reset() {
  usePullProgressStore.setState({ byScope: {} })
}

function makeEvent(
  type: string,
  payload: Record<string, unknown>,
): BaseEvent {
  return {
    id: "ev-x",
    type,
    sequence: "1",
    scope: "global",
    correlation_id: "corr",
    timestamp: new Date().toISOString(),
    payload,
  }
}

describe("pullProgressStore", () => {
  beforeEach(reset)

  it("inserts entry on llm.model.pull.started", () => {
    usePullProgressStore.getState().handleEvent(
      makeEvent("llm.model.pull.started", {
        pull_id: "p1",
        scope: "admin-local",
        slug: "llama3.2",
        timestamp: "2026-04-15T00:00:00Z",
      }),
    )
    const entries = usePullProgressStore.getState().byScope["admin-local"]
    expect(entries?.["p1"]?.slug).toBe("llama3.2")
    expect(entries?.["p1"]?.status).toBe("")
  })

  it("merges progress into existing entry", () => {
    const s = usePullProgressStore.getState()
    s.handleEvent(makeEvent("llm.model.pull.started", {
      pull_id: "p1", scope: "admin-local", slug: "x", timestamp: "t",
    }))
    s.handleEvent(makeEvent("llm.model.pull.progress", {
      pull_id: "p1", scope: "admin-local", status: "downloading",
      digest: "sha256:a", completed: 50, total: 100, timestamp: "t",
    }))
    const e = usePullProgressStore.getState().byScope["admin-local"]?.["p1"]
    expect(e?.status).toBe("downloading")
    expect(e?.completed).toBe(50)
    expect(e?.total).toBe(100)
  })

  it("ignores progress for unknown pull", () => {
    usePullProgressStore.getState().handleEvent(
      makeEvent("llm.model.pull.progress", {
        pull_id: "ghost", scope: "admin-local", status: "downloading",
        digest: null, completed: 1, total: 100, timestamp: "t",
      }),
    )
    expect(usePullProgressStore.getState().byScope).toEqual({})
  })

  it("removes entry on completed / failed / cancelled", () => {
    for (const type of [
      "llm.model.pull.completed",
      "llm.model.pull.failed",
      "llm.model.pull.cancelled",
    ]) {
      reset()
      const s = usePullProgressStore.getState()
      s.handleEvent(makeEvent("llm.model.pull.started", {
        pull_id: "p1", scope: "admin-local", slug: "x", timestamp: "t",
      }))
      const failedPayload = type === "llm.model.pull.failed"
        ? {
            pull_id: "p1", scope: "admin-local", slug: "x",
            error_code: "unknown", user_message: "boom", timestamp: "t",
          }
        : { pull_id: "p1", scope: "admin-local", slug: "x", timestamp: "t" }
      s.handleEvent(makeEvent(type, failedPayload))
      expect(
        usePullProgressStore.getState().byScope["admin-local"]?.["p1"],
      ).toBeUndefined()
    }
  })

  it("ignores unrelated topics", () => {
    usePullProgressStore.getState().handleEvent(
      makeEvent("job.started", { job_id: "j", job_type: "memory_extraction" }),
    )
    expect(usePullProgressStore.getState().byScope).toEqual({})
  })

  it("hydrateFromList replaces entries for the scope only", () => {
    const s = usePullProgressStore.getState()
    s.handleEvent(makeEvent("llm.model.pull.started", {
      pull_id: "p1", scope: "connection:c1", slug: "a", timestamp: "t",
    }))
    s.hydrateFromList("admin-local", [
      { pull_id: "p2", slug: "b", status: "downloading",
        started_at: "2026-04-15T00:00:00Z" },
    ])
    const state = usePullProgressStore.getState()
    // admin-local has been hydrated
    expect(state.byScope["admin-local"]?.["p2"]?.slug).toBe("b")
    // connection:c1 still there (hydrate is scope-local)
    expect(state.byScope["connection:c1"]?.["p1"]?.slug).toBe("a")
  })
})

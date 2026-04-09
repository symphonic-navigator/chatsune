import { beforeEach, describe, expect, it } from "vitest"
import { useJobStore } from "./jobStore"

function reset() {
  useJobStore.setState({ jobs: {} })
}

function startedEvent(overrides: Record<string, unknown> = {}) {
  return {
    id: "ev-1",
    type: "job.started",
    sequence: "1",
    scope: "user:u",
    correlation_id: "corr-1",
    timestamp: new Date().toISOString(),
    payload: {
      job_id: "job-1",
      job_type: "memory_extraction",
      notify: true,
      persona_id: "persona-1",
      correlation_id: "corr-1",
      timestamp: new Date().toISOString(),
      ...overrides,
    },
  }
}

function retryEvent(overrides: Record<string, unknown> = {}) {
  return {
    id: "ev-2",
    type: "job.retry",
    sequence: "2",
    scope: "user:u",
    correlation_id: "corr-1",
    timestamp: new Date().toISOString(),
    payload: {
      job_id: "job-1",
      job_type: "memory_extraction",
      attempt: 1,
      next_retry_at: new Date().toISOString(),
      notify: true,
      correlation_id: "corr-1",
      timestamp: new Date().toISOString(),
      ...overrides,
    },
  }
}

function doneEvent(type: string, jobId = "job-1") {
  return {
    id: "ev-done",
    type,
    sequence: "3",
    scope: "user:u",
    correlation_id: "corr-1",
    timestamp: new Date().toISOString(),
    payload: {
      job_id: jobId,
      job_type: "memory_extraction",
      correlation_id: "corr-1",
      timestamp: new Date().toISOString(),
    },
  }
}

describe("jobStore", () => {
  beforeEach(reset)

  it("adds a running job on job.started with notify=true", () => {
    useJobStore.getState().handleEvent(startedEvent())
    const jobs = useJobStore.getState().visibleJobs()
    expect(jobs).toHaveLength(1)
    expect(jobs[0].jobId).toBe("job-1")
    expect(jobs[0].jobType).toBe("memory_extraction")
    expect(jobs[0].personaId).toBe("persona-1")
    expect(jobs[0].attempt).toBe(0)
  })

  it("ignores job.started with notify=false", () => {
    useJobStore.getState().handleEvent(startedEvent({ notify: false }))
    expect(useJobStore.getState().visibleJobs()).toHaveLength(0)
  })

  it("handles missing persona_id as null", () => {
    useJobStore.getState().handleEvent(startedEvent({ persona_id: null }))
    const jobs = useJobStore.getState().visibleJobs()
    expect(jobs).toHaveLength(1)
    expect(jobs[0].personaId).toBeNull()
  })

  it("increments attempt on job.retry for a known job", () => {
    useJobStore.getState().handleEvent(startedEvent())
    useJobStore.getState().handleEvent(retryEvent({ attempt: 2 }))
    const jobs = useJobStore.getState().visibleJobs()
    expect(jobs[0].attempt).toBe(2)
  })

  it("creates an entry on job.retry for an unknown job", () => {
    useJobStore.getState().handleEvent(retryEvent({ attempt: 1 }))
    const jobs = useJobStore.getState().visibleJobs()
    expect(jobs).toHaveLength(1)
    expect(jobs[0].attempt).toBe(1)
  })

  it("ignores job.retry with notify=false", () => {
    useJobStore.getState().handleEvent(retryEvent({ notify: false }))
    expect(useJobStore.getState().visibleJobs()).toHaveLength(0)
  })

  it("removes the entry on job.completed", () => {
    useJobStore.getState().handleEvent(startedEvent())
    useJobStore.getState().handleEvent(doneEvent("job.completed"))
    expect(useJobStore.getState().visibleJobs()).toHaveLength(0)
  })

  it("removes the entry on job.failed", () => {
    useJobStore.getState().handleEvent(startedEvent())
    useJobStore.getState().handleEvent(doneEvent("job.failed"))
    expect(useJobStore.getState().visibleJobs()).toHaveLength(0)
  })

  it("removes the entry on job.expired", () => {
    useJobStore.getState().handleEvent(startedEvent())
    useJobStore.getState().handleEvent(doneEvent("job.expired"))
    expect(useJobStore.getState().visibleJobs()).toHaveLength(0)
  })

  it("keeps multiple concurrent jobs independent", () => {
    useJobStore.getState().handleEvent(startedEvent({ job_id: "job-a" }))
    useJobStore.getState().handleEvent(startedEvent({ job_id: "job-b" }))
    expect(useJobStore.getState().visibleJobs()).toHaveLength(2)
    useJobStore.getState().handleEvent(doneEvent("job.completed", "job-a"))
    const jobs = useJobStore.getState().visibleJobs()
    expect(jobs).toHaveLength(1)
    expect(jobs[0].jobId).toBe("job-b")
  })

  it("sorts visible jobs by startedAt ascending", async () => {
    useJobStore.getState().handleEvent(startedEvent({ job_id: "job-old" }))
    // Nudge clock forward to guarantee a distinct startedAt.
    await new Promise((r) => setTimeout(r, 5))
    useJobStore.getState().handleEvent(startedEvent({ job_id: "job-new" }))
    const jobs = useJobStore.getState().visibleJobs()
    expect(jobs.map((j) => j.jobId)).toEqual(["job-old", "job-new"])
  })
})

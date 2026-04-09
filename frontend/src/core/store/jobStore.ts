import { create } from "zustand"
import type { BaseEvent } from "../types/events"

export interface RunningJob {
  jobId: string
  jobType: string
  personaId: string | null
  startedAt: number
  attempt: number
}

interface JobState {
  jobs: Record<string, RunningJob>
  visibleJobs: () => RunningJob[]
  handleEvent: (event: BaseEvent) => void
}

type StartedPayload = {
  job_id: string
  job_type: string
  notify?: boolean
  persona_id?: string | null
}

type RetryPayload = {
  job_id: string
  job_type: string
  attempt: number
  notify?: boolean
}

type DonePayload = {
  job_id: string
}

function handleStarted(
  jobs: Record<string, RunningJob>,
  payload: StartedPayload,
): Record<string, RunningJob> {
  if (payload.notify === false) return jobs
  return {
    ...jobs,
    [payload.job_id]: {
      jobId: payload.job_id,
      jobType: payload.job_type,
      personaId: payload.persona_id ?? null,
      startedAt: Date.now(),
      attempt: 0,
    },
  }
}

function handleRetry(
  jobs: Record<string, RunningJob>,
  payload: RetryPayload,
): Record<string, RunningJob> {
  if (payload.notify === false) return jobs
  const existing = jobs[payload.job_id]
  if (existing) {
    return {
      ...jobs,
      [payload.job_id]: { ...existing, attempt: payload.attempt },
    }
  }
  // Unknown job (reconnect mid-retry): create an entry starting now.
  return {
    ...jobs,
    [payload.job_id]: {
      jobId: payload.job_id,
      jobType: payload.job_type,
      personaId: null,
      startedAt: Date.now(),
      attempt: payload.attempt,
    },
  }
}

function handleDone(
  jobs: Record<string, RunningJob>,
  payload: DonePayload,
): Record<string, RunningJob> {
  if (!jobs[payload.job_id]) return jobs
  const next = { ...jobs }
  delete next[payload.job_id]
  return next
}

export const useJobStore = create<JobState>((set, get) => ({
  jobs: {},
  visibleJobs: () =>
    Object.values(get().jobs).sort((a, b) => a.startedAt - b.startedAt),
  handleEvent: (event) => {
    switch (event.type) {
      case "job.started":
        set({ jobs: handleStarted(get().jobs, event.payload as StartedPayload) })
        return
      case "job.retry":
        set({ jobs: handleRetry(get().jobs, event.payload as RetryPayload) })
        return
      case "job.completed":
      case "job.failed":
      case "job.expired":
        set({ jobs: handleDone(get().jobs, event.payload as DonePayload) })
        return
      default:
        return
    }
  },
}))

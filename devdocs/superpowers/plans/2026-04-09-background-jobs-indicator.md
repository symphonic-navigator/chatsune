# Background Jobs Topbar Indicator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a pill in the topbar with a spinner and count whenever the user has `memory_extraction` or `memory_consolidation` jobs running, with a click-to-open popover listing job type, persona, attempt and elapsed time.

**Architecture:** Extend `JobStartedEvent` and `JobRetryEvent` with optional `notify` and (for started) `persona_id` fields. Add a frontend `jobStore` that consumes `job.*` events and is filtered via `notify`. Persist `eventStore.lastSequence` to `sessionStorage` so the existing Redis-Streams replay mechanism survives page reloads. New `JobsPill` component lives in the topbar's right-hand pill row.

**Tech Stack:** Pydantic v2, FastAPI, pytest (backend). Zustand, React, Vitest, Tailwind (frontend).

Spec: `docs/superpowers/specs/2026-04-09-background-jobs-indicator-design.md`.

---

## Task 1: Extend event DTOs

Add optional `notify` and `persona_id` fields to the job lifecycle events so the frontend can filter out low-signal jobs (title generation) and enrich the popover with persona context.

**Files:**
- Modify: `shared/events/jobs.py`
- Test: `tests/test_job_events.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_job_events.py`:

```python
from datetime import datetime, timezone

from shared.events.jobs import JobStartedEvent, JobRetryEvent


def test_job_started_event_has_notify_and_persona_id_defaults():
    """New optional fields default to backwards-compatible values."""
    ev = JobStartedEvent(
        job_id="job-1",
        job_type="memory_extraction",
        correlation_id="corr-1",
        timestamp=datetime.now(timezone.utc),
    )
    assert ev.notify is True
    assert ev.persona_id is None


def test_job_started_event_accepts_notify_and_persona_id():
    ev = JobStartedEvent(
        job_id="job-1",
        job_type="memory_extraction",
        correlation_id="corr-1",
        timestamp=datetime.now(timezone.utc),
        notify=False,
        persona_id="persona-42",
    )
    assert ev.notify is False
    assert ev.persona_id == "persona-42"


def test_job_retry_event_has_notify_default():
    ev = JobRetryEvent(
        job_id="job-1",
        job_type="memory_extraction",
        correlation_id="corr-1",
        attempt=1,
        next_retry_at=datetime.now(timezone.utc),
        timestamp=datetime.now(timezone.utc),
    )
    assert ev.notify is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_job_events.py -v
```

Expected: FAIL with `AttributeError: 'JobStartedEvent' object has no attribute 'notify'` (or equivalent Pydantic validation error).

- [ ] **Step 3: Add fields to the DTOs**

Edit `shared/events/jobs.py`:

```python
class JobStartedEvent(BaseModel):
    type: str = "job.started"
    job_id: str
    job_type: str
    correlation_id: str
    timestamp: datetime
    notify: bool = True
    persona_id: str | None = None
```

And:

```python
class JobRetryEvent(BaseModel):
    type: str = "job.retry"
    job_id: str
    job_type: str
    correlation_id: str
    attempt: int
    next_retry_at: datetime
    timestamp: datetime
    notify: bool = True
```

Do NOT change `JobCompletedEvent`, `JobFailedEvent`, `JobExpiredEvent` — the frontend does not filter terminal events on `notify` (see design spec §3).

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_job_events.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add shared/events/jobs.py tests/test_job_events.py
git commit -m "Add notify and persona_id fields to job lifecycle events"
```

---

## Task 2: Populate new fields in the consumer

Hook `notify` (from `JobConfig`) and `persona_id` (from the job payload) into the consumer's `JOB_STARTED` and `JOB_RETRY` publish sites.

**Files:**
- Modify: `backend/jobs/_consumer.py` (around lines 188-198 and 301-313)
- Test: `tests/test_job_consumer.py` (add new test functions)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_job_consumer.py`:

```python
async def test_job_started_event_carries_notify_and_persona_id(redis):
    """JOB_STARTED publish must include notify from config and persona_id from payload."""
    from backend.jobs._consumer import ensure_consumer_group, process_one
    from backend.jobs._models import JobConfig, JobType
    from backend.jobs._registry import JOB_REGISTRY

    captured: list = []

    class CapturingBus:
        async def publish(self, topic, event, **kwargs):
            captured.append((topic, event))

    handler = AsyncMock()
    original = JOB_REGISTRY[JobType.MEMORY_EXTRACTION]
    JOB_REGISTRY[JobType.MEMORY_EXTRACTION] = JobConfig(
        handler=handler,
        max_retries=original.max_retries,
        retry_delay_seconds=original.retry_delay_seconds,
        queue_timeout_seconds=original.queue_timeout_seconds,
        execution_timeout_seconds=original.execution_timeout_seconds,
        reasoning_enabled=original.reasoning_enabled,
        notify=original.notify,
        notify_error=original.notify_error,
    )
    try:
        await _enqueue_job(
            redis,
            job_type="memory_extraction",
            payload={"persona_id": "persona-42", "session_id": "sess-1"},
        )
        await ensure_consumer_group(redis)
        await process_one(redis, CapturingBus())

        started = [ev for topic, ev in captured if topic == "job.started"]
        assert len(started) == 1
        assert started[0].notify is original.notify
        assert started[0].persona_id == "persona-42"
    finally:
        JOB_REGISTRY[JobType.MEMORY_EXTRACTION] = original


async def test_job_started_event_notify_false_for_title_generation(redis):
    """Title generation has notify=False; the emitted event must reflect that."""
    from backend.jobs._consumer import ensure_consumer_group, process_one
    from backend.jobs._models import JobType
    from backend.jobs._registry import JOB_REGISTRY

    captured: list = []

    class CapturingBus:
        async def publish(self, topic, event, **kwargs):
            captured.append((topic, event))

    # JOB_REGISTRY[TITLE_GENERATION] already has notify=False — see _registry.py
    assert JOB_REGISTRY[JobType.TITLE_GENERATION].notify is False

    handler = AsyncMock()
    original = JOB_REGISTRY[JobType.TITLE_GENERATION]
    JOB_REGISTRY[JobType.TITLE_GENERATION] = type(original)(
        handler=handler,
        max_retries=original.max_retries,
        retry_delay_seconds=original.retry_delay_seconds,
        queue_timeout_seconds=original.queue_timeout_seconds,
        execution_timeout_seconds=original.execution_timeout_seconds,
        reasoning_enabled=original.reasoning_enabled,
        notify=original.notify,
        notify_error=original.notify_error,
    )
    try:
        await _enqueue_job(
            redis,
            job_type="title_generation",
            payload={"persona_id": "persona-7", "session_id": "sess-2"},
        )
        await ensure_consumer_group(redis)
        await process_one(redis, CapturingBus())

        started = [ev for topic, ev in captured if topic == "job.started"]
        assert len(started) == 1
        assert started[0].notify is False
        assert started[0].persona_id == "persona-7"
    finally:
        JOB_REGISTRY[JobType.TITLE_GENERATION] = original
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_job_consumer.py::test_job_started_event_carries_notify_and_persona_id tests/test_job_consumer.py::test_job_started_event_notify_false_for_title_generation -v
```

Expected: FAIL — the emitted event will be missing the new fields with non-default values.

- [ ] **Step 3: Update the consumer publish sites**

In `backend/jobs/_consumer.py`, find the `JobStartedEvent` construction inside the `async with lock:` block (around line 188) and update it:

```python
await event_bus.publish(
    Topics.JOB_STARTED,
    JobStartedEvent(
        job_id=job.id,
        job_type=job.job_type,
        correlation_id=job.correlation_id,
        timestamp=now,
        notify=config.notify,
        persona_id=job.payload.get("persona_id"),
    ),
    target_user_ids=[job.user_id],
    correlation_id=job.correlation_id,
)
```

Then find the `JobRetryEvent` construction in the retry branch (around line 301) and update it:

```python
await event_bus.publish(
    Topics.JOB_RETRY,
    JobRetryEvent(
        job_id=job.id,
        job_type=job.job_type,
        correlation_id=job.correlation_id,
        attempt=attempt,
        next_retry_at=next_retry_at,
        timestamp=now,
        notify=config.notify,
    ),
    target_user_ids=[job.user_id],
    correlation_id=job.correlation_id,
)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_job_consumer.py -v
```

Expected: all consumer tests pass (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add backend/jobs/_consumer.py tests/test_job_consumer.py
git commit -m "Populate notify and persona_id in job lifecycle events"
```

---

## Task 3: Persist `lastSequence` across reloads

Persist `eventStore.lastSequence` to `sessionStorage` so the WebSocket handshake after F5 resumes from where the old tab left off. This is the "R2 serendipity" from the spec — the jobs pill benefits, and so does every other event-driven view.

**Files:**
- Modify: `frontend/src/core/store/eventStore.ts`
- Test: `frontend/src/core/store/eventStore.test.ts` (new)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/core/store/eventStore.test.ts`:

```ts
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && pnpm vitest run src/core/store/eventStore.test.ts
```

Expected: first two tests FAIL (nothing writes to `sessionStorage`), third test FAIL (store initial value is `null`).

- [ ] **Step 3: Update the store**

Replace the contents of `frontend/src/core/store/eventStore.ts`:

```ts
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
  setStatus: (status: ConnectionStatus) => void
  setLastSequence: (seq: string | null) => void
}

export const useEventStore = create<EventState>((set) => ({
  status: "disconnected",
  lastSequence: readPersistedSequence(),
  setStatus: (status) => set({ status }),
  setLastSequence: (lastSequence) => {
    writePersistedSequence(lastSequence)
    set({ lastSequence })
  },
}))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd frontend && pnpm vitest run src/core/store/eventStore.test.ts
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/store/eventStore.ts frontend/src/core/store/eventStore.test.ts
git commit -m "Persist lastSequence to sessionStorage for replay across reloads"
```

---

## Task 4: Create the `jobStore`

Zustand store that holds running jobs keyed by `jobId`, with event handlers that filter on `notify` and track retry attempts.

**Files:**
- Create: `frontend/src/core/store/jobStore.ts`
- Test: `frontend/src/core/store/jobStore.test.ts` (new)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/core/store/jobStore.test.ts`:

```ts
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && pnpm vitest run src/core/store/jobStore.test.ts
```

Expected: FAIL — `jobStore` does not exist yet.

- [ ] **Step 3: Implement the store**

Create `frontend/src/core/store/jobStore.ts`:

```ts
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd frontend && pnpm vitest run src/core/store/jobStore.test.ts
```

Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/store/jobStore.ts frontend/src/core/store/jobStore.test.ts
git commit -m "Add jobStore tracking running background jobs"
```

---

## Task 5: Wire `jobStore` into the event bus

Create a `useJobEvents` hook that subscribes to `job.*` and dispatches into `jobStore`, and mount it in `AppLayout` alongside the other event hooks.

**Files:**
- Create: `frontend/src/features/jobs/useJobEvents.ts`
- Modify: `frontend/src/app/layouts/AppLayout.tsx`

- [ ] **Step 1: Create the hook**

Create `frontend/src/features/jobs/useJobEvents.ts`:

```ts
import { useEffect } from "react"
import { eventBus } from "../../core/websocket/eventBus"
import { useJobStore } from "../../core/store/jobStore"

/**
 * Subscribes the job store to the 'job.*' event stream. Mount exactly
 * once at the top of the authenticated tree (e.g. AppLayout), not per
 * view — otherwise events would be dispatched multiple times.
 */
export function useJobEvents() {
  useEffect(() => {
    const handler = useJobStore.getState().handleEvent
    const unsub = eventBus.on("job.*", handler)
    return () => {
      unsub()
    }
  }, [])
}
```

- [ ] **Step 2: Mount the hook in `AppLayout`**

Edit `frontend/src/app/layouts/AppLayout.tsx`:

```tsx
// Add next to the existing import for useKnowledgeEvents (line 6):
import { useJobEvents } from "../../features/jobs/useJobEvents"
```

And in the component body, next to `useKnowledgeEvents()` (line 25):

```tsx
  useKnowledgeEvents()
  useJobEvents()
```

- [ ] **Step 3: Smoke-test the wiring**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: clean build, no type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/jobs/useJobEvents.ts frontend/src/app/layouts/AppLayout.tsx
git commit -m "Wire jobStore into the event bus via useJobEvents hook"
```

---

## Task 6: Build the `JobsPill` component

Visual pill + click-to-open popover with per-job rows, persona lookup, attempt badge, and an elapsed-time ticker that runs only while the popover is open.

**Files:**
- Create: `frontend/src/app/components/topbar/JobsPill.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/app/components/topbar/JobsPill.tsx`:

```tsx
import { useEffect, useRef, useState } from "react"
import { useJobStore, type RunningJob } from "../../../core/store/jobStore"
import { usePersonaStore } from "../../../core/store/personaStore"

const JOB_TYPE_LABELS: Record<string, string> = {
  memory_extraction: "Memory extraction",
  memory_consolidation: "Memory consolidation",
}

function labelFor(jobType: string): string {
  return JOB_TYPE_LABELS[jobType] ?? jobType
}

function formatElapsed(startedAt: number, now: number): string {
  const seconds = Math.max(0, Math.floor((now - startedAt) / 1000))
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${s.toString().padStart(2, "0")}`
}

function Spinner() {
  return (
    <span
      aria-hidden
      className="inline-block h-2 w-2 rounded-full border border-white/40 border-t-transparent animate-spin"
    />
  )
}

interface JobRowProps {
  job: RunningJob
  now: number
  personaName: string | null
}

function JobRow({ job, now, personaName }: JobRowProps) {
  const parts: string[] = []
  if (personaName) parts.push(personaName)
  parts.push(formatElapsed(job.startedAt, now))
  if (job.attempt > 0) parts.push(`retry ${job.attempt}`)

  return (
    <div className="flex flex-col gap-0.5 px-3 py-2">
      <div className="flex items-center gap-2 text-[12px] text-white/80">
        <Spinner />
        <span>{labelFor(job.jobType)}</span>
      </div>
      <div className="pl-4 text-[11px] font-mono text-white/40">
        {parts.join(" · ")}
      </div>
    </div>
  )
}

export function JobsPill() {
  const jobs = useJobStore((s) => Object.values(s.jobs))
  const personas = usePersonaStore((s) => s.personas)
  const [isOpen, setIsOpen] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const containerRef = useRef<HTMLDivElement>(null)

  const sorted = [...jobs].sort((a, b) => a.startedAt - b.startedAt)
  const count = sorted.length

  // Close the popover automatically when the last job finishes.
  useEffect(() => {
    if (count === 0 && isOpen) setIsOpen(false)
  }, [count, isOpen])

  // Tick once per second only while the popover is open.
  useEffect(() => {
    if (!isOpen) return
    setNow(Date.now())
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [isOpen])

  // Click-outside closes the popover.
  useEffect(() => {
    if (!isOpen) return
    const handleClick = (e: MouseEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsOpen(false)
    }
    document.addEventListener("mousedown", handleClick)
    document.addEventListener("keydown", handleEscape)
    return () => {
      document.removeEventListener("mousedown", handleClick)
      document.removeEventListener("keydown", handleEscape)
    }
  }, [isOpen])

  if (count === 0) return null

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setIsOpen((v) => !v)}
        title={`${count} background job${count === 1 ? "" : "s"} running`}
        className="flex items-center gap-1.5 rounded-full border border-white/8 bg-white/4 px-2.5 py-0.5 font-mono text-[11px] text-white/55 transition-colors hover:bg-white/7"
      >
        <Spinner />
        <span>{count}</span>
      </button>

      {isOpen && (
        <div
          className="absolute right-0 top-full mt-2 z-50 w-[280px] overflow-hidden rounded-xl border border-white/8 bg-surface shadow-2xl"
        >
          <div className="divide-y divide-white/5">
            {sorted.map((job) => (
              <JobRow
                key={job.jobId}
                job={job}
                now={now}
                personaName={
                  job.personaId
                    ? personas.find((p) => p.id === job.personaId)?.name ?? null
                    : null
                }
              />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify the component compiles**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: clean. If `usePersonaStore` path or selector differ, fix the import path (grep for `personaStore` to confirm).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/components/topbar/JobsPill.tsx
git commit -m "Add JobsPill component for running background jobs"
```

---

## Task 7: Render `JobsPill` in the topbar

Add `<JobsPill />` to the right-hand pill row in both render paths of `Topbar.tsx` (chat and non-chat).

**Files:**
- Modify: `frontend/src/app/components/topbar/Topbar.tsx`

- [ ] **Step 1: Import and place the component**

Edit `frontend/src/app/components/topbar/Topbar.tsx`:

Add next to the existing import for `ProviderPill` (line 10):

```tsx
import { JobsPill } from "./JobsPill"
```

In the **chat render path**, find the pill row (around line 139, the `<div className="flex-shrink-0 flex items-center gap-1.5">` block) and insert `<JobsPill />` right before the `<LivePill ... />`:

```tsx
          <ProviderPill provider="ollama_local" label="Local Ollama" />
          <JobsPill />
          <LivePill isLive={isLive} wsStatus={wsStatus} />
```

In the **non-chat render path** (around line 152), do the same:

```tsx
      <div className="ml-auto flex items-center gap-2">
        <ProviderPill provider="ollama_local" label="Local Ollama" />
        <JobsPill />
        <LivePill isLive={isLive} wsStatus={wsStatus} />
      </div>
```

- [ ] **Step 2: Type-check and build**

```bash
cd frontend && pnpm tsc --noEmit && pnpm run build
```

Expected: clean type-check and successful Vite build.

- [ ] **Step 3: Manual E2E check with the backend running**

Start the stack, trigger a memory extraction (e.g. send a chat message and let the idle timer fire, or use the manual extraction endpoint). Verify in the browser:

1. Pill appears in the topbar showing `1` with a spinner.
2. Click opens the popover; row shows job type + persona name + elapsed time.
3. Elapsed time increments once per second while popover is open.
4. Clicking outside or pressing Escape closes the popover.
5. When the job completes/fails/is skipped, the pill disappears.
6. F5 during a running job: after reconnect, the pill reappears (validates Task 3).
7. Trigger a title-generation job: pill does NOT appear (validates `notify=false` filter).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/topbar/Topbar.tsx
git commit -m "Render JobsPill in the topbar next to the live indicator"
```

---

## Task 8: Full test sweep

Run the backend and frontend test suites once to make sure nothing regressed.

- [ ] **Step 1: Backend tests**

```bash
uv run pytest tests/ -q --ignore=tests/memory/test_handlers.py --ignore=tests/test_user_model_config.py
```

Expected: all green (pre-existing failures in `tests/memory/test_handlers.py` and `tests/test_user_model_config.py` are an unrelated setup-fixture issue — see baseline run 2026-04-09).

- [ ] **Step 2: Frontend tests**

```bash
cd frontend && pnpm vitest run
```

Expected: all green.

- [ ] **Step 3: Frontend type-check and build**

```bash
cd frontend && pnpm tsc --noEmit && pnpm run build
```

Expected: clean.

- [ ] **Step 4: Final commit (only if the sweep surfaced any cleanup)**

If nothing needed fixing, skip the commit. Otherwise commit the cleanup with a descriptive message.

---

## Notes for the Implementer

- **Do not** filter `job.completed` / `job.failed` / `job.expired` on `notify`. If a `notify=false` `JOB_STARTED` was emitted but somehow a stale entry ends up in the store, the removal path must still clear it. Removal is always safe.
- **Do not** persist the `jobStore` itself to `sessionStorage`. It is derived state; Redis Streams replay reconstructs it on reconnect after Task 3.
- **Do not** add REST endpoints or new topics. The whole feature rides on existing event plumbing.
- The elapsed timer is intentionally only active while the popover is open. Do not move it into the store — that would re-render every subscriber every second for no reason.
- Title generation failure toasts are a separate concern and not part of this plan.

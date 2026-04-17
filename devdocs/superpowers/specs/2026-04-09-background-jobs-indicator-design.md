# Background Jobs Indicator — Design

**Date:** 2026-04-09
**Status:** Approved, ready for implementation plan

## Goal

Surface currently-running background jobs (memory extraction,
memory consolidation) in the topbar so the user knows at a glance
that something is happening on their behalf. Primary use-case:
Chris's deliberate stress test with an oversized local model, where
a hanging memory extraction is currently only visible in the backend
logs.

## Scope

**In scope:**

- A new `JobsPill` component in the topbar that shows a spinner and
  a running-jobs count, and opens a popover listing the active jobs.
- A new `jobStore` on the frontend that tracks running jobs from the
  `job.*` event stream.
- Two optional fields on `JobStartedEvent` (`notify`, `persona_id`)
  and one on `JobRetryEvent` (`notify`) so the frontend can filter
  correctly and look up the persona.
- Persisting `lastSequence` to `sessionStorage` so the existing
  Redis Streams replay mechanism survives page reloads. This fixes
  the fresh-reload blind spot for the jobs pill and — serendipitously
  — for every other event-driven view in the app.
- A minimal test suite (backend publish check, frontend store unit
  tests). No component tests for the pill itself.

**Explicitly out of scope:**

- Title generation is *not* shown. Its result is visible in the chat
  session title anyway; only its failure case warrants a toast
  (separate concern, handled elsewhere).
- No click-to-cancel, no navigate-on-click. The user cannot do
  anything useful about a running job, so the UI stays read-only.
- No snapshot query at WebSocket handshake. Stream replay plus
  persisted `lastSequence` is enough for realistic scenarios.
- No toast/banner for skipped/failed — already covered by the
  `MemoryExtractionSkippedEvent` work from earlier today (separate
  UI task).

## Architecture

A new Zustand store `jobStore` subscribes to the existing WebSocket
event bus and maintains a `jobId → RunningJob` map. A new
`JobsPill` component reads the store, shows a spinner+count pill
when the list is non-empty, and opens a click-to-toggle popover
with the running jobs.

Backend changes are limited to two event-DTO field additions and
the one publish site in the job consumer that fills them in. No
new endpoints, no new collections, no new topics. Strictly
event-first, per `CLAUDE.md`.

Data flow:

```
Backend job consumer
      │
      ▼  JobStartedEvent { job_id, job_type, notify, persona_id }
WebSocket (existing per-user channel)
      │
      ▼
Frontend eventStore dispatcher
      │
      ▼  (filter: notify === true)
jobStore.jobs[jobId] = RunningJob
      │
      ▼  (selector)
JobsPill → count + spinner
      │
      ▼  (click)
Popover → list with persona name + elapsed timer
```

## Backend Changes

### `shared/events/jobs.py`

Extend `JobStartedEvent` and `JobRetryEvent` with optional fields:

```python
class JobStartedEvent(BaseModel):
    type: str = "job.started"
    job_id: str
    job_type: JobType
    correlation_id: str
    timestamp: datetime
    notify: bool = True                 # NEW
    persona_id: str | None = None       # NEW


class JobRetryEvent(BaseModel):
    # ... existing fields ...
    notify: bool = True                 # NEW
```

Both default to backwards-compatible values so existing tests and
any unknown consumers keep working.

### `backend/jobs/_consumer.py`

At the `Topics.JOB_STARTED` publish site (around `_consumer.py:188`),
pass the two new fields:

```python
JobStartedEvent(
    job_id=job.id,
    job_type=job.job_type,
    correlation_id=job.correlation_id,
    timestamp=now,
    notify=config.notify,
    persona_id=job.payload.get("persona_id"),
)
```

Same at the `Topics.JOB_RETRY` publish site — `notify=config.notify`.

All three current job types (`title_generation`, `memory_extraction`,
`memory_consolidation`) place `persona_id` in their payload, so the
lookup is uniform. Future job types without a persona scope get
`None`, which the frontend renders as "no persona prefix".

## Frontend Changes

### `frontend/src/core/store/jobStore.ts` (new)

```ts
interface RunningJob {
  jobId: string
  jobType: string            // 'memory_extraction' | 'memory_consolidation' | string
  personaId: string | null
  startedAt: number          // Date.now() when JOB_STARTED arrived
  attempt: number            // incremented on JOB_RETRY
}

interface JobState {
  jobs: Record<string, RunningJob>
  visibleJobs: () => RunningJob[]   // sorted by startedAt asc
  // internal handlers wired from eventStore dispatcher:
  _onJobStarted: (event: JobStartedEvent) => void
  _onJobRetry:   (event: JobRetryEvent)   => void
  _onJobDone:    (jobId: string)          => void
}
```

Event handlers:

- **`job.started`** — if `notify === false`: return. Else insert a new
  entry with `attempt: 0`, `startedAt: Date.now()`.
- **`job.retry`** — if `notify === false`: return. Else look up by
  `job_id`: update `attempt` if found; if not found (reconnect edge
  case), insert a fresh entry with `startedAt: Date.now()`.
- **`job.completed`** / **`job.failed`** / **`job.expired`** — delete
  the entry by `job_id`. No filtering on `notify` — removal is always
  safe.

The store must be hooked into the existing `eventStore` dispatch
pipeline (same mechanism as all other event-driven stores in the app).

### `frontend/src/core/store/eventStore.ts`

Persist `lastSequence` to `sessionStorage`:

- On `setLastSequence`, also `sessionStorage.setItem('chatsune.lastSequence', seq)`.
- On store init, seed `lastSequence` from `sessionStorage.getItem('chatsune.lastSequence')`.

`sessionStorage` (not `localStorage`) is correct: it is tab-scoped
and clears on tab close, matching the WebSocket session lifecycle.
This is the "R2 serendipity" — not strictly required by the jobs
pill, but covers reload edge cases for every event consumer.

### `frontend/src/app/components/topbar/JobsPill.tsx` (new)

A small component placed between `ProviderPill` and `LivePill` in
the topbar (`Topbar.tsx`, both render paths — chat and non-chat).

**Closed state (always when `visibleJobs.length > 0`):**

- `rounded-full border border-white/8 bg-white/4 px-2.5 py-0.5 font-mono text-[11px]`
- Animated spinner (simple CSS keyframe, two rotating dots) + the
  count as a number.
- Hover: `bg-white/7`, cursor-pointer.
- Hidden entirely when the list is empty.

**Popover (on click):**

- Positioned below the pill, right-aligned. `w-[280px]`,
  `bg-surface` with `border-white/8`, `rounded-xl`, `shadow-2xl`.
- Follow the existing `KnowledgeDropdown` pattern for positioning
  and click-outside handling.
- One row per job, vertically stacked, thin dividers:

  ```
  ⋯ Memory extraction
    Miri · 0:47

  ⋯ Memory consolidation
    Chris · 2:13
  ```

  - Top line: spinner + human label (mapping table `JOB_TYPE_LABELS`).
  - Bottom line: persona name (from `personaStore`; fallback `—`),
    middle dot, elapsed duration as `m:ss`. If `attempt > 0`,
    append ` · retry ${attempt}` in a dimmer colour.
- No click action on individual rows. Read-only.
- Escape or click-outside closes the popover.
- If the list becomes empty while open (last job finishes), the
  popover closes automatically.

**Elapsed timer:**

- `useEffect` + `setInterval(1000)` while the popover is open.
- Each row computes `(Date.now() - startedAt) / 1000` on every tick.
- Timer is cleaned up on unmount or when the popover closes.
- No ticker when only the pill (not the popover) is rendered — the
  count and spinner are enough, and we avoid needless re-renders.

### `JOB_TYPE_LABELS` mapping

Lives in the JobsPill component file:

```ts
const JOB_TYPE_LABELS: Record<string, string> = {
  memory_extraction: 'Memory extraction',
  memory_consolidation: 'Memory consolidation',
}
```

Unknown types fall back to the raw `job_type` string — new jobs show
up automatically with a debug-ish label until someone adds a nicer
name.

## Edge Cases

- **Unknown `job_type`** — accepted; label falls back to raw string.
- **Missing `persona_id`** — second line shows only elapsed, no
  persona prefix.
- **`persona_id` present but not in `personaStore`** — fallback
  `—`. No on-the-fly fetch.
- **Orphaned entry** (backend crashed, `JOB_COMPLETED` lost) — stays
  in the store until F5 or until a new event with the same `jobId`
  replaces it. No cleanup timer, no TTL. Acceptable.
- **`JOB_RETRY` before `JOB_STARTED`** (reconnect mid-retry) — store
  inserts a fresh entry; elapsed timer starts from reconnect rather
  than original job start. Mild inaccuracy, better than invisibility.
- **Multiple jobs for the same persona** — both shown separately,
  each with its own `jobId`. No deduplication.

## Testing

### Backend (pytest)

Add to the existing job-consumer tests:

- `test_job_started_event_includes_notify_and_persona_id` — publish a
  memory-extraction job, assert the emitted `JobStartedEvent` has
  `notify=True` and the correct `persona_id`.
- `test_job_started_event_notify_false_for_title_gen` — publish a
  title-generation job, assert `notify=False`.
- `test_job_retry_event_includes_notify` — trigger a retry, assert
  the emitted `JobRetryEvent` has `notify` set.

Use the existing fake event bus / in-memory capture helpers in the
test module. No new fixtures.

### Frontend (Vitest)

New test file `frontend/src/core/store/jobStore.test.ts`:

- `job.started` with `notify=true` inserts a `RunningJob`.
- `job.started` with `notify=false` is ignored (store unchanged).
- `job.retry` on a known `jobId` increments `attempt`.
- `job.retry` on an unknown `jobId` inserts a new entry.
- `job.completed` removes the entry.
- `job.failed` removes the entry.
- `job.expired` removes the entry.
- Multiple concurrent jobs are kept independently.

No component tests for `JobsPill` — layout and `setInterval` are
verified manually in the browser.

### Manual E2E

Done during Chris's oversized-local-model test run:

1. Trigger memory extraction; pill appears showing `1` with spinner.
2. Open popover; entry shows "Memory extraction – <persona> – 0:0N".
3. Timer increments once per second while popover is open.
4. Job fails/skips; entry disappears; pill hides when list empty.
5. F5 mid-job; after reconnect, pill reappears (validates the R2
   `sessionStorage` persistence fix).

## Non-Goals / Explicit Deferrals

- **Job-snapshot endpoint at WS handshake** — not needed once
  `sessionStorage` persistence covers reload. Revisit only if stream
  replay turns out to miss legitimate cases.
- **Click-to-cancel** — the backend job system has no cancellation
  path today, and exposing a button that does nothing is worse than
  not having the button.
- **Persistence of the `jobStore` itself** — the store is derived
  state from the event stream. On reload, stream replay reconstructs
  it. No need for its own `sessionStorage` copy.
- **Toast for skipped/failed extraction** — separate concern, already
  scoped in the `MemoryExtractionSkippedEvent` work from earlier
  today.

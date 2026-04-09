# Job Log User Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Job-Log" tab to the user overlay that shows the last 200 background-job events per user (started / completed / failed / retry) with persona filter, silent-jobs toggle, and expandable error details.

**Architecture:** Each job state transition in `backend/jobs/_consumer.py` appends a compact JSON entry to a Redis **list** `jobs:log:{user_id}` via `LPUSH`, followed by `LTRIM 0 199` and `EXPIRE` (7 days). A new REST endpoint `GET /api/jobs/log` returns the list. A new `JobLogTab.tsx` fetches the list on mount and additionally subscribes to `job.*` events via the existing `eventBus` to live-append new entries (capped at 200 client-side). All job events are recorded regardless of the `notify` flag — the flag is persisted on the entry so the UI can filter "silent" jobs.

**Tech Stack:** FastAPI + `redis.asyncio` (backend), React + TypeScript + Tailwind + zustand event bus (frontend), Pydantic v2 DTOs in `shared/dtos/jobs.py`.

---

## File Structure

**Backend — new files**
- `backend/jobs/_log.py` — `append_job_log_entry`, `read_job_log_entries`, constants (`JOB_LOG_MAX = 200`, `JOB_LOG_TTL_SECONDS = 7 * 24 * 3600`)
- `backend/jobs/_http.py` — `router` exposing `GET /api/jobs/log`
- `shared/dtos/jobs.py` — `JobLogEntryDto`, `JobLogDto`
- `tests/test_jobs_log.py` — repository + handler tests

**Backend — modified files**
- `backend/jobs/__init__.py` — re-export `router as jobs_http_router`, plus `append_job_log_entry`
- `backend/jobs/_consumer.py` — call `append_job_log_entry` at 4 emission sites (started, completed, failed, retry); track `execution_started_at` for duration
- `backend/main.py` — `app.include_router(jobs_http_router)`

**Frontend — new files**
- `frontend/src/core/types/jobLog.ts` — mirrors `JobLogEntryDto`
- `frontend/src/core/api/jobsLog.ts` — `fetchJobLog()`
- `frontend/src/app/components/user-modal/JobLogTab.tsx` — the tab UI
- `frontend/src/app/components/user-modal/__tests__/JobLogTab.test.tsx` — filter tests

**Frontend — modified files**
- `frontend/src/app/components/user-modal/UserModal.tsx` — add `'job-log'` to `UserModalTab`, insert into `TABS` between `models` and `settings`, conditional render

---

## Data Model

**Redis key:** `jobs:log:{user_id}` — Redis list, newest-first (`LPUSH`).

**Entry (JSON-encoded string, one per list element):**

```json
{
  "entry_id": "0197...uuid",
  "job_id": "d3c...",
  "job_type": "memory_extraction",
  "persona_id": "b8f..." ,
  "status": "started",
  "attempt": 0,
  "silent": false,
  "ts": "2026-04-09T14:32:07.431+00:00",
  "duration_ms": null,
  "error_message": null
}
```

- `status` ∈ `{"started", "completed", "failed", "retry"}`
- `silent` = `not config.notify` (persisted so UI can filter)
- `duration_ms` set only on `completed` / `failed` (computed from `execution_started_at`)
- `error_message` set only on `failed`; `attempt` set on `retry` / `failed`
- `entry_id` is a per-entry UUID so the frontend can dedupe when live events race with the initial fetch

---

## Task 1: Shared DTOs and constants

**Files:**
- Create: `shared/dtos/jobs.py`

- [ ] **Step 1: Create `shared/dtos/jobs.py`**

```python
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

JobLogStatus = Literal["started", "completed", "failed", "retry"]


class JobLogEntryDto(BaseModel):
    """One transition of a background job, as shown in the Job Log tab."""

    entry_id: str = Field(..., description="Stable id for client-side dedupe")
    job_id: str
    job_type: str
    persona_id: str | None = None
    status: JobLogStatus
    attempt: int = 0
    silent: bool = False
    ts: datetime
    duration_ms: int | None = None
    error_message: str | None = None


class JobLogDto(BaseModel):
    entries: list[JobLogEntryDto]
```

- [ ] **Step 2: Verify it imports**

Run: `uv run python -c "from shared.dtos.jobs import JobLogEntryDto, JobLogDto; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add shared/dtos/jobs.py
git commit -m "Add JobLogEntryDto and JobLogDto shared contracts"
```

---

## Task 2: Redis log repository (`backend/jobs/_log.py`)

**Files:**
- Create: `backend/jobs/_log.py`
- Create: `tests/test_jobs_log.py`

- [ ] **Step 1: Write the failing repository test**

Create `tests/test_jobs_log.py`:

```python
import json
from datetime import datetime, timezone

import pytest
from redis.asyncio import Redis

from backend.jobs._log import (
    JOB_LOG_MAX,
    JOB_LOG_TTL_SECONDS,
    append_job_log_entry,
    read_job_log_entries,
)
from shared.dtos.jobs import JobLogEntryDto


@pytest.fixture
async def redis_client():
    client = Redis.from_url("redis://localhost:6379/15", decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.mark.asyncio
async def test_append_and_read_roundtrip(redis_client: Redis) -> None:
    entry = JobLogEntryDto(
        entry_id="e1",
        job_id="j1",
        job_type="memory_extraction",
        persona_id="p1",
        status="started",
        ts=datetime(2026, 4, 9, 14, 30, tzinfo=timezone.utc),
    )
    await append_job_log_entry(redis_client, user_id="u1", entry=entry)

    entries = await read_job_log_entries(redis_client, user_id="u1", limit=50)
    assert len(entries) == 1
    assert entries[0].job_id == "j1"
    assert entries[0].status == "started"


@pytest.mark.asyncio
async def test_trim_keeps_newest_n(redis_client: Redis) -> None:
    for i in range(JOB_LOG_MAX + 25):
        entry = JobLogEntryDto(
            entry_id=f"e{i}",
            job_id=f"j{i}",
            job_type="memory_extraction",
            status="started",
            ts=datetime(2026, 4, 9, 14, 30, tzinfo=timezone.utc),
        )
        await append_job_log_entry(redis_client, user_id="u1", entry=entry)

    length = await redis_client.llen("jobs:log:u1")
    assert length == JOB_LOG_MAX

    entries = await read_job_log_entries(redis_client, user_id="u1", limit=JOB_LOG_MAX)
    # Newest first — the last appended should be at index 0
    assert entries[0].job_id == f"j{JOB_LOG_MAX + 24}"


@pytest.mark.asyncio
async def test_ttl_is_set(redis_client: Redis) -> None:
    entry = JobLogEntryDto(
        entry_id="e1",
        job_id="j1",
        job_type="memory_extraction",
        status="started",
        ts=datetime(2026, 4, 9, 14, 30, tzinfo=timezone.utc),
    )
    await append_job_log_entry(redis_client, user_id="u1", entry=entry)

    ttl = await redis_client.ttl("jobs:log:u1")
    assert 0 < ttl <= JOB_LOG_TTL_SECONDS


@pytest.mark.asyncio
async def test_read_empty(redis_client: Redis) -> None:
    entries = await read_job_log_entries(redis_client, user_id="nobody", limit=50)
    assert entries == []
```

- [ ] **Step 2: Run the test — expect import failure**

Run: `uv run pytest tests/test_jobs_log.py -v`
Expected: FAIL (cannot import `backend.jobs._log`)

- [ ] **Step 3: Create `backend/jobs/_log.py`**

```python
"""Per-user job log stored in a Redis list.

Entries are JSON-encoded ``JobLogEntryDto`` instances. Each append
performs ``LPUSH`` + ``LTRIM`` so the list is capped at
``JOB_LOG_MAX`` (newest-first), then refreshes a rolling TTL so
inactive users' logs expire after ``JOB_LOG_TTL_SECONDS``.
"""

from __future__ import annotations

import logging
from redis.asyncio import Redis

from shared.dtos.jobs import JobLogEntryDto

JOB_LOG_MAX = 200
JOB_LOG_TTL_SECONDS = 7 * 24 * 3600  # 7 days

_log = logging.getLogger("chatsune.jobs.log")


def _key(user_id: str) -> str:
    return f"jobs:log:{user_id}"


async def append_job_log_entry(
    redis: Redis, *, user_id: str, entry: JobLogEntryDto
) -> None:
    """Append a single entry to the user's job log.

    Uses a pipeline so LPUSH/LTRIM/EXPIRE are atomic relative to
    reads. Failures are logged but never raised — the job log is
    diagnostic and must not break the main job flow.
    """
    key = _key(user_id)
    payload = entry.model_dump_json()
    try:
        pipe = redis.pipeline(transaction=False)
        pipe.lpush(key, payload)
        pipe.ltrim(key, 0, JOB_LOG_MAX - 1)
        pipe.expire(key, JOB_LOG_TTL_SECONDS)
        await pipe.execute()
    except Exception:
        _log.exception("job_log.append_failed user_id=%s", user_id)


async def read_job_log_entries(
    redis: Redis, *, user_id: str, limit: int = JOB_LOG_MAX
) -> list[JobLogEntryDto]:
    """Return up to ``limit`` most-recent entries (newest first)."""
    capped = max(0, min(limit, JOB_LOG_MAX))
    if capped == 0:
        return []
    raw = await redis.lrange(_key(user_id), 0, capped - 1)
    entries: list[JobLogEntryDto] = []
    for item in raw:
        try:
            entries.append(JobLogEntryDto.model_validate_json(item))
        except Exception:
            _log.warning("job_log.skip_invalid_entry user_id=%s", user_id)
    return entries
```

- [ ] **Step 4: Run the tests — expect PASS**

Run: `uv run pytest tests/test_jobs_log.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/jobs/_log.py tests/test_jobs_log.py
git commit -m "Add per-user job log repository backed by Redis list"
```

---

## Task 3: Wire log appends into the job consumer

**Files:**
- Modify: `backend/jobs/_consumer.py` (imports, 4 emission sites, track `execution_started_at`)
- Modify: `backend/jobs/__init__.py` (re-export `append_job_log_entry`)

- [ ] **Step 1: Re-export from `backend/jobs/__init__.py`**

Add the import and extend `__all__`:

```python
from backend.jobs._log import append_job_log_entry, read_job_log_entries
```

And append `"append_job_log_entry"`, `"read_job_log_entries"` to the existing `__all__` tuple/list.

- [ ] **Step 2: Add import and helper at the top of `backend/jobs/_consumer.py`**

Add alongside the existing imports:

```python
import uuid
from backend.jobs._log import append_job_log_entry
from shared.dtos.jobs import JobLogEntryDto, JobLogStatus
```

- [ ] **Step 3: Add a small helper at module level (below the existing helpers, above `process_one`)**

```python
async def _log_job_transition(
    redis: Redis,
    *,
    user_id: str,
    job,
    status: JobLogStatus,
    silent: bool,
    ts,
    attempt: int = 0,
    duration_ms: int | None = None,
    error_message: str | None = None,
) -> None:
    entry = JobLogEntryDto(
        entry_id=str(uuid.uuid4()),
        job_id=job.id,
        job_type=job.job_type,
        persona_id=job.payload.get("persona_id"),
        status=status,
        attempt=attempt,
        silent=silent,
        ts=ts,
        duration_ms=duration_ms,
        error_message=error_message,
    )
    await append_job_log_entry(redis, user_id=user_id, entry=entry)
```

- [ ] **Step 4: Capture `execution_started_at` and log `started`**

In `_consumer.py`, immediately before the `JOB_STARTED` publish (currently around line 188), insert:

```python
execution_started_at = datetime.now(timezone.utc)
await _log_job_transition(
    redis,
    user_id=job.user_id,
    job=job,
    status="started",
    silent=not config.notify,
    ts=execution_started_at,
)
```

- [ ] **Step 5: Log `completed` with duration**

Right after the existing `JOB_COMPLETED` publish block (around line 233, inside `if config.notify:` — but the log call must run regardless of `notify`, so place it **after** the `if` block, still inside the `try`), insert:

```python
completed_at = datetime.now(timezone.utc)
await _log_job_transition(
    redis,
    user_id=job.user_id,
    job=job,
    status="completed",
    silent=not config.notify,
    ts=completed_at,
    duration_ms=int((completed_at - execution_started_at).total_seconds() * 1000),
)
```

- [ ] **Step 6: Log `failed` (final failure) with duration + error message**

Inside the final-failure branch (`if unrecoverable or attempt >= config.max_retries:`), after the existing `JOB_FAILED` publish block and before `clear_retry`, insert:

```python
failed_at = datetime.now(timezone.utc)
await _log_job_transition(
    redis,
    user_id=job.user_id,
    job=job,
    status="failed",
    silent=not (config.notify or config.notify_error),
    ts=failed_at,
    attempt=attempt,
    duration_ms=int((failed_at - execution_started_at).total_seconds() * 1000)
    if "execution_started_at" in dir()
    else None,
    error_message=error_message,
)
```

Note: `execution_started_at` may not exist if the job failed *before* the started-publish (e.g. quota check). Use a local default at the top of the `try` block: add `execution_started_at: datetime | None = None` before the quota call, then the duration expression becomes:

```python
duration_ms=(
    int((failed_at - execution_started_at).total_seconds() * 1000)
    if execution_started_at is not None
    else None
),
```

Apply the same `None` default treatment to Step 5's completed branch (though by definition `execution_started_at` is set there, it's more robust).

- [ ] **Step 7: Log `retry`**

Inside the `else` branch (schedule retry), after the `JOB_RETRY` publish, insert:

```python
await _log_job_transition(
    redis,
    user_id=job.user_id,
    job=job,
    status="retry",
    silent=not config.notify,
    ts=now,
    attempt=attempt,
    error_message=error_message,
)
```

- [ ] **Step 8: Run the existing job consumer tests to verify nothing broke**

Run: `uv run pytest tests/test_job_consumer.py tests/test_job_events.py tests/test_job_integration.py -v`
Expected: all existing tests pass.

- [ ] **Step 9: Verify backend still py-compiles**

Run: `uv run python -m py_compile backend/jobs/_consumer.py backend/jobs/_log.py backend/jobs/__init__.py`
Expected: no output.

- [ ] **Step 10: Commit**

```bash
git add backend/jobs/_consumer.py backend/jobs/__init__.py
git commit -m "Record every job state transition into the per-user job log"
```

---

## Task 4: REST endpoint `GET /api/jobs/log`

**Files:**
- Create: `backend/jobs/_http.py`
- Modify: `backend/jobs/__init__.py` (export `router`)
- Modify: `backend/main.py` (include router)
- Modify: `tests/test_jobs_log.py` (add handler test)

- [ ] **Step 1: Write the failing handler test**

Append to `tests/test_jobs_log.py`:

```python
from httpx import ASGITransport, AsyncClient

from backend.main import app


@pytest.mark.asyncio
async def test_get_job_log_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/jobs/log")
    assert response.status_code in (401, 403)
```

(A full authed integration test lives already under `tests/test_job_integration.py`; here we only assert the route exists and rejects anonymous access — keeps the unit test fast and self-contained.)

- [ ] **Step 2: Run the test — expect 404 (route not mounted)**

Run: `uv run pytest tests/test_jobs_log.py::test_get_job_log_requires_auth -v`
Expected: FAIL (status 404).

- [ ] **Step 3: Create `backend/jobs/_http.py`**

```python
"""HTTP routes for the job log (per-user diagnostic view)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from backend.database import get_redis
from backend.dependencies import require_active_session
from backend.jobs._log import JOB_LOG_MAX, read_job_log_entries
from shared.dtos.jobs import JobLogDto

_log = logging.getLogger("chatsune.jobs.http")

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/log", response_model=JobLogDto)
async def get_job_log(
    user: dict = Depends(require_active_session),
    limit: int = Query(JOB_LOG_MAX, ge=1, le=JOB_LOG_MAX),
) -> JobLogDto:
    redis = get_redis()
    user_id = user["sub"]
    entries = await read_job_log_entries(redis, user_id=user_id, limit=limit)
    _log.debug("jobs.log.served user_id=%s count=%d", user_id, len(entries))
    return JobLogDto(entries=entries)
```

- [ ] **Step 4: Export the router from `backend/jobs/__init__.py`**

Add:

```python
from backend.jobs._http import router as jobs_http_router
```

and append `"jobs_http_router"` to `__all__`.

- [ ] **Step 5: Mount it in `backend/main.py`**

Find the existing `app.include_router(...)` block (around line 545) and add after `debug_router`:

```python
from backend.jobs import jobs_http_router  # add near the other router imports
# ...
app.include_router(jobs_http_router)
```

- [ ] **Step 6: Run the handler test again — expect PASS**

Run: `uv run pytest tests/test_jobs_log.py -v`
Expected: all green.

- [ ] **Step 7: Verify py-compile**

Run: `uv run python -m py_compile backend/jobs/_http.py backend/main.py`
Expected: no output.

- [ ] **Step 8: Commit**

```bash
git add backend/jobs/_http.py backend/jobs/__init__.py backend/main.py tests/test_jobs_log.py
git commit -m "Expose GET /api/jobs/log returning the per-user job log"
```

---

## Task 5: Frontend type + API client

**Files:**
- Create: `frontend/src/core/types/jobLog.ts`
- Create: `frontend/src/core/api/jobsLog.ts`

- [ ] **Step 1: Create the TypeScript type**

`frontend/src/core/types/jobLog.ts`:

```typescript
export type JobLogStatus = 'started' | 'completed' | 'failed' | 'retry'

export interface JobLogEntry {
  entry_id: string
  job_id: string
  job_type: string
  persona_id: string | null
  status: JobLogStatus
  attempt: number
  silent: boolean
  ts: string // ISO timestamp
  duration_ms: number | null
  error_message: string | null
}
```

- [ ] **Step 2: Create the API client**

`frontend/src/core/api/jobsLog.ts`:

```typescript
import type { JobLogEntry } from '../types/jobLog'

export async function fetchJobLog(limit = 200): Promise<JobLogEntry[]> {
  const response = await fetch(`/api/jobs/log?limit=${limit}`, {
    credentials: 'include',
  })
  if (!response.ok) {
    throw new Error(`Failed to fetch job log: ${response.status}`)
  }
  const data = (await response.json()) as { entries: JobLogEntry[] }
  return data.entries
}
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/core/types/jobLog.ts frontend/src/core/api/jobsLog.ts
git commit -m "Add frontend type and fetch client for /api/jobs/log"
```

---

## Task 6: `JobLogTab` component

**Files:**
- Create: `frontend/src/app/components/user-modal/JobLogTab.tsx`

- [ ] **Step 1: Create the component**

`frontend/src/app/components/user-modal/JobLogTab.tsx`:

```tsx
import { useEffect, useMemo, useState } from 'react'

import { fetchJobLog } from '../../../core/api/jobsLog'
import { usePersonas } from '../../../core/hooks/usePersonas'
import { eventBus } from '../../../core/websocket/eventBus'
import type { BaseEvent } from '../../../core/types/events'
import type { JobLogEntry, JobLogStatus } from '../../../core/types/jobLog'

const MAX_ENTRIES = 200

const JOB_TYPE_LABELS: Record<string, string> = {
  memory_extraction: 'Memory extraction',
  memory_consolidation: 'Memory consolidation',
  title_generation: 'Title generation',
}

const STATUS_STYLE: Record<JobLogStatus, string> = {
  started: 'text-white/60',
  completed: 'text-green-400/80',
  failed: 'text-red-400/80',
  retry: 'text-amber-400/80',
}

const STATUS_LABEL: Record<JobLogStatus, string> = {
  started: 'started',
  completed: 'completed',
  failed: 'failed',
  retry: 'retry',
}

function relativeTime(fromIso: string, now: number): string {
  const then = Date.parse(fromIso)
  const diffS = Math.max(0, Math.floor((now - then) / 1000))
  if (diffS < 60) return `${diffS}s ago`
  if (diffS < 3600) return `${Math.floor(diffS / 60)}m ago`
  if (diffS < 86400) return `${Math.floor(diffS / 3600)}h ago`
  return `${Math.floor(diffS / 86400)}d ago`
}

function absoluteTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString()
}

function labelFor(jobType: string): string {
  return JOB_TYPE_LABELS[jobType] ?? jobType
}

interface JobEventPayload {
  job_id: string
  job_type: string
  persona_id?: string | null
  attempt?: number
  notify?: boolean
  error_message?: string
}

function statusFromEventType(type: string): JobLogStatus | null {
  if (type === 'job.started') return 'started'
  if (type === 'job.completed') return 'completed'
  if (type === 'job.failed') return 'failed'
  if (type === 'job.retry') return 'retry'
  return null
}

function entryFromEvent(event: BaseEvent): JobLogEntry | null {
  const status = statusFromEventType(event.type)
  if (!status) return null
  const p = (event.payload ?? {}) as JobEventPayload
  if (!p.job_id || !p.job_type) return null
  return {
    entry_id: event.id,
    job_id: p.job_id,
    job_type: p.job_type,
    persona_id: p.persona_id ?? null,
    status,
    attempt: p.attempt ?? 0,
    silent: p.notify === false,
    ts:
      typeof event.timestamp === 'string'
        ? event.timestamp
        : new Date().toISOString(),
    duration_ms: null,
    error_message: p.error_message ?? null,
  }
}

type PersonaFilter = 'all' | 'none' | string

export function JobLogTab() {
  const [entries, setEntries] = useState<JobLogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [personaFilter, setPersonaFilter] = useState<PersonaFilter>('all')
  const [showSilent, setShowSilent] = useState(false)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [now, setNow] = useState(() => Date.now())
  const { personas } = usePersonas()

  // Initial fetch
  useEffect(() => {
    let cancelled = false
    fetchJobLog(MAX_ENTRIES)
      .then((data) => {
        if (cancelled) return
        setEntries(data)
        setError(null)
      })
      .catch((e) => {
        if (cancelled) return
        setError(e instanceof Error ? e.message : 'Unknown error')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Live append from event bus
  useEffect(() => {
    const handler = (event: BaseEvent) => {
      const entry = entryFromEvent(event)
      if (!entry) return
      setEntries((prev) => {
        if (prev.some((e) => e.entry_id === entry.entry_id)) return prev
        const next = [entry, ...prev]
        return next.length > MAX_ENTRIES ? next.slice(0, MAX_ENTRIES) : next
      })
    }
    const unsub = eventBus.on('job.*', handler)
    return () => {
      unsub()
    }
  }, [])

  // Tick for relative time display
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 15_000)
    return () => window.clearInterval(id)
  }, [])

  const filtered = useMemo(() => {
    return entries.filter((e) => {
      if (!showSilent && e.silent) return false
      if (personaFilter === 'all') return true
      if (personaFilter === 'none') return !e.persona_id
      return e.persona_id === personaFilter
    })
  }, [entries, personaFilter, showSilent])

  const toggleExpanded = (entryId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(entryId)) next.delete(entryId)
      else next.add(entryId)
      return next
    })
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-white/30 font-mono uppercase tracking-wider mr-1">
            Persona
          </span>
          <select
            value={personaFilter}
            onChange={(e) => setPersonaFilter(e.target.value)}
            className="bg-surface border border-white/8 rounded-lg px-2 py-1 text-[11px] font-mono text-white/60 outline-none focus:border-gold/40 cursor-pointer appearance-none pr-6"
            style={{
              backgroundImage:
                'url("data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 width=%2712%27 height=%2712%27 viewBox=%270 0 12 12%27%3E%3Cpath d=%27M3 5l3 3 3-3%27 fill=%27none%27 stroke=%27rgba(255,255,255,0.3)%27 stroke-width=%271.5%27/%3E%3C/svg%3E")',
              backgroundRepeat: 'no-repeat',
              backgroundPosition: 'right 6px center',
            }}
          >
            <option value="all" style={{ background: '#0f0d16', color: 'rgba(255,255,255,0.85)' }}>
              All
            </option>
            <option value="none" style={{ background: '#0f0d16', color: 'rgba(255,255,255,0.85)' }}>
              No persona
            </option>
            {personas.map((p) => (
              <option
                key={p.id}
                value={p.id}
                style={{ background: '#0f0d16', color: 'rgba(255,255,255,0.85)' }}
              >
                {p.name}
              </option>
            ))}
          </select>
        </div>

        <button
          type="button"
          onClick={() => setShowSilent((v) => !v)}
          className={
            showSilent
              ? 'rounded-lg border border-gold/40 bg-gold/10 px-2 py-1 text-[11px] font-mono text-gold/90'
              : 'rounded-lg border border-white/8 bg-surface px-2 py-1 text-[11px] font-mono text-white/50 hover:text-white/70'
          }
          title="Show silent jobs (title generation etc.)"
        >
          Silent: {showSilent ? 'on' : 'off'}
        </button>

        <div className="ml-auto text-[10px] text-white/30 font-mono">
          {filtered.length} entr{filtered.length === 1 ? 'y' : 'ies'}
        </div>
      </div>

      {loading && (
        <div className="text-[11px] text-white/40 font-mono">Loading…</div>
      )}
      {error && (
        <div className="text-[11px] text-red-400/80 font-mono">Error: {error}</div>
      )}
      {!loading && !error && filtered.length === 0 && (
        <div className="text-[11px] text-white/30 font-mono">
          No entries match the current filter.
        </div>
      )}

      <div className="flex flex-col divide-y divide-white/5 border border-white/8 rounded-lg overflow-hidden">
        {filtered.map((entry) => {
          const persona = entry.persona_id
            ? personas.find((p) => p.id === entry.persona_id)?.name ?? entry.persona_id
            : null
          const isExpandable = entry.status === 'failed' && !!entry.error_message
          const isOpen = expanded.has(entry.entry_id)
          return (
            <div key={entry.entry_id} className="flex flex-col px-3 py-2">
              <div className="flex items-center gap-3 text-[11px] font-mono">
                <span className={`${STATUS_STYLE[entry.status]} w-[70px]`}>
                  {STATUS_LABEL[entry.status]}
                </span>
                <span className="text-white/80 w-[150px] truncate">{labelFor(entry.job_type)}</span>
                <span className="text-white/50 w-[120px] truncate">{persona ?? '—'}</span>
                <span
                  className="text-white/40"
                  title={absoluteTime(entry.ts)}
                >
                  {relativeTime(entry.ts, now)} · {absoluteTime(entry.ts)}
                </span>
                {entry.duration_ms != null && (
                  <span className="text-white/30">{entry.duration_ms} ms</span>
                )}
                {entry.attempt > 0 && (
                  <span className="text-amber-400/70">attempt {entry.attempt}</span>
                )}
                {entry.silent && (
                  <span className="text-white/25">silent</span>
                )}
                {isExpandable && (
                  <button
                    type="button"
                    onClick={() => toggleExpanded(entry.entry_id)}
                    className="ml-auto text-white/40 hover:text-white/70"
                  >
                    {isOpen ? 'hide' : 'details'}
                  </button>
                )}
              </div>
              {isExpandable && isOpen && (
                <pre className="mt-2 whitespace-pre-wrap break-words bg-black/30 border border-white/5 rounded px-2 py-1.5 text-[10px] text-red-300/80 font-mono">
                  {entry.error_message}
                </pre>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no errors.

If `usePersonas` lives elsewhere or has a different shape, fix the import path and the `.name`/`.id` access accordingly. Find it with: `rg "export function usePersonas|export const usePersonas" frontend/src`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/components/user-modal/JobLogTab.tsx
git commit -m "Add JobLogTab component with persona filter and silent toggle"
```

---

## Task 7: Tab unit test (filter logic)

**Files:**
- Create: `frontend/src/app/components/user-modal/__tests__/JobLogTab.test.tsx`

- [ ] **Step 1: Write the filter test**

```tsx
import { describe, expect, it } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { JobLogTab } from '../JobLogTab'

// Mock the API client and personas hook used by the component.
vi.mock('../../../../core/api/jobsLog', () => ({
  fetchJobLog: async () => [
    {
      entry_id: 'a',
      job_id: 'j1',
      job_type: 'memory_extraction',
      persona_id: 'p1',
      status: 'completed',
      attempt: 0,
      silent: false,
      ts: new Date().toISOString(),
      duration_ms: 1234,
      error_message: null,
    },
    {
      entry_id: 'b',
      job_id: 'j2',
      job_type: 'title_generation',
      persona_id: null,
      status: 'completed',
      attempt: 0,
      silent: true,
      ts: new Date().toISOString(),
      duration_ms: 500,
      error_message: null,
    },
  ],
}))

vi.mock('../../../../core/hooks/usePersonas', () => ({
  usePersonas: () => ({ personas: [{ id: 'p1', name: 'Aria' }] }),
}))

vi.mock('../../../../core/websocket/eventBus', () => ({
  eventBus: { on: () => () => {} },
}))

describe('JobLogTab', () => {
  it('hides silent entries by default and shows them when toggled', async () => {
    render(<JobLogTab />)
    // Initial fetch resolves
    expect(await screen.findByText('Memory extraction')).toBeInTheDocument()
    expect(screen.queryByText('Title generation')).not.toBeInTheDocument()

    fireEvent.click(screen.getByTitle(/silent jobs/i))
    expect(await screen.findByText('Title generation')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the test**

Run: `cd frontend && pnpm vitest run src/app/components/user-modal/__tests__/JobLogTab.test.tsx`
Expected: PASS. If mocks need different paths, adjust based on the real locations surfaced in Task 6 Step 2.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/components/user-modal/__tests__/JobLogTab.test.tsx
git commit -m "Test JobLogTab silent filter toggling"
```

---

## Task 8: Wire the tab into `UserModal`

**Files:**
- Modify: `frontend/src/app/components/user-modal/UserModal.tsx`

- [ ] **Step 1: Extend the tab union type**

Change the `UserModalTab` definition to insert `'job-log'` between `'models'` and `'settings'`:

```typescript
export type UserModalTab =
  | 'about-me'
  | 'personas'
  | 'projects'
  | 'history'
  | 'knowledge'
  | 'bookmarks'
  | 'uploads'
  | 'artefacts'
  | 'models'
  | 'job-log'
  | 'settings'
  | 'api-keys'
```

- [ ] **Step 2: Add the tab entry**

In the `TABS` array, insert between `models` and `settings`:

```typescript
{ id: 'job-log', label: 'Job-Log' },
```

- [ ] **Step 3: Import and render the tab**

Add import near the other tab imports:

```typescript
import { JobLogTab } from './JobLogTab'
```

In the conditional render block (around line 179), add between the `models` and `settings` branches:

```tsx
{activeTab === 'job-log' && <JobLogTab />}
```

- [ ] **Step 4: Type-check and build**

Run: `cd frontend && pnpm tsc --noEmit && pnpm run build`
Expected: clean build.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/user-modal/UserModal.tsx
git commit -m "Add Job-Log tab to user overlay between Models and Settings"
```

---

## Task 9: End-to-end smoke verification

- [ ] **Step 1: Start the stack and trigger a job**

Run the backend and frontend locally (however the project normally starts — `docker compose up` or equivalent). Send a chat message that causes a memory extraction job.

- [ ] **Step 2: Open User overlay → Job-Log tab**

Expected:
- The new tab appears between "Models" and "Settings".
- The just-triggered `memory_extraction` job shows as `started` → `completed`.
- Persona dropdown lists all personas and filters rows correctly.
- `Silent: off` hides `title_generation` rows; toggling to `on` reveals them.
- On a deliberately failing job (e.g. disconnect the LLM provider temporarily), the `failed` row shows a `details` button that expands the error message.
- Both relative and absolute time are shown on each row.

- [ ] **Step 3: If all checks pass, merge to master per project convention**

```bash
git checkout master
git merge --no-ff <branch-name>
git push
```

---

## Self-Review Notes

- **Spec coverage:**
  - List + LTRIM deckel of 200 → Task 2 (`JOB_LOG_MAX = 200`, `LTRIM 0 199`)
  - TTL on list → Task 2 (`EXPIRE` in pipeline, 7 days)
  - Pro-User mit Persona-Spalte → `persona_id` in entry (Task 1), persona column in row (Task 6)
  - Persona-Dropdown-Filter mit allen Personas → Task 6 (matches Uploads tab pattern)
  - Silent-Toggle default off → Task 6 (`useState(false)`)
  - Alle Jobs (auch silent) geloggt → Task 3 logs unconditionally; silent flag persisted
  - Failure details ausklappbar → Task 6 (`expanded` Set + `<pre>` block)
  - Relative + absolute Zeit → Task 6 (`relativeTime` + `absoluteTime` + `title` tooltip)
  - Zwischen Models und Settings → Task 8

- **Placeholder scan:** no TBDs, no "handle edge cases" hand-waves, every code step has full code.

- **Type consistency:** `JobLogEntryDto` field names (snake_case) match the TypeScript `JobLogEntry` (kept snake_case on the wire since other DTOs in this repo also mirror snake_case). `JobLogStatus` string literal matches between Pydantic `Literal` and TS union.

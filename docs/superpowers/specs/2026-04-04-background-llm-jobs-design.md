# Background LLM Job System -- Design Spec

**Date:** 2026-04-04
**Status:** Draft
**Scope:** Infrastructure layer for asynchronous LLM-powered background tasks

---

## Overview

Chatsune needs a system for running LLM-powered background processes (title generation,
memory consolidation, etc.) that share infrastructure: queuing, retry logic, per-user
concurrency control, and notification. This spec defines that system.

The first concrete job type is **automatic title generation** for chat sessions.

---

## Principles

- **Event-first:** All job lifecycle changes publish events to the affected user.
- **Privacy-first:** Admin sees system health, never user-specific job details.
- **Streaming always:** All LLM calls use streaming (Ollama requirement), results are collected.
- **Shared concurrency:** Background jobs and chat inference share a single per-user lock -- no concurrent LLM requests per user.
- **BYOK:** Jobs always use the triggering user's API key and the model that caused the job.

---

## File Structure

```
backend/
  jobs/
    __init__.py              # Public API: submit(), JobType enum, get_user_lock()
    _consumer.py             # Redis Streams consumer loop (XREADGROUP)
    _registry.py             # Job type registry: handler + config per type
    _models.py               # JobConfig, JobEntry
    _lock.py                 # Shared per-user asyncio.Lock singleton
    _retry.py                # Retry state management in Redis
    handlers/
      __init__.py
      _title_generation.py   # First concrete handler
```

**Shared contracts:**
- `shared/events/jobs.py` -- Job lifecycle events
- `shared/topics.py` -- New topic constants
- No new DTOs required -- job results flow through existing module APIs

---

## Job Type Registry

Each job type is a named entry with its own configuration:

```python
class JobType(StrEnum):
    TITLE_GENERATION = "title_generation"

@dataclass(frozen=True)
class JobConfig:
    handler: Callable[..., Awaitable[None]]
    max_retries: int = 3
    retry_delay_seconds: float = 15.0
    queue_timeout_seconds: float = 3600.0       # 60 min default
    execution_timeout_seconds: float = 300.0     # 5 min default
    reasoning_enabled: bool = False
    notify: bool = False
    notify_error: bool = False                   # Only checked when notify=False

JOB_REGISTRY: dict[JobType, JobConfig] = {
    JobType.TITLE_GENERATION: JobConfig(
        handler=handle_title_generation,
        max_retries=3,
        retry_delay_seconds=15.0,
        queue_timeout_seconds=3600.0,
        execution_timeout_seconds=60.0,
        reasoning_enabled=False,
        notify=False,
        notify_error=True,
    ),
}
```

**Retry and timeout values are per job type.** Future job types (e.g. memory consolidation)
will use longer retry delays (3-5 minutes) and longer execution timeouts.

---

## Job Entry

What gets written into the Redis Stream:

```python
class JobEntry(BaseModel):
    id: str                    # UUID
    job_type: JobType
    user_id: str
    model_unique_id: str       # provider:slug
    payload: dict              # Job-specific data (e.g. session_id, messages)
    correlation_id: str
    created_at: datetime
    attempt: int = 0
```

---

## Shared Per-User Lock

The existing `InferenceRunner._user_locks` is extracted to `backend/jobs/_lock.py`
as a shared singleton.

```python
_user_locks: dict[str, asyncio.Lock] = {}

def get_user_lock(user_id: str) -> asyncio.Lock:
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]
```

**Usage rules:**
- **Consumer loop:** Non-blocking check (`lock.locked()`). If busy, skip the job
  (leave unacknowledged) and process other users' jobs. Re-check on next iteration.
- **InferenceRunner:** Blocking acquire (`async with lock:`). Chat requests wait for
  a running background job to finish (and vice versa).
- **Both:** Wrapped in `asyncio.timeout(execution_timeout_seconds)` to prevent deadlocks.
  On timeout, the lock is released cleanly and the job enters retry flow.

**No eviction needed.** Self-hosted app with few users -- a dict of 10-20 locks is negligible.

---

## Consumer Loop

Runs as an `asyncio.Task` started in the FastAPI lifespan.

### Startup

```python
# In main.py lifespan
await ensure_consumer_group("jobs:pending", "workers")
consumer_task = asyncio.create_task(consumer_loop(redis, event_bus))
```

### Loop Logic

1. `XREADGROUP GROUP workers consumer-1 BLOCK 5000 STREAMS jobs:pending >`
2. Parse `JobEntry` from stream message
3. **Queue timeout check:** If `created_at + queue_timeout < now`, publish `JOB_EXPIRED`, `XACK`, skip.
4. **Retry timing check:** If job has `next_retry_at` in Redis and it hasn't passed, skip (leave unacked).
5. **Per-user lock check:** If `lock.locked()`, skip (leave unacked), continue to next job.
6. Acquire lock, execute handler within `asyncio.timeout(execution_timeout_seconds)`.
7. **On success:** `XACK`, clean up retry state, publish `JOB_COMPLETED`, optional notification.
8. **On failure:** Increment attempt. If `attempt >= max_retries`, publish `JOB_FAILED` (final), `XACK`.
   Otherwise publish `JOB_RETRY`, store `next_retry_at` in Redis hash `jobs:retry:{job_id}`.

### Non-Blocking Behaviour

When a user's lock is held (e.g. by an active chat), the job stays in the
Pending Entries List of the consumer group. The loop continues processing
jobs for other users. On the next iteration, the job is re-checked.

---

## Events

### New Topics (`shared/topics.py`)

```python
JOB_STARTED = "job.started"
JOB_COMPLETED = "job.completed"
JOB_FAILED = "job.failed"
JOB_RETRY = "job.retry"
JOB_EXPIRED = "job.expired"
```

### Event Models (`shared/events/jobs.py`)

```python
class JobStartedEvent(BaseModel):
    job_id: str
    job_type: str
    correlation_id: str
    timestamp: datetime

class JobCompletedEvent(BaseModel):
    job_id: str
    job_type: str
    correlation_id: str
    timestamp: datetime

class JobFailedEvent(BaseModel):
    job_id: str
    job_type: str
    correlation_id: str
    attempt: int
    max_retries: int
    error_message: str
    recoverable: bool          # True if retries remain
    timestamp: datetime

class JobRetryEvent(BaseModel):
    job_id: str
    job_type: str
    correlation_id: str
    attempt: int
    next_retry_at: datetime
    timestamp: datetime

class JobExpiredEvent(BaseModel):
    job_id: str
    job_type: str
    correlation_id: str
    waited_seconds: float
    timestamp: datetime
```

### Fan-Out Rules

- All job events target only the affected user: `target_user_ids=[job.user_id]`
- Admin never sees job events (privacy-first)

### Notification Logic

| `notify` | `notify_error` | `JOB_COMPLETED` sent? | `JOB_FAILED` (final) sent? |
|-----------|----------------|------------------------|----------------------------|
| `True`    | (implied True) | Yes                    | Yes                        |
| `False`   | `True`         | No                     | Yes                        |
| `False`   | `False`        | No                     | No                         |

`JOB_EXPIRED` is always sent -- a job dying after 60 minutes is always noteworthy.

Technical events (`JOB_STARTED`, `JOB_RETRY`) are always published for frontend
state management. The frontend decides whether to surface them in the UI.

---

## Title Generation Handler

### Trigger

After the first assistant response in a new chat session. The chat module calls:

```python
await jobs.submit(
    JobType.TITLE_GENERATION,
    user_id=user_id,
    model_unique_id=model_unique_id,
    payload={"session_id": session_id, "messages": [user_msg, assistant_msg]},
    correlation_id=correlation_id,
)
```

### Execution

1. Fetch user's API key via LLM module
2. Build prompt: system instruction + first messages + "Generate a short title for this conversation"
3. Call `stream_completion()` with `reasoning_enabled=False`, collect result
4. Extract plain text title (no quotes, max ~60 characters)
5. Persist via chat module public API: `chat_service.update_session_title(session_id, title)`
6. Chat module publishes its own event (e.g. `CHAT_SESSION_UPDATED`) with the new title

**The handler does not publish domain events.** It uses module APIs, and those modules
publish their own events. The consumer only handles job lifecycle events.

---

## Integration: InferenceRunner Changes

The `InferenceRunner` in `backend/modules/chat/_inference.py` must be updated:

1. **Remove** `_user_locks` dict from `InferenceRunner`
2. **Import** `get_user_lock` from `backend.jobs`
3. **Wrap** lock acquisition with `asyncio.timeout()` (same pattern as consumer)

This is a minimal, non-breaking change -- the behaviour stays identical, only the
lock source changes.

---

## Redis Keys

| Key Pattern              | Type          | Purpose                        | TTL     |
|--------------------------|---------------|--------------------------------|---------|
| `jobs:pending`           | Stream        | Job queue (consumer group)     | None    |
| `jobs:retry:{job_id}`    | Hash          | Retry state (attempt, next_at) | 2h      |

Stream entries are acknowledged and removed after processing. The stream itself
does not need a TTL -- acknowledged entries are trimmed periodically.

---

## Out of Scope (Future)

- Admin dashboard for job metrics (system health only, no user details)
- Multi-process consumer coordination (single process sufficient for self-hosted)
- Priority lanes (all jobs equal for now)
- Job cancellation by user

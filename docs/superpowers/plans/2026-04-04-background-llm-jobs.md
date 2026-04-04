# Background LLM Job System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Redis Streams-based background job system for asynchronous LLM tasks, with automatic chat title generation as the first concrete job type.

**Architecture:** Infrastructure layer at `backend/jobs/` using Redis Streams consumer groups (XREADGROUP). Per-user asyncio locks shared between chat inference and background jobs. Job types registered in a plain dict registry with per-type configuration (retries, timeouts, notifications).

**Tech Stack:** Python, asyncio, Redis Streams (consumer groups), Pydantic v2, pytest

**Spec:** `docs/superpowers/specs/2026-04-04-background-llm-jobs-design.md`

---

### Task 1: Shared Per-User Lock

Extract the per-user lock from InferenceRunner into a shared singleton so both chat inference and background jobs use the same lock.

**Files:**
- Create: `backend/jobs/__init__.py`
- Create: `backend/jobs/_lock.py`
- Modify: `backend/modules/chat/_inference.py:17-28`
- Create: `tests/test_user_lock.py`

- [ ] **Step 1: Write the failing test for get_user_lock**

```python
# tests/test_user_lock.py
import asyncio

import pytest


async def test_get_user_lock_returns_same_instance():
    from backend.jobs._lock import get_user_lock

    lock_a = get_user_lock("user-1")
    lock_b = get_user_lock("user-1")
    assert lock_a is lock_b


async def test_get_user_lock_returns_different_for_different_users():
    from backend.jobs._lock import get_user_lock

    lock_a = get_user_lock("user-1")
    lock_b = get_user_lock("user-2")
    assert lock_a is not lock_b


async def test_lock_serialises_access():
    from backend.jobs._lock import get_user_lock

    lock = get_user_lock("user-serial")
    order = []

    async def task(name: str, delay: float):
        async with lock:
            order.append(f"{name}_start")
            await asyncio.sleep(delay)
            order.append(f"{name}_end")

    t1 = asyncio.create_task(task("a", 0.05))
    await asyncio.sleep(0.01)
    t2 = asyncio.create_task(task("b", 0.01))
    await asyncio.gather(t1, t2)

    assert order.index("a_end") < order.index("b_start")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_user_lock.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.jobs'`

- [ ] **Step 3: Implement the lock module**

```python
# backend/jobs/__init__.py
"""Background job infrastructure — queue, consumer, per-user lock.

Public API: import only from this file.
"""

from backend.jobs._lock import get_user_lock

__all__ = [
    "get_user_lock",
]
```

```python
# backend/jobs/_lock.py
import asyncio

_user_locks: dict[str, asyncio.Lock] = {}


def get_user_lock(user_id: str) -> asyncio.Lock:
    """Return a per-user asyncio.Lock, creating one if it does not exist.

    This lock is shared between chat inference and background jobs
    to ensure at most one concurrent LLM request per user.
    """
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_user_lock.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Update InferenceRunner to use shared lock**

Replace the internal lock in `backend/modules/chat/_inference.py`. Remove `_get_lock` method and `_user_locks` dict, import `get_user_lock` from `backend.jobs`:

```python
# backend/modules/chat/_inference.py — lines 1-45 become:
import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timezone

from backend.jobs import get_user_lock
from backend.modules.llm._adapters._events import (
    ContentDelta, StreamDone, StreamError, ThinkingDelta,
)
from shared.events.chat import (
    ChatContentDeltaEvent, ChatStreamEndedEvent, ChatStreamErrorEvent,
    ChatStreamStartedEvent, ChatThinkingDeltaEvent,
)

_log = logging.getLogger(__name__)


class InferenceRunner:
    """Orchestrates a single inference stream with per-user serialisation."""

    async def run(
        self,
        user_id: str,
        session_id: str,
        correlation_id: str,
        stream_fn: Callable,
        emit_fn: Callable,
        save_fn: Callable,
        cancel_event: asyncio.Event | None = None,
        context_status: str = "green",
        context_fill_percentage: float = 0.0,
    ) -> None:
        lock = get_user_lock(user_id)
        async with lock:
            await self._run_locked(
                session_id, correlation_id, stream_fn, emit_fn, save_fn, cancel_event,
                context_status, context_fill_percentage,
            )
```

Everything from `_run_locked` onward stays unchanged.

- [ ] **Step 6: Run existing inference runner tests**

Run: `uv run pytest tests/test_inference_runner.py -v`
Expected: PASS (all 5 existing tests still pass)

- [ ] **Step 7: Commit**

```bash
git add backend/jobs/__init__.py backend/jobs/_lock.py backend/modules/chat/_inference.py tests/test_user_lock.py
git commit -m "Extract per-user lock to shared backend/jobs module"
```

---

### Task 2: Job Models and Registry

Define the job configuration, entry model, and type registry.

**Files:**
- Create: `backend/jobs/_models.py`
- Create: `backend/jobs/_registry.py`
- Create: `tests/test_job_models.py`

- [ ] **Step 1: Write the failing test for JobEntry and JobConfig**

```python
# tests/test_job_models.py
from datetime import datetime, timezone

import pytest


def test_job_entry_serialisation():
    from backend.jobs._models import JobEntry, JobType

    entry = JobEntry(
        id="job-1",
        job_type=JobType.TITLE_GENERATION,
        user_id="user-1",
        model_unique_id="ollama_cloud:llama3.2",
        payload={"session_id": "sess-1"},
        correlation_id="corr-1",
        created_at=datetime(2026, 4, 4, tzinfo=timezone.utc),
    )

    data = entry.model_dump(mode="json")
    assert data["job_type"] == "title_generation"
    assert data["attempt"] == 0

    roundtrip = JobEntry.model_validate(data)
    assert roundtrip.id == "job-1"
    assert roundtrip.model_unique_id == "ollama_cloud:llama3.2"


def test_job_config_defaults():
    from backend.jobs._models import JobConfig

    config = JobConfig(handler=lambda: None)
    assert config.max_retries == 3
    assert config.retry_delay_seconds == 15.0
    assert config.queue_timeout_seconds == 3600.0
    assert config.execution_timeout_seconds == 300.0
    assert config.reasoning_enabled is False
    assert config.notify is False
    assert config.notify_error is False


def test_job_config_custom_values():
    from backend.jobs._models import JobConfig

    config = JobConfig(
        handler=lambda: None,
        max_retries=5,
        retry_delay_seconds=180.0,
        execution_timeout_seconds=600.0,
        notify=True,
    )
    assert config.max_retries == 5
    assert config.retry_delay_seconds == 180.0
    assert config.execution_timeout_seconds == 600.0
    assert config.notify is True


def test_registry_contains_title_generation():
    from backend.jobs._models import JobType
    from backend.jobs._registry import JOB_REGISTRY

    assert JobType.TITLE_GENERATION in JOB_REGISTRY
    config = JOB_REGISTRY[JobType.TITLE_GENERATION]
    assert config.max_retries == 3
    assert config.retry_delay_seconds == 15.0
    assert config.execution_timeout_seconds == 60.0
    assert config.reasoning_enabled is False
    assert config.notify is False
    assert config.notify_error is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_job_models.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement models**

```python
# backend/jobs/_models.py
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class JobType(StrEnum):
    TITLE_GENERATION = "title_generation"


@dataclass(frozen=True)
class JobConfig:
    handler: Callable[..., Awaitable[None]]
    max_retries: int = 3
    retry_delay_seconds: float = 15.0
    queue_timeout_seconds: float = 3600.0
    execution_timeout_seconds: float = 300.0
    reasoning_enabled: bool = False
    notify: bool = False
    notify_error: bool = False


class JobEntry(BaseModel):
    id: str
    job_type: JobType
    user_id: str
    model_unique_id: str
    payload: dict
    correlation_id: str
    created_at: datetime
    attempt: int = 0
```

- [ ] **Step 4: Implement registry (with placeholder handler)**

```python
# backend/jobs/_registry.py
from backend.jobs._models import JobConfig, JobType

# Placeholder — replaced in Task 7 when the real handler is implemented.
async def _placeholder_title_handler(**kwargs) -> None:
    raise NotImplementedError("Title generation handler not yet wired")


JOB_REGISTRY: dict[JobType, JobConfig] = {
    JobType.TITLE_GENERATION: JobConfig(
        handler=_placeholder_title_handler,
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

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_job_models.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/jobs/_models.py backend/jobs/_registry.py tests/test_job_models.py
git commit -m "Add job models, config, and type registry"
```

---

### Task 3: Shared Events and Topics

Add job lifecycle events and topics to the shared contracts layer.

**Files:**
- Create: `shared/events/jobs.py`
- Modify: `shared/topics.py`
- Modify: `backend/ws/event_bus.py` (fan-out rules)
- Create: `tests/test_shared_job_events.py`

- [ ] **Step 1: Write the failing test for job events**

```python
# tests/test_shared_job_events.py
from datetime import datetime, timezone

import pytest


def test_job_started_event():
    from shared.events.jobs import JobStartedEvent

    event = JobStartedEvent(
        job_id="job-1",
        job_type="title_generation",
        correlation_id="corr-1",
        timestamp=datetime(2026, 4, 4, tzinfo=timezone.utc),
    )
    data = event.model_dump(mode="json")
    assert data["type"] == "job.started"
    assert data["job_id"] == "job-1"


def test_job_completed_event():
    from shared.events.jobs import JobCompletedEvent

    event = JobCompletedEvent(
        job_id="job-1",
        job_type="title_generation",
        correlation_id="corr-1",
        timestamp=datetime(2026, 4, 4, tzinfo=timezone.utc),
    )
    assert event.type == "job.completed"


def test_job_failed_event():
    from shared.events.jobs import JobFailedEvent

    event = JobFailedEvent(
        job_id="job-1",
        job_type="title_generation",
        correlation_id="corr-1",
        attempt=3,
        max_retries=3,
        error_message="Provider unavailable",
        recoverable=False,
        timestamp=datetime(2026, 4, 4, tzinfo=timezone.utc),
    )
    assert event.type == "job.failed"
    assert event.recoverable is False


def test_job_retry_event():
    from shared.events.jobs import JobRetryEvent

    event = JobRetryEvent(
        job_id="job-1",
        job_type="title_generation",
        correlation_id="corr-1",
        attempt=1,
        next_retry_at=datetime(2026, 4, 4, 0, 0, 15, tzinfo=timezone.utc),
        timestamp=datetime(2026, 4, 4, tzinfo=timezone.utc),
    )
    assert event.type == "job.retry"
    assert event.attempt == 1


def test_job_expired_event():
    from shared.events.jobs import JobExpiredEvent

    event = JobExpiredEvent(
        job_id="job-1",
        job_type="title_generation",
        correlation_id="corr-1",
        waited_seconds=3600.0,
        timestamp=datetime(2026, 4, 4, tzinfo=timezone.utc),
    )
    assert event.type == "job.expired"


def test_topics_have_job_constants():
    from shared.topics import Topics

    assert Topics.JOB_STARTED == "job.started"
    assert Topics.JOB_COMPLETED == "job.completed"
    assert Topics.JOB_FAILED == "job.failed"
    assert Topics.JOB_RETRY == "job.retry"
    assert Topics.JOB_EXPIRED == "job.expired"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_shared_job_events.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement job events**

```python
# shared/events/jobs.py
from datetime import datetime

from pydantic import BaseModel


class JobStartedEvent(BaseModel):
    type: str = "job.started"
    job_id: str
    job_type: str
    correlation_id: str
    timestamp: datetime


class JobCompletedEvent(BaseModel):
    type: str = "job.completed"
    job_id: str
    job_type: str
    correlation_id: str
    timestamp: datetime


class JobFailedEvent(BaseModel):
    type: str = "job.failed"
    job_id: str
    job_type: str
    correlation_id: str
    attempt: int
    max_retries: int
    error_message: str
    recoverable: bool
    timestamp: datetime


class JobRetryEvent(BaseModel):
    type: str = "job.retry"
    job_id: str
    job_type: str
    correlation_id: str
    attempt: int
    next_retry_at: datetime
    timestamp: datetime


class JobExpiredEvent(BaseModel):
    type: str = "job.expired"
    job_id: str
    job_type: str
    correlation_id: str
    waited_seconds: float
    timestamp: datetime
```

- [ ] **Step 4: Add job topics to shared/topics.py**

Add these lines at the end of the `Topics` class in `shared/topics.py`:

```python
    # Background jobs
    JOB_STARTED = "job.started"
    JOB_COMPLETED = "job.completed"
    JOB_FAILED = "job.failed"
    JOB_RETRY = "job.retry"
    JOB_EXPIRED = "job.expired"
```

- [ ] **Step 5: Add fan-out rules to event_bus.py**

Add these entries to the `_FANOUT` dict in `backend/ws/event_bus.py`, after the chat entries:

```python
    # Background jobs — target user only
    Topics.JOB_STARTED: ([], True),
    Topics.JOB_COMPLETED: ([], True),
    Topics.JOB_FAILED: ([], True),
    Topics.JOB_RETRY: ([], True),
    Topics.JOB_EXPIRED: ([], True),
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_shared_job_events.py -v`
Expected: PASS (6 tests)

- [ ] **Step 7: Run full test suite to check nothing is broken**

Run: `uv run pytest -v`
Expected: All existing tests still pass

- [ ] **Step 8: Commit**

```bash
git add shared/events/jobs.py shared/topics.py backend/ws/event_bus.py tests/test_shared_job_events.py
git commit -m "Add job lifecycle events, topics, and fan-out rules"
```

---

### Task 4: Job Submission (submit)

Implement the `submit()` function that enqueues jobs into the Redis Stream.

**Files:**
- Create: `backend/jobs/_submit.py`
- Modify: `backend/jobs/__init__.py`
- Create: `tests/test_job_submit.py`

- [ ] **Step 1: Write the failing test for submit**

```python
# tests/test_job_submit.py
import json

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from backend.config import settings


@pytest_asyncio.fixture
async def redis(clean_db):
    """Provide a clean Redis client for job tests."""
    from backend.database import connect_db, disconnect_db, get_redis
    await connect_db()
    try:
        yield get_redis()
    finally:
        await disconnect_db()


async def test_submit_adds_entry_to_stream(redis):
    from backend.jobs import submit
    from backend.jobs._models import JobType

    job_id = await submit(
        job_type=JobType.TITLE_GENERATION,
        user_id="user-1",
        model_unique_id="ollama_cloud:llama3.2",
        payload={"session_id": "sess-1"},
        correlation_id="corr-1",
    )

    assert job_id  # non-empty string

    entries = await redis.xrange("jobs:pending")
    assert len(entries) == 1

    _, fields = entries[0]
    data = json.loads(fields["data"])
    assert data["id"] == job_id
    assert data["job_type"] == "title_generation"
    assert data["user_id"] == "user-1"
    assert data["model_unique_id"] == "ollama_cloud:llama3.2"
    assert data["payload"] == {"session_id": "sess-1"}
    assert data["attempt"] == 0


async def test_submit_returns_unique_ids(redis):
    from backend.jobs import submit
    from backend.jobs._models import JobType

    id_a = await submit(
        job_type=JobType.TITLE_GENERATION,
        user_id="user-1",
        model_unique_id="ollama_cloud:llama3.2",
        payload={"session_id": "sess-1"},
    )
    id_b = await submit(
        job_type=JobType.TITLE_GENERATION,
        user_id="user-1",
        model_unique_id="ollama_cloud:llama3.2",
        payload={"session_id": "sess-2"},
    )

    assert id_a != id_b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_job_submit.py -v`
Expected: FAIL — `ImportError: cannot import name 'submit'`

- [ ] **Step 3: Implement submit**

```python
# backend/jobs/_submit.py
from datetime import datetime, timezone
from uuid import uuid4

from backend.database import get_redis
from backend.jobs._models import JobEntry, JobType


async def submit(
    job_type: JobType,
    user_id: str,
    model_unique_id: str,
    payload: dict,
    correlation_id: str | None = None,
) -> str:
    """Enqueue a background job into the Redis Stream.

    Returns the job ID (UUID).
    """
    job_id = str(uuid4())
    entry = JobEntry(
        id=job_id,
        job_type=job_type,
        user_id=user_id,
        model_unique_id=model_unique_id,
        payload=payload,
        correlation_id=correlation_id or str(uuid4()),
        created_at=datetime.now(timezone.utc),
    )

    redis = get_redis()
    await redis.xadd("jobs:pending", {"data": entry.model_dump_json()})
    return job_id
```

- [ ] **Step 4: Update public API**

Add to `backend/jobs/__init__.py`:

```python
"""Background job infrastructure — queue, consumer, per-user lock.

Public API: import only from this file.
"""

from backend.jobs._lock import get_user_lock
from backend.jobs._models import JobType
from backend.jobs._submit import submit

__all__ = [
    "get_user_lock",
    "submit",
    "JobType",
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_job_submit.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/jobs/_submit.py backend/jobs/__init__.py tests/test_job_submit.py
git commit -m "Add job submission to Redis Stream"
```

---

### Task 5: Consumer Loop

Implement the Redis Streams consumer that processes jobs with lock checking, retry logic, and timeout handling.

**Files:**
- Create: `backend/jobs/_consumer.py`
- Create: `backend/jobs/_retry.py`
- Modify: `backend/jobs/__init__.py`
- Create: `tests/test_job_consumer.py`

- [ ] **Step 1: Write the failing tests for retry state**

```python
# tests/test_job_consumer.py
import asyncio
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from backend.config import settings


@pytest_asyncio.fixture
async def redis(clean_db):
    from backend.database import connect_db, disconnect_db, get_redis
    await connect_db()
    try:
        yield get_redis()
    finally:
        await disconnect_db()


async def test_retry_state_roundtrip(redis):
    from backend.jobs._retry import set_retry, get_retry, clear_retry

    next_at = datetime(2026, 4, 4, 0, 1, 0, tzinfo=timezone.utc)
    await set_retry(redis, "job-1", attempt=2, next_retry_at=next_at)

    state = await get_retry(redis, "job-1")
    assert state is not None
    assert state["attempt"] == 2
    assert state["next_retry_at"] == next_at

    await clear_retry(redis, "job-1")
    assert await get_retry(redis, "job-1") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_job_consumer.py::test_retry_state_roundtrip -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement retry state management**

```python
# backend/jobs/_retry.py
from datetime import datetime, timezone

from redis.asyncio import Redis

_RETRY_TTL = 7200  # 2 hours


async def set_retry(
    redis: Redis,
    job_id: str,
    attempt: int,
    next_retry_at: datetime,
) -> None:
    """Store retry state for a job in Redis."""
    key = f"jobs:retry:{job_id}"
    await redis.hset(key, mapping={
        "attempt": str(attempt),
        "next_retry_at": next_retry_at.isoformat(),
    })
    await redis.expire(key, _RETRY_TTL)


async def get_retry(redis: Redis, job_id: str) -> dict | None:
    """Read retry state, or None if no retry is pending."""
    key = f"jobs:retry:{job_id}"
    data = await redis.hgetall(key)
    if not data:
        return None
    return {
        "attempt": int(data["attempt"]),
        "next_retry_at": datetime.fromisoformat(data["next_retry_at"]),
    }


async def clear_retry(redis: Redis, job_id: str) -> None:
    """Remove retry state after job completes or is discarded."""
    await redis.delete(f"jobs:retry:{job_id}")
```

- [ ] **Step 4: Run retry test to verify it passes**

Run: `uv run pytest tests/test_job_consumer.py::test_retry_state_roundtrip -v`
Expected: PASS

- [ ] **Step 5: Write the failing tests for the consumer loop**

Append to `tests/test_job_consumer.py`:

```python
async def _enqueue_job(redis, job_type="title_generation", user_id="user-1",
                       model_unique_id="ollama_cloud:llama3.2", payload=None,
                       correlation_id="corr-1", created_at=None):
    """Helper to push a job directly into the stream."""
    from backend.jobs._models import JobEntry, JobType

    entry = JobEntry(
        id=f"job-{id(payload)}",
        job_type=JobType(job_type),
        user_id=user_id,
        model_unique_id=model_unique_id,
        payload=payload or {},
        correlation_id=correlation_id,
        created_at=created_at or datetime.now(timezone.utc),
    )
    await redis.xadd("jobs:pending", {"data": entry.model_dump_json()})
    return entry


async def test_consumer_processes_job(redis):
    from backend.jobs._consumer import ensure_consumer_group, process_one
    from backend.jobs._models import JobConfig, JobType
    from backend.jobs._registry import JOB_REGISTRY

    handler = AsyncMock()
    original = JOB_REGISTRY[JobType.TITLE_GENERATION]
    JOB_REGISTRY[JobType.TITLE_GENERATION] = JobConfig(
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
        event_bus = AsyncMock()
        entry = await _enqueue_job(redis, payload={"session_id": "sess-1"})
        await ensure_consumer_group(redis)

        processed = await process_one(redis, event_bus)
        assert processed is True
        handler.assert_awaited_once()

        call_kwargs = handler.call_args.kwargs
        assert call_kwargs["job"].user_id == "user-1"
        assert call_kwargs["job"].payload == {"session_id": "sess-1"}
    finally:
        JOB_REGISTRY[JobType.TITLE_GENERATION] = original


async def test_consumer_skips_locked_user(redis):
    from backend.jobs._consumer import ensure_consumer_group, process_one
    from backend.jobs._lock import get_user_lock

    event_bus = AsyncMock()
    entry = await _enqueue_job(redis, payload={"a": 1})
    await ensure_consumer_group(redis)

    lock = get_user_lock("user-1")
    await lock.acquire()

    try:
        processed = await process_one(redis, event_bus)
        assert processed is False  # Skipped because lock is held
    finally:
        lock.release()


async def test_consumer_expires_old_job(redis):
    from backend.jobs._consumer import ensure_consumer_group, process_one

    event_bus = AsyncMock()
    old_time = datetime.now(timezone.utc) - timedelta(hours=2)
    entry = await _enqueue_job(redis, payload={"old": True}, created_at=old_time)
    await ensure_consumer_group(redis)

    processed = await process_one(redis, event_bus)
    assert processed is True  # Processed (expired)

    # Check that a JOB_EXPIRED event was published
    event_bus.publish.assert_called()
    call_args = event_bus.publish.call_args_list
    topics = [c.args[0] for c in call_args]
    assert "job.expired" in topics
```

- [ ] **Step 6: Run consumer tests to verify they fail**

Run: `uv run pytest tests/test_job_consumer.py -v -k "not retry_state"`
Expected: FAIL — `ImportError: cannot import name 'ensure_consumer_group'`

- [ ] **Step 7: Implement the consumer**

```python
# backend/jobs/_consumer.py
import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta

from redis.asyncio import Redis

from backend.jobs._lock import get_user_lock
from backend.jobs._models import JobEntry
from backend.jobs._registry import JOB_REGISTRY
from backend.jobs._retry import set_retry, get_retry, clear_retry
from shared.events.jobs import (
    JobCompletedEvent, JobExpiredEvent, JobFailedEvent,
    JobRetryEvent, JobStartedEvent,
)
from shared.topics import Topics

_log = logging.getLogger(__name__)

_STREAM = "jobs:pending"
_GROUP = "workers"
_CONSUMER_NAME = "consumer-1"


async def ensure_consumer_group(redis: Redis) -> None:
    """Create the consumer group if it does not already exist."""
    try:
        await redis.xgroup_create(_STREAM, _GROUP, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" in str(exc):
            pass  # Group already exists
        else:
            raise


async def process_one(redis: Redis, event_bus) -> bool:
    """Read and process a single job from the stream.

    Returns True if a job was processed (success, failure, or expiry).
    Returns False if no job was available or the job was skipped (locked user).
    """
    # First check pending entries (retries, previously unacked)
    entries = await redis.xreadgroup(
        _GROUP, _CONSUMER_NAME, {_STREAM: "0"}, count=1,
    )

    pending_job = True
    if not entries or not entries[0][1]:
        # No pending — read new entries
        entries = await redis.xreadgroup(
            _GROUP, _CONSUMER_NAME, {_STREAM: ">"}, count=1, block=5000,
        )
        pending_job = False

    if not entries or not entries[0][1]:
        return False

    stream_id, fields = entries[0][1][0]
    job = JobEntry.model_validate_json(fields["data"])

    config = JOB_REGISTRY.get(job.job_type)
    if config is None:
        _log.error("Unknown job type: %s — acknowledging and discarding", job.job_type)
        await redis.xack(_STREAM, _GROUP, stream_id)
        return True

    now = datetime.now(timezone.utc)

    # Check queue timeout
    if (now - job.created_at).total_seconds() > config.queue_timeout_seconds:
        await event_bus.publish(
            Topics.JOB_EXPIRED,
            JobExpiredEvent(
                job_id=job.id,
                job_type=job.job_type,
                correlation_id=job.correlation_id,
                waited_seconds=(now - job.created_at).total_seconds(),
                timestamp=now,
            ),
            target_user_ids=[job.user_id],
            correlation_id=job.correlation_id,
        )
        await clear_retry(redis, job.id)
        await redis.xack(_STREAM, _GROUP, stream_id)
        return True

    # Check retry timing
    retry_state = await get_retry(redis, job.id)
    if retry_state and retry_state["next_retry_at"] > now:
        return False  # Not yet time — leave unacked

    # Update attempt from retry state if available
    if retry_state:
        job.attempt = retry_state["attempt"]

    # Check per-user lock (non-blocking)
    lock = get_user_lock(job.user_id)
    if lock.locked():
        return False  # User busy — leave unacked for next iteration

    # Execute the job
    await event_bus.publish(
        Topics.JOB_STARTED,
        JobStartedEvent(
            job_id=job.id,
            job_type=job.job_type,
            correlation_id=job.correlation_id,
            timestamp=now,
        ),
        target_user_ids=[job.user_id],
        correlation_id=job.correlation_id,
    )

    try:
        async with asyncio.timeout(config.execution_timeout_seconds):
            async with lock:
                await config.handler(
                    job=job,
                    config=config,
                    redis=redis,
                    event_bus=event_bus,
                )

        # Success
        await event_bus.publish(
            Topics.JOB_COMPLETED,
            JobCompletedEvent(
                job_id=job.id,
                job_type=job.job_type,
                correlation_id=job.correlation_id,
                timestamp=datetime.now(timezone.utc),
            ),
            target_user_ids=[job.user_id],
            correlation_id=job.correlation_id,
        )
        await clear_retry(redis, job.id)
        await redis.xack(_STREAM, _GROUP, stream_id)
        return True

    except Exception as exc:
        attempt = job.attempt + 1
        now = datetime.now(timezone.utc)

        if attempt >= config.max_retries:
            # Final failure
            should_notify = config.notify or config.notify_error
            if should_notify:
                await event_bus.publish(
                    Topics.JOB_FAILED,
                    JobFailedEvent(
                        job_id=job.id,
                        job_type=job.job_type,
                        correlation_id=job.correlation_id,
                        attempt=attempt,
                        max_retries=config.max_retries,
                        error_message=str(exc),
                        recoverable=False,
                        timestamp=now,
                    ),
                    target_user_ids=[job.user_id],
                    correlation_id=job.correlation_id,
                )
            await clear_retry(redis, job.id)
            await redis.xack(_STREAM, _GROUP, stream_id)
            _log.warning("Job %s failed after %d attempts: %s", job.id, attempt, exc)
            return True
        else:
            # Schedule retry
            next_retry_at = now + timedelta(seconds=config.retry_delay_seconds)
            await set_retry(redis, job.id, attempt=attempt, next_retry_at=next_retry_at)
            await event_bus.publish(
                Topics.JOB_RETRY,
                JobRetryEvent(
                    job_id=job.id,
                    job_type=job.job_type,
                    correlation_id=job.correlation_id,
                    attempt=attempt,
                    next_retry_at=next_retry_at,
                    timestamp=now,
                ),
                target_user_ids=[job.user_id],
                correlation_id=job.correlation_id,
            )
            _log.info("Job %s retry %d/%d scheduled at %s", job.id, attempt, config.max_retries, next_retry_at)
            return False


async def consumer_loop(redis: Redis, event_bus) -> None:
    """Main consumer loop — runs indefinitely as a background task."""
    await ensure_consumer_group(redis)
    _log.info("Job consumer started")

    while True:
        try:
            await process_one(redis, event_bus)
        except asyncio.CancelledError:
            _log.info("Job consumer shutting down")
            break
        except Exception:
            _log.exception("Unexpected error in job consumer loop")
            await asyncio.sleep(1)
```

- [ ] **Step 8: Update public API**

Update `backend/jobs/__init__.py`:

```python
"""Background job infrastructure — queue, consumer, per-user lock.

Public API: import only from this file.
"""

from backend.jobs._consumer import consumer_loop, ensure_consumer_group
from backend.jobs._lock import get_user_lock
from backend.jobs._models import JobType
from backend.jobs._submit import submit

__all__ = [
    "consumer_loop",
    "ensure_consumer_group",
    "get_user_lock",
    "submit",
    "JobType",
]
```

- [ ] **Step 9: Run consumer tests to verify they pass**

Run: `uv run pytest tests/test_job_consumer.py -v`
Expected: PASS (4 tests)

- [ ] **Step 10: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

- [ ] **Step 11: Commit**

```bash
git add backend/jobs/_consumer.py backend/jobs/_retry.py backend/jobs/__init__.py tests/test_job_consumer.py
git commit -m "Add Redis Streams consumer loop with retry and timeout handling"
```

---

### Task 6: Chat Module — Title Field and Update API

Add a `title` field to chat sessions and expose an update method, plus the corresponding event.

**Files:**
- Modify: `shared/dtos/chat.py`
- Modify: `shared/events/chat.py`
- Modify: `shared/topics.py`
- Modify: `backend/ws/event_bus.py`
- Modify: `backend/modules/chat/_repository.py`
- Modify: `backend/modules/chat/__init__.py`
- Create: `tests/test_chat_title.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_chat_title.py
from datetime import datetime, timezone

import pytest


def test_chat_session_dto_has_title():
    from shared.dtos.chat import ChatSessionDto

    dto = ChatSessionDto(
        id="sess-1",
        user_id="user-1",
        persona_id="persona-1",
        model_unique_id="ollama_cloud:llama3.2",
        state="idle",
        title=None,
        created_at=datetime(2026, 4, 4, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 4, tzinfo=timezone.utc),
    )
    assert dto.title is None

    dto2 = ChatSessionDto(
        id="sess-2",
        user_id="user-1",
        persona_id="persona-1",
        model_unique_id="ollama_cloud:llama3.2",
        state="idle",
        title="My chat",
        created_at=datetime(2026, 4, 4, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 4, tzinfo=timezone.utc),
    )
    assert dto2.title == "My chat"


def test_chat_session_title_updated_event():
    from shared.events.chat import ChatSessionTitleUpdatedEvent

    event = ChatSessionTitleUpdatedEvent(
        session_id="sess-1",
        title="Generated title",
        correlation_id="corr-1",
        timestamp=datetime(2026, 4, 4, tzinfo=timezone.utc),
    )
    assert event.type == "chat.session.title_updated"


def test_topic_exists():
    from shared.topics import Topics

    assert Topics.CHAT_SESSION_TITLE_UPDATED == "chat.session.title_updated"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_chat_title.py -v`
Expected: FAIL

- [ ] **Step 3: Add title to ChatSessionDto**

In `shared/dtos/chat.py`, add `title` field to `ChatSessionDto`:

```python
class ChatSessionDto(BaseModel):
    id: str
    user_id: str
    persona_id: str
    model_unique_id: str
    state: Literal["idle", "streaming", "requires_action"]
    title: str | None = None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 4: Add ChatSessionTitleUpdatedEvent**

Add to `shared/events/chat.py`:

```python
class ChatSessionTitleUpdatedEvent(BaseModel):
    type: str = "chat.session.title_updated"
    session_id: str
    title: str
    correlation_id: str
    timestamp: datetime
```

- [ ] **Step 5: Add topic constant**

Add to `shared/topics.py` in the chat section:

```python
    CHAT_SESSION_TITLE_UPDATED = "chat.session.title_updated"
```

- [ ] **Step 6: Add fan-out rule**

Add to `_FANOUT` in `backend/ws/event_bus.py`:

```python
    Topics.CHAT_SESSION_TITLE_UPDATED: ([], True),
```

- [ ] **Step 7: Add update_session_title to ChatRepository**

Add to `backend/modules/chat/_repository.py` after `update_session_state`:

```python
    async def update_session_title(self, session_id: str, title: str) -> dict | None:
        """Set the title of a chat session."""
        now = datetime.now(UTC)
        await self._sessions.update_one(
            {"_id": session_id},
            {"$set": {"title": title, "updated_at": now}},
        )
        return await self._sessions.find_one({"_id": session_id})
```

- [ ] **Step 8: Update session_to_dto to include title**

In `backend/modules/chat/_repository.py`, update `session_to_dto`:

```python
    @staticmethod
    def session_to_dto(doc: dict) -> ChatSessionDto:
        return ChatSessionDto(
            id=doc["_id"],
            user_id=doc["user_id"],
            persona_id=doc["persona_id"],
            model_unique_id=doc["model_unique_id"],
            state=doc["state"],
            title=doc.get("title"),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )
```

- [ ] **Step 9: Add update_session_title to chat module public API**

Add to `backend/modules/chat/__init__.py` a new public function and export it:

```python
async def update_session_title(session_id: str, title: str, user_id: str, correlation_id: str) -> None:
    """Update a session's title and publish the change event."""
    db = get_db()
    repo = ChatRepository(db)
    await repo.update_session_title(session_id, title)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.CHAT_SESSION_TITLE_UPDATED,
        ChatSessionTitleUpdatedEvent(
            session_id=session_id,
            title=title,
            correlation_id=correlation_id,
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )
```

Add `ChatSessionTitleUpdatedEvent` to imports from `shared.events.chat` and add `update_session_title` to `__all__`.

- [ ] **Step 10: Run tests**

Run: `uv run pytest tests/test_chat_title.py -v`
Expected: PASS (3 tests)

Run: `uv run pytest -v`
Expected: All tests pass

- [ ] **Step 11: Commit**

```bash
git add shared/dtos/chat.py shared/events/chat.py shared/topics.py backend/ws/event_bus.py backend/modules/chat/_repository.py backend/modules/chat/__init__.py tests/test_chat_title.py
git commit -m "Add title field to chat sessions with update API and event"
```

---

### Task 7: Title Generation Handler

Implement the actual handler that generates a title using the LLM.

**Files:**
- Create: `backend/jobs/handlers/__init__.py`
- Create: `backend/jobs/handlers/_title_generation.py`
- Modify: `backend/jobs/_registry.py` (wire real handler)
- Create: `tests/test_title_generation_handler.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_title_generation_handler.py
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from backend.jobs._models import JobConfig, JobEntry, JobType
from backend.modules.llm._adapters._events import ContentDelta, StreamDone


def _make_job(session_id: str = "sess-1") -> JobEntry:
    from datetime import datetime, timezone
    return JobEntry(
        id="job-1",
        job_type=JobType.TITLE_GENERATION,
        user_id="user-1",
        model_unique_id="ollama_cloud:llama3.2",
        payload={"session_id": session_id, "messages": [
            {"role": "user", "content": "Tell me about black holes"},
            {"role": "assistant", "content": "Black holes are fascinating regions of spacetime..."},
        ]},
        correlation_id="corr-1",
        created_at=datetime(2026, 4, 4, tzinfo=timezone.utc),
    )


def _make_config() -> JobConfig:
    from backend.jobs.handlers._title_generation import handle_title_generation
    return JobConfig(
        handler=handle_title_generation,
        execution_timeout_seconds=60.0,
        reasoning_enabled=False,
        notify=False,
        notify_error=True,
    )


async def test_handler_generates_and_saves_title():
    from backend.jobs.handlers._title_generation import handle_title_generation

    async def _mock_stream(*args, **kwargs):
        yield ContentDelta(delta="Black Holes")
        yield ContentDelta(delta=" Explained")
        yield StreamDone(input_tokens=50, output_tokens=5)

    mock_update = AsyncMock()
    event_bus = AsyncMock()

    with patch("backend.jobs.handlers._title_generation.llm_stream_completion", side_effect=_mock_stream), \
         patch("backend.jobs.handlers._title_generation.update_session_title", mock_update):

        job = _make_job()
        config = _make_config()
        await handle_title_generation(
            job=job,
            config=config,
            redis=AsyncMock(),
            event_bus=event_bus,
        )

    mock_update.assert_awaited_once()
    call_kwargs = mock_update.call_args.kwargs
    assert call_kwargs["session_id"] == "sess-1"
    assert call_kwargs["title"] == "Black Holes Explained"
    assert call_kwargs["user_id"] == "user-1"
    assert call_kwargs["correlation_id"] == "corr-1"


async def test_handler_strips_quotes_from_title():
    from backend.jobs.handlers._title_generation import handle_title_generation

    async def _mock_stream(*args, **kwargs):
        yield ContentDelta(delta='"Black Holes Explained"')
        yield StreamDone()

    mock_update = AsyncMock()

    with patch("backend.jobs.handlers._title_generation.llm_stream_completion", side_effect=_mock_stream), \
         patch("backend.jobs.handlers._title_generation.update_session_title", mock_update):

        await handle_title_generation(
            job=_make_job(),
            config=_make_config(),
            redis=AsyncMock(),
            event_bus=AsyncMock(),
        )

    assert mock_update.call_args.kwargs["title"] == "Black Holes Explained"


async def test_handler_truncates_long_title():
    from backend.jobs.handlers._title_generation import handle_title_generation

    long_text = "A" * 100

    async def _mock_stream(*args, **kwargs):
        yield ContentDelta(delta=long_text)
        yield StreamDone()

    mock_update = AsyncMock()

    with patch("backend.jobs.handlers._title_generation.llm_stream_completion", side_effect=_mock_stream), \
         patch("backend.jobs.handlers._title_generation.update_session_title", mock_update):

        await handle_title_generation(
            job=_make_job(),
            config=_make_config(),
            redis=AsyncMock(),
            event_bus=AsyncMock(),
        )

    title = mock_update.call_args.kwargs["title"]
    assert len(title) <= 64


async def test_handler_raises_on_stream_error():
    from backend.jobs.handlers._title_generation import handle_title_generation
    from backend.modules.llm._adapters._events import StreamError

    async def _mock_stream(*args, **kwargs):
        yield StreamError(error_code="provider_unavailable", message="Down")

    with patch("backend.jobs.handlers._title_generation.llm_stream_completion", side_effect=_mock_stream), \
         patch("backend.jobs.handlers._title_generation.update_session_title", AsyncMock()):

        with pytest.raises(RuntimeError, match="provider_unavailable"):
            await handle_title_generation(
                job=_make_job(),
                config=_make_config(),
                redis=AsyncMock(),
                event_bus=AsyncMock(),
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_title_generation_handler.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement the handler**

```python
# backend/jobs/handlers/__init__.py
```

```python
# backend/jobs/handlers/_title_generation.py
import logging

from backend.jobs._models import JobEntry, JobConfig
from backend.modules.chat import update_session_title
from backend.modules.llm import stream_completion as llm_stream_completion
from backend.modules.llm._adapters._events import ContentDelta, StreamDone, StreamError
from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart

_log = logging.getLogger(__name__)

_MAX_TITLE_LENGTH = 64

_SYSTEM_PROMPT = (
    "Generate a short, descriptive title for the following conversation. "
    "Respond with ONLY the title — no quotes, no explanation, no punctuation at the end. "
    "Maximum 60 characters. Use the language of the conversation."
)


def _clean_title(raw: str) -> str:
    """Strip quotes, whitespace, trailing punctuation, and truncate."""
    title = raw.strip().strip('"\'').strip()
    if title.endswith("."):
        title = title[:-1].strip()
    if len(title) > _MAX_TITLE_LENGTH:
        # Truncate at last space before limit to avoid cutting words
        truncated = title[:_MAX_TITLE_LENGTH]
        last_space = truncated.rfind(" ")
        if last_space > _MAX_TITLE_LENGTH // 2:
            title = truncated[:last_space]
        else:
            title = truncated
    return title


async def handle_title_generation(
    job: JobEntry,
    config: JobConfig,
    redis,
    event_bus,
) -> None:
    """Generate a title for a chat session using the same model as the chat."""
    provider_id, model_slug = job.model_unique_id.split(":", 1)
    messages_data = job.payload.get("messages", [])

    messages = [
        CompletionMessage(
            role="system",
            content=[ContentPart(type="text", text=_SYSTEM_PROMPT)],
        ),
    ]
    for msg in messages_data:
        messages.append(CompletionMessage(
            role=msg["role"],
            content=[ContentPart(type="text", text=msg["content"])],
        ))

    request = CompletionRequest(
        model=model_slug,
        messages=messages,
        temperature=0.3,
        reasoning_enabled=False,
    )

    full_content = ""
    async for event in llm_stream_completion(job.user_id, provider_id, request):
        match event:
            case ContentDelta(delta=delta):
                full_content += delta
            case StreamDone():
                break
            case StreamError() as err:
                raise RuntimeError(f"Title generation failed: {err.error_code} — {err.message}")

    title = _clean_title(full_content)
    if not title:
        _log.warning("Title generation produced empty result for job %s", job.id)
        return

    await update_session_title(
        session_id=job.payload["session_id"],
        title=title,
        user_id=job.user_id,
        correlation_id=job.correlation_id,
    )
    _log.info("Generated title '%s' for session %s", title, job.payload["session_id"])
```

- [ ] **Step 4: Wire the real handler into the registry**

Replace `backend/jobs/_registry.py`:

```python
# backend/jobs/_registry.py
from backend.jobs._models import JobConfig, JobType
from backend.jobs.handlers._title_generation import handle_title_generation

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

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_title_generation_handler.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
git add backend/jobs/handlers/__init__.py backend/jobs/handlers/_title_generation.py backend/jobs/_registry.py tests/test_title_generation_handler.py
git commit -m "Add title generation handler for background jobs"
```

---

### Task 8: Lifespan Integration and Title Generation Trigger

Wire the consumer loop into FastAPI lifespan and trigger title generation after the first assistant response.

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/modules/chat/__init__.py`

- [ ] **Step 1: Update FastAPI lifespan to start the consumer**

In `backend/main.py`, add the consumer startup. Add imports:

```python
import asyncio
from backend.jobs import consumer_loop, ensure_consumer_group
```

Update the lifespan to start the consumer task and cancel it on shutdown:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    db = get_db()
    redis = get_redis()
    await user_init_indexes(db)
    await llm_init_indexes(db)
    await persona_init_indexes(db)
    await settings_init_indexes(db)
    await chat_init_indexes(db)
    manager = ConnectionManager()
    set_manager(manager)
    event_bus = EventBus(redis=redis, manager=manager)
    set_event_bus(event_bus)

    # Start background job consumer
    consumer_task = asyncio.create_task(consumer_loop(redis, event_bus))

    yield

    # Shut down consumer
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass

    await disconnect_db()
```

- [ ] **Step 2: Trigger title generation in chat module**

In `backend/modules/chat/__init__.py`, add the title generation trigger. Add imports at the top:

```python
from backend.jobs import submit, JobType
```

In the `_run_inference` function, inside the `save_fn` closure, after saving the assistant message, check if this is the first assistant message and submit a title generation job. Replace the `save_fn` definition (around line 175) with:

```python
    async def save_fn(content: str, thinking: str | None, usage: dict | None) -> None:
        token_count = count_tokens(content)
        await repo.save_message(
            session_id,
            role="assistant",
            content=content,
            token_count=token_count,
            thinking=thinking,
        )
        await repo.update_session_state(session_id, "idle")

        # Trigger title generation after first assistant response
        if not session.get("title"):
            messages = await repo.list_messages(session_id)
            if len(messages) >= 2:
                # Get first user + first assistant message for title context
                first_user = next((m for m in messages if m["role"] == "user"), None)
                first_assistant = next((m for m in messages if m["role"] == "assistant"), None)
                if first_user and first_assistant:
                    await submit(
                        job_type=JobType.TITLE_GENERATION,
                        user_id=user_id,
                        model_unique_id=model_unique_id,
                        payload={
                            "session_id": session_id,
                            "messages": [
                                {"role": "user", "content": first_user["content"]},
                                {"role": "assistant", "content": first_assistant["content"]},
                            ],
                        },
                        correlation_id=correlation_id,
                    )
```

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add backend/main.py backend/modules/chat/__init__.py
git commit -m "Wire consumer loop into lifespan and trigger title generation"
```

---

### Task 9: Integration Test

End-to-end test that submits a job and verifies the consumer processes it.

**Files:**
- Create: `tests/test_job_integration.py`

- [ ] **Step 1: Write the integration test**

```python
# tests/test_job_integration.py
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from backend.jobs._models import JobConfig, JobEntry, JobType


@pytest_asyncio.fixture
async def redis(clean_db):
    from backend.database import connect_db, disconnect_db, get_redis
    await connect_db()
    try:
        yield get_redis()
    finally:
        await disconnect_db()


async def test_submit_and_consume_roundtrip(redis):
    """Submit a job via the public API and verify the consumer processes it."""
    from backend.jobs import submit
    from backend.jobs._consumer import ensure_consumer_group, process_one
    from backend.jobs._models import JobType
    from backend.jobs._registry import JOB_REGISTRY

    handler = AsyncMock()
    original = JOB_REGISTRY[JobType.TITLE_GENERATION]
    JOB_REGISTRY[JobType.TITLE_GENERATION] = JobConfig(
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
        event_bus = AsyncMock()
        await ensure_consumer_group(redis)

        job_id = await submit(
            job_type=JobType.TITLE_GENERATION,
            user_id="user-1",
            model_unique_id="ollama_cloud:llama3.2",
            payload={"session_id": "sess-1", "messages": []},
            correlation_id="corr-1",
        )

        processed = await process_one(redis, event_bus)
        assert processed is True
        handler.assert_awaited_once()
        assert handler.call_args.kwargs["job"].id == job_id

        # Verify JOB_STARTED and JOB_COMPLETED events were published
        topics = [c.args[0] for c in event_bus.publish.call_args_list]
        assert "job.started" in topics
        assert "job.completed" in topics
    finally:
        JOB_REGISTRY[JobType.TITLE_GENERATION] = original


async def test_retry_on_handler_failure(redis):
    """Verify that a failing handler triggers retry logic."""
    from backend.jobs import submit
    from backend.jobs._consumer import ensure_consumer_group, process_one
    from backend.jobs._models import JobType
    from backend.jobs._registry import JOB_REGISTRY

    handler = AsyncMock(side_effect=RuntimeError("Boom"))
    original = JOB_REGISTRY[JobType.TITLE_GENERATION]
    JOB_REGISTRY[JobType.TITLE_GENERATION] = JobConfig(
        handler=handler,
        max_retries=2,
        retry_delay_seconds=0.1,  # Short for testing
        queue_timeout_seconds=3600.0,
        execution_timeout_seconds=60.0,
        reasoning_enabled=False,
        notify=False,
        notify_error=True,
    )

    try:
        event_bus = AsyncMock()
        await ensure_consumer_group(redis)

        await submit(
            job_type=JobType.TITLE_GENERATION,
            user_id="user-retry",
            model_unique_id="ollama_cloud:llama3.2",
            payload={"session_id": "sess-retry"},
        )

        # First attempt — should schedule retry
        result = await process_one(redis, event_bus)
        # Result is False because retry was scheduled (not acked)
        assert result is False

        topics = [c.args[0] for c in event_bus.publish.call_args_list]
        assert "job.started" in topics
        assert "job.retry" in topics

        # Wait for retry delay
        await asyncio.sleep(0.2)

        # Second attempt — should fail permanently (max_retries=2)
        event_bus.reset_mock()
        result = await process_one(redis, event_bus)
        assert result is True  # Acked after final failure

        topics = [c.args[0] for c in event_bus.publish.call_args_list]
        assert "job.failed" in topics
    finally:
        JOB_REGISTRY[JobType.TITLE_GENERATION] = original
```

- [ ] **Step 2: Run integration tests**

Run: `uv run pytest tests/test_job_integration.py -v`
Expected: PASS (2 tests)

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_job_integration.py
git commit -m "Add integration tests for job submit and consume roundtrip"
```

---

### Task 10: Final Verification and Merge

Verify everything works together, clean up, and merge.

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -v --tb=short`
Expected: All tests pass

- [ ] **Step 2: Verify module boundaries**

Check that no internal imports leak across modules:

Run: `rg "from backend.jobs._" --type py --glob "!backend/jobs/*" --glob "!tests/*"`
Expected: No results (only `backend/modules/chat/_inference.py` imports from `backend.jobs`, using the public API)

- [ ] **Step 3: Verify file structure**

Run: `find backend/jobs -type f | sort`
Expected:
```
backend/jobs/__init__.py
backend/jobs/_consumer.py
backend/jobs/_lock.py
backend/jobs/_models.py
backend/jobs/_registry.py
backend/jobs/_retry.py
backend/jobs/_submit.py
backend/jobs/handlers/__init__.py
backend/jobs/handlers/_title_generation.py
```

- [ ] **Step 4: Commit any final adjustments and merge to master**

```bash
git checkout master
git merge --no-ff <branch> -m "Add background LLM job system with title generation"
```

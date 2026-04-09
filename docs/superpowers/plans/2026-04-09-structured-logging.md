# Structured Logging (structlog) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce structlog-based structured logging with dual sinks (pretty console + JSON rotating file locally; JSON console only in Docker), a stdlib bridge so existing `logging.getLogger(...)` call sites keep working, and full instrumentation of the jobs subsystem (enqueue, consume, lock, retry, disconnect-retry, Redis `jobs:*` writes/deletes).

**Architecture:**
- New module `backend/_logging.py` owns logging configuration. Called exactly once from `backend/main.py` as the first action, replacing the current `logging.basicConfig` block.
- structlog is configured with a `contextvars` merger so `correlation_id`, `user_id`, `job_id`, `job_type`, `lock_key` etc. can be bound once and appear in every downstream log event automatically.
- Both structlog-native loggers and the stdlib `logging` hierarchy route through a single `ProcessorFormatter`, so uvicorn/fastapi/pymongo logs come out in the same shape as our own.
- Two handlers are attached to the root logger depending on env:
  - Console handler (always on by default): `pretty` colourful renderer locally, `json` in Docker.
  - File handler (on by default, off in Docker): `TimedRotatingFileHandler` writing JSON lines to `backend/logs/chatsune.log`, daily rotation, 14 backups.
- Event names become stable dotted identifiers (e.g. `job.enqueued`, `job.lock.acquired`) carried in structlog's `event` field, while the logger namespace (`chatsune.jobs.consumer`) stays in the `logger` field. Two filter axes in lnav/jq.

**Tech Stack:** Python 3.12+, structlog, stdlib `logging`, `logging.handlers.TimedRotatingFileHandler`, FastAPI, uv.

---

## File Structure

**Create:**
- `backend/_logging.py` — single source of truth for logging config. Exports `configure_logging()` and `get_logger(name)`.
- `tests/backend/test_logging.py` — unit tests for the logging config (processor chain, env switches, stdlib bridge, context binding).
- `backend/logs/.gitkeep` — not created; directory is gitignored and created at runtime.

**Modify:**
- `backend/main.py:1-23` — replace `logging.basicConfig(...)` block with `from backend._logging import configure_logging; configure_logging()` as the very first executable statement after imports of `os`/`sys`.
- `backend/config.py` — add logging-related settings (`log_console`, `log_console_format`, `log_file`, `log_file_path`, `log_level`, `log_level_uvicorn_access`, `log_level_third_party`).
- `backend/jobs/_submit.py` — instrument `enqueue_job` / submit path with structured `job.enqueued` / `job.enqueue.failed` events.
- `backend/jobs/_consumer.py` — replace existing `_log.*` calls with structlog, using bound `job_id`, `job_type`, `attempt`. Events: `job.consumer.started`, `job.consumer.shutdown`, `job.received`, `job.completed`, `job.failed`, `job.retry.scheduled`, `job.timeout`, `job.unknown_type`, `job.pel.zombie_dropped`, `job.exception`.
- `backend/jobs/_lock.py` — instrument acquire/release/contention with events `job.lock.acquired`, `job.lock.released`, `job.lock.contended`, `job.lock.expired`. Bind `lock_key`, `holder`, `ttl_ms`.
- `backend/jobs/_disconnect_retry.py` — events `job.disconnect_retry.loop_started`, `job.disconnect_retry.requeued`, `job.disconnect_retry.loop_error`.
- `backend/jobs/_retry.py` — events `job.retry.computed`, `job.retry.exhausted`.
- `backend/jobs/_dedup.py` — events `job.dedup.hit`, `job.dedup.miss`, `job.dedup.key_written`, `job.dedup.key_deleted`. Every Redis `jobs:*` write/delete gets a log line with `redis_key`.
- `backend/jobs/_inspect.py` — structlog logger, no behavioural change.
- `backend/jobs/handlers/_title_generation.py`, `_memory_consolidation.py`, `_memory_extraction.py`, `_budget_helpers.py` — swap `logging.getLogger(__name__)` → `structlog.get_logger(__name__)`. No event name rewrite in this plan — they keep their current messages but gain structured context automatically via contextvars.
- `.gitignore` — add `backend/logs/`.
- `pyproject.toml` — add `structlog>=24.1` to dependencies.
- `compose.yml` / `docker-compose.yml` (whichever exists) — set env vars `LOG_CONSOLE_FORMAT=json` and `LOG_FILE=0` for the backend service.
- `README.md` — add short "Logging" section documenting env vars and log file location.
- `.env.example` — add the new `LOG_*` variables with defaults and comments.

**Test:**
- `tests/backend/test_logging.py`

---

## Task 1: Add structlog dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dependency**

Open `pyproject.toml` and add `"structlog>=24.1"` to the `[project].dependencies` (or `[tool.uv]` dependencies, whichever the project uses — inspect the file first).

- [ ] **Step 2: Sync**

Run: `uv sync`
Expected: structlog installed, no errors.

- [ ] **Step 3: Verify import**

Run: `uv run python -c "import structlog; print(structlog.__version__)"`
Expected: prints a version >= 24.1.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "Add structlog dependency"
```

---

## Task 2: Logging settings in config

**Files:**
- Modify: `backend/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Read current config.py**

Read `backend/config.py` fully so you know the Settings class style (Pydantic BaseSettings vs plain dataclass). Match it exactly for the new fields.

- [ ] **Step 2: Add fields**

Add these fields to the Settings class (adapt syntax to whatever pattern the file uses — the example below assumes Pydantic `BaseSettings` with `Field`):

```python
# Logging
log_level: str = Field(default="INFO", alias="LOG_LEVEL")
log_console: bool = Field(default=True, alias="LOG_CONSOLE")
log_console_format: str = Field(default="pretty", alias="LOG_CONSOLE_FORMAT")  # "pretty" or "json"
log_file: bool = Field(default=True, alias="LOG_FILE")
log_file_path: str = Field(default="backend/logs/chatsune.log", alias="LOG_FILE_PATH")
log_file_backup_count: int = Field(default=14, alias="LOG_FILE_BACKUP_COUNT")
log_level_uvicorn_access: str = Field(default="WARNING", alias="LOG_LEVEL_UVICORN_ACCESS")
log_level_third_party: str = Field(default="WARNING", alias="LOG_LEVEL_THIRD_PARTY")
```

- [ ] **Step 3: Update `.env.example`**

Append to `.env.example`:

```dotenv
# Logging
LOG_LEVEL=INFO
LOG_CONSOLE=1
# "pretty" for human-readable colourful console output, "json" for machine-parseable.
# Overridden to "json" in docker-compose.yml.
LOG_CONSOLE_FORMAT=pretty
LOG_FILE=1
LOG_FILE_PATH=backend/logs/chatsune.log
LOG_FILE_BACKUP_COUNT=14
LOG_LEVEL_UVICORN_ACCESS=WARNING
LOG_LEVEL_THIRD_PARTY=WARNING
```

- [ ] **Step 4: Verify config loads**

Run: `uv run python -c "from backend.config import settings; print(settings.log_level, settings.log_console_format, settings.log_file_path)"`
Expected: `INFO pretty backend/logs/chatsune.log`

- [ ] **Step 5: Commit**

```bash
git add backend/config.py .env.example
git commit -m "Add logging configuration settings"
```

---

## Task 3: Gitignore logs directory

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add entry**

Append to `.gitignore`:

```gitignore
# Runtime log files
backend/logs/
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "Ignore backend/logs runtime directory"
```

---

## Task 4: Write failing test for logging configuration

**Files:**
- Create: `tests/backend/test_logging.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for backend._logging — structured logging configuration."""
import json
import logging
import os
from pathlib import Path

import pytest
import structlog


def _reset_logging():
    """Reset stdlib logging state between tests."""
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    structlog.reset_defaults()


@pytest.fixture(autouse=True)
def _isolate():
    _reset_logging()
    yield
    _reset_logging()


def test_configure_logging_is_importable():
    from backend._logging import configure_logging, get_logger
    assert callable(configure_logging)
    assert callable(get_logger)


def test_console_json_format_emits_valid_json(capsys):
    from backend._logging import configure_logging, get_logger

    configure_logging(
        level="INFO",
        console=True,
        console_format="json",
        file=False,
    )
    log = get_logger("chatsune.test")
    log.info("job.enqueued", job_id="abc123", job_type="extraction")

    captured = capsys.readouterr()
    line = (captured.err or captured.out).strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["event"] == "job.enqueued"
    assert payload["job_id"] == "abc123"
    assert payload["job_type"] == "extraction"
    assert payload["level"] == "info"
    assert payload["logger"] == "chatsune.test"
    assert "timestamp" in payload


def test_stdlib_logger_routes_through_structlog(capsys):
    from backend._logging import configure_logging

    configure_logging(level="INFO", console=True, console_format="json", file=False)
    stdlib_log = logging.getLogger("chatsune.stdlib_bridge_test")
    stdlib_log.info("legacy message %s", "value")

    captured = capsys.readouterr()
    line = (captured.err or captured.out).strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["logger"] == "chatsune.stdlib_bridge_test"
    assert "legacy message value" in payload["event"]


def test_context_binding_propagates(capsys):
    from backend._logging import configure_logging, get_logger

    configure_logging(level="INFO", console=True, console_format="json", file=False)
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-42", job_id="job-7")
    log = get_logger("chatsune.test")
    log.info("job.started")
    structlog.contextvars.clear_contextvars()

    captured = capsys.readouterr()
    line = (captured.err or captured.out).strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["correlation_id"] == "corr-42"
    assert payload["job_id"] == "job-7"


def test_file_handler_writes_json(tmp_path):
    from backend._logging import configure_logging, get_logger

    log_path = tmp_path / "chatsune.log"
    configure_logging(
        level="INFO",
        console=False,
        console_format="json",
        file=True,
        file_path=str(log_path),
    )
    log = get_logger("chatsune.test")
    log.info("job.completed", job_id="z")

    # Flush all handlers
    for h in logging.getLogger().handlers:
        h.flush()

    assert log_path.exists()
    content = log_path.read_text().strip()
    payload = json.loads(content.splitlines()[-1])
    assert payload["event"] == "job.completed"
    assert payload["job_id"] == "z"


def test_third_party_loggers_muted(capsys):
    from backend._logging import configure_logging

    configure_logging(
        level="INFO",
        console=True,
        console_format="json",
        file=False,
        uvicorn_access_level="WARNING",
        third_party_level="WARNING",
    )
    logging.getLogger("uvicorn.access").info("should not appear")
    logging.getLogger("httpx").info("should not appear either")

    captured = capsys.readouterr()
    out = (captured.err or captured.out)
    assert "should not appear" not in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/test_logging.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend._logging'`.

- [ ] **Step 3: Commit**

```bash
git add tests/backend/test_logging.py
git commit -m "Add failing tests for structured logging module"
```

---

## Task 5: Implement backend/_logging.py

**Files:**
- Create: `backend/_logging.py`

- [ ] **Step 1: Write implementation**

```python
"""Structured logging configuration for Chatsune.

Single source of truth for logging setup. Uses structlog with a stdlib
ProcessorFormatter bridge so that both structlog-native loggers and legacy
`logging.getLogger(...)` callers emit records through the same processor
chain.

Two sinks are supported simultaneously:

- Console (stderr): pretty colourful output locally, JSON in Docker.
- File: JSON lines to `backend/logs/chatsune.log`, daily rotation, 14
  backups. Intended for local development and lnav/jq consumption; in
  Docker the file sink is turned off and logs go only to stdout/stderr
  where Grafana picks them up.

Context (`correlation_id`, `user_id`, `job_id`, `job_type`, `lock_key`,
...) is carried through `structlog.contextvars` so it can be bound once
and automatically appear on every downstream event.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Any

import structlog


def _build_shared_processors() -> list[Any]:
    """Processors shared by structlog-native and stdlib-bridged records."""
    return [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.stdlib.add_logger_name,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]


def configure_logging(
    *,
    level: str = "INFO",
    console: bool = True,
    console_format: str = "pretty",  # "pretty" | "json"
    file: bool = True,
    file_path: str = "backend/logs/chatsune.log",
    file_backup_count: int = 14,
    uvicorn_access_level: str = "WARNING",
    third_party_level: str = "WARNING",
) -> None:
    """Configure stdlib logging + structlog.

    Idempotent: calling repeatedly resets previous handlers.
    """
    shared_processors = _build_shared_processors()

    # Configure structlog: native loggers go through `ProcessorFormatter.wrap_for_formatter`
    # so the final rendering happens in the stdlib formatter, giving us a single pipeline.
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level.upper())
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    if console_format == "json":
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    formatter = structlog.stdlib.ProcessorFormatter(
        # `foreign_pre_chain` is applied to records coming from stdlib loggers
        # (uvicorn, fastapi, pymongo, our legacy `logging.getLogger(...)` callers).
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    # File formatter is always JSON regardless of console_format, because
    # the file sink is meant for lnav / jq consumption.
    file_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    root = logging.getLogger()
    # Reset to make `configure_logging` idempotent (tests rely on this).
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.setLevel(logging.getLevelName(level.upper()))

    if console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    if file:
        log_path = Path(file_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=str(log_path),
            when="midnight",
            backupCount=file_backup_count,
            encoding="utf-8",
            utc=True,
        )
        file_handler.setFormatter(file_formatter)
        root.addHandler(file_handler)

    # Tame noisy libraries.
    logging.getLogger("uvicorn.access").setLevel(
        logging.getLevelName(uvicorn_access_level.upper())
    )
    for noisy in ("httpx", "httpcore", "pymongo"):
        logging.getLogger(noisy).setLevel(
            logging.getLevelName(third_party_level.upper())
        )


def get_logger(name: str | None = None) -> Any:
    """Return a structlog-bound logger. Prefer this over `logging.getLogger`."""
    return structlog.get_logger(name)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/backend/test_logging.py -v`
Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/_logging.py
git commit -m "Add structlog-based logging configuration module"
```

---

## Task 6: Wire configure_logging into main.py

**Files:**
- Modify: `backend/main.py:1-23`

- [ ] **Step 1: Replace the basicConfig block**

Read `backend/main.py` lines 1-30. Replace lines 1-23 (current `basicConfig` block and third-party muting) with:

```python
import asyncio
import os
import sys
from contextlib import asynccontextmanager

# Configure structured logging before any module-level loggers are created
# by imports further down. Without this, early imports create loggers that
# cache the default (WARNING) handler and INFO lines from those modules
# get silently dropped.
from backend.config import settings
from backend._logging import configure_logging

configure_logging(
    level=settings.log_level,
    console=settings.log_console,
    console_format=settings.log_console_format,
    file=settings.log_file,
    file_path=settings.log_file_path,
    file_backup_count=settings.log_file_backup_count,
    uvicorn_access_level=settings.log_level_uvicorn_access,
    third_party_level=settings.log_level_third_party,
)
```

Note: `from backend.config import settings` may already exist further down — keep this early import and remove the duplicate later one if it causes a lint issue.

- [ ] **Step 2: Verify backend boots**

Run: `uv run python -c "import backend.main"`
Expected: no exceptions. A startup log line may appear.

- [ ] **Step 3: Smoke-run uvicorn for 2 seconds**

Run: `timeout 3 uv run uvicorn backend.main:app --port 18123 || true`
Expected: startup logs appear with pretty formatting (colours, `chatsune.lifecycle` style), no tracebacks. Confirm `backend/logs/chatsune.log` was created and contains JSON lines.

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "Wire structured logging into backend startup"
```

---

## Task 7: Instrument jobs submit path

**Files:**
- Modify: `backend/jobs/_submit.py`

- [ ] **Step 1: Read current file**

Read `backend/jobs/_submit.py` fully to understand the enqueue function and the existing `_log.info` / `_log.warning` sites.

- [ ] **Step 2: Swap to structlog and rewrite log calls**

Replace the module-level logger:

```python
import structlog

_log = structlog.get_logger("chatsune.jobs.submit")
```

For every enqueue/submission code path, rewrite the existing `_log.info(...)` / `_log.warning(...)` calls to structured events. Example transformation:

Before:
```python
_log.info("Enqueued job %s (type=%s) on stream %s", job.id, job.job_type, stream)
```

After:
```python
_log.info(
    "job.enqueued",
    job_id=job.id,
    job_type=job.job_type,
    stream=stream,
)
```

Apply the same transformation to the existing `_log.warning` at line 70 — name the event `job.enqueue.dedup_conflict` (or the most descriptive stable name based on what the warning is actually about — read the surrounding code to decide).

Every Redis write that stores a `jobs:*` key inside this file must get its own log line: `_log.info("job.redis.write", redis_key=key, ttl_seconds=...)`.

- [ ] **Step 3: Verify compile**

Run: `uv run python -m py_compile backend/jobs/_submit.py`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add backend/jobs/_submit.py
git commit -m "Instrument job submit path with structured events"
```

---

## Task 8: Instrument jobs consumer

**Files:**
- Modify: `backend/jobs/_consumer.py`

- [ ] **Step 1: Read current file**

Read `backend/jobs/_consumer.py` fully.

- [ ] **Step 2: Swap logger**

Replace module-level logger:

```python
import structlog

_log = structlog.get_logger("chatsune.jobs.consumer")
```

- [ ] **Step 3: Rewrite every log call**

Map the existing calls (lines approximately 87, 112, 117, 236, 247, 254, 283, 305, 312, 320, 323) to stable events. Use `structlog.contextvars.bind_contextvars(job_id=job.id, job_type=job.job_type, attempt=attempt)` at the start of processing each job, and `clear_contextvars()` in a `finally` — so every line inside the processing block automatically carries that context.

Event mapping:

| Old | New event | Fields |
|---|---|---|
| `"Dropping zombie PEL entry ..."` | `job.pel.zombie_dropped` | `entry_id` |
| `"Unknown job type: ..."` | `job.unknown_type` | `job_type`, `job_id` |
| line 117 `_log.info(...)` (job received) | `job.received` | `job_id`, `job_type`, `attempt` |
| `"Job %s timed out ..."` | `job.timeout` | `timeout_seconds` |
| line 247 `_log.warning` | `job.failed.retriable` (or similar — pick based on context) | `error`, `attempt` |
| `"Job %s raised an exception"` | `job.exception` | use `_log.exception("job.exception")` to keep traceback |
| `"Job %s failed after %d attempts"` | `job.failed.final` | `attempt`, `error` |
| `"Job %s retry %d/%d scheduled at ..."` | `job.retry.scheduled` | `attempt`, `max_retries`, `next_retry_at` |
| `"Job consumer started"` | `job.consumer.started` | — |
| `"Job consumer shutting down"` | `job.consumer.shutdown` | — |
| `"Unexpected error in job consumer loop"` | `job.consumer.loop_error` | use `_log.exception(...)` |

Show the shape of one rewrite for clarity:

```python
# Before
_log.info("Job %s retry %d/%d scheduled at %s", job.id, attempt, config.max_retries, next_retry_at)

# After
_log.info(
    "job.retry.scheduled",
    attempt=attempt,
    max_retries=config.max_retries,
    next_retry_at=next_retry_at.isoformat(),
)
```

Add `bind_contextvars`/`clear_contextvars` around the per-job processing block so the fields are implicit:

```python
structlog.contextvars.bind_contextvars(
    job_id=job.id, job_type=job.job_type, attempt=attempt
)
try:
    ...
finally:
    structlog.contextvars.clear_contextvars()
```

- [ ] **Step 4: Verify compile**

Run: `uv run python -m py_compile backend/jobs/_consumer.py`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add backend/jobs/_consumer.py
git commit -m "Instrument job consumer with structured events and bound context"
```

---

## Task 9: Instrument jobs lock

**Files:**
- Modify: `backend/jobs/_lock.py`

- [ ] **Step 1: Read current file**

Read `backend/jobs/_lock.py` fully to identify acquire / release / contention code paths and any `jobs:*` Redis key writes/deletes.

- [ ] **Step 2: Add structured logging**

Add at module level:

```python
import structlog

_log = structlog.get_logger("chatsune.jobs.lock")
```

Add log lines at:

- Successful acquire: `_log.info("job.lock.acquired", lock_key=key, holder=holder, ttl_ms=ttl_ms)`
- Contention / failed acquire: `_log.info("job.lock.contended", lock_key=key, holder=current_holder)`
- Release: `_log.info("job.lock.released", lock_key=key, holder=holder)`
- Release-of-expired-lock: `_log.warning("job.lock.expired", lock_key=key)`
- Every Redis SET/DEL on a `jobs:*` key: `_log.debug("job.redis.write", redis_key=key, op="set", ttl_ms=ttl_ms)` / `_log.debug("job.redis.write", redis_key=key, op="del")`

If the file does not currently have a logger, add one. If there are existing `print()` or log calls, replace them.

- [ ] **Step 3: Verify compile**

Run: `uv run python -m py_compile backend/jobs/_lock.py`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add backend/jobs/_lock.py
git commit -m "Instrument job lock acquire/release/contention"
```

---

## Task 10: Instrument retry, dedup, disconnect_retry

**Files:**
- Modify: `backend/jobs/_retry.py`
- Modify: `backend/jobs/_dedup.py`
- Modify: `backend/jobs/_disconnect_retry.py`
- Modify: `backend/jobs/_inspect.py`

- [ ] **Step 1: Read all four files**

Read each file fully before editing.

- [ ] **Step 2: Update `_retry.py`**

Replace the module logger with `_log = structlog.get_logger("chatsune.jobs.retry")`. Wherever a retry decision is computed, add `_log.info("job.retry.computed", attempt=attempt, max_retries=..., backoff_seconds=...)`. Where a job is given up, add `_log.info("job.retry.exhausted", attempt=attempt)`.

- [ ] **Step 3: Update `_dedup.py`**

Replace module logger with `_log = structlog.get_logger("chatsune.jobs.dedup")`. At every Redis `jobs:*` key write: `_log.debug("job.dedup.key_written", redis_key=key, ttl_seconds=ttl)`. At every delete: `_log.debug("job.dedup.key_deleted", redis_key=key)`. On a dedup hit: `_log.info("job.dedup.hit", dedup_key=..., existing_job_id=...)`. On a miss: `_log.debug("job.dedup.miss", dedup_key=...)`.

- [ ] **Step 4: Update `_disconnect_retry.py`**

Replace `_log = logging.getLogger("chatsune.jobs.disconnect_retry")` with `_log = structlog.get_logger("chatsune.jobs.disconnect_retry")`. Convert existing `_log.info` calls to structured events: `job.disconnect_retry.loop_started`, `job.disconnect_retry.requeued` (with `job_id`, `user_id`), `job.disconnect_retry.loop_error` (use `.exception(...)`).

- [ ] **Step 5: Update `_inspect.py`**

Swap `logging.getLogger(...)` → `structlog.get_logger("chatsune.debug.jobs_inspect")`. No other behavioural change.

- [ ] **Step 6: Verify compile**

Run: `uv run python -m py_compile backend/jobs/_retry.py backend/jobs/_dedup.py backend/jobs/_disconnect_retry.py backend/jobs/_inspect.py`
Expected: no output.

- [ ] **Step 7: Commit**

```bash
git add backend/jobs/_retry.py backend/jobs/_dedup.py backend/jobs/_disconnect_retry.py backend/jobs/_inspect.py
git commit -m "Instrument retry, dedup, disconnect-retry, inspect with structlog"
```

---

## Task 11: Swap job handlers to structlog

**Files:**
- Modify: `backend/jobs/handlers/_title_generation.py`
- Modify: `backend/jobs/handlers/_memory_consolidation.py`
- Modify: `backend/jobs/handlers/_memory_extraction.py`
- Modify: `backend/jobs/handlers/_budget_helpers.py`

- [ ] **Step 1: Swap logger imports**

In each of the four files, replace:

```python
import logging
_log = logging.getLogger(__name__)
```

with:

```python
import structlog
_log = structlog.get_logger(__name__)
```

Do **not** rewrite existing `_log.info(...)` / `_log.warning(...)` / `_log.exception(...)` call sites. structlog's stdlib-compatible API accepts positional `%s` formatting, so existing messages keep working and automatically pick up bound context (`job_id`, `job_type`, etc.) from the consumer.

- [ ] **Step 2: Verify compile**

Run: `uv run python -m py_compile backend/jobs/handlers/_title_generation.py backend/jobs/handlers/_memory_consolidation.py backend/jobs/handlers/_memory_extraction.py backend/jobs/handlers/_budget_helpers.py`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add backend/jobs/handlers/
git commit -m "Swap job handlers to structlog logger"
```

---

## Task 12: Docker compose env overrides

**Files:**
- Modify: `compose.yml` or `docker-compose.yml` (whichever exists at repo root)

- [ ] **Step 1: Find the file**

Run: `ls compose.yml docker-compose.yml 2>/dev/null`

- [ ] **Step 2: Add env vars to the backend service**

Under the backend service's `environment:` block (create it if missing) add:

```yaml
      LOG_CONSOLE_FORMAT: json
      LOG_FILE: "0"
```

- [ ] **Step 3: Validate compose file**

Run: `docker compose config > /dev/null`
Expected: no errors. (If Docker is not installed locally, skip and note in the commit that validation was deferred.)

- [ ] **Step 4: Commit**

```bash
git add compose.yml docker-compose.yml 2>/dev/null
git commit -m "Switch backend logging to JSON stdout in docker compose"
```

---

## Task 13: Document logging in README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a "Logging" section**

Append (or insert in the appropriate place) a section:

```markdown
## Logging

Chatsune uses [structlog](https://www.structlog.org/) with two sinks:

- **Console** — pretty, colourful output in local dev; JSON lines in Docker
  (picked up by Grafana/Loki). Controlled by `LOG_CONSOLE` and
  `LOG_CONSOLE_FORMAT`.
- **Rotating file** — JSON lines at `backend/logs/chatsune.log`, rotated
  daily, 14 backups. Off by default in Docker. Controlled by `LOG_FILE`,
  `LOG_FILE_PATH`, `LOG_FILE_BACKUP_COUNT`. Ideal for `lnav` or `jq`.

Every log record carries `timestamp`, `level`, `logger` (dotted namespace
such as `chatsune.jobs.consumer`), `event` (stable short identifier such
as `job.enqueued`), and any bound context (`correlation_id`, `job_id`,
`job_type`, `user_id`, `lock_key`).

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Root log level |
| `LOG_CONSOLE` | `1` | Enable console sink |
| `LOG_CONSOLE_FORMAT` | `pretty` | `pretty` or `json` |
| `LOG_FILE` | `1` | Enable rotating file sink |
| `LOG_FILE_PATH` | `backend/logs/chatsune.log` | File path |
| `LOG_FILE_BACKUP_COUNT` | `14` | Daily rotations retained |
| `LOG_LEVEL_UVICORN_ACCESS` | `WARNING` | HTTP access noise threshold |
| `LOG_LEVEL_THIRD_PARTY` | `WARNING` | `httpx`, `httpcore`, `pymongo` |

### Filtering examples

```bash
# Everything from the job consumer
jq 'select(.logger=="chatsune.jobs.consumer")' backend/logs/chatsune.log

# One specific job end-to-end
jq 'select(.job_id=="abc123")' backend/logs/chatsune.log

# Lock contention only
jq 'select(.event=="job.lock.contended")' backend/logs/chatsune.log
```
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Document structured logging setup in README"
```

---

## Task 14: End-to-end verification

**Files:** none

- [ ] **Step 1: Run the test suite**

Run: `uv run pytest tests/backend/test_logging.py -v`
Expected: all tests PASS.

- [ ] **Step 2: Start the backend briefly with pretty console**

Run: `LOG_CONSOLE_FORMAT=pretty timeout 4 uv run uvicorn backend.main:app --port 18124 || true`
Expected: coloured lines like `chatsune.lifecycle` and `chatsune.jobs.consumer  job.consumer.started` appear on stderr. `backend/logs/chatsune.log` was created and contains JSON lines for the same events.

- [ ] **Step 3: Inspect the JSON file**

Run: `tail -n 5 backend/logs/chatsune.log | jq .`
Expected: valid JSON objects with `event`, `logger`, `timestamp`, `level` fields.

- [ ] **Step 4: Start with JSON console (simulate Docker)**

Run: `LOG_CONSOLE_FORMAT=json LOG_FILE=0 timeout 4 uv run uvicorn backend.main:app --port 18125 || true`
Expected: only JSON on stderr, no file created this time.

- [ ] **Step 5: Submit a test job and confirm structured events**

Submit a job through whatever path is most convenient (an admin endpoint, a script, or the frontend). In the log file, confirm that `job.enqueued`, `job.received`, and either `job.completed` or `job.failed.*` events appear with the same `job_id` bound to every line.

Run: `jq 'select(.logger | startswith("chatsune.jobs"))' backend/logs/chatsune.log | tail -n 30`
Expected: the full lifecycle of at least one job visible, with `job_id` present on every consumer/lock line.

- [ ] **Step 6: Final commit if any tidy-ups were needed**

If no changes: skip. Otherwise commit a `Tidy: ...` follow-up.

---

## Done

- Structured logs flow through a single structlog pipeline.
- Pretty console + rotating JSON file locally, JSON stdout only in Docker.
- Jobs subsystem (submit, consumer, lock, retry, dedup, disconnect-retry, inspect, handlers) is fully instrumented with stable dotted event names and bound `job_id` / `job_type` / `lock_key` context.
- `lnav` / `jq` / Grafana can all filter on the same fields.
- Existing `logging.getLogger(...)` call sites keep working via the ProcessorFormatter bridge; they can be migrated opportunistically later.

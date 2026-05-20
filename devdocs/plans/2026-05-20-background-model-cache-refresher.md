# Background Model Cache Refresher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `devdocs/specs/2026-05-20-background-model-cache-refresher-design.md`

**Goal:** Replace the 30-minute TTL on the LLM model metadata cache with a per-user background refresher so that cache expiry never blocks the read path.

**Architecture:** A new internal service `ModelCacheRefresher` runs one `asyncio.Task` per online user, refreshing every connection and Premium Provider model list every ~30 minutes. The `ConnectionManager` gains generic lifecycle hooks (first connect / last disconnect) that the LLM module registers against at app startup. The read path becomes pure cache lookup — cache miss returns `[]` instead of fetching synchronously. The Redis TTL extends to 7 days as a garbage-collection floor for users who go inactive.

**Tech Stack:** Python 3.12, FastAPI, Redis (`redis.asyncio`), pytest-asyncio (`asyncio_mode = "auto"`).

---

## File Map

**New files:**

- `backend/modules/llm/_metadata_refresher.py` — refresher service (loop body, refcount, triggers).
- `backend/tests/modules/llm/test_metadata_refresher.py` — unit tests for refresher.
- `backend/tests/modules/llm/test_metadata_read_path.py` — read-path tests for the changed `_metadata.py`.
- `backend/tests/ws/test_manager_lifecycle_hooks.py` — tests for the new manager hooks.

**Modified files:**

- `backend/modules/llm/_metadata.py` — TTL constant, remove sync fetch on miss.
- `backend/ws/manager.py` — add `_on_first_user_connect` / `_on_last_user_disconnect` callback lists and edge-fire logic.
- `backend/main.py` — instantiate the refresher and register lifecycle hooks on the manager.
- `backend/modules/llm/__init__.py` — expose `get_model_cache_refresher()` accessor for callers outside the module.
- `backend/modules/llm/_handlers.py` — call `trigger_connection` after `LLM_CONNECTION_CREATED` / `LLM_CONNECTION_UPDATED` are published.
- `backend/modules/providers/_handlers.py` — call `trigger_premium` after `PREMIUM_PROVIDER_ACCOUNT_UPSERTED` is published.

---

## Test invocation reference

All backend pytest invocations from the repo root use this prefix (per project memory):

```
PYTHONPATH=. uv run pytest <path>
```

DB-touching test files are excluded by default — none of the new tests touch MongoDB, so the standard invocation works without `--ignore` flags. New tests use mocked Redis and mocked adapter classes.

---

### Task 1: Add lifecycle hooks to ConnectionManager

**Files:**
- Modify: `backend/ws/manager.py`
- Test: `backend/tests/ws/test_manager_lifecycle_hooks.py` (new)

- [ ] **Step 1: Write the failing test for hook registration and edge firing**

Create `backend/tests/ws/test_manager_lifecycle_hooks.py`:

```python
"""Lifecycle hooks fire on first-connect / last-disconnect edges."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.ws.manager import ConnectionManager


def _fake_ws() -> MagicMock:
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


@pytest.mark.asyncio
async def test_first_connect_hook_fires_only_on_first_socket():
    mgr = ConnectionManager()
    hook = AsyncMock()
    mgr.register_on_first_connect(hook)

    await mgr.connect("user-a", "user", _fake_ws())
    await mgr.connect("user-a", "user", _fake_ws())
    await mgr.connect("user-b", "user", _fake_ws())

    assert hook.await_count == 2
    hook.assert_any_await("user-a")
    hook.assert_any_await("user-b")


@pytest.mark.asyncio
async def test_last_disconnect_hook_fires_only_when_last_socket_leaves():
    mgr = ConnectionManager()
    hook = AsyncMock()
    mgr.register_on_last_disconnect(hook)

    ws1, ws2 = _fake_ws(), _fake_ws()
    await mgr.connect("user-a", "user", ws1)
    await mgr.connect("user-a", "user", ws2)

    await mgr.disconnect("user-a", ws1)
    assert hook.await_count == 0  # still one socket left

    await mgr.disconnect("user-a", ws2)
    assert hook.await_count == 1
    hook.assert_awaited_with("user-a")


@pytest.mark.asyncio
async def test_hook_exception_does_not_break_connect():
    mgr = ConnectionManager()

    async def bad_hook(user_id: str) -> None:
        raise RuntimeError("boom")

    mgr.register_on_first_connect(bad_hook)
    # Must not raise:
    cid = await mgr.connect("user-a", "user", _fake_ws())
    assert cid in mgr.connection_ids_for_user("user-a")
```

- [ ] **Step 2: Run the test to verify it fails**

```
PYTHONPATH=. uv run pytest backend/tests/ws/test_manager_lifecycle_hooks.py -v
```

Expected: FAIL with `AttributeError: 'ConnectionManager' object has no attribute 'register_on_first_connect'`.

- [ ] **Step 3: Implement hooks in `backend/ws/manager.py`**

Add an import at the top of the file:

```python
import logging
from typing import Awaitable, Callable
```

Add `_log = logging.getLogger(__name__)` at module scope after the imports.

In `ConnectionManager.__init__`, append after the existing attribute assignments:

```python
self._on_first_user_connect: list[Callable[[str], Awaitable[None]]] = []
self._on_last_user_disconnect: list[Callable[[str], Awaitable[None]]] = []
```

Add two registration methods inside the class (placement: right after `__init__`):

```python
def register_on_first_connect(
    self, cb: Callable[[str], Awaitable[None]],
) -> None:
    self._on_first_user_connect.append(cb)

def register_on_last_disconnect(
    self, cb: Callable[[str], Awaitable[None]],
) -> None:
    self._on_last_user_disconnect.append(cb)

async def _fire_hooks(
    self,
    hooks: list[Callable[[str], Awaitable[None]]],
    user_id: str,
) -> None:
    for hook in hooks:
        try:
            await hook(user_id)
        except Exception:
            _log.exception(
                "lifecycle hook %r failed for user=%s",
                getattr(hook, "__name__", repr(hook)), user_id,
            )
```

Modify `connect()` — replace the current body with:

```python
async def connect(self, user_id: str, role: str, ws: WebSocket) -> str:
    """Register a new WebSocket and return its assigned connection id."""
    connection_id = str(uuid4())
    is_first = user_id not in self._connections
    if is_first:
        self._connections[user_id] = {}
    self._connections[user_id][connection_id] = ws
    self._user_roles[user_id] = role
    if is_first:
        await self._fire_hooks(self._on_first_user_connect, user_id)
    return connection_id
```

Modify `disconnect()` — replace the current body with:

```python
async def disconnect(self, user_id: str, ws: WebSocket) -> None:
    conns = self._connections.get(user_id)
    if not conns:
        return
    dead_ids = [cid for cid, w in conns.items() if w is ws]
    for cid in dead_ids:
        del conns[cid]
    became_empty = not conns
    if became_empty:
        del self._connections[user_id]
        del self._user_roles[user_id]
        await self._fire_hooks(self._on_last_user_disconnect, user_id)
```

- [ ] **Step 4: Run the test to verify it passes**

```
PYTHONPATH=. uv run pytest backend/tests/ws/test_manager_lifecycle_hooks.py -v
```

Expected: 3 passing tests.

- [ ] **Step 5: Run the existing WS disconnect-cleanup test to confirm no regression**

```
PYTHONPATH=. uv run pytest backend/tests/ws/test_disconnect_cleanup.py -v
```

Expected: unchanged pass status.

- [ ] **Step 6: Commit**

```bash
git add backend/ws/manager.py backend/tests/ws/test_manager_lifecycle_hooks.py
git commit -m "Add first-connect / last-disconnect lifecycle hooks to ConnectionManager"
```

---

### Task 2: Create ModelCacheRefresher skeleton with refcount lifecycle

**Files:**
- Create: `backend/modules/llm/_metadata_refresher.py`
- Test: `backend/tests/modules/llm/test_metadata_refresher.py` (new)

- [ ] **Step 1: Write the failing test for ensure / release lifecycle**

Create `backend/tests/modules/llm/test_metadata_refresher.py`:

```python
"""Refcounted per-user refresher task lifecycle."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from backend.modules.llm._metadata_refresher import ModelCacheRefresher


@pytest.fixture
def refresher(monkeypatch) -> ModelCacheRefresher:
    r = ModelCacheRefresher()

    async def _noop_iteration(user_id: str) -> None:
        # Park indefinitely so the task stays alive until cancelled.
        await asyncio.Event().wait()

    monkeypatch.setattr(r, "_run_user_iteration", AsyncMock(side_effect=_noop_iteration))
    return r


@pytest.mark.asyncio
async def test_ensure_creates_task_on_first_call(refresher):
    await refresher.ensure_user_task("user-a")
    assert refresher.has_active_task("user-a")
    await refresher.release_user_task("user-a")


@pytest.mark.asyncio
async def test_ensure_is_idempotent(refresher):
    await refresher.ensure_user_task("user-a")
    task_before = refresher._tasks["user-a"]

    await refresher.ensure_user_task("user-a")
    task_after = refresher._tasks["user-a"]

    assert task_before is task_after
    assert refresher._refcounts["user-a"] == 2

    await refresher.release_user_task("user-a")
    assert refresher.has_active_task("user-a")  # one ref left
    await refresher.release_user_task("user-a")
    assert not refresher.has_active_task("user-a")


@pytest.mark.asyncio
async def test_release_below_zero_is_safe(refresher):
    # Releasing a user we never ensured must not raise:
    await refresher.release_user_task("nobody")
    assert not refresher.has_active_task("nobody")
```

- [ ] **Step 2: Run the test to verify it fails**

```
PYTHONPATH=. uv run pytest backend/tests/modules/llm/test_metadata_refresher.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backend.modules.llm._metadata_refresher'`.

- [ ] **Step 3: Create the refresher skeleton**

Create `backend/modules/llm/_metadata_refresher.py`:

```python
"""Per-user background refresher for the LLM model metadata cache.

One `asyncio.Task` runs for every online user. It refreshes every
Connection and Premium Provider model list owned by the user on a fixed
cadence and replaces the Redis entry atomically on success. Failures are
logged and leave the prior cached value intact.

Lifecycle is driven by WebSocket presence: the ConnectionManager fires
`ensure_user_task` on the first-connect edge and `release_user_task` on
the last-disconnect edge. Both are idempotent and refcounted so multiple
tabs do not create multiple tasks.
"""

import asyncio
import logging
import random

_log = logging.getLogger(__name__)

REFRESH_INTERVAL_SECONDS = 30 * 60
REFRESH_JITTER_SECONDS = 60
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60


class ModelCacheRefresher:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._refcounts: dict[str, int] = {}
        self._lock = asyncio.Lock()

    def has_active_task(self, user_id: str) -> bool:
        task = self._tasks.get(user_id)
        return task is not None and not task.done()

    async def ensure_user_task(self, user_id: str) -> None:
        async with self._lock:
            self._refcounts[user_id] = self._refcounts.get(user_id, 0) + 1
            if user_id in self._tasks and not self._tasks[user_id].done():
                return
            self._tasks[user_id] = asyncio.create_task(
                self._user_loop(user_id),
                name=f"model-cache-refresher:{user_id}",
            )

    async def release_user_task(self, user_id: str) -> None:
        async with self._lock:
            current = self._refcounts.get(user_id, 0)
            if current <= 1:
                self._refcounts.pop(user_id, None)
                task = self._tasks.pop(user_id, None)
            else:
                self._refcounts[user_id] = current - 1
                task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            _log.exception(
                "refresher task for user=%s raised on cancel", user_id,
            )

    async def _user_loop(self, user_id: str) -> None:
        """Background loop body — runs until cancelled."""
        while True:
            try:
                await self._run_user_iteration(user_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                _log.exception(
                    "refresher iteration crashed for user=%s — continuing",
                    user_id,
                )
            jitter = random.uniform(-REFRESH_JITTER_SECONDS, REFRESH_JITTER_SECONDS)
            await asyncio.sleep(REFRESH_INTERVAL_SECONDS + jitter)

    async def _run_user_iteration(self, user_id: str) -> None:
        """One full refresh pass. Filled in by Task 3."""
        raise NotImplementedError


_refresher: ModelCacheRefresher | None = None


def get_model_cache_refresher() -> ModelCacheRefresher:
    global _refresher
    if _refresher is None:
        _refresher = ModelCacheRefresher()
    return _refresher


def reset_for_tests() -> None:
    """Test-only hook to reinitialise the singleton."""
    global _refresher
    _refresher = None
```

- [ ] **Step 4: Run the test to verify it passes**

```
PYTHONPATH=. uv run pytest backend/tests/modules/llm/test_metadata_refresher.py -v
```

Expected: 3 passing tests.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_metadata_refresher.py backend/tests/modules/llm/test_metadata_refresher.py
git commit -m "Add ModelCacheRefresher skeleton with refcounted per-user task lifecycle"
```

---

### Task 3: Implement refresher iteration body

**Files:**
- Modify: `backend/modules/llm/_metadata_refresher.py`
- Modify: `backend/tests/modules/llm/test_metadata_refresher.py`

- [ ] **Step 1: Write the failing iteration test**

Append to `backend/tests/modules/llm/test_metadata_refresher.py`:

```python
from datetime import UTC, datetime
from unittest.mock import patch

from backend.modules.llm._adapters._types import ResolvedConnection


def _make_resolved(adapter_type: str, conn_id: str) -> ResolvedConnection:
    now = datetime.now(UTC)
    return ResolvedConnection(
        id=conn_id,
        user_id="user-a",
        adapter_type=adapter_type,
        display_name=conn_id,
        slug=conn_id,
        config={"url": "http://x", "api_key": "k"},
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_iteration_refreshes_all_connections_and_premium_accounts():
    r = ModelCacheRefresher()

    conn = _make_resolved("ollama_http", "conn-1")
    premium = _make_resolved("xai_http", "premium:xai")

    refresh_conn = AsyncMock()
    refresh_premium = AsyncMock()

    with (
        patch.object(r, "_resolve_user_connections", AsyncMock(return_value=[conn])),
        patch.object(r, "_resolve_user_premium_accounts",
                     AsyncMock(return_value=[("xai", premium)])),
        patch(
            "backend.modules.llm._metadata_refresher._refresh_connection_into_cache",
            refresh_conn,
        ),
        patch(
            "backend.modules.llm._metadata_refresher._refresh_premium_into_cache",
            refresh_premium,
        ),
    ):
        await r._run_user_iteration("user-a")

    refresh_conn.assert_awaited_once()
    refresh_premium.assert_awaited_once()


@pytest.mark.asyncio
async def test_iteration_continues_when_one_target_fails():
    r = ModelCacheRefresher()
    conn_ok = _make_resolved("ollama_http", "conn-ok")
    conn_bad = _make_resolved("ollama_http", "conn-bad")

    async def fake_refresh(c, *_args, **_kwargs):
        if c.id == "conn-bad":
            raise RuntimeError("upstream down")

    with (
        patch.object(r, "_resolve_user_connections",
                     AsyncMock(return_value=[conn_bad, conn_ok])),
        patch.object(r, "_resolve_user_premium_accounts",
                     AsyncMock(return_value=[])),
        patch(
            "backend.modules.llm._metadata_refresher._refresh_connection_into_cache",
            AsyncMock(side_effect=fake_refresh),
        ) as mock_refresh,
    ):
        await r._run_user_iteration("user-a")
    assert mock_refresh.await_count == 2  # both attempted, one raised
```

- [ ] **Step 2: Run the test to verify it fails**

```
PYTHONPATH=. uv run pytest backend/tests/modules/llm/test_metadata_refresher.py -v
```

Expected: FAIL — `_run_user_iteration` raises `NotImplementedError`.

- [ ] **Step 3: Implement iteration body**

In `backend/modules/llm/_metadata_refresher.py`, add these imports at the top:

```python
from datetime import UTC, datetime
import json

from redis.asyncio import Redis

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._types import ResolvedConnection
from shared.dtos.llm import ModelMetaDto
from shared.events.llm import (
    LlmConnectionModelsRefreshedEvent,
    PremiumProviderModelsRefreshedEvent,
)
from shared.topics import Topics
```

Replace the `_run_user_iteration` stub with:

```python
async def _run_user_iteration(self, user_id: str) -> None:
    """Fetch and atomically replace every cache key owned by the user."""
    connections = await self._resolve_user_connections(user_id)
    premium = await self._resolve_user_premium_accounts(user_id)

    redis = self._get_redis()
    event_bus = self._get_event_bus()

    for conn in connections:
        adapter_cls = self._get_adapter_class(conn.adapter_type)
        if adapter_cls is None:
            continue
        try:
            await _refresh_connection_into_cache(conn, adapter_cls, redis)
        except Exception as exc:
            _log.warning(
                "background refresh failed for connection=%s adapter=%s: %s",
                conn.id, conn.adapter_type, exc,
            )
            continue
        await self._publish_connection_refreshed(event_bus, user_id, conn.id)

    for provider_id, resolved in premium:
        adapter_cls = self._get_adapter_class(resolved.adapter_type)
        if adapter_cls is None:
            continue
        try:
            await _refresh_premium_into_cache(
                resolved, adapter_cls, redis, user_id, provider_id,
            )
        except Exception as exc:
            _log.warning(
                "background refresh failed for premium provider=%s user=%s: %s",
                provider_id, user_id, exc,
            )
            continue
        await self._publish_premium_refreshed(event_bus, user_id, provider_id)
```

Below the class, add helper functions that the iteration calls:

```python
async def _refresh_connection_into_cache(
    c: ResolvedConnection, adapter_cls: type[BaseAdapter], redis: Redis,
) -> list[ModelMetaDto]:
    """Fetch and write the connection-scoped cache. Raises on adapter failure."""
    from backend.modules.llm._metadata import _cache_key
    from backend.modules.llm._registry import _instantiate_adapter

    adapter = _instantiate_adapter(adapter_cls, redis)
    models = await adapter.fetch_models(c)
    await redis.set(
        _cache_key(c.id),
        json.dumps([m.model_dump(mode="json") for m in models]),
        ex=CACHE_TTL_SECONDS,
    )
    return models


async def _refresh_premium_into_cache(
    c: ResolvedConnection,
    adapter_cls: type[BaseAdapter],
    redis: Redis,
    user_id: str,
    provider_id: str,
) -> list[ModelMetaDto]:
    """Fetch and write the user-scoped Premium Provider cache. Raises on failure."""
    from backend.modules.llm._metadata import _premium_cache_key
    from backend.modules.llm._registry import _instantiate_adapter

    adapter = _instantiate_adapter(adapter_cls, redis)
    models = await adapter.fetch_models(c)
    await redis.set(
        _premium_cache_key(user_id, provider_id),
        json.dumps([m.model_dump(mode="json") for m in models]),
        ex=CACHE_TTL_SECONDS,
    )
    return models
```

Add helper methods inside the class (right after `_run_user_iteration`):

```python
async def _resolve_user_connections(
    self, user_id: str,
) -> list[ResolvedConnection]:
    """Fetch all connections owned by ``user_id`` as ResolvedConnections."""
    from backend.database import get_db
    from backend.modules.llm._connections import ConnectionRepository
    from backend.modules.llm._resolver import _to_resolved

    repo = ConnectionRepository(get_db())
    docs = await repo.list_for_user(user_id)
    return [_to_resolved(d) for d in docs]

async def _resolve_user_premium_accounts(
    self, user_id: str,
) -> list[tuple[str, ResolvedConnection]]:
    """For every Premium Provider account the user has, return
    ``(provider_id, ResolvedConnection)`` pairs ready to fetch models against.
    Providers without an LLM adapter mapping are silently skipped."""
    from backend.modules.llm._resolver import resolve_premium_for_listing
    from backend.modules.providers import PremiumProviderService
    from backend.modules.providers._repository import (
        PremiumProviderAccountRepository,
    )
    from backend.database import get_db

    svc = PremiumProviderService(PremiumProviderAccountRepository(get_db()))
    accounts = await svc.list_for_user(user_id)
    out: list[tuple[str, ResolvedConnection]] = []
    for account in accounts:
        provider_id = account["provider_id"]
        resolved = await resolve_premium_for_listing(user_id, provider_id)
        if resolved is not None:
            out.append((provider_id, resolved))
    return out

def _get_adapter_class(self, adapter_type: str) -> type[BaseAdapter] | None:
    from backend.modules.llm._registry import ADAPTER_REGISTRY
    return ADAPTER_REGISTRY.get(adapter_type)

def _get_redis(self) -> Redis:
    from backend.database import get_redis
    return get_redis()

def _get_event_bus(self):
    from backend.ws.event_bus import get_event_bus
    return get_event_bus()

async def _publish_connection_refreshed(
    self, event_bus, user_id: str, connection_id: str,
) -> None:
    await event_bus.publish(
        Topics.LLM_CONNECTION_MODELS_REFRESHED,
        LlmConnectionModelsRefreshedEvent(
            connection_id=connection_id,
            success=True,
            error=None,
            timestamp=datetime.now(UTC),
        ),
        target_user_ids=[user_id],
    )

async def _publish_premium_refreshed(
    self, event_bus, user_id: str, provider_id: str,
) -> None:
    await event_bus.publish(
        Topics.PREMIUM_PROVIDER_MODELS_REFRESHED,
        PremiumProviderModelsRefreshedEvent(
            provider_id=provider_id,
            success=True,
            error=None,
            timestamp=datetime.now(UTC),
        ),
        target_user_ids=[user_id],
    )
```

- [ ] **Step 4: Verify event class names and `get_event_bus` location**

Before running tests, check the imports above resolve correctly:

```
PYTHONPATH=. uv run python -c "from shared.events.llm import LlmConnectionModelsRefreshedEvent, PremiumProviderModelsRefreshedEvent; from backend.ws.event_bus import get_event_bus; from backend.database import get_redis; print('ok')"
```

Expected: prints `ok`. If a `NameError` / `ImportError` surfaces, adjust the import (search the codebase for the actual symbol — `rg -n 'class LlmConnectionModelsRefreshedEvent\|class PremiumProviderModelsRefreshedEvent' shared/events/`).

- [ ] **Step 5: Run the tests to verify they pass**

```
PYTHONPATH=. uv run pytest backend/tests/modules/llm/test_metadata_refresher.py -v
```

Expected: 5 passing tests.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_metadata_refresher.py backend/tests/modules/llm/test_metadata_refresher.py
git commit -m "Implement model cache refresher iteration body"
```

---

### Task 4: Add one-shot triggers for connection / premium upsert paths

**Files:**
- Modify: `backend/modules/llm/_metadata_refresher.py`
- Modify: `backend/tests/modules/llm/test_metadata_refresher.py`

- [ ] **Step 1: Write the failing test for one-shot triggers**

Append to `backend/tests/modules/llm/test_metadata_refresher.py`:

```python
@pytest.mark.asyncio
async def test_trigger_connection_spawns_task_and_returns_immediately():
    r = ModelCacheRefresher()
    fake_conn = _make_resolved("ollama_http", "conn-x")

    refresh_called = asyncio.Event()

    async def fake_refresh(*_args, **_kwargs):
        refresh_called.set()

    with (
        patch.object(r, "_load_connection",
                     AsyncMock(return_value=fake_conn)),
        patch(
            "backend.modules.llm._metadata_refresher._refresh_connection_into_cache",
            AsyncMock(side_effect=fake_refresh),
        ),
        patch.object(r, "_publish_connection_refreshed", AsyncMock()),
    ):
        await r.trigger_connection("conn-x")
        # await the spawned task explicitly via the refresher's tracking:
        await asyncio.wait_for(refresh_called.wait(), timeout=1.0)


@pytest.mark.asyncio
async def test_trigger_connection_swallows_errors():
    r = ModelCacheRefresher()
    fake_conn = _make_resolved("ollama_http", "conn-x")

    async def bad_refresh(*_args, **_kwargs):
        raise RuntimeError("upstream down")

    with (
        patch.object(r, "_load_connection",
                     AsyncMock(return_value=fake_conn)),
        patch(
            "backend.modules.llm._metadata_refresher._refresh_connection_into_cache",
            AsyncMock(side_effect=bad_refresh),
        ),
    ):
        await r.trigger_connection("conn-x")
        # Yield so the spawned task has a chance to fail:
        await asyncio.sleep(0.05)
    # Reaching here without an unhandled-exception warning is the assertion.
```

- [ ] **Step 2: Run the test to verify it fails**

```
PYTHONPATH=. uv run pytest backend/tests/modules/llm/test_metadata_refresher.py::test_trigger_connection_spawns_task_and_returns_immediately -v
```

Expected: FAIL — `trigger_connection` does not exist.

- [ ] **Step 3: Implement the triggers in `_metadata_refresher.py`**

Add inside the `ModelCacheRefresher` class:

```python
async def trigger_connection(self, connection_id: str) -> None:
    """Fire-and-forget refresh of a single connection's cache."""
    asyncio.create_task(
        self._safe_one_shot_connection(connection_id),
        name=f"model-cache-refresh-conn:{connection_id}",
    )

async def trigger_premium(self, user_id: str, provider_id: str) -> None:
    """Fire-and-forget refresh of a single user/provider's cache."""
    asyncio.create_task(
        self._safe_one_shot_premium(user_id, provider_id),
        name=f"model-cache-refresh-prem:{user_id}:{provider_id}",
    )

async def _safe_one_shot_connection(self, connection_id: str) -> None:
    try:
        conn = await self._load_connection(connection_id)
        if conn is None:
            return
        adapter_cls = self._get_adapter_class(conn.adapter_type)
        if adapter_cls is None:
            return
        await _refresh_connection_into_cache(conn, adapter_cls, self._get_redis())
        await self._publish_connection_refreshed(
            self._get_event_bus(), conn.user_id, conn.id,
        )
    except Exception as exc:
        _log.warning(
            "one-shot refresh failed for connection=%s: %s",
            connection_id, exc,
        )

async def _safe_one_shot_premium(
    self, user_id: str, provider_id: str,
) -> None:
    try:
        from backend.modules.llm._resolver import resolve_premium_for_listing
        resolved = await resolve_premium_for_listing(user_id, provider_id)
        if resolved is None:
            return
        adapter_cls = self._get_adapter_class(resolved.adapter_type)
        if adapter_cls is None:
            return
        await _refresh_premium_into_cache(
            resolved, adapter_cls, self._get_redis(), user_id, provider_id,
        )
        await self._publish_premium_refreshed(
            self._get_event_bus(), user_id, provider_id,
        )
    except Exception as exc:
        _log.warning(
            "one-shot refresh failed for premium provider=%s user=%s: %s",
            provider_id, user_id, exc,
        )

async def _load_connection(
    self, connection_id: str,
) -> ResolvedConnection | None:
    from backend.database import get_db
    from backend.modules.llm._connections import ConnectionRepository
    from backend.modules.llm._resolver import _to_resolved

    repo = ConnectionRepository(get_db())
    doc = await repo.find_by_id(connection_id)
    if doc is None:
        return None
    return _to_resolved(doc)
```

Note: `ConnectionRepository.find_by_id` may or may not exist under that exact name — check `_connections.py` around line 111+ for the correct method (likely `find` accepting `(user_id, id)` or a separate `find_by_id`). If only the user-scoped `find(user_id, id)` exists, change `_load_connection` to look up the doc directly via the repo's underlying collection helper, or add a new repo method `find_any(connection_id)` and use that.

Verify with:

```
rg -n "async def find" backend/modules/llm/_connections.py
```

If the only finder needs `user_id`, add this helper to `ConnectionRepository`:

```python
async def find_any(self, connection_id: str) -> dict | None:
    """Look up a connection by id without scoping to a user.
    For internal background jobs only — HTTP code paths must keep using
    the user-scoped finders."""
    return await self._coll.find_one({"_id": connection_id})
```

…and call it from `_load_connection` instead of `find_by_id`.

- [ ] **Step 4: Run the tests to verify they pass**

```
PYTHONPATH=. uv run pytest backend/tests/modules/llm/test_metadata_refresher.py -v
```

Expected: 7 passing tests.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_metadata_refresher.py backend/modules/llm/_connections.py backend/tests/modules/llm/test_metadata_refresher.py
git commit -m "Add one-shot trigger methods to ModelCacheRefresher"
```

---

### Task 5: Wire refresher into app startup

**Files:**
- Modify: `backend/modules/llm/__init__.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Expose the refresher accessor from the LLM module's public API**

In `backend/modules/llm/__init__.py`, add this re-export near the other `from backend.modules.llm._...` imports at the top:

```python
from backend.modules.llm._metadata_refresher import (
    ModelCacheRefresher,
    get_model_cache_refresher,
)
```

…and add both names to the `__all__` list (search the file for the closing `__all__ = [...]` block — append:

```python
    "ModelCacheRefresher",
    "get_model_cache_refresher",
```

- [ ] **Step 2: Wire up hooks in `backend/main.py`**

Find the lines that read:

```python
manager = ConnectionManager()
set_manager(manager)
```

Immediately below them, add:

```python
from backend.modules.llm import get_model_cache_refresher

_refresher = get_model_cache_refresher()
manager.register_on_first_connect(_refresher.ensure_user_task)
manager.register_on_last_disconnect(_refresher.release_user_task)
```

(Place the `from backend.modules.llm import ...` at the top of `main.py` alongside the other imports if the module's import-order conventions prefer that — search `main.py` for other `from backend.modules.` imports as a placement signal.)

- [ ] **Step 3: Verify Python import-graph health**

```
PYTHONPATH=. uv run python -c "from backend.main import app; print('app imported OK')"
```

Expected: prints `app imported OK`. Any `ImportError` here means the LLM module's public re-export has a cycle — break it by deferring the `_metadata_refresher` import inside `get_model_cache_refresher`.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/llm/__init__.py backend/main.py
git commit -m "Wire ModelCacheRefresher to ConnectionManager lifecycle hooks"
```

---

### Task 6: Trigger one-shot refresh after Connection create / update

**Files:**
- Modify: `backend/modules/llm/_handlers.py`

- [ ] **Step 1: Locate the publish sites**

Search for the connection-event publish calls:

```
rg -n "LLM_CONNECTION_CREATED\|LLM_CONNECTION_UPDATED" backend/modules/llm/_handlers.py
```

Note the line numbers reported (approximately 133 and 204 today).

- [ ] **Step 2: Add the refresher import**

At the top of `backend/modules/llm/_handlers.py`, alongside the other `from backend.modules.llm._...` imports, add:

```python
from backend.modules.llm._metadata_refresher import get_model_cache_refresher
```

- [ ] **Step 3: Trigger after `LLM_CONNECTION_CREATED` publish**

After the `event_bus.publish(Topics.LLM_CONNECTION_CREATED, ...)` block in `create_connection`, add:

```python
await get_model_cache_refresher().trigger_connection(doc["_id"])
```

(Use whichever local variable holds the newly-created document's id at that point. If the create handler returns via `ConnectionRepository.to_dto(doc)`, then `doc["_id"]` is correct; if a local `connection_id` variable already exists, prefer that.)

- [ ] **Step 4: Trigger after `LLM_CONNECTION_UPDATED` publish**

Apply the same one-liner — `await get_model_cache_refresher().trigger_connection(<id>)` — after the `LLM_CONNECTION_UPDATED` event publish.

- [ ] **Step 5: Run the existing handler test suite to confirm no regression**

```
PYTHONPATH=. uv run pytest backend/tests/modules/llm/ -v --ignore=backend/tests/modules/llm/test_connections_repo.py --ignore=backend/tests/modules/llm/test_homelabs.py --ignore=backend/tests/modules/llm/test_homelab_self_connection.py --ignore=backend/tests/modules/llm/test_homelab_tokens.py
```

(The four ignored files touch MongoDB and require a running replica set per project memory.)

Expected: no new failures introduced.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_handlers.py
git commit -m "Trigger background model refresh after connection create / update"
```

---

### Task 7: Trigger one-shot refresh after Premium Provider account upsert

**Files:**
- Modify: `backend/modules/providers/_handlers.py`

- [ ] **Step 1: Locate the publish site**

```
rg -n "PREMIUM_PROVIDER_ACCOUNT_UPSERTED" backend/modules/providers/_handlers.py
```

Note the line (approximately 67).

- [ ] **Step 2: Add the trigger**

After the `event_bus.publish(Topics.PREMIUM_PROVIDER_ACCOUNT_UPSERTED, ...)` call, add:

```python
from backend.modules.llm._metadata_refresher import get_model_cache_refresher
await get_model_cache_refresher().trigger_premium(user["sub"], provider_id)
```

(Use the local variable names that already exist in this handler — verify by reading 10 lines above the publish site. The `user_id` is conventionally `user["sub"]` in this codebase.)

- [ ] **Step 3: Run the provider test suite**

```
PYTHONPATH=. uv run pytest backend/tests/modules/providers/ -v
```

Expected: no new failures. If this directory does not exist yet, skip — the next task verifies end-to-end.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/providers/_handlers.py
git commit -m "Trigger background model refresh after premium provider account upsert"
```

---

### Task 8: Extend Redis TTL and remove synchronous fetch from read path

**Files:**
- Modify: `backend/modules/llm/_metadata.py`
- Create: `backend/tests/modules/llm/test_metadata_read_path.py`

- [ ] **Step 1: Write failing read-path tests**

Create `backend/tests/modules/llm/test_metadata_read_path.py`:

```python
"""Read path is pure cache lookup — no synchronous fetch on miss."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._metadata import (
    _cache_key,
    _premium_cache_key,
    get_models_for_connection,
    get_premium_models,
)
from shared.dtos.llm import ModelMetaDto


def _make_conn() -> ResolvedConnection:
    now = datetime.now(UTC)
    return ResolvedConnection(
        id="conn-1",
        user_id="user-a",
        adapter_type="ollama_http",
        display_name="conn-1",
        slug="conn-1",
        config={"url": "http://x", "api_key": "k"},
        created_at=now,
        updated_at=now,
    )


def _fake_redis_with(cached_value: str | None) -> MagicMock:
    redis = MagicMock()
    redis.get = AsyncMock(return_value=cached_value)
    redis.set = AsyncMock()
    redis.delete = AsyncMock()
    return redis


@pytest.mark.asyncio
async def test_connection_cache_miss_returns_empty_without_fetching():
    conn = _make_conn()
    adapter_cls = MagicMock()
    redis = _fake_redis_with(None)

    result = await get_models_for_connection(conn, adapter_cls, redis)

    assert result == []
    adapter_cls.assert_not_called()  # adapter never instantiated
    redis.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_connection_cache_hit_returns_parsed():
    conn = _make_conn()
    adapter_cls = MagicMock()
    model = ModelMetaDto(
        connection_id="conn-1",
        model_id="m",
        display_name="m",
        context_window=4096,
        supports_vision=False,
        supports_tool_calls=False,
    )
    cached = json.dumps([model.model_dump(mode="json")])
    redis = _fake_redis_with(cached)

    result = await get_models_for_connection(conn, adapter_cls, redis)

    assert len(result) == 1
    assert result[0].model_id == "m"


@pytest.mark.asyncio
async def test_connection_cache_validation_error_drops_key_and_returns_empty():
    conn = _make_conn()
    adapter_cls = MagicMock()
    # Garbage that no DTO can parse:
    redis = _fake_redis_with(json.dumps([{"unknown_field": True}]))

    result = await get_models_for_connection(conn, adapter_cls, redis)

    assert result == []
    redis.delete.assert_awaited_once_with(_cache_key("conn-1"))
    adapter_cls.assert_not_called()


@pytest.mark.asyncio
async def test_premium_cache_miss_returns_empty_without_fetching():
    conn = _make_conn()
    adapter_cls = MagicMock()
    redis = _fake_redis_with(None)

    result = await get_premium_models(conn, adapter_cls, redis, "user-a", "xai")

    assert result == []
    adapter_cls.assert_not_called()
    redis.set.assert_not_awaited()
```

- [ ] **Step 2: Confirm `ModelMetaDto` constructor arguments**

The DTO has many required fields beyond the ones used in the test. Re-read the current shape with:

```
rg -n "class ModelMetaDto" -A 40 shared/dtos/llm.py
```

The test currently supplies `connection_id`, `model_id`, `display_name`, `context_window`, `supports_vision`, `supports_tool_calls` — if newer required fields have been added since this plan was written (no `= default`, no `default_factory`), append them to the constructor call.

- [ ] **Step 3: Run the tests to verify they fail**

```
PYTHONPATH=. uv run pytest backend/tests/modules/llm/test_metadata_read_path.py -v
```

Expected: at least the "miss returns empty without fetching" tests FAIL — the current code still calls `_fetch_and_cache` on miss.

- [ ] **Step 4: Modify `_metadata.py`**

In `backend/modules/llm/_metadata.py`:

a. Change the TTL constant:

```python
# was: _TTL_SECONDS = 30 * 60
_TTL_SECONDS = 7 * 24 * 60 * 60
```

b. Replace `get_models_for_connection` with:

```python
async def get_models_for_connection(
    c: ResolvedConnection, adapter_cls: type[BaseAdapter], redis: Redis,
) -> list[ModelMetaDto]:
    """Return cached models or an empty list. The background refresher owns
    cache population; this read path no longer fetches synchronously."""
    cached = await redis.get(_cache_key(c.id))
    if cached is None:
        return []
    try:
        return [ModelMetaDto.model_validate(m) for m in json.loads(cached)]
    except ValidationError as exc:
        _log.warning(
            "stale model cache for connection=%s — dropping: %s",
            c.id, exc,
        )
        await redis.delete(_cache_key(c.id))
        return []
```

c. Replace `get_premium_models` with:

```python
async def get_premium_models(
    c: ResolvedConnection,
    adapter_cls: type[BaseAdapter],
    redis: Redis,
    user_id: str,
    provider_id: str,
) -> list[ModelMetaDto]:
    """Return cached premium-provider models or empty. The background
    refresher owns cache population; no synchronous fetch on miss."""
    cached = await redis.get(_premium_cache_key(user_id, provider_id))
    if cached is None:
        return []
    try:
        return [ModelMetaDto.model_validate(m) for m in json.loads(cached)]
    except ValidationError as exc:
        _log.warning(
            "stale premium model cache for provider=%s user=%s — dropping: %s",
            provider_id, user_id, exc,
        )
        await redis.delete(_premium_cache_key(user_id, provider_id))
        return []
```

The `adapter_cls` parameter is now unused but stays in the signature — many callers pass it positionally and removing it would be a ripple-edit unrelated to this fix. Add `# noqa: ARG001` or a one-line comment if the linter complains.

The `_fetch_and_cache` and `_fetch_and_cache_premium` helpers stay unchanged — they are still called from `refresh_connection_models` / `refresh_premium_models` (the explicit refresh button paths) and now use the new 7-day TTL via the shared `_TTL_SECONDS` constant.

- [ ] **Step 5: Run all read-path tests to verify they pass**

```
PYTHONPATH=. uv run pytest backend/tests/modules/llm/test_metadata_read_path.py -v
```

Expected: 4 passing tests.

- [ ] **Step 6: Run the full LLM test suite (excluding DB-touching files) for regressions**

```
PYTHONPATH=. uv run pytest backend/tests/modules/llm/ -v --ignore=backend/tests/modules/llm/test_connections_repo.py --ignore=backend/tests/modules/llm/test_homelabs.py --ignore=backend/tests/modules/llm/test_homelab_self_connection.py --ignore=backend/tests/modules/llm/test_homelab_tokens.py
```

Expected: no new failures. Any pre-existing test that asserts the old "fetch on miss" behaviour must be updated to reflect the new contract — but that should be flagged explicitly with a comment pointing at this commit, not silently re-asserted.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/llm/_metadata.py backend/tests/modules/llm/test_metadata_read_path.py
git commit -m "Extend model cache TTL to 7 days and remove synchronous fetch on miss"
```

---

### Task 9: Manual verification on a running backend

This is the final pass before declaring the work done. No code changes — only observation against a real backend.

- [ ] **Step 1: Build verification**

```
pnpm --dir frontend run build && PYTHONPATH=. uv run python -m py_compile backend/main.py backend/modules/llm/_metadata.py backend/modules/llm/_metadata_refresher.py backend/ws/manager.py
```

Expected: no errors.

- [ ] **Step 2: Start the backend and connect a frontend session**

Bring up the dev stack (`docker compose up backend redis mongo frontend` or whichever invocation the project uses). Log in as a test user that has at least one LLM Connection and one Premium Provider Account with an LLM-capable adapter (e.g. xAI).

- [ ] **Step 3: Confirm refresh events on connect**

In the browser devtools WebSocket tab (or backend logs), within a few seconds of connecting, you must see both:

- `llm.connection.models_refreshed` for each connection
- `providers.models_refreshed` for each premium provider

- [ ] **Step 4: Inspect Redis TTL**

```
docker compose exec redis redis-cli TTL llm:models:<connection_id>
```

Expected: a value close to 604800 (7 days), not 1800.

- [ ] **Step 5: Simulate cache loss**

```
docker compose exec redis redis-cli DEL llm:models:<connection_id>
```

Then in the UI, edit and save the same connection — observe the one-shot trigger event fire, and confirm the cache key reappears with a fresh TTL.

- [ ] **Step 6: Simulate upstream failure**

Point a connection at an unreachable URL (e.g. `http://localhost:9` for the API endpoint). Wait one refresh cycle. The backend log must show a single `background refresh failed for connection=...` warning per cycle. The previously cached value (if any) must persist in Redis — do not delete it as part of the failure path.

- [ ] **Step 7: Multi-tab refcount**

Open three browser tabs as the same user. In the backend log, only one "refresher task started" line should appear. Close two tabs — log shows nothing further. Close the last tab — log shows "refresher task cancelled".

If the backend does not currently log these transitions, add `_log.info("refresher started for user=%s", user_id)` to `ensure_user_task` (after task creation) and `_log.info("refresher stopped for user=%s", user_id)` to `release_user_task` (after task await) — a separate commit on this branch is fine for this observability nicety.

- [ ] **Step 8: Final commit if any observability tweaks were made**

```bash
git add backend/modules/llm/_metadata_refresher.py
git commit -m "Add info-level start/stop logs to model cache refresher"
```

---

## Plan complete

After all nine tasks land cleanly, merge to `master` (per project default).

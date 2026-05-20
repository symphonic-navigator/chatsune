# Background Model Cache Refresher — Design

**Date:** 2026-05-20
**Status:** Approved, ready for implementation plan
**Scope:** `backend/modules/llm/` and `backend/ws/manager.py`

---

## Problem

The model metadata cache (`backend/modules/llm/_metadata.py`) currently uses a
30-minute Redis TTL on both connection-scoped and premium-provider-scoped
entries. On cache expiry the read path performs a **synchronous** upstream
fetch; on any upstream error it returns `[]` and swallows the exception.

This produces two user-visible symptoms whenever a cache entry expires:

1. **Metadata-dependent features break** — capability lookups, reasoning
   flags, context-window hints, model labels in pickers all collapse to
   defaults because the upstream call is in flight or has failed quietly.
2. **The app appears broken** until the synchronous fetch finishes (or
   times out, in which case it stays broken until the next user-triggered
   read happens to coincide with an upstream recovery).

The fix is to remove the synchronous fetch from the read path entirely and
guarantee a populated cache via a background refresher running for every
online user.

---

## Solution overview

Replace expiry-driven cache invalidation with **stale-while-revalidate**:

- The cache never expires from the user's perspective. A successful
  background refresh atomically replaces the entry; a failed refresh leaves
  the previous value untouched.
- A per-user asyncio task drives the refresh loop. It starts when the user
  opens their first WebSocket and stops when the last WebSocket closes.
- The read path becomes pure: cache hit → return; cache miss → return `[]`.
  No fetching, no swallowing.
- A 7-day Redis TTL acts as a garbage-collection safety net for users who
  go inactive — the background loop refreshes it on every success, so for
  active users it is effectively infinite.

---

## Component design

### 1. `ModelCacheRefresher` (new, internal to LLM module)

Location: `backend/modules/llm/_metadata_refresher.py`

Public surface (called from outside the module via the LLM module's
`__init__.py` re-export):

```python
class ModelCacheRefresher:
    async def ensure_user_task(self, user_id: str) -> None: ...
    async def release_user_task(self, user_id: str) -> None: ...
    async def trigger_connection(self, connection_id: str) -> None: ...
    async def trigger_premium(self, user_id: str, provider_id: str) -> None: ...
```

**Refcounting.** `ensure_user_task` is idempotent and tracks how many
WebSockets each user has open. The task is created on the first call and
cancelled when the refcount returns to zero. Multiple browser tabs do not
create multiple tasks.

**Internal state:**

```python
self._tasks: dict[str, asyncio.Task] = {}
self._refcounts: dict[str, int] = {}
self._lock = asyncio.Lock()  # for refcount mutations
```

**Loop body (`_user_loop`):**

```
loop:
  resolve all connections owned by user_id (DB query each cycle to pick up
    new/removed ones without restart)
  resolve all premium providers active for user_id
  for each: call existing _fetch_and_cache(_premium) helpers
    - on success: redis.set(key, value, ex=7*24*3600); publish refresh event
    - on failure: log warning at WARN level; do nothing else
  sleep(30 * 60 ± random jitter up to 60s)
```

The first iteration runs immediately on task start (no initial sleep) so
that on-connect serves as cold-start population.

**Cancellation.** `release_user_task` decrements refcount; when it hits
zero, the task is cancelled (`task.cancel()`) and then awaited with a
`try/except asyncio.CancelledError` so any in-flight HTTP call gets a
chance to unwind before the entry is removed from `self._tasks`. A
disconnect therefore may block briefly (up to one in-flight upstream
request) — acceptable because disconnect is not on a hot path.

**One-shot triggers.** `trigger_connection` and `trigger_premium` schedule a
single immediate refresh of one cache key (used when a Connection is created
or updated). Implementation: each call spawns an `asyncio.create_task(...)`
that runs the single-key fetch helper and returns immediately to the caller.
They do not interact with the loop's sleep schedule; the loop will simply
re-fetch on its next cycle. Errors inside the spawned task are logged, not
raised. `ensure_user_task` likewise spawns the long-running loop via
`asyncio.create_task(...)` and returns immediately — it never awaits the
loop body itself.

### 2. WebSocket lifecycle hooks

`backend/ws/manager.py` gains two callback registries that remain generic
(the manager must not import from `backend.modules.llm`):

```python
self._on_first_user_connect: list[Callable[[str], Awaitable[None]]] = []
self._on_last_user_disconnect: list[Callable[[str], Awaitable[None]]] = []

def register_on_first_connect(self, cb): self._on_first_user_connect.append(cb)
def register_on_last_disconnect(self, cb): self._on_last_user_disconnect.append(cb)
```

Hooks fire on the **transition** edges only:

- `connect()` fires the first-connect hooks **iff** the user had no prior
  connections (i.e. `user_id` not in `_connections` before insertion).
- `disconnect()` fires the last-disconnect hooks **iff** the disconnect
  drained the user's connection dict.

Hook callbacks are awaited sequentially inside `connect`/`disconnect`. They
must be fast or schedule their own work — they are wrapped in a
`try/except` that logs but does not raise, so a misbehaving hook cannot
take down the WS handshake.

Registration happens at app startup in `backend/main.py` (or wherever the
manager is constructed), wiring `manager.register_on_first_connect(
refresher.ensure_user_task)` and the mirror for disconnect.

### 3. Read-path simplification

In `_metadata.py`, both `get_models_for_connection` and `get_premium_models`
change as follows:

- Cache hit (and validates) → return models.
- Cache hit but `ValidationError` → log, delete key, return `[]`. (Schema
  drift is now the only reason to delete a key from the read path; the
  refresher will repopulate on the next cycle.)
- Cache miss → return `[]`. No upstream call.

The `_fetch_and_cache` and `_fetch_and_cache_premium` helpers stay — they
are still called by the refresher and by the explicit `refresh_*` paths
(used by manual refresh buttons and adapter test endpoints).

The TTL constant changes from `30 * 60` to `7 * 24 * 60 * 60`.

### 4. Connection-lifecycle integration

Where the LLM module already publishes `LLM_CONNECTION_CREATED` /
`LLM_CONNECTION_UPDATED`, also call `refresher.trigger_connection(id)` so a
new connection is populated immediately rather than waiting up to 30
minutes. `LLM_CONNECTION_REMOVED` keeps its current behaviour (deletes the
cache key) and additionally is implicitly handled by the next loop iteration
not seeing the connection in the DB query.

For Premium Provider Accounts, mirror this on
`PREMIUM_PROVIDER_ACCOUNT_UPSERTED`.

---

## Behavioural contract

| Scenario | Behaviour |
|---|---|
| User opens first tab | Refresh task starts; first iteration runs immediately; events fire as each cache key is populated. |
| User opens additional tabs | Refcount increments only; no new task. |
| User closes last tab | Task is cancelled; cache keys keep their 7-day TTL. |
| User reopens within 7 days | New task starts, first iteration refreshes still-valid cache and resets TTL. |
| User stays away > 7 days | Cache keys expire; on next connect the first iteration repopulates them. During the brief window between first read and first successful fetch, model lists are empty. |
| Upstream provider down | Loop logs warnings each cycle, old cache value persists; for very-first-fetch case where there is no old value, model list stays `[]` until upstream recovers. Accepted: a non-functioning upstream provides nothing of value to the user. |
| Backend restart | All tasks gone, cache survives in Redis. Tasks restart as users reconnect. |
| Pydantic schema drift on a cached entry | Read path deletes the poisoned key and returns `[]`; refresher repopulates on next cycle. |

---

## Configuration

Hard-coded constants in `_metadata_refresher.py`:

- `REFRESH_INTERVAL_SECONDS = 30 * 60`
- `REFRESH_JITTER_SECONDS = 60`
- `CACHE_TTL_SECONDS = 7 * 24 * 60 * 60` (mirrored in `_metadata.py`)

Not environment variables — these are operational defaults and should not
diverge between deployments without a code change.

---

## Out of scope

- No backpressure / global rate limiting across all users. Acceptable
  because each user's loop is naturally throttled to a request burst every
  30 minutes, and the number of online users is small.
- No exposure of refresher state via an admin endpoint (could be added
  later for ops; not required for this fix).
- No change to homelab/Ollama-local code paths beyond what they already
  share with the connection-scoped cache.
- No frontend changes. The existing `LLM_CONNECTION_MODELS_REFRESHED` and
  `PREMIUM_PROVIDER_MODELS_REFRESHED` events are already consumed.

---

## Manual verification

After implementation, run these steps on a real backend with one online
user that has at least one LLM connection and one Premium Provider Account
configured:

1. Restart the backend, then connect the frontend. Within a few seconds,
   confirm `LLM_CONNECTION_MODELS_REFRESHED` and
   `PREMIUM_PROVIDER_MODELS_REFRESHED` events arrive (browser devtools WS
   tab or backend log).
2. Inspect Redis: `TTL llm:models:<conn_id>` should return a value close
   to 604800 (7 days), not 1800.
3. Manually delete a cache key: `DEL llm:models:<conn_id>`. Within 30
   minutes (or trigger via a connection update for immediate effect), it
   reappears with a fresh 7-day TTL.
4. Simulate upstream failure: point a connection at an unreachable URL.
   Existing cache value must remain in Redis after the next refresh cycle;
   backend log shows a single warning per failed cycle.
5. Close all browser tabs for the user. Confirm via log/instrumentation
   that the task is cancelled. Reopen — task starts again.
6. Multi-tab: open three tabs, close two. Task must keep running. Close
   the third — task must stop.

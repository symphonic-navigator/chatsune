# Ollama Model Management (pull / delete / cancel)

**Date:** 2026-04-15
**Status:** Design — awaiting implementation
**Scope:** Backend + Frontend

## Goal

Give Chatsune admins and connection owners the ability to manage Ollama
models on their Ollama instances (local and remote) directly from the UI:

- Pull a model by slug, with live download progress
- Cancel a running pull
- Delete an installed model

A "stop" action for running (`ps`) models is out of scope — Ollama has no
API endpoint for it.

## Non-goals

- Persisting pull state across backend restarts
- Slug syntax validation (Ollama itself validates; errors surface via
  `LLM_MODEL_PULL_FAILED`)
- Admin-level aggregation of pulls across users or connections
- Any new behaviour for `/api/ps` — the tab stays as it is

## User-facing surfaces

The same UI appears in two places, via a single shared component:

1. **Admin overlay — "Ollama Local"** (`frontend/src/app/components/admin-modal/OllamaTab.tsx`)
   Uses the admin routes; scope `admin-local`.
2. **Connection editor — Ollama HTTP view** (`frontend/src/core/api/llm-providers/adapter-views/OllamaHttpView.tsx`)
   Uses the adapter sub-router for the current connection; scope
   `connection:{id}`.

Both embed the new `OllamaModelsPanel` component. The only per-embedding
difference is the endpoint set and the scope string.

## Architecture

### Component: `OllamaModelsPanel`

Location: `frontend/src/app/components/ollama/OllamaModelsPanel.tsx`

Props:

```ts
interface OllamaEndpoints {
  ps: string;            // GET
  tags: string;          // GET
  pull: string;          // POST { slug }
  cancel: (pullId: string) => string; // POST
  deleteModel: (name: string) => string; // DELETE
  listPulls: string;     // GET
}

interface OllamaModelsPanelProps {
  scope: string;           // "connection:{id}" | "admin-local"
  endpoints: OllamaEndpoints;
}
```

Layout:

- Existing Subtabs: `Running (ps)` | `Models (tags)` — unchanged, polled
  at the existing 5 s interval while the tab is visible.
- `tags` table: new trailing column with a **Delete** button per row.
- Below the `tags` table: a **Pull model** input + Pull button.
- Below that: an **Active pulls** section driven by `pullProgressStore`.

### Store: `pullProgressStore`

Location: `frontend/src/core/stores/pullProgressStore.ts` (following the
existing store conventions).

State shape:

```ts
type PullEntry = {
  pullId: string;
  slug: string;
  status: string;          // e.g. "pulling manifest", "downloading", "verifying"
  completed: number | null;
  total: number | null;
  startedAt: string;       // ISO timestamp
};

type PullProgressState = {
  byScope: Record<string, Record<string, PullEntry>>; // scope -> pullId -> entry
};
```

Subscriptions:

- `LLM_MODEL_PULL_STARTED` → insert entry
- `LLM_MODEL_PULL_PROGRESS` → merge into entry
- `LLM_MODEL_PULL_COMPLETED` → remove entry, refresh `tags` table
- `LLM_MODEL_PULL_FAILED` → remove entry, raise toast with `user_message`
- `LLM_MODEL_PULL_CANCELLED` → remove entry
- `LLM_MODEL_DELETED` → refresh `tags` table

When `OllamaModelsPanel` mounts, it calls `GET .../pulls` once to hydrate
the store for its scope (handles the case where a pull is already
running from another tab or from before the overlay was opened).

### Backend: adapter sub-router routes

Added to `backend/modules/llm/_adapters/_ollama_http.py` in the adapter's
`router()`. All routes live under
`/api/llm/connections/{connection_id}/adapter/` and are authorised by
the existing connection-owner resolver.

| Method | Path | Body / Params | Response |
|---|---|---|---|
| `POST` | `/pull` | `{ "slug": "llama3.2:3b" }` | `{ "pull_id": "<uuid>" }` |
| `POST` | `/pull/{pull_id}/cancel` | — | `204 No Content` |
| `DELETE` | `/models/{name}` | — | `204 No Content` |
| `GET` | `/pulls` | — | `{ "pulls": [PullHandleDto, ...] }` |

### Backend: admin routes

Added next to the existing `/api/llm/admin/ollama-local/ps|tags`
handlers. Admin-guarded. Thin wrappers that resolve the local Ollama
URL from server config and delegate to the same helper as the adapter
sub-router.

| Method | Path |
|---|---|
| `POST` | `/api/llm/admin/ollama-local/pull` |
| `POST` | `/api/llm/admin/ollama-local/pull/{pull_id}/cancel` |
| `DELETE` | `/api/llm/admin/ollama-local/models/{name}` |
| `GET` | `/api/llm/admin/ollama-local/pulls` |

### Backend: shared helper `OllamaModelOps`

Location: `backend/modules/llm/_ollama_model_ops.py`

Responsibilities:

- Start a streaming pull against `{base_url}/api/pull`, parse JSON lines,
  publish throttled progress events.
- Cancel a running pull by cancelling its `asyncio.Task` (closes the
  `httpx` stream, which Ollama treats as an abort).
- Delete a model via `DELETE {base_url}/api/delete`.
- Translate Ollama errors into stable `error_code` + `user_message` pairs.

Constructor takes `(base_url, api_key_or_none, scope, event_bus, registry)`.
No module may call this helper directly from outside the LLM module.

### Backend: `PullTaskRegistry`

Location: `backend/modules/llm/_pull_registry.py`

In-memory singleton, owned by the LLM module. Keyed by `(scope, pull_id)`.
Holds `PullHandle` records:

```python
@dataclass
class PullHandle:
    pull_id: str
    scope: str          # "connection:{id}" | "admin-local"
    slug: str
    task: asyncio.Task
    last_status: str
    started_at: datetime
```

Methods: `register`, `cancel`, `list(scope)`, internal `_on_done(handle)`
for cleanup. No persistence — if the backend restarts, all handles are
lost and Ollama aborts the downloads because the client is gone. Users
restart the pull manually.

### Progress throttling

Ollama can emit hundreds of progress lines per second for a large
download. `OllamaModelOps` coalesces updates and publishes at most one
`LLM_MODEL_PULL_PROGRESS` event per 200 ms per pull. The terminal
events (`COMPLETED` / `FAILED` / `CANCELLED`) are always emitted
immediately regardless of throttling.

### Correlation IDs

`pull_id` is used as the `correlation_id` for the full lifecycle of a
pull: `STARTED → PROGRESS* → {COMPLETED | FAILED | CANCELLED}`.

## Events

### New topic constants

Added to `shared/topics.py`:

```python
LLM_MODEL_PULL_STARTED   = "llm.model.pull.started"
LLM_MODEL_PULL_PROGRESS  = "llm.model.pull.progress"
LLM_MODEL_PULL_COMPLETED = "llm.model.pull.completed"
LLM_MODEL_PULL_FAILED    = "llm.model.pull.failed"
LLM_MODEL_PULL_CANCELLED = "llm.model.pull.cancelled"
LLM_MODEL_DELETED        = "llm.model.deleted"
```

### New event DTOs

Added to `shared/events/llm.py`:

```python
class ModelPullStartedEvent(BaseModel):
    pull_id: str
    scope: str
    slug: str

class ModelPullProgressEvent(BaseModel):
    pull_id: str
    scope: str
    status: str
    digest: str | None
    completed: int | None
    total: int | None

class ModelPullCompletedEvent(BaseModel):
    pull_id: str
    scope: str
    slug: str

class ModelPullFailedEvent(BaseModel):
    pull_id: str
    scope: str
    slug: str
    error_code: str
    user_message: str

class ModelPullCancelledEvent(BaseModel):
    pull_id: str
    scope: str
    slug: str

class ModelDeletedEvent(BaseModel):
    scope: str
    name: str
```

### Fanout

In `ws/event_bus.py`, all `LLM_MODEL_*` topics follow the same rule
that already applies to `LLM_CONNECTION_*`: delivered to
`target_user_ids` only.

- For a `connection:{id}` scope, `target_user_ids = { owner_user_id }`.
- For `admin-local` scope, `target_user_ids = all admin user IDs`.

## UI interactions

### Pull

1. User types a slug and clicks **Pull**.
2. Frontend calls `POST .../pull { slug }` and clears the input.
3. Backend creates a `PullHandle`, starts the task, and publishes
   `LLM_MODEL_PULL_STARTED`.
4. The store inserts the entry; the row appears in **Active pulls**.
5. Progress events update the row's progress bar and status text.
6. On completion, the row disappears and the `tags` table refreshes.

Multiple parallel pulls are allowed. Ollama decides internally whether
to process them serially or in parallel.

### Cancel

1. User clicks the **X** on an active pull. No confirm dialog — the
   action is explicit and easy to undo (just start again).
2. Frontend calls `POST .../pull/{pull_id}/cancel`.
3. Backend cancels the task, which closes the stream to Ollama.
4. `LLM_MODEL_PULL_CANCELLED` is published; the row disappears.

### Delete

1. User clicks **Delete** on a `tags` row.
2. Frontend shows a confirm dialog: "Delete model `{name}`?".
3. On confirm, frontend calls `DELETE .../models/{name}`.
4. Backend deletes via Ollama and publishes `LLM_MODEL_DELETED`.
5. On the `LLM_MODEL_DELETED` event, the panel triggers a `tags`
   refetch; the row disappears when the refetch completes. No
   optimistic removal — avoids a flash of inconsistent state if
   deletion fails server-side.

## Error handling

`OllamaModelOps` maps HTTP and stream errors into a stable
`error_code` + `user_message` pair. Candidate codes:

- `ollama_unreachable` — network error, DNS failure, connection refused
- `ollama_auth_failed` — 401 / 403 from Ollama
- `model_not_found` — 404 on delete or on a pull that Ollama rejects
- `pull_stream_error` — malformed or truncated stream
- `unknown` — anything else; includes `detail` for logging only

Stack traces never leak to the frontend. `user_message` is kept short
and actionable.

## Testing

- Unit tests for `OllamaModelOps`: stream parsing, throttle behaviour,
  error-mapping.
- Unit tests for `PullTaskRegistry`: register / cancel / cleanup.
- Integration test (mocked Ollama): full lifecycle
  `STARTED → PROGRESS* → COMPLETED` event sequence.
- Integration test: cancel mid-stream produces `CANCELLED`, stream is
  closed, handle is removed.
- Frontend: store reducer tests for the six event types.

## Out of scope / deferred

- Persisting pull progress across backend restarts
- Admin-wide list of pulls across all connections
- Slug auto-complete / model catalogue browsing
- A "stop running model" action (no Ollama endpoint)

## Files touched

New:

- `backend/modules/llm/_ollama_model_ops.py`
- `backend/modules/llm/_pull_registry.py`
- `frontend/src/app/components/ollama/OllamaModelsPanel.tsx`
- `frontend/src/core/stores/pullProgressStore.ts`

Modified:

- `backend/modules/llm/_adapters/_ollama_http.py` — new routes in `router()`
- `backend/modules/llm/_admin_handlers.py` (or equivalent) — admin routes
- `backend/ws/event_bus.py` — fanout rule for `LLM_MODEL_*`
- `shared/topics.py` — new topic constants
- `shared/events/llm.py` — new event DTOs
- `frontend/src/app/components/admin-modal/OllamaTab.tsx` — embed
  `OllamaModelsPanel` with admin endpoints
- `frontend/src/core/api/llm-providers/adapter-views/OllamaHttpView.tsx`
  — embed `OllamaModelsPanel` with adapter endpoints
- `frontend/src/core/api/llm/types.ts` — new DTO types

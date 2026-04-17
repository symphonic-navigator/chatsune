# Ollama Local Adapter + Admin Cache Invalidation

**Status:** Approved
**Date:** 2026-04-08

## Goal

Add a second Ollama upstream adapter (`ollama_local`) alongside the existing
`ollama_cloud`, sharing all HTTP/translation logic via a common base class. The
local provider is global (no per-user credential), self-discovering ("if it's
there, it's there"), and surfaces a "Local Ollama" reachability pill in the
frontend topbar. Additionally, the admin Models page gets an "Invalidate caches
& refresh" button that wipes and rebuilds the model cache for all upstream
providers in one click.

## Motivation

Chatsune is privacy-first and self-hosted. Users running the platform on their
own hardware frequently also run Ollama locally on the same box (or LAN). Today
the only way to use Ollama is via Ollama Cloud with a per-user API key. Local
Ollama removes that hurdle entirely — no key, no setup, just works if the
daemon is reachable.

The admin cache-invalidation button is a small operational quality-of-life
addition: today the model cache only refreshes on demand via the existing
"Refresh providers" path, but there is no way to force a full eviction (e.g.
after pulling a new model on the Ollama host).

## Design

### 1. Adapter refactoring — shared base class

New file `backend/modules/llm/_adapters/_ollama_base.py` introduces
`OllamaBaseAdapter(BaseAdapter)` containing all logic currently in
`_ollama_cloud.py`:

- `fetch_models()`
- `stream_completion()`
- `_build_chat_payload()`
- `_map_to_dto()`
- module-level helpers `_parse_parameter_size`, `_format_parameter_count`,
  `_build_display_name`, `_translate_message` move into this file

Subclasses override only:

- Class attributes `provider_id: str` and `provider_display_name: str`
- New hook method `_auth_headers(api_key: str | None) -> dict` — invoked by
  `fetch_models` and `stream_completion` instead of inlining the
  `Authorization` header
- `validate_key()`
- `_map_to_dto()` consumes `self.provider_id` / `self.provider_display_name`
  rather than hard-coded literals

`OllamaCloudAdapter` shrinks to roughly 25 lines: class attributes,
`_auth_headers` returning `{"Authorization": f"Bearer {api_key}"}`, and the
existing `validate_key` against `/api/me`.

`OllamaLocalAdapter`:

```python
class OllamaLocalAdapter(OllamaBaseAdapter):
    provider_id = "ollama_local"
    provider_display_name = "Ollama Local"
    requires_key_for_listing = False

    def _auth_headers(self, api_key: str | None) -> dict:
        return {}

    async def validate_key(self, api_key: str | None) -> bool:
        return True
```

### 2. Registry & configuration

`backend/modules/llm/_registry.py`:

```python
ADAPTER_REGISTRY = {
    "ollama_cloud": OllamaCloudAdapter,
    "ollama_local": OllamaLocalAdapter,
}
PROVIDER_DISPLAY_NAMES = {
    "ollama_cloud": "Ollama Cloud",
    "ollama_local": "Ollama Local",
}
PROVIDER_BASE_URLS = {
    "ollama_cloud": "https://ollama.com",
    "ollama_local": "http://localhost:11434",
}
```

The local base URL is overridable via the env variable
`OLLAMA_LOCAL_BASE_URL`. At adapter instantiation time, the env var (if set)
takes precedence over the registry default. Both `.env.example` and
`README.md` document the variable.

### 3. Global-provider handling (no per-user credential)

Ollama Local has no API key and no per-user opt-in. Every authenticated user
sees its models automatically.

In `backend/modules/llm/_handlers.py` and `_metadata.py`, the per-provider
loops branch on `requires_key_for_listing`:

- **`requires_key_for_listing == False`** — skip the credential lookup
  entirely; call `fetch_models()` and `stream_completion(api_key=None, ...)`
  directly. The adapter ignores the key.
- **Failure modes** — if `fetch_models()` raises (`httpx.ConnectError`,
  timeout, non-200), the failure is logged and the provider contributes an
  **empty model list**. No exception propagates. "Server not running" is a
  legitimate steady state, not an error.

The model picker therefore shows ollama_local models for every user iff the
local daemon is reachable at refresh time.

### 4. Provider reachability status

Reachability is defined as: **the most recent refresh attempt for this
provider succeeded and produced ≥1 model.** No separate health-poll loop.

`_metadata.py` records per-provider status alongside the model cache. Either
as part of the existing cached object or as a small Redis key
`llm:provider_status:{provider_id}` containing:

```
{available: bool, last_refresh_at: datetime, model_count: int}
```

The status is written after every provider fetch inside
`refresh_all_providers`.

A new event `Topics.LLM_PROVIDER_STATUS_CHANGED` is published **only when
`available` flips** (false→true or true→false), not on every refresh. The
event payload identifies the provider and its new status.

A new DTO/event `LlmProviderStatusSnapshotEvent` (or extension of an existing
"initial state on connect" event — whichever matches the project pattern) is
sent on WebSocket connect so the frontend has the current state for all
providers without waiting for a flip.

New shared additions:

- `shared/topics.py`: `LLM_PROVIDER_STATUS_CHANGED`, possibly
  `LLM_PROVIDER_STATUS_SNAPSHOT`
- `shared/events/llm.py`: matching event classes

### 5. Frontend — Local Ollama pill

In `frontend/src/app/components/topbar/Topbar.tsx`, immediately to the left of
the existing `LivePill`:

- New store slice (extension of `useEventStore` or sibling slice)
  `llmProviderStatus: Record<string, {available: boolean}>`, fed by the
  snapshot event on connect and updated by `LLM_PROVIDER_STATUS_CHANGED`.
- New small component `ProviderPill` taking `provider` and `label` props.
  Renders the same green-dot pill as `LivePill` (same `bg-live` class, same
  text styling) **only when** `llmProviderStatus[provider]?.available === true`.
  Returns `null` otherwise.
- Used as `<ProviderPill provider="ollama_local" label="Local Ollama" />`,
  inserted at both Topbar render sites (header and sidebar).

The component is generic so future provider pills (OpenAI, Anthropic) can be
added trivially, but only the Local Ollama instance is wired up in this work.

### 6. Admin "Invalidate caches & refresh" button

**Backend.** New admin-only endpoint
`POST /api/llm/admin/refresh-models`. Behaviour:

1. Wipe all per-provider model cache entries (so models removed upstream
   actually disappear).
2. Call `refresh_all_providers()` (the existing function, possibly with a new
   `force=True` parameter that bypasses any TTL guard).
3. Return a small summary `{providers: [{provider_id, model_count, available,
   error?}, ...]}`.

The existing `LLM_MODELS_FETCH_STARTED` / `LLM_MODELS_FETCH_COMPLETED` events
are published as today, so the frontend updates via its existing
subscription path. The provider-status events from §4 fire as a side effect.

**Frontend.** In
`frontend/src/app/components/admin-modal/ModelsTab.tsx`, next to the existing
"Refresh providers" button (around line 108), add a new button **"Invalidate
caches & refresh"**. Same button style. On click: call the new endpoint, show
a spinner while pending, then rely on the existing event subscription to
re-render the model list.

### 7. Files

**New:**

- `backend/modules/llm/_adapters/_ollama_base.py`
- `backend/modules/llm/_adapters/_ollama_local.py`
- `frontend/src/app/components/topbar/ProviderPill.tsx` (or inline in Topbar)

**Modified:**

- `backend/modules/llm/_adapters/_ollama_cloud.py` (drastically slimmed)
- `backend/modules/llm/_registry.py`
- `backend/modules/llm/_metadata.py` (status tracking, force-refresh path)
- `backend/modules/llm/_handlers.py` (skip-credential path for global
  providers, new admin endpoint)
- `shared/topics.py`
- `shared/events/llm.py`
- `frontend/src/app/components/topbar/Topbar.tsx`
- `frontend/src/core/...` (store slice for provider status, websocket event
  subscription wiring)
- `frontend/src/app/components/admin-modal/ModelsTab.tsx`
- `.env.example`
- `README.md` (document `OLLAMA_LOCAL_BASE_URL`)

## Decisions

- **Global, not per-user.** Ollama Local is shared across all users. No
  credential, no opt-in toggle, no per-user base URL. Justification: matches
  the spirit of "if it's there, it's there" and the self-hosted user persona.
- **No health-poll loop.** Reachability is derived from the regular model
  refresh cycle plus the admin invalidate action. A separate background ping
  would be overkill for something that changes rarely.
- **Shared base class (template-method) over flag-based single class.** The
  two adapters differ structurally only in auth, validation, and identity. A
  base class with a small `_auth_headers` hook expresses this most clearly
  and keeps each subclass tiny.
- **Dedicated `LLM_PROVIDER_STATUS_CHANGED` event.** Not reusing
  `LLM_MODELS_FETCH_COMPLETED` — the two carry different semantics and
  conflating them would force the frontend to re-derive status from model
  counts on every refresh.
- **Invalidate = wipe + immediate refetch in one action.** No two-button
  split. Operationally there is no use case for "wipe but don't refetch".
- **Env var name:** `OLLAMA_LOCAL_BASE_URL`.

## Out of scope

- Other provider pills (only Local Ollama in this round)
- Per-user disable / opt-out for `ollama_local`
- Background health-polling loop
- Per-provider selective invalidation in the admin UI (all-at-once only)
- Adapters for additional upstream providers (OpenAI, Anthropic, etc.)

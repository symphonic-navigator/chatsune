# Connections Refactor — Design Spec

## Overview

Chatsune currently couples upstream inference to a singleton pair of providers
(`ollama_cloud`, `ollama_local`). Each provider has one global base URL and
one per-user API key. This refactor replaces the singleton model with a
**per-user, multi-instance Connection model**: the user owns any number of
named Connections, each pointing at a Connection-specific backend with its
own credentials and concurrency configuration.

The refactor also prepares the ground for a future **Reverse Upstream
Provisioning** feature, where a user runs a sidecar in their homelab that
opens an outbound WebSocket to Chatsune and exposes a local Ollama instance
as an inference backend without any inbound port forwarding.

### Driving Principles

- **User owns the upstream relationship.** Each Connection is provisioned and
  maintained by the user. There are no admin-managed or shared Connections.
- **Adapter vs. Instance.** The adapter is code (how to talk to a backend type);
  a Connection is configuration (which URL, which key, which concurrency
  budget). One adapter supports many Connections.
- **Adapters are mini-plugins.** An adapter brings its own FastAPI sub-router
  for adapter-specific operations (test, diagnostics, pair, ...) and nominates
  a `view_id` that the frontend resolves to a bespoke React component.
- **No admin curation.** The model-curation layer (global admin ratings /
  descriptions / hide flags) is removed; user decides for themselves.
- **Hard-cut migration.** This is prototype 3; no migration code is written.
  A startup cleanup drops the affected collections and nulls stale persona
  references, users re-create their Connections and re-wire personas.

### Scope

- Replace `llm_user_credentials`, `llm_model_curations`, the global adapter
  registry, and the `ConcurrencyPolicy` enum with a Connection-based model.
- Split the `ollama_cloud` / `ollama_local` adapters into a single
  `ollama_http` adapter with UX **Templates** ("Ollama Local", "Ollama
  Cloud", "Custom").
- Move the former admin-only `/api/ps` and `/api/tags` inspection into a
  per-Connection **Diagnostics** panel available on any Ollama-HTTP
  Connection.
- Give Web Search its own credential store and remove the `KEY_SOURCES`
  sharing mechanism (INS-009 is superseded).
- Update the frontend with a new **LLM Providers** tab in the user modal;
  strip the API-Keys tab down to Web-Search-only entries.
- Prepare the adapter abstraction so a future `ollama_sidecar` adapter can
  be added as a drop-in sibling without touching generic handlers.

Out of scope: implementing the Sidecar adapter itself, adding additional
upstream adapters (OpenRouter / Mistral / Kagi / Brave), or building a
Connection-sharing / marketplace mechanism.

---

## Architecture

### Core Concepts

- **Adapter**: A Python class registered in `ADAPTER_REGISTRY`. Knows how to
  talk to a particular backend *type*. Stateless at the class level; each
  inference instantiates the adapter with a `ResolvedConnection`. Declares
  its `adapter_type`, `display_name`, `view_id`, `secret_fields`, a list of
  `templates()`, an optional FastAPI `router()`, and implements
  `fetch_models()` and `stream_completion()`.
- **Connection**: A Mongo document owned by one user. Combines an adapter
  type with user-chosen display name, unique slug, and adapter-specific
  config (URL, API key, `max_parallel`, ...). This is the identity all
  downstream systems reference.
- **Adapter Template**: A named preset exposed by the adapter for the "add
  Connection" wizard. Supplies default display name, slug prefix, and
  config values. Purely a UX affordance — templates are not persisted
  anywhere; only the resulting Connection is.
- **ResolvedConnection**: Runtime DTO passed to adapter methods. Merges the
  plain `config` with the decrypted secret fields; the adapter never sees a
  raw Mongo document.

### Data Flow — Inference

1. A call site (chat orchestrator, vision fallback, job runner) has a
   `model_unique_id = "<connection_id>:<model_slug>"` and a user ID.
2. `llm.stream_completion(user_id, model_unique_id, request)` parses out
   the `connection_id`, loads the owning Connection, asserts it belongs to
   the caller's user, decrypts secrets → `ResolvedConnection`.
3. Acquires the semaphore for that `connection_id` from the
   `ConnectionSemaphoreRegistry` (size = `config.max_parallel`).
4. Instantiates the adapter, invokes `stream_completion(resolved, request)`.
5. Forwards provider stream events to the caller, publishes inference
   tracker events (debug overlay) as before.
6. Releases the semaphore and unregisters the tracker on completion.

### Data Flow — Model Listing

1. Frontend fetches `GET /api/llm/connections/{id}/models`.
2. Backend reads `llm:models:{connection_id}` from Redis (30-min TTL,
   same as today but keyed per Connection).
3. On miss: loads Connection → `ResolvedConnection` → `adapter.fetch_models`
   → persists to Redis → returns.
4. `POST /api/llm/connections/{id}/refresh` drops the Redis key and
   re-fetches eagerly; publishes `llm.connection.models_refreshed` so the
   frontend invalidates and re-fetches.

### Data Flow — Per-Connection Diagnostics (Ollama HTTP)

The adapter's sub-router exposes `GET /api/llm/connections/{id}/adapter/diagnostics`.
Handler:

1. Receives `ResolvedConnection` via dependency.
2. Concurrently calls `{url}/api/ps` and `{url}/api/tags` with the
   Connection's API key (if any).
3. Returns a combined payload: running models (from `/api/ps`) + available
   tags (from `/api/tags`). HTTP errors are mapped to structured error
   payloads the frontend can render ("Connection unreachable",
   "Unauthorised", etc.) without the UI having to know Ollama specifics.

### Concurrency

- Per-Connection asyncio `Semaphore(max_parallel)`, keyed by `connection_id`,
  held in a process-local registry.
- On Connection delete: semaphore evicted from the registry.
- On Connection update that changes `max_parallel`: the existing semaphore
  is evicted and recreated on the next request. In-flight inferences
  continue under the old budget; this simplification is acceptable since
  `max_parallel` changes are rare and never concurrent with the exact
  inference they would affect.
- **Lock granularity**: by `connection_id` only. Two Connections pointing at
  the same URL get independent semaphores. The wizard warns on URL collision
  with an existing Connection but does not block — users who genuinely have
  two Ollama Cloud accounts on the same URL have a legitimate use case; a
  user mistakenly double-provisioning their local Ollama gets a visible
  nudge.

### Adapter Abstraction

```python
class BaseAdapter(ABC):
    adapter_type: str
    display_name: str
    view_id: str
    secret_fields: frozenset[str]

    @classmethod
    def templates(cls) -> list[AdapterTemplate]: ...

    @classmethod
    def router(cls) -> APIRouter | None: ...

    @abstractmethod
    async def fetch_models(self, c: ResolvedConnection) -> list[ModelMetaDto]: ...

    @abstractmethod
    def stream_completion(
        self, c: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]: ...
```

`ConcurrencyPolicy` and the lock registry are removed. Adapters no longer
carry `requires_key_for_listing`, `requires_setup`, or `is_global` flags —
all of those were singleton-world concerns.

### Sidecar Preparation

The Sidecar adapter (future work) will:

- Declare `adapter_type = "ollama_sidecar"`, `view_id = "ollama_sidecar"`.
- `secret_fields = {"pairing_token"}`.
- Skip `url` in its config, replace with `pairing_token`.
- Register endpoints `POST /pair` / `DELETE /pair` in its sub-router.
- Listen for inbound WebSocket frames from the sidecar via a separate WS
  endpoint (design deferred).
- Implement `stream_completion` by routing the request to the connected
  sidecar over the established WS channel.

The abstraction introduced here is intentionally transport-agnostic:
`stream_completion` promises only to yield `ProviderStreamEvent`s given a
`ResolvedConnection` and a `CompletionRequest`. How the bytes move is the
adapter's business.

---

## Data Model

### New Collection: `llm_connections`

```
{
  _id: str (uuid4),
  user_id: str,
  adapter_type: str,              # e.g. "ollama_http"
  display_name: str,              # user-visible, e.g. "Ollama Cloud"
  slug: str,                      # user-scoped unique, e.g. "ollama-cloud"
  config: dict,                   # adapter-specific, plain fields
  config_encrypted: dict,         # adapter-specific, encrypted fields (api_key, ...)
  last_test_status: str | null,   # "untested" | "valid" | "failed"
  last_test_error: str | null,
  last_test_at: datetime | null,
  created_at: datetime,
  updated_at: datetime,
}
```

**Indexes:**

- `(user_id, slug)` unique
- `(user_id, created_at)` for deterministic listing order

**Encryption:** fields named in `adapter.secret_fields` are encrypted with
the existing Fernet key (`settings.encryption_key`) and stored in
`config_encrypted`. Everything else lives in `config` as plain data.
Resolver merges the two into `ResolvedConnection.config` at read time.

### Removed Collections

- `llm_user_credentials` — replaced by `llm_connections`.
- `llm_model_curations` — curation feature eliminated.

### Collection Reset (structure unchanged, data dropped)

- `llm_user_model_configs` — schema unchanged, but `model_unique_id`
  semantics change from `<provider_id>:<slug>` to
  `<connection_id>:<slug>`. Hard-cut drops all existing rows.

### New Collection: `websearch_user_credentials`

```
{
  _id: str (uuid4),
  user_id: str,
  provider_id: str,              # "ollama_cloud_search" for v1
  api_key_encrypted: str,
  last_test_status: str | null,
  last_test_error: str | null,
  last_test_at: datetime | null,
  created_at: datetime,
  updated_at: datetime,
}
```

**Index:** `(user_id, provider_id)` unique.

### Redis Keys

- `llm:models:{connection_id}` — 30-min TTL, same serialisation as today.
- Removed: `llm:provider:status:{provider_id}` — Connection status lives in
  Mongo and in transient events.

### Persona Impact

`personas.model_unique_id` remains a nullable string but carries the new
format `<connection_id>:<model_slug>`. During hard-cut, every Persona's
`model_unique_id` is set to `null`; the UI surfaces a "model not wired"
state and prompts the user to re-select.

### Chat-Session Impact

Historical chat-session documents that carry `model_unique_id` are kept
verbatim. The value is informational and is no longer resolved on read,
so stale references never raise an error.

---

## Backend API

### Generic Connection Endpoints (LLM module)

```
GET    /api/llm/connections                          → ConnectionDto[]
POST   /api/llm/connections                          → ConnectionDto
       body: { adapter_type, display_name, slug, config }
       Backend validates slug uniqueness (per user);
       if slug exists, 409 with a suggested auto-suffixed slug in body.
GET    /api/llm/connections/{id}                     → ConnectionDto
PATCH  /api/llm/connections/{id}                     → ConnectionDto
       body: partial { display_name?, slug?, config? }
DELETE /api/llm/connections/{id}                     → 204
       Side effects: drop Redis model cache, evict semaphore, unwire
       personas that reference this Connection (set model_unique_id to null,
       publish persona.updated events for each affected persona).

GET    /api/llm/connections/{id}/models              → ModelMetaDto[]
POST   /api/llm/connections/{id}/refresh             → 202
       Drops Redis cache, triggers an async refresh, publishes
       llm.connection.models_refreshed on completion.

GET    /api/llm/adapters                             → AdapterDto[]
       Each: { adapter_type, display_name, view_id, templates,
               config_schema, secret_fields }
```

`config_schema` is a JSON-schema-ish hint list used by the wizard for
field types/validation — not a general-purpose schema engine; just enough
to render form fields without the frontend knowing adapter internals.

### Adapter Sub-Router (Ollama HTTP)

Mounted under `/api/llm/connections/{id}/adapter/`. Connection resolution
and ownership check run as dependencies before the sub-router handler is
invoked.

```
POST   /api/llm/connections/{id}/adapter/test        → { valid, error }
GET    /api/llm/connections/{id}/adapter/diagnostics → { ps, tags }
```

### User Model Config Endpoints

```
GET    /api/llm/user-model-configs                                     → UserModelConfigDto[]
GET    /api/llm/connections/{id}/models/{slug:path}/user-config        → UserModelConfigDto
PUT    /api/llm/connections/{id}/models/{slug:path}/user-config        → UserModelConfigDto
DELETE /api/llm/connections/{id}/models/{slug:path}/user-config        → UserModelConfigDto (default)
```

### Web Search Endpoints

```
GET    /api/websearch/providers                                 → WebSearchProviderDto[]
GET    /api/websearch/providers/{pid}/credential                → WebSearchCredentialDto
PUT    /api/websearch/providers/{pid}/credential                → WebSearchCredentialDto
DELETE /api/websearch/providers/{pid}/credential                → 204
POST   /api/websearch/providers/{pid}/test                      → { valid, error }
```

### Removed Endpoints

```
GET    /api/llm/providers
PUT    /api/llm/providers/{pid}/key
DELETE /api/llm/providers/{pid}/key
POST   /api/llm/providers/{pid}/test
POST   /api/llm/providers/{pid}/test-stored
GET    /api/llm/providers/{pid}/models
PUT    /api/llm/providers/{pid}/models/{slug}/curation
DELETE /api/llm/providers/{pid}/models/{slug}/curation
GET    /api/llm/admin/credential-status
POST   /api/llm/admin/refresh-providers
GET    /api/llm/provider-status
GET    /api/llm/admin/ollama-local/ps
GET    /api/llm/admin/ollama-local/tags
```

### DTO Changes

**New:**

- `ConnectionDto` — id, user_id, adapter_type, display_name, slug,
  config (safe: secrets redacted to `{is_set: true}` placeholders),
  last_test_status, last_test_error, last_test_at, created_at, updated_at.
- `AdapterDto` — adapter_type, display_name, view_id, templates,
  config_schema, secret_fields.
- `AdapterTemplateDto` — id, display_name, slug_prefix, config_defaults.
- `WebSearchProviderDto` — provider_id, display_name, is_configured,
  last_test_status, last_test_error.
- `WebSearchCredentialDto` — provider_id, is_configured,
  last_test_status, last_test_error, last_test_at.

**Removed:**

- `ProviderCredentialDto`, `ModelCurationDto`, `SetModelCurationDto`,
  `SetProviderKeyDto`, `FaultyProviderDto`.

**Changed:**

- `ModelMetaDto`: field `provider_id` → `connection_id`;
  field `provider_display_name` → `connection_display_name`;
  field `curation` removed.
- `UserModelConfigDto`: `model_unique_id` format change only (string-level).

---

## WebSocket Events

All new events are per-user unless noted; deliver with
`target_user_ids=[owner]`. **INS-011**: every topic listed below must be
added to `_FANOUT` in `backend/ws/event_bus.py` when implemented.

### New Topics — Connection Lifecycle

```
llm.connection.created           { connection: ConnectionDto }
llm.connection.updated           { connection: ConnectionDto }
llm.connection.removed           { connection_id: str,
                                   affected_persona_ids: list[str] }
llm.connection.tested            { connection_id, valid, error }
llm.connection.status_changed    { connection_id,
                                   status: "reachable" | "unreachable"
                                         | "unauthorised" | "disconnected" }
llm.connection.models_refreshed  { connection_id }   # trigger-only
```

`llm.connection.removed` carries `affected_persona_ids` so the frontend
can update persona state inline without polling.

### New Topics — Web Search

```
websearch.credential.set         { provider_id }
websearch.credential.removed     { provider_id }
websearch.credential.tested      { provider_id, valid, error }
```

### Changed Events — Debug / Inference Tracker

`DebugInferenceStartedEvent` and `DebugInferenceFinishedEvent`:

- `provider_id` → `connection_id`
- Add `connection_slug` and `adapter_type` for admin debug overlay display
- `model_unique_id` keeps the field, new format

### Removed Topics

```
llm.credential.set
llm.credential.removed
llm.credential.tested
llm.model.curated
llm.provider.status_changed
llm.models.fetch_started
llm.models.fetch_completed
```

---

## Frontend UX

### Navigation

- **User Modal → LLM Providers tab** (new): the Connection management page.
  Replaces the former LLM content of the API Keys tab.
- **User Modal → API Keys tab** (retained): now lists Web-Search providers
  only. Currently a single row for "Ollama Web Search"; structured so
  future Brave / Kagi entries slot in without layout changes.
- **Tab badge**: an exclamation-mark indicator appears on the **LLM
  Providers** tab whenever the user has zero Connections, matching the
  existing pattern on the API Keys tab when Ollama Cloud is unconfigured.

### LLM Providers Tab

- Header: "LLM Providers" + "+ Add Connection" button.
- Body: list of the user's Connections sorted by `created_at`.
  Each row:
  - Display name (large), slug (small, monospace, greyed).
  - Adapter-type badge (e.g. "Ollama HTTP").
  - Status pill driven by `last_test_status` and live
    `llm.connection.status_changed` events.
  - Model count (from the latest cached model list for this Connection).
  - Row click opens the **Config Modal**.
- Empty state: single CTA "Noch keine LLM-Verbindung — jetzt einrichten"
  (button → Add-Connection wizard).

### Add-Connection Wizard

Two steps:

1. **Choose adapter** — cards from `GET /api/llm/adapters`. v1 shows a
   single "Ollama" card.
2. **Choose template** — cards from the adapter's `templates`. Ollama HTTP
   ships: "Ollama Local" (url=localhost:11434, max_parallel=1, api_key=""),
   "Ollama Cloud" (url=ollama.com, max_parallel=3, api_key=""), "Custom"
   (empty). Selecting a template opens the Config Modal, pre-filled.

The wizard auto-suggests `display_name` and `slug` based on the template,
and appends a numeric suffix if the slug is already in use. The user can
edit both before saving.

### Connection Config Modal

- Generic frame: title (= display name), Save/Cancel/Delete controls,
  slug and display-name editors at the top.
- Adapter-specific body resolved via `AdapterViewRegistry[view_id]`. For
  `view_id = "ollama_http"`:
  - URL input (text, http/https validator).
  - API key input (masked, toggleable show/hide, omitted display if empty).
  - `max_parallel` number input (min 1, max 32).
  - "Test" button → `POST /api/llm/connections/{id}/adapter/test`,
    renders status inline.
  - "Diagnostics" collapsible panel → `GET .../adapter/diagnostics`.
    Renders running models (ps) and available tags (tags) as two lists.
    Refresh button. Error states: friendly text + HTTP code.
- URL-collision warning: if the user enters a URL matching another of
  their Connections, inline warning "Du hast bereits eine Verbindung zu
  dieser URL (slug: x). Das kann zu unerwartetem Queuing-Verhalten am
  Backend führen." Non-blocking.

### API Keys Tab (slimmed)

- Row for each Web-Search provider returned by
  `GET /api/websearch/providers`.
- v1: "Ollama Web Search" row with key input, Test, Remove.
- Same status-pill and badge conventions as before.

### Model Browser / Persona Model Picker

- Replaces today's grouping by `provider_id` with grouping by **Connection**.
  Group heading: `display_name (slug)`. Users with multiple Ollama Cloud
  accounts see multiple groups.
- Removes the admin-curation column (stars, hidden toggle, admin
  description). Model rows show capabilities (reasoning / vision / tools),
  parameter count, context window, user-config overlays (favourite,
  hidden, notes, custom prompt).
- Persona picker retains selection by `model_unique_id` (new format).
  When the referenced Connection is deleted, the persona UI shows
  "Modell nicht verfügbar — bitte neu zuordnen" and disables inference
  until the user picks a new model.

### Empty/Error States

- No Connections → block chat inputs in the chat view, show inline CTA
  linking to the wizard.
- Persona without `model_unique_id` → banner on the persona view prompting
  the user to pick a model.
- Deleted-Connection persona → same banner, linked to the picker.

---

## Hard-Cut Migration

No data preservation. The first boot of the new version executes a gated
cleanup via a `_migrations` collection marker:

1. `db.llm_user_credentials.drop()`
2. `db.llm_model_curations.drop()`
3. `db.llm_user_model_configs.drop()`
4. `db.personas.update_many({}, {"$set": {"model_unique_id": None}})`
5. Redis: delete all keys matching `llm:models:*` and `llm:provider:status:*`
6. Write marker document `{ _id: "connections_refactor_v1", at: <now> }`.
7. Emit a single structured log line: `"connections_refactor_v1: cleanup
   complete — users must re-create Connections and re-wire personas"`.

The guard is a `find_one({_id: "connections_refactor_v1"})` check on
startup; subsequent boots are no-ops.

Operator communication (out-of-band, not implemented):
"Connections refactor — please re-add your LLM backends under LLM
Providers and re-select models for your personas."

---

## Removed Code (non-exhaustive)

- `backend/modules/llm/_credentials.py`
- `backend/modules/llm/_curation.py`
- `backend/modules/llm/_concurrency.py` (replaced by semaphore registry
  inside the new `_connections.py`)
- `backend/modules/llm/_provider_status.py`
- `backend/modules/llm/_adapters/_ollama_cloud.py`
- `backend/modules/llm/_adapters/_ollama_local.py`
- `backend/modules/llm/_adapters/_ollama_base.py` is renamed / restructured
  as the new `_ollama_http.py` adapter (or retained as shared helper,
  final call made during implementation).
- Admin proxy endpoints for Ollama Local (`/admin/ollama-local/*`).
- `PROVIDER_DISPLAY_NAMES` / `PROVIDER_BASE_URLS` tables in `_registry.py`.
- `KEY_SOURCES` in `websearch/_registry.py`.

Frontend equivalents: `ApiKeysTab` becomes web-search-only;
`ModelBrowser`, `CurationModal`, `ModelList` are restructured or removed.

## New Code (non-exhaustive)

- `backend/modules/llm/_connections.py` — repository + semaphore registry.
- `backend/modules/llm/_adapters/_ollama_http.py` — unified Ollama HTTP
  adapter with templates.
- `backend/modules/websearch/_credentials.py` — Web-Search credentials
  store (mirrors the old `CredentialRepository` pattern).
- `frontend/src/app/components/user-modal/LlmProvidersTab.tsx`.
- `frontend/src/core/adapters/AdapterViewRegistry.ts` + one view component
  per registered adapter (`OllamaHttpView.tsx` in v1).
- New DTO / event / topic files under `shared/`.

---

## INSIGHTS Updates

- **INS-004** — ID format updated: `model_unique_id = "<connection_id>:<model_slug>"`.
- **INS-005 / INS-006** — invalidated. Curation removed; model data reduced
  to two layers (provider metadata in Redis per Connection; user config in
  Mongo). Update the INSIGHTS entries to reflect this.
- **INS-009** — invalidated. `KEY_SOURCES` removed; Web Search owns its
  credentials.
- **New entry** — "Adapter vs. Connection. Adapter declares type, display
  name, view_id, secret fields, templates, and optionally a FastAPI
  sub-router. Connections are user-owned Mongo documents that carry the
  adapter-specific config. Adapters never see Mongo docs directly —
  `ResolvedConnection` is merged with decrypted secrets before hand-off."
- **New entry** — "Concurrency per Connection via `asyncio.Semaphore`,
  keyed by `connection_id`. Lock granularity is intentionally per-id (not
  per-URL): two Connections to the same URL get independent budgets; the
  wizard warns on URL collision but does not block."
- **New entry** — "Hard-cut migration policy for pre-production prototypes:
  mark the one-shot cleanup with a `_migrations` document, drop affected
  collections, null out dependent fields, re-wire is the user's problem."

---

## Risks & Trade-offs

- **Lost persona wiring on upgrade.** Users must re-pick models after the
  hard-cut. Mitigation: clear banner in the persona UI; communication
  out-of-band.
- **Redis footprint** scales with Connection count (not user count alone):
  `N_users × avg_connections × models_per_connection`. For self-hosted
  single-user instances this is negligible; for larger deployments it
  remains bounded (each entry is small, TTL expires idle data).
- **URL-collision footgun** on local Ollama with multiple Connections is
  surfaced via wizard warning but not blocked. A determined user can still
  over-commit their local backend; the failure mode is visible (queue
  timeouts), not silent corruption.
- **`config_schema` is adapter-controlled** and must stay disciplined. The
  v1 schema carries only enough hints for form rendering; extending it
  into a full validation DSL is a non-goal.
- **Sidecar future work assumption**: the adapter abstraction has been
  designed *as if* the sidecar will slot in, but the actual WS transport,
  pairing handshake, and reconnect semantics are deferred. A design-only
  review in a future spec will confirm whether the current abstraction
  survives first contact; changes confined to the adapter itself are
  acceptable, changes that propagate into generic handlers are not.

---

## Testing Posture

- **Unit**: adapter contract (template listing, config schema rendering,
  stream-completion happy path / 401 / 503), semaphore registry eviction,
  slug uniqueness and auto-suffixing.
- **Integration**: full Connection CRUD via HTTP; event emission on each
  mutation; Redis cache hit / miss paths for model listing; persona
  unwire on Connection delete.
- **Manual**: new user flow (empty state → wizard → first inference);
  existing user flow post-cleanup (personas unwired → re-pick →
  inference resumes); diagnostics panel against a live local Ollama;
  URL-collision warning.
- **Regression**: chat, memory consolidation, journal, vision fallback
  all still resolve models through the new inference path.
- **Out of scope for this refactor**: testing the unimplemented sidecar
  adapter.

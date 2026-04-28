# Chatsune — Progressive Discovery Log

Architectural decisions and design insights that emerged during development.
These are not hard requirements (those live in CLAUDE.md) but rather
reasoning that explains *why* things are built the way they are.

Add an entry whenever a non-obvious design choice is made — especially when
a simpler-seeming alternative was considered and rejected.

---

## INS-001 — Model Metadata: Lazy Redis TTL + Fetch Events

**Decision:** Model metadata (available models per provider, including capabilities
like reasoning/vision/tool-calls) is cached in Redis with a 30-minute TTL.
It is fetched lazily: only when a cache miss occurs at request time.
No background cron job.

**Why lazy load:**
A cron job would poll the upstream provider even when no user is active.
Lazy loading means the upstream is only hit when someone actually needs the data,
and Redis absorbs all subsequent requests until the TTL expires.

**Fetch events (added April 2026):**
When the UI triggers a full model refresh across all providers (e.g. admin model
management, or opening the model browser after cache expiry), the backend publishes
two events via `refresh_all_providers()`:

- `llm.models.fetch_started` — carries the list of provider IDs being queried and
  a `correlation_id`. The frontend can show a loading indicator.
- `llm.models.fetch_completed` — carries `status` (success/partial/failed),
  `total_models` count, and a `faulty_providers` list with error details per
  provider that failed. This supports partially successful multi-provider fetches.

These events exist because we now have multiple upstream providers and fetching
from source is not instantaneous. The UI needs to communicate progress and errors
to the user — especially when a provider is down. Cached reads (from Redis) remain
event-free since they are near-instant.

**Trade-off accepted:**
The very first user to open the model picker after TTL expiry bears the latency
of the upstream fetch. This is acceptable — the list is small and Ollama's API
is fast. If this ever becomes a problem, a soft background refresh on startup
can be added without changing the contract.

**When to revisit:**
If Ollama introduces per-user model availability (e.g. gated models per
subscription tier), the global cache becomes invalid and must be replaced
with per-user caching. Document this change here when it happens.

---

## INS-002 — BYOK (Bring Your Own Key) as a First-Class Principle

**Decision:** Every user manages their own API keys for upstream inference providers.
There is no admin-managed shared key. No user can use a provider without
having configured their own key for it.

**Why:**
Chatsune is a self-hosted, privacy-first platform. The operator deploys the
software; users pay for their own compute. Pooling keys couples user activity
to a single account, creates billing attribution problems, and violates the
privacy model. This is a deliberate departure from tools like Open WebUI,
which historically resist per-user key management.

**Implication for the LLM module:**
The LLM module owns a `llm_user_credentials` MongoDB collection keyed by
`(user_id, provider_id)`. The actual API key is stored encrypted.
The key is never returned via the API — only `is_configured: bool` is exposed.
At inference time, the LLM module looks up the calling user's credential for
the relevant provider.

---

## INS-003 — LLM Adapter Registry Pattern

**Decision:** Adapters for upstream inference providers are registered at startup
in a plain dictionary: `ADAPTER_REGISTRY: dict[str, type[BaseAdapter]]`.

**Why:**
Simple, explicit, and inspectable. No metaclass magic, no auto-discovery,
no plugin system. Adding a new provider = implement `BaseAdapter`, add one line
to `_registry.py`. The provider ID (e.g. `ollama_cloud`) is the dictionary key
and also the first segment of `model_unique_id` (format: `provider_id:model_slug`).

**Adapter location:**
`backend/modules/llm/_adapters/` — internal to the LLM module, never imported
from outside. The `_base.py` defines the abstract interface; each concrete adapter
lives in its own file (e.g. `_ollama_cloud.py`).

---

## INS-004 — Model Unique ID Format

> **SUPERSEDED 2026-04-15 (UI restructure).** Model `unique_id` canonical form is now `<connection_slug>:<model_slug>`. See INS-019.

**Decision (UPDATED 2026-04-14, Connections Refactor):** Models are identified
by `model_unique_id = "<connection_id>:<model_slug>"`. The `connection_id` is
the UUID of a user-owned Connection (see INS-016). The backend validates the
Connection exists and is owned by the calling user; model slug validation is
left to the adapter.

Examples: `7a1b2c3d-4e5f-6789-abcd-ef0123456789:llama3.2`,
`7a1b2c3d-4e5f-6789-abcd-ef0123456789:qwen2.5-coder:32b`

**Parsing:** split on the first `:`. Left segment = Connection UUID (resolved
to a `ResolvedConnection` via the LLM module's generic resolver dependency).
Right segment = model slug, passed as-is to the Connection's adapter.

**Consequence — DTO field rename:** `ModelMetaDto` field `provider_id` is now
`connection_id`, and `provider_display_name` is now `connection_display_name`.
Callers that previously matched on adapter/provider identity must now resolve
via the Connection instead.

**Validation:** When a Persona is created or updated with a `model_unique_id`,
the backend verifies the Connection exists, belongs to the calling user, and is
currently enabled. Specific model-slug existence is not validated here (that
would require an upstream call).

---

## INS-005: Two-Layer Model Data (Ephemeral + Persistent)

> **SUPERSEDED 2026-04-14 (Connections Refactor).** Model metadata is now two
> layers: provider metadata cached in Redis **per Connection** (30-min TTL)
> plus user configuration in MongoDB (`llm_user_model_configs`). Admin
> curation is removed; the `llm_model_curations` collection no longer exists.
> See INS-016 for the Adapter vs. Connection distinction that replaced it.

**Decision:** Provider model metadata (Redis, 30min TTL) is stored separately from admin curation (MongoDB, persistent). They are merged at read time.

**Why:** Provider data is volatile — models appear, disappear, change specs on the upstream. Curation is an admin decision that must survive cache flushes and temporary provider outages. Coupling them (as Prototype 2 did) means a cache flush or provider hiccup wipes admin work. Separating them means curation persists even if a model temporarily vanishes.

**Event differentiation:** `llm.model.curated` events carry the full merged DTO (instant client update). `llm.models.refreshed` events are trigger-only (client re-fetches). This distinction matters for frontend implementation: curated = update store in place, refreshed = invalidate and re-fetch.

---

## INS-006 — Three-Layer Model Data (Extension of INS-005)

> **SUPERSEDED 2026-04-14 (Connections Refactor).** Model data is now two
> layers: provider metadata cached in Redis **per Connection** (30-min TTL)
> plus user configuration in MongoDB (`llm_user_model_configs`). The admin
> curation layer (and its `llm_model_curations` collection) has been removed
> — curation is no longer a platform-wide concern. See INS-016.

**Decision:** Model data is now served from three layers, merged at read time:

1. **Provider metadata** (Redis, ephemeral, 30min TTL) — what the model *is*
   (capabilities, parameter count, context window). Fetched from upstream adapter.
2. **Admin curation** (MongoDB, persistent) — how the admin *rates* the model
   (overall rating, hidden flag, admin description). Collection: `llm_model_curations`.
3. **User config** (MongoDB, persistent, per-user) — how the user *uses* the model
   (favourite, hidden, notes, system prompt addition). Collection: `llm_user_model_configs`.

**Why three layers:**
Each layer has a different owner (provider, admin, user), lifecycle (volatile, persistent,
persistent-per-user), and event semantics. Keeping them separate means changes in one layer
never corrupt or invalidate another.

**Default behaviour:**
When no user config document exists, the API returns sensible defaults (not-favourite,
not-hidden, no notes, no system prompt addition). The document is only created on first
explicit user action.

**Delete semantics:**
There is no separate "deleted" event for user config. The DELETE endpoint removes the
MongoDB document but emits an `llm.user_model_config.updated` event with default values.
The frontend handles a single event type — this is a general pattern: if a resource has
sensible defaults, "deleted" and "reset to defaults" are identical from the client's
perspective.

---

## INS-007 — System Prompt Hierarchy

**Decision:** The system prompt for a chat session is assembled from three sources,
concatenated in priority order:

| Priority | Source | Scope |
|----------|--------|-------|
| 1 (highest) | Global system prompt | Platform-wide admin setting |
| 2 | User model config addition | Per user, per model |
| 3 | Persona system prompt | Per persona |

**Why this order:**
The global system prompt contains admin guardrails ("be harmless", content policy).
These must not be overridden by user or persona prompts. The user model config addition
carries community-sourced model-specific tweaks (e.g. "tell Mistral to focus on the last
message") — these are model-level, not persona-level. The persona prompt defines character
and behaviour, which is the most specific and variable layer.

**Implementation note:**
The three layers are concatenated as separate blocks, not merged. Each block is a distinct
section in the final prompt. The context/session management layer (being designed in a
parallel session as of 2026-04-03) will be responsible for assembling the final prompt
from these sources — not the InferenceRunner directly. The admin UI for editing the global
system prompt is part of the prototype UI improvements spec.

**Differentiating feature:**
The user model config system prompt addition is unique to Chatsune. Neither Open WebUI nor
SillyTavern offer per-user per-model prompt additions. This lets users encode community
knowledge about model quirks directly into their configuration.

---

## INS-008 — Sanitized Mode (NSFW Flag System)

**Decision:** Personas, projects, and knowledge base entries can be tagged with an `nsfw: bool`
flag. A global user toggle called "Sanitized Mode" hides all resources that carry this flag.

**Why:**
Chatsune targets mixed deployment scenarios — shared household setups, workplace environments,
or any context where a user needs to temporarily present a clean UI without permanently deleting
or reconfiguring their data. The flag is per-resource; the toggle is per-session (persisted in
user preferences).

**Behaviour when Sanitized Mode is active:**
- NSFW-flagged personas are hidden from the sidebar and persona selection screen.
- NSFW-flagged projects are hidden from the Projects section and project management.
- NSFW-flagged knowledge base entries are excluded from context injection.
- If the user's last active chat involves an NSFW persona, the app falls back to the most
  recently used non-NSFW persona (or the empty/new-chat state if none exists).

**UI placement (TBD at implementation time):**
The toggle should be quickly accessible — candidate locations are the user menu (bottom of
sidebar) or a persistent status pill in the topbar.

**This was requested by users of a prior prototype.** Do not remove this feature without
reviewing whether demand still exists.

---

## INS-009 — Web Search Adapter Registry with KEY_SOURCES

> **SUPERSEDED 2026-04-14 (Connections Refactor).** Web search now owns its
> own credentials in `websearch_user_credentials` — the `KEY_SOURCES`
> key-sharing mechanism and the cross-module `llm.get_api_key()` call have
> been removed. The search provider id was renamed from `ollama_cloud` to
> `ollama_cloud_search` to avoid a namespace collision with the former LLM
> provider id (LLM identifiers are now Connection UUIDs — see INS-016). The
> historical rationale below is preserved for context; do not reintroduce
> the cross-module key borrowing.

**Decision:** Web search is implemented as a separate module (`backend/modules/websearch/`)
with its own adapter registry, mirroring the LLM adapter pattern (INS-003). A `KEY_SOURCES`
dictionary declares where each search provider gets its API key from.

**KEY_SOURCES format:**
```python
KEY_SOURCES: dict[str, str | None] = {
    "ollama_cloud": "llm:ollama_cloud",   # reuse LLM inference key
    # "brave":      None,                  # own credential store
    # "openrouter": "llm:openrouter",      # reuse OpenRouter inference key
}
```

- `"llm:<provider_id>"` — the search provider shares an API key with an LLM
  inference provider. The websearch module calls `llm.get_api_key()` to resolve it.
- `None` — the search provider has its own credential, stored in the websearch
  module's own credential collection (to be added when Brave/Kagi are implemented).

**Why not a single credential store:**
Ollama Cloud uses the same API key for inference and web search — there is no
separate search key. Duplicating the key in a second collection creates a sync
problem (user updates LLM key, search still uses the old one). The `KEY_SOURCES`
mechanism avoids duplication: the LLM module is the single source of truth for
keys it owns; the websearch module simply borrows them.

**Why a separate module (not part of LLM):**
Web search is conceptually a *tool*, not an *inference concern*. Future search
providers (Brave, Kagi) have no relation to LLM inference at all. The module
boundary prevents scope creep in the LLM module.

**Cross-module API:**
The LLM module exposes `get_api_key(user_id, provider_id) -> str` in its public
API specifically for this use case. The websearch module imports it via the
`__init__.py` boundary — no internal imports.

---

## INS-010 — Tool Registry with Group-Based Session Toggling

**Decision:** Server-side and client-side tools are registered in a central
`ToolGroup` registry (`backend/modules/tools/`). Each group bundles related tool
definitions under a single toggle (e.g. "Web Search" controls both `web_search`
and `web_fetch`). Sessions store `disabled_tool_groups: list[str]` — empty by
default, meaning all tools start enabled.

**Why group-based:**
Individual tool toggles would clutter the UI and confuse users. `web_search` and
`web_fetch` are logically one feature — toggling them independently makes no sense.
Groups map to user-facing concepts ("Web Search", "Code Execution"), not
implementation details.

**Why disabled-list (not enabled-list):**
New tools auto-activate in all existing sessions without migration. When a new
`ToolGroup` is registered, `disabled_tool_groups` doesn't contain it, so it is
active by default. This is the desired behaviour: users opt *out*, not in.

**ToolGroup.toggleable flag:**
Not every tool group should appear in the toggle UI. Some tools are always-on
(e.g. a future "artefact" tool that the model uses to structure output). The
`toggleable: bool` flag controls this — non-toggleable groups are always included
in the tool definitions regardless of the session's disabled list.

**ToolGroup.side flag:**
`"server"` tools have an executor and are dispatched by the InferenceRunner.
`"client"` tools have no server-side executor — their definitions are sent to the
model, but tool calls are forwarded to the frontend for execution (e.g. Pyodide
code execution in the browser). This distinction is declared at registration time
so the tool loop knows whether to dispatch locally or forward.

**Tool-call messages are ephemeral:**
Intermediate tool-call/result messages exist only during the tool loop. They are
NOT persisted in `chat_messages`. Only the final assistant response is saved,
alongside lightweight metadata (`web_search_context`) for citation display. This
prevents context bloat when sessions are reopened — a lesson from Prototype 2.

---

## INS-011 — Event Bus Fan-Out Table Must Be Updated for New Topics

**Decision:** Every new event topic that should be delivered via WebSocket MUST be
added to the `_FANOUT` dict in `backend/ws/event_bus.py`. Without an entry, the
event is persisted to Redis Streams but silently NOT delivered to any client. The
event bus logs a warning (`"no fan-out rule for topic — event persisted but not
delivered"`) but this is easy to miss.

**Why this matters:**
When adding `CHAT_SESSION_RESTORED`, the topic was added to `shared/topics.py`,
the event was published from the handler, and the frontend subscribed to it — but
the session didn't reappear in the UI. Root cause: missing `_FANOUT` entry. The
event was stored in Redis but never sent over the WebSocket.

**Checklist for new events:**
1. Define event model in `shared/events/`
2. Add topic constant to `shared/topics.py`
3. Add topic to frontend `core/types/events.ts`
4. **Add topic to `_FANOUT` in `backend/ws/event_bus.py`** ← easy to forget
5. Subscribe in frontend

---

## INS-012 — CSS Zoom Breaks @dnd-kit Coordinate Calculations

**Decision:** When using CSS `body { zoom: X }` with @dnd-kit, a custom modifier
must be applied to all `<DragOverlay>` components to compensate for the coordinate
space mismatch between `getBoundingClientRect()` (zoomed) and pointer events
(unzoomed).

**The modifier** (`frontend/src/core/utils/dndZoomModifier.ts`):
- Divides the pointer delta by the zoom factor (fixes proportional drift)
- Applies a position offset based on `activeNodeRect` (fixes constant shift)
- Formula: `x = transform.x / zoom + activeNodeRect.left * (1/zoom - 1)`

**Why DragOverlay, not DndContext:**
Applying the modifier on both DndContext AND DragOverlay causes double
compensation (overlay moves in the wrong direction). The modifier belongs ONLY
on `<DragOverlay modifiers={zoomModifiers}>`.

**This bug persisted across two prototypes** because CSS zoom coordinate
mismatches are browser-specific and poorly documented. The key insight: the
error is proportional to the element's distance from the viewport origin, which
is why it was most visible horizontally (cards offset by sidebar + centering)
and barely noticeable vertically (cards near the top).

---

## INS-013 — Embedding Query Cache: Count-Bounded Redis LRU

**Decision:** Query-side embeddings (`query_embed`) are cached in Redis using a
count-bounded LRU-by-insertion strategy. Default cap: 16384 entries. Bulk
embeddings (`embed_texts`) are deliberately NOT cached.

**Encoding:**
Vectors are stored as base64-encoded `struct.pack` floats, not JSON. A 768-dim
vector lands at ~4KB encoded vs. ~15KB as a JSON array. At 16384 entries this
caps the Redis footprint at roughly 64MB — leaving room for 4× more entries
within the same memory budget compared to JSON.

**Normalization is shared:**
The query is normalized (`strip().lower()`, whitespace collapsed) once. The
SAME normalized string is used for BOTH the cache key hash AND the model
inference call on a miss. This guarantees coherence: the cached vector is
exactly what a recompute would produce. Without this, two queries that hash to
the same key could legitimately return different vectors and the cache would
be silently wrong.

**Why bulk embeddings are excluded:**
Document chunks rarely repeat verbatim. Caching them would pollute the index
with one-shot entries and evict genuinely hot query embeddings. The cache is
optimized for the search/retrieval pattern where the same query phrase recurs.

**Graceful degradation:**
Every Redis call in `_query_cache.py` is wrapped in try/except. On any failure
the warning is logged with `exc_info=True` and the call falls through — `get`
returns None (treated as a miss), `set` returns silently. The embedding path
must never fail because of cache infrastructure issues.

**Eviction:**
After each `set`, the index sorted set is checked for overflow. Excess entries
(oldest by insertion timestamp) are removed in a single `DELETE` + `ZREM`. The
trim is not atomic with the write, which is fine: redundant evictions on the
already-deleted keys are no-ops.

**Lazy initialization:**
The `QueryCache` is constructed on first call to `query_embed`, not at module
startup. This avoids a startup-order coupling with `connect_db()` and lets the
cache pick up the actual model name from the loaded `EmbeddingModel`.

---

## INS-014 — Responsive Design: Two Layout Stages, Not Three

**Decision:** Chatsune's frontend uses exactly **two layout stages**, split at
Tailwind's `lg:` breakpoint (1024 px): "compact" (< `lg:`, for phone and
tablet) and "desktop" (≥ `lg:`). Tablet is intentionally treated as a larger
phone, not as its own distinct layout.

**Why two and not three:**
Primary target devices are phones. Tablet is "mitgedacht" but not a first-class
citizen — a third layout stage would have doubled the surface area of the
responsive rewrite for marginal gain. Treating tablet as compact means each
component only has two states to reason about, and visual reduction (see
below) applies cleanly at one boundary.

**Visual reduction under `lg:`:**
Effects that contribute to the opulent "prototype style" on desktop —
`backdrop-blur`, decorative `bg-gradient-*`, large custom `shadow-[…]` — are
scoped with `lg:` prefixes so they only appear on desktop. Mobile and tablet
get flat surfaces with solid fallback colours. The colour palette itself
(persona chakras, gold accents, brand gradients like the avatar
`from-purple to-gold`) is **information-bearing and unchanged** across
viewports. This keeps brand identity intact while letting the small screen
breathe.

**Font options stay everywhere:**
Serif / Sans-serif / white-script toggles in `SettingsTab.tsx` are reachable
on all viewports via the mobilised `UserModal` Sheet. White-script exists
specifically for users without OLED displays where pure-white text on pure
black would smear — it is not a visual polish option, it is an accessibility
feature.

**Component primitives:**
- `useViewport` (`frontend/src/core/hooks/useViewport.ts`) — `matchMedia`
  wrapper exposing `isMobile` / `isDesktop` / breakpoint flags. Single source
  of truth for any JS-side viewport branching.
- `useDrawerStore` (`frontend/src/core/store/drawerStore.ts`) — sidebar open
  state on mobile. Not persisted; drawer starts closed on every load.
- `<Sheet>` (`frontend/src/core/components/Sheet.tsx`) — eigene Portal-based
  modal; full-screen under `lg:`, centred dialog above. Hand-rolled to avoid
  a new dependency (Vaul / Radix were considered and rejected). Swipe-to-
  dismiss is deliberately **not** implemented — `disableSwipeToDismiss` is
  kept in the prop interface so a later implementation can land without an
  API break.
- `bodyScrollLock` helper (`frontend/src/core/utils/bodyScrollLock.ts`) —
  counter-based `document.body.style.overflow` guard. Multiple consumers
  (drawer + sheet) can lock concurrently without stepping on each other.

**Overlays split between Sheet-migrated and CSS-scoped:**
Five overlays (`ModelConfigModal`, `CurationModal`, `LibraryEditorModal`,
`BookmarkModal`, `AvatarCropModal`) were migrated to `<Sheet>`. Three
(`UserModal`, `AdminModal`, `PersonaOverlay`) were **not** — they render
inside `<main>` (not as portals) on desktop, deliberately leaving the sidebar
and topbar visible around them. Migrating them to `<Sheet>` would have
changed their desktop framing. Instead they got `lg:`-scoped classes
(`inset-0 lg:inset-4`, `rounded-none lg:rounded-xl`) so mobile gets
full-screen behaviour and desktop is byte-identical to before.

**PWA as a deliberate minimum:**
Chatsune is installable as a PWA (manifest, service worker, install prompt,
update flow via `vite-plugin-pwa`) but the service worker **only caches the
app shell**. No runtime caching of API or WebSocket data. Offline chat was
explicitly rejected because it would break Chatsune's event-first
architecture — state changes must flow through events to stay coherent across
tabs and devices. The app opens offline, shows its shell, and waits for the
connection; that is the intended offline experience.

**Trade-off accepted:**
`vite-plugin-pwa` 1.2.0 lists vite ^7 as a peer but the repo is on vite 8.
Build works fine; peer warning is tolerated until the plugin updates.

---

## INS-015 — WebSocket Reconnect on Tab Resume

**Decision:** The WebSocket client listens for `visibilitychange` and `focus`
events and calls `ensureConnected()` whenever the tab becomes visible or
regains focus. `ensureConnected()` is a cheap no-op if the socket is already
`OPEN`; otherwise it disarms any stale socket and calls `connect()`, which
picks up sequence-based catchup via `?since=<lastSequence>`.

**Why this matters:**
Mobile browsers — iOS Safari in particular — will silently let a backgrounded
WebSocket rot without firing `onclose`. The ping loop (30 s interval) would
eventually notice, but that leaves a window of up to 30 seconds where the
client believes it is connected while events are dropping. On desktop the
same symptom appears after a laptop lid-close.

Prior to this fix, the reconnect path only ran as a reaction to `onclose` /
`onerror`. Tab resume was not an event the client listened for at all. That
was fine in Prototype 2 (desktop-only) but became a real gap once Chatsune
became PWA-installable, because PWA users background the app aggressively.

**Sequence catchup carries the state:**
When `connect()` runs, it appends `?since=<lastSequence>` to the WebSocket
URL. The backend replays any events the client missed from Redis Streams
(24h TTL). This means a tab that was backgrounded for an hour wakes up,
detects the stale socket on resume, reconnects, and receives the full
backlog — no client-side state merging, no explicit "refresh" button, no
user-visible hiccup beyond a brief `reconnecting` status.

**What this is not:**
It is not a heartbeat or keep-alive. The existing 30 s ping stays. It is
also not a general retry on `navigator.onLine` — that API is unreliable
(especially on iOS) and was deliberately avoided. Only explicit viewport
signals (`visibilitychange`, `focus`) trigger the check.

**When to revisit:**
If Chatsune later adds background-sync-style features (deferred message
queueing while offline), this logic needs to coordinate with whatever state
the queue holds before forcing a fresh connection.

---

## INS-016 — Adapter vs. Connection (Connections Refactor, 2026-04-14)

**Decision:** Separate "how to talk to a backend" (Adapter) from "which
instance of a backend a user has configured" (Connection).

- **Adapter** — code. One class per backend type, living in
  `backend/modules/llm/_adapters/`. Declares:
  - `adapter_type: str` (e.g. `"ollama_http"`) — registry key
  - `display_name: str`
  - `view_id: str` — frontend key into `AdapterViewRegistry`
  - `secret_fields: set[str]` — which config keys are encrypted at rest
  - `templates() -> list[ConnectionTemplate]` — pre-filled wizard options
    (e.g. self-hosted Ollama, Ollama Cloud, Custom Ollama-compatible)
  - optional `router() -> APIRouter` — adapter-specific FastAPI sub-router

- **Connection** — data. User-owned MongoDB document carrying the
  adapter-specific config (URL, API key, `max_parallel`, etc.).

Adapters are stateless; a `ResolvedConnection` is constructed per request
and handed to the adapter. Adapter-specific HTTP routes mount under
`/api/llm/connections/{id}/adapter/...` — the LLM module's generic
resolver dependency validates ownership and injects the
`ResolvedConnection` before delegating to the adapter's sub-router.

**Frontend:** `AdapterViewRegistry` is keyed by `view_id` and resolves to
a bespoke React component per adapter, so each backend type can render
its own wizard, settings panel, and diagnostics without a generic
config-form engine.

> The `unique_id` format referenced here is the slug-based form per INS-019 (previously UUID-based per INS-004).

---

## INS-017 — Per-Connection Concurrency

**Decision:** Inference concurrency is bounded per Connection by an
`asyncio.Semaphore(max_parallel)` keyed by `connection_id`, held in a
process-local `ConnectionSemaphoreRegistry` inside
`backend/modules/llm/`. The legacy `ConcurrencyPolicy` enum is removed —
`max_parallel` is a plain integer on the Connection document.

**Lock granularity — per id, not per URL:** If two Connections point at
the same Ollama URL, they get independent semaphores. The wizard warns
on URL collision so the operator knows both budgets will be charged to
the same backend, but it does not block creation (an operator may
deliberately run two Connections against the same URL with different
credentials).

**Rebuild on change:** When a Connection's `max_parallel` is edited, the
semaphore for that `connection_id` is re-created. Inferences already
holding a slot continue under the old budget — they finish naturally. New
acquires use the new semaphore immediately.

**Eviction:** On Connection delete, the semaphore entry is removed from
the registry. If inferences are still in flight they complete normally;
the registry slot is just garbage.

---

## INS-018 — Hard-Cut Migration Policy for Prototype Refactors

**Decision:** Pre-production refactors that change data shape wholesale
drop the affected collections on startup, gated by a marker document in
the `_migrations` collection. No data-preservation code, no online
migration, no dual-read. The operator is expected to re-configure
Connections and re-wire personas out-of-band.

**Pattern:** each such refactor ships a one-shot cleanup module at
`backend/modules/<owning_module>/_migration_<name>.py` exposing
`async def run_if_needed(db, redis)`. The function:
1. Checks `_migrations` for the marker (e.g.
   `connections_refactor_v1`); exits immediately if present.
2. Drops the obsolete collections / Redis keys.
3. Inserts the marker with a timestamp.

`main.py` calls each registered migration once during startup, after DB
and Redis are connected but before any request handlers bind. The
function must be idempotent after the first successful run.

**Why hard-cut:** Prototype 3 has no production users. The cost of
writing, testing, and maintaining online migration code for throwaway
schemas exceeds the cost of re-configuration. This policy is explicitly
revoked at GA; once real users exist, every schema change needs a proper
migration.

---

## INS-019 — Model Unique ID Slug Format (2026-04-15)

**Decision:** Models are identified by `model_unique_id = "<connection_slug>:<model_slug>"`. Supersedes INS-004's UUID-based format.

**Parsing:** split on the first `:`. Left segment = Connection slug (user-defined, unique per user, validated by `_SLUG_RE`). Right segment = model slug (opaque, passed to the adapter).

**Rename cascade:** Renaming a Connection slug is a legitimate user action. The `ConnectionRepository.update` method runs a MongoDB transaction (RS0) that updates the connection document and every `persona.model_unique_id` and `llm_user_model_configs.model_unique_id` of that user matching the old prefix. Publishes `Topics.LLM_CONNECTION_SLUG_RENAMED` so client stores can remap in place. Scope is strictly per-user; cross-user data is never touched.

**Adapter-level filter for unusable models:** The `ollama_http` adapter drops any model without a `context_length` from `list_models()`. A model without a known max context window cannot be reasoned about and is not offered to the user.

**DTO impact:** `ModelMetaDto` gains `connection_slug` (used in `unique_id` composition) and keeps `quantisation_level` (populated where the adapter reports it). `connection_id` is retained for internal bookkeeping (tracker enrichment, debug collector).

---

## INS-020 — Persona & Knowledge Portability: Scope Split, Allowlist Export, Green-Meadow Import (2026-04-15)

**Decision:** Personas and knowledge libraries are exportable/importable as `.chatsune-persona.tar.gz` and `.chatsune-knowledge.tar.gz` archives. The split of what travels with a persona is deliberate and explicit:

- **a) Personality** (always): `system_prompt`, `nsfw`, `name`, `tagline`, `colour_scheme`, `monogram`, `profile_crop`, avatar binary, and the full chat history (all sessions, flat).
- **b) Content** (optional, `include_content` flag): memory (journal entries + memory bodies), artefacts (with their full version history), storage uploads (files tagged to the persona, binaries in `storage/files/`).
- **Excluded, by design**: technical config (`model_unique_id`, temperature, reasoning/soft-cot, vision fallback, voice, MCP, integrations) and knowledge library assignments. Neither is portable across installs — the user reconfigures them after import.

**Why the split:** Technical config binds the persona to the target system's LLM connections and model slugs (INS-019) which don't exist on the receiving side. Knowledge assignments bind to libraries that may not exist. Attempting to carry them would either fail on import or silently produce a broken persona. Forcing the user to re-link is honest and trivial (one click per assignment).

**Archive format:** Gzip-compressed tar with a `manifest.json` as the first file (`format`, `version`, `exported_at`, `include_content`). This allows future format versioning without breaking old archives. All payloads are JSON serialisable with explicit Pydantic DTOs in `shared/dtos/export.py`.

**Explicit field allowlist at serialization:** Session export uses `_EXPORTED_SESSION_FIELDS` in `chat/__init__.py`, NOT `model_dump()` of the raw document. Personality export likewise names each included field. Rationale: this guarantees that when new fields are added to a schema (e.g., a future `project_id` on `ChatSessionDocument`), they are automatically excluded from exports unless a developer explicitly opts them in. This is the mechanism that delivers the "project-linked chats export flat" requirement before the project-linking feature exists.

**New UUIDs on import, id-map for cross-references:** Every imported document gets a fresh UUID (or `ObjectId` where the collection natively uses it — artefacts). Cross-references that must be preserved (artefact → session) use an `original_id` field carried on the export DTO plus an `old_id → new_id` map computed during session import. This way the receiving instance has no collisions with existing data and no assumption of a "clean" database.

**Rollback via cascade helper:** Persona import runs compensating cleanup on any failure by calling `cascade_delete_persona` (factored out of the existing DELETE handler). Both the user-facing DELETE and the import rollback path go through the same helper — behaviour stays identical. Knowledge import uses the existing `KnowledgeRepository.delete_library` cascade. Rollback is best-effort: a failure during rollback is logged but never masks the original exception.

**Knowledge documents re-embed on import:** `knowledge_chunks` and embeddings are NOT exported. The import path funnels each document through the existing upload service (`_create_document_internal`), which triggers chunking and embedding normally via the existing event flow. Exporting embeddings would bind the archive to the embedder version and dimension; re-deriving on import is cheaper than a compatibility matrix.

**200MB caps, both compressed and uncompressed:** HTTP layer rejects uploads >200MB compressed (413). The extractor tracks running uncompressed bytes during tar walk and rejects >200MB uncompressed — zip-bomb protection. Both caps were picked as round "big enough for anything sensible, small enough to fit a response cycle" numbers; revisit if they bite.

**Green-meadow assumption on reimport:** The user after import finds a persona/library that behaves like a freshly created one — new IDs, no links to prior configuration. No merge, no conflict resolution, no "do you want to replace the existing?". This matches user intent for the portability use case and keeps the import path simple and auditable.

**Why not a dedicated `portability` module:** Persona already orchestrates across `chat`, `memory`, `artefact`, `storage` for its cascade delete. Export/import is the same orchestration in the opposite direction, so it belongs in the persona module. A standalone portability module would either re-create those cross-module calls or import persona's internals — either way, a module-boundary regression. Knowledge is small enough that its export/import stays in its own module unchanged.

---

## INS-021 — Cascade-Delete Reports & Bidirectional Library Cleanup (2026-04-15)

**Decision:** Persona and knowledge-library DELETE endpoints return a structured `DeletionReportDto` (`shared/dtos/deletion.py`) listing every cleanup step with a count and a list of warnings. The frontend renders this as a Markdown text dump in a `Sheet` so the user sees exactly what was purged ("6 chat sessions", "3 committed memory journal entries", "5 uncommitted memory journal entries", …) without having to take the system on faith. Privacy is the driver: a delete that doesn't show its work isn't trustworthy.

**Tolerance contract:** The cascade is best-effort. Each step is wrapped: an exception becomes a warning on its row but the cascade continues — a memory-deletion failure must not block storage / avatar / persona-document cleanup. Two specific behaviours are non-negotiable:

- **"File does not exist" is NOT a warning.** Both `BlobStore.delete` and `AvatarStore.delete` use `unlink(missing_ok=True)`; the post-condition (file is gone) is already met. Returning a warning here would scare users about successful deletions. Both stores now return `str | None` — `None` on success including missing-file, an error message string on a real `OSError`.
- **`success` reflects the target document, not the steps.** A persona/library can be reported as deleted even if a sub-step warned; conversely, `success=False` only when the top-level document itself could not be removed. This matches the user's mental model — "is the persona gone? yes/no" — and keeps the report honest about partial outcomes.

**Bidirectional library reference cleanup:** Personas and chat sessions both carry a `knowledge_library_ids: list[str]` array. Before this change, `delete_library` only purged its own documents and chunks — those arrays kept dangling library IDs forever. The new `cascade_delete_library` (`backend/modules/knowledge/_cascade.py`) calls public-API helpers `persona.remove_library_from_all_personas()` and `chat.remove_library_from_all_sessions()` so n:m link cleanup happens synchronously and contributes to the report. The `KNOWLEDGE_LIBRARY_DELETED` event is still published for frontend cache invalidation, but cleanup is NOT event-driven — synchronous calls give us deterministic counts in the report and avoid race windows where an in-flight retrieval might still see the deleted library.

**Why synchronous (not event-driven) for cleanup:** The persona cascade is already synchronous and uses public APIs of the owning modules; the library cascade follows the same pattern for consistency. Event-driven cleanup would require either (a) an additional response-completion handshake to know counts before returning to the user, or (b) returning an incomplete report that grows over time. Both are worse for the report use case. Module boundaries stay intact because every cross-module call goes through `__init__.py`.

**Per-module count helpers were added rather than richer delete return types:** `memory.count_for_persona` (committed / uncommitted / bodies split), `chat.count_messages_for_persona`, plus a `delete_by_persona_with_warnings` variant on `storage` that returns `(count, warnings)`. The plain `delete_by_persona` and `delete_library` keep their old signatures so the import-rollback paths remain untouched. This costs one extra round-trip per category before the delete, but trades that for zero risk to the existing call sites.

**Pre-counts vs post-counts for the memory split:** The cascade snapshots `count_for_persona` BEFORE running the delete, then trusts those numbers in the report. Strictly speaking this is racy (a concurrent insert during the delete window would skew the report), but the persona-being-deleted has no UI flow that can write to it, and the alternative — adding state-aware delete return values across three repository methods — was disproportionate. Documented here so a future reader doesn't "fix" it.

**Knowledge documents are MongoDB-only:** Confirmed during this work — there is no on-disk store for knowledge documents (chunks live in the `knowledge_chunks` collection with the embedding vector inline). The library cascade therefore needs no `BlobStore` step, unlike the persona cascade. If the document model ever gains an on-disk attachment, the library cascade must add an analogous blob-cleanup step and a corresponding "document files" report row.

**Frontend rendering:** A single shared `DeletionReportSheet` component (`frontend/src/core/components/DeletionReportSheet.tsx`) takes a `DeletionReportDto | null` and renders it via `react-markdown` inside the existing `Sheet` overlay. Both the persona overlay and the knowledge tab wire the same component — one component, two consumers, zero duplicated UI.

---

## INS-022 — User Self-Delete (Right-To-Be-Forgotten) (2026-04-15)

**Decision:** Authenticated users can purge their own account via `DELETE /api/users/me`. The cascade reuses the existing persona and knowledge-library cascades (INS-021) rather than re-implementing per-resource cleanup — one source of truth for what "remove this persona / library" means. The user cascade is orchestration only: enumerate → delegate → aggregate.

**Report aggregation, not per-persona sub-reports:** A power user can have ten personas, each with their own chat-session / memory / artefact counts. Dumping ten `DeletionReportDto`s on the user is noise. Instead the orchestrator walks each sub-report and sums `deleted_count` into resource-type totals ("chat sessions" = sum across all personas), preserving first-seen step ordering. The receipt stays short and scannable while still honestly reflecting what was removed.

**Public deletion-report fetch is unauthenticated on purpose.** By the time the user reads their receipt they are logged out; the access token is no longer valid and a login flow is meaningless for an account that no longer exists. The slug (24 bytes of `secrets.token_urlsafe` entropy + 15-minute Redis TTL) IS the capability. Whoever holds the URL can read the report once; after 15 minutes Redis drops the key. No cleanup job needed.

**15-minute TTL:** Long enough to read, copy the report text, and share it with support if something went wrong. Short enough that a dangling Redis key is negligible. Longer TTLs would invite copies leaking from shared-device caches; shorter TTLs would disrupt the receipt-reading flow if the user gets interrupted.

**Master admin cannot self-delete.** Cascading their deletion would orphan the installation — no one left to promote a replacement. The 403 response carries a clear "transfer the role first" message. This is a deliberate gap until role transfer exists; no silent downgrade.

**Redis pseudonymisation:** Every per-user Redis key (`safeguard:queue:{user_id}`, `safeguard:budget:{user_id}:*`, circuit-breaker keys, refresh tokens) embeds only the `user_id` UUID — never username or email. After `users`-document deletion the UUID maps to nothing. SCAN+DEL of those patterns is therefore idempotent cleanup rather than privacy-critical; still performed because dangling keys waste memory.

**Attestation audit row written AFTER the cascade.** The cascade step 8 wipes all audit rows tied to the user; writing a `user.self_deleted` row afterwards leaves exactly one surviving trace — the attestation. This matches GDPR's "legitimate interest" carve-out for records of the deletion itself.

---

## INS-023 — Community Provisioning: Host Self-Connection & Layered Concurrency (2026-04-16)

**Decision:** Homelab hosts access their own compute through a system-managed `community` Connection, auto-created alongside the Homelab under a host-supplied slug. Not a special "host mode" flag on the adapter path — it's an ordinary Connection whose config carries `is_host_self: true` and whose lifecycle is owned by `HomelabService`. The frontend treats `is_system_managed=True` rows as read-only (separate "Self-Hosted" section in the providers list, edit/delete disabled, generic `PATCH/DELETE /connections/{id}` return HTTP 400).

**Why a Connection and not a special path:** the adapter layer, resolver, per-connection semaphore, model-cache, and model-picker all key off Connection. Threading a second path for "host talks to own homelab" through every layer would double the surface area. Making the host-self case a Connection keeps the adapter registry uniform; the only branching is `is_host_self` inside `CommunityAdapter.fetch_models/stream_completion`, which skips api-key validation and the allowlist filter.

**Three layers of concurrency, acquired in order:**

1. **Per-Connection semaphore** (existing, INS-017) — gates each user's own parallel requests through their one Connection.
2. **Per-API-Key semaphore** (new, `ApiKeySemaphoreRegistry` keyed by `api_key_id`, default 1) — lets the host hand out keys with different parallelism budgets (a test key gets 1, a trusted collaborator gets 4). Host-self path skips this layer.
3. **Homelab-wide semaphore** (new, `HomelabSemaphoreRegistry` keyed by `homelab_id`, default 3) — the host's setting for total simultaneous requests across ALL consumers (host-self + every api-key). This is the "homelab total capacity" number the host owns.

All three are process-local `asyncio.Semaphore`s held in `_KeyedSemRegistry`. Size is read from the current DB value and the registry rebuilds on change. Acquisition order in `CommunityAdapter.stream_completion` is api-key → homelab-wide (inside the already-acquired per-connection sem). Sidecar-declared `max_concurrent` from the handshake is left in place as a safety ceiling.

**Host-configured, not sidecar-declared:** the CSP handshake still advertises `max_concurrent`, but what the host edits in the UI is stored on the Homelab document. The host's policy trumps the sidecar's advertisement for the purposes of scheduling; the sidecar's internal semaphore remains as a hard backend safety cap.

**Self-connection lifecycle:** `HomelabService.create_homelab` reserves the slug (rejecting with HTTP 409 + `suggested_slug` on collision), inserts the homelab, inserts the `community` Connection with `is_system_managed=True` and `config.max_parallel = homelab.max_concurrent_requests`, and emits paired `LLM_HOMELAB_CREATED` + `LLM_CONNECTION_CREATED`. `update_homelab` cascades renames and max-concurrency changes to the self-connection. `delete_homelab` drops the self-connection via `delete_by_system` (bypasses the generic `is_system_managed` guard) and evicts all three semaphore registry entries. No MongoDB transaction spans both inserts — the self-connection create runs after the homelab insert and best-effort-rolls-back the homelab on failure; this keeps the service free of Motor session plumbing and the failure mode is tiny (uuid-slug collision within the same user).

**Backwards-compat (no-wipe):** existing homelab documents predate `max_concurrent_requests` and `host_slug` — they deserialise with defaults (`3` and `None` respectively), which means they don't have a self-connection. Hosts of legacy homelabs continue to use API-Keys until they create a new homelab. No migration script; no DB touch. Pydantic models use `int = 3` / `str | None = None` / `bool = False` defaults so old documents decode cleanly (CLAUDE.md §Data-Model Migrations rule).

---

## INS-024 — Usage Telemetry: Cache-Hit Tokens Captured But Not Surfaced (2026-04-20)

**Decision:** Adapters that receive structured cache-hit information from their upstream (xAI returns `usage.prompt_tokens_details.cached_tokens`, Anthropic returns `cache_read_input_tokens` and `cache_creation_input_tokens`, OpenAI returns `prompt_tokens_details.cached_tokens`) currently **discard** this detail. Only the aggregate `input_tokens` / `output_tokens` are forwarded via `StreamDone`, which feeds `ChatStreamEndedEvent.usage`.

**Why this is deliberate (for now):**
The streaming contract (`StreamDone(input_tokens, output_tokens)`) is adapter-neutral and stays minimal. Adding cache-tier fields per provider would either bloat the event with optional provider-specific fields or force a lowest-common-denominator schema that loses information. Neither is worth doing before we know what we want to show the user or charge against.

**When to revisit:**
Planned as a small follow-up iteration after the xAI adapter ships. Goals:

1. **Uniform usage schema** — extend `StreamDone` with an optional `cache_tokens_read: int | None` (and possibly `cache_tokens_written` for Anthropic-style providers) so the chat-end-event carries provider-agnostic cache telemetry.
2. **UI surfacing** — show "N tokens served from cache" in the chat status line or a per-message debug overlay. Lets the user see when `x-grok-conv-id` prefix-stickiness actually pays off, and makes prompt-churn costs visible (helps tuning the PromptAssembler).
3. **Possibly later** — per-connection rolling cost/token aggregates for the connection health view, once multiple providers report cache data.

**What NOT to do:**
Do not bake provider-specific fields into `ChatStreamEndedEvent` (no `xai_cached_prompt_tokens`). Keep the outward contract provider-agnostic; per-provider mapping stays inside each adapter, same pattern as `supports_reasoning`.

---

## INS-025 — Per-user key infrastructure (2026-04-23)

Added a `user_keys` MongoDB collection and a client-side Argon2id → HKDF → server-side H_auth/H_kek login flow. No data is encrypted by this change; the plumbing is in place for later rollout, collection by collection. Key design choices:

- **Client-derived hashes:** the server never sees the plaintext password. `H_auth` is sent in place of the password and bcrypt-hashed server-side; `H_kek` unwraps the DEK and is not stored. The operator holding `ENCRYPTION_KEY` in `.env` gains nothing against a user's data — the DEK is sealed under the user's password-derived key, not the operator's master key.
- **Double-wrap with recovery key:** the DEK is wrapped with AES-256-GCM twice — once under `H_kek`, once under a key derived from a 32-character Crockford-Base32 recovery key. The recovery key is generated client-side, displayed once, and only transits once during signup (or once in the legacy-migration response body). Neither is ever persisted.
- **`deks` as a version-keyed map:** the `user_keys` document stores wrapped keys in `deks: {"1": {...}}` so rotation is an additive schema-compatible change: new rotation adds `"2": {...}` and bumps `current_dek_version`. Nothing to migrate when we add rotation later.
- **Reserved `dek_version` field on per-document payloads:** convention defined but not yet applied. Absent/null = plaintext (legacy or pre-rollout); N ≥ 1 = encrypted with DEK version N for that user. This lets future rollouts be collection-by-collection rather than flag-days.
- **Admin-reset uses a `$SENTINEL$` password hash** that no bcrypt input can match. The login handler detects the sentinel and forces the recovery flow regardless of `H_auth`. After `/recover-dek` succeeds, the sentinel is replaced with a real bcrypt hash derived from the new `H_auth` the user supplied.
- **Legacy users migrate lazily** on their first post-upgrade login via `/login-legacy` — the single path that still accepts a plaintext password, and only once per user. After migration the row looks identical to a freshly signed-up user.
- **User-enumeration defence at `/kdf-params`:** for unknown usernames the server returns a deterministic pseudo-salt derived as `HMAC-SHA256(kdf_pepper, username.lower().strip())`. Indistinguishable from a real user's salt; login then fails at bcrypt as usual. `kdf_pepper` is a new env var, distinct from `encryption_key`.
- **Session-DEK in Redis under `session_dek:{session_id}`** with TTL = access-token TTL. Logout deletes it; refresh extends the TTL. For Phase 1, a refresh that finds an expired Redis DEK still succeeds (logs a warning). Once data is actually encrypted, this will need a design decision — currently tracked as a follow-up.

Follow-ups tracked in `devdocs/superpowers/specs/2026-04-23-per-user-key-infrastructure-design.md` §16.

---

## INS-026 — Nano-GPT: some models stop streaming (and reasoning) when `tools` are present (2026-04-24)

**Observation:** For certain nano-gpt models — confirmed for `xiaomi/mimo-v2.5-pro`, suspected for others — sending a request that includes `tools: [...]` in the body causes the upstream to return the entire completion in a **single SSE frame** instead of token-by-token deltas, and additionally disables the model's reasoning output (the same model emits ~40 `delta.reasoning` chunks when called without `tools`).

Verified with two curl tests against `https://nano-gpt.com/api/v1/chat/completions`, identical apart from the `tools` field:

- **Without `tools`:** ~60 delta frames, reasoning + content streamed normally, `reasoning_tokens > 0`.
- **With `tools`:** 3 frames total (role, one big content chunk, finish/usage), `reasoning_tokens: 0`.

Nothing on our side changes the outcome — this is upstream routing inside nano-gpt (or the provider it proxies to) picking a different execution path when tool-calling is enabled. The adapter, inference pipeline, and WebSocket layer have all been traced chunk-by-chunk (`LLM_TRACE_DELTAS=1`) and faithfully pass through whatever the upstream sends.

**Current stance — no code change.** Chatsune already gates tools by the user's tool-group toggles (`_orchestrator.py:559` via `get_active_definitions(disabled_tool_groups)`), so disabling tool groups in the session restores streaming for affected models. That is the workaround today.

**Why not a capability flag yet:**
We do not know the shape of the problem well enough to design a flag. Open questions:

- Is this a property of the model, the upstream provider behind nano-gpt, or a nano-gpt routing choice?
- Does `parallel_tool_calls` or another OpenAI-compat request property change the behaviour?
- Which of the ~200 nano-gpt models are affected? Correlating against nano-gpt's model metadata (and hints from the nano-gpt Discord) is the next step.

Adding `streams_with_tools: bool` to the model catalogue now would either require guessing per model (likely wrong for many) or a probe-call during import (extra cost, still might be wrong if upstream routing changes). Premature.

**Planned exploration (separate session):**

1. Pull nano-gpt's model metadata and look for correlations — in particular any tool-related capability fields the upstream advertises.
2. Test a handful of popular models with and without `tools` to understand the breadth.
3. Try the `parallel_tool_calls` request property as a potential opt-out for the non-streaming path.
4. Incorporate the Discord hints on list refinement.

**When to revisit:**
Once the exploration lands, decide between (a) a per-model capability flag plus a UI hint when the user has tools enabled on a non-streaming model, or (b) leaving it as documented behaviour if it turns out to be rare enough.

**What NOT to do:**
No silent stripping of `tools` for affected models — that would violate the "no magic, uniform flows" principle. Whatever we eventually build must be visible and user-controllable.

---

## INS-027 — Nano-GPT three-mode reasoning switching: slug pair vs flag singleton (2026-04-24)

**Decision:** The nano-gpt pair map carries a `switching_mode` discriminator with three values — `slug`, `flag`, `none` — and the adapter dispatches accordingly. Flag-mode requests carry `{"reasoning": {"enabled": <bool>}}` in the request body (the OpenRouter unified reasoning object); slug-mode requests select via the upstream slug and carry no reasoning field; plain singletons carry no reasoning field either.

**Why three modes (not two):**
Nano-gpt expresses thinking capability through two distinct mechanisms, not one. Some models arrive as a *pair* of slugs (`base` + `base:thinking`, or rare inverted `base` + `base-nothinking`); others arrive as a *singleton* with `capabilities.reasoning == true` and switch via a body flag. We discovered ~79 switchable singletons in the current dump (xiaomi/mimo-v2.5, openai/gpt-5.x, anthropic/claude-sonnet-latest, gemini-2.5/3.1, grok-4.x). Treating these as plain non-reasoning models — as the previous adapter did — silently denied users the thinking toggle on a major chunk of the catalogue.

**Why the OpenRouter unified format (and not the OpenAI / Anthropic flat alternatives):**
Empirically verified on 2026-04-24 against `xiaomi/mimo-v2.5` (probe scripts under `scratch/probe_nano_flag_mode*`). Of seven candidate body shapes — boolean `reasoning`, `reasoning_effort: minimal/medium/high/none`, boolean `thinking`, object `thinking: {"type": "disabled"}`, and the OpenRouter `{"reasoning": {"enabled": bool}}` — only the OpenRouter nested form actually toggles the model. Cross-vendor confirmation on claude-sonnet-latest and gpt-5.4-nano showed the same field works in both directions across vendors. The flat alternatives are silently ignored.

**Why always send the flag in flag-mode (even when `enabled: false`):**
Vendors disagree on the default thinking direction: gpt-5 family defaults OFF, claude-sonnet-latest defaults ON, mimo-v2.5 defaults ON. Without an explicit `enabled: false`, the user toggling reasoning OFF would have no effect on default-ON vendors. The previous "send only when on" reflex (still present in the upstream `nano-explore` reference at the time of porting) violates this invariant.

**Why never send the flag in slug-mode:**
Empirically, sending `{"reasoning": {"enabled": false}}` to a slug-mode "thinking half" (`xiaomi/mimo-v2-flash-thinking`) suppresses reasoning even though the slug itself selected the thinking variant. The body flag wins over the slug, which would silently invert the user's choice. Strict separation of mechanisms.

**Cache invalidation:** Pair-map Redis key was bumped from `nano_gpt:pair_map:{conn_id}` to `nano_gpt:pair_map:v2:{conn_id}`. The value shape gained `switching_mode`, and a pre-revision entry would deserialise as a none-mode dict with `mode = "none"` (the default in `pair.get("switching_mode", "none")`), silently downgrading switchable singletons. The v2 key parallel-runs with v1; old keys expire on their own 30-minute TTL. A defensive read also rejects any v2-keyed value that lacks `switching_mode` and treats the whole map as a cache miss.

**Frontend impact:** None. `ModelMetaDto.supports_reasoning=True` now covers both "we'll route to a thinking sibling slug" and "we'll set the body flag" — the UI sees the same toggle either way.

**Reference:** Empirical methodology and raw results live in `scratch/probe_nano_flag_mode*.{py,_results.json}` (gitignored). Three-mode pipeline ported from `/home/chris/projects/nano-explore` — that exploration repo carries the model-by-model audit and the canonical mini fixtures used by the chatsune tests.

---

## INS-028 — PTI normalisation lives in two languages (2026-04-25)

The PTI trigger-phrase / message normalisation function lives in two
files that must be kept manually in sync:

- `backend/modules/knowledge/_pti_normalisation.py` — Python authority,
  used at save time and during runtime matching.
- `frontend/src/features/knowledge/normalisePhrase.ts` — used for live
  preview in the trigger-phrase editor.

There is no runtime drift check. When changing the normalisation
algorithm — adding a step, changing a Unicode behaviour, etc. — both
files must be updated together. Pattern is identical to the xAI
voice-expression-tags duplication (see CLAUDE.md and the existing
`backend/modules/integrations/_voice_expression_tags.py`).

**Known approximation:** JS has no exact equivalent of Python's `str.casefold()`. The TS mirror uses `toLocaleLowerCase("en")` plus an explicit `ß → ss` substitution. This covers the practical cases (German ß, uppercase ẞ via `toLocaleLowerCase` then replace). Other locale-specific casefold differences (e.g. Turkish dotted I) are not handled — the backend remains the authoritative normaliser, and the frontend value is only a UI preview.

**Symptom of drift:** tag shown in the editor differs from what the backend
matches against. Test via the existing parametrised tests on each side;
any diff in expected outputs is the smoking gun.

---

## INS-029 — Server cannot enforce password strength (BYO-key constraint)

**Decision:** Password-strength validation lives entirely in the client.
The server has no knowledge of the plaintext password and therefore
cannot apply length/complexity/zxcvbn rules.

**Why:** Chatsune uses an end-to-end encrypted key schema. The client
derives `h_auth` (Argon2 hash for authentication) and `h_kek` (key
encryption key for wrapping the user's DEK) from the password locally.
Only those derived values reach the server. A server-side strength check
would require shipping the password itself, which would defeat the entire
BYO-key threat model.

**What this means in practice:**
- Strength meters and basic typo checks (length, character classes,
  confirm-password match) are client-side concerns.
- This applies to all account-creation flows: master-admin setup,
  invitation-token registration, change-password, recovery flow.
- A future "server enforces strength" change is not a small ticket — it
  would require fundamental rework of the auth scheme. Do not file it
  as a routine improvement.

---

## INS-030 — Account-creation crypto duplicated; extract on third use

**Decision:** The form + Argon2 derivation + recovery-key generation
sequence currently lives in two places: the master-admin setup mode in
`frontend/src/app/pages/LoginPage.tsx` and the invitation-token
self-registration in `frontend/src/app/pages/RegisterPage.tsx`. Both
files carry a `// see also` comment pointing at the other.

**Why duplicate:** Rule of three. Two implementations are easier to keep
correct than one premature abstraction whose seams may not match the
third use case.

**Trigger for extraction:** The third place that needs this sequence
(e.g. a hypothetical "join an existing org via link" flow, or a
multi-tenant invitation variant) is the cue to pull a shared
`useAccountSetup({ mode })` hook into `frontend/src/features/auth/`.
Until then, two copies are fine.

---

## INS-031 — User-isolation audit: recurring patterns and the rules they break (2026-04-28)

**Context:** A full multi-user data-isolation audit was run on
2026-04-28 (branch `claude/audit-user-data-separation-SES1j`,
merges `5a9f7cb` and `a386ae5`). It surfaced 8 findings across the
chat, memory, bookmark, knowledge, embedding, and ws layers — two
critical, three high, three medium. The architecture held: WebSocket
scoping, BYOK credential handling, and the LLM connection resolver
were already correct. What broke was always the same handful of
shapes — and they're worth naming so future code review catches
them without a second audit.

**The five recurring shapes:**

1. **"Body field naming a foreign entity, used without ownership
   verification."** The single most exploitable finding (C1) was
   `PUT /sessions/{id}/knowledge` accepting `library_ids` from the
   request body and writing them to the session unchecked — a user
   could attach a victim's knowledge library and have its documents
   injected into their own LLM context. **Rule:** any list of IDs
   that names another user-owned entity must be verified through
   the owning module's public API before persistence. The new
   `verify_libraries_owned()` in `backend/modules/knowledge/__init__.py`
   is the canonical example.

2. **"_id-only operation after upstream ownership check."** Several
   repository methods (chat `update_session_*`, memory
   `auto_commit_old_entries`'s second `find`, artefact `get_by_id`)
   keyed only on `_id` because the caller had already verified
   ownership. This is brittle: any future refactor that bypasses
   the upstream check silently creates an IDOR primitive. **Rule:**
   the lowest-level mutation/fetch should always carry `user_id`,
   even when today's callers happen to be safe. Defense-in-depth
   isn't paranoia, it's surviving the next refactor.

3. **"Cascade operation forgets owner scope."** Bookmark
   `delete_by_message` / `delete_by_session` (H1) filtered only on
   the cascade key. UUIDs are unique in practice, so the bug was
   latent — but unique-by-construction is an invariant, not an
   enforced constraint. **Rule:** cascade primitives accept and
   filter on `user_id` as a required parameter. System-maintenance
   callers (cleanup loops) get the user_id from the triggering
   entity — see how chat `delete_stale_empty_sessions` /
   `hard_delete_expired_sessions` were changed to return
   `(session_id, user_id)` tuples.

4. **"Event payload trusts reference_id alone."** Embedding events
   (H2) carried only `reference_id`; the consumer in knowledge
   looked up `knowledge_documents` by `_id` without any owner check.
   Today only the knowledge module publishes these events, but that's
   an implicit invariant the event contract didn't express. **Rule:**
   when an event crosses module boundaries, `user_id` is a
   first-class field on the event. Make it `str | None = None` for
   the deploy window (so in-flight events don't fail validation),
   then tighten in a follow-up release once the legacy events have
   drained from Redis Streams (24h TTL).

5. **"Latent bug hides under an early-return."** PTI invalidation
   (M1) had `payload.get("document_id")` always returning `None`
   because `KnowledgeDocumentUpdatedEvent` nests the document under
   `payload["document"]`. The handler silently returned early on
   every event — effectively dead code. Audit-by-reading-code missed
   it; only tracing the event flow caught it. **Rule:** when an
   event handler has an early-return on a missing field, sanity-check
   the field name against the event's actual `model_dump()` shape.
   A unit test that publishes a real event and asserts the handler
   reached its main path would have flagged this on day one.

**Structural patterns the audit confirmed are correct:**

- The LLM module's generic resolver dependency
  (`resolve_connection_for_user` in `backend/modules/llm/_resolver.py`)
  enforces `(connection_id, user_id)` ownership before any adapter
  sub-router runs. Every LLM-connection endpoint inherits the check
  via FastAPI `Depends`. This pattern should be the model for any
  future "user-owned resource with a sub-router" feature.
- WebSocket `scope` is metadata for persistence, not a subscribe
  primitive. The frontend cannot opt into another user's scope;
  delivery is decided server-side via `target_user_ids` and
  role-based fan-out, and stream replay re-checks targets at
  delivery time. Don't change this.
- Vector-search filter fields (`user_id`, `library_id`) are declared
  in the Atlas index AND used as `$vectorSearch` pre-filters. Without
  the index declaration the filter is silently ignored or post-applied,
  which leaks. Any new vector field used for filtering must be added
  to the index in the same change.

**The one finding deferred:** `/api/metrics` is unauthenticated (H3).
Not a user-to-user leak — it exposes Prometheus internals (queue
depth, cache stats, system load). Risk depends entirely on the
deployment topology: behind a reverse proxy that filters
`/api/metrics`, near zero; directly on the public internet,
medium recon risk. The fix is a Prometheus-auth concept (bearer
token, mTLS, or network-policy-only access) which the project
hasn't decided on yet. Revisit when the deployment story for
metrics scraping is settled.

**Admin-event scoping (BD-031, now resolved as INS-031.M3):**
sensitive admin actions (USER_UPDATED, USER_DEACTIVATED,
USER_PASSWORD_RESET, USER_DELETED, INVITATION_CREATED) now go to
`master_admin` only. USER_CREATED and INVITATION_USED stay broadcast
to all admins as low-sensitivity coordination signals. If a future
delegated-admin model needs real-time updates for non-master admins,
adopt the audit-pattern fanout (master_admin + acting admin) — the
precedent is `_fan_out_audit` in `backend/ws/event_bus.py:362`.
This requires adding `actor_id` to the affected event schemas.

**When to re-audit:** before alpha-to-beta transitions, when a new
module exposes user-owned resources via cross-module APIs, or when
a refactor touches event-bus fanout / repository methods that
currently carry `user_id`. The 8-finding pattern catalogue above is
the checklist.

## INS-032 — OpenRouter prompt caching is per-provider, not uniform (2026-04-28)

**Context:** OpenRouter routes to 50+ upstream providers, each with a
different caching story:

- **OpenAI / Gemini / DeepSeek models** — automatic prefix caching
  above ~1024 tokens. No marker needed, transparent savings. (List
  grows empirically; validated via the OpenRouter dashboard.)
- **Anthropic models** — require explicit
  `cache_control: {type: "ephemeral"}` markers on individual
  message-content blocks (typically system prompt and long tool
  definitions). Without markers, every turn pays full token price.
- **Others (Llama, Mistral on OR, etc.)** — usually no caching.

**Phase-1 decision:** Pass-through with no `cache_control` markers.
OpenAI / Gemini / DeepSeek auto-caching covers the bulk of realistic
Chatsune traffic out of the box; Anthropic models run uncached.

**What testers must know:** users who route mostly to Claude through
OpenRouter will see no cache savings until we ship marker support.
Iterate on real usage data before optimising.

**Why not implement markers now:** `cache_control` belongs at the
content-block level inside chat messages, not on the message itself.
Adding it would require either an OR-specific message translator
(more code, more divergence from Mistral / xAI / nano-gpt) or a
parameter on the shared `CompletionMessage` model that every other
adapter would ignore. Neither is justified before we have usage data.

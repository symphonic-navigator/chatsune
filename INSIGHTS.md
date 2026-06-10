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

**Update 2026-05-08:** This Phase-1 decision is reversed for
Anthropic models behind both OR and nano-gpt. Beta testers explicitly
asked for cache savings on Claude; the routers became the canonical
Claude path (BYOK + anonymisation). Per-persona TTL toggle
(`Off / 5m / 1h`), strategy-lib in
`backend/modules/llm/_adapters/_anthropic_cache.py`, three-marker
layout (system 1h + block 1h every 8 messages + rolling tail at
chosen TTL). Other adapters and non-Anthropic routes stay
pass-through. Spec:
`devdocs/specs/2026-05-08-claude-router-cache-breakpoints-design.md`.

## INS-033 — Background completions: stream-end events must reach non-active sessions (2026-05-07)

**Context:** With background completions, an inference for session A
keeps running after the user navigates to session B. The backend
publishes `CHAT_STREAM_ENDED` for A when it finishes. The frontend
must clear A's slot in `chatStore.streamsBySession` so the sidebar
pulse-dot disappears and the slot is in a clean state for the user's
next visit.

**The trap:** `useChatStream` is a per-active-session hook. There is
only one instance at a time, bound to the currently-mounted ChatView's
session id. The natural reflex is to gate every event handler on
`if (event.session_id !== hookSessionId) return` — and that is exactly
what the hook did before this feature.

With background completions, that gate is wrong for slot-bookkeeping
events. The Group for session A has been cancelled with reason
`'teardown'` (UI unmounted), so its `chatStoreSink.onStreamEnd` will
not run either. If `useChatStream` also drops the event, nothing on
the frontend ever clears A's slot. The dot stays on forever.

**The split:** events fall into two categories.

- *Slot-bookkeeping*: `CHAT_STREAM_ENDED`, `CHAT_STREAM_ERROR`. These
  must mutate the slot identified by the **event's** session id, not
  the hook's. `chatStore.finishStreaming` already has the
  `isActive = sessionId === activeSessionId` branch that prevents
  background-session messages from polluting the visible transcript;
  the slot itself is cleared unconditionally by `clearStream`.
- *Active-session UI side effects*: scroll, focus, toast banners,
  `activeTagBuffer` flush, the active Group's `onStreamEnd` hand-off.
  These stay gated on the hook's session id — raising a banner about
  a chat the user is not viewing would be confusing.

`CHAT_STREAM_ERROR` does not carry `session_id` in its DTO. The hook
resolves the slot by scanning `streamsBySession` for the matching
`correlationId` instead. A small price for not changing the event
shape.

**ChatView reconciliation as a safety net:** the `getSession.then`
path in ChatView checks `session.state === 'idle'` and clears any
stale `isStreaming: true` slot it finds. This covers the rare case
where an END event arrived before the frontend was alive (login,
hard reload before catchup completes), where the in-band hook fix
cannot help.

**Generalisable rule:** when a feature lets state survive across
component lifetimes (background completions, long-running jobs,
deferred ops), audit every per-component event handler for gates
that drop events meant for the orphaned state. The gate is usually
correct for UI side effects and wrong for state mutations.

---

## INS-034 — LLM reasoning/tools capabilities: orthogonal axes, not one bool (2026-05-09)

**Context:** Until this point `ModelMetaDto` carried a single
`supports_reasoning: bool` and `CompletionRequest` carried matching
`reasoning_enabled: bool` / `supports_reasoning: bool`. That collapsed
several independent dimensions into one bit, with three painful
consequences in the field:

1. The cockpit could not tell the user what was actually possible —
   a model with effort buckets, a model with a boolean toggle, and a
   model that always reasons all looked identical.
2. The "tools XOR reasoning" mutex case was invisible. Some models
   silently degrade or fail when both are sent in one request
   (DeepSeek R1 raw, QwQ, Magistral in some configurations).
3. Effort (low/medium/high, plus GPT-5's `minimal`) was not modelled
   at all.

**Decision:** Replace the bool with three orthogonal capability axes
on `ModelMetaDto`, plus an optional effort spec:

```python
class ReasoningCapability(BaseModel):
    kind: Literal["no_reasoning", "optional", "always_on"]
    effort: ReasoningEffortSpec | None = None  # buckets + default
    default_on: bool = True

class ToolCapability(BaseModel):
    supported: bool
    exclusive_with_reasoning: bool = False  # the XOR axis
```

Plus a new `first_class_support: bool` flag, true only when the model
has been curated end-to-end (YAML override or adapter-internal claim).
The user sees a ★ badge in the model browser; a filter hides
best-effort rows.

**Why not a discriminated union:** an earlier draft modelled this as
a `ReasoningCapability` sum-type (`AlwaysOn | EffortBuckets |
TokenBudget | ...`). It crammed effort into the type system and made
common queries — "does this model support reasoning at all?" — read
through a discriminator. Splitting `kind` and `effort` into two
orthogonal fields kept the type lean and let the cockpit's render
logic stay flat (one switch per axis, not nested).

**Capability resolution hierarchy** (in
`backend/modules/llm/_capabilities.py::resolve_capabilities`):

1. **YAML override** — `backend/modules/llm/data/model_capabilities.yaml`,
   keyed on `(adapter_type, model_id pattern)` with `fnmatch` semantics.
   Sets `first_class_support=True`.
2. **Adapter heuristic** — each adapter implements an optional
   `capability_hint(model_id) -> CapabilityHint | None`. OpenRouter
   inspects `top_provider.supported_parameters`, Novita reads
   `features`, nano-gpt consults `_pair_map.py`. Heuristic guidance,
   `first_class_support=False`.
3. **Universal fallback** — `kind="optional", effort=None,
   tools.supported=true, tools.exclusive_with_reasoning=false`. Mirrors
   pre-existing behaviour for unknown models.

**Why YAML over inline adapter code:** adapter-internal heuristics
were already there and stayed there as fallback. The YAML overlays a
hand-curated truth on top, separate from adapter implementation
detail. A new model gets first-class status by adding a YAML row
(reviewable, no code change). A new adapter quirk gets handled where
it belongs (in the adapter).

**Why `(adapter, model_id)`, not `model_id` alone:** the same logical
model can have different capabilities depending on which upstream
serves it. Grok 4.3 via the xAI direct adapter exposes a simulated
reasoning toggle (slug-pair table maps `mode=on/off` to a slug swap).
Grok 4.3 via OpenRouter has no equivalent mechanism on the router
side, so the capability is honestly `always_on`. The cockpit must
reflect this — same model name, different controls.

**Translation layer per adapter — "always explicit":** when the
model is `optional`, the adapter sends an explicit value for both
`mode=on` and `mode=off`, regardless of whether the provider's
default would have produced the same outcome. This prevents drift
when providers change defaults silently. `mode=off` for OpenRouter /
Novita / nano-gpt-flag-mode is `reasoning: {enabled: false}`, never
`reasoning: {exclude: true}` — `exclude` only hides thinking from the
stream while the model continues to think (cost + latency unchanged).
Per spec §2 we do not use `exclude` to fake an off-state; the user
deserves the truth.

**Cockpit UX rule:** never hide a button. `no_reasoning`,
`always_on`, and `tools.supported=false` all render as
disabled-with-tooltip. Effort-capable models open a pop-out that
includes "Off" as a first-class choice — so the visual state of the
button (white = off, accent = on) is the same regardless of whether
the model is boolean-toggle or effort-graded. Mental model:
*the way you get there changes, the visual result is constant.*

**Self-healing model-switch:** a session's effective model can change
when the user edits the persona's `model_unique_id`. Rather than
hooking every model-change endpoint, the orchestrator does a lazy
remap on every inference: parse the stored `extras`, run
`remap_extras_for_capability(extras, current.reasoning,
current.tools)`, and only persist + broadcast if the result differs.
Equality short-circuit means the common (already-consistent) case
costs one pure-function call and zero DB writes.

**The "tools win on conflict" rule:** when remap produces a state
that violates the new model's mutex (tools=on AND reasoning=on on a
mutex model), tools win. Web search is too useful to silently lose;
losing reasoning is more recoverable from the user's perspective.

**Out of this iteration (deferred to follow-up specs):** the xAI and
Mistral adapters got conservative-default treatment only — they emit
the new `ModelMetaDto` shape with `first_class_support=false` so the
system works uniformly, but their premium per-model handling will be
its own spec each. xAI converges on roughly one model post-cleanup;
Mistral on 2–3, since Magistral and Mistral Medium 3.5 absorbed
most of the family.

**Spec:** `devdocs/specs/2026-05-09-llm-reasoning-tools-capabilities-design.md`
**Plan:** `devdocs/plans/2026-05-09-llm-reasoning-tools-capabilities.md`

---

## INS-035 — Router ``effort`` for Anthropic models is a percentage, not a budget (2026-05-09)

**Symptom:** Beta tester set Claude Sonnet 4.6 reasoning effort to ``low``
expecting a short reasoning trace; got pages and pages of thinking
content. The selector wasn't broken — the wire payload carried
``reasoning: {effort: "low"}`` correctly, the router accepted it, and
the model still produced ~12k thinking tokens.

**Root cause:** OpenRouter's universal ``reasoning`` object documents
``effort`` as a vendor-agnostic shorthand. For OpenAI o-series it
passes through directly to the upstream's ``reasoning_effort``
parameter. **For Anthropic models it gets translated to
``thinking.budget_tokens`` as a percentage of the response
``max_tokens``**, which defaults to the model's full output budget
(~64k for Sonnet 4.x). The mapping (per OR docs at the time of this
commit) is approximately:

- ``effort=low``     ≈ 20% of max_tokens → ~12k thinking tokens
- ``effort=medium``  ≈ 50% of max_tokens → ~32k thinking tokens
- ``effort=high``    ≈ 80% of max_tokens → ~50k thinking tokens

So even ``low`` allows a deeply meandering trace. The user's mental
model ("low = a few hundred tokens of quick reasoning") doesn't match
the wire reality.

Anthropic now has a native ``output_config.effort`` field on the
direct Messages API (claude.com/docs/en/build-with-claude/effort) that
*does* behave like an explicit budget. As of this commit, OpenRouter's
translator hasn't been updated to use it — the percentage-of-max_tokens
mapping is still in effect. nano-gpt mirrors OpenRouter's universal
reasoning object and inherits the same behaviour.

**Fix:** for Anthropic models routed via OpenRouter or nano-gpt, send
explicit ``reasoning: {max_tokens: <budget>}`` instead of
``reasoning: {effort: <bucket>}``. The router accepts ``max_tokens``
as a precise override and forwards it to Anthropic's
``thinking.budget_tokens``. Per spec §6.4 starting values:

- low     → 2048 tokens
- medium  → 8192 tokens
- high    → 16384 tokens
- minimal → 1024 tokens (for symmetry with GPT-5; Anthropic doesn't
  expose a ``minimal`` bucket, so this only fires if the user picks
  it from a model that does)

Other vendors (OpenAI, DeepSeek, etc.) keep the effort string — they
handle it correctly. The discrimination is via the existing
``is_anthropic_model(request.model)`` helper from
``backend/modules/llm/_adapters/_anthropic_cache.py``. The budget
table lives in both ``_openrouter_http.py`` and ``_nano_gpt_http.py``
as ``_ANTHROPIC_REASONING_BUDGET`` — keep them in sync when calibrating.

**When this stops mattering:** when we ship a native Anthropic
adapter (separate future spec per design §9), it can use
``output_config.effort`` directly and the model can decide what
``low`` means in budget terms — likely tighter and smarter than our
hand-picked numbers. Until then, the explicit-max_tokens shim is the
predictable user experience.

**Generalisable rule:** when a router/proxy advertises a "vendor-
agnostic" parameter, verify what it actually sends downstream for
each upstream you care about. Identical names don't mean identical
semantics — the percentage-vs-tokens trap repeats across the
ecosystem (rate limits, max-output, temperature scales, etc.).

---

## INS-036 — OpenRouter silently drops reasoning.max_tokens when cache_control is present (2026-05-09)

**Symptom:** Beta tester set Claude Sonnet 4.6 to ``low`` effort
expecting a 128-token reasoning budget. The wire payload was correct
(``reasoning: {max_tokens: 128}`` confirmed via LLM_TRACE log).
Anthropic still produced 1500+ reasoning tokens. Out-of-band curl
test against the same model with the same payload but **no
``cache_control`` markers** honoured the budget verbatim
(~100 reasoning tokens). The only difference between live and
isolated tests was the cache markers attached to the system message.

**Reproduction (curl, 2026-05-09):**
```jsonc
// Body A — cache_control + reasoning.max_tokens=128
// Result: 15945 reasoning tokens, completion hit max
{
  "model": "anthropic/claude-sonnet-4.6",
  "messages": [
    {"role": "system",
     "content": [{"type":"text","text":"...",
                  "cache_control":{"type":"ephemeral","ttl":"1h"}}]},
    {"role": "user", "content": "<long puzzle>"}
  ],
  "reasoning": {"max_tokens": 128}
}

// Body B — same prompt, NO cache_control
// Result: ~100 reasoning tokens, budget honoured
```

**Hypothesis:** OpenRouter's translator inspects the body for
Anthropic-specific markup (``cache_control`` is the giveaway) and
switches to a "pass through to Anthropic native" code path. On that
path the ``reasoning`` object isn't translated to
``thinking.budget_tokens`` — it's silently dropped. Anthropic then
runs at its default thinking budget, which for Sonnet 4.x is
effectively unbounded relative to a 128-token request.

**Fix:** when the user has dialled in a specific reasoning effort
bucket (``extras.reasoning_effort`` set, ``reasoning_mode == "on"``,
Anthropic model), strip ``cache_control`` from the outgoing payload.
The user implicitly chose "I care about how long Claude thinks" over
"I want cache savings on this turn". Cache markers stay on for every
other case (no effort dialled, or effort dialled but reasoning off).
Both router adapters (openrouter and nano-gpt) carry the same
workaround. Tests cover all three branches: suppressed-when-effort,
kept-when-no-effort, kept-when-reasoning-off.

**When this stops mattering:** when a native Anthropic adapter
ships, both ``thinking.budget_tokens`` and ``cache_control`` go
direct to Anthropic and the trade-off disappears. Until then, the
router is the bottleneck.

**OR-side bug-report TODO:** worth filing with OpenRouter — the
percentage-vs-budget translation (INS-035) is a defensible design
choice; silently dropping a documented field when another field is
present is not. Reproduction body above is self-contained.

**Generalisable rule:** when two seemingly-orthogonal parameters
collide on the wire, write a curl reproduction with each one
isolated. The "everything looks right in the trace" case is exactly
where two fields are interacting upstream in a way you can't see
without bisecting them.

---

## INS-037 — Reasoning effort dropped for Anthropic-via-router; cache wins (2026-05-09)

**Decision:** For Claude models routed through OpenRouter or nano-gpt,
``ChatSessionExtras.reasoning_effort`` is **ignored**. The wire body
carries only ``reasoning: {enabled: true|false}`` — no ``effort`` field,
no ``max_tokens`` field. Sonnet's adaptive default-effort decides
reasoning depth on its own. The capability YAML for these models
omits the ``effort:`` block entirely, so the cockpit's ThinkingButton
falls back to a simple on/off toggle (no pop-out).

**Context:** INS-035 found that OR's universal ``effort`` shorthand
becomes a percentage of response max_tokens for Anthropic, making
``low`` yield ~12k thinking tokens. INS-036 found that switching to
``reasoning.max_tokens`` works in isolation but is silently dropped
when ``cache_control`` markers are present in the same body. We
spent a session bisecting workarounds (suppress cache_control when
effort is set, calibrate budgets, swap field shapes) before stepping
back to weigh the trade-off.

**The trade-off:**
- Cache_control on long Anthropic conversations is **massive** value:
  a 4000-token system prompt cached at 5m TTL on a 10-turn session
  saves ~36000 prompt-tokens × 90% discount = effectively the system
  prompt cost on 9 of 10 turns. For Chatsune's persona-driven sessions
  (long instruction prompts, multi-turn dialogue) this dominates.
- Effort control is **nice to have** but rarely used: Claude's
  internal adaptive reasoning already scales depth with problem
  difficulty. Power-users who want manual tuning are an edge case.
- Routers don't let us have both. We pick cache.

**What stays first-class:** Claude Sonnet 4.6 + Opus 4.7 via
OpenRouter and nano-gpt remain ★ first-class in the model browser.
The "first-class" badge means "we have curated this end-to-end" —
the curation now reads "we deliberately disabled effort for these
models in favour of cache survival, and that is documented behaviour".
Other vendors (OpenAI o-series, DeepSeek V4) keep their effort
buckets — the bug is Anthropic-via-router specific.

**What this looks like in the code:**
- ``model_capabilities.yaml``: Claude entries omit ``effort:``.
- ``_openrouter_http.py`` / ``_nano_gpt_http.py``: when building
  the reasoning object, ``if not is_anthropic_model(...)``
  guards the ``effort`` field. Anthropic on → ``{enabled: true}``,
  off → ``{enabled: false}``.
- No more ``_ANTHROPIC_REASONING_BUDGET`` table, no more
  ``user_chose_explicit_effort`` cache_control suppression.
  The previous workarounds (commits before this one) are reverted.

**When this stops mattering:** when a native Anthropic adapter
ships (deferred per design §9), it can use ``thinking.budget_tokens``
and ``cache_control`` together because both go direct to Anthropic
without router translation. We expect to expose effort buckets there
at the same time. The "Provider Integration Policy" Anthropic is
working towards may also resolve this on the OR side without code
change on our end — worth re-checking the OR-Anthropic wire format
periodically.

**Generalisable rule:** when a workaround stack grows past two layers
for the same root cause (here: bucket calibration → field-shape swap
→ cache_control suppression), step back and ask whether the feature is
worth keeping in this routing path at all. Sometimes the cleanest fix
is to remove the parameter from the user-visible surface.

---

## INS-038 — `thinking_chars=0` is ambiguous; reasoning_tokens is the truth signal (2026-05-09)

**Symptom:** Beta tester ran a logic-puzzle prompt against
``openai/gpt-5.5`` via OpenRouter with ``reasoning: {effort: "high",
enabled: true}``. The ``inference.stream.end`` log line showed
``thinking_chars=0`` and the chat UI had no thinking pill. The natural
read — "reasoning didn't run" — was wrong. Reasoning had run; it was
just invisible.

**Root cause — provider policy, not a Chatsune bug:** OpenAI's
reasoning family (o-series, GPT-5, GPT-5.5) does **not** return raw
reasoning content over the API by design. What you get is a token
count under ``usage.completion_tokens_details.reasoning_tokens`` and
optionally an encrypted/redacted block for multi-turn consistency,
never the prose. OpenRouter passes this through faithfully — the
``reasoning`` field in delta chunks stays empty for OpenAI upstreams,
so our stream parser (which reads both ``delta.reasoning_content`` and
``delta.reasoning``) accumulates zero characters and reports
``thinking_chars=0``. Compare with Anthropic, DeepSeek, xAI, Mistral
Magistral — those stream the prose and we see chars > 0.

So ``thinking_chars`` collapses two distinct states into the same
number:

1. *Reasoning is genuinely off* (no_reasoning model, or optional model
   with toggle off, or always_on model that produced no thinking
   tokens this turn).
2. *Reasoning ran, the provider refused to ship the prose.*

For OpenAI models, state 2 is the steady state. For Claude / DeepSeek
/ Grok, state 2 essentially never happens — chars > 0 reliably tracks
"reasoning ran".

**Fix — observability, not behaviour:** plumb the
``reasoning_tokens`` count through ``StreamDone`` and emit it
alongside ``thinking_chars`` in the stream-end log. The log line is
now ``... content_chars=N thinking_chars=N reasoning_tokens=N|n/a``,
where ``n/a`` means the upstream did not report the field at all
(distinct from ``0``, which means "reported and zero").

Wired in five OpenAI-compat adapters: ``_openrouter_http.py``,
``_nano_gpt_http.py``, ``_novita_http.py``, ``_xai_http.py``,
``_mistral_http.py``. Ollama and the community stub were skipped —
neither has reasoning_tokens semantics.

**Diagnostic rule:** when a beta report says "reasoning isn't working
for model X", the correctness check is now:

| ``thinking_chars`` | ``reasoning_tokens`` | Conclusion |
|---|---|---|
| > 0 | > 0 | Reasoning ran, prose visible. Working as expected. |
| 0 | > 0 | Reasoning ran, prose hidden by provider policy. Expected for OpenAI; unexpected for Claude/DeepSeek/Grok (then look at the stream parser). |
| > 0 | 0 / n/a | Provider streams thinking tokens but doesn't account them. Possible for Ollama / community adapters; investigate billing path. |
| 0 | 0 | Reasoning genuinely did not run. Verify the wire payload (LLM_TRACE) and the model's capability shape. |
| 0 | n/a | Non-reasoning model or older response shape; expected. |

Do **not** equate ``thinking_chars=0`` with "reasoning is off" without
checking the right-hand column.

**Why not also surface this in events to the frontend:** out of scope
for this iteration. The cockpit already shows reasoning state via the
toggle button (per INS-034); the frontend doesn't currently need to
distinguish "ran but hidden" from "didn't run" because the user
chose the toggle. If a future feature wants to show "thinking happened
silently for N tokens" as a UI affordance (cost transparency, trust
calibration), the data is now in ``StreamDone.reasoning_tokens`` and
the chat persistence path can pick it up without further adapter
changes.

**Generalisable rule:** when an observability metric appears to
collapse two states into one, check whether the underlying API
exposes a second metric that disambiguates. Char-count and
token-count are not interchangeable observability axes —
char-count tracks *what reached the user*, token-count tracks
*what the provider charged for*. For reasoning, those diverge by
design. Log both.

---

## INS-039 — Recommended context window: deferred until ≥3 providers stagger pricing (2026-05-09)

**Observation:** Some upstream providers price the same model in
*tiers* based on used context window — most concretely, xAI doubles
the per-token rate above 200K. Naively letting a chat run up to the
model's hard ``context_window`` ceiling can therefore double the bill
silently, and on at least one provider (Grok) also degrades response
quality in the upper context range.

**Proposed shape (for later pickup):**

- Add ``recommended_context_window: int | None = None`` to
  ``ModelMetaDto`` (parallel to the existing capability fields).
- Resolution rule: use the explicit value when set; otherwise fall
  back to ``min(262144, context_window)``. The 262K floor is our own
  defence against pathological context blow-ups, independent of
  pricing.
- UI: the persona's context-window slider would default to this
  recommended value. Pulling it past the recommendation crosses a
  red threshold and shows a textual warning ("above this, this
  provider charges more / quality may drop").
- Drivers (per the planned driver layer) set the field for each
  ``(model, router)`` pair where the upstream's pricing or behaviour
  is known to staircase.
- Compatible with the upcoming compact-and-continue feature: a hard
  recommendation lets compact-and-continue trigger predictably at a
  defensible threshold, instead of right at the model ceiling.

**Why deferred (Pareto check):** the only state-confirmed instance
today is xAI. DeepSeek V4 has no staircase pricing across any
observed router; Anthropic / OpenAI / Mistral / Ollama-Cloud
pricing-tier behaviour at long context wasn't checked yet. Building
a full slider-with-warning UI for a feature that benefits one
provider would be wish-driven generalisation. The capability field
is cheap and worth landing eventually; the UI is only worth it once
3+ providers exhibit the pattern.

**Before picking this up:** survey the major providers/routers we
support for context-tiered pricing or known quality degradation at
long context. If ≥3 confirmed, build the full UI. If still ≤2, ship
the field with hardcoded values for the affected models and skip
the slider warning.

**Generalisable rule:** when "we should add a feature for X" is
backed by one observation, write the design down (so it isn't lost),
ship the cheap part (here: the data field), and gate the expensive
part (here: the UI) on a state threshold (here: third confirmed
provider). Don't generalise UI ahead of state.

---

## INS-040 — Driver Layer for premium models with router-specific quirks (2026-05-10)

**Observation:** Premium LLMs (the ones our users actually use day to
day) behave significantly differently across the routers that expose
them. The DeepSeek V4 wire-shape research
([devdocs/research/deepseek-v4-wire-shapes.md](devdocs/research/deepseek-v4-wire-shapes.md))
showed five orthogonal divergences for the same model on the same
day:

1. **CoT stream key differs across all four routers**:
   `delta.reasoning` (OR), `delta.reasoning` (nano-gpt `:thinking`),
   `delta.reasoning_content` (Novita), `message.thinking` (Ollama
   Cloud, NDJSON not SSE).
2. **Reasoning gating is router-specific**: OR uses
   `reasoning.enabled`; nano-gpt uses **separate slugs** (`:thinking`
   suffix); Novita silently ignores `reasoning.enabled` and requires
   top-level `thinking.type`; Ollama uses `think: true|"max"`.
3. **Effort vocabularies don't agree**: OR's `xhigh` ≡ nano-gpt's
   `max` ≡ Ollama's `think="max"` ≡ DeepSeek-native max. Novita's
   `max` ≡ Novita's `high` (silently — it does not pass through to
   DeepSeek's native max mode; prompt_tokens stays at 19 with no
   system-prompt injection).
4. **Silent failure modes**: Novita silently degrades unknown
   `effort` values to ~"low" with HTTP 200 (no validation error);
   nano-gpt has no `usage` block at all on stream completion and
   bundles reasoning into a single `outputTokens`.
5. **Metadata visibility varies**: nano-gpt's `/v1/models` is sparse
   by default; `?detailed=true` is required to surface
   `context_length` (e.g. TEE variant 800k) and `capabilities`.

A purely declarative table (`model_capabilities.yaml`) cannot encode
behaviour, only shape. None of the above five are shape; all are
behaviour.

**Decision:** Introduce a **Driver Layer** at
`backend/modules/llm/_drivers/`, one driver package per *model
family* (not per model id), coexisting with the existing
`model_capabilities.yaml`. Drivers handle premium models with
router-specific quirks; yaml handles the long tail of well-behaved
generic OpenAI-compat models. Spec:
[devdocs/specs/driver-layer.md](devdocs/specs/driver-layer.md). First
concrete driver: `DeepSeekV4Driver` (covers V4 Pro and V4 Flash
across OpenRouter, nano-gpt, Novita, and Ollama Cloud).

Key design points:

- **Two-level dispatch.** `match_driver(slug)` uses fnmatch on the
  slug basename (`slug.rsplit("/", 1)[-1]`). Inside the matched
  driver, `(adapter_type, slug-suffix)` resolves to a Builder +
  Parser via a default-with-overrides registry. Multiple PATTERNS
  per driver are supported so naming-convention drift across routers
  doesn't multiply driver classes.
- **Per-driver user-facing effort scale**, not a global one. The
  scale comes from the model author's docs, not from the router with
  the most permissive vocabulary. DeepSeek V4 exposes `[high, max]`
  per
  [DeepSeek's thinking-mode docs](https://api-docs.deepseek.com/guides/thinking_mode)
  ("low and medium are mapped to high"). OR's
  `minimal`/`low`/`medium` and Novita's silent-low are **not**
  exposed because their behaviour is not specified by DeepSeek and
  varies router-to-router.
- **Capability-spec merging.** Driver fields explicit > provider
  metadata > defaults. Driver leaves `context_length`, `pricing`,
  `max_output_tokens` as `None` so provider metadata fills them in
  — per-slug variants like nano-gpt TEE (800k context) work without
  the driver knowing about them.
- **Force-default-routing toggle** per per-model-config — escape
  hatch when a driver misbehaves. UI surfaces it with a warning
  ("you will lose advanced capabilities for this model"). Default
  off for first-class models.
- **Validation at the boundary.** Invalid effort buckets for a given
  `(adapter, slug)` raise at request-build time. No silent
  degradation. Novita `max` is rejected client-side because Novita
  silently caps it — refusing is closer to the truth than degrading
  without telling the user.

**Why coexist with yaml instead of replacing it:** yaml works well
for the long tail. Claude 4.5/4.6/4.7 and GPT-5 are already in
production via yaml entries and are battle-tested. Forcing every
model through a driver would multiply boilerplate ~5x for zero
behaviour gain on well-behaved models. The cost of "two paths to
learn" is real but small; the cost of "every new yaml entry must
become a driver" would have killed adoption. Migration in either
direction stays optional and reactive.

**Generalisable rules:**

1. **Realism toward upstream**: when a vendor's behaviour diverges
   from its docs, the code must embody what they actually do, not
   what they claim. The driver is the artefact that captures the
   divergence; the spec keeps it auditable.
2. **Model-author docs trump router extensions**: when deciding what
   user-facing options to expose for a model, default to the
   vocabulary the model's author defines. Routers that extend the
   vocabulary (intentionally or by silent permissiveness) are not
   authoritative for what the model actually supports.
3. **Boundary-validate against silent degradation**: prefer a clean
   client-side rejection over a server-side silent downgrade. Silent
   downgrades are the exact failure mode that makes user complaints
   useless ("I sent max but it was lazy"); rejections produce
   actionable errors.

## INS-041 — OR's `xhigh` halves DSv4 Flash reasoning instead of expanding it (2026-05-10)

OpenRouter's `reasoning.effort: "xhigh"` for `deepseek/deepseek-v4-flash`
returns roughly **half** the reasoning tokens of `effort: "high"` on the
same prompt (probed 2026-05-10: 2300 vs 4039 reasoning_tokens, ratio
0.57). OR rejects `effort: "max"` directly (HTTP 400 — accepted set is
`{none, minimal, low, medium, high, xhigh}`), so `xhigh` is the only
mapping path for the user-bucket "max"; we cannot work around it by
sending a different value.

The same model on the same prompt via Ollama Cloud with `think: "max"`
returns **4×** the reasoning of `think: true` (9880 vs 3513 eval tokens)
and triggers a server-side system-prompt injection (prompt_eval jumps
from 62 to 141), so the upstream "max" mode itself works — the bug is
in OR's `xhigh → DeepSeek-Flash` translation.

DSv4 Pro on OR is unaffected: `xhigh` produces measurably more reasoning
than `high` as expected.

**Action:** For (`openrouter_http`, `*flash*`) we expose only
`effort.buckets = ["high"]`. The OR-Pro and Ollama-Cloud paths keep
`["high", "max"]`. A defensive silent-downgrade in the OR builder
catches stale stored settings still carrying `"max"`. Re-probe quarterly
via `backend/llm_harness/probes/dsv4_flash_or_drift.py`.

When the OR-side fix lands (verdict flips to FIXED), drop the override
in `_capability.py` and `_builders.py` and remove
`_is_or_flash_quirk_applicable` from `_quirks.py`.

## INS-042 — Novita's permissive effort vocabulary + cache visibility (2026-05-10)

**Permissive effort.** Novita accepts any string for `reasoning.effort`
without 400-rejection (probed: `"high"`, `"max"`, `"xhigh"`,
`"invalid_xyz"` all returned 200). Unknown values silent-degrade to a
default low setting — `"invalid_xyz"` produced reasoning_tokens=1403 vs
`"high"`'s 2250 on the same prompt. This is the failure mode INS-040
generalisable rule 3 warns about ("boundary-validate against silent
degradation"): the DSv4 Novita builder rejects any effort outside
`{high, max}` so a typo or a stale stored value surfaces as a loud
ValueError instead of a quiet quality drop.

**Wire-shape parity with OR.** Tool-call streaming is OpenAI-fragmented
and indexed; the `ToolCallAccumulator` shared with the OR parser handles
both providers without duplication. The only diff vs OR is the CoT key:
Novita uses `delta.reasoning_content` (DeepSeek-native), OR uses
`delta.reasoning`. Both DSv4 Pro and Flash work on Novita with both
buckets — no Flash-quirk like INS-041 here.

**Free win: cache visibility.** Novita streams
`prompt_tokens_details.cached_tokens` in the terminal usage block on
DSv4 (probed: 128 cached tokens on a tool-call request). OR shows the
same field; nano-gpt does not (per existing memory). When QA-ing
cache-related features for DSv4, Novita is a viable alternative to OR.

## INS-043 — Driver layer capability-only mode (nano-gpt + DSv4)

**Date:** 2026-05-10

**Context:** When integrating DeepSeek V4 across four routers (OR, Ollama
Cloud, Novita, nano-gpt) we found nano-gpt's existing adapter already
covers DSv4 wire-shape needs adequately:

- Slug-pair switching for thinking on/off (`:thinking` suffix) is
  encoded directly in the URL slug — nano-gpt's
  `_nano_gpt_http.py:402-424` handles this without driver help.
- Reasoning streams as `delta.reasoning` (OR-unified shape), already
  parsed by `_nano_gpt_http._chunk_to_events`.
- Tool-calls are delivered atomically (single chunk, full args), which
  the existing accumulator handles as a degenerate case.

The only DSv4-specific knowledge the existing path lacks is the
**capability shape** itself: on/off-only reasoning (no effort buckets,
because nano-gpt's slug-pair encoding already covers thinking mode),
plus a slug-based `first_class_support` differentiation (curated
DSv4 family yes; `TEE/*` and `*-cheaper` upstream paths no).

**Decision:** Introduce a "capability-only driver arm" pattern. The
DSv4 driver's `capability_spec` gains a `nano_gpt_http` branch with
its own logic, while `build_request` and `parse_chunk` continue to
raise `NotImplementedError` for that adapter — *by design, not as a
TODO*.

This shape:

1. Keeps the canonical DSv4 capability truth in one place (the driver),
   so the UI behaves consistently regardless of adapter.
2. Avoids duplicating the nano-gpt adapter's (working) wire-shape code
   into a parallel driver path.
3. Reflects the "best effort, not gold-plating" product stance for
   nano-gpt — we coupled minimally to a provider whose pflege of
   basics has been historically uneven.

**Generalises to:** any future provider where the existing adapter
already implements the wire shape correctly, but the model has
provider-specific capability rules worth centralising. The driver
arm acts purely as a capability lookup; wire calls stay in the
adapter.

**Anti-pattern this prevents:** dispatching a "complete the
asymmetry" task that would copy `build_request_*` and `parse_chunk_*`
into the driver for nano-gpt, duplicating logic and increasing
surface area for drift between the driver arm and the live adapter
path. The `NotImplementedError` messages and class docstring spell
this out so it's not mistaken for unfinished work.

**Slug-based `first_class_support`:** A second sub-decision worth
recording. We were tempted to introduce a "do not recommend" list
or new `is_curated` field, but `first_class_support` already encodes
the right semantic: it's the UI signal for "this is a path the
product recommends." Marking nano-gpt's `TEE/*` and `*-cheaper`
variants as `first_class_support=False` (while still listing them)
matches existing UI behaviour and avoids schema growth.

**Re-probe condition:** if nano-gpt ever introduces effort granularity
on the `:thinking` slug (e.g. `:thinking-max` or a real
`reasoning.effort` parameter that reaches the model), revisit this
to expose buckets. As of 2026-05-10, no such surface exists.

## INS-044 — Streamable HTTP session lifecycle is required by FastMCP-default servers (2026-05-10)

**Date:** 2026-05-10

**Context:** While polishing MCP integration we tested against a
local FastMCP server (`/home/chris/projects/simple_mcp`). After
adding `Accept: application/json, text/event-stream` to every MCP
request — fixing 406 responses — calls still failed with HTTP 400
`"Bad Request: Missing session ID"`.

**Cause:** FastMCP's Streamable HTTP transport (mcp lib >= 1.27) is
**stateful by default**. The protocol mandates a three-step lifecycle
before any tool call:

1. Client `POST /mcp` with `method: "initialize"` and capability
   negotiation. Server responds with the `Mcp-Session-Id` header.
2. Client stores the session id and sends it as `Mcp-Session-Id`
   header on every subsequent request.
3. Client sends a `notifications/initialized` notification to confirm
   the handshake is complete.

Servers can opt out via `stateless_http=True` (no session id required)
or by accepting `json_response=True` clients in the looser JSON-only
mode — but those are server-side switches, not something the client
can negotiate. A *correct* MCP client must implement the lifecycle to
be compatible with default-configured servers.

**Decision:** **Out of scope** for the 2026-05-10 polish package. The
MCP polish spec
(`devdocs/specs/2026-05-10-mcp-pills-result-and-streamable-http-design.md`,
§2 Non-Goals) already lists `Mcp-Session-Id` stateful session
management as deferred. The package ships:

- Accept header (both backend `_mcp_executor.py` and frontend
  `mcpClient.ts`)
- Content-Type dispatch (JSON / SSE) on the backend
- Pill Response rendering

A FastMCP server with `json_response=True` and either
`stateless_http=True` *or* a server willing to skip the session check
in JSON-only mode will work after this package. A FastMCP-default
server (stateful, JSON or SSE) will return 400 until session
lifecycle is implemented.

**Trigger to revisit:** the first user request for "I want to point
chatsune at a vanilla FastMCP server." Implementing the lifecycle is
roughly:

1. State on `GatewayHandle` — current session id, plus a small lock
   so two concurrent requests don't initialise twice.
2. `_mcp_executor.discover_tools` becomes the natural place to drive
   the initialise handshake (it runs once at session start), then
   stash the session id on the handle.
3. Every subsequent `call_tool` reads the session id off the handle
   and sets `Mcp-Session-Id` header. On 404 (`Session not found,
   please reinitialize`) re-run `initialize` and retry once.
4. Frontend `mcpClient.ts` needs the same lifecycle for `tier="local"`
   gateways. This is browser-fetch territory — straightforward but
   doubles the request count for tools/list.

**Why not now:** the symptom that drove this work was tester pills
showing no output, plus one Streamable-HTTP-aware server. Lifecycle
implementation has its own design surface (failure modes,
re-initialisation triggers, frontend storage of session id) and
deserves its own spec. Bundling it into the polish package would
have doubled the diff and delayed the pill fix that the testers
actually asked for. Pareto.

**Anti-pattern this prevents:** scope creep on a polish package.
"While we're in here, let's also implement sessions" feels efficient
but produces a spec that covers two distinct user-visible problems
(what-did-the-tool-return AND can-we-talk-to-arbitrary-MCP-servers)
in one design pass. Splitting them keeps each spec coherent and the
PRs reviewable.

**Resolved (2026-05-10):** Implemented in
`devdocs/specs/2026-05-10-mcp-streamable-http-session-lifecycle-design.md`
and `devdocs/plans/2026-05-10-mcp-streamable-http-session-lifecycle-plan.md`.
All four server modes (stateless+JSON/SSE, stateful+JSON/SSE)
verified manually against `simple_mcp` across local, remote, and admin
tiers. Mode auto-detected from `Mcp-Session-Id` response-header
presence; per-WebSocket-session state on `GatewayHandle`; in-memory
session cache in `mcpStore` for the local tier; one-shot lifecycle
on backend proxy routes; 404-retry-with-reinit on the inference path.

---

## INS-045 — Semver build versioning (`version.txt` + `/api/version`) (2026-05-13)

**Decision:** The repo's base version lives in a single `version.txt` at
the root (semver `<major>.<minor>.<patch>`). The CI workflow
(`.github/workflows/docker.yml`) derives the *full* version per build:

- Push to `master` → `<base>-pre.<github.run_number>` (e.g. `0.1.0-pre.25`)
- Push to tag `v1.2.3` → `1.2.3` (no `-pre` suffix)
- Pull request → same `-pre.<run>` shape; not pushed to GHCR

The computed value is passed to both Dockerfiles as a `VERSION` build-arg,
along with `CHATSUNE_GIT_SHA` (short SHA) and `CHATSUNE_BUILT_AT` (ISO-8601
UTC). The backend exposes `GET /api/version` returning a `VersionDto`
(`shared/dtos/system.py`). The frontend image writes the same value to
`/usr/share/nginx/html/VERSION` so nginx serves a plain-text `/VERSION`
endpoint.

**Resolution order in `backend.modules.system._version`:**

1. `CHATSUNE_VERSION` env var (Docker-injected)
2. `/app/VERSION` file (Docker fallback if env var stripped at runtime)
3. `version.txt` at repo root with `-dev` suffix appended (local dev runs)
4. `0.0.0-unknown` (hard fallback — should never be seen in practice)

Cached for the process lifetime via `lru_cache`; restart needed to pick
up a new version.

**Where the code lives:** A new tiny module `backend/modules/system/`
(public API: `router`, `resolve_version`). It's intentionally minimal —
versioning is a platform concern, not a domain. Adding business logic
to this module is a smell; pick or create a domain module instead.

**Why not embed in `main.py`:** the project convention is one module per
concern with a `_handlers.py` + public `__init__.py`. Putting a router
in `main.py` would set a precedent for other "tiny" features and erode
the boundary discipline that has paid off elsewhere.

**Bumping rules:** patch for bug fixes, minor for backwards-compatible
features, major for breaking changes. The `-pre.N` suffix is automatic
on master and means "what's currently on master, build N"; it is *not*
a stable identifier — only tagged `v*.*.*` builds are.

---

## INS-046 — Tensorix uses heterogeneous backend routing; reasoning surface varies per-model (2026-05-15)

**Date:** 2026-05-15

**Context:** When integrating Tensorix as a Premium provider we
initially classified each of the seven curated models as either
`binary` (on/off reasoning) or `stepped` (low/medium/high), based on
Tensorix's marketing and standard OpenAI-compatible expectations.
Empirical probing of the live API against all seven models showed
this is wrong.

**Discovery:** `GET /v1/model/info` exposes each model's underlying
route in `litellm_params.model`. Tensorix uses two routes:

- **OpenRouter proxy** (`openrouter/...` prefix) — deepseek-v4-pro,
  deepseek-v3.2, kimi-k2.6, glm-5, glm-4.6.
- **Direct in-house engines** (`openai/...` prefix, `api_base` to
  internal IPs like `95.133.253.142:8002`) — deepseek-v4-flash,
  glm-5.1.

The two routes don't agree about the OpenAI `reasoning_effort` field:

- OpenRouter-proxied models honour it the way OpenAI documents.
- glm-5.1 (direct) ignores `reasoning_effort="none"` — it thinks
  regardless.
- deepseek-v4-flash (direct) is reasoning-capable but Tensorix's
  direct backend doesn't emit a separate `reasoning_content` SSE
  channel for it; the model demonstrably thinks inline in the
  `content` stream. There is also no `completion_tokens_details`
  block in the terminal usage on this route. This is a Tensorix-side
  shape problem, not ours.

**Decision:** Classify each Tensorix model's reasoning surface
empirically (probe it), not from provider documentation. The
adapter now exposes only two shapes:

- `off_on_toggle` — only `deepseek-v3-2` today. ON sends
  `reasoning_effort="high"`, OFF sends `"none"`. Same shape as
  Mistral and xAI.
- `always_on` — the other six models. We omit `reasoning_effort`
  entirely (no point sending a field the backend ignores or
  contradicts) and surface a disabled-but-visible "always on" toggle
  in the UI.

**Why not just send the field everywhere:** lying to the upstream
about what we're controlling makes debugging harder and pollutes
the request logs we'd otherwise rely on to spot real regressions.
Better to be honest in the wire shape and honest in the UI.

**Re-probe trigger:** if Tensorix unifies their backend routing
(everything via OpenRouter, or everything via in-house) then the
empirical classification should be re-checked end-to-end. The
adapter's `/test` sub-router still validates only the curated slug
intersection, not per-model reasoning behaviour — capability drift
in *this* dimension is silent.

**Related:** INS-004 / INS-019 (model_unique_id format — slug-based
identity is what lets us route per-model logic in the adapter
without leaking provider plumbing to other modules).

---

## INS-047 — `session_seq` replaces `created_at` as the message ordering key (2026-05-17)

**Date:** 2026-05-17

**Context:** Every read and mutation of message ordering used to key
off `created_at`, a microsecond datetime. Two paths exposed the
foot-gun: `list_messages_tail` sorted by `created_at`, and
`delete_messages_after` / `edit_message_atomic` truncated by
`created_at: {"$gte": ...}`. When a user opened two tabs (or sent
two requests back-to-back), inserts could share a `created_at` tick;
the tiebreak was the random UUID `_id`, so pair-matching downstream
got non-deterministic, and the wrong sibling could be swept up by a
`$gte` delete.

For branching (the next spec), `created_at` is also fatal as a
lineage key — branches need an ordered identifier that isn't a clock.

**Decision:** Introduce a per-session monotonic integer counter,
`session_seq`, assigned atomically at insert time via
`find_one_and_update({"_id": session_id}, {"$inc": {"last_message_seq": 1}}, return_document=AFTER)`
on `ChatSessionDocument`. The session document holds the high-water
mark; messages carry their reserved seq. Two collections, one
counter, no multi-doc transaction:

- `find_one_and_update` is atomic at the Mongo level (even under
  RS0), so concurrent saves on the same session get distinct,
  causally-ordered seqs.
- If the subsequent `insert_one` fails, we leak one seq value —
  acceptable, because the invariant is monotonicity, not
  contiguity. Gaps after deletes are also normal.

**Implementation:** see
`devdocs/specs/2026-05-17-session-seq-migration-design.md`. The
field is additive on read (default 0 for legacy docs) and the
backfill runs in a numbered startup migration —
`backend/migrations/0001_session_seq.py` — invoked via
`backend/migrations/run_all(db)` from the FastAPI lifespan after
every module's `init_indexes` and before the app accepts requests.
This is the first auto-run migration in the repo; the directory
also still hosts legacy `m_YYYY_MM_DD_*.py` manual scripts which
`run_all` does NOT pick up (the regex only matches `NNNN_*.py`).

**Why we kept `created_at`:** it remains useful for display in the
sidebar, the admin "messages by time range" queries, and the
ChatGPT-import path's chronological seeding. The compound index
`(session_id, created_at)` stays in place alongside the new
`(session_id, session_seq)` index. Two indexes, two query shapes
— one for time-range UX, one for ordering correctness.

**`last_message_seq` is never rewound on delete.** Edits that
truncate the tail leave the high-water mark untouched; the next
insert receives the next seq value, creating a gap. The branching
spec relies on this: a branch that forks from seq=5 can be cloned,
the original counter advances to 6, and the two timelines never
collide on seq even if the user keeps writing on both.

**Tests:**

- `tests/test_repository_session_seq.py` — atomic increment under
  `asyncio.gather`, sort/delete/edit semantics, `next_session_seq`
  reservation.
- `tests/migrations/test_session_seq_migration.py` — old-shape
  fixture (3×5, no seq fields), idempotent re-run, out-of-band
  insert pick-up, live `save_message` after migration, `run_all`
  discovers and runs the 0001 module.

**When to revisit:** if Mongo ever loses single-document atomicity
on `find_one_and_update` (it won't, but theoretically), the entire
ordering story collapses. If cross-session ordering ever becomes a
need (e.g. a global timeline view), seq is per-session — a
secondary key (e.g. global `created_at` or a separate `global_seq`)
would have to be added.

**Related:** the existing `_id: {"$ne": message_id}` clause in
`edit_message_atomic` is preserved — we still need to keep the
target around for the subsequent content update. The truncate
helper was renamed from `delete_messages_after` to
`delete_messages_from` to match the new inclusive `$gte`
semantics; the old name implied target-exclusion which never
matched what callers actually needed.

## INS-048 — Pair messages by `correlation_id`, not positional adjacency (2026-05-17)

**Date:** 2026-05-17

**Context:** `select_message_pairs` used to walk the chronological
message list with `i += 2` on a user/assistant alternation and
`i += 1` otherwise. Three bugs shared this root cause:

- **a-2:** `_filter_usable_history` dropped aborted assistants but
  left the sibling user behind. The pair-builder then saw
  `[user, user, assistant]`, advanced past the orphan, and the
  model received no record the user said anything on that turn.
- **a-3:** the two-tab race writes `user_B` between `user_A` and
  the cancelled `assistant-for-A`. `session_seq` (INS-047) made
  the order deterministic, but positional pairing still mismatched
  `user_B` with `assistant-for-A` — the model received a reply
  addressed to the wrong question.
- **a-10:** orphan user messages survived compaction and polluted
  subsequent pair-matching.

**Decision:** Pair user/assistant docs by shared `correlation_id`.
Every user message already carries one (assigned by
`handle_chat_send`); the forward-fix at
`backend/modules/chat/_orchestrator.py` `save_fn` now forwards that
cid (and `user_id`) onto the assistant write so the pair-builder
has a key to match on. Position is no longer load-bearing —
race-poisoned timelines re-pair correctly, branching (the next
spec) clones cids without changes, and aborted/refused assistants
take their sibling user with them when their pair is dropped.

**Implementation:** see
`devdocs/specs/2026-05-17-pair-by-correlation-design.md`. Three
moving parts:

1. **Forward-fix** at `backend/modules/chat/_orchestrator.py:1241`
   (`save_fn` passes `correlation_id` + `user_id` to
   `repo.save_message`). One-line change covers every assistant
   write that flows through the orchestrator — edit and regenerate
   paths route through the same `save_fn`.
2. **Backfill migration** at
   `backend/migrations/0002_assistant_correlation_id.py`. Two
   cohorts:
   - **Legacy sessions:** assistant docs with `correlation_id=None`
     inherit the immediately-preceding user's cid (sorted by
     `session_seq`, with `created_at` and `_id` as tiebreaks).
   - **Imported sessions** (`session.imported_from` set, every doc
     has `cid=None` by construction): each pair gets a synthetic
     `imported-{session_id}-{idx}`; trailing or doubled-up users
     get `imported-{session_id}-orphan-{idx}`.

   Idempotent — only writes when `correlation_id is None`.
3. **Pair-builder rewrite** at `backend/modules/chat/_context.py`
   `select_message_pairs`. Public signature unchanged. New algorithm
   indexes by cid, then walks user docs in their original order and
   emits `(user, assistant)` only when (a) the cid has both halves
   and (b) the assistant's `status == "completed"`. Newest-first
   budget selection is identical to before.

**`_filter_usable_history` is now a pass-through.** Status semantics
moved to the pair-builder so the user and assistant are dropped
*together* — never one without the other. The function is kept
(rather than inlined out) because regression tests reference it
directly; the in-file comment warns future contributors not to
re-introduce role/status filtering there.

**Why `correlation_id`, not `session_seq` adjacency on the read
side?** Branching (the next spec) clones a subtree of messages
into a new session. Under a tree model "positional adjacency" no
longer expresses lineage, but a `correlation_id` invariant carries
through cleanly — the pair-builder works on a branch without
changes. INS-047's `session_seq` is still the *write*-ordering key;
INS-048 covers *pairing*. The two are orthogonal.

**Defensive skip on missing cid.** Until the migration runs, legacy
assistant docs have `correlation_id=None`. The pair-builder's
`if not cid: continue` keeps them out of the pair set without
crashing. The migration runs at startup before the app accepts
requests (via `run_all` from INS-047), so by the time real traffic
flows every doc has a cid.

**Tests:**

- `tests/test_context_pair_by_correlation.py` — eight unit tests
  covering basic pairing, aborted/refused drops, orphan user,
  two-tab race regression, defensive skip on missing cid, budget
  cap, and regenerate last-write-wins on a slot.
- `tests/migrations/test_correlation_id_backfill.py` — six
  integration tests against old-shape docs in a real Mongo DB
  (CLAUDE.md hard rule): legacy backfill, imported synthetic ids,
  orphan-user handling, idempotent re-run, two-users-in-a-row
  edge case, `run_all` discovery.
- Smoke assertion in `tests/test_chat_repo_phase2.py` that
  `save_message` persists the forwarded `correlation_id` and
  `user_id` on assistant docs.

**When to revisit:** if we ever need to render a *partial* pair
(e.g. show the orphan user message in a "this turn was cancelled"
UI slot in the chat history view), the pair-builder is for LLM
context only — the renderer reads `list_messages_tail` directly
and is not affected. If branching introduces a session where two
distinct branches both carry the same `correlation_id` (a clone
preserved it on both sides), the pair-builder's per-session input
keeps them isolated — only the orchestrator's session scoping
needs to stay tight.

**Related:** INS-047 (`session_seq` write ordering). Both ship in
the same v0.2.0 pre-branching wave; correlation-id pairing is the
last structural prerequisite before the tree model lands.

---

## INS-049 — Persist `replay_tool_history` per assistant turn, not retroactively (2026-05-17)

**Date:** 2026-05-17

**Context:** The reasoning + tool replay spec (INS-shipped earlier in
this wave) introduced `ChatSessionExtras.replay_tool_history` as a
session-level cockpit toggle. Initially the orchestrator read the
live value at history-expansion time and applied it to every past
turn in the session. That made the toggle **retroactive**: flipping
it off mid-conversation rebuilt every prior tool-using turn without
its tool narration, the context-fill ampel jumped down instantly,
and the user's mental model — "the model already knew about that
tool call" — was violated. Flipping back on restored the old token
counts; back-and-forth toggling made the ampel jitter for no good
reason.

**Decision:** Snapshot the flag value **per turn** at the moment the
assistant document is persisted, then read that snapshot back at
history-expansion time. The live `extras.replay_tool_history` toggle
governs only **future** turns; prior turns stay expanded with the
policy that produced them.

**Implementation:** see
`devdocs/specs/2026-05-17-replay-tool-history-per-turn-flag-design.md`.
Four moving parts:

1. **Document field.** `ChatMessageDocument.tool_replay_at_save:
   bool = True` in `backend/modules/chat/_models.py`. Pydantic
   default `True` is the backwards-compat read mechanism — legacy
   assistant docs without the key deserialise as if replay was on,
   matching their original behaviour. No migration script needed;
   no index, no schema migration.
2. **Repository write.** `ChatRepository.save_message` takes an
   optional `tool_replay_at_save: bool | None = None` kwarg. The
   value is only written when `role == "assistant"` and the kwarg
   is supplied — user-message writes and legacy callers leave the
   field absent.
3. **Snapshot capture.** `run_inference` resolves the snapshot
   immediately after the extras are finalised (post
   `reasoning_override` merge) — *at inference start*, not at
   `save_fn` call time. Mid-stream toggles do not retroactively
   reshape the in-flight turn. The closure threads
   `replay_tool_history_snapshot` through to `save_message`.
4. **Read path.** `_expand_history_doc` no longer accepts
   `replay_tool_history` as a kwarg. Instead it does
   `doc.get("tool_replay_at_save", True)` on each assistant
   document. The call site in `run_inference` stops passing the
   global flag — there is no global replay flag in expansion any
   more.

**Why a snapshot, not a join against session extras?** Sessions
mutate; per-turn semantics need turn-pinned state. Storing the
flag on the assistant document keeps the read path one fetch deep
(the same query that returns the message) and survives branching
cleanly — a branch clone copies each message's snapshot along with
its content, so the branch's prior history expands identically to
the parent's at fork time. The branch's *new* turns can diverge by
toggling without rewriting history.

**`extras.replay_tool_history` stays put** on the session document
— it is the "next-turn policy" knob the cockpit toggle writes to.
Its semantic changed from "applied at expansion" to "snapshot at
save". For users who never touch the toggle, behaviour is
identical.

**Tests:**

- `tests/modules/chat/test_history_expansion.py` — extended. The
  legacy `(replay_reasoning, replay_tool_history)` kwarg combos
  now set `tool_replay_at_save` on the fixture docs. Two new
  cases: per-doc respected across two assistant docs in the same
  history, and legacy doc without the key defaults to replay-on.
- `tests/test_chat_repo_phase2.py` — smoke test that
  `save_message` writes the field when supplied, leaves it absent
  when omitted, and never writes it on user-role docs even if the
  kwarg is supplied.

**Related:** INS-047 (`session_seq` write ordering), INS-048
(`correlation_id` pairing). The trio ships in v0.2.0's
pre-branching stabilisation wave. The cockpit toggle UI that
exposes this flag to users lives in spec
`devdocs/specs/2026-05-17-replay-tool-history-toggle-ui-design.md`.

---

## INS-050 — Replay-tool-history cockpit toggle: desktop button + mobile R-badge (2026-05-17)

**Date:** 2026-05-17

**Context:** INS-049 made `extras.replay_tool_history` historically
stable — each assistant doc snapshots the policy that produced it,
so toggling the flag governs only future turns. To surface that
control to users, the cockpit needed a glanceable affordance with
a non-retroactive UX message ("applies from the next response").
Two presentations, one underlying state.

**Decision:**

- **Desktop:** a dedicated `ReplayHistoryToggleButton` inside the
  cockpit row, immediately to the right of the `ReasoningToolsCluster`
  (which renders ThinkingButton + ToolsButton). Glyph: `↻`. Accent:
  neutral. ARIA label reflects state ("Tool history replay: on" /
  "off"). A transient German hint "Wirkt sich ab der nächsten
  Antwort aus" surfaces below the button for 3000 ms after every
  state change — local component state with a `setTimeout`, no
  global store, fade respects `prefers-reduced-motion`.
- **Mobile:** the toggle is folded into the 🔧 group dropdown's
  expanded menu as the LAST entry (after Image + Integrations).
  The collapsed 🔧 trigger carries a small "R" marker in its
  bottom-left corner whenever `replay_tool_history === true` (the
  default). Off → no badge. Chris's preference: badge on the
  default state, because the feature is a positive capability and
  permanent visibility adds awareness without harm.

**Implementation:** see
`devdocs/specs/2026-05-17-replay-tool-history-toggle-ui-design.md`.
Four moving parts:

1. **New file** `frontend/src/features/chat/cockpit/buttons/
   ReplayHistoryToggleButton.tsx`. Reads
   `cockpit.extras.replay_tool_history` (defaulting to `true` for
   unhydrated sessions) and writes through `useCockpitStore.
   updateExtras(sessionId, { replay_tool_history: !enabled })`.
   No new endpoint — `PATCH /api/chat/sessions/{id}/extras` already
   accepts the field via the underlying Pydantic DTO.
2. **`CockpitGroupButton.bottomLeftBadge`** prop. Optional
   `string | null`. Renders an `aria-hidden` 9 px marker styled
   like the existing `CockpitButton` badge (bottom-right for
   single-button effort markers; bottom-left here so it does not
   collide with the active-child dot in the top-right). Used today
   only for the "R" replay marker, but the prop is generic.
3. **`CockpitBar` wiring.** Desktop: `<ReplayHistoryToggleButton>`
   between `{cluster}` and the Image/Integrations block, with a
   `<Sep />` between Image and the toggle so the cluster reads as
   "Thinking · Tools · Replay". Mobile: toggle appended as the
   last child of `toolsGroupChildren`; `bottomLeftBadge={replayActive
   ? 'R' : null}` on the parent `<CockpitGroupButton icon="🔧">`.
4. **`ChatSessionExtras` TS type + defaults.** The frontend type
   gains `replay_tool_history: boolean` (required, matching the
   backend Pydantic shape with the `True` default).
   `cockpitDefaults.ts`, the fallback in `CockpitBar`, the
   `ChatView` hydrate path, and the `cockpitStore` extras event
   handler all set `replay_tool_history: true` so legacy
   payloads / unhydrated sessions render the toggle in the
   active state. The store event-handler defends against a
   missing `replay_tool_history` field in the event payload by
   defaulting to `true` — same backwards-compat read story as
   the backend.

**Why a transient hint, not a permanent caption?** The
non-retroactive semantics ("applies from next response") matters
exactly once per toggle change. A permanent caption would clutter
the cockpit; a tooltip alone is invisible on touch. 3 s is long
enough to read and short enough that the cockpit row stays clean
for normal use. Local state plus `setTimeout` keeps it scoped to
the component — no global hint-state plumbing.

**Why the "R" badge on the default state, not on the
non-default?** Chris's variant A: the feature is a positive
capability ("we will replay tools to keep the model coherent
across turns"), permanent visibility adds awareness without harm.
The off state needs no permanent UI — the user just set it that
way two seconds ago.

**Tests:**

- `frontend/src/features/chat/cockpit/buttons/__tests__/
  ReplayHistoryToggleButton.test.tsx` — renders active when on,
  idle when off, PATCHes the negated value on click, surfaces the
  German hint for 3 s and clears it (fake timers).
- Existing `CockpitBar.test.tsx` fixtures gained the new
  `replay_tool_history` field so the cluster regression suite
  stays green against the now-required type.

**Related:** INS-049 (per-turn `tool_replay_at_save` snapshot
that makes this toggle's UX honest). The next consumer of this
control is the branching feature (`a-9`): each branch carries its
own `extras.replay_tool_history` in the cloned session document,
so the R-badge surfaces per-branch state at a glance.

---

## INS-051 — Frontend race fixes: dedup-by-content + reconciliation queue (2026-05-17)

**Date:** 2026-05-17

**Context:** Two long-standing frontend races got worse under the
branching feature's frequent session switches:

- **d-6 — duplicate-display of user messages.** The
  `CHAT_MESSAGE_CREATED` handler swapped an optimistic entry into a
  real one only when the server-echoed event carried THIS tab's
  `client_message_id`. Any path that produced a real user doc
  without that id (ChatGPT import replay, branch-fork synthetic
  message, second-tab echo) appended the real message and left the
  optimistic in place. The user saw their own text twice.
- **d-13 — `reset` + REST `getMessages` race.** Switching to a
  session opens a 50–500 ms gap between `chatApi.getMessages(...)`
  firing and its `.then(...)` running. WS events arriving during
  that window either landed on top of state that the upcoming REST
  snapshot was about to overwrite (lost) or were applied to the
  freshly-replaced snapshot in arbitrary order. Branch-switching
  under a live stream is exactly that hot path made common.

**Decision:**

- **d-6:** add a second fallback to `CHAT_MESSAGE_CREATED` handling.
  When `client_message_id` does not match (or is absent), look for
  an optimistic user message with **exact** content equality. If
  found, swap it; otherwise append. Gated on `role === 'user'`
  (only user messages have optimistic counterparts) and
  `is_optimistic === true` (never collapse a real message into
  another real one). No trimming, no normalisation — same-text
  false positives are vanishingly rare; the dedup cost is far
  preferable to the duplicate-display cost.
- **d-13:** add a per-session **reconciliation queue** to
  `chatStore`. ChatView opens the window with
  `beginReconciliation(sid)` before firing `getMessages`. Any
  WS event whose `payload.session_id === sid` arriving while the
  window is open gets queued instead of dispatched. The
  `then(...)` handler applies the REST snapshot, then calls
  `endReconciliation(sid, handler)` which drops the entry FIRST
  (so the drained-event recursion sees a closed window) and
  replays the queue through `handleChatEvent`. Each event takes
  the exact same path it would have taken live — d-6's dedup
  fallback survives the drain unchanged. Cancellation
  (`if (cancelled)`) and REST failure both close the window with
  a no-op handler so events do not get queued forever.

**Implementation:** see
`devdocs/specs/2026-05-17-frontend-race-fixes-design.md`.

- `frontend/src/features/chat/useChatStream.ts` —
  `CHAT_MESSAGE_CREATED` switches over three fallbacks
  (`client_message_id` exact match → content-equality dedup →
  unconditional append). At the top of `handleChatEvent`, the
  function checks `chatStore.reconciling[sid]` for the event's
  `payload.session_id` and queues if a window is open.
- `frontend/src/core/store/chatStore.ts` — new
  `reconciling: Record<string, BaseEvent[]>` state, plus
  `beginReconciliation` / `endReconciliation` /
  `queueReconciliationEvent` actions. `endReconciliation` clears
  the entry **before** replaying so the drained events dispatch
  normally (bounded recursion).
- `frontend/src/features/chat/ChatView.tsx` — the `getMessages`
  effect opens the window before firing the REST call, closes
  it (with a no-op handler) on cancellation or REST failure, and
  closes it (with the regular dispatcher) on success — after the
  snapshot has been applied.

**Why content equality without trimming?** A user typing
`"hello "` with a trailing space and the server echoing `"hello"`
without it would NOT dedup, and the optimistic would get cleaned
up by its own future echo or stay until session-switch. That is
acceptable: the failure mode is one stray optimistic, not a
silent collapse of two distinct messages. Trimming or fuzzy
matching introduces a risk of false-positive collapsing of
deliberately-similar messages (think: rapid retries of "yes" /
"yes." / "yes!") which is worse.

**Why drop the reconcile-entry first, then replay?** A drained
event whose handler recursively touches the store (typical for
`setMessages` / `appendMessage`) must see
`reconciling[sid] === undefined`, otherwise the dispatch would
re-queue itself into the same array. Dropping first keeps the
recursion bounded at one level: the queued event runs, takes the
non-queue path, and any handler-internal events get dispatched
normally too.

**Tests:**

- `frontend/src/features/chat/__tests__/useChatStream.dedup.test.ts`
  — six cases covering all three fallbacks plus the
  role-mismatch and is_optimistic guards.
- `frontend/src/features/chat/__tests__/useChatStream.reconcile.test.ts`
  — six cases: events arriving during the window get queued,
  `endReconciliation` drains them, OTHER sessions flow through,
  cancellation drops the queue, and drained events still
  exercise d-6's dedup-by-content path.

**Related:** d-6 + d-13 are listed in `PRE-BRANCHING.md` as
race-mitigation prerequisites for the branching feature itself.
With these in place, frequent session switches under live streams
no longer silently corrupt the message list.

## INS-052 — Branching is clone-on-branch, not a tree on disk (2026-05-17)

**Date:** 2026-05-17

**Context:** Branching is the v0.2.0 flagship feature: users fork a
conversation at any past assistant turn into an independent new
chat. Two storage shapes were on the table — a deep tree
(`parent_id` + `branch_id` columns, branches share documents) vs
clone-on-branch (each branch is a normal `ChatSessionDocument`
with its own messages). PRE-BRANCHING Q1 picked clone-on-branch
explicitly: storage cost is low priority, and the clone composes
cleanly with everything we already built (compaction, memory
extraction, pair-by-correlation, reasoning replay, the new
`session_seq` write key).

**Decision:** `POST /api/chat/sessions/{parent_session_id}/branch`
performs a synchronous multi-document MongoDB transaction
(`ChatRepository.clone_session_at`) that:

1. Loads the parent session and the fork-point assistant under a
   transaction so a parallel compaction can't slip in.
2. Pulls every message with `session_seq <= fork_msg.session_seq`.
3. Writes a new session doc (new `_id`, fresh `created_at`,
   `pinned=False`, `state="idle"`, `forked_from` populated).
4. Clones each parent message with a fresh `_id`, a re-stamped
   `session_seq` running 1..N over the cloned set, and **the same
   `correlation_id`** so pair-by-correlation (INS-048) and
   reasoning replay continue to work on the branch.
5. Drops compaction checkpoints whose `tail_start_message_id`
   falls outside the cloned set, and re-maps the survivors onto
   the new branch's `_id`s.
6. Tags every dict entry on each cloned assistant doc's `events`
   array with `cloned_from_branch: True`.

`fork_message_id=None` is the documented "branch from session
start" case (spec §7.7) — the new session is created with zero
cloned messages and the user's frontend then runs a normal
`chat.send` against it.

**Why a Mongo transaction:** the clone touches both
`chat_sessions` and `chat_messages` and reads from
`chat_messages` while a parallel compaction may be writing.
Without a transaction, step 2's read can race against the
compaction's tail-rewrite. RS0 is mandatory per CLAUDE.md;
multi-doc transactions work. The existing `edit_message_atomic`
already uses the same pattern (`backend.database.get_client` →
`start_session` → `start_transaction`).

**The `cloned_from_branch` flag.** Per PRE-BRANCHING Q5, cloned
tool-call events do NOT re-execute (which would duplicate side
effects like `write_journal_entry`); the recorded result is
preserved verbatim. The flag is added to every `TimelineEntry*`
DTO (default `False`) so the frontend renders a small
"cloned from parent — not re-executed" subtitle on the pill.
Existing documents deserialise unchanged — the flag is purely
additive.

**The `forked_from` pointer is informational only.** Set at
clone time, never consulted by the inference path. Future
"show branches of this session" surfaces (and analytics) can
walk it; v0.2.0's sidebar treats branches as ordinary sessions
sorted by `updated_at`. `forked_from.message_id` is optional so
the session-start case round-trips cleanly. Parent deletion
leaves the pointer dangling — that's by design, no cascade.

**`session_seq` re-stamp on clone, correlation_id preserved.**
INS-047 keeps the parent's `last_message_seq` advancing on its
own track; the branch starts a fresh per-session counter at
`len(cloned_msgs)`. Re-stamping 1..N on the cloned messages
keeps the branch's monotonic invariant intact. Correlation IDs
carry through 1:1 so the pair-builder (INS-048) doesn't even
notice it's working on a branch — branch and parent can share a
cid for the same logical pre-fork turn without colliding (per-
session scoping makes them distinct rows).

**No `branch_session` mutation in `_handlers_ws.py`.** The
clone endpoint lives entirely in `_handlers.py` (REST) — it
does not run inference, does not start a stream, does not
publish any chat content events. After 201 the frontend
switches to the new session and issues normal `chat.send` or
`chat.regenerate` against the branch (cases 1/2/3/4b in the
spec). Keeps the endpoint side-effect-free in inference terms.

**Why no `_compaction_lock_held` boundary leak.** The lock
helper lives in `backend/modules/chat/_handlers_ws.py` (sibling
of `_handlers.py`, same module). Importing it inside the chat
module is fine — the boundary rule guards against *external*
modules reaching into our internals, not against intra-module
sharing. Moving the helper to a shared internal file is an
option for a follow-up tidy; we'd touch every existing call
site, so it can wait.

**Tests:** `tests/test_branching.py` covers ten cases — basic
clone shape, extras preservation, compaction-checkpoint re-map,
event-flag stamping, session-start (`None`) branching, the
defensive user-role fork-point rejection, wrong-owner 404, the
compaction-lock 409 path (HTTP end-to-end), the concurrency
case (`asyncio.gather`), and an HTTP smoke test that asserts the
DTO carries `forked_from`. No backfill migration — the new
fields are additive and default-friendly per CLAUDE.md's no-DB-
wipes rule.

**When to revisit:** if a single clone of a multi-thousand-
message session ever exceeds ~5s sync, move it to a background
job and stream progress events (already speculated in PRE-
BRANCHING). The current synchronous design assumes the typical
branch fork-point is within a few hundred messages of the head.

**Related:** INS-047 (`session_seq`), INS-048 (pair by
`correlation_id`), INS-049 (per-turn `replay_tool_history`
snapshot — carried through verbatim on cloned assistant docs).
The whole pre-branching wave was scoped specifically so branching
could compose with them without further structural changes.

## INS-053 — Branching UI: four trigger patterns, two dialogs, one orchestrator (2026-05-17)

**Date:** 2026-05-17

**Context:** The branch endpoint (INS-052) is purely additive on
the wire — clone, return the new session, no inference. The UX
work lives entirely on the frontend: four behaviourally distinct
trigger patterns must collapse onto the same `POST /branch` call
plus optional follow-up `chat.send` / `chat.regenerate`. Spec
`devdocs/specs/2026-05-17-branching-design.md` §2.

**The four triggers and how the UI distinguishes them:**

1. **`[Branch]` on any assistant message** — fork at this
   assistant (verbatim clone), no follow-up. Endpoint state in
   the branch: the cloned assistant is the last message; the
   user types the next turn.
2. **`[Regenerate]` on the LAST assistant** — unchanged in-place
   behaviour. No dialog, no API call.
3. **`[Branch & Regenerate]` on a non-last assistant** — same
   button slot as Regenerate, re-labelled. Forks at the
   assistant, then runs `chat.regenerate` against the branch.
4. **Edit + Save & Resend** on a user message — two sub-cases:
   - **Last user message (case 1):** chooser dialog with two
     options. *Antwort ersetzen* runs the legacy in-place flow;
     *Neuer Branch* chains into the name dialog with a
     `chat.send` follow-up against the branch.
   - **Earlier user message (case 2):** no chooser. Branch is
     the only safe option (in-place would invalidate later
     messages), so the name dialog opens directly with the same
     `chat.send` follow-up.

**Two dialogs, two state slots.** `BranchNameDialog` and
`EditResendDialog` are separate components and have separate
`branchDialogContext` / `editResendContext` state slots in
`ChatView`. The chooser dialog can chain into the name dialog
cleanly by clearing its own context and setting the other one;
keeping them entangled would have forced a state machine where a
simpler hand-off does the job.

**The fork-point is always an assistant (or `null`).** Spec §3.1
is strict: pair-matching demands the cloned tail is well-formed.
The frontend computes the fork id from the action context:
- Branch / Branch&Regen on assistant `A_n` → `fork = A_n.id`.
- Edit user `U_n` → `fork = the assistant immediately before U_n`,
  or `null` if `U_n` is the first message. Helper:
  `findPriorAssistantId` in `ChatView.tsx`.

**Follow-up dispatch happens on the next tick, not immediately.**
After `branchSession` returns, the orchestrator calls
`navigate(/chat/{persona}/{branchId})` and only then schedules the
follow-up `sendMessage` via `setTimeout(..., 50)`. Dispatching
synchronously would target the parent session because the route
change hasn't remounted `ChatView` yet — the chatStore's
`activeSessionId` is still the parent's. The 50ms delay is
empirical; it could be replaced with a "wait until route
matches" promise in a future tidy.

**`cloned_from_branch` subtitle is rendered at the timeline-
entry render layer, not inside each pill.** Wrapping every
pill component to know about the flag would have meant touching
five files (`ToolCallPill`, `WebSearchPills`, `KnowledgePills`,
`ArtefactCard`, `InlineImageBlock`). Instead `renderTimelineEntry`
in `MessageList.tsx` checks `entry.cloned_from_branch` and drops
a small `<ClonedFromBranchSubtitle />` beneath the rendered pill.
DRY by construction; pill components remain ignorant of branching.

**Sibling-variant-index computation is best-effort and cosmetic.**
The name dialog scans `useChatSessions().sessions` for titles
matching `${parentTitle} (Variante <n>)` and picks `max + 1`. Two
tabs branching simultaneously may compute the same number — the
backend does not enforce unique titles, so the collision is a
purely cosmetic problem the user can fix by renaming. Spec §7.6.

**Incognito sessions bypass the branch path entirely.** No
server-side session means no document to clone. `handleEdit`
short-circuits to the in-place flow when `isIncognito` is true,
and `onBranch` is left undefined on the `MessageList` so the
Branch button doesn't render at all in incognito chats.

**`MessageList.onRegenerate` signature change.** It now takes an
optional `{ messageId, isLastAssistant }` object so the
non-last branch path can route to the name dialog. The trailing
"Generate response" CTA (which fires when the last message is a
user message awaiting an assistant) calls it with no arguments
and the existing in-place behaviour is preserved.

**Tests live in `frontend/src/features/chat/branching/__tests__/`**
and `frontend/src/core/api/__tests__/chat.branchSession.test.ts`.
Coverage:
- API wire shape (path, body, return value).
- Dialog rendering (German strings, default-name seeding, cancel
  vs confirm wiring, loader on submit).
- Action-bar rules on assistant messages (last vs non-last
  labels and button visibility).
- End-to-end flow harness (confirm → API call → switch
  notification; error path leaves the user in the parent).
- `cloned_from_branch` subtitle rendering on cloned entries
  and its absence on fresh ones.

**Related:** INS-052 (backend endpoint and clone semantics),
INS-048 (pair-by-correlation — branch and parent share cids by
design so the pair builder works without changes).

## INS-054 — nano-gpt STT rejects `audio/webm`; spoof as MKV (2026-05-17)

Browser MediaRecorder (notably Chrome) captures audio as
`audio/webm;codecs=opus`. xAI's direct STT endpoint accepts that
content-type. **nano-gpt's STT wrapper does not** — it runs an
early content-type whitelist (MP3, WAV, OGG, OPUS, FLAC, AAC, MP4,
M4A, MKV) and returns HTTP 400 `Unsupported file type` before the
audio ever reaches ffmpeg.

**Fix.** In `_nano_gpt_voice_xai.py:transcribe`, when the inbound
content-type contains `webm`, the multipart upload declares
`audio/x-matroska` with filename `audio.mkv`. The audio bytes are
unchanged. This works because webm is a restricted profile of
Matroska — the MKV parser ffmpeg uses on `.mkv` files reads the
webm container fine.

**Empirically verified** against the live nano-gpt API on
2026-05-17 with a real Opus-in-webm sample. Three alternative
spoofs were probed and all failed:
- `audio/ogg` / `audio.ogg` → 400 "Unable to read the audio
  duration" (ogg headers differ from webm just enough that the
  duration probe rejects).
- `audio/opus` / `audio.opus` → same error.
- `application/octet-stream` → bypasses the early whitelist but
  triggers an upstream xAI 422.

Only `audio/x-matroska` (and the equivalent `video/x-matroska`)
get a 200.

**Why this lives in the adapter, not at the frontend.** Different
upstream voice providers have different format tolerances. xAI
direct accepts webm; nano-gpt's wrapper doesn't. Keeping the
remap at the adapter boundary means frontend behaviour stays
provider-agnostic and per-provider quirks live in one place. If a
future backend behind nano-gpt (Mistral, ElevenLabs, MiniMax)
exposes a different whitelist, the same pattern repeats inside
that adapter.

**Related:** Spec
`devdocs/superpowers/specs/2026-05-17-nano-gpt-voice-design.md`.

## INS-055 — Fable is effort-based Claude; INS-037 gets an exception (2026-06-10)

**Decision:** ``anthropic/claude-fable-*`` models send
``reasoning: {enabled: true, effort: <bucket>}`` on the router paths
(nano-gpt, OpenRouter). ``is_effort_based_claude()`` in
``_anthropic_cache.py`` carries the exception; all other Claude
families keep the INS-037 effort omission.

**Context:** Live probes (2026-06-10, nano-gpt) showed that for Fable 5
``{"enabled": true}`` alone is a **silent no-op** — zero reasoning
output, while Opus 4.7 reasons on the identical flag. With an
``effort`` bucket present, reasoning streams and scales plausibly
(low/medium/high). The INS-037 rationale does not apply here: no
INS-035-style percentage-budget explosion (Fable handles effort
natively), and no INS-036-style silent drop — effort and
``cache_control`` markers coexisted in one body with reasoning intact.
Unsigned thinking-block replay (nano-gpt streams no signature for
Fable) is accepted upstream. Cache usage metrics read zero via
nano-gpt for Fable *and* Opus alike — the known nano-gpt
cache-visibility gap, not a Fable regression; cache QA stays on
OpenRouter.

**Probes:** see devdocs/specs/2026-06-10-claude-fable-5-nano-gpt-design.md.

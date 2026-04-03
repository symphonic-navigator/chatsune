# Chatsune — Progressive Discovery Log

Architectural decisions and design insights that emerged during development.
These are not hard requirements (those live in CLAUDE.md) but rather
reasoning that explains *why* things are built the way they are.

Add an entry whenever a non-obvious design choice is made — especially when
a simpler-seeming alternative was considered and rejected.

---

## INS-001 — Model Metadata: Lazy Redis TTL, No Cron, No Events

**Decision:** Model metadata (available models per provider, including capabilities
like reasoning/vision/tool-calls) is cached in Redis with a 30-minute TTL.
It is fetched lazily: only when a cache miss occurs at request time.
No background cron job. No WebSocket events for model list updates.

**Why lazy load:**
A cron job would poll the upstream provider even when no user is active.
Lazy loading means the upstream is only hit when someone actually needs the data,
and Redis absorbs all subsequent requests until the TTL expires.

**Why no events for model list updates:**
Model metadata is reference data, not mutable user state.
It changes rarely (new models added by Ollama every few weeks at most).
WebSocket events are for state changes that happen asynchronously without
the user asking — model list updates do not qualify.
The UI fetches the model list when it needs it (e.g. opening the model picker)
via `GET /api/llm/providers/{provider_id}/models`. If the cache is warm, it is
instant. If not, it fetches once and warms the cache for all other users.

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

**Decision:** Models are identified by a compound string: `<provider_id>:<model_slug>`

Examples: `ollama_cloud:llama3.2`, `ollama_cloud:qwen2.5-coder:32b`

**Why:**
The provider prefix makes it unambiguous which adapter handles a given model,
without requiring a separate lookup. Parsing is trivial: split on the first `:`.
The remainder is passed as-is to the adapter — adapters own their slug format.

**Validation:**
When a Persona is created or updated with a `model_unique_id`, the backend
validates that the provider segment matches a registered adapter. It does not
validate that the specific model slug exists (that would require an upstream call).

---

## INS-005: Two-Layer Model Data (Ephemeral + Persistent)

**Decision:** Provider model metadata (Redis, 30min TTL) is stored separately from admin curation (MongoDB, persistent). They are merged at read time.

**Why:** Provider data is volatile — models appear, disappear, change specs on the upstream. Curation is an admin decision that must survive cache flushes and temporary provider outages. Coupling them (as Prototype 2 did) means a cache flush or provider hiccup wipes admin work. Separating them means curation persists even if a model temporarily vanishes.

**Event differentiation:** `llm.model.curated` events carry the full merged DTO (instant client update). `llm.models.refreshed` events are trigger-only (client re-fetches). This distinction matters for frontend implementation: curated = update store in place, refreshed = invalidate and re-fetch.

---

## INS-006 — Three-Layer Model Data (Extension of INS-005)

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

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

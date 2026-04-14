# Chatsune — Developer Guide for Claude Code

This file is the single source of truth for architectural decisions, conventions,
and hard requirements. Read it before touching any code. Update it when decisions change.

For non-obvious design choices and the reasoning behind them, see **[INSIGHTS.md](INSIGHTS.md)**.
Add an entry there whenever a significant architectural decision is made during development.

---

## What is Chatsune?

Chatsune is a privacy-first, self-hosted, multi-user AI companion platform.
It is built as a **Modular Monolith** backend with a React/TSX frontend.
All LLM inference runs locally via Ollama (Phase 1).

This is Prototype 3. Two prior prototypes were built and discarded.
The architecture here reflects hard-won lessons — do not shortcut them.

---

## Implementation defaults

1. Please use subagent driven implementation always (no need to ask here)
2. Please always merge to master after implementation

---

## Debugging

When fixing bugs, always consider the **full causal chain** — do not stop at the first fix.
Check whether there are multiple root causes or if the fix depends on infrastructure
(e.g. Docker volumes, environment config, Redis state, MongoDB replica set).

- Before implementing any fix, enumerate **all** possible root causes
- Check infrastructure and config layers, not just application code
- After applying a fix, verify it end-to-end — not just the immediate symptom
- If a fix spans backend and frontend, verify both sides

---

## Build Verification

This is a **TypeScript/JSX frontend + Python backend** project.
Always ensure clean compilation/build after changes.

- **Frontend:** run `pnpm run build` (or `pnpm tsc --noEmit`) after frontend changes
- **Backend:** run `uv run python -m py_compile <changed_file>` for syntax checks
- Do not consider a task complete until the build is clean

### Dependency Management

We build for Docker — dependency files must always list packages **explicitly
with pinned minimum versions**. Never rely on transitive installs. If code
imports a package, that package must appear in the dependency file.

**IMPORTANT — two `pyproject.toml` files exist:**

- `pyproject.toml` (root) — used by `uv sync` during local development
- `backend/pyproject.toml` — used by `backend/Dockerfile` for Docker builds

When adding a Python dependency, **update both files**. The Docker build uses
only `backend/pyproject.toml` — a package missing there will crash on startup
even if local development works fine.

---

## LLM Test Harness

Located at `backend/llm_harness/`. A standalone tool for direct LLM calls against
Ollama Cloud — no DB, no auth, no event bus, no business logic.

**When to use:**

- **Debugging model behaviour** — when a model does not produce expected output
- **Prompt optimisation** — iterating on system prompts (memory consolidation, summarisation, etc.)
- **Interface testing** — verifying provider-specific parameters (thinking, temperature, tool calls)

When investigating LLM-related issues, **use the test harness first** before guessing at prompt changes.

**Quick reference:**

```bash
# Simple prompt
uv run python -m backend.llm_harness --model llama3.2 \
  --message '{"role":"user","content":"Hello"}'

# With system prompt and reasoning
uv run python -m backend.llm_harness --model deepseek-r1 \
  --system "You are helpful." --reasoning \
  --message '{"role":"user","content":"Explain X"}'

# Load a reproducible scenario from file
uv run python -m backend.llm_harness --from tests/llm_scenarios/simple_hello.json

# Multi-turn conversation
uv run python -m backend.llm_harness --model llama3.2 \
  --message '{"role":"user","content":"My name is Chris."}' \
  --message '{"role":"assistant","content":"Hello Chris!"}' \
  --message '{"role":"user","content":"What is my name?"}'
```

**API key:** stored in `.llm-test-key` (project root, gitignored, plain text).
Scenarios live in `tests/llm_scenarios/` as JSON files.

---

## Claude-Oriented Logging

The backend maintains structured logs designed to be useful for Claude Code during debugging.
These are not just human-readable logs — they are **machine-parseable context** for AI-assisted development.

When debugging issues:

- **Read the logs first** — check backend logs before making assumptions about what went wrong
- **Log entries include:** correlation IDs, module names, operation context, and timing
- When adding new functionality, ensure meaningful log lines are emitted at key decision points
- Log format should be structured (JSON or key=value) so it can be grepped and filtered effectively

---

## Scope Control

Do NOT add unrequested features or expand scope beyond what was asked for.
If you think something extra would be valuable, **ask first**.
Finish the current feature, commit, then discuss next steps.

---

## Repository Layout

```
chatsune/
  frontend/                  ← Vite + React + TSX + Tailwind
  backend/
    main.py                  ← single FastAPI entrypoint
    modules/
      user/                  ← auth, users, admin
        __init__.py          ← ONLY public API of this module
        _repository.py
        _handlers.py
        _models.py
      chat/                  ← sessions, history, MCP orchestration
        __init__.py
        _repository.py
        _handlers.py
      persona/               ← personas, memory, journal, consolidation, projects
        __init__.py
        _repository.py
        _handlers.py
      llm/                   ← Ollama adapter, embeddings
        __init__.py
        _client.py
      websearch/             ← pluggable web-search adapters
        __init__.py
        _registry.py
        _adapters/
          _base.py
          _ollama_cloud.py
      tools/                 ← tool registry, group toggling, executor dispatch
        __init__.py
        _registry.py
        _executors.py
    ws/
      manager.py             ← WebSocket connection manager
      router.py              ← WebSocket event routing
  shared/                    ← contracts shared across backend modules AND frontend
    dtos/
      auth.py
      chat.py
      persona.py
      websearch.py
      tools.py
      memory.py
      journal.py
    events/
      auth.py
      chat.py
      memory.py
      llm.py
      system.py
    topics.py                ← event type name constants
  docs/
    adr-001-stack.md
    adr-002-events.md
    adr-003-services.md
  docker-compose.yml
  CLAUDE.md                  ← this file
  README.md
```

---

## Hard Requirements

### 1. Module Boundaries — STRICTLY ENFORCED

Each module exposes exactly one public API via its `__init__.py`.
Internal files are prefixed with `_` and must **never** be imported from outside the module.

```python
# ✅ CORRECT
from backend.modules.user import UserService
from backend.modules.persona import PersonaService

# ❌ FORBIDDEN — never do this
from backend.modules.user._repository import UsersCollection
from backend.modules.persona._models import MemoryDocument
```

If you find yourself needing to import internals of another module, **STOP**.
This is a signal that either:

- The shared contract is missing something → add it to `shared/`
- The module boundary is wrong → think before changing

**Never work around this with a direct import.**

### 2. Shared Contracts — Single Source of Truth

All Pydantic models for events and DTOs live in `shared/`.
No module may define its own version of a DTO that crosses module boundaries.
No magic strings for event type names — use `shared/topics.py` constants.

```python
# ✅ CORRECT
from shared.events.memory import MemoryConsolidationStartedEvent
from shared.topics import Topics

await event_bus.publish(Topics.MEMORY_CONSOLIDATION_STARTED, event)

# ❌ FORBIDDEN
await event_bus.publish("memory.consolidation.started", {...})
```

### 3. Event-First — No Exceptions

Everything that happens in the backend must be visible to the relevant user in the frontend.
The frontend is a **view**, not a participant.

- Every state change publishes an event
- Events carry DTOs — the frontend never makes a follow-up REST call to learn what changed
- All events flow through one WebSocket connection per user session
- Errors are events too — see `shared/events/system.py` for `ErrorEvent`

### 4. No Cross-Module DB Access

Each module owns its own MongoDB collections.
No module may query another module's collections directly.
If module A needs data owned by module B, it calls module B's public API.

```python
# ✅ CORRECT — Chat module asks Persona module for persona data
persona = await persona_service.get_persona(persona_id)

# ❌ FORBIDDEN — Chat module queries Persona's collection directly
persona = await db["personas"].find_one({"_id": persona_id})
```

---

## Technology Stack

### Frontend

- **Vite + React + TypeScript (TSX)**
- **Tailwind CSS** for styling
- **pnpm** as package manager — never npm, never yarn

### Backend

- **Python + FastAPI** — async-first throughout
- **uv** as package manager — never pip, never poetry
- **Pydantic v2** for all models and validation
- Single FastAPI process — Modular Monolith, not microservices

### Database

- **MongoDB 7.0** with Single-Node Replica Set (RS0)
- RS0 is required for Vector Search and multi-document transactions
- RS0 is configured in Docker Compose — never reconfigure manually
- **MongoDB Vector Search** replaces Qdrant (Phase 1)

### Cache & Event Store

- **Redis** — session cache, JWT refresh tokens, Redis Streams
- Redis Streams provide event persistence and catchup on reconnect (24h TTL)

### LLM Inference

- Each user manages their own **Connections** — named instances of an adapter
  type, carrying URL, API key, `max_parallel`, and any other adapter-specific
  config. BYOK remains a first-class principle: each Connection carries its
  own encrypted credential; no admin-managed shared keys.
- Adapters live in `backend/modules/llm/_adapters/` and are registered in
  `ADAPTER_REGISTRY` in `backend/modules/llm/_registry.py`. In Phase 1 only
  `ollama_http` is implemented; it bundles Ollama Local, Ollama Cloud, and
  custom Ollama-compatible backends via adapter Templates.
- Adapters may expose an adapter-specific FastAPI sub-router, mounted under
  `/api/llm/connections/{id}/adapter/...`, for test / diagnostics / pairing
  endpoints. Ownership and resolution are handled by the LLM module's generic
  resolver dependency.
- Model unique ID format: `<connection_id>:<model_slug>` — see INSIGHTS.md
  INS-004 / INS-016.
- Abstracted behind `backend/modules/llm/` — never call any upstream provider
  directly from other modules.

---

## WebSocket Architecture

One WebSocket connection per authenticated user. All server-to-client communication
flows through this connection. The frontend maintains an event bus — components
subscribe to event types they care about.

### Event Envelope

```python
class BaseEvent(BaseModel):
    id: str                  # UUID
    type: str                # from Topics constants
    sequence: int            # monotonically increasing per scope
    scope: str               # e.g. "persona:abc123" or "session:xyz" or "global"
    correlation_id: str      # groups related events for one logical operation
    timestamp: datetime
    payload: dict
```

### Correlation IDs

All events from the same logical operation share a `correlation_id`:

```
correlation_id: "consolidation-run-abc"
  → memory.consolidation.started
  → memory.consolidation.entry_processed  { index: 1, total: 10 }
  → memory.consolidation.done
```

### Reconnect & Catchup

On reconnect, the frontend sends its last seen sequence number.
The backend replays missed events from Redis Streams.

### Error Events

```python
class ErrorEvent(BaseModel):
    type: Literal["error"]
    correlation_id: str
    error_code: str
    recoverable: bool        # true = show retry button; false = final error
    user_message: str        # shown in UI
    detail: str | None       # dev/logging only
```

---

## Authentication

- **Access Token:** 15 minutes, JWT, sent in WebSocket handshake header
- **Refresh Token:** 30 days, httpOnly cookie, never accessible to JavaScript
- Token expiry warning sent as event 2 minutes before expiry
- Token refresh happens over WebSocket — no reconnect needed
- Multiple concurrent sessions per user are supported

---

## Phase 1 Scope

Build only what validates the full stack end-to-end:

1. **User module** — login, refresh, user CRUD, master admin
2. **WebSocket infrastructure** — connection manager, event routing, Redis Streams
3. **Shared library** — all contracts, DTOs, events, topics

Chat, Persona, LLM — after the foundation is proven and stable.

---

## Naming Conventions

| Thing | Convention | Example |
|---|---|---|
| Module public API | PascalCase class | `UserService` |
| Module internal files | `_snake_case.py` | `_repository.py` |
| Event classes | PascalCase + Event suffix | `MemoryConsolidationDoneEvent` |
| DTO classes | PascalCase + Dto suffix | `ChatSessionSummaryDto` |
| Topic constants | `Topics.SCREAMING_SNAKE` | `Topics.MEMORY_CONSOLIDATION_DONE` |
| Frontend components | PascalCase | `ChatSessionList.tsx` |
| Frontend stores | camelCase + Store | `wsStore.ts` |

---

## Frontend styling gotchas

### Native `<select>` dropdowns

Browsers render the **open** dropdown list of a native `<select>` using
OS-native widgets. They ignore styles set on the `<select>` element itself
— `background`, `color`, Tailwind classes, nothing applies to the list
when it is open. The parent element only styles the closed state.

To get a dark dropdown list that matches the app theme, set `background`
and `color` **directly on each `<option>` element**:

```tsx
const OPTION_STYLE: React.CSSProperties = {
  background: '#0f0d16',         // surface colour
  color: 'rgba(255,255,255,0.85)',
}

<select ...>
  <option value="" style={OPTION_STYLE}>No fallback</option>
  {items.map((x) => (
    <option key={x.id} value={x.id} style={OPTION_STYLE}>{x.label}</option>
  ))}
</select>
```

Honoured by Chrome, Firefox, and Safari. Symptom when you forget it: the
open dropdown list is light grey on white while the closed select looks
correct. This is a recurring mistake — always the same fix.

---

## What NOT to Do

These are lessons from Prototype 2:

- **Never** add a feature before the contract (event/DTO) is defined in `shared/`
- **Never** call Ollama from anywhere except `backend/modules/llm/`
- **Never** use `any` in TypeScript — define the type or use a shared contract
- **Never** poll for state — if you think you need polling, you need an event instead
- **Never** expand scope mid-session — finish the current feature, commit, then discuss next
- **Never** bypass module boundaries "just this once" — it is always permanent
- **Never** reach into another module's adapter sub-router. The sub-router is
  mounted under `/api/llm/connections/{id}/adapter/` and resolution/auth is
  handled by the LLM module's generic resolver dependency. If your code needs
  something the LLM module doesn't currently expose, add it to the LLM
  module's public API — do not import adapter internals from outside
  `backend/modules/llm/`.

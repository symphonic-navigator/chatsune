# Design Spec: Persona Module & LLM Adapter Architecture

**Date:** 2026-04-03  
**Status:** Approved  
**Scope:** Phase 1 extension — Persona CRUD + LLM adapter scaffolding

---

## Context

This spec covers two closely related additions to the Chatsune backend:

1. **Persona module** — allows users to create and manage AI personas (name, system prompt, model assignment, etc.)
2. **LLM module** — scaffolds the adapter architecture for upstream inference providers, starting with Ollama Cloud as the first concrete adapter (implemented as stubs in this iteration)

Both areas require new shared contracts (DTOs, events, topics) and follow the existing Modular Monolith conventions.

---

## Core Principles (reiterated for this spec)

- Every state change publishes a WebSocket event carrying the full DTO — no follow-up REST calls
- API keys are **per-user** (BYOK — Bring Your Own Key); no shared/admin keys
- Module boundaries are strictly enforced; `shared/` is the single source of truth for contracts
- The Ollama Cloud adapter is scaffolded (stubs) in this iteration; full integration is deferred

---

## Part 1 — Persona Module

### Data Model

MongoDB collection: `personas`

```python
# backend/modules/persona/_models.py
class PersonaDocument(BaseModel):
    id: str                       # UUID, _id in MongoDB
    user_id: str                  # owning user
    name: str
    tagline: str
    model_unique_id: str          # format: "provider_id:model_slug"
    system_prompt: str
    temperature: float            # 0.0–2.0, default 0.8
    reasoning_enabled: bool       # default False
    colour_scheme: str            # hex string or named colour, default ""
    display_order: int            # default 0
    created_at: datetime
    updated_at: datetime
```

`PinnedKnowledgeItems` is explicitly excluded from Phase 1. It will return when the knowledge base is implemented.

### Shared Contracts

**DTOs** (`shared/dtos/persona.py`):

```python
class PersonaDto(BaseModel):
    id: str
    user_id: str
    name: str
    tagline: str
    model_unique_id: str
    system_prompt: str
    temperature: float
    reasoning_enabled: bool
    colour_scheme: str
    display_order: int
    created_at: datetime
    updated_at: datetime

class CreatePersonaDto(BaseModel):
    name: str
    tagline: str
    model_unique_id: str
    system_prompt: str
    temperature: float = 0.8
    reasoning_enabled: bool = False
    colour_scheme: str = ""
    display_order: int = 0

class UpdatePersonaDto(BaseModel):
    name: str | None = None
    tagline: str | None = None
    model_unique_id: str | None = None
    system_prompt: str | None = None
    temperature: float | None = None
    reasoning_enabled: bool | None = None
    colour_scheme: str | None = None
    display_order: int | None = None
```

**Events** (`shared/events/persona.py`):

```python
class PersonaCreatedEvent(BaseEvent): ...   # payload: PersonaDto
class PersonaUpdatedEvent(BaseEvent): ...   # payload: PersonaDto (full, after update)
class PersonaDeletedEvent(BaseEvent): ...   # payload: {"id": str}
```

Scope: `persona:{persona_id}` for created/updated/deleted.

**Topics** (added to `shared/topics.py`):

```python
PERSONA_CREATED = "persona.created"
PERSONA_UPDATED = "persona.updated"
PERSONA_DELETED = "persona.deleted"
```

### REST API

All endpoints require authentication. Users can only access their own personas. No admin cross-user access in Phase 1.

```
GET    /api/personas              → list own personas, ordered by display_order
POST   /api/personas              → create persona → publishes PersonaCreatedEvent
GET    /api/personas/{id}         → get single persona (own only)
PUT    /api/personas/{id}         → full update → publishes PersonaUpdatedEvent
PATCH  /api/personas/{id}         → partial update → publishes PersonaUpdatedEvent
DELETE /api/personas/{id}         → delete → publishes PersonaDeletedEvent
```

Validation on create/update: `model_unique_id` must parse as `provider_id:model_slug`
and `provider_id` must exist in `ADAPTER_REGISTRY`.

### Module Structure

```
backend/modules/persona/
  __init__.py      ← PersonaService (public API)
  _models.py       ← PersonaDocument (MongoDB document shape)
  _repository.py   ← CRUD against MongoDB personas collection
  _handlers.py     ← FastAPI router, registered in main.py
```

---

## Part 2 — LLM Module

### Adapter Registry

Adapters are registered at startup in a plain dictionary. The key is the `provider_id` used in `model_unique_id`.

```python
# backend/modules/llm/_registry.py
ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = {
    "ollama_cloud": OllamaCloudAdapter,
}
```

No auto-discovery. Adding a new provider = implement `BaseAdapter`, add one line here.

### Model Unique ID Format

```
<provider_id>:<model_slug>
```

Examples: `ollama_cloud:llama3.2`, `ollama_cloud:qwen2.5-coder:32b`

Parsing: split on the **first** `:` only. The remainder is the model slug and is passed as-is to the adapter. See INSIGHTS.md INS-004.

### Abstract Base Adapter

```python
# backend/modules/llm/_adapters/_base.py
class BaseAdapter(ABC):

    @abstractmethod
    async def validate_key(self, api_key: str) -> bool:
        """Return True if the key is valid for this provider."""
        ...

    @abstractmethod
    async def fetch_models(self) -> list[ModelMetaDto]:
        """Fetch all available models with their capabilities."""
        ...
```

Full inference methods (`complete`, `stream`, etc.) are defined in a later iteration.

### Ollama Cloud Adapter (Stub)

```python
# backend/modules/llm/_adapters/_ollama_cloud.py
class OllamaCloudAdapter(BaseAdapter):

    async def validate_key(self, api_key: str) -> bool:
        raise NotImplementedError("OllamaCloudAdapter.validate_key not yet implemented")

    async def fetch_models(self) -> list[ModelMetaDto]:
        raise NotImplementedError("OllamaCloudAdapter.fetch_models not yet implemented")
```

### User Credentials

MongoDB collection: `llm_user_credentials`  
Keyed by `(user_id, provider_id)` — one key per user per provider.

```python
# backend/modules/llm/_models.py
class UserCredentialDocument(BaseModel):
    id: str
    user_id: str
    provider_id: str              # must exist in ADAPTER_REGISTRY
    api_key_encrypted: str        # encrypted at rest; never returned via API
    created_at: datetime
    updated_at: datetime
```

The raw `api_key` is **never** returned via the API. Only `is_configured: bool` is exposed.

**Shared Contracts** (`shared/dtos/llm.py`):

```python
class ProviderCredentialDto(BaseModel):
    provider_id: str
    display_name: str             # human-readable, e.g. "Ollama Cloud"
    is_configured: bool
    created_at: datetime | None

class SetProviderKeyDto(BaseModel):
    api_key: str

class ModelMetaDto(BaseModel):
    provider_id: str
    model_id: str                 # e.g. "llama3.2"
    display_name: str
    context_window: int
    supports_reasoning: bool
    supports_vision: bool
    supports_tool_calls: bool
```

**Events** (`shared/events/llm.py`):

```python
class LlmCredentialSetEvent(BaseEvent): ...     # payload: ProviderCredentialDto
class LlmCredentialRemovedEvent(BaseEvent): ... # payload: {"provider_id": str}
class LlmCredentialTestedEvent(BaseEvent): ...  # payload: {"provider_id": str, "valid": bool}
```

**Topics** (added to `shared/topics.py`):

```python
LLM_CREDENTIAL_SET     = "llm.credential.set"
LLM_CREDENTIAL_REMOVED = "llm.credential.removed"
LLM_CREDENTIAL_TESTED  = "llm.credential.tested"
```

### Model Metadata Cache

Stored in Redis. Key: `llm:models:{provider_id}`. TTL: 30 minutes.  
Fetched lazily on cache miss — no background cron job.  
No WebSocket event for model list updates (reference data, not user state).  
See INSIGHTS.md INS-001 for the full reasoning.

### REST API

```
GET    /api/llm/providers                        → list all registered providers + is_configured per user
PUT    /api/llm/providers/{provider_id}/key      → set/overwrite API key → publishes LlmCredentialSetEvent
DELETE /api/llm/providers/{provider_id}/key      → remove API key → publishes LlmCredentialRemovedEvent
POST   /api/llm/providers/{provider_id}/test     → validate key without storing → publishes LlmCredentialTestedEvent
GET    /api/llm/providers/{provider_id}/models   → available models (from Redis cache, lazy-fetched)
```

The `/test` endpoint accepts `{"api_key": str}` in the request body. It calls `adapter.validate_key()` and publishes `LlmCredentialTestedEvent` with `valid: true/false`. It never stores the key.

### Module Structure

```
backend/modules/llm/
  __init__.py          ← LlmService (public API)
  _registry.py         ← ADAPTER_REGISTRY dict
  _credentials.py      ← UserCredential repository (MongoDB)
  _metadata.py         ← model metadata cache (Redis, lazy load)
  _models.py           ← MongoDB document models
  _handlers.py         ← FastAPI router
  _adapters/
    __init__.py        ← empty, makes it a package
    _base.py           ← abstract BaseAdapter
    _ollama_cloud.py   ← OllamaCloudAdapter (stubs only)
```

---

## Shared Contracts Summary

| File | New additions |
|---|---|
| `shared/dtos/persona.py` | `PersonaDto`, `CreatePersonaDto`, `UpdatePersonaDto` |
| `shared/dtos/llm.py` | `ProviderCredentialDto`, `SetProviderKeyDto`, `ModelMetaDto` |
| `shared/events/persona.py` | `PersonaCreatedEvent`, `PersonaUpdatedEvent`, `PersonaDeletedEvent` |
| `shared/events/llm.py` | `LlmCredentialSetEvent`, `LlmCredentialRemovedEvent`, `LlmCredentialTestedEvent` |
| `shared/topics.py` | 6 new topic constants |

---

## Out of Scope (this iteration)

- Persona cloning / sharing
- Admin cross-user persona management
- Full Ollama Cloud adapter implementation (HTTP calls, streaming)
- Model metadata background refresh
- Persona memory, journal, projects
- Any chat/LLM inference wiring

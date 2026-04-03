# Model Metadata, Key Validation & Curation

**Date:** 2026-04-03
**Status:** Approved
**Scope:** Backend only (LLM module + shared contracts)

---

## Summary

Extend the LLM module with:

1. An enriched model metadata format including parameter count and quantisation level
2. A working OllamaCloudAdapter (`validate_key` via `/api/me`, `fetch_models` via `/api/tags` + `/api/show`)
3. A persistent model curation system (admin-managed, stored in MongoDB)
4. Event-based propagation so curation changes reach all connected users instantly

---

## Data Architecture

### Two Storage Layers

**Provider model data** is ephemeral and lives in Redis:

- Cache key: `llm:models:{provider_id}`
- TTL: 30 minutes, lazy loaded on cache miss (INS-001)
- Contains: model_id, display_name, context_window, capabilities, and the new optional fields `parameter_count` and `quantisation_level`

**Model curation** is persistent and lives in MongoDB (collection: `llm_model_curations`):

- Composite key: `provider_id` + `model_slug`
- Fields: `overall_rating`, `hidden`, `admin_description`, `last_curated_at`, `last_curated_by`
- Never overwritten by provider reload

When models are delivered to clients, both layers are merged into a single DTO.

### Why Two Layers

Provider data is volatile — models appear, disappear, change specs. Curation is an admin decision that must survive cache flushes and provider outages. Storing them together (as Prototype 2 did with a nested `Curation` field on the model document) couples the lifecycle of admin decisions to upstream sync. Separating them means curation persists even if a model temporarily vanishes from the provider and reappears later.

---

## Shared Contracts

### Extended ModelMetaDto

```python
class ModelMetaDto(BaseModel):
    provider_id: str
    model_id: str
    display_name: str
    context_window: int
    supports_reasoning: bool
    supports_vision: bool
    supports_tool_calls: bool
    parameter_count: str | None = None       # e.g. "675B", "8B"
    quantisation_level: str | None = None    # e.g. "FP8", "Q4_K_M"
    curation: ModelCurationDto | None = None

    @computed_field
    @property
    def unique_id(self) -> str:
        return f"{self.provider_id}:{self.model_id}"
```

### New DTOs

```python
class ModelRating(str, Enum):
    AVAILABLE = "available"
    RECOMMENDED = "recommended"
    NOT_RECOMMENDED = "not_recommended"

class ModelCurationDto(BaseModel):
    overall_rating: ModelRating = ModelRating.AVAILABLE
    hidden: bool = False
    admin_description: str | None = None
    last_curated_at: datetime | None = None
    last_curated_by: str | None = None

class SetModelCurationDto(BaseModel):
    overall_rating: ModelRating = ModelRating.AVAILABLE
    hidden: bool = False
    admin_description: str | None = None
```

### New Events

```python
class LlmModelCuratedEvent(BaseModel):
    """Carries the full updated model DTO so clients can update in place."""
    type: str = "llm.model.curated"
    provider_id: str
    model_slug: str
    model: ModelMetaDto       # complete merged model with curation
    curated_by: str
    timestamp: datetime

class LlmModelsRefreshedEvent(BaseModel):
    """Trigger-only: tells clients to re-fetch the model list."""
    type: str = "llm.models.refreshed"
    provider_id: str
    timestamp: datetime
```

### New Topics

```python
LLM_MODEL_CURATED = "llm.model.curated"
LLM_MODELS_REFRESHED = "llm.models.refreshed"
```

---

## Event Flow

### Curation events (carry data)

When an admin curates a model, the `LLM_MODEL_CURATED` event is broadcast to all connected users. The event payload contains the full merged `ModelMetaDto` so the frontend can update its store in place without an additional fetch.

### Provider reload events (trigger only)

When a model cache expires and is re-fetched from the provider, the `LLM_MODELS_REFRESHED` event is broadcast to all connected users. The event contains only the `provider_id` — the frontend should treat this as a signal to re-fetch the model list.

**Frontend implication (for later):** These two event types require different handling. `model_curated` means "here are the new data, update your store directly". `models_refreshed` means "your model list is stale, please re-fetch".

### Existing events (unchanged)

`LLM_CREDENTIAL_SET`, `LLM_CREDENTIAL_REMOVED`, `LLM_CREDENTIAL_TESTED` remain user-scoped and unchanged.

---

## OllamaCloudAdapter Implementation

### validate_key

`GET {base_url}/api/me` with `Authorization: Bearer {api_key}`. Returns `True` on HTTP 200, `False` on 401/403, raises on other errors.

### fetch_models

1. `GET {base_url}/api/tags` — returns list of available model names
2. For each model: `POST {base_url}/api/show` with `{"model": name}` — returns details

Extraction from `/api/show` response:

| Field | Source |
|---|---|
| `display_name` | Built from model name (title-case, tag as suffix) |
| `context_window` | `model_info["*.context_length"]` (find key ending in `.context_length`) |
| `supports_tool_calls` | `"tools" in capabilities` |
| `supports_vision` | `"vision" in capabilities` |
| `supports_reasoning` | `"thinking" in capabilities` |
| `parameter_count` | `details.parameter_size` or `model_info["general.parameter_count"]`, formatted as human-readable (e.g. `675000000000` becomes `"675B"`) |
| `quantisation_level` | `details.quantization_level` (e.g. `"FP8"`, `"Q4_K_M"`) |

### Parameter count formatting

Convert raw integer to human-readable short form:

- `>= 1_000_000_000_000` — format as `"{n}T"` (trillion)
- `>= 1_000_000_000` — format as `"{n}B"` (billion)
- `>= 1_000_000` — format as `"{n}M"` (million)

Use one decimal place when not a round number (e.g. `7_000_000_000` becomes `"7B"`, `7_500_000_000` becomes `"7.5B"`).

---

## Curation Repository

### MongoDB Document

```python
class ModelCurationDocument(BaseModel):
    id: str                    # generated UUID
    provider_id: str
    model_slug: str
    overall_rating: str        # ModelRating enum value
    hidden: bool
    admin_description: str | None
    last_curated_at: datetime
    last_curated_by: str
```

Collection: `llm_model_curations`
Unique index: `(provider_id, model_slug)`

### Operations

- `upsert(provider_id, model_slug, dto, admin_user_id)` — create or update curation
- `delete(provider_id, model_slug)` — remove curation (model reverts to uncurated)
- `find(provider_id, model_slug)` — get single curation
- `list_for_provider(provider_id)` — get all curations for a provider (used during merge)

---

## API Endpoints

### Existing (unchanged)

- `GET /api/llm/providers` — list providers with configuration status
- `PUT /api/llm/providers/{provider_id}/key` — set API key
- `DELETE /api/llm/providers/{provider_id}/key` — remove API key
- `POST /api/llm/providers/{provider_id}/test` — test API key (calls `validate_key`)

### Modified

- `GET /api/llm/providers/{provider_id}/models` — now returns merged data (provider metadata + curation). Publishes `LLM_MODELS_REFRESHED` event when cache is refreshed.

### New (admin only)

- `PUT /api/llm/providers/{provider_id}/models/{model_slug}/curation` — set or update curation. Body: `SetModelCurationDto`. Publishes `LLM_MODEL_CURATED` event.
- `DELETE /api/llm/providers/{provider_id}/models/{model_slug}/curation` — remove curation. Publishes `LLM_MODEL_CURATED` event (with curation set to None).

---

## Files Affected

### New

| File | Purpose |
|---|---|
| `backend/modules/llm/_curation.py` | CurationRepository (MongoDB CRUD) |

### Modified

| File | Change |
|---|---|
| `shared/dtos/llm.py` | Add `ModelCurationDto`, `SetModelCurationDto`, `ModelRating` enum; extend `ModelMetaDto` with `parameter_count`, `quantisation_level`, `curation` |
| `shared/events/llm.py` | Add `LlmModelCuratedEvent`, `LlmModelsRefreshedEvent` |
| `shared/topics.py` | Add `LLM_MODEL_CURATED`, `LLM_MODELS_REFRESHED` |
| `backend/modules/llm/_adapters/_base.py` | Ensure `fetch_models` return type accommodates new optional fields |
| `backend/modules/llm/_adapters/_ollama_cloud.py` | Implement `validate_key` and `fetch_models` |
| `backend/modules/llm/_handlers.py` | Add curation endpoints, merge logic in model listing, publish new events |
| `backend/modules/llm/_metadata.py` | Publish `LLM_MODELS_REFRESHED` event on cache refresh |
| `backend/modules/llm/_models.py` | Add `ModelCurationDocument` |
| `backend/modules/llm/__init__.py` | Export new public API surface |
| `backend/ws/event_bus.py` | Add fanout rules for `LLM_MODEL_CURATED` (broadcast) and `LLM_MODELS_REFRESHED` (broadcast) |

---

## Testing

### Unit tests

- Parameter count formatting (edge cases: exact billions, fractional, zero, None)
- Curation merge logic (model with curation, without curation, hidden model filtering)
- ModelRating enum serialisation

### Integration tests

- OllamaCloudAdapter `validate_key` (mock `/api/me` — 200, 401)
- OllamaCloudAdapter `fetch_models` (mock `/api/tags` + `/api/show` with full detail response including parameter_size and quantization_level)
- Curation CRUD endpoints (set, update, delete, verify admin-only)
- Model listing returns merged data
- Event publication on curation change and model refresh

---

## Out of Scope

- Spider dimension scores (deferred to later iteration)
- Periodic key validation (user tests manually via button)
- Frontend implementation (separate spec)
- Chat streaming via OllamaCloudAdapter (already exists, not touched here)

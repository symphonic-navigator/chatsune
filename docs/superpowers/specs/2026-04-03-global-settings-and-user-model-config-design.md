# Global Settings & User Model Config

**Date:** 2026-04-03
**Status:** Draft

---

## Overview

Two new features that together complete the configuration layer before frontend work begins:

1. **Global Settings** — admin-managed key-value store for platform-wide configuration (starting with the global system prompt)
2. **User Model Config** — per-user, per-model preferences (favourites, hidden, notes, system prompt additions)

Both feed into the system prompt hierarchy that will govern chat behaviour.

---

## Feature A: Global Settings Module

### Module Location

New module: `backend/modules/settings/`

### Files

| File | Purpose |
|------|---------|
| `__init__.py` | Public API: `SettingsRepository`, `router`, `init_indexes()` |
| `_models.py` | `AppSettingDocument` |
| `_repository.py` | `SettingsRepository` — CRUD on `app_settings` collection |
| `_handlers.py` | REST endpoints (admin-only) |

### Data Model

**MongoDB Collection:** `app_settings`

```python
class AppSettingDocument(BaseModel):
    key: str              # primary key, e.g. "global_system_prompt"
    value: str            # free-form string value
    updated_at: datetime
    updated_by: str       # user_id of the admin who set it
```

**Index:** Unique on `key`.

### REST Endpoints

All endpoints require `admin` or `master_admin` role.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/settings` | List all settings |
| `GET` | `/api/settings/{key}` | Get single setting |
| `PUT` | `/api/settings/{key}` | Create or update a setting |
| `DELETE` | `/api/settings/{key}` | Remove a setting |

### Shared Contracts

**`shared/dtos/settings.py`:**
- `AppSettingDto` — key, value, updated_at, updated_by
- `SetSettingDto` — value (request body for PUT)

**`shared/events/settings.py`:**
- `SettingUpdatedEvent` — key, value, updated_by
- `SettingDeletedEvent` — key, deleted_by

**`shared/topics.py` additions:**
- `SETTING_UPDATED = "setting.updated"`
- `SETTING_DELETED = "setting.deleted"`

### Event Scope

`global` — settings affect all users. Events are delivered to connected admin sessions.

---

## Feature B: User Model Config (LLM Module Extension)

### Module Location

Extension of existing `backend/modules/llm/`.

### New/Modified Files

| File | Change |
|------|--------|
| `_user_config.py` | **New** — `UserModelConfigRepository` |
| `_models.py` | **Modified** — add `UserModelConfigDocument` |
| `_handlers.py` | **Modified** — add user model config endpoints |
| `__init__.py` | **Modified** — export `UserModelConfigRepository` |

### Data Model

**MongoDB Collection:** `llm_user_model_configs`

```python
class UserModelConfigDocument(BaseModel):
    id: str                         # UUID
    user_id: str
    model_unique_id: str            # e.g. "ollama_cloud:llama3.2"
    is_favourite: bool = False
    is_hidden: bool = False
    notes: str | None = None
    system_prompt_addition: str | None = None
    created_at: datetime
    updated_at: datetime
```

**Index:** Unique on `(user_id, model_unique_id)`.

**Defaults (when no document exists):**
- `is_favourite`: `False`
- `is_hidden`: `False`
- `notes`: `None`
- `system_prompt_addition`: `None`

The API returns a DTO with these defaults when no document exists — never a 404.

### REST Endpoints

All endpoints are user-scoped (user_id from JWT).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/llm/user-model-configs` | List all configs for the authenticated user |
| `GET` | `/api/llm/providers/{provider_id}/models/{model_slug:path}/user-config` | Get config (returns defaults if none exists) |
| `PUT` | `/api/llm/providers/{provider_id}/models/{model_slug:path}/user-config` | Create or update config |
| `DELETE` | `/api/llm/providers/{provider_id}/models/{model_slug:path}/user-config` | Remove config (resets to defaults) |

This matches the existing curation endpoint pattern (`/providers/{provider_id}/models/{model_slug:path}/curation`) and avoids URL-encoding issues with the `:` in `model_unique_id`. The `model_unique_id` is reconstructed as `f"{provider_id}:{model_slug}"` in the handler.

### Shared Contracts

**`shared/dtos/llm.py` additions:**
- `UserModelConfigDto` — model_unique_id, is_favourite, is_hidden, notes, system_prompt_addition
- `SetUserModelConfigDto` — is_favourite, is_hidden, notes, system_prompt_addition (all optional)

**`shared/events/llm.py` additions:**
- `LlmUserModelConfigUpdatedEvent` — model_unique_id, config (full `UserModelConfigDto`)

**`shared/topics.py` additions:**
- `LLM_USER_MODEL_CONFIG_UPDATED = "llm.user_model_config.updated"`

### Event Design: Defaults Over Delete

There is no separate "deleted" event. The DELETE endpoint emits `LLM_USER_MODEL_CONFIG_UPDATED` with default values as payload. The frontend handles a single event type — "deleted" and "reset to defaults" are semantically identical from the client's perspective.

### Event Scope

`user:{user_id}` — only the affected user receives the event.

---

## System Prompt Hierarchy

Defined now for future implementation in the chat module. Three layers, concatenated in order (first = strongest weight):

| Priority | Source | Scope | Description |
|----------|--------|-------|-------------|
| 1 (highest) | Global System Prompt | Platform-wide | Admin guardrails (e.g. "be harmless") |
| 2 | User Model Config Addition | Per user, per model | Community-sourced model tweaks |
| 3 | Persona System Prompt | Per persona | Character, behaviour, context |

This is a differentiating feature: users can encode community knowledge about model-specific quirks (e.g. "tell Mistral to focus on the last message") directly into their config.

---

## INSIGHTS.md Entries

### INS-006: Three-Layer Model Data

Extension of INS-005. Model data now has three layers:

1. **Provider metadata** (Redis, ephemeral, 30min TTL) — what the model *is*
2. **Admin curation** (MongoDB, persistent) — how the admin *rates* the model
3. **User config** (MongoDB, persistent, per-user) — how the user *uses* the model

Merged at read time. Each layer has its own event type.

### INS-007: System Prompt Hierarchy

The system prompt for a chat session is assembled from three sources in priority order: global system prompt (admin guardrails), user model config addition (model-specific tweaks), persona system prompt (character/behaviour). Concatenated, not merged — each layer is a distinct block.

---

## Out of Scope

- Chat module integration (consuming the system prompt hierarchy)
- Frontend UI for settings or user model config
- Pre-seeding settings on first boot
- Validation of specific setting keys (handler-level concern, not contract-level)

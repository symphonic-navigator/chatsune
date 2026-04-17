# Model Refresh & Persona Clone — Design

**Date:** 2026-04-15
**Scope:** Three independent, small features bundled together because they share no plumbing but are naturally co-developed.

---

## 1. Motivation

1. **Per-provider model refresh.** With runpod.io, local Ollama and Ollama Cloud, users now control models from outside Chatsune. They need a way to re-sync a specific Connection's model list on demand without reloading the page.
2. **Auto-refresh after pull / delete.** When a user pulls a model in `OllamaModelsPanel`, the intent is to *use* it immediately. Today, the Enriched-Models store that backs the Picker and the User-Models page does not learn about the new model until a manual refresh. Symmetrically, deleting a model should remove it from the Picker.
3. **Persona cloning.** Creating a variation of an existing persona (same system prompt and model settings, different personality tweaks) currently requires manual re-entry of every field.

---

## 2. Feature 1 — Per-Provider Refresh Button

### Backend

No changes. The endpoint already exists:

- `POST /api/llm/connections/{connection_id}/refresh` — `backend/modules/llm/_handlers.py:245`
- Calls `refresh_connection_models()` (`_metadata.py:50`)
- Emits `LLM_CONNECTION_MODELS_REFRESHED` event
- Returns 502 on upstream failure, 200 on success

### Frontend

**`ModelBrowser.tsx`** — modify the `ConnectionGroup` header (currently lines 209–238) to include an inline refresh button "⟳" to the right of the connection slug.

- Clicking invokes `llmApi.refreshConnectionModels(connectionId)`.
- During the request: button disabled, spinner icon.
- On success: no additional UI — the `LLM_CONNECTION_MODELS_REFRESHED` event already triggers the store refresh.
- On error (502 or network): show a dezent red inline hint next to the button for ~5s with the error message.

Because both `ModelSelectionModal` (Picker) and `UserModal/ModelsTab` (user-facing model management) render `ModelBrowser`, both locations get the button automatically.

**`useEnrichedModels`** — verify the hook already subscribes to `LLM_CONNECTION_MODELS_REFRESHED` and refetches the Enriched-Models store. Add the subscription if missing.

**`llmApi`** — add the client method if not present:

```ts
refreshConnectionModels(connectionId: string): Promise<void>
  // POST /api/llm/connections/{connectionId}/refresh
```

### Acceptance

- Clicking the refresh button on a ConnectionGroup re-queries the upstream, updates the backend metadata cache, and refreshes the list in all open Model Browsers without a page reload.
- An upstream error shows a dezent inline hint; the rest of the UI stays usable.

---

## 3. Feature 2 — Auto-Refresh After Pull / Delete

### Backend

Modify `backend/modules/llm/_ollama_model_ops.py`:

**`_finalise_success()`** (lines 207–230) — after publishing `LLM_MODEL_PULL_COMPLETED`:

1. Resolve the Connection for the scope (already available to the task runner).
2. Call `refresh_connection_models(connection, adapter_cls, redis)`.
3. Publish `LLM_CONNECTION_MODELS_REFRESHED` targeting the owning user.
4. Wrap steps 2–3 in a try/except that logs-and-swallows — the pull itself succeeded, so a refresh failure must not produce a `pull.failed` event.

**`delete()`** (line 248 onward) — after successful delete:

1. Same three-step sequence: `refresh_connection_models` → `LLM_CONNECTION_MODELS_REFRESHED` → swallow refresh errors.

### Frontend

No changes — the handler added in Feature 1 covers both cases.

### Acceptance

- Pulling a model via `OllamaModelsPanel` causes the new model to appear in Picker and User-Models page without manual refresh.
- Deleting a model via `OllamaModelsPanel` causes the model to disappear from Picker and User-Models page without manual refresh.
- If the post-pull refresh fails, the `pull.completed` event is still delivered and the user sees the pull as successful; only a warning is logged.

---

## 4. Feature 3 — Persona Cloning

### User Flow

1. User opens a persona's overlay, lands on the **Overview** tab.
2. Clicks the **Clone** button.
3. Dialog opens with:
   - Name field — pre-filled `"<Original.name> Clone"`, auto-focused.
   - Checkbox **"Memories mitklonen"** — off by default, short hint: *"Journal und konsolidierte Memories aus der Original-Persona übernehmen. History wird nie geklont."*
   - Buttons: **Abbrechen** (left) / **Klonen** (right, primary).
4. On submit: backend creates the new persona, event flows back, sidebar shows the clone, overlay closes or navigates to the new persona.

### What Gets Cloned

| Field | Cloned? | Notes |
|---|---|---|
| `name` | Custom | from dialog input, server falls back to `"<Original> Clone"` if blank |
| `tagline` | 1:1 | |
| `system_prompt` | 1:1 | |
| `model_unique_id` | 1:1 | |
| `temperature` | 1:1 | |
| `reasoning_enabled` | 1:1 | |
| `soft_cot_enabled` | 1:1 | |
| `vision_fallback_model` | 1:1 | |
| `nsfw` | 1:1 | |
| `colour_scheme` | 1:1 | |
| `profile_crop` | 1:1 | |
| `profile_image` | Copy | avatar file duplicated in `AvatarStore` with a new filename |
| `mcp_config` | 1:1 | |
| `integrations_config` | 1:1 | |
| `voice_config` | 1:1 | |
| `knowledge_library_ids` | 1:1 | **Only the reference list is copied.** KB entities are n:m and never duplicated. |
| `monogram` | Regenerated | collision-free for the new name, same helper as `_import.py:278` |
| `display_order` | New | appended at the end |
| `pinned` | `false` | |
| `id`, `created_at`, `updated_at` | New | |
| Memory (Journal + Memory-Bodies) | Optional | all-or-nothing; only if `clone_memory=true` |
| Sessions / History | Never | |
| Artefacts | Never | bound to sessions |
| Storage blobs | Never | bound to artefacts / KB entities (which are not cloned) |

### Backend

**New endpoint** — `POST /api/personas/{persona_id}/clone`

Request body:

```json
{
  "name": "optional string",
  "clone_memory": false
}
```

Response: `PersonaDto` for the newly created persona (same shape as `POST /api/personas`).

**New module file** — `backend/modules/persona/_clone.py` — orchestrates the clone. Mirrors the structure of `_import.py`:

1. Load source persona; 404 if missing or not owned by caller.
2. Resolve final name: body `name` stripped; if empty → `f"{source.name} Clone"`.
3. Generate monogram via existing helper, collision-checked against user's existing monograms.
4. Insert new `PersonaDocument` via `PersonaRepository.create()` with cloned technical fields (see table above). `knowledge_library_ids` copied via a follow-up update (repository already exposes this on import path).
5. If `source.profile_image` is set: copy the file via `AvatarStore.duplicate(source_filename) -> new_filename`, then `update_profile_image`.
6. If `clone_memory=true`: call `memory.bulk_export_for_persona(user_id, source_id)` → `memory.bulk_import_for_persona(user_id, new_id, bundle)`. Both APIs already exist for the Export/Import feature.
7. Fetch the fresh doc, convert via `PersonaRepository.to_dto`, publish `PersonaCreatedEvent`.
8. Rollback on any post-insert failure: `cascade_delete_persona(user_id, new_id)`, then re-raise as `HTTPException(400)` (same pattern as `_import.py:405`).
9. Return the DTO.

**Public API** — add `clone_persona(user_id, source_id, name, clone_memory) -> PersonaDto` to `backend/modules/persona/__init__.py` for symmetry; the handler thins to input validation + delegation.

**`AvatarStore`** — add a `duplicate(existing_filename: str) -> str` method that copies the blob and returns the new filename. Keeps avatar file handling inside the persona module.

**Event** — reuse the existing `PersonaCreatedEvent` (Topics.PERSONA_CREATED). No new topic is required — a clone is a persona creation from the frontend's perspective.

### Frontend

**`OverviewTab.tsx`** — already hosts the Delete button (`onDelete` prop, used at line ~92). Extend the existing actions area with:

- **Clone** (new) — opens `PersonaCloneDialog`.
- **Export** (moved from `EditTab`) — opens the existing `ExportPersonaModal`.
- **Delete** — already here; keep in place.

Visual grouping / ordering to match the existing tab style — concrete placement decided during implementation, constrained only to the OverviewTab.

**`EditTab.tsx`** — remove the Export button, its state (`exportOpen`, `exporting`), `handleExport`, and the `ExportPersonaModal` render. Clean up the unused import.

**New component — `PersonaCloneDialog.tsx`** (in `frontend/src/app/components/persona-overlay/`):

- Built with the existing `Sheet` / modal primitives.
- State: `name` (default `"<source.name> Clone"`), `cloneMemory` (default `false`), `submitting`, `error`.
- Submit → `personasApi.clonePersona(sourceId, { name, clone_memory })`.
- On success: close dialog; trust `PersonaCreatedEvent` to update the sidebar. Optionally navigate to the new persona via the existing selected-persona mechanism.
- On failure: inline error, dialog stays open.
- Enter in the name field submits; Escape cancels.

**`personasApi`** — add:

```ts
clonePersona(
  sourceId: string,
  body: { name: string; clone_memory: boolean },
): Promise<PersonaDto>
```

### Acceptance

- Overview tab shows Clone, Export, Delete buttons; Export no longer appears on Edit tab.
- Clone dialog pre-fills `"<Original> Clone"` as the name, has an off-by-default Memories toggle, and can be cancelled.
- Clone without Memories: new persona has identical config, its own avatar file on disk, references the same KB libraries, has zero sessions/history/memories.
- Clone with Memories: additionally carries Journal entries and Memory-Bodies from the source.
- Backend rolls back cleanly on partial failure — no zombie personas.
- `PersonaCreatedEvent` fires with the new persona's full DTO.

---

## 5. Out of Scope

- Cloning across users (admin-style). Always same owner.
- Cloning of sessions, history, artefacts, storage blobs.
- Duplicating KB libraries.
- Scheduled / bulk clone operations.
- Bulk refresh of all Connections with one click. (Per-Connection is explicit and intentional.)

---

## 6. Implementation Order

1. Feature 2 backend first (smallest blast radius, reuses existing refresh endpoint) — catches any integration surprises early.
2. Feature 1 frontend — depends on `useEnrichedModels` subscribing to `LLM_CONNECTION_MODELS_REFRESHED`, which Feature 2 validates end-to-end.
3. Feature 3 backend (`_clone.py`, endpoint, `AvatarStore.duplicate`, public API).
4. Feature 3 frontend (move Export, add Clone button, build `PersonaCloneDialog`).

Each feature ships independently and can be merged to master on its own.

# UI Restructure and Bug Fixes — Design (2026-04-15)

## Overview

Reduce User-Modal navigation surface from 15 flat tabs to 7 top-level
groups with 2-level pill navigation. Rework the model browser / picker
(favourite-in-list, provider dropdown, collapsible groups). Replace
model-editor checkboxes with tag-style toggles and a context-window
slider. Migrate the model `unique_id` canonical form from UUID- to
slug-based. Fix three UX/data bugs around API-key and LLM-connection
testing.

Database is effectively empty; no user-data migration required.

---

## 1. Tab Restructure

### 1.1 Information Architecture

7 top-level groups (flat tabs become nested pills):

| # | Top | Sub-tabs |
|---|-----|----------|
| 1 | About Me | — |
| 2 | Personas | — |
| 3 | Chats | Projects · History · Bookmarks |
| 4 | Knowledge | — |
| 5 | My data | Uploads · Artefacts |
| 6 | Settings | LLM Providers · Models · API-Keys · MCP · Integrations · Display |
| 7 | Job-Log | — |

A future "Debug" group is reserved for when more operational tools
accumulate — not built now.

The current `SettingsTab` (account settings) content moves into
`Settings → Display`. No other content is consolidated or deleted.

### 1.2 Layout — Two Horizontal Pill Rows

Desktop and mobile share the same layout (current flat-tab pattern
extended with a second row):

- **Row 1:** Top-level pill row. Uses the existing gold-underline
  active style. `flex flex-wrap` on desktop, horizontal scroll on
  narrow mobile.
- **Row 2:** Sub-tab pill row, visible only when the active top-level
  group has children. Smaller pills, lighter background. Hidden when
  the active top-level has no children.

### 1.3 Problem Indicator Propagation

Each sub-tab can show the existing 10-px red `!` badge. The parent top
tab shows a single red `!` if **any** of its sub-tabs carries one. No
counter. Avatar badge shows if any top-level has `!`.

Current sources:
- `Settings → API-Keys` — at least one web-search provider
  un-configured
- `Settings → LLM Providers` — zero connections

### 1.4 Default Landing Tab

Avatar click:
- If API-keys problem → `Settings → API-Keys` (both levels set in one
  action)
- Else → `About Me`

### 1.5 Sub-Tab Persistence

Last-selected sub-tab per top-level group is persisted in
`localStorage` under `chatsune_user_modal_subtabs` (JSON map:
`{ topTabId: subTabId }`). On top-level switch, the remembered sub-tab
is restored; default is the first sub-tab of the group.

### 1.6 Deep-Linking

Out of scope for this pass. Tab state stays client-only. Existing
sidebar triggers (`onOpenModal('knowledge')`,
`onOpenModal('bookmarks')`, etc.) are adapted to the new structure:
the trigger resolves to a `(top, sub)` pair internally.

---

## 2. Model Picker — Sizing and Nesting

### 2.1 Always a Child of Its Parent Overlay

The model picker (`ModelSelectionModal`) is constrained to its parent
overlay on desktop:

- `max-height: 80%` of parent-overlay height
- `max-width: 90%` of parent-overlay width
- Visually rendered as a sub-modal within the parent (not a viewport-
  level sheet).

This applies to both call-sites:
- Persona `EditTab` (parent = `PersonaOverlay`)
- Any other future invocation

Mobile (`<lg`): full-screen, as today.

### 2.2 Models Tab Is Inline

The `Models` sub-tab under `Settings` continues to embed
`ModelBrowser` directly (not via `ModelSelectionModal`). No modal-in-
modal.

---

## 3. Model Picker / Browser UX

### 3.1 Inline Favourite Toggle

A star button is rendered **left** of each model row:

- Filled gold (`★`) when `is_favourite`
- Outline grey (`☆`) otherwise
- Click toggles immediately via existing `llmApi.setUserModelConfig`
  (optimistic update, event-driven refresh)
- Click on the star **does not** open the editor or trigger selection

### 3.2 Row Click Semantics

- Browser mode (Models tab): row click opens `ModelConfigModal`
- Selection mode (persona picker): row click invokes
  `onSelect(model.unique_id)` and closes the picker
- Editor is **not** reachable from selection mode — deliberate. User
  is actively choosing a model, not editing it.

### 3.3 Provider Filter — Dropdown (Single-Select)

Above the model list, replace any Provider-filter chips with a
`<select>` dropdown:

- Options: `All providers` (default) + one entry per user Connection
  (`display_name` — `slug`)
- Single-select. No multi-select.
- Rendered with the project's dark-option styling (see CLAUDE.md).

Capability chips (Reasoning / Vision / Tools / Show hidden /
Favourites) stay as they are — curated, small set.

### 3.4 Collapsible Connection Groups

Each connection-group header becomes a clickable caret:

- Click toggles collapse
- Collapsed state persisted in `localStorage` under
  `chatsune_model_browser_collapsed` (JSON array of connection IDs)
- Default: all expanded

### 3.5 Quantisation in Model Rows

If the adapter reports quantisation (Ollama Cloud does; Local may),
show it next to the model display name as a small mono-font tag
(e.g. `Q4_K_M`). When the field is absent, omit silently.

`ModelMetaDto` requires a nullable `quantisation: str | None` field.
The `ollama_http` adapter populates it where the upstream returns it.

---

## 4. Model Editor Redesign

### 4.1 Tag-Button Replacements

Replace the two checkboxes with pill-shaped toggle buttons:

- **Favourite** — gold filled-star + label "Favourite" when active;
  grey outline-star + label "Favourite" when inactive
- **Visible / Hidden** — green eye + label "Visible" when
  `is_hidden === false`; grey crossed-out eye + label "Hidden" when
  `is_hidden === true` (single toggle; label and colour flip)

### 4.2 Context-Window Slider

Replaces the number input:

- Range: `[80 000, model_max_context_window]`
- Step: `4096` if `model_max_context_window` is a power of 2
  (e.g. `131 072`, `262 144`), else `4000`
  (covers rounded-decimal values like `128 000`, `200 000`)
- Disabled (greyed out) when `model_max_context_window <= 80 000`
- Current value shown next to the label, mono-font
- Reset button below slider: "Use model default" — sets
  `custom_context_window` to `null`; slider indicator visually snaps
  to "default" marker

Models whose adapter does not report a max context window are
**filtered out at the adapter layer** and never appear in the list
(reason: technically unworkable). See §5.3.

### 4.3 Other Editor Fields

Unchanged: `custom_display_name` (text), `notes` (textarea),
`system_prompt_addition` (textarea). Reset / Cancel / Save buttons
unchanged.

---

## 5. Model `unique_id` — Slug-Based Canonical Form

### 5.1 New Format

Canonical: `<connection_slug>:<model_slug>`.

Example: `ollama-cloud:llama3.3:70b`, `ollama-local:qwen2.5-coder:32b`

Parsing: split on the **first** `:`. Left = connection slug
(user-defined, unique per user, validated by the existing slug regex).
Right = model slug (opaque, passed to the adapter).

### 5.2 Cascade on Slug Rename

`ConnectionRepository.update` must, when `slug` actually changes, run
a cascade **scoped to the current `user_id`** (personas and model
configs are always per-user; no cross-user touches):

1. In a MongoDB transaction (RS0 available):
   - Update the connection document (`slug`, `updated_at`)
   - Update every `persona.model_unique_id` of this user matching
     `<old-slug>:*` → `<new-slug>:*` (regex update)
   - Update every `llm_user_model_configs.model_unique_id` of this
     user matching `<old-slug>:*` → `<new-slug>:*`
2. Publish existing `Topics.LLM_CONNECTION_UPDATED` plus a new
   `Topics.LLM_CONNECTION_SLUG_RENAMED` event with `{old_slug,
   new_slug, connection_id}`, so frontend stores can remap in place
   rather than refetch everything.

Cross-user cascades cannot occur because personas and user-model-
configs are owned by the connection's user, and slug uniqueness is
enforced per `(user_id, slug)`.

### 5.3 Adapter-Level Filter for Unusable Models

The `ollama_http` adapter drops any model that does not expose a
`context_length` (alias `max_context_window`) from `list_models()`.
These are considered under-specified and cannot be offered.

### 5.4 DTO Impact

- `ModelMetaDto` gains a new `connection_slug: str` field. The
  existing `connection_id: str` (UUID) is retained for internal
  bookkeeping (e.g. tracker enrichment), but `unique_id` is composed
  from `connection_slug`, not the UUID.
- The generic LLM-module resolver dependency (used to resolve an
  incoming `unique_id` from an API path or DTO) now looks up the
  Connection by `(user_id, slug)` instead of `(user_id, _id)`.
- The `llm_connections` collection keeps its UUID `_id`; no schema
  change there. The Connection's `slug` is already unique per user
  (existing index `(user_id, slug)` with `unique=True`).
- Frontend `slugWithoutConnection()` helper unchanged in behaviour
  (still splits on first `:`).

### 5.5 INSIGHTS.md Updates

- `INS-004` header becomes `(SUPERSEDED 2026-04-15)` pointing to a new
  `INS-019 — Model Unique ID Slug Format`
- `INS-016` keeps a note on the revised `unique_id` format
- `INS-019` explains the slug-based format, cascade semantics, and
  adapter-level filter for unusable models

---

## 6. Bug Fixes

### 6.1 API-Keys — Test Button

File: `frontend/.../user-modal/ApiKeysTab.tsx`

- Enable condition:
  `row.draft.length > 0 || provider.is_configured`
- Click handler:
  - If `row.draft` is non-empty → test with that draft
  - Else → call test endpoint **without** a body's `api_key`; backend
    uses the stored credential
- Backend `POST /api/websearch/providers/{provider_id}/test` is
  extended to accept a missing / empty `api_key`; falls back to the
  stored one (error if neither present)
- Change canary query from `"chatsune_test"` to `"capital of paris"`

### 6.2 LLM-Provider Edit Modal — Auto-Save-on-Test + Footer Redesign

Remove the separate "Test connection" button. Footer becomes:

- Left: **Cancel** (unchanged)
- Right: **Save** (secondary) — save + test, modal stays open,
  shows status
- Right primary: **Save and close** — save + test + close modal
  immediately (regardless of test result; status is visible in the
  connection list)

Both Save paths:

1. Validate form locally (slug regex, required fields). On error:
   inline messages, no save, no test.
2. Call `updateConnection` / `createConnection`
3. On success, call `testConnection`
4. `testConnection` (backend change, §6.3) now persists status and
   publishes an event; frontend receives the event and renders the
   up-to-date pill

### 6.3 LLM-Provider Test Backend — Persist + Event

File: `backend/modules/llm/_adapters/_ollama_http.py` (`POST /test`
handler, currently fire-and-forget).

After determining `valid` / `error`:

- Call `ConnectionRepository.update_test_status(user_id, conn_id,
  status=..., error=...)`
- `await event_bus.publish(Topics.LLM_CONNECTION_UPDATED, ...)` — same
  topic used by update/create, payload is the fresh `ConnectionDto`

### 6.4 "Optional" Placeholder Perception Bug

Likely a form-reload issue: after save, the modal's `connection`
prop is not re-hydrated with the fresh redacted config
(`api_key.is_set = true`), so the placeholder logic continues to see
a missing key.

Plan:

1. Reproduce by saving a connection with `api_key` in the Ollama-
   Cloud modal
2. Confirm whether `apiKeyState.is_set` returns `true` from the
   backend after save
3. If the data is correct, fix the modal's state-refresh after save
   to adopt the returned connection doc
4. If the data is wrong, fix `_redact_config` or the create/update
   return value

Acceptance: after saving a connection with an API key, reopening the
modal shows `'••••••••  (leave empty to keep)'` and a `saved` badge
— never the `Optional` placeholder.

---

## 7. Out of Scope

- URL deep-linking for tabs
- Second-level nesting beyond 2 (no sub-sub-tabs)
- Redesign of capability chips (Reasoning / Vision / Tools stay as
  chips)
- Extraction of `ModelBrowser` into a shared library
- Adding new adapter types (only `ollama_http` Templates remain the
  set)

---

## 8. Build / Verification Checklist

- `pnpm run build` clean after all frontend changes
- `uv run python -m py_compile` on all touched backend files
- `backend/pyproject.toml` + root `pyproject.toml` parity if any new
  Python dep is introduced (none expected)
- New event `Topics.LLM_CONNECTION_SLUG_RENAMED` added to
  `shared/topics.py` and `shared/events/llm.py`
- INSIGHTS update in same commit as the slug migration

---

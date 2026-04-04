# User Model Customisation -- Design Spec

**Date:** 2026-04-04
**Status:** Draft

---

## Summary

Enhance the user-facing Models tab so users can personalise their model experience:
custom display names, hiding unwanted models, adjusting context window size, and
streamlined access to configuration via row-click (matching the admin pattern).
Remove the dedicated CFG column and replace it with an inline customisation indicator.

---

## Motivation

- Users need to manage a growing list of models from multiple providers
- Some models are irrelevant to a user (e.g. Kimi K2, GLM-4.7) and clutter the list
- Models like Grok degrade with long contexts; users need per-model context limits
- Pay-per-token and limited-compute providers (Ollama Cloud) make context size a cost factor
- The current CFG column wastes space and the column order has bugs

---

## Changes

### 1. Table Bug Fixes

**Column order mismatch:** The SORT_FIELDS array defines Name, Provider, Params, Context, Rating
but the rendered data outputs Provider, Name, Params, Context, Caps, Rating.

**Fix:** Align header order and data order to: Fav | Name | Provider | Params | Context | Caps | Rating.

**Rating display for uncurated models:** Currently shows "--" when `curation` is null.
Change to show "Available" (blue badge), matching the effective default.

### 2. Remove CFG Column and "..." Menu

- Remove the Cfg column (gear icon) and the trailing "..." menu button
- Entire row becomes clickable, opening the `ModelConfigModal`
- Remove `onSelect` and `onEditConfig` distinction -- there is only one action: open config
- Grid changes from 9 columns to 7: `[2rem_1fr_5.5rem_5rem_4rem_3.5rem_6.5rem]`

### 3. Customisation Indicator

When a model has any user customisation, display a small purple diamond (`&#9670;`)
next to the model name. Uses the existing `#cba6f7` colour.

"Has customisation" means the user config exists AND at least one of:
`is_favourite`, `is_hidden`, `custom_display_name`, `custom_context_window`,
`notes` (non-empty), or `system_prompt_addition` (non-empty) is set.

### 4. Custom Display Name

- New optional field `custom_display_name: string | null` in user config
- When set, shown as the primary name in the table
- Original `display_name` shown faded beside it (italic, smaller font)
- Max length: 100 characters
- Stored in `UserModelConfigDto` and `SetUserModelConfigDto`

### 5. Hide Models

- Expose the existing `is_hidden` field in the config modal as a toggle switch
- Red-tinted toggle to signal it is a "destructive" visibility action
- Hidden models are filtered out by default (same as admin-hidden models)
- New filter button "Hidden" in the header bar (alongside Favourites and Customised)
  - When active, shows ONLY user-hidden models (dimmed at 45% opacity)
  - Badge shows count of hidden models
- Hidden models do not appear in the model picker (persona configuration) either

### 6. Context Size Slider

New optional field `custom_context_window: int | null` in user config.

**Availability rule:** Slider only shown when the model's `context_window >= 96_000`.
For smaller models, show a disabled label: "Context adjustment available for models
with 96k+ context window."

**Step ladder:**

| Range | Step | Values |
|-------|------|--------|
| 96k -- 256k | 32k | 96k, 128k, 160k, 192k, 224k, 256k |
| 256k -- 512k | 128k | 384k, 512k |
| 512k -- 2M | 256k | 768k, 1M, 1.25M, 1.5M, 2M |

Only steps up to and including the model's actual `context_window` are offered.
Default (null) = model's maximum context window.

**Display:** Current value shown in gold next to the label. Slider track fills
from left to current position. Step labels shown below the track.

**Help text:** "Smaller context = lower cost per message. Default is the model's maximum."

### 7. Auto-Growing Textareas

System Prompt Addition and Notes textareas auto-grow with content.
Minimum height stays as current (4 rows / 3 rows respectively).
Growth capped at 12 rows to prevent the modal from becoming excessively tall;
after that, the textarea scrolls internally.

---

## Data Model Changes

### Backend: `shared/dtos/llm.py`

```python
class UserModelConfigDto(BaseModel):
    model_unique_id: str
    is_favourite: bool = False
    is_hidden: bool = False
    custom_display_name: str | None = None
    custom_context_window: int | None = None
    notes: str | None = None
    system_prompt_addition: str | None = None

class SetUserModelConfigDto(BaseModel):
    is_favourite: bool | None = None
    is_hidden: bool | None = None
    custom_display_name: str | None = None
    custom_context_window: int | None = None
    notes: str | None = None
    system_prompt_addition: str | None = None
```

### Frontend: `frontend/src/core/types/llm.ts`

Mirror the two new fields:

```typescript
export interface UserModelConfigDto {
  model_unique_id: string
  is_favourite: boolean
  is_hidden: boolean
  custom_display_name: string | null
  custom_context_window: number | null
  notes: string | null
  system_prompt_addition: string | null
}

export interface SetUserModelConfigRequest {
  is_favourite?: boolean
  is_hidden?: boolean
  custom_display_name?: string | null
  custom_context_window?: number | null
  notes?: string | null
  system_prompt_addition?: string | null
}
```

### Database: `llm_user_model_configs` collection

Two new optional fields on the document. No migration needed -- existing documents
simply lack these fields, which maps to `None`/`null` (= use defaults).

Repository `upsert()` already handles partial updates; just add the two new fields
to the `$set` dict when not None.

---

## Component Changes

### `ModelBrowser.tsx`

- Remove CFG column and "..." menu column
- Change grid to 7 columns: `[2rem_1fr_5.5rem_5rem_4rem_3.5rem_6.5rem]`
- Fix SORT_FIELDS to match actual render order
- Row click calls `onEditConfig` (rename to `onConfigure` for clarity)
- Remove `onSelect` prop entirely
- Show purple diamond next to name when model has customisation
- Show custom display name as primary, original name faded beside it
- Uncurated models show "Available" badge instead of "--"
- Add "Hidden" filter button (shows count, filters to user-hidden models only)
- User-hidden models shown at 45% opacity when the hidden filter is active
- User-hidden models excluded from default view

### `ModelConfigModal.tsx`

- Add hidden toggle (red-tinted switch) below favourite
- Add custom display name input below hidden toggle
- Add context size slider (stepped, conditional on >= 96k)
- Make System Prompt Addition and Notes textareas auto-growing (min 3-4 rows, max 12 rows)
- Send new fields in `SetUserModelConfigRequest`

### `modelFilters.ts`

- Add `showHidden?: boolean` to `ModelFilters`
- Filter logic: when `showHidden` is false/undefined, exclude models where
  `user_config?.is_hidden === true`
- When `showHidden` is true, show ONLY user-hidden models
- Adjust `hasCustomisation` check to include `custom_display_name` and `custom_context_window`

### `useEnrichedModels.ts`

No changes needed -- it already merges user configs with model metadata.

---

## Context Step Ladder -- Implementation

```typescript
const CONTEXT_STEPS: number[] = [
  96_000, 128_000, 160_000, 192_000, 224_000, 256_000,
  384_000, 512_000,
  768_000, 1_000_000, 1_250_000, 1_500_000, 2_000_000,
]

function availableSteps(maxContext: number): number[] {
  return CONTEXT_STEPS.filter(s => s <= maxContext)
}
```

The slider maps to an index into the filtered steps array. If the model's max context
is not exactly on a step boundary, include it as the final step.

---

## Validation

### Backend

- `custom_display_name`: max 100 characters, stripped of leading/trailing whitespace
- `custom_context_window`: must be >= 96_000 and <= model's `context_window`.
  If set to the model's max, store as null (= default).
  Backend does not enforce the step ladder -- the frontend handles step snapping.

### Frontend

- Display name input: maxLength 100
- Context slider: only available steps shown, no free-form input

---

## Files to Modify

| File | Change |
|------|--------|
| `shared/dtos/llm.py` | Add `custom_display_name`, `custom_context_window` to both DTOs |
| `backend/modules/llm/_user_config.py` | Handle new fields in `upsert()` |
| `backend/modules/llm/_handlers.py` | Add validation for new fields in PUT endpoint |
| `frontend/src/core/types/llm.ts` | Add new fields to TS interfaces |
| `frontend/src/app/components/model-browser/ModelBrowser.tsx` | Table restructure, bug fixes, indicators |
| `frontend/src/app/components/model-browser/ModelConfigModal.tsx` | New fields, auto-grow textareas |
| `frontend/src/app/components/model-browser/modelFilters.ts` | Hidden filter, customisation check |
| `frontend/src/app/components/user-modal/ModelsTab.tsx` | Adapt to new ModelBrowser props |
| Tests for backend validation | New fields in existing test patterns |

---

## Out of Scope

- Model picker in persona configuration (separate feature)
- Admin-side changes (already works as intended)
- Actual enforcement of context window during chat (future: chat module uses this value)

# Model Picker in Persona Editor

## Summary

Integrate the existing `ModelSelectionModal` and `ModelBrowser` components into the persona editor (`EditTab`), making model selection a required step when creating or editing a persona. The `ModelBrowser` gains a dual-mode behaviour: in selection mode (persona picker), clicking a row selects the model and closes the modal immediately; in management mode (settings), clicking a row opens the config editor as before.

## Scope

- Frontend only -- no backend changes required
- `model_unique_id` field, validation, and DTOs already exist end-to-end

## Components Affected

### EditTab (`frontend/src/app/components/persona-overlay/EditTab.tsx`)

**New: Model selector field** placed after Tagline, before Temperature.

- Clickable area spanning full width of the form
- **With model selected:** Shows provider badge (monospace, dimmed) and model display name (serif font). Hover effect consistent with other interactive elements.
- **Without model selected:** Placeholder text "Select a model..." in dimmed style. Border changes to `1px solid rgba(243, 139, 168, 0.4)` (subtle red) as a visual cue that the field is required.
- Click opens `ModelSelectionModal` as a nested modal
- Save button remains disabled while no model is selected

**State additions:**
- `modelUniqueId: string` -- the `provider_id:model_slug` value
- `modelDisplayName: string` -- for display in the selector
- `modelProvider: string` -- for the provider badge
- `canReason: boolean` -- tracks whether the selected model supports reasoning

**On model select callback:**
- Sets all four state values from the selection
- If new model has `canReason === false`, sets `reasoningEnabled` to `false`

**Reasoning toggle change:**
- Always visible (not hidden based on model capability)
- When selected model has `canReason === false`: toggle is disabled, rendered at 30% opacity, with `title="Model does not support reasoning"`
- When a model without reasoning is selected, `reasoningEnabled` is automatically set to `false`

### ModelBrowser (`frontend/src/app/components/model-browser/ModelBrowser.tsx`)

**Dual-mode behaviour based on `onSelect` prop:**

| Aspect | Selection mode (`onSelect` set) | Management mode (`onSelect` absent) |
|---|---|---|
| Row click | Calls `onSelect(model)` | Opens `ModelConfigModal` |
| "..." button | Visible at row end, opens `ModelConfigModal` | Not rendered |
| Current model highlight | Gold left border on matching row | N/A |

**"..." button details:**
- Positioned at the right end of each model row
- Monospace text, dimmed opacity, small hit target
- `onClick` calls `stopPropagation()` then opens `ModelConfigModal`
- Consistent with the prototype's pattern

### ModelSelectionModal (`frontend/src/app/components/model-browser/ModelSelectionModal.tsx`)

**Integration in EditTab:**
- Rendered as a child of EditTab when `modelModalOpen` state is true
- Props: `currentModelId`, `onSelect`, `onClose`
- `onSelect` receives `{ id, displayName, provider, canReason }` and closes the modal immediately
- Nested `ModelConfigModal` (triggered via "..." button) renders above selection modal (higher z-index)

## Data Flow

```
EditTab
  |-- [click model selector area]
  |     |
  |     v
  |   ModelSelectionModal
  |     |-- ModelBrowser (selectionMode via onSelect prop)
  |     |     |-- [click row] --> onSelect(model) --> close modal --> update EditTab state
  |     |     |-- [click "..."] --> ModelConfigModal (nested, higher z-index)
  |     |
  |     |-- [Escape / click backdrop] --> close modal
  |
  |-- [model state updated]
  |     |-- Update display in selector area
  |     |-- If !canReason: set reasoningEnabled = false, disable toggle
  |
  |-- [save persona]
        |-- model_unique_id included in create/update payload
        |-- Save button disabled if model_unique_id is empty
```

## Validation

- **Frontend:** Save button disabled when `model_unique_id` is empty. Red border on empty model selector as visual cue.
- **Backend:** Existing validation in `_handlers.py` checks `model_unique_id` format and provider existence -- no changes needed.

## What This Does NOT Include

- No new API endpoints
- No changes to DTOs or shared contracts
- No changes to the ModelBrowser in settings/management context (existing behaviour preserved)
- No auto-opening of model picker for new personas (user retains agency)

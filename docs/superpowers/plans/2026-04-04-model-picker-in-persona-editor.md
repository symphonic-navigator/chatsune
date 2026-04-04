# Model Picker in Persona Editor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the existing ModelSelectionModal into the persona editor's EditTab so users can pick a model when creating or editing a persona, with immediate selection on click and inline model config via a "..." button.

**Architecture:** The ModelBrowser component gains two new optional props (`onSelect`, `currentModelId`) that switch it into selection mode — row click selects, "..." button opens config. EditTab gets a clickable model selector area and wires up ModelSelectionModal. The reasoning toggle becomes always-visible but disabled when the model lacks reasoning support.

**Tech Stack:** React, TypeScript, Tailwind CSS

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `frontend/src/app/components/model-browser/ModelBrowser.tsx` | Modify | Add `onSelect`, `currentModelId` props; add "..." button column; dual-mode row click |
| `frontend/src/app/components/persona-overlay/EditTab.tsx` | Modify | Add model selector area, model state, wire ModelSelectionModal, disable reasoning toggle |

---

### Task 1: Add selection mode to ModelBrowser

**Files:**
- Modify: `frontend/src/app/components/model-browser/ModelBrowser.tsx`

- [ ] **Step 1: Add `onSelect` and `currentModelId` props to the interface**

Add two new optional props to `ModelBrowserProps`:

```typescript
interface ModelBrowserProps {
  onEditConfig?: (model: EnrichedModelDto) => void
  onToggleFavourite?: (model: EnrichedModelDto) => void
  onSelect?: (model: EnrichedModelDto) => void
  currentModelId?: string | null
  models?: EnrichedModelDto[]
}
```

Destructure them in the component function signature:

```typescript
export function ModelBrowser({
  onEditConfig,
  onToggleFavourite,
  onSelect,
  currentModelId,
  models: externalModels,
}: ModelBrowserProps) {
```

- [ ] **Step 2: Derive `selectionMode` boolean and change row click handler**

Add after the existing `const providers` line:

```typescript
const selectionMode = onSelect != null
```

Change the row's `onClick` handler from:

```tsx
onClick={() => onEditConfig?.(model)}
```

to:

```tsx
onClick={() => selectionMode ? onSelect(model) : onEditConfig?.(model)}
```

- [ ] **Step 3: Add current-model highlighting to row styling**

Change the row's className from:

```tsx
className={[
  "grid grid-cols-[2rem_1fr_5.5rem_5rem_4rem_3.5rem_6.5rem] items-center gap-1 border-b border-white/6 px-4 py-2 text-[12px] transition-colors",
  "cursor-pointer hover:bg-white/4",
  model.user_config?.is_hidden ? "opacity-45" : "",
].join(" ")}
```

to:

```tsx
className={[
  `grid items-center gap-1 border-b border-white/6 px-4 py-2 text-[12px] transition-colors`,
  selectionMode
    ? "grid-cols-[2rem_1fr_5.5rem_5rem_4rem_3.5rem_6.5rem_2rem]"
    : "grid-cols-[2rem_1fr_5.5rem_5rem_4rem_3.5rem_6.5rem]",
  "cursor-pointer hover:bg-white/4",
  model.unique_id === currentModelId ? "bg-[#C9A96E]/8 border-l-2 border-l-[#C9A96E]" : "",
  model.user_config?.is_hidden ? "opacity-45" : "",
].join(" ")}
```

- [ ] **Step 4: Add "..." button column at the end of each row (selection mode only)**

After the `{/* Rating */}` block inside the `.map()`, add:

```tsx
{/* Edit config button (selection mode only) */}
{selectionMode && (
  <button
    type="button"
    onClick={(e) => {
      e.stopPropagation()
      onEditConfig?.(model)
    }}
    className="text-[14px] text-white/25 hover:text-white/50 transition-colors cursor-pointer text-center"
    title="Configure model"
  >
    &#x2026;
  </button>
)}
```

- [ ] **Step 5: Update column headers grid to match**

Change the column headers grid from:

```tsx
<div className="grid grid-cols-[2rem_1fr_5.5rem_5rem_4rem_3.5rem_6.5rem] items-center gap-1 border-b border-white/6 px-4 py-1.5 text-[10px] font-medium uppercase tracking-wider text-white/30">
```

to:

```tsx
<div className={[
  "grid items-center gap-1 border-b border-white/6 px-4 py-1.5 text-[10px] font-medium uppercase tracking-wider text-white/30",
  selectionMode
    ? "grid-cols-[2rem_1fr_5.5rem_5rem_4rem_3.5rem_6.5rem_2rem]"
    : "grid-cols-[2rem_1fr_5.5rem_5rem_4rem_3.5rem_6.5rem]",
].join(" ")}>
```

After the closing `</span>` for "Rating", add an empty spacer for the "..." column:

```tsx
{selectionMode && <span />}
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/components/model-browser/ModelBrowser.tsx
git commit -m "Add selection mode to ModelBrowser with onSelect, currentModelId, and edit button"
```

---

### Task 2: Add model selector and reasoning toggle changes to EditTab

**Files:**
- Modify: `frontend/src/app/components/persona-overlay/EditTab.tsx`

- [ ] **Step 1: Add imports for ModelSelectionModal**

Add at the top of the file:

```typescript
import { ModelSelectionModal } from '../model-browser/ModelSelectionModal'
```

- [ ] **Step 2: Add model-related state variables**

After the existing `const [saving, setSaving] = useState(false)` line, add:

```typescript
const [modelUniqueId, setModelUniqueId] = useState(persona.model_unique_id)
const [modelDisplayName, setModelDisplayName] = useState('')
const [modelProvider, setModelProvider] = useState('')
const [canReason, setCanReason] = useState(false)
const [modelModalOpen, setModelModalOpen] = useState(false)
```

- [ ] **Step 3: Add model fields to dirty check and canSave**

Change the `isDirty` check from:

```typescript
const isDirty = isCreating ||
  name !== persona.name ||
  tagline !== persona.tagline ||
  colourScheme !== persona.colour_scheme ||
  systemPrompt !== persona.system_prompt ||
  temperature !== persona.temperature ||
  reasoningEnabled !== persona.reasoning_enabled ||
  nsfw !== persona.nsfw
```

to:

```typescript
const isDirty = isCreating ||
  name !== persona.name ||
  tagline !== persona.tagline ||
  colourScheme !== persona.colour_scheme ||
  systemPrompt !== persona.system_prompt ||
  temperature !== persona.temperature ||
  reasoningEnabled !== persona.reasoning_enabled ||
  nsfw !== persona.nsfw ||
  modelUniqueId !== persona.model_unique_id
```

Change `canSave` from:

```typescript
const canSave = isCreating ? name.trim() !== '' && tagline.trim() !== '' : isDirty
```

to:

```typescript
const canSave = isCreating
  ? name.trim() !== '' && tagline.trim() !== '' && modelUniqueId !== ''
  : isDirty
```

- [ ] **Step 4: Update handleSave to always include model_unique_id**

Replace the entire `handleSave` function:

```typescript
async function handleSave() {
  if (!canSave || saving) return
  setSaving(true)
  try {
    const data: Record<string, unknown> = {
      name,
      tagline,
      colour_scheme: colourScheme,
      system_prompt: systemPrompt,
      temperature,
      reasoning_enabled: reasoningEnabled,
      nsfw,
      model_unique_id: modelUniqueId,
    }
    await onSave(isCreating ? null : persona.id, data)
  } finally {
    setSaving(false)
  }
}
```

- [ ] **Step 5: Add model select handler**

After the `handleSave` function, add:

```typescript
function handleModelSelect(model: {
  unique_id: string
  display_name: string
  provider_id: string
  supports_reasoning: boolean
}) {
  setModelUniqueId(model.unique_id)
  setModelDisplayName(model.display_name)
  setModelProvider(model.provider_id)
  setCanReason(model.supports_reasoning)
  if (!model.supports_reasoning) {
    setReasoningEnabled(false)
  }
  setModelModalOpen(false)
}
```

- [ ] **Step 6: Add model selector area in the form — after Tagline, before Chakra colour**

Insert between the `{/* Tagline */}` label and the `{/* Chakra colour picker */}` div:

```tsx
{/* Model */}
<div className="flex flex-col gap-1.5">
  <span className="text-[11px] text-white/40 uppercase tracking-wider">Model</span>
  <button
    type="button"
    onClick={() => setModelModalOpen(true)}
    className="flex items-center gap-2 w-full text-left rounded-lg px-3 py-2.5 transition-colors hover:bg-white/4 cursor-pointer"
    style={{
      background: 'rgba(255,255,255,0.03)',
      border: modelUniqueId
        ? `1px solid ${chakra.hex}26`
        : '1px solid rgba(243, 139, 168, 0.4)',
      borderRadius: 8,
    }}
  >
    {modelUniqueId ? (
      <>
        <span className="text-[10px] font-mono text-white/35 uppercase tracking-wider">{modelProvider}</span>
        <span className="text-[13px] text-white/80">{modelDisplayName || modelUniqueId}</span>
      </>
    ) : (
      <span className="text-[13px] text-white/30 italic">Select a model...</span>
    )}
  </button>
</div>
```

- [ ] **Step 7: Modify reasoning toggle to be always visible but disabled when model lacks support**

Change the reasoning Toggle from:

```tsx
<Toggle
  label="Reasoning"
  description="Enable extended thinking for complex tasks"
  value={reasoningEnabled}
  onChange={setReasoningEnabled}
  chakraHex={chakra.hex}
/>
```

to:

```tsx
<Toggle
  label="Reasoning"
  description={canReason ? "Enable extended thinking for complex tasks" : "Model does not support reasoning"}
  value={reasoningEnabled}
  onChange={setReasoningEnabled}
  chakraHex={chakra.hex}
  disabled={!canReason}
/>
```

- [ ] **Step 8: Update Toggle component to support `disabled` prop**

Change the `ToggleProps` interface:

```typescript
interface ToggleProps {
  label: string
  description: string
  value: boolean
  onChange: (v: boolean) => void
  chakraHex: string
  disabled?: boolean
}
```

Change the Toggle function signature and add disabled handling:

```typescript
function Toggle({ label, description, value, onChange, chakraHex, disabled }: ToggleProps) {
  return (
    <div
      className="flex items-center justify-between py-2 px-3 rounded-lg"
      style={{
        background: 'rgba(255,255,255,0.02)',
        border: '1px solid rgba(255,255,255,0.05)',
        opacity: disabled ? 0.3 : 1,
        cursor: disabled ? 'not-allowed' : 'pointer',
      }}
      onClick={() => !disabled && onChange(!value)}
      title={disabled ? description : undefined}
    >
      <div className="flex flex-col gap-0.5">
        <span className="text-[13px] text-white/75">{label}</span>
        <span className="text-[11px] text-white/30">{description}</span>
      </div>

      {/* Custom toggle — 44x20px */}
      <div
        className="relative flex-shrink-0"
        style={{
          width: 44,
          height: 20,
          borderRadius: 10,
          background: value ? `${chakraHex}cc` : 'rgba(255,255,255,0.12)',
          transition: 'background 0.2s',
        }}
      >
        <div
          style={{
            position: 'absolute',
            top: 2,
            left: 2,
            width: 16,
            height: 16,
            borderRadius: '50%',
            background: 'white',
            transform: value ? 'translateX(24px)' : 'translateX(0)',
            transition: 'transform 0.2s',
            boxShadow: '0 1px 3px rgba(0,0,0,0.4)',
          }}
        />
      </div>
    </div>
  )
}
```

- [ ] **Step 9: Add ModelSelectionModal render at the bottom of the component return**

Change the component's return statement — wrap the existing `<div>` in a fragment and add the modal. The return becomes:

```tsx
return (
  <>
    <div className="flex flex-col gap-5 px-6 py-6 max-w-lg mx-auto w-full">
      {/* ... all existing form content ... */}
    </div>

    {modelModalOpen && (
      <ModelSelectionModal
        currentModelId={modelUniqueId || null}
        onSelect={handleModelSelect}
        onClose={() => setModelModalOpen(false)}
      />
    )}
  </>
)
```

- [ ] **Step 10: Commit**

```bash
git add frontend/src/app/components/persona-overlay/EditTab.tsx
git commit -m "Add model selector and disabled reasoning toggle to persona EditTab"
```

---

### Task 3: Verify existing ModelsTab still works (management mode)

**Files:**
- Read: `frontend/src/app/components/user-modal/ModelsTab.tsx`

- [ ] **Step 1: Verify ModelsTab does not pass `onSelect` or `currentModelId`**

Read `frontend/src/app/components/user-modal/ModelsTab.tsx` and confirm the `<ModelBrowser>` usage only passes `models`, `onToggleFavourite`, and `onEditConfig` — no `onSelect` or `currentModelId`. This means the ModelBrowser will remain in management mode (row click opens config, no "..." button) for the settings page.

- [ ] **Step 2: Run the dev server and test both flows**

```bash
cd frontend && pnpm dev
```

**Test selection mode (persona editor):**
1. Open persona editor (create new or edit existing)
2. Click the model selector area
3. ModelSelectionModal opens with all models
4. Click a model row → modal closes, model appears in selector
5. Click "..." on a model row → ModelConfigModal opens (selection modal stays open)
6. Close config modal → back to selection
7. Selected model has gold highlight

**Test management mode (settings > models):**
1. Open user settings → Models tab
2. Click a model row → ModelConfigModal opens (same as before)
3. No "..." button visible
4. Everything works as before

- [ ] **Step 3: Test reasoning toggle**

1. Select a model with reasoning support → toggle is enabled, clickable
2. Select a model without reasoning → toggle greys out (30% opacity), value resets to false
3. Select a reasoning model again → toggle re-enables

- [ ] **Step 4: Test validation**

1. Create new persona → model selector has red border
2. Fill in name + tagline but no model → Save button stays disabled
3. Select a model → red border disappears, Save becomes enabled

- [ ] **Step 5: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "Fix issues found during model picker testing"
```

# UI Tweaks: Vision Fallback Picker & New Chat Button — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the leaky native vision-fallback `<select>` in the persona editor with the shared `ModelSelectionModal` (locked to vision-capable models), and add a new "New Chat" entry point in the sidebar that expands an inline persona picker honouring sanitised mode.

**Architecture:** Two independent frontend changes. (1) Add a generic `lockedFilters` prop to `ModelBrowser`/`ModelSelectionModal` so capability filters can be force-enabled and disabled in the UI; reuse this from `EditTab.tsx` for the vision fallback. (2) Move `sortPersonas` into a shared helper and add a new sidebar row + collapsible inline panel above the Personas section.

**Tech Stack:** React + TypeScript (TSX), Vite, Tailwind, Vitest. No backend changes.

Spec: `docs/superpowers/specs/2026-04-07-ui-tweaks-vision-picker-new-chat-design.md`.

---

## File Structure

**Created**

- `frontend/src/app/components/sidebar/personaSort.ts` — shared `sortPersonas` helper extracted from `PersonasTab.tsx`. Single responsibility: pinned-first stable partition.
- `frontend/src/app/components/sidebar/NewChatRow.tsx` — sidebar row + inline expanded persona picker panel for the new chat flow.

**Modified**

- `frontend/src/app/components/model-browser/ModelBrowser.tsx` — add `lockedFilters` prop; force flags into filter state; render locked capability toggles in active+disabled style.
- `frontend/src/app/components/model-browser/ModelSelectionModal.tsx` — accept `lockedFilters`, pass through to `ModelBrowser`.
- `frontend/src/app/components/persona-overlay/EditTab.tsx` — remove `visionCapableModels` state + cross-provider load effect + native `<select>` block; replace with picker trigger button + clear button + nested `ModelSelectionModal`.
- `frontend/src/app/components/sidebar/Sidebar.tsx` — render `<NewChatRow />` immediately above the existing PERSONAS section (and below the admin banner when admin).
- `frontend/src/app/components/user-modal/PersonasTab.tsx` — import `sortPersonas` from the new shared helper; remove the local copy.

**Tests**

- `frontend/src/app/components/model-browser/__tests__/ModelBrowser.lockedFilters.test.tsx` — verifies vision toggle is forced on and disabled, and only vision models are shown.
- `frontend/src/app/components/sidebar/__tests__/NewChatRow.test.tsx` — verifies expand/collapse, sanitised filter, sort, click → navigate.

---

## Part 1 — Vision Fallback Picker

### Task 1: Add `lockedFilters` prop to `ModelBrowser`

**Files:**
- Modify: `frontend/src/app/components/model-browser/ModelBrowser.tsx`
- Test: `frontend/src/app/components/model-browser/__tests__/ModelBrowser.lockedFilters.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/app/components/model-browser/__tests__/ModelBrowser.lockedFilters.test.tsx
import { render, screen } from "@testing-library/react"
import { describe, it, expect, vi } from "vitest"
import { ModelBrowser } from "../ModelBrowser"
import type { EnrichedModelDto } from "../../../../core/types/llm"

function model(over: Partial<EnrichedModelDto>): EnrichedModelDto {
  return {
    unique_id: "p:m",
    model_id: "m",
    display_name: "M",
    provider_id: "p",
    provider_display_name: "P",
    context_window: 8000,
    parameter_count: null,
    quantisation_level: null,
    supports_tool_calls: false,
    supports_vision: false,
    supports_reasoning: false,
    user_config: null,
    curation: null,
    ...over,
  } as EnrichedModelDto
}

describe("ModelBrowser lockedFilters", () => {
  it("forces vision filter on, disables its toggle, and hides non-vision models", () => {
    const visionModel = model({ unique_id: "p:vis", display_name: "VisOne", supports_vision: true })
    const plainModel = model({ unique_id: "p:plain", display_name: "PlainOne", supports_vision: false })

    render(
      <ModelBrowser
        models={[visionModel, plainModel]}
        onSelect={vi.fn()}
        lockedFilters={{ capVision: true }}
      />,
    )

    expect(screen.getByText("VisOne")).toBeInTheDocument()
    expect(screen.queryByText("PlainOne")).not.toBeInTheDocument()

    const visionBtn = screen.getByTitle("Vision")
    expect(visionBtn).toBeDisabled()
    expect(visionBtn.className).toMatch(/text-\[#89b4fa\]/)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/app/components/model-browser/__tests__/ModelBrowser.lockedFilters.test.tsx`
Expected: FAIL — `lockedFilters` prop is not declared on `ModelBrowser`.

- [ ] **Step 3: Implement `lockedFilters` in `ModelBrowser.tsx`**

Add the type and prop, force the filter, and render locked toggles disabled. Edits inside `frontend/src/app/components/model-browser/ModelBrowser.tsx`:

(a) Below the existing `ModelBrowserProps` interface, add:

```tsx
export interface LockedFilters {
  capTools?: true
  capVision?: true
  capReason?: true
}

interface ModelBrowserProps {
  onEditConfig?: (model: EnrichedModelDto) => void
  onToggleFavourite?: (model: EnrichedModelDto) => void
  onSelect?: (model: EnrichedModelDto) => void
  currentModelId?: string | null
  models?: EnrichedModelDto[]
  lockedFilters?: LockedFilters
}
```

(Replace the existing `ModelBrowserProps` interface with this version.)

(b) In the function signature, accept the new prop:

```tsx
export function ModelBrowser({
  onEditConfig,
  onToggleFavourite,
  onSelect,
  currentModelId,
  models: externalModels,
  lockedFilters,
}: ModelBrowserProps) {
```

(c) Immediately after `const [filters, setFilters] = useState<ModelFilters>({})`, add an effect that forces locked flags into state on mount and whenever the locks change:

```tsx
useEffect(() => {
  if (!lockedFilters) return
  setFilters((f) => ({
    ...f,
    ...(lockedFilters.capTools ? { capTools: true } : {}),
    ...(lockedFilters.capVision ? { capVision: true } : {}),
    ...(lockedFilters.capReason ? { capReason: true } : {}),
  }))
}, [lockedFilters])
```

(d) Update each capability toggle button to honour the lock. Replace the existing T / V / R buttons (currently around lines 206–244) with this block:

```tsx
<div className="flex items-center gap-1">
  <button
    type="button"
    onClick={() => updateFilter("capTools", !filters.capTools)}
    disabled={lockedFilters?.capTools === true}
    className={[
      "rounded px-1.5 py-0.5 text-[10px] font-semibold transition-colors",
      lockedFilters?.capTools ? "cursor-not-allowed" : "cursor-pointer",
      filters.capTools
        ? "bg-[#a6e3a1]/15 text-[#a6e3a1]"
        : "text-white/30 hover:text-white/50",
    ].join(" ")}
    title={lockedFilters?.capTools ? "Tool Calls (required)" : "Tool Calls"}
  >
    T
  </button>
  <button
    type="button"
    onClick={() => updateFilter("capVision", !filters.capVision)}
    disabled={lockedFilters?.capVision === true}
    className={[
      "rounded px-1.5 py-0.5 text-[10px] font-semibold transition-colors",
      lockedFilters?.capVision ? "cursor-not-allowed" : "cursor-pointer",
      filters.capVision
        ? "bg-[#89b4fa]/15 text-[#89b4fa]"
        : "text-white/30 hover:text-white/50",
    ].join(" ")}
    title={lockedFilters?.capVision ? "Vision (required)" : "Vision"}
  >
    V
  </button>
  <button
    type="button"
    onClick={() => updateFilter("capReason", !filters.capReason)}
    disabled={lockedFilters?.capReason === true}
    className={[
      "rounded px-1.5 py-0.5 text-[10px] font-semibold transition-colors",
      lockedFilters?.capReason ? "cursor-not-allowed" : "cursor-pointer",
      filters.capReason
        ? "bg-[#f9e2af]/15 text-[#f9e2af]"
        : "text-white/30 hover:text-white/50",
    ].join(" ")}
    title={lockedFilters?.capReason ? "Reasoning (required)" : "Reasoning"}
  >
    R
  </button>
</div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm vitest run src/app/components/model-browser/__tests__/ModelBrowser.lockedFilters.test.tsx`
Expected: PASS.

- [ ] **Step 5: Run the full vitest suite for the model-browser folder to catch regressions**

Run: `cd frontend && pnpm vitest run src/app/components/model-browser`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/components/model-browser/ModelBrowser.tsx \
        frontend/src/app/components/model-browser/__tests__/ModelBrowser.lockedFilters.test.tsx
git commit -m "Add lockedFilters prop to ModelBrowser for constrained pickers"
```

---

### Task 2: Pass `lockedFilters` through `ModelSelectionModal`

**Files:**
- Modify: `frontend/src/app/components/model-browser/ModelSelectionModal.tsx`

- [ ] **Step 1: Add the prop and forward it**

In `frontend/src/app/components/model-browser/ModelSelectionModal.tsx`:

(a) Add the import next to the existing `ModelBrowser` import:

```tsx
import { ModelBrowser, type LockedFilters } from "./ModelBrowser"
```

(b) Extend `ModelSelectionModalProps`:

```tsx
interface ModelSelectionModalProps {
  currentModelId: string | null
  onSelect: (model: {
    unique_id: string
    display_name: string
    provider_id: string
    supports_reasoning: boolean
    supports_tool_calls: boolean
  }) => void
  onClose: () => void
  lockedFilters?: LockedFilters
}
```

(c) Destructure and forward:

```tsx
export function ModelSelectionModal({
  currentModelId,
  onSelect,
  onClose,
  lockedFilters,
}: ModelSelectionModalProps) {
```

In the existing `<ModelBrowser ... />` JSX block, add the prop:

```tsx
<ModelBrowser
  currentModelId={currentModelId}
  models={models}
  onSelect={handleSelect}
  onEditConfig={(m) => setConfigModel(m)}
  onToggleFavourite={handleToggleFavourite}
  lockedFilters={lockedFilters}
/>
```

- [ ] **Step 2: TypeScript check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/components/model-browser/ModelSelectionModal.tsx
git commit -m "Forward lockedFilters from ModelSelectionModal to ModelBrowser"
```

---

### Task 3: Replace native vision-fallback select in `EditTab.tsx`

**Files:**
- Modify: `frontend/src/app/components/persona-overlay/EditTab.tsx`

- [ ] **Step 1: Remove obsolete state and effect**

Delete these lines from `EditTab.tsx`:

- Line 51–53: the `visionCapableModels` state declaration
- Lines 90–114: the entire `useEffect` that loads vision-capable models across providers (the comment block above it can also be removed)

- [ ] **Step 2: Add a `visionPickerOpen` state next to the existing `modelModalOpen`**

Locate `const [modelModalOpen, setModelModalOpen] = useState(false)` (around line 55). Immediately below it, add:

```tsx
const [visionPickerOpen, setVisionPickerOpen] = useState(false)
const [visionFallbackDisplayName, setVisionFallbackDisplayName] = useState<string | null>(null)
```

Then load the display name for the persisted fallback once on mount, so the trigger button can show a friendly label rather than the raw `unique_id`. Add this `useEffect` immediately after the existing model-capabilities `useEffect` (after line 88):

```tsx
// Resolve a friendly display name for the persisted vision fallback model.
useEffect(() => {
  const uid = persona.vision_fallback_model
  if (!uid || !uid.includes(":")) {
    setVisionFallbackDisplayName(null)
    return
  }
  const providerId = uid.split(":")[0]
  const modelSlug = uid.split(":").slice(1).join(":")
  llmApi.listModels(providerId)
    .then((models) => {
      const model = models.find((m) => m.model_id === modelSlug)
      setVisionFallbackDisplayName(model?.display_name ?? modelSlug)
    })
    .catch(() => setVisionFallbackDisplayName(modelSlug))
}, [persona.vision_fallback_model])
```

- [ ] **Step 3: Replace the native `<select>` block**

In `EditTab.tsx`, the block currently at lines 414–449 (`{!canSeeImages && ( ... )}`) — replace it entirely with:

```tsx
{!canSeeImages && (
  <div className="flex flex-col gap-1.5">
    <label className="text-[11px] text-white/40 uppercase tracking-wider">
      Vision fallback
    </label>
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={() => setVisionPickerOpen(true)}
        className="flex-1 rounded-lg border px-3 py-2 text-left text-[13px] text-white/85 transition-colors hover:bg-white/5"
        style={{ borderColor: `${chakra.hex}26`, background: 'var(--color-surface)' }}
      >
        {visionFallbackModel
          ? (visionFallbackDisplayName ?? visionFallbackModel)
          : <span className="text-white/40">No fallback</span>}
      </button>
      {visionFallbackModel && (
        <button
          type="button"
          onClick={() => setVisionFallbackModel(null)}
          className="rounded-lg border border-white/10 px-2.5 py-2 text-[11px] text-white/55 hover:bg-white/5 transition-colors"
          title="Clear vision fallback"
        >
          Clear
        </button>
      )}
    </div>
    <span className="text-[11px] text-white/45">
      Used to describe images for this non-vision model.
    </span>
  </div>
)}
```

- [ ] **Step 4: Render the picker modal**

Find the existing `{cropOpen && !isCreating && (...)}` block near the bottom of the JSX. Immediately above it (still inside the top-level fragment), add:

```tsx
{visionPickerOpen && (
  <ModelSelectionModal
    currentModelId={visionFallbackModel}
    onSelect={(m) => {
      setVisionFallbackModel(m.unique_id)
      setVisionFallbackDisplayName(m.display_name)
      setVisionPickerOpen(false)
    }}
    onClose={() => setVisionPickerOpen(false)}
    lockedFilters={{ capVision: true }}
  />
)}
```

`ModelSelectionModal` is already imported at the top of the file.

- [ ] **Step 5: Drop now-unused `_OPTION_STYLE` if it has no other consumers**

After the previous edits, search the file for other uses of `_OPTION_STYLE`:

Run: `grep -n "_OPTION_STYLE" frontend/src/app/components/persona-overlay/EditTab.tsx`

If the only remaining occurrence is the constant definition (around lines 25–28), delete the constant. If there are still other consumers, leave it alone.

- [ ] **Step 6: Build check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: No errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/components/persona-overlay/EditTab.tsx
git commit -m "Replace vision fallback select with shared model picker"
```

---

## Part 2 — New Chat Button in Sidebar

### Task 4: Extract `sortPersonas` into a shared helper

**Files:**
- Create: `frontend/src/app/components/sidebar/personaSort.ts`
- Modify: `frontend/src/app/components/user-modal/PersonasTab.tsx`

- [ ] **Step 1: Create the helper file**

```ts
// frontend/src/app/components/sidebar/personaSort.ts
import type { PersonaDto } from '../../../core/types/persona'

/**
 * Stable pinned-first partition. Preserves the incoming list order, which is
 * authoritative: the API returns personas already sorted by display_order, and
 * optimistic reorder mutates array order (not display_order fields). Sorting
 * by display_order would fight optimistic updates.
 */
export function sortPersonas(list: PersonaDto[]): PersonaDto[] {
  const pinned: PersonaDto[] = []
  const unpinned: PersonaDto[] = []
  for (const p of list) {
    if (p.pinned) pinned.push(p)
    else unpinned.push(p)
  }
  return [...pinned, ...unpinned]
}
```

- [ ] **Step 2: Replace the local copy in `PersonasTab.tsx`**

In `frontend/src/app/components/user-modal/PersonasTab.tsx`:

(a) Delete the local `function sortPersonas(...)` block (lines 22–35 in the original).

(b) Add an import near the top:

```tsx
import { sortPersonas } from '../sidebar/personaSort'
```

- [ ] **Step 3: Run user-modal tests to confirm nothing regresses**

Run: `cd frontend && pnpm vitest run src/app/components/user-modal`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/sidebar/personaSort.ts \
        frontend/src/app/components/user-modal/PersonasTab.tsx
git commit -m "Extract sortPersonas into shared helper"
```

---

### Task 5: Build `NewChatRow` with inline persona picker

**Files:**
- Create: `frontend/src/app/components/sidebar/NewChatRow.tsx`
- Test: `frontend/src/app/components/sidebar/__tests__/NewChatRow.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/app/components/sidebar/__tests__/NewChatRow.test.tsx
import { render, screen, fireEvent } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach } from "vitest"
import { NewChatRow } from "../NewChatRow"
import type { PersonaDto } from "../../../../core/types/persona"

const mockNavigate = vi.fn()
vi.mock("react-router-dom", () => ({
  useNavigate: () => mockNavigate,
}))

const mockSanitised = { value: false }
vi.mock("../../../../core/store/sanitisedModeStore", () => ({
  useSanitisedMode: (sel: (s: { isSanitised: boolean }) => unknown) =>
    sel({ isSanitised: mockSanitised.value }),
}))

function p(id: string, name: string, opts: Partial<PersonaDto> = {}): PersonaDto {
  return {
    id,
    name,
    pinned: false,
    nsfw: false,
  } as PersonaDto & typeof opts
}

describe("NewChatRow", () => {
  beforeEach(() => {
    mockNavigate.mockReset()
    mockSanitised.value = false
  })

  it("does not show the persona panel by default", () => {
    render(<NewChatRow personas={[p("a", "Alice")]} onCloseModal={() => {}} />)
    expect(screen.queryByText("Alice")).not.toBeInTheDocument()
  })

  it("expands to show personas (pinned first), navigates on click, and collapses", () => {
    const personas = [
      p("a", "Alice"),
      p("b", "Bob", { pinned: true }),
    ]
    render(<NewChatRow personas={personas} onCloseModal={() => {}} />)
    fireEvent.click(screen.getByRole("button", { name: /new chat/i }))

    const items = screen.getAllByTestId("new-chat-persona")
    expect(items.map((i) => i.textContent)).toEqual(["Bob", "Alice"])

    fireEvent.click(items[0])
    expect(mockNavigate).toHaveBeenCalledWith("/chat/b?new=1")
    expect(screen.queryByTestId("new-chat-persona")).not.toBeInTheDocument()
  })

  it("hides nsfw personas when sanitised mode is on", () => {
    mockSanitised.value = true
    render(
      <NewChatRow
        personas={[p("a", "Alice", { nsfw: true }), p("b", "Bob")]}
        onCloseModal={() => {}}
      />,
    )
    fireEvent.click(screen.getByRole("button", { name: /new chat/i }))
    expect(screen.queryByText("Alice")).not.toBeInTheDocument()
    expect(screen.getByText("Bob")).toBeInTheDocument()
  })

  it("shows an empty state when no personas are available", () => {
    render(<NewChatRow personas={[]} onCloseModal={() => {}} />)
    fireEvent.click(screen.getByRole("button", { name: /new chat/i }))
    expect(screen.getByText(/no personas available/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/app/components/sidebar/__tests__/NewChatRow.test.tsx`
Expected: FAIL — `NewChatRow` does not exist.

- [ ] **Step 3: Implement `NewChatRow.tsx`**

```tsx
// frontend/src/app/components/sidebar/NewChatRow.tsx
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { PersonaDto } from '../../../core/types/persona'
import { useSanitisedMode } from '../../../core/store/sanitisedModeStore'
import { sortPersonas } from './personaSort'

interface NewChatRowProps {
  personas: PersonaDto[]
  onCloseModal: () => void
}

export function NewChatRow({ personas, onCloseModal }: NewChatRowProps) {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const isSanitised = useSanitisedMode((s) => s.isSanitised)

  const visible = useMemo(() => {
    const filtered = isSanitised ? personas.filter((p) => !p.nsfw) : personas
    return sortPersonas(filtered)
  }, [personas, isSanitised])

  function startNewChat(persona: PersonaDto) {
    onCloseModal()
    setOpen(false)
    navigate(`/chat/${persona.id}?new=1`)
  }

  return (
    <div className="flex-shrink-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="group mx-2 mt-1 flex w-[calc(100%-16px)] items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-white/5"
      >
        <span className="text-[14px]">🪶</span>
        <span className="flex-1 text-[12px] font-medium uppercase tracking-wider text-white/70 group-hover:text-white/90">
          New Chat
        </span>
        <span className="text-[10px] text-white/40">{open ? '∨' : '›'}</span>
      </button>

      {open && (
        <div className="mx-2 mt-0.5 mb-1 rounded-md border border-white/6 bg-white/2 py-1">
          {visible.length === 0 ? (
            <p className="px-3 py-1 text-[11px] text-white/40">No personas available</p>
          ) : (
            visible.map((persona) => (
              <button
                key={persona.id}
                type="button"
                data-testid="new-chat-persona"
                onClick={() => startNewChat(persona)}
                className="flex w-full items-center gap-2 px-3 py-1 text-left text-[12px] text-white/80 transition-colors hover:bg-white/6"
              >
                {persona.name}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm vitest run src/app/components/sidebar/__tests__/NewChatRow.test.tsx`
Expected: PASS (all 4 cases).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/sidebar/NewChatRow.tsx \
        frontend/src/app/components/sidebar/__tests__/NewChatRow.test.tsx
git commit -m "Add NewChatRow sidebar component with inline persona picker"
```

---

### Task 6: Mount `NewChatRow` in `Sidebar.tsx`

**Files:**
- Modify: `frontend/src/app/components/sidebar/Sidebar.tsx`

- [ ] **Step 1: Import the component**

Near the top of `Sidebar.tsx`, with the other sidebar imports, add:

```tsx
import { NewChatRow } from './NewChatRow'
```

- [ ] **Step 2: Render it above the PERSONAS section**

Find the `{/* PERSONAS */}` block (around line 663). Immediately above the line `<div className="mt-1.5 flex-shrink-0">`, insert the new component. The order in the rendered tree should be:

1. Admin banner (existing, conditional on `isAdmin`)
2. **NewChatRow (new)**
3. PERSONAS block (existing)

```tsx
{/* New Chat */}
<NewChatRow personas={personas} onCloseModal={onCloseModal} />

{/* PERSONAS */}
<div className="mt-1.5 flex-shrink-0">
  <NavRow icon="💞" label="Personas" onClick={() => { onCloseModal(); navigate("/personas") }} />
  ...
```

- [ ] **Step 3: Build check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: No errors.

- [ ] **Step 4: Run sidebar tests**

Run: `cd frontend && pnpm vitest run src/app/components/sidebar`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/sidebar/Sidebar.tsx
git commit -m "Mount NewChatRow above personas section in sidebar"
```

---

## Part 3 — Final Verification

### Task 7: Full build & test sweep

- [ ] **Step 1: Run the full vitest suite**

Run: `cd frontend && pnpm vitest run`
Expected: All tests pass.

- [ ] **Step 2: Run the production build**

Run: `cd frontend && pnpm run build`
Expected: Clean build, no TypeScript errors.

- [ ] **Step 3: Manual smoke check (note for the implementer)**

Open the running app and verify:

1. Persona editor → for a persona whose primary model has no vision support, the "Vision fallback" section now shows a clickable button (not a native dropdown). Clicking opens the model picker; the V (vision) toggle is highlighted and disabled; only vision-capable models appear; selecting one updates the trigger label; "Clear" resets to "No fallback".
2. Sidebar (expanded) → "🪶 New Chat" row appears between the Admin banner (if admin) and the Personas section. Clicking expands the inline panel showing personas pinned-first. Clicking a persona navigates to `/chat/<id>?new=1` and the panel collapses. Toggling sanitised mode hides NSFW personas from the panel.

- [ ] **Step 4: No commit needed if step 1 and 2 pass cleanly.** If the build surfaces unrelated lint/type issues, fix them in a separate commit and document briefly.

---

## Notes for the implementer

- All work is frontend-only. Do not touch the backend.
- The third reported point (disabling reasoning during vision-fallback description) is **already implemented** at `backend/modules/chat/_vision_fallback.py:100` (`reasoning_enabled=False`). No code change required; mentioned in the spec for traceability.
- Use British English in comments and identifiers (per `CLAUDE.md`).
- Do not introduce new abstractions beyond `lockedFilters` and the extracted `sortPersonas`. Keep the diff focused.

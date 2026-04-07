# UserModal Personas Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a sortable, pin-able `Personas` tab to `UserModal` between `about-me` and `projects`, and show the bound model on the persona overview page.

**Architecture:** A new `PersonasTab.tsx` reuses the existing `usePersonas` hook (state, reorder, update) and the existing sanitised-mode store for filtering. Drag/drop via `@dnd-kit/sortable` (`verticalListSortingStrategy`). Row click closes the modal and opens the persona overlay via a new `onOpenPersonaOverlay` prop threaded through `UserModal` from `AppLayout`. `OverviewTab.tsx` gains a single mono-styled model line.

**Tech Stack:** React, TypeScript, Tailwind CSS, `@dnd-kit/core`, `@dnd-kit/sortable`, Vitest + React Testing Library.

**Spec:** `docs/superpowers/specs/2026-04-07-user-modal-personas-tab-design.md`

---

## File Structure

Create:
- `frontend/src/app/components/user-modal/PersonasTab.tsx` — the new tab
- `frontend/src/app/components/user-modal/__tests__/PersonasTab.test.tsx` — tests

Modify:
- `frontend/src/app/components/user-modal/UserModal.tsx` — register tab, thread `onOpenPersonaOverlay`
- `frontend/src/app/components/user-modal/UserModal.test.tsx` — adjust to new tab id
- `frontend/src/app/layouts/AppLayout.tsx` — pass `onOpenPersonaOverlay` to `UserModal`
- `frontend/src/app/components/persona-overlay/OverviewTab.tsx` — model line under tagline

---

## Task 1: Thread `onOpenPersonaOverlay` through `UserModal`

**Files:**
- Modify: `frontend/src/app/components/user-modal/UserModal.tsx`
- Modify: `frontend/src/app/layouts/AppLayout.tsx`

This is a structural prerequisite — `PersonasTab` will need to open the persona overlay, which lives at `AppLayout` level. We add the prop now so the tab implementation in Task 3 can consume it.

- [ ] **Step 1: Extend `UserModalProps` and forward the callback**

In `UserModal.tsx`, add `onOpenPersonaOverlay` to the props and (later) pass it to `<PersonasTab>`. For now, just declare it.

```tsx
interface UserModalProps {
  activeTab: UserModalTab
  onClose: () => void
  onTabChange: (tab: UserModalTab) => void
  displayName: string
  hasApiKeyProblem: boolean
  onProvidersChanged: (providers: ProviderCredentialDto[]) => void
  onOpenPersonaOverlay: (personaId: string) => void
}
```

Destructure it in the component signature:

```tsx
export function UserModal({
  activeTab,
  onClose,
  onTabChange,
  displayName,
  hasApiKeyProblem,
  onProvidersChanged,
  onOpenPersonaOverlay,
}: UserModalProps) {
```

- [ ] **Step 2: Pass it from `AppLayout.tsx`**

Locate the `<UserModal …/>` mount around line 206 and add the new prop:

```tsx
<UserModal
  activeTab={modalTab}
  onClose={closeModal}
  onTabChange={setModalTab}
  displayName={displayName}
  hasApiKeyProblem={hasApiKeyProblem}
  onProvidersChanged={setProviders}
  onOpenPersonaOverlay={(id) => {
    closeModal()
    openPersonaOverlay(id, "overview")
  }}
/>
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: PASS (0 errors). The new prop is required, and we just added it on the call site.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/user-modal/UserModal.tsx frontend/src/app/layouts/AppLayout.tsx
git commit -m "UserModal: thread onOpenPersonaOverlay prop from AppLayout"
```

---

## Task 2: Register the `personas` tab id

**Files:**
- Modify: `frontend/src/app/components/user-modal/UserModal.tsx`
- Modify: `frontend/src/app/components/user-modal/UserModal.test.tsx`

Adds the tab id and label only — the actual `PersonasTab` component is built in Task 3. Until then we render a placeholder so the modal still compiles.

- [ ] **Step 1: Extend the union and TABS array**

In `UserModal.tsx`:

```tsx
export type UserModalTab =
  | 'about-me'
  | 'personas'
  | 'projects'
  | 'history'
  | 'knowledge'
  | 'bookmarks'
  | 'uploads'
  | 'artefacts'
  | 'models'
  | 'settings'
  | 'api-keys'

const TABS: Tab[] = [
  { id: 'about-me', label: 'About me' },
  { id: 'personas', label: 'Personas' },
  { id: 'projects', label: 'Projects' },
  { id: 'history', label: 'History' },
  { id: 'knowledge', label: 'Knowledge' },
  { id: 'bookmarks', label: 'Bookmarks' },
  { id: 'uploads', label: 'Uploads' },
  { id: 'artefacts', label: 'Artefacts' },
  { id: 'models', label: 'Models' },
  { id: 'settings', label: 'Settings' },
  { id: 'api-keys', label: 'API-Keys' },
]
```

- [ ] **Step 2: Render a placeholder branch**

Just below `{activeTab === 'about-me' && <AboutMeTab />}` add:

```tsx
{activeTab === 'personas' && <div data-testid="personas-tab-placeholder" />}
```

This is replaced in Task 3 with the real component import.

- [ ] **Step 3: Update `UserModal.test.tsx` if it asserts the tab list**

Check:

```bash
rg -n "TABS|about-me|personas" frontend/src/app/components/user-modal/UserModal.test.tsx
```

If it counts tabs or matches against the label list, add `'Personas'` to the expected list. If it does not, no change required.

- [ ] **Step 4: Build + tests**

```bash
cd frontend && pnpm tsc --noEmit && pnpm test -- UserModal.test
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/user-modal/UserModal.tsx frontend/src/app/components/user-modal/UserModal.test.tsx
git commit -m "UserModal: register personas tab id and placeholder"
```

---

## Task 3: Build `PersonasTab` — non-DnD core (TDD)

**Files:**
- Create: `frontend/src/app/components/user-modal/PersonasTab.tsx`
- Create: `frontend/src/app/components/user-modal/__tests__/PersonasTab.test.tsx`

Build the row layout, sorting (pinned-first then `display_order`), sanitised-mode filtering, click→open-overlay, pin toggle. Drag/drop is added in Task 4.

The hook to use is `usePersonas()` from `frontend/src/core/hooks/usePersonas.ts`, which returns `{ personas, reorder, update }` (confirmed by `PersonasPage.tsx:21`). Sanitised-mode store: `useSanitisedMode((s) => s.isSanitised)`. Chakra palette: `import { CHAKRA_PALETTE } from '../../../core/types/chakra'`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/app/components/user-modal/__tests__/PersonasTab.test.tsx`:

```tsx
import { render, screen, fireEvent, within } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { PersonasTab } from '../PersonasTab'

const mockReorder = vi.fn()
const mockUpdate = vi.fn()
let mockPersonas: any[] = []
let mockSanitised = false

vi.mock('../../../../core/hooks/usePersonas', () => ({
  usePersonas: () => ({ personas: mockPersonas, reorder: mockReorder, update: mockUpdate }),
}))
vi.mock('../../../../core/store/sanitisedModeStore', () => ({
  useSanitisedMode: (sel: any) => sel({ isSanitised: mockSanitised }),
}))

function makePersona(overrides: any = {}) {
  return {
    id: 'p1',
    name: 'Aria',
    monogram: 'AR',
    tagline: 'A kind voice',
    profile_image: false,
    profile_crop: null,
    colour_scheme: 'crown' as const,
    model_unique_id: 'ollama_cloud:llama3.2',
    display_order: 0,
    pinned: false,
    nsfw: false,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  }
}

beforeEach(() => {
  mockReorder.mockReset()
  mockUpdate.mockReset()
  mockPersonas = []
  mockSanitised = false
})

describe('PersonasTab', () => {
  it('renders personas in pinned-first then display_order ascending', () => {
    mockPersonas = [
      makePersona({ id: 'a', name: 'Alpha', display_order: 2, pinned: false }),
      makePersona({ id: 'b', name: 'Beta', display_order: 0, pinned: false }),
      makePersona({ id: 'c', name: 'Gamma', display_order: 5, pinned: true }),
    ]
    render(<PersonasTab onOpenPersonaOverlay={vi.fn()} />)
    const rows = screen.getAllByTestId('persona-row')
    expect(rows.map((r) => r.getAttribute('data-persona-id'))).toEqual(['c', 'b', 'a'])
  })

  it('hides nsfw personas in sanitised mode', () => {
    mockSanitised = true
    mockPersonas = [
      makePersona({ id: 'a', name: 'Alpha', nsfw: false }),
      makePersona({ id: 'b', name: 'Beta', nsfw: true }),
    ]
    render(<PersonasTab onOpenPersonaOverlay={vi.fn()} />)
    expect(screen.queryByText('Beta')).not.toBeInTheDocument()
    expect(screen.getByText('Alpha')).toBeInTheDocument()
  })

  it('renders model identifier in monospace', () => {
    mockPersonas = [makePersona({ model_unique_id: 'ollama_cloud:llama3.2' })]
    render(<PersonasTab onOpenPersonaOverlay={vi.fn()} />)
    expect(screen.getByText('llama3.2')).toBeInTheDocument()
  })

  it('row click opens overlay with persona id', () => {
    const onOpen = vi.fn()
    mockPersonas = [makePersona({ id: 'p1' })]
    render(<PersonasTab onOpenPersonaOverlay={onOpen} />)
    fireEvent.click(screen.getByTestId('persona-row-body'))
    expect(onOpen).toHaveBeenCalledWith('p1')
  })

  it('pin toggle calls update with inverted pinned and does not trigger row click', () => {
    const onOpen = vi.fn()
    mockPersonas = [makePersona({ id: 'p1', pinned: false })]
    render(<PersonasTab onOpenPersonaOverlay={onOpen} />)
    fireEvent.click(screen.getByTestId('persona-pin-toggle'))
    expect(mockUpdate).toHaveBeenCalledWith('p1', { pinned: true })
    expect(onOpen).not.toHaveBeenCalled()
  })

  it('shows nsfw indicator when not sanitised and persona is nsfw', () => {
    mockPersonas = [makePersona({ id: 'p1', nsfw: true })]
    render(<PersonasTab onOpenPersonaOverlay={vi.fn()} />)
    expect(screen.getByTestId('persona-nsfw-indicator')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the failing test**

```bash
cd frontend && pnpm test -- PersonasTab.test
```

Expected: FAIL — module `../PersonasTab` not found.

- [ ] **Step 3: Write `PersonasTab.tsx` (no DnD yet)**

Create `frontend/src/app/components/user-modal/PersonasTab.tsx`:

```tsx
import { useMemo } from 'react'
import { usePersonas } from '../../../core/hooks/usePersonas'
import { useSanitisedMode } from '../../../core/store/sanitisedModeStore'
import { CHAKRA_PALETTE } from '../../../core/types/chakra'
import { CroppedAvatar } from '../avatar-crop/CroppedAvatar'
import type { PersonaDto } from '../../../core/types/persona'

interface PersonasTabProps {
  onOpenPersonaOverlay: (personaId: string) => void
}

function sortPersonas(list: PersonaDto[]): PersonaDto[] {
  return [...list].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1
    return a.display_order - b.display_order
  })
}

export function PersonasTab({ onOpenPersonaOverlay }: PersonasTabProps) {
  const { personas, update } = usePersonas()
  const isSanitised = useSanitisedMode((s) => s.isSanitised)

  const visible = useMemo(() => {
    const filtered = isSanitised ? personas.filter((p) => !p.nsfw) : personas
    return sortPersonas(filtered)
  }, [personas, isSanitised])

  return (
    <div className="flex flex-col gap-2 p-4">
      {visible.map((persona) => (
        <PersonaRow
          key={persona.id}
          persona={persona}
          onOpen={() => onOpenPersonaOverlay(persona.id)}
          onTogglePin={() => update(persona.id, { pinned: !persona.pinned })}
        />
      ))}
    </div>
  )
}

interface PersonaRowProps {
  persona: PersonaDto
  onOpen: () => void
  onTogglePin: () => void
}

function PersonaRow({ persona, onOpen, onTogglePin }: PersonaRowProps) {
  const chakra = CHAKRA_PALETTE[persona.colour_scheme]
  const modelLabel = persona.model_unique_id.split(':').slice(1).join(':')

  return (
    <div
      data-testid="persona-row"
      data-persona-id={persona.id}
      className="flex items-center gap-3 rounded-lg px-3 py-2 transition-colors hover:bg-white/5"
      style={{ border: `1px solid ${chakra.hex}22` }}
    >
      {/* Drag handle placeholder — wired up in Task 4 */}
      <span
        data-testid="persona-drag-handle"
        className="cursor-grab select-none text-white/30"
        aria-hidden
      >
        ≡
      </span>

      {/* Avatar / monogram */}
      <div
        className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full"
        style={{ background: `${chakra.hex}22`, border: `1px solid ${chakra.hex}55` }}
      >
        {persona.profile_image ? (
          <CroppedAvatar
            personaId={persona.id}
            updatedAt={persona.updated_at}
            crop={persona.profile_crop}
            size={28}
            alt={persona.name}
          />
        ) : (
          <span className="text-[11px] font-semibold" style={{ color: chakra.hex }}>
            {persona.monogram}
          </span>
        )}
      </div>

      {/* Click body — name / tagline / model */}
      <button
        type="button"
        data-testid="persona-row-body"
        onClick={onOpen}
        className="flex min-w-0 flex-1 flex-col items-start text-left"
      >
        <span className="truncate text-[13px] font-medium text-white/90">{persona.name}</span>
        {persona.tagline && (
          <span className="truncate text-[11px] text-white/45">{persona.tagline}</span>
        )}
        <span
          className="truncate font-mono text-[10px]"
          style={{ color: chakra.hex + '4d', letterSpacing: '0.5px' }}
        >
          {modelLabel}
        </span>
      </button>

      {/* NSFW marker (only when not sanitised — sanitised already filters out nsfw rows) */}
      {persona.nsfw && (
        <span
          data-testid="persona-nsfw-indicator"
          className="text-[14px]"
          aria-label="NSFW"
          title="NSFW"
        >
          💋
        </span>
      )}

      {/* Pin toggle */}
      <button
        type="button"
        data-testid="persona-pin-toggle"
        onClick={(e) => {
          e.stopPropagation()
          onTogglePin()
        }}
        className="rounded p-1 transition-colors"
        style={{
          color: persona.pinned ? chakra.hex : 'rgba(255,255,255,0.2)',
          background: persona.pinned ? chakra.hex + '1a' : 'transparent',
        }}
        aria-label={persona.pinned ? 'Unpin' : 'Pin'}
        title={persona.pinned ? 'Unpin' : 'Pin'}
      >
        📌
      </button>
    </div>
  )
}
```

- [ ] **Step 4: Run the tests, expect PASS**

```bash
cd frontend && pnpm test -- PersonasTab.test
```

Expected: all 6 tests PASS. If any fail because `usePersonas` import path differs, fix the mocked path to match the actual import in `PersonasTab.tsx`.

- [ ] **Step 5: Wire `PersonasTab` into `UserModal` (replace placeholder)**

In `UserModal.tsx`, add:

```tsx
import { PersonasTab } from './PersonasTab'
```

Replace the placeholder branch from Task 2:

```tsx
{activeTab === 'personas' && <PersonasTab onOpenPersonaOverlay={onOpenPersonaOverlay} />}
```

- [ ] **Step 6: Type-check**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/components/user-modal/PersonasTab.tsx frontend/src/app/components/user-modal/__tests__/PersonasTab.test.tsx frontend/src/app/components/user-modal/UserModal.tsx
git commit -m "UserModal: add PersonasTab with sort, filter, pin, click-to-open"
```

---

## Task 4: Add drag & drop reordering

**Files:**
- Modify: `frontend/src/app/components/user-modal/PersonasTab.tsx`
- Modify: `frontend/src/app/components/user-modal/__tests__/PersonasTab.test.tsx`

The `usePersonas` hook already exposes `reorder(orderedIds)` which calls `PATCH /personas/reorder`. We wrap the rows in `DndContext` + `SortableContext` and call `reorder` on drag-end.

- [ ] **Step 1: Add the failing reorder test**

Append to `PersonasTab.test.tsx`:

```tsx
  it('reorder via drag-end calls reorder with new order', async () => {
    mockPersonas = [
      makePersona({ id: 'a', name: 'Alpha', display_order: 0 }),
      makePersona({ id: 'b', name: 'Beta', display_order: 1 }),
      makePersona({ id: 'c', name: 'Gamma', display_order: 2 }),
    ]
    const { container } = render(<PersonasTab onOpenPersonaOverlay={vi.fn()} />)
    // Use the exposed test helper to drive a synthetic reorder.
    const helper = (window as any).__personasTabTestHelper
    expect(helper).toBeDefined()
    helper.simulateReorder('a', 'c')
    expect(mockReorder).toHaveBeenCalledWith(['b', 'c', 'a'])
  })
```

> Why a window helper rather than synthetic pointer events: `@dnd-kit` is notoriously hard to drive in jsdom (it relies on `PointerEvent` plus timers). The handler logic is the bit we care about; we expose a tiny test seam that calls the *same* `handleDragEnd` the DnD context calls. Bookmarks tab uses the same approach informally — see `BookmarksTab.tsx`.

- [ ] **Step 2: Run the failing test**

```bash
cd frontend && pnpm test -- PersonasTab.test
```

Expected: FAIL — `__personasTabTestHelper` is undefined.

- [ ] **Step 3: Add DnD wiring + the test seam**

Modify `PersonasTab.tsx`. New imports at the top:

```tsx
import { useEffect } from 'react'
import {
  DndContext,
  closestCenter,
  type DragEndEvent,
} from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy, useSortable, arrayMove } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { zoomModifiers } from '../../../core/utils/dndZoomModifier'
```

Pull `reorder` from the hook:

```tsx
const { personas, update, reorder } = usePersonas()
```

Replace the body of `PersonasTab` (the `return` block) with:

```tsx
  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const oldIndex = visible.findIndex((p) => p.id === active.id)
    const newIndex = visible.findIndex((p) => p.id === over.id)
    if (oldIndex === -1 || newIndex === -1) return
    const reordered = arrayMove(visible, oldIndex, newIndex)
    reorder(reordered.map((p) => p.id))
  }

  // Test seam — exposes the same handler the DndContext uses, so unit tests
  // can drive reorder logic without simulating jsdom pointer events.
  useEffect(() => {
    if (typeof window === 'undefined') return
    ;(window as any).__personasTabTestHelper = {
      simulateReorder: (activeId: string, overId: string) => {
        handleDragEnd({ active: { id: activeId }, over: { id: overId } } as unknown as DragEndEvent)
      },
    }
    return () => {
      delete (window as any).__personasTabTestHelper
    }
  })

  return (
    <div className="flex flex-col gap-2 p-4">
      <DndContext collisionDetection={closestCenter} onDragEnd={handleDragEnd} modifiers={zoomModifiers}>
        <SortableContext items={visible.map((p) => p.id)} strategy={verticalListSortingStrategy}>
          {visible.map((persona) => (
            <SortablePersonaRow
              key={persona.id}
              persona={persona}
              onOpen={() => onOpenPersonaOverlay(persona.id)}
              onTogglePin={() => update(persona.id, { pinned: !persona.pinned })}
            />
          ))}
        </SortableContext>
      </DndContext>
    </div>
  )
}

function SortablePersonaRow(props: PersonaRowProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: props.persona.id,
  })
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }
  return (
    <div ref={setNodeRef} style={style}>
      <PersonaRow {...props} dragAttributes={attributes} dragListeners={listeners} />
    </div>
  )
}
```

Update `PersonaRowProps` and the drag handle in `PersonaRow` to consume the listeners:

```tsx
import type { DraggableAttributes, DraggableSyntheticListeners } from '@dnd-kit/core'

interface PersonaRowProps {
  persona: PersonaDto
  onOpen: () => void
  onTogglePin: () => void
  dragAttributes?: DraggableAttributes
  dragListeners?: DraggableSyntheticListeners
}
```

In `PersonaRow`, replace the static drag handle span with:

```tsx
      <span
        data-testid="persona-drag-handle"
        className="cursor-grab select-none text-white/30"
        aria-hidden
        {...(dragAttributes ?? {})}
        {...(dragListeners ?? {})}
      >
        ≡
      </span>
```

And destructure the new props in the row:

```tsx
function PersonaRow({ persona, onOpen, onTogglePin, dragAttributes, dragListeners }: PersonaRowProps) {
```

- [ ] **Step 4: Run the tests, expect PASS**

```bash
cd frontend && pnpm test -- PersonasTab.test
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Type-check + full build**

```bash
cd frontend && pnpm tsc --noEmit && pnpm run build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/components/user-modal/PersonasTab.tsx frontend/src/app/components/user-modal/__tests__/PersonasTab.test.tsx
git commit -m "PersonasTab: add drag-and-drop reordering via dnd-kit"
```

---

## Task 5: Show model on persona overview page

**Files:**
- Modify: `frontend/src/app/components/persona-overlay/OverviewTab.tsx`

Add a single mono-styled line directly under the tagline, identical to the card style.

- [ ] **Step 1: Edit `OverviewTab.tsx`**

Locate the name + tagline block (around the existing `<h2>...{persona.name}</h2>` and tagline `<p>`) and append a model line within the same `flex flex-col items-center gap-1` container:

```tsx
      {/* Name + tagline + model */}
      <div className="flex flex-col items-center gap-1 text-center">
        <h2 className="text-[18px] font-semibold text-white/90">{persona.name}</h2>
        {persona.tagline && (
          <p className="text-[13px] text-white/45 max-w-xs">{persona.tagline}</p>
        )}
        <p
          className="font-mono text-[11px]"
          style={{ color: chakra.hex + '4d', letterSpacing: '0.5px' }}
        >
          {persona.model_unique_id.split(':').slice(1).join(':')}
        </p>
      </div>
```

- [ ] **Step 2: Type-check + build**

```bash
cd frontend && pnpm tsc --noEmit && pnpm run build
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/components/persona-overlay/OverviewTab.tsx
git commit -m "PersonaOverview: show bound model in chakra-toned mono under tagline"
```

---

## Task 6: Final verification + merge to master

- [ ] **Step 1: Run the full frontend test suite + build**

```bash
cd frontend && pnpm tsc --noEmit && pnpm test && pnpm run build
```

Expected: all tests PASS, build clean.

- [ ] **Step 2: Manual smoke (describe to user)**

Tell the user to:
1. Open UserModal → Personas tab
2. Verify ordering (pinned first, display_order ascending)
3. Toggle a pin → row reorders live
4. Drag a row → order persists after reload
5. Click a row → modal closes, persona overlay opens on Overview
6. Toggle sanitised mode → NSFW personas vanish
7. Persona overview now shows the model under the tagline

- [ ] **Step 3: Merge to master**

```bash
git checkout master
git merge --no-ff -
git push origin master
```

(Or, if working directly on master, the per-task commits are already in place — skip the merge.)

---

## Spec Coverage Check

| Spec section | Implemented in |
|---|---|
| New `personas` tab between about-me/projects | Task 2 |
| Reuses existing personas state, no new fetch | Task 3 (uses `usePersonas`) |
| Sanitised mode filters out NSFW rows entirely | Task 3 (test + impl) |
| Row layout with drag, monogram, avatar, name, tagline, model, NSFW, pin | Tasks 3 + 4 |
| Model in mono `chakra.hex + "4d"` with `split(":").slice(1).join(":")` | Task 3 |
| Click row → close modal + open overlay on overview | Tasks 1 + 3 |
| Drag end → `bulk_reorder` via existing route | Task 4 (`reorder` from hook) |
| Pin toggle via existing update route | Task 3 |
| OverviewTab shows model identically | Task 5 |
| `pnpm tsc --noEmit` and `pnpm run build` clean | Tasks 4, 5, 6 |

# Mobile-Sidebar Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the mobile branch of the sidebar to a fullscreen overlay with a 2-deep in-sidebar stack (New Chat / History / Bookmarks render inside the sidebar instead of as scrolling sections), while leaving the desktop branch untouched and applying a small responsive tweak to the reused History- and Bookmarks-tabs.

**Architecture:** The `Sidebar` component splits into two render branches: desktop (unchanged) and mobile (new). The mobile branch is fullscreen (`w-screen`) and shows either a main view or one of three overlays. State is a single local `mobileView` value in `Sidebar.tsx`. Three new components live in `frontend/src/app/components/sidebar/`. The existing User-Modal `HistoryTab` and `BookmarksTab` get a small responsive tweak (`flex-col sm:flex-row` for the filter row) and are reused as-is from inside the sidebar.

**Tech Stack:** React 18, TypeScript, Tailwind CSS, Vitest, @testing-library/react. CSS-only horizontal slide animation (no animation library).

**Spec:** `devdocs/specs/2026-04-27-mobile-sidebar-redesign-design.md`

---

## File Structure

### New files
- `frontend/src/app/components/sidebar/MobileSidebarHeader.tsx` — 50px top bar with two modes (main / overlay)
- `frontend/src/app/components/sidebar/MobileSidebarHeader.test.tsx`
- `frontend/src/app/components/sidebar/MobileNewChatView.tsx` — persona-list overlay
- `frontend/src/app/components/sidebar/MobileNewChatView.test.tsx`
- `frontend/src/app/components/sidebar/MobileMainView.tsx` — top + spacer + bottom layout
- `frontend/src/app/components/sidebar/MobileMainView.test.tsx`

### Modified files
- `frontend/src/app/components/sidebar/Sidebar.tsx` — split mobile vs desktop branch; add `mobileView` state; render new components in mobile branch; preserve desktop branch verbatim.
- `frontend/src/app/components/sidebar/Sidebar.test.tsx` — extend with mobile-stack tests.
- `frontend/src/app/components/user-modal/HistoryTab.tsx` — filter row becomes `flex-col sm:flex-row`; inputs full-width below `sm`.
- `frontend/src/app/components/user-modal/BookmarksTab.tsx` — same tweak to filter row.

### Unchanged files
- `frontend/src/core/store/drawerStore.ts` — public API and behaviour unchanged.
- `frontend/src/core/store/sidebarStore.ts` — desktop-only collapse state, unchanged.
- `frontend/src/app/components/sidebar/NewChatRow.tsx` — kept for desktop branch only.

---

## Task 1: MobileSidebarHeader component

**Files:**
- Create: `frontend/src/app/components/sidebar/MobileSidebarHeader.tsx`
- Create: `frontend/src/app/components/sidebar/MobileSidebarHeader.test.tsx`

The header has two modes. On the main view it shows the fox + "Chatsune" as a single button that closes the drawer. On overlays it shows `‹ <title>` as a back button. Both modes also show a separate `✕` button on the right that always calls `onClose`.

- [ ] **Step 1.1: Write failing tests**

Create `frontend/src/app/components/sidebar/MobileSidebarHeader.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MobileSidebarHeader } from './MobileSidebarHeader'

describe('MobileSidebarHeader — main view', () => {
  it('renders the logo + Chatsune label', () => {
    render(<MobileSidebarHeader onClose={() => {}} />)
    expect(screen.getByText('Chatsune')).toBeInTheDocument()
  })

  it('calls onClose when the logo area is clicked', async () => {
    const onClose = vi.fn()
    render(<MobileSidebarHeader onClose={onClose} />)
    await userEvent.click(screen.getByRole('button', { name: /close sidebar/i }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('calls onClose when the ✕ button is clicked', async () => {
    const onClose = vi.fn()
    render(<MobileSidebarHeader onClose={onClose} />)
    await userEvent.click(screen.getByRole('button', { name: /close drawer/i }))
    expect(onClose).toHaveBeenCalledOnce()
  })
})

describe('MobileSidebarHeader — overlay mode', () => {
  it('renders title and back arrow when title is provided', () => {
    render(<MobileSidebarHeader title="New Chat" onBack={() => {}} onClose={() => {}} />)
    expect(screen.getByText('New Chat')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /back to main/i })).toBeInTheDocument()
  })

  it('calls onBack — not onClose — when the back area is clicked', async () => {
    const onBack = vi.fn()
    const onClose = vi.fn()
    render(<MobileSidebarHeader title="History" onBack={onBack} onClose={onClose} />)
    await userEvent.click(screen.getByRole('button', { name: /back to main/i }))
    expect(onBack).toHaveBeenCalledOnce()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('calls onClose when the ✕ button is clicked', async () => {
    const onBack = vi.fn()
    const onClose = vi.fn()
    render(<MobileSidebarHeader title="History" onBack={onBack} onClose={onClose} />)
    await userEvent.click(screen.getByRole('button', { name: /close drawer/i }))
    expect(onClose).toHaveBeenCalledOnce()
    expect(onBack).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run from project root:
```bash
docker compose -f docker-compose.dev.yml run --rm frontend pnpm vitest run src/app/components/sidebar/MobileSidebarHeader.test.tsx
```

Expected: Tests fail with `Cannot find module './MobileSidebarHeader'`.

If Docker is not the local convention here, an equivalent direct invocation also works:
```bash
cd frontend && pnpm vitest run src/app/components/sidebar/MobileSidebarHeader.test.tsx
```

- [ ] **Step 1.3: Implement the component**

Create `frontend/src/app/components/sidebar/MobileSidebarHeader.tsx`:

```tsx
interface MobileSidebarHeaderProps {
  /** When set, the header is in overlay mode showing back-arrow + title. */
  title?: string
  /** Required when title is set — handles back-navigation to main view. */
  onBack?: () => void
  /** Always required — closes the entire mobile drawer. */
  onClose: () => void
}

export function MobileSidebarHeader({ title, onBack, onClose }: MobileSidebarHeaderProps) {
  const isOverlay = title !== undefined

  return (
    <div className="flex h-[50px] flex-shrink-0 items-center gap-1 border-b border-white/5 px-3.5">
      {isOverlay ? (
        <button
          type="button"
          onClick={onBack}
          aria-label="Back to main"
          className="flex flex-1 min-h-[44px] items-center gap-2.5 rounded-md -mx-1 px-1 py-0.5 text-left transition-colors hover:bg-white/5"
        >
          <span className="text-[18px] text-white/60">‹</span>
          <span className="flex-1 text-[15px] font-semibold tracking-wide text-white/85">{title}</span>
        </button>
      ) : (
        <button
          type="button"
          onClick={onClose}
          aria-label="Close sidebar"
          className="flex flex-1 min-h-[44px] items-center gap-2.5 rounded-md -mx-1 px-1 py-0.5 text-left transition-colors hover:bg-white/5"
        >
          <span className="text-[17px]">🦊</span>
          <span className="flex-1 text-[15px] font-semibold tracking-wide text-white/85">Chatsune</span>
        </button>
      )}

      <button
        type="button"
        onClick={onClose}
        aria-label="Close drawer"
        className="flex h-7 w-7 items-center justify-center rounded text-[14px] text-white/60 transition-colors hover:bg-white/8 hover:text-white/85"
      >
        ✕
      </button>
    </div>
  )
}
```

- [ ] **Step 1.4: Run tests to verify they pass**

```bash
cd frontend && pnpm vitest run src/app/components/sidebar/MobileSidebarHeader.test.tsx
```

Expected: All 6 tests pass.

- [ ] **Step 1.5: Commit**

```bash
git add frontend/src/app/components/sidebar/MobileSidebarHeader.tsx \
        frontend/src/app/components/sidebar/MobileSidebarHeader.test.tsx
git commit -m "Add MobileSidebarHeader with main and overlay modes"
```

---

## Task 2: MobileNewChatView component

**Files:**
- Create: `frontend/src/app/components/sidebar/MobileNewChatView.tsx`
- Create: `frontend/src/app/components/sidebar/MobileNewChatView.test.tsx`

A scrollable list of personas with `Pinned` and `Other` sections. NSFW pill on NSFW personas. Sanitised mode filters NSFW out entirely. Tap a row to start a new chat with that persona.

- [ ] **Step 2.1: Write failing tests**

Create `frontend/src/app/components/sidebar/MobileNewChatView.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { MobileNewChatView } from './MobileNewChatView'
import type { PersonaDto } from '../../../core/types/persona'

const aria: PersonaDto = {
  id: 'aria', name: 'Aria', monogram: 'A',
  pinned: true, nsfw: false,
  colour_scheme: 'red',
} as PersonaDto

const lyra: PersonaDto = {
  id: 'lyra', name: 'Lyra', monogram: 'L',
  pinned: true, nsfw: true,
  colour_scheme: 'pink',
} as PersonaDto

const marcus: PersonaDto = {
  id: 'marcus', name: 'Marcus the Stoic', monogram: 'M',
  pinned: false, nsfw: false,
  colour_scheme: 'green',
} as PersonaDto

const thorne: PersonaDto = {
  id: 'thorne', name: 'Thorne', monogram: 'T',
  pinned: false, nsfw: true,
  colour_scheme: 'red',
} as PersonaDto

vi.mock('../../../core/store/sanitisedModeStore', () => ({
  useSanitisedMode: (sel: (s: { isSanitised: boolean }) => unknown) => sel({ isSanitised: false }),
}))

beforeEach(() => {
  vi.clearAllMocks()
})

function renderView(personas: PersonaDto[], onSelect: (p: PersonaDto) => void = () => {}) {
  return render(
    <MemoryRouter>
      <MobileNewChatView personas={personas} onSelect={onSelect} />
    </MemoryRouter>
  )
}

describe('MobileNewChatView — sections', () => {
  it('renders Pinned section header only when pinned personas exist', () => {
    renderView([aria, marcus])
    expect(screen.getByText('Pinned')).toBeInTheDocument()
    expect(screen.getByText('Other')).toBeInTheDocument()
  })

  it('omits Pinned header when no pinned personas', () => {
    renderView([marcus, thorne])
    expect(screen.queryByText('Pinned')).not.toBeInTheDocument()
    expect(screen.getByText('Other')).toBeInTheDocument()
  })

  it('omits Other header when no unpinned personas', () => {
    renderView([aria, lyra])
    expect(screen.getByText('Pinned')).toBeInTheDocument()
    expect(screen.queryByText('Other')).not.toBeInTheDocument()
  })

  it('renders empty-state when no personas at all', () => {
    renderView([])
    expect(screen.getByText(/no personas yet/i)).toBeInTheDocument()
  })
})

describe('MobileNewChatView — NSFW pill', () => {
  it('renders the NSFW pill for NSFW personas', () => {
    renderView([aria, lyra])
    const pills = screen.getAllByText('NSFW')
    expect(pills).toHaveLength(1)
  })

  it('does not render NSFW pill for non-NSFW personas', () => {
    renderView([aria, marcus])
    expect(screen.queryByText('NSFW')).not.toBeInTheDocument()
  })
})

describe('MobileNewChatView — selection', () => {
  it('calls onSelect with the persona when a row is tapped', async () => {
    const onSelect = vi.fn()
    renderView([aria, marcus], onSelect)
    await userEvent.click(screen.getByText('Marcus the Stoic'))
    expect(onSelect).toHaveBeenCalledWith(marcus)
  })
})
```

- [ ] **Step 2.2: Run tests to verify they fail**

```bash
cd frontend && pnpm vitest run src/app/components/sidebar/MobileNewChatView.test.tsx
```

Expected: Tests fail with `Cannot find module './MobileNewChatView'`.

- [ ] **Step 2.3: Implement the component**

Create `frontend/src/app/components/sidebar/MobileNewChatView.tsx`:

```tsx
import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import type { PersonaDto } from '../../../core/types/persona'
import { useSanitisedMode } from '../../../core/store/sanitisedModeStore'
import { CHAKRA_PALETTE } from '../../../core/types/chakra'

interface MobileNewChatViewProps {
  personas: PersonaDto[]
  onSelect: (persona: PersonaDto) => void
}

export function MobileNewChatView({ personas, onSelect }: MobileNewChatViewProps) {
  const isSanitised = useSanitisedMode((s) => s.isSanitised)

  const visible = useMemo(() => {
    return isSanitised ? personas.filter((p) => !p.nsfw) : personas
  }, [personas, isSanitised])

  const pinned = visible.filter((p) => p.pinned)
  const other = visible.filter((p) => !p.pinned)

  if (visible.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
        <p className="mb-3 text-[14px] text-white/60">No personas yet</p>
        <Link
          to="/personas"
          className="rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-[12px] text-white/80 transition-colors hover:bg-white/10"
        >
          Create persona
        </Link>
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto py-1 [&::-webkit-scrollbar]:w-[3px] [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10">
      {pinned.length > 0 && (
        <>
          <div className="px-4 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-widest text-white/45">
            Pinned
          </div>
          {pinned.map((p) => (
            <PersonaRow key={p.id} persona={p} onSelect={onSelect} />
          ))}
        </>
      )}

      {other.length > 0 && (
        <>
          <div className="px-4 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-widest text-white/45">
            Other
          </div>
          {other.map((p) => (
            <PersonaRow key={p.id} persona={p} onSelect={onSelect} />
          ))}
        </>
      )}
    </div>
  )
}

interface PersonaRowProps {
  persona: PersonaDto
  onSelect: (persona: PersonaDto) => void
}

function PersonaRow({ persona, onSelect }: PersonaRowProps) {
  const chakra = CHAKRA_PALETTE[persona.colour_scheme]
  const monogram = persona.monogram || persona.name.charAt(0).toUpperCase()
  return (
    <button
      type="button"
      onClick={() => onSelect(persona)}
      className="flex w-full items-center gap-3 px-3.5 py-2.5 text-left transition-colors hover:bg-white/4"
    >
      <span
        className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full text-[14px] font-semibold"
        style={{
          background: `${chakra.hex}22`,
          border: `1px solid ${chakra.hex}55`,
          color: chakra.hex,
        }}
      >
        {monogram}
      </span>
      <span className="flex-1 truncate text-[14px] text-white/85">{persona.name}</span>
      {persona.nsfw && (
        <span className="flex-shrink-0 rounded-full border border-pink-400/35 bg-pink-400/15 px-1.5 py-[1px] text-[9px] font-semibold uppercase tracking-wider text-pink-200/90">
          NSFW
        </span>
      )}
    </button>
  )
}
```

- [ ] **Step 2.4: Run tests to verify they pass**

```bash
cd frontend && pnpm vitest run src/app/components/sidebar/MobileNewChatView.test.tsx
```

Expected: All 7 tests pass.

- [ ] **Step 2.5: Commit**

```bash
git add frontend/src/app/components/sidebar/MobileNewChatView.tsx \
        frontend/src/app/components/sidebar/MobileNewChatView.test.tsx
git commit -m "Add MobileNewChatView with Pinned/Other sections and NSFW pill"
```

---

## Task 3: HistoryTab responsive filter row

**Files:**
- Modify: `frontend/src/app/components/user-modal/HistoryTab.tsx` (the filter row at lines ~140-161)

The filter row currently uses `flex gap-2` which puts search input and persona dropdown side-by-side. On `< sm` (< 640px) we want them stacked.

- [ ] **Step 3.1: Locate the filter row**

Open `frontend/src/app/components/user-modal/HistoryTab.tsx` and find the block:

```tsx
<div className="px-4 pt-4 pb-2 flex-shrink-0 flex gap-2">
  <input
    type="text"
    value={search}
    onChange={(e) => setSearch(e.target.value)}
    placeholder="Search history..."
    aria-label="Search session history"
    className="flex-1 bg-white/[0.04] border border-white/8 rounded-lg px-3 py-2 text-[13px] text-white/75 placeholder:text-white/30 outline-none focus:border-gold/30 transition-colors font-mono"
  />
  <select
    value={personaFilter}
    onChange={(e) => setPersonaFilter(e.target.value)}
    aria-label="Filter by persona"
    className="bg-surface border border-white/8 rounded-lg px-2 py-1 text-[11px] font-mono text-white/60 outline-none focus:border-gold/40 cursor-pointer appearance-none pr-6"
    ...
  >
```

- [ ] **Step 3.2: Apply the responsive change**

Use Edit to make these two changes:

1. Container className from `flex gap-2` to `flex flex-col sm:flex-row gap-2`.
2. `<select>` className adds `w-full sm:w-auto`.

The replacements:

**old container:**
```
className="px-4 pt-4 pb-2 flex-shrink-0 flex gap-2"
```
**new container:**
```
className="px-4 pt-4 pb-2 flex-shrink-0 flex flex-col sm:flex-row gap-2"
```

**old select className:**
```
className="bg-surface border border-white/8 rounded-lg px-2 py-1 text-[11px] font-mono text-white/60 outline-none focus:border-gold/40 cursor-pointer appearance-none pr-6"
```
**new select className:**
```
className="w-full sm:w-auto bg-surface border border-white/8 rounded-lg px-2 py-1 text-[11px] font-mono text-white/60 outline-none focus:border-gold/40 cursor-pointer appearance-none pr-6"
```

The input `flex-1` already adapts to both column and row layouts.

- [ ] **Step 3.3: Verify with type-check**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: No errors.

- [ ] **Step 3.4: Verify with build**

```bash
cd frontend && pnpm run build
```

Expected: Build succeeds (the stricter `tsc -b` step also passes).

- [ ] **Step 3.5: Commit**

```bash
git add frontend/src/app/components/user-modal/HistoryTab.tsx
git commit -m "Stack History tab filter row vertically below sm breakpoint"
```

---

## Task 4: BookmarksTab responsive filter row

**Files:**
- Modify: `frontend/src/app/components/user-modal/BookmarksTab.tsx` (the filter row at lines ~134-156)

Same change as Task 3, applied to `BookmarksTab.tsx`.

- [ ] **Step 4.1: Apply the responsive change**

In `frontend/src/app/components/user-modal/BookmarksTab.tsx`:

**old container:**
```
className="px-4 pt-4 pb-2 flex-shrink-0 flex gap-2"
```
**new container:**
```
className="px-4 pt-4 pb-2 flex-shrink-0 flex flex-col sm:flex-row gap-2"
```

**old select className:**
```
className="bg-surface border border-white/8 rounded-lg px-2 py-1 text-[11px] font-mono text-white/60 outline-none focus:border-gold/40 cursor-pointer appearance-none pr-6"
```
**new select className:**
```
className="w-full sm:w-auto bg-surface border border-white/8 rounded-lg px-2 py-1 text-[11px] font-mono text-white/60 outline-none focus:border-gold/40 cursor-pointer appearance-none pr-6"
```

- [ ] **Step 4.2: Verify with type-check**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: No errors.

- [ ] **Step 4.3: Commit**

```bash
git add frontend/src/app/components/user-modal/BookmarksTab.tsx
git commit -m "Stack Bookmarks tab filter row vertically below sm breakpoint"
```

---

## Task 5: MobileMainView component

**Files:**
- Create: `frontend/src/app/components/sidebar/MobileMainView.tsx`
- Create: `frontend/src/app/components/sidebar/MobileMainView.test.tsx`

This component renders the contents of the main view (everything below the header) for the mobile sidebar. It is a "presenter" — all handlers and data come in via props. Layout: top section (anchored top, conditional rows), `flex-1` spacer, bottom section (anchored bottom).

- [ ] **Step 5.1: Write failing tests**

Create `frontend/src/app/components/sidebar/MobileMainView.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { MobileMainView } from './MobileMainView'

const baseProps = {
  isAdmin: false,
  isInChat: false,
  hasLastSession: false,
  hasApiKeyProblem: false,
  isSanitised: false,
  displayName: 'Chris',
  role: 'user',
  initial: 'C',
  onAdmin: vi.fn(),
  onContinue: vi.fn(),
  onNewChat: vi.fn(),
  onPersonas: vi.fn(),
  onHistory: vi.fn(),
  onBookmarks: vi.fn(),
  onKnowledge: vi.fn(),
  onMyData: vi.fn(),
  onToggleSanitised: vi.fn(),
  onUserRow: vi.fn(),
  onLogout: vi.fn(),
}

function renderView(overrides: Partial<typeof baseProps> = {}) {
  return render(
    <MemoryRouter>
      <MobileMainView {...baseProps} {...overrides} />
    </MemoryRouter>
  )
}

describe('MobileMainView — conditional rows', () => {
  it('renders Admin row when isAdmin is true', () => {
    renderView({ isAdmin: true })
    expect(screen.getByText('Admin')).toBeInTheDocument()
  })

  it('hides Admin row when isAdmin is false', () => {
    renderView({ isAdmin: false })
    expect(screen.queryByText('Admin')).not.toBeInTheDocument()
  })

  it('renders Continue row when not in chat AND last session exists', () => {
    renderView({ isInChat: false, hasLastSession: true })
    expect(screen.getByText('Continue')).toBeInTheDocument()
  })

  it('hides Continue row when in chat', () => {
    renderView({ isInChat: true, hasLastSession: true })
    expect(screen.queryByText('Continue')).not.toBeInTheDocument()
  })

  it('hides Continue row when no last session', () => {
    renderView({ isInChat: false, hasLastSession: false })
    expect(screen.queryByText('Continue')).not.toBeInTheDocument()
  })

  it('shows API-key alert dot on avatar when hasApiKeyProblem', () => {
    renderView({ hasApiKeyProblem: true })
    expect(screen.getByLabelText(/api key problem/i)).toBeInTheDocument()
  })

  it('omits the alert dot when no problem', () => {
    renderView({ hasApiKeyProblem: false })
    expect(screen.queryByLabelText(/api key problem/i)).not.toBeInTheDocument()
  })
})

describe('MobileMainView — fixed rows render unconditionally', () => {
  it('renders New Chat, Personas, History, Bookmarks', () => {
    renderView()
    expect(screen.getByText('New Chat')).toBeInTheDocument()
    expect(screen.getByText('Personas')).toBeInTheDocument()
    expect(screen.getByText('History')).toBeInTheDocument()
    expect(screen.getByText('Bookmarks')).toBeInTheDocument()
  })

  it('renders Knowledge, My Data, Sanitised, Log out', () => {
    renderView()
    expect(screen.getByText('Knowledge')).toBeInTheDocument()
    expect(screen.getByText('My Data')).toBeInTheDocument()
    expect(screen.getByText('Sanitised')).toBeInTheDocument()
    expect(screen.getByText('Log out')).toBeInTheDocument()
  })
})

describe('MobileMainView — handler wiring', () => {
  it('calls onNewChat when New Chat row is tapped', async () => {
    const onNewChat = vi.fn()
    renderView({ onNewChat })
    await userEvent.click(screen.getByText('New Chat'))
    expect(onNewChat).toHaveBeenCalledOnce()
  })

  it('calls onHistory when History row is tapped', async () => {
    const onHistory = vi.fn()
    renderView({ onHistory })
    await userEvent.click(screen.getByText('History'))
    expect(onHistory).toHaveBeenCalledOnce()
  })

  it('calls onMyData when My Data row is tapped', async () => {
    const onMyData = vi.fn()
    renderView({ onMyData })
    await userEvent.click(screen.getByText('My Data'))
    expect(onMyData).toHaveBeenCalledOnce()
  })

  it('calls onToggleSanitised when Sanitised row is tapped', async () => {
    const onToggleSanitised = vi.fn()
    renderView({ onToggleSanitised })
    await userEvent.click(screen.getByText('Sanitised'))
    expect(onToggleSanitised).toHaveBeenCalledOnce()
  })

  it('calls onLogout when Log out row is tapped', async () => {
    const onLogout = vi.fn()
    renderView({ onLogout })
    await userEvent.click(screen.getByText('Log out'))
    expect(onLogout).toHaveBeenCalledOnce()
  })
})
```

- [ ] **Step 5.2: Run tests to verify they fail**

```bash
cd frontend && pnpm vitest run src/app/components/sidebar/MobileMainView.test.tsx
```

Expected: Tests fail with `Cannot find module './MobileMainView'`.

- [ ] **Step 5.3: Implement the component**

Create `frontend/src/app/components/sidebar/MobileMainView.tsx`:

```tsx
interface MobileMainViewProps {
  isAdmin: boolean
  isInChat: boolean
  hasLastSession: boolean
  hasApiKeyProblem: boolean
  isSanitised: boolean
  displayName: string
  role: string
  initial: string
  onAdmin: () => void
  onContinue: () => void
  onNewChat: () => void
  onPersonas: () => void
  onHistory: () => void
  onBookmarks: () => void
  onKnowledge: () => void
  onMyData: () => void
  onToggleSanitised: () => void
  onUserRow: () => void
  onLogout: () => void
}

export function MobileMainView(props: MobileMainViewProps) {
  return (
    <div className="flex h-full flex-col">
      {/* Top section */}
      <div className="flex-shrink-0 pt-2">
        {props.isAdmin && (
          <>
            <button
              type="button"
              onClick={props.onAdmin}
              className="mx-3 flex w-[calc(100%-24px)] items-center gap-2 rounded-lg border border-gold/16 bg-gold/7 px-2.5 py-1.5 transition-colors hover:bg-gold/12"
            >
              <span className="text-[12px]">🪄</span>
              <span className="flex-1 text-left text-[12px] font-bold uppercase tracking-widest text-gold">
                Admin
              </span>
              <span className="text-[11px] text-gold/50">›</span>
            </button>
            <Divider />
          </>
        )}

        {!props.isInChat && props.hasLastSession && (
          <NavRow icon="▶️" label="Continue" onClick={props.onContinue} />
        )}

        <NavRow icon="💬" label="New Chat" chev onClick={props.onNewChat} />
        <NavRow icon="💞" label="Personas" onClick={props.onPersonas} />

        <Divider />

        <NavRow icon="📖" label="History" chev onClick={props.onHistory} />
        <NavRow icon="🔖" label="Bookmarks" chev onClick={props.onBookmarks} />
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Bottom section */}
      <div className="flex-shrink-0 border-t border-white/5">
        <NavRow icon="🎓" label="Knowledge" onClick={props.onKnowledge} />
        <NavRow icon="📂" label="My Data" onClick={props.onMyData} />

        <Divider />

        <button
          type="button"
          onClick={props.onToggleSanitised}
          aria-pressed={props.isSanitised}
          className="flex w-full items-center gap-3 px-3.5 py-2 text-left transition-colors hover:bg-white/4"
        >
          <span className={`text-[15px] ${props.isSanitised ? 'opacity-100' : 'opacity-60 grayscale'}`}>🔒</span>
          <span
            className={`flex-1 text-[13px] transition-colors ${
              props.isSanitised ? 'font-medium text-gold' : 'text-white/65'
            }`}
          >
            Sanitised
          </span>
        </button>

        <Divider />

        <button
          type="button"
          onClick={props.onUserRow}
          className="flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-white/4"
        >
          <div className="relative flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-purple to-gold text-[12px] font-bold text-white">
            {props.initial}
            {props.hasApiKeyProblem && (
              <span
                aria-label="API key problem"
                className="absolute -top-0.5 -right-0.5 flex h-3 w-3 items-center justify-center rounded-full bg-red-500 text-[7px] font-bold text-white"
              >
                !
              </span>
            )}
          </div>
          <div className="min-w-0 flex-1 text-left">
            <p className="truncate text-[13px] font-medium text-white/70">{props.displayName}</p>
            <p className="text-[10px] text-white/55">{props.role}</p>
          </div>
        </button>

        <button
          type="button"
          onClick={props.onLogout}
          className="flex w-full items-center gap-2 px-4 py-2 font-mono text-[11px] text-white/55 transition-colors hover:text-white/85"
        >
          <span>↪</span>
          <span>Log out</span>
        </button>
      </div>
    </div>
  )
}

interface NavRowProps {
  icon: string
  label: string
  chev?: boolean
  onClick: () => void
}

function NavRow({ icon, label, chev, onClick }: NavRowProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-3 px-3.5 py-2 text-left transition-colors hover:bg-white/4"
    >
      <span className="w-5 flex-shrink-0 text-center text-[15px]">{icon}</span>
      <span className="flex-1 text-[13px] text-white/70">{label}</span>
      {chev && <span className="text-[11px] text-white/30">›</span>}
    </button>
  )
}

function Divider() {
  return <div className="mx-3 my-1 h-px bg-white/6" />
}
```

- [ ] **Step 5.4: Run tests to verify they pass**

```bash
cd frontend && pnpm vitest run src/app/components/sidebar/MobileMainView.test.tsx
```

Expected: All 17 tests pass.

- [ ] **Step 5.5: Commit**

```bash
git add frontend/src/app/components/sidebar/MobileMainView.tsx \
        frontend/src/app/components/sidebar/MobileMainView.test.tsx
git commit -m "Add MobileMainView component with top, spacer, bottom layout"
```

---

## Task 6: Wire mobile branch into Sidebar.tsx

**Files:**
- Modify: `frontend/src/app/components/sidebar/Sidebar.tsx` (the expanded view return statement at lines ~669-1071)

Add `mobileView` state. Below `lg`, render the new mobile shell (header + sliding container with main view + active overlay). Above `lg`, the existing expanded-view JSX is preserved verbatim.

The desktop branch (collapsed at line ~451 and the expanded JSX from line ~669) MUST stay byte-identical to today on `>= lg`.

- [ ] **Step 6.1: Add the imports and state**

Open `frontend/src/app/components/sidebar/Sidebar.tsx`. After the existing imports (lines 1-32), add:

```tsx
import { MobileSidebarHeader } from './MobileSidebarHeader'
import { MobileMainView } from './MobileMainView'
import { MobileNewChatView } from './MobileNewChatView'
import { HistoryTab } from '../user-modal/HistoryTab'
import { BookmarksTab } from '../user-modal/BookmarksTab'
```

After the existing `useState` calls (around line 167-206 — `historyOpen`, `unpinnedOpen`, `historySearch`, `flyoutTab`), add:

```tsx
type MobileView = 'main' | 'new-chat' | 'history' | 'bookmarks'
const [mobileView, setMobileView] = useState<MobileView>('main')

// Reset to main when the drawer is closed (so next open lands on main view).
useEffect(() => {
  if (!drawerOpen) setMobileView('main')
}, [drawerOpen])
```

- [ ] **Step 6.2: Define the close-overlay-and-drawer helper**

Find the existing `closeDrawerIfMobile` function (around line 299) and add right after it:

```tsx
/** Close any mobile overlay AND the drawer itself. Used by item-tap in
 *  History/Bookmarks/New-Chat to fully collapse. */
function closeOverlayAndDrawer() {
  setMobileView('main')
  if (!isDesktop) {
    useDrawerStore.getState().close()
  }
}
```

- [ ] **Step 6.3: Define the new-chat persona-select handler**

Add a new function near the existing `handleNewChat` (around line 323):

```tsx
function handleNewChatFromMobileOverlay(persona: PersonaDto) {
  onCloseModal()
  setMobileView('main')
  useDrawerStore.getState().close()
  navigate(`/chat/${persona.id}?new=1`)
}
```

- [ ] **Step 6.4: Insert the mobile branch**

Find the existing expanded-view return statement (around line 670, starting with `return (` and `<aside className={[`). Replace it with a branch:

```tsx
// ── Mobile branch ───────────────────────────────────────────────
if (!isDesktop) {
  const handleAdmin     = () => { closeDrawerIfMobile(); onOpenAdmin() }
  const handlePersonas  = () => { onCloseModal(); closeDrawerIfMobile(); navigate('/personas') }
  const handleKnowledge = () => openModalAndClose('knowledge')
  const handleMyData    = () => openModalAndClose('my-data')
  const handleUserRow   = () => openModalAndClose(avatarTab)
  const handleClose     = () => useDrawerStore.getState().close()

  const overlayTitle =
    mobileView === 'new-chat'  ? 'New Chat'  :
    mobileView === 'history'   ? 'History'   :
    mobileView === 'bookmarks' ? 'Bookmarks' :
    undefined

  return (
    <aside
      className={[
        'fixed inset-y-0 left-0 z-40 flex h-full w-screen flex-col overflow-hidden border-r border-white/6 bg-base transition-transform duration-200 ease-out',
        drawerOpen ? 'translate-x-0' : '-translate-x-full',
      ].join(' ')}
    >
      <MobileSidebarHeader
        title={overlayTitle}
        onBack={overlayTitle ? () => setMobileView('main') : undefined}
        onClose={handleClose}
      />

      <div className="relative flex-1 overflow-hidden">
        <div
          className="flex h-full w-[200%] transition-transform duration-150 ease-out"
          style={{ transform: mobileView === 'main' ? 'translateX(0)' : 'translateX(-50%)' }}
        >
          <div className="h-full w-1/2 flex-shrink-0 overflow-hidden">
            <MobileMainView
              isAdmin={isAdmin}
              isInChat={isInChat}
              hasLastSession={!!lastSession}
              hasApiKeyProblem={hasApiKeyProblem}
              isSanitised={isSanitised}
              displayName={displayName}
              role={user?.role || ''}
              initial={initial}
              onAdmin={handleAdmin}
              onContinue={handleContinue}
              onNewChat={() => setMobileView('new-chat')}
              onPersonas={handlePersonas}
              onHistory={() => setMobileView('history')}
              onBookmarks={() => setMobileView('bookmarks')}
              onKnowledge={handleKnowledge}
              onMyData={handleMyData}
              onToggleSanitised={toggleSanitised}
              onUserRow={handleUserRow}
              onLogout={() => logout()}
            />
          </div>

          <div className="h-full w-1/2 flex-shrink-0 overflow-hidden">
            {mobileView === 'new-chat'  && <MobileNewChatView personas={personas} onSelect={handleNewChatFromMobileOverlay} />}
            {mobileView === 'history'   && <HistoryTab   onClose={closeOverlayAndDrawer} />}
            {mobileView === 'bookmarks' && <BookmarksTab onClose={closeOverlayAndDrawer} />}
          </div>
        </div>
      </div>
    </aside>
  )
}

// ── Desktop expanded view ──────────────────────────────────────
```

Then the existing expanded view JSX (the original `return ( <aside ...>`) follows unchanged. Make sure to drop the original `return (` line — the existing code becomes the desktop branch's return.

- [ ] **Step 6.5: Update Sidebar.test.tsx for the mobile branch**

Add to `frontend/src/app/components/sidebar/Sidebar.test.tsx` a new describe-block that mocks `useViewport` to return `isDesktop: false` and the `useDrawerStore` to expose state:

```tsx
import { useDrawerStore } from '../../../core/store/drawerStore'

vi.mock('../../../core/hooks/useViewport', () => ({
  useViewport: () => ({ isDesktop: false, isMobile: true, isTablet: false, isLandscape: false, isSm: true, isMd: false, isLg: false, isXl: false }),
}))

describe('Sidebar — mobile stack', () => {
  beforeEach(() => {
    useDrawerStore.setState({ sidebarOpen: true })
    mockNavigate.mockClear()
  })

  it('starts on the main view', () => {
    renderSidebar()
    expect(screen.getByText('Chatsune')).toBeInTheDocument()
    expect(screen.getByText('New Chat')).toBeInTheDocument()
  })

  it('navigates to new-chat overlay when New Chat row is tapped', async () => {
    renderSidebar()
    await userEvent.click(screen.getByText('New Chat'))
    // After tap, the overlay header is rendered:
    expect(screen.getByRole('button', { name: /back to main/i })).toBeInTheDocument()
  })

  it('returns to main view when back button is tapped', async () => {
    renderSidebar()
    await userEvent.click(screen.getByText('New Chat'))
    await userEvent.click(screen.getByRole('button', { name: /back to main/i }))
    // Main header is back:
    expect(screen.getByRole('button', { name: /close sidebar/i })).toBeInTheDocument()
  })

  it('closes the drawer when ✕ is tapped (state goes false)', async () => {
    renderSidebar()
    await userEvent.click(screen.getByRole('button', { name: /close drawer/i }))
    expect(useDrawerStore.getState().sidebarOpen).toBe(false)
  })
})
```

Note: depending on Vitest module resolution, the existing tests at the top of the file run with `isDesktop` mocked false. If they relied on desktop rendering, gate them by re-mocking `useViewport` for those describes. Verify after running.

- [ ] **Step 6.6: Run all sidebar tests**

```bash
cd frontend && pnpm vitest run src/app/components/sidebar/
```

Expected: All tests pass (existing + 4 new mobile-stack tests).

- [ ] **Step 6.7: Build verification**

```bash
cd frontend && pnpm run build
```

Expected: Build succeeds. Catch any type errors from the rewritten Sidebar branch.

- [ ] **Step 6.8: Commit**

```bash
git add frontend/src/app/components/sidebar/Sidebar.tsx \
        frontend/src/app/components/sidebar/Sidebar.test.tsx
git commit -m "Wire mobile sidebar branch with main/overlay stack"
```

---

## Task 7: Manual verification

This task does not produce code. It documents the manual verification that must pass before marking this work complete.

- [ ] **Step 7.1: Start dev server**

```bash
cd frontend && pnpm dev
```

- [ ] **Step 7.2: Open the app at iPhone-SE viewport (Chrome DevTools → toggle device → iPhone SE 375 × 667)**

Walk through each item:

- [ ] Open the drawer (top-bar hamburger). Main view fits the screen with no scrolling. Bottom row (Log out) is visible.
- [ ] Tap the fox/Chatsune logo area — drawer closes.
- [ ] Re-open. Tap `✕` — drawer closes.
- [ ] Tap "New Chat" — slide animation, overlay shows pinned + other sections, NSFW pill rendered, long persona names truncate.
- [ ] Tap a persona — drawer closes, app navigates to the new-chat URL.
- [ ] Re-open drawer — main view (state was reset).
- [ ] Tap "History" — existing History tab rendered inside the sidebar; search input and persona-filter dropdown stack vertically; tapping a session navigates and closes the drawer.
- [ ] Tap "Bookmarks" — same: stacked filter row, tap a bookmark, drawer closes.
- [ ] Tap "Knowledge" — User-Modal opens to Knowledge tab.
- [ ] Tap "My Data" — User-Modal opens, last-visited sub-tab applies.
- [ ] Toggle Sanitised — confirm New-Chat overlay hides NSFW personas; History hides NSFW sessions.
- [ ] Continue row visible only when not in chat; verify by being on `/personas` (visible) vs in a chat (hidden).
- [ ] Admin banner visible only as admin; relog as non-admin to confirm hidden.
- [ ] Avatar `!` indicator visible when API-key problem; tap routes to Settings → API-Keys.
- [ ] Tap user row (no problem) → About-me opens.
- [ ] Tap Log out → user logged out, redirected to login.
- [ ] Rotate to landscape — layout still correct, no overflow.

- [ ] **Step 7.3: Desktop regression check (>= lg viewport)**

- [ ] At >= 1024 px, sidebar is permanent (no off-canvas) and looks identical to before.
- [ ] Rail collapse still works (click `⏪` → narrow rail; click rail icon → expand).
- [ ] All desktop NavRows still functional (Knowledge, Bookmarks, Uploads, Artefacts, Images).

- [ ] **Step 7.4: User-Modal tabs at desktop width regression**

- [ ] Open User-Modal → Chats → History on desktop. Search input and filter dropdown remain side-by-side.
- [ ] Same for Bookmarks tab.

- [ ] **Step 7.5: User-Modal tabs at mobile width**

- [ ] Resize to 375 px. Open User-Modal → Chats → History. Search and filter stack vertically. Both inputs full-width. List renders normally.
- [ ] Same for Bookmarks tab.

- [ ] **Step 7.6: Final commit (only if any polish was needed)**

If manual testing surfaced small fixes, commit them with a clear message. Otherwise skip.

---

## Decisions Recap

| Decision                                       | Choice                                            |
|-----------------------------------------------|---------------------------------------------------|
| "My Data" entry destination                    | User-Modal `my-data` top-tab                      |
| Continue visibility                            | Only when `!isInChat && lastSession`              |
| Header on mobile                               | Logo area + ✕ both close drawer; no `<<`          |
| Settings shortcut on user row                  | Removed; API-key indicator stays                  |
| Overlay model                                  | Stack inside sidebar (depth 2)                    |
| History / Bookmarks reuse                      | Reuse existing tabs + small responsive tweak      |
| New-Chat search field                          | None                                              |
| New-Chat sections                              | Pinned + Other, manual order, NSFW pill           |
| Animation                                      | Horizontal slide ~150 ms                          |
| Tablet handling                                | Same fullscreen mobile sidebar                    |

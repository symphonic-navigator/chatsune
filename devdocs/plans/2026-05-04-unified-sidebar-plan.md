# Unified Sidebar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align mobile drawer button order with the 2026-05-03 desktop sidebar
redesign — Bookmarks moves into the footer, New Incognito Chat becomes a
transient toggle inside the persona picker, and the desktop `··· Settings`
button gains a mobile counterpart.

**Architecture:** Frontend-only change. Three components are modified
(`MobileMainView`, `MobileNewChatView`, `Sidebar`). The `MobileNewChatView`'s
`onSelect` signature widens to accept an optional `{ incognito?: boolean }`
opts argument; the `Sidebar` mobile branch routes to `?incognito=1` vs
`?new=1` based on the flag. Desktop sidebar code is **not touched**.

**Tech Stack:** React + TypeScript (TSX), Vite, Tailwind, Vitest +
@testing-library/react, react-router-dom v7.

**Spec:** `devdocs/specs/2026-05-04-unified-sidebar-design.md`

---

## File Structure

| Path | Role | Action |
|---|---|---|
| `frontend/src/app/components/sidebar/MobileNewChatView.tsx` | Persona picker shown after tapping New Chat on mobile | Modify — add transient Incognito toggle, widen `onSelect` |
| `frontend/src/app/components/sidebar/MobileNewChatView.test.tsx` | Vitest spec for the picker | Modify — add toggle assertions |
| `frontend/src/app/components/sidebar/MobileMainView.tsx` | Top-level mobile drawer body | Modify — Bookmarks moves to footer, add `··· Settings` button |
| `frontend/src/app/components/sidebar/MobileMainView.test.tsx` | Vitest spec for the drawer body | Modify — assert new order and Settings button |
| `frontend/src/app/components/sidebar/Sidebar.tsx` | Top-level sidebar component (desktop + mobile branch) | Modify — wire incognito navigation, pass `onOpenSettings` |

No new files. Changes are scoped to the sidebar feature folder.

---

## Task 1: Add transient Incognito toggle to MobileNewChatView

**Files:**
- Modify: `frontend/src/app/components/sidebar/MobileNewChatView.tsx`
- Test: `frontend/src/app/components/sidebar/MobileNewChatView.test.tsx`

The picker gains a top-mounted Incognito toggle. State lives inside
`MobileNewChatView` so unmount/remount on close+reopen resets it to `off`.
The `onSelect` signature widens from `(persona) => void` to
`(persona, opts?: { incognito?: boolean }) => void`.

- [ ] **Step 1: Add failing tests for the Incognito toggle**

Append the following describe block to `MobileNewChatView.test.tsx` (place after the existing `describe('MobileNewChatView — selection', ...)` block):

```tsx
describe('MobileNewChatView — Incognito toggle', () => {
  it('renders the Incognito toggle, defaults to off', () => {
    renderView([aria, marcus])
    const toggle = screen.getByRole('button', { name: /incognito/i })
    expect(toggle).toBeInTheDocument()
    expect(toggle).toHaveAttribute('aria-pressed', 'false')
  })

  it('flips aria-pressed to true after tapping the toggle', async () => {
    renderView([aria, marcus])
    const toggle = screen.getByRole('button', { name: /incognito/i })
    await userEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-pressed', 'true')
  })

  it('calls onSelect with { incognito: true } when toggle is on', async () => {
    const onSelect = vi.fn()
    renderView([aria, marcus], onSelect)
    await userEvent.click(screen.getByRole('button', { name: /incognito/i }))
    await userEvent.click(screen.getByText('Marcus the Stoic'))
    expect(onSelect).toHaveBeenCalledWith(marcus, { incognito: true })
  })

  it('calls onSelect with { incognito: false } when toggle is off', async () => {
    const onSelect = vi.fn()
    renderView([aria, marcus], onSelect)
    await userEvent.click(screen.getByText('Marcus the Stoic'))
    expect(onSelect).toHaveBeenCalledWith(marcus, { incognito: false })
  })

  it('resets the toggle to off when the component is remounted', async () => {
    const { unmount } = renderView([aria, marcus])
    const toggle = screen.getByRole('button', { name: /incognito/i })
    await userEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-pressed', 'true')
    unmount()
    renderView([aria, marcus])
    const fresh = screen.getByRole('button', { name: /incognito/i })
    expect(fresh).toHaveAttribute('aria-pressed', 'false')
  })
})
```

Also update the existing selection test (line 100-107 of the current file) to match the wider signature:

```tsx
describe('MobileNewChatView — selection', () => {
  it('calls onSelect with the persona when a row is tapped', async () => {
    const onSelect = vi.fn()
    renderView([aria, marcus], onSelect)
    await userEvent.click(screen.getByText('Marcus the Stoic'))
    expect(onSelect).toHaveBeenCalledWith(marcus, { incognito: false })
  })
})
```

Update the `renderView` helper's signature so the type matches the new `onSelect`:

```tsx
function renderView(personas: PersonaDto[], onSelect: (p: PersonaDto, opts?: { incognito?: boolean }) => void = () => {}) {
  return render(
    <MemoryRouter>
      <MobileNewChatView personas={personas} onSelect={onSelect} />
    </MemoryRouter>
  )
}
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd frontend && pnpm vitest run src/app/components/sidebar/MobileNewChatView.test.tsx
```

Expected: the new tests fail (no toggle button found, or `onSelect` called with one arg instead of two).

- [ ] **Step 3: Implement the toggle in MobileNewChatView**

Replace the contents of `frontend/src/app/components/sidebar/MobileNewChatView.tsx` with:

```tsx
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import type { PersonaDto } from '../../../core/types/persona'
import { useSanitisedMode } from '../../../core/store/sanitisedModeStore'
import { CHAKRA_PALETTE } from '../../../core/types/chakra'

interface MobileNewChatViewProps {
  personas: PersonaDto[]
  /** Wider signature than the original: opts carries the transient Incognito
   *  toggle state from this picker. Always called with opts so the caller can
   *  rely on the flag being present. */
  onSelect: (persona: PersonaDto, opts: { incognito: boolean }) => void
  /** Called when the empty-state "Create persona" link is tapped. Gives the
   *  sidebar a chance to close the drawer before route navigation. */
  onClose?: () => void
}

export function MobileNewChatView({ personas, onSelect, onClose }: MobileNewChatViewProps) {
  const isSanitised = useSanitisedMode((s) => s.isSanitised)
  // Transient by design: parent unmounts+remounts the picker on each open,
  // so this state resets to `false` every time. Do NOT lift this into a store.
  const [incognito, setIncognito] = useState(false)

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
          replace
          onClick={onClose}
          className="rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-[12px] text-white/80 transition-colors hover:bg-white/10"
        >
          Create persona
        </Link>
      </div>
    )
  }

  function handlePick(persona: PersonaDto) {
    onSelect(persona, { incognito })
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-shrink-0 px-3 pt-2 pb-1">
        <button
          type="button"
          onClick={() => setIncognito((v) => !v)}
          aria-pressed={incognito}
          aria-label={incognito ? 'Turn Incognito mode off' : 'Turn Incognito mode on'}
          className={[
            'flex w-full items-center gap-2 rounded-md border px-2.5 py-1.5 text-left transition-colors',
            incognito
              ? 'border-gold/35 bg-gold/12 text-gold'
              : 'border-white/8 bg-white/4 text-white/65 hover:bg-white/6',
          ].join(' ')}
        >
          <span className="text-[14px]">🕶</span>
          <span className="flex-1 text-[12px] font-medium">Incognito</span>
          <span
            className={[
              'rounded-full px-1.5 py-[1px] text-[9px] font-semibold uppercase tracking-wider',
              incognito ? 'bg-gold/20 text-gold' : 'bg-white/8 text-white/55',
            ].join(' ')}
          >
            {incognito ? 'On' : 'Off'}
          </span>
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto py-1 [&::-webkit-scrollbar]:w-[3px] [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10">
        {pinned.length > 0 && (
          <>
            <div className="px-4 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-widest text-white/45">
              Pinned
            </div>
            {pinned.map((p) => (
              <PersonaRow key={p.id} persona={p} onSelect={handlePick} />
            ))}
          </>
        )}

        {other.length > 0 && (
          <>
            <div className="px-4 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-widest text-white/45">
              Other
            </div>
            {other.map((p) => (
              <PersonaRow key={p.id} persona={p} onSelect={handlePick} />
            ))}
          </>
        )}
      </div>
    </div>
  )
}

interface PersonaRowProps {
  persona: PersonaDto
  onSelect: (persona: PersonaDto) => void
}

function PersonaRow({ persona, onSelect }: PersonaRowProps) {
  const chakra = CHAKRA_PALETTE[persona.colour_scheme] ?? CHAKRA_PALETTE.solar
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

- [ ] **Step 4: Run tests, verify they pass**

```bash
cd frontend && pnpm vitest run src/app/components/sidebar/MobileNewChatView.test.tsx
```

Expected: all tests pass (the new toggle tests, plus the existing section / NSFW / sanitised / selection tests with their updated argument shape).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/sidebar/MobileNewChatView.tsx frontend/src/app/components/sidebar/MobileNewChatView.test.tsx
git commit -m "Add transient Incognito toggle to mobile new-chat picker"
```

---

## Task 2: Route mobile new-chat picker through incognito flag in Sidebar

**Files:**
- Modify: `frontend/src/app/components/sidebar/Sidebar.tsx:212-217`

The mobile branch passes `MobileNewChatView`'s `onSelect` directly to
`handleNewChatFromMobileOverlay`. That handler must accept the new opts
argument and route to `?incognito=1` when the toggle was on.

- [ ] **Step 1: Update `handleNewChatFromMobileOverlay`**

In `Sidebar.tsx`, find the function at lines 212-217:

```tsx
  function handleNewChatFromMobileOverlay(persona: PersonaDto) {
    onCloseModal()
    setMobileView('main')
    closeDrawerIfMobile()
    navigate(`/chat/${persona.id}?new=1`, { replace: true })
  }
```

Replace it with:

```tsx
  function handleNewChatFromMobileOverlay(persona: PersonaDto, opts: { incognito: boolean }) {
    onCloseModal()
    setMobileView('main')
    closeDrawerIfMobile()
    const query = opts.incognito ? 'incognito=1' : 'new=1'
    navigate(`/chat/${persona.id}?${query}`, { replace: true })
  }
```

The `MobileNewChatView` JSX usage at line 570 needs no change — `onSelect={handleNewChatFromMobileOverlay}` already passes both args through.

- [ ] **Step 2: Run frontend type-check / build**

```bash
cd frontend && pnpm run build
```

Expected: clean compile. The picker test from Task 1 already exercises the new signature; no Sidebar-level test exists for this handler (the wider Sidebar.test.tsx is a smoke render — verify it still passes):

```bash
cd frontend && pnpm vitest run src/app/components/sidebar/Sidebar.test.tsx
```

Expected: pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/components/sidebar/Sidebar.tsx
git commit -m "Route mobile new-chat picker through incognito flag"
```

---

## Task 3: Reorder MobileMainView and add Settings button

**Files:**
- Modify: `frontend/src/app/components/sidebar/MobileMainView.tsx`
- Test: `frontend/src/app/components/sidebar/MobileMainView.test.tsx`

Bookmarks leaves the top group and joins the footer between Knowledge and
My Data. A `··· Settings` button is added to the right of the user row,
mirroring the desktop `FooterBlock`. The component gains an
`onOpenSettings` prop and an `avatarHighlight` prop (the latter for full
desktop parity — the user row container picks up a gold tint when the
About-Me / Settings modal is active).

- [ ] **Step 1: Update tests in MobileMainView.test.tsx**

Replace the entire contents of `frontend/src/app/components/sidebar/MobileMainView.test.tsx` with:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MobileMainView } from './MobileMainView'

const baseProps = {
  isAdmin: false,
  isInChat: false,
  hasLastSession: false,
  hasApiKeyProblem: false,
  isSanitised: false,
  avatarHighlight: false,
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
  onOpenSettings: vi.fn(),
  onLogout: vi.fn(),
}

function renderView(overrides: Partial<typeof baseProps> = {}) {
  return render(<MobileMainView {...baseProps} {...overrides} />)
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
  it('renders New Chat, Personas, History', () => {
    renderView()
    expect(screen.getByText('New Chat')).toBeInTheDocument()
    expect(screen.getByText('Personas')).toBeInTheDocument()
    expect(screen.getByText('History')).toBeInTheDocument()
  })

  it('renders Knowledge, Bookmarks, My Data, Sanitised, Log out', () => {
    renderView()
    expect(screen.getByText('Knowledge')).toBeInTheDocument()
    expect(screen.getByText('Bookmarks')).toBeInTheDocument()
    expect(screen.getByText('My Data')).toBeInTheDocument()
    expect(screen.getByText('Sanitised')).toBeInTheDocument()
    expect(screen.getByText('Log out')).toBeInTheDocument()
  })

  it('renders the Settings ··· button next to the user row', () => {
    renderView()
    expect(screen.getByRole('button', { name: /settings/i })).toBeInTheDocument()
  })
})

describe('MobileMainView — button order', () => {
  it('places Bookmarks between Knowledge and My Data (footer group, not top group)', () => {
    renderView()
    const all = screen.getAllByRole('button').map((b) => b.textContent ?? '')
    const idxKnowledge = all.findIndex((t) => t.includes('Knowledge'))
    const idxBookmarks = all.findIndex((t) => t.includes('Bookmarks'))
    const idxMyData = all.findIndex((t) => t.includes('My Data'))
    const idxHistory = all.findIndex((t) => t.includes('History'))
    expect(idxKnowledge).toBeGreaterThan(-1)
    expect(idxBookmarks).toBeGreaterThan(idxKnowledge)
    expect(idxMyData).toBeGreaterThan(idxBookmarks)
    // Bookmarks must be in the FOOTER group, after History — i.e. below it.
    expect(idxBookmarks).toBeGreaterThan(idxHistory)
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

  it('calls onBookmarks when Bookmarks row is tapped', async () => {
    const onBookmarks = vi.fn()
    renderView({ onBookmarks })
    await userEvent.click(screen.getByText('Bookmarks'))
    expect(onBookmarks).toHaveBeenCalledOnce()
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

  it('calls onOpenSettings when the ··· Settings button is tapped', async () => {
    const onOpenSettings = vi.fn()
    renderView({ onOpenSettings })
    await userEvent.click(screen.getByRole('button', { name: /settings/i }))
    expect(onOpenSettings).toHaveBeenCalledOnce()
  })

  it('calls onUserRow when the user row body is tapped (not the Settings button)', async () => {
    const onUserRow = vi.fn()
    const onOpenSettings = vi.fn()
    renderView({ onUserRow, onOpenSettings })
    await userEvent.click(screen.getByText('Chris'))
    expect(onUserRow).toHaveBeenCalledOnce()
    expect(onOpenSettings).not.toHaveBeenCalled()
  })

  it('calls onLogout when Log out row is tapped', async () => {
    const onLogout = vi.fn()
    renderView({ onLogout })
    await userEvent.click(screen.getByText('Log out'))
    expect(onLogout).toHaveBeenCalledOnce()
  })
})
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd frontend && pnpm vitest run src/app/components/sidebar/MobileMainView.test.tsx
```

Expected: failures around the new `Bookmarks` position, the missing `Settings` button, and missing `onOpenSettings` / `avatarHighlight` props.

- [ ] **Step 3: Implement the new MobileMainView**

Replace the entire contents of `frontend/src/app/components/sidebar/MobileMainView.tsx` with:

```tsx
interface MobileMainViewProps {
  isAdmin: boolean
  isInChat: boolean
  hasLastSession: boolean
  hasApiKeyProblem: boolean
  isSanitised: boolean
  avatarHighlight: boolean
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
  onOpenSettings: () => void
  onLogout: () => void
}

export function MobileMainView(props: MobileMainViewProps) {
  return (
    <div className="flex h-full flex-col">
      {/* Top section — mirrors desktop order: New Chat → Continue → Personas → History */}
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

        <NavRow icon="💬" label="New Chat" chev onClick={props.onNewChat} />

        {!props.isInChat && props.hasLastSession && (
          <NavRow icon="▶️" label="Continue" onClick={props.onContinue} />
        )}

        <Divider />

        <NavRow icon="💞" label="Personas" onClick={props.onPersonas} />
        <NavRow icon="📖" label="History" chev onClick={props.onHistory} />
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Bottom section — footer parity with desktop FooterBlock */}
      <div className="flex-shrink-0 border-t border-white/5">
        <NavRow icon="🎓" label="Knowledge" onClick={props.onKnowledge} />
        <NavRow icon="🔖" label="Bookmarks" onClick={props.onBookmarks} />
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

        <div
          className={[
            'flex items-center gap-2.5 px-3 py-2 transition-colors',
            props.avatarHighlight ? 'bg-gold/7' : '',
          ].join(' ')}
        >
          <button
            type="button"
            onClick={props.onUserRow}
            className="flex flex-1 items-center gap-2.5 min-w-0 hover:opacity-80 transition-opacity"
            title="Your profile"
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
              <p
                className={[
                  'truncate text-[13px] font-medium transition-colors',
                  props.avatarHighlight ? 'text-gold' : 'text-white/70',
                ].join(' ')}
              >
                {props.displayName}
              </p>
              <p className="text-[10px] text-white/55">{props.role}</p>
            </div>
          </button>

          <button
            type="button"
            onClick={props.onOpenSettings}
            title="Settings"
            aria-label="Settings"
            className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded text-[13px] text-white/60 transition-colors hover:bg-white/8 hover:text-white/85"
          >
            ···
          </button>
        </div>

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

Note the order changes inside the top section: `New Chat → Continue (conditional) → Divider → Personas → History`. The previous version had Continue **before** New Chat — the spec aligns this with the desktop ActionBlock where New Chat comes first. Bookmarks no longer appears in the top section.

- [ ] **Step 4: Run tests, verify they pass**

```bash
cd frontend && pnpm vitest run src/app/components/sidebar/MobileMainView.test.tsx
```

Expected: all tests pass, including the order check and the Settings button assertions.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/sidebar/MobileMainView.tsx frontend/src/app/components/sidebar/MobileMainView.test.tsx
git commit -m "Reorder mobile sidebar: Bookmarks to footer, add Settings button"
```

---

## Task 4: Wire `onOpenSettings` and `avatarHighlight` from Sidebar to MobileMainView

**Files:**
- Modify: `frontend/src/app/components/sidebar/Sidebar.tsx:545-566`

The mobile branch of `Sidebar` constructs `<MobileMainView ... />` and must
pass the two new props.

- [ ] **Step 1: Update the mobile branch's MobileMainView usage**

In `Sidebar.tsx`, find the `<MobileMainView ...>` block at lines 546-566:

```tsx
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
```

Replace it with:

```tsx
              <MobileMainView
                isAdmin={isAdmin}
                isInChat={isInChat}
                hasLastSession={!!lastSession}
                hasApiKeyProblem={hasApiKeyProblem}
                isSanitised={isSanitised}
                avatarHighlight={avatarHighlight}
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
                onOpenSettings={() => openModalAndClose('settings')}
                onLogout={() => logout()}
              />
```

`avatarHighlight` is already defined as a local `const` in `Sidebar` (line 301). `openModalAndClose` is the existing helper that closes the drawer on mobile and opens the modal leaf.

- [ ] **Step 2: Build check**

```bash
cd frontend && pnpm run build
```

Expected: clean compile (`tsc -b` and `vite build` both succeed).

- [ ] **Step 3: Smoke-run all sidebar tests**

```bash
cd frontend && pnpm vitest run src/app/components/sidebar/
```

Expected: all tests in the sidebar folder pass, including
`MobileMainView.test.tsx`, `MobileNewChatView.test.tsx`,
`Sidebar.test.tsx`, `MobileSidebarHeader.test.tsx`, `NavRow.test.tsx`,
`PersonaItem.test.tsx`, `personaColour.test.ts`, `personaSort.test.ts`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/sidebar/Sidebar.tsx
git commit -m "Pass onOpenSettings and avatarHighlight to mobile sidebar"
```

---

## Task 5: Final verification

- [ ] **Step 1: Full frontend build**

```bash
cd frontend && pnpm run build
```

Expected: clean `tsc -b` and `vite build`. No type errors, no warnings beyond the project's existing baseline.

- [ ] **Step 2: Full sidebar test sweep**

```bash
cd frontend && pnpm vitest run src/app/components/sidebar/
```

Expected: every sidebar test file passes.

- [ ] **Step 3: Manual verification (run on actual mobile device, not just devtools)**

Spec ref: `devdocs/specs/2026-05-04-unified-sidebar-design.md` § *Manual verification steps*. The full list of 8 manual checks lives in the spec — work through each one. Key checks:

1. Mobile drawer order matches the canonical order (Bookmarks below Knowledge, not above History).
2. Mobile picker Incognito toggle: tap on, pick persona → URL `?incognito=1`. Reopen picker → toggle is off again.
3. Mobile picker Incognito toggle: leave off, pick persona → URL `?new=1`.
4. Mobile `··· Settings` button opens the Settings modal (not About-Me).
5. Mobile user-row body still opens About-Me (or API-keys when problem flagged).
6. Desktop sidebar visibly unchanged from yesterday's redesign.

- [ ] **Step 4: Confirm with user before merge**

After all checks pass, hand the result back to the user for the final
"merge to master" step. Per the project default (`Please always merge to
master after implementation`), but the user explicitly drives that step.

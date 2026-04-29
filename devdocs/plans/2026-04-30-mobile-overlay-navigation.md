# Mobile Overlay Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the wrapping tab rows in `UserModal`, `AdminModal`, and `PersonaOverlay` below the `lg` (1024 px) breakpoint with a single shared `OverlayMobileNav` component — a dropdown trigger showing the current path plus an outline panel listing every destination.

**Architecture:** A new shared component lives at `frontend/src/app/components/overlay-mobile-nav/`. It walks a flat `NavNode[]` array, rendering each node either as a non-clickable section header (parents with children) or as a clickable leaf. Each of the three overlays maps its existing tab structure to `NavNode[]`, hides the desktop tab rows under `lg:` (`hidden lg:flex`), and renders the mobile nav under `lg:hidden`.

**Tech Stack:** React 19 + TypeScript (TSX), Tailwind CSS, Vitest + @testing-library/react + @testing-library/user-event.

**Spec:** `devdocs/specs/2026-04-30-mobile-overlay-navigation.md`. Read it before starting.

---

## File Structure

**Create**
- `frontend/src/app/components/overlay-mobile-nav/types.ts` — `NavLeaf`, `NavSection`, `NavNode`, `isSection`.
- `frontend/src/app/components/overlay-mobile-nav/resolveCrumb.ts` — pure helper that maps `(tree, activeId)` to `{ parent?, leaf }`.
- `frontend/src/app/components/overlay-mobile-nav/resolveCrumb.test.ts` — unit tests for the helper.
- `frontend/src/app/components/overlay-mobile-nav/OverlayMobileNav.tsx` — the dropdown trigger + outline panel.
- `frontend/src/app/components/overlay-mobile-nav/OverlayMobileNav.test.tsx` — component tests.

**Modify**
- `frontend/src/app/components/user-modal/userModalTree.ts` — add `toMobileNavTree()` exporter.
- `frontend/src/app/components/user-modal/UserModal.tsx` — gate desktop tab rows under `lg:`, mount `OverlayMobileNav` under `lg:hidden`.
- `frontend/src/app/components/admin-modal/AdminModal.tsx` — same.
- `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx` — same with chakra accent and filter mapping.

---

## Task 1: Types and isSection guard

**Files:**
- Create: `frontend/src/app/components/overlay-mobile-nav/types.ts`

The types file is small and pure declaration plus one one-line guard. No tests — per project convention, trivial helpers don't get their own tests.

- [ ] **Step 1: Create the types file**

Write `frontend/src/app/components/overlay-mobile-nav/types.ts`:

```ts
/**
 * Navigation tree shape consumed by `OverlayMobileNav`.
 *
 * A `NavLeaf` is a single navigable destination. A `NavSection` is a
 * non-clickable group header whose children render indented underneath.
 * The component walks the array as a single flat list and decides per
 * node whether to render it as a header or a leaf via `isSection`.
 */
export interface NavLeaf {
  id: string
  label: string
  badge?: boolean
}

export interface NavSection {
  id: string
  label: string
  children: NavLeaf[]
}

export type NavNode = NavLeaf | NavSection

export function isSection(node: NavNode): node is NavSection {
  return 'children' in node
}
```

- [ ] **Step 2: Verify it compiles**

Run from `frontend/`:
```bash
pnpm tsc --noEmit
```
Expected: clean exit.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/components/overlay-mobile-nav/types.ts
git commit -m "Add NavNode types for overlay mobile nav"
```

---

## Task 2: resolveCrumb helper

**Files:**
- Create: `frontend/src/app/components/overlay-mobile-nav/resolveCrumb.ts`
- Create: `frontend/src/app/components/overlay-mobile-nav/resolveCrumb.test.ts`

Pure function with three input cases (flat leaf, child of a section, leaf-only top in a hierarchical tree) plus a defensive fallback when the id is not found.

- [ ] **Step 1: Write the failing test**

Write `frontend/src/app/components/overlay-mobile-nav/resolveCrumb.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { resolveCrumb } from './resolveCrumb'
import type { NavNode } from './types'

const flatTree: NavNode[] = [
  { id: 'users', label: 'Users' },
  { id: 'system', label: 'System' },
]

const hierarchicalTree: NavNode[] = [
  { id: 'about-me', label: 'About me' },
  {
    id: 'settings',
    label: 'Settings',
    children: [
      { id: 'llm-providers', label: 'LLM Providers' },
      { id: 'voice', label: 'Voice' },
    ],
  },
  { id: 'job-log', label: 'Job-Log' },
]

describe('resolveCrumb', () => {
  it('returns leaf only for flat-tree active id', () => {
    expect(resolveCrumb(flatTree, 'users')).toEqual({ leaf: 'Users' })
  })

  it('returns parent + leaf for a section child', () => {
    expect(resolveCrumb(hierarchicalTree, 'voice')).toEqual({
      parent: 'Settings',
      leaf: 'Voice',
    })
  })

  it('returns leaf only for a leaf-only top tab in a hierarchical tree', () => {
    expect(resolveCrumb(hierarchicalTree, 'about-me')).toEqual({
      leaf: 'About me',
    })
  })

  it('returns leaf only when active id matches a section (defensive)', () => {
    expect(resolveCrumb(hierarchicalTree, 'settings')).toEqual({
      leaf: 'Settings',
    })
  })

  it('falls back to an empty leaf when active id is unknown', () => {
    expect(resolveCrumb(flatTree, 'does-not-exist')).toEqual({ leaf: '' })
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run from `frontend/`:
```bash
pnpm vitest run src/app/components/overlay-mobile-nav/resolveCrumb.test.ts
```
Expected: FAIL with "Cannot find module './resolveCrumb'".

- [ ] **Step 3: Implement the helper**

Write `frontend/src/app/components/overlay-mobile-nav/resolveCrumb.ts`:

```ts
import { isSection, type NavNode } from './types'

export interface Crumb {
  parent?: string
  leaf: string
}

/**
 * Find `activeId` in `tree` and return its display crumb.
 *
 * - Top-level leaf  → `{ leaf }`.
 * - Child of section → `{ parent: section.label, leaf: child.label }`.
 * - Section id (defensive) → `{ leaf: section.label }`.
 * - Unknown id → `{ leaf: '' }`.
 */
export function resolveCrumb(tree: NavNode[], activeId: string): Crumb {
  for (const node of tree) {
    if (node.id === activeId) {
      return { leaf: node.label }
    }
    if (isSection(node)) {
      const child = node.children.find((c) => c.id === activeId)
      if (child) {
        return { parent: node.label, leaf: child.label }
      }
    }
  }
  return { leaf: '' }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
pnpm vitest run src/app/components/overlay-mobile-nav/resolveCrumb.test.ts
```
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/overlay-mobile-nav/resolveCrumb.ts \
        frontend/src/app/components/overlay-mobile-nav/resolveCrumb.test.ts
git commit -m "Add resolveCrumb helper for overlay mobile nav"
```

---

## Task 3: OverlayMobileNav skeleton — trigger renders the path

**Files:**
- Create: `frontend/src/app/components/overlay-mobile-nav/OverlayMobileNav.tsx`
- Create: `frontend/src/app/components/overlay-mobile-nav/OverlayMobileNav.test.tsx`

Smallest possible component: renders the trigger button with the correct path label. Panel and toggle behaviour come in later tasks.

- [ ] **Step 1: Write the failing tests**

Write `frontend/src/app/components/overlay-mobile-nav/OverlayMobileNav.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { OverlayMobileNav } from './OverlayMobileNav'
import type { NavNode } from './types'

// scrollIntoView is not implemented by jsdom; stub once for the file.
beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
})

const flatTree: NavNode[] = [
  { id: 'users', label: 'Users' },
  { id: 'system', label: 'System' },
]

const hierarchicalTree: NavNode[] = [
  { id: 'about-me', label: 'About me' },
  {
    id: 'settings',
    label: 'Settings',
    children: [
      { id: 'llm-providers', label: 'LLM Providers' },
      { id: 'voice', label: 'Voice' },
    ],
  },
]

describe('OverlayMobileNav — trigger rendering', () => {
  it('renders the leaf only for a flat tree', () => {
    render(
      <OverlayMobileNav
        tree={flatTree}
        activeId="system"
        onSelect={vi.fn()}
      />,
    )
    const trigger = screen.getByRole('button', { name: /system/i })
    expect(trigger).toBeInTheDocument()
    expect(trigger.textContent).toContain('System')
    expect(trigger.textContent).not.toContain('–')
  })

  it('renders parent – leaf for a section child', () => {
    render(
      <OverlayMobileNav
        tree={hierarchicalTree}
        activeId="voice"
        onSelect={vi.fn()}
      />,
    )
    const trigger = screen.getByRole('button')
    // Real En-Dash, U+2013, never a hyphen.
    expect(trigger.textContent).toContain('Settings–Voice')
  })

  it('renders leaf only for a leaf-only top tab', () => {
    render(
      <OverlayMobileNav
        tree={hierarchicalTree}
        activeId="about-me"
        onSelect={vi.fn()}
      />,
    )
    const trigger = screen.getByRole('button')
    expect(trigger.textContent).toContain('About me')
    expect(trigger.textContent).not.toContain('–')
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pnpm vitest run src/app/components/overlay-mobile-nav/OverlayMobileNav.test.tsx
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the skeleton**

Write `frontend/src/app/components/overlay-mobile-nav/OverlayMobileNav.tsx`:

```tsx
import { useState } from 'react'
import { resolveCrumb } from './resolveCrumb'
import type { NavNode } from './types'

const EN_DASH = '–'

export interface OverlayMobileNavProps {
  tree: NavNode[]
  activeId: string
  onSelect: (id: string) => void
  /** Override the default gold; PersonaOverlay passes chakra.hex. */
  accentColour?: string
  /** Optional aria-label override for the trigger. */
  ariaLabel?: string
}

const DEFAULT_ACCENT = '#f5c542'

export function OverlayMobileNav({
  tree,
  activeId,
  onSelect: _onSelect,
  accentColour = DEFAULT_ACCENT,
  ariaLabel = 'Open navigation',
}: OverlayMobileNavProps) {
  const [open, _setOpen] = useState(false)
  const crumb = resolveCrumb(tree, activeId)

  // Keep these refs to silence unused-symbol lint warnings until later
  // tasks wire them up. The body of the component grows over the next
  // tasks (open/close toggle, panel content, keyboard nav).
  void _onSelect
  void _setOpen
  void open
  void accentColour

  return (
    <button
      type="button"
      aria-label={ariaLabel}
      aria-haspopup="listbox"
      aria-expanded={open}
      className="w-full flex items-center justify-between rounded-md border border-white/12 bg-white/4 px-3 py-2.5"
    >
      <span className="text-[13px] font-medium text-white/92">
        {crumb.parent && (
          <>
            <span className="text-white/50 font-normal">{crumb.parent}</span>
            <span className="text-white/35 mx-1.5">{EN_DASH}</span>
          </>
        )}
        {crumb.leaf}
      </span>
      <span className="text-white/50 text-[14px]" aria-hidden>{open ? '▴' : '▾'}</span>
    </button>
  )
}
```

Note: the `void` lines are temporary scaffolding so the file compiles cleanly under the project's strict TS settings while the rest of the body is added in later tasks. Remove each one as the symbol gets used.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pnpm vitest run src/app/components/overlay-mobile-nav/OverlayMobileNav.test.tsx
```
Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/overlay-mobile-nav/OverlayMobileNav.tsx \
        frontend/src/app/components/overlay-mobile-nav/OverlayMobileNav.test.tsx
git commit -m "Add OverlayMobileNav skeleton with path trigger"
```

---

## Task 4: Open/close toggle, panel renders nodes, leaf click selects + closes

**Files:**
- Modify: `frontend/src/app/components/overlay-mobile-nav/OverlayMobileNav.tsx`
- Modify: `frontend/src/app/components/overlay-mobile-nav/OverlayMobileNav.test.tsx`

Wire the `open` state to clicks, render the panel as a `role="listbox"` containing `role="option"` rows for leaves and presentation rows for sections, fire `onSelect` and close on leaf click, do nothing on section click.

- [ ] **Step 1: Add the failing tests**

Append the following blocks to `OverlayMobileNav.test.tsx` (inside the same file, alongside the existing `describe`):

```tsx
import { fireEvent } from '@testing-library/react'

describe('OverlayMobileNav — panel behaviour', () => {
  it('toggles aria-expanded on trigger click', () => {
    render(
      <OverlayMobileNav
        tree={flatTree}
        activeId="users"
        onSelect={vi.fn()}
      />,
    )
    const trigger = screen.getByRole('button')
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
  })

  it('renders sections as presentation and leaves as options when open', () => {
    render(
      <OverlayMobileNav
        tree={hierarchicalTree}
        activeId="voice"
        onSelect={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /open navigation/i }))
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    // Leaf-only top renders as option
    expect(screen.getByRole('option', { name: 'About me' })).toBeInTheDocument()
    // Section header renders as presentation (not as option)
    expect(screen.queryByRole('option', { name: 'Settings' })).toBeNull()
    // Children of the section render as options
    expect(screen.getByRole('option', { name: 'LLM Providers' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Voice' })).toBeInTheDocument()
    // Active leaf is aria-selected
    expect(screen.getByRole('option', { name: 'Voice' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByRole('option', { name: 'LLM Providers' })).toHaveAttribute(
      'aria-selected',
      'false',
    )
  })

  it('calls onSelect and closes panel when a leaf is clicked', () => {
    const onSelect = vi.fn()
    render(
      <OverlayMobileNav
        tree={hierarchicalTree}
        activeId="about-me"
        onSelect={onSelect}
      />,
    )
    const trigger = screen.getByRole('button', { name: /open navigation/i })
    fireEvent.click(trigger)
    fireEvent.click(screen.getByRole('option', { name: 'LLM Providers' }))
    expect(onSelect).toHaveBeenCalledWith('llm-providers')
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
  })

  it('does nothing when a section header is clicked', () => {
    const onSelect = vi.fn()
    render(
      <OverlayMobileNav
        tree={hierarchicalTree}
        activeId="about-me"
        onSelect={onSelect}
      />,
    )
    const trigger = screen.getByRole('button', { name: /open navigation/i })
    fireEvent.click(trigger)
    // Find the section header by its visible text — it has no role=option.
    fireEvent.click(screen.getByText('Settings'))
    expect(onSelect).not.toHaveBeenCalled()
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
  })
})
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
pnpm vitest run src/app/components/overlay-mobile-nav/OverlayMobileNav.test.tsx
```
Expected: FAIL — listbox not rendered, click does not toggle.

- [ ] **Step 3: Wire the panel into the component**

Replace the body of `OverlayMobileNav.tsx` with the following (full file):

```tsx
import { useId, useState } from 'react'
import { resolveCrumb } from './resolveCrumb'
import { isSection, type NavLeaf, type NavNode } from './types'

const EN_DASH = '–'
const DEFAULT_ACCENT = '#f5c542'

export interface OverlayMobileNavProps {
  tree: NavNode[]
  activeId: string
  onSelect: (id: string) => void
  /** Override the default gold; PersonaOverlay passes chakra.hex. */
  accentColour?: string
  /** Optional aria-label override for the trigger. */
  ariaLabel?: string
}

export function OverlayMobileNav({
  tree,
  activeId,
  onSelect,
  accentColour = DEFAULT_ACCENT,
  ariaLabel = 'Open navigation',
}: OverlayMobileNavProps) {
  const [open, setOpen] = useState(false)
  const crumb = resolveCrumb(tree, activeId)
  const panelId = useId()

  function handleLeafClick(leaf: NavLeaf) {
    onSelect(leaf.id)
    setOpen(false)
  }

  // Temporary scaffolding — used in later tasks.
  void accentColour

  return (
    <div className="relative">
      <button
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between rounded-md border border-white/12 bg-white/4 px-3 py-2.5"
      >
        <span className="text-[13px] font-medium text-white/92">
          {crumb.parent && (
            <>
              <span className="text-white/50 font-normal">{crumb.parent}</span>
              <span className="text-white/35 mx-1.5">{EN_DASH}</span>
            </>
          )}
          {crumb.leaf}
        </span>
        <span className="text-white/50 text-[14px]" aria-hidden>{open ? '▴' : '▾'}</span>
      </button>

      {open && (
        <ul
          id={panelId}
          role="listbox"
          className="absolute left-0 right-0 mt-1.5 max-h-[min(70vh,460px)] overflow-y-auto rounded-md border border-white/12 bg-[#13101e] shadow-2xl z-30"
        >
          {tree.map((node) =>
            isSection(node) ? (
              <li key={node.id} role="presentation">
                <div
                  aria-hidden
                  className="px-3.5 pt-3.5 pb-1.5 text-[10px] uppercase tracking-wider text-white/32 font-medium select-none"
                >
                  {node.label}
                </div>
                {node.children.map((child) => (
                  <LeafRow
                    key={child.id}
                    leaf={child}
                    indented
                    active={child.id === activeId}
                    onClick={() => handleLeafClick(child)}
                  />
                ))}
              </li>
            ) : (
              <LeafRow
                key={node.id}
                leaf={node}
                indented={false}
                active={node.id === activeId}
                onClick={() => handleLeafClick(node)}
              />
            ),
          )}
        </ul>
      )}
    </div>
  )
}

interface LeafRowProps {
  leaf: NavLeaf
  indented: boolean
  active: boolean
  onClick: () => void
}

function LeafRow({ leaf, indented, active, onClick }: LeafRowProps) {
  return (
    <li
      role="option"
      aria-selected={active}
      tabIndex={active ? 0 : -1}
      onClick={onClick}
      className={[
        'flex items-center gap-2 cursor-pointer border-b border-white/4 last:border-b-0',
        indented ? 'pl-6 pr-3.5 py-2.5 text-[12.5px]' : 'px-3.5 py-2.5 text-[13px]',
        active ? 'text-[#f5c542] bg-[#f5c54214]' : 'text-white/70',
      ].join(' ')}
    >
      <span className="flex-1">{leaf.label}</span>
    </li>
  )
}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pnpm vitest run src/app/components/overlay-mobile-nav/OverlayMobileNav.test.tsx
```
Expected: PASS, 7 tests (3 from Task 3 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/overlay-mobile-nav/
git commit -m "Wire panel rendering and leaf selection in OverlayMobileNav"
```

---

## Task 5: Backdrop close + Escape close

**Files:**
- Modify: `frontend/src/app/components/overlay-mobile-nav/OverlayMobileNav.tsx`
- Modify: `frontend/src/app/components/overlay-mobile-nav/OverlayMobileNav.test.tsx`

Add a transparent backdrop that covers the rest of the overlay (sibling to the panel) and an Escape-key handler.

- [ ] **Step 1: Add the failing tests**

Append to the `'OverlayMobileNav — panel behaviour'` describe block:

```tsx
it('closes the panel on Escape', () => {
  render(
    <OverlayMobileNav
      tree={flatTree}
      activeId="users"
      onSelect={vi.fn()}
    />,
  )
  const trigger = screen.getByRole('button', { name: /open navigation/i })
  fireEvent.click(trigger)
  fireEvent.keyDown(window, { key: 'Escape' })
  expect(trigger).toHaveAttribute('aria-expanded', 'false')
})

it('closes the panel on backdrop click', () => {
  render(
    <OverlayMobileNav
      tree={flatTree}
      activeId="users"
      onSelect={vi.fn()}
    />,
  )
  const trigger = screen.getByRole('button', { name: /open navigation/i })
  fireEvent.click(trigger)
  const backdrop = screen.getByTestId('overlay-mobile-nav-backdrop')
  fireEvent.click(backdrop)
  expect(trigger).toHaveAttribute('aria-expanded', 'false')
})

it('does not close on click inside the listbox', () => {
  render(
    <OverlayMobileNav
      tree={hierarchicalTree}
      activeId="about-me"
      onSelect={vi.fn()}
    />,
  )
  const trigger = screen.getByRole('button', { name: /open navigation/i })
  fireEvent.click(trigger)
  // Click on a non-clickable section header — panel must stay open.
  fireEvent.click(screen.getByText('Settings'))
  expect(trigger).toHaveAttribute('aria-expanded', 'true')
})
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pnpm vitest run src/app/components/overlay-mobile-nav/OverlayMobileNav.test.tsx
```
Expected: 2 NEW FAIL (Escape, backdrop). `does not close on click inside listbox` already passes from Task 4 — leave it as a regression guard.

- [ ] **Step 3: Add the backdrop and Escape handler**

Replace the JSX body of `OverlayMobileNav` (everything inside the `return`) with:

```tsx
  return (
    <div className="relative">
      <button
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between rounded-md border border-white/12 bg-white/4 px-3 py-2.5"
      >
        <span className="text-[13px] font-medium text-white/92">
          {crumb.parent && (
            <>
              <span className="text-white/50 font-normal">{crumb.parent}</span>
              <span className="text-white/35 mx-1.5">{EN_DASH}</span>
            </>
          )}
          {crumb.leaf}
        </span>
        <span className="text-white/50 text-[14px]" aria-hidden>{open ? '▴' : '▾'}</span>
      </button>

      {open && (
        <>
          <div
            data-testid="overlay-mobile-nav-backdrop"
            aria-hidden
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-20"
          />
          <ul
            id={panelId}
            role="listbox"
            className="absolute left-0 right-0 mt-1.5 max-h-[min(70vh,460px)] overflow-y-auto rounded-md border border-white/12 bg-[#13101e] shadow-2xl z-30"
          >
            {tree.map((node) =>
              isSection(node) ? (
                <li key={node.id} role="presentation">
                  <div
                    aria-hidden
                    className="px-3.5 pt-3.5 pb-1.5 text-[10px] uppercase tracking-wider text-white/32 font-medium select-none"
                  >
                    {node.label}
                  </div>
                  {node.children.map((child) => (
                    <LeafRow
                      key={child.id}
                      leaf={child}
                      indented
                      active={child.id === activeId}
                      onClick={() => handleLeafClick(child)}
                    />
                  ))}
                </li>
              ) : (
                <LeafRow
                  key={node.id}
                  leaf={node}
                  indented={false}
                  active={node.id === activeId}
                  onClick={() => handleLeafClick(node)}
                />
              ),
            )}
          </ul>
        </>
      )}
    </div>
  )
```

Add an Escape-key effect at the top of the component, just below the existing `useState` and helpers (replace the existing `useState`/`useId` lines and add `useEffect`):

```tsx
import { useEffect, useId, useState } from 'react'
```

Inside the component, immediately after `const panelId = useId()`:

```tsx
  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pnpm vitest run src/app/components/overlay-mobile-nav/OverlayMobileNav.test.tsx
```
Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/overlay-mobile-nav/
git commit -m "Close OverlayMobileNav on Escape and backdrop click"
```

---

## Task 6: Badge propagation

**Files:**
- Modify: `frontend/src/app/components/overlay-mobile-nav/OverlayMobileNav.tsx`
- Modify: `frontend/src/app/components/overlay-mobile-nav/OverlayMobileNav.test.tsx`

A leaf with `badge: true` shows a red `!`. If a flagged leaf lives under a section, the section header also shows a `!`. Propagation happens inside `OverlayMobileNav` based on the `badge` field of each `NavLeaf`.

- [ ] **Step 1: Add the failing tests**

Append a new describe block at the bottom of `OverlayMobileNav.test.tsx`:

```tsx
const treeWithBadge: NavNode[] = [
  { id: 'about-me', label: 'About me' },
  {
    id: 'settings',
    label: 'Settings',
    children: [
      { id: 'llm-providers', label: 'LLM Providers', badge: true },
      { id: 'voice', label: 'Voice' },
    ],
  },
]

describe('OverlayMobileNav — badge propagation', () => {
  it('renders a badge on the flagged leaf', () => {
    render(
      <OverlayMobileNav
        tree={treeWithBadge}
        activeId="about-me"
        onSelect={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /open navigation/i }))
    const llm = screen.getByRole('option', { name: /LLM Providers/i })
    expect(llm.querySelector('[data-testid="leaf-badge"]')).toBeTruthy()
  })

  it('renders a badge on the section header containing a flagged leaf', () => {
    render(
      <OverlayMobileNav
        tree={treeWithBadge}
        activeId="about-me"
        onSelect={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /open navigation/i }))
    // Only Settings has a flagged child in this tree, so exactly one
    // section-badge should render.
    expect(screen.queryAllByTestId('section-badge')).toHaveLength(1)
  })

  it('does not render a section badge if no child is flagged', () => {
    const tree: NavNode[] = [
      {
        id: 'chats',
        label: 'Chats',
        children: [{ id: 'history', label: 'History' }],
      },
    ]
    render(
      <OverlayMobileNav tree={tree} activeId="history" onSelect={vi.fn()} />,
    )
    fireEvent.click(screen.getByRole('button', { name: /open navigation/i }))
    expect(screen.queryByTestId('section-badge')).toBeNull()
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pnpm vitest run src/app/components/overlay-mobile-nav/OverlayMobileNav.test.tsx
```
Expected: 2 NEW FAIL.

- [ ] **Step 3: Implement badge rendering**

In `OverlayMobileNav.tsx`, replace `LeafRow` with:

```tsx
function LeafRow({ leaf, indented, active, onClick }: LeafRowProps) {
  return (
    <li
      role="option"
      aria-selected={active}
      tabIndex={active ? 0 : -1}
      onClick={onClick}
      className={[
        'flex items-center gap-2 cursor-pointer border-b border-white/4 last:border-b-0',
        indented ? 'pl-6 pr-3.5 py-2.5 text-[12.5px]' : 'px-3.5 py-2.5 text-[13px]',
        active ? 'text-[#f5c542] bg-[#f5c54214]' : 'text-white/70',
      ].join(' ')}
    >
      <span className="flex-1">{leaf.label}</span>
      {leaf.badge && (
        <span
          data-testid="leaf-badge"
          aria-label="Attention required"
          title="Attention required"
          className="text-red-400 text-[10px]"
        >
          !
        </span>
      )}
    </li>
  )
}
```

Then update the section-rendering branch (inside the `tree.map` of the `<ul>`) to add a header badge when any child is flagged:

```tsx
            {tree.map((node) =>
              isSection(node) ? (
                <li key={node.id} role="presentation">
                  <div
                    aria-hidden
                    className="px-3.5 pt-3.5 pb-1.5 text-[10px] uppercase tracking-wider text-white/32 font-medium select-none flex items-center gap-1.5"
                  >
                    {node.label}
                    {node.children.some((c) => c.badge) && (
                      <span
                        data-testid="section-badge"
                        aria-label="Attention required"
                        className="text-red-400 text-[10px] normal-case"
                      >
                        !
                      </span>
                    )}
                  </div>
                  {node.children.map((child) => (
                    <LeafRow
                      key={child.id}
                      leaf={child}
                      indented
                      active={child.id === activeId}
                      onClick={() => handleLeafClick(child)}
                    />
                  ))}
                </li>
              ) : (
                <LeafRow
                  key={node.id}
                  leaf={node}
                  indented={false}
                  active={node.id === activeId}
                  onClick={() => handleLeafClick(node)}
                />
              ),
            )}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pnpm vitest run src/app/components/overlay-mobile-nav/OverlayMobileNav.test.tsx
```
Expected: PASS, 13 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/overlay-mobile-nav/
git commit -m "Add badge propagation to OverlayMobileNav sections"
```

---

## Task 7: Accent colour override

**Files:**
- Modify: `frontend/src/app/components/overlay-mobile-nav/OverlayMobileNav.tsx`
- Modify: `frontend/src/app/components/overlay-mobile-nav/OverlayMobileNav.test.tsx`

The `accentColour` prop overrides the gold default for the open-state border colour, the caret colour when open, and the active leaf row's text + background tint. Used by `PersonaOverlay` with `chakra.hex`.

- [ ] **Step 1: Add the failing test**

Append to the bottom of `OverlayMobileNav.test.tsx`:

```tsx
describe('OverlayMobileNav — accent colour', () => {
  it('applies the override colour to the open trigger border and active row', () => {
    render(
      <OverlayMobileNav
        tree={hierarchicalTree}
        activeId="voice"
        onSelect={vi.fn()}
        accentColour="#ff00aa"
      />,
    )
    const trigger = screen.getByRole('button', { name: /open navigation/i })
    fireEvent.click(trigger)
    // Trigger picks up the accent on its inline border-color when open.
    expect(trigger.style.borderColor).toMatch(/#ff00aa/i)
    // Active leaf picks up the accent on its inline color + background.
    const active = screen.getByRole('option', { name: 'Voice' })
    expect(active.style.color).toMatch(/#ff00aa/i)
    expect(active.style.backgroundColor).not.toBe('')
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pnpm vitest run src/app/components/overlay-mobile-nav/OverlayMobileNav.test.tsx
```
Expected: 1 NEW FAIL.

- [ ] **Step 3: Wire the prop into inline styles**

In `OverlayMobileNav.tsx`, drop the temporary `void accentColour` line (it's now used). Add an `accentBg` helper next to the `EN_DASH` constant:

```tsx
function accentBackground(colour: string): string {
  // ~8% opacity over the panel background. Hex+alpha is widely supported.
  return colour + '14'
}
```

Update the `<button>` element to apply the open-state border via inline style:

```tsx
      <button
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        style={open ? { borderColor: accentColour } : undefined}
        className="w-full flex items-center justify-between rounded-md border border-white/12 bg-white/4 px-3 py-2.5"
      >
```

Update the caret span to use the accent when open:

```tsx
        <span
          className="text-[14px]"
          style={{ color: open ? accentColour : 'rgba(255,255,255,0.5)' }}
          aria-hidden
        >
          {open ? '▴' : '▾'}
        </span>
```

Pass `accentColour` into `LeafRow` and switch to inline styles for the active state:

```tsx
                  {node.children.map((child) => (
                    <LeafRow
                      key={child.id}
                      leaf={child}
                      indented
                      active={child.id === activeId}
                      accentColour={accentColour}
                      onClick={() => handleLeafClick(child)}
                    />
                  ))}
              ) : (
                <LeafRow
                  key={node.id}
                  leaf={node}
                  indented={false}
                  active={node.id === activeId}
                  accentColour={accentColour}
                  onClick={() => handleLeafClick(node)}
                />
              ),
```

Update `LeafRowProps` and `LeafRow`:

```tsx
interface LeafRowProps {
  leaf: NavLeaf
  indented: boolean
  active: boolean
  accentColour: string
  onClick: () => void
}

function LeafRow({ leaf, indented, active, accentColour, onClick }: LeafRowProps) {
  return (
    <li
      role="option"
      aria-selected={active}
      tabIndex={active ? 0 : -1}
      onClick={onClick}
      style={
        active
          ? { color: accentColour, backgroundColor: accentBackground(accentColour) }
          : undefined
      }
      className={[
        'flex items-center gap-2 cursor-pointer border-b border-white/4 last:border-b-0',
        indented ? 'pl-6 pr-3.5 py-2.5 text-[12.5px]' : 'px-3.5 py-2.5 text-[13px]',
        active ? '' : 'text-white/70',
      ].join(' ')}
    >
      <span className="flex-1">{leaf.label}</span>
      {leaf.badge && (
        <span
          data-testid="leaf-badge"
          aria-label="Attention required"
          title="Attention required"
          className="text-red-400 text-[10px]"
        >
          !
        </span>
      )}
    </li>
  )
}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pnpm vitest run src/app/components/overlay-mobile-nav/OverlayMobileNav.test.tsx
```
Expected: PASS, 14 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/overlay-mobile-nav/
git commit -m "Honour accentColour prop in OverlayMobileNav trigger and active row"
```

---

## Task 8: Initial focus + scrollIntoView on open + arrow-key navigation

**Files:**
- Modify: `frontend/src/app/components/overlay-mobile-nav/OverlayMobileNav.tsx`
- Modify: `frontend/src/app/components/overlay-mobile-nav/OverlayMobileNav.test.tsx`

When the panel opens, focus moves to the active option and that option scrolls into view. Arrow Up / Down moves focus through clickable leaves only (skipping section headers). Enter / Space on a focused leaf selects it.

- [ ] **Step 1: Add the failing tests**

Append to the bottom of `OverlayMobileNav.test.tsx`:

```tsx
import userEvent from '@testing-library/user-event'

describe('OverlayMobileNav — keyboard and focus', () => {
  it('focuses the active option and scrolls it into view on open', () => {
    const scrollSpy = vi.spyOn(Element.prototype, 'scrollIntoView')
    render(
      <OverlayMobileNav
        tree={hierarchicalTree}
        activeId="voice"
        onSelect={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /open navigation/i }))
    expect(screen.getByRole('option', { name: 'Voice' })).toHaveFocus()
    expect(scrollSpy).toHaveBeenCalled()
    scrollSpy.mockRestore()
  })

  it('moves focus through clickable leaves with ArrowDown / ArrowUp', async () => {
    const user = userEvent.setup()
    render(
      <OverlayMobileNav
        tree={hierarchicalTree}
        activeId="about-me"
        onSelect={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /open navigation/i }))
    expect(screen.getByRole('option', { name: 'About me' })).toHaveFocus()
    await user.keyboard('{ArrowDown}')
    expect(screen.getByRole('option', { name: 'LLM Providers' })).toHaveFocus()
    await user.keyboard('{ArrowDown}')
    expect(screen.getByRole('option', { name: 'Voice' })).toHaveFocus()
    await user.keyboard('{ArrowUp}')
    expect(screen.getByRole('option', { name: 'LLM Providers' })).toHaveFocus()
  })

  it('selects the focused leaf on Enter', async () => {
    const onSelect = vi.fn()
    const user = userEvent.setup()
    render(
      <OverlayMobileNav
        tree={hierarchicalTree}
        activeId="about-me"
        onSelect={onSelect}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /open navigation/i }))
    await user.keyboard('{ArrowDown}{Enter}')
    expect(onSelect).toHaveBeenCalledWith('llm-providers')
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pnpm vitest run src/app/components/overlay-mobile-nav/OverlayMobileNav.test.tsx
```
Expected: 3 NEW FAIL.

- [ ] **Step 3: Implement focus, scrollIntoView, and arrow nav**

In `OverlayMobileNav.tsx`, add a `useRef` import and a leaf-id list helper. Inside the component, alongside the existing state, add:

```tsx
import { useEffect, useId, useMemo, useRef, useState } from 'react'
```

Inside the component:

```tsx
  const listboxRef = useRef<HTMLUListElement>(null)

  // Flat list of clickable leaf ids in render order — used for ArrowUp / ArrowDown.
  const orderedLeafIds = useMemo(() => {
    const ids: string[] = []
    for (const node of tree) {
      if (isSection(node)) {
        for (const child of node.children) ids.push(child.id)
      } else {
        ids.push(node.id)
      }
    }
    return ids
  }, [tree])

  // On open: focus the active option and scroll it into view.
  useEffect(() => {
    if (!open) return
    const root = listboxRef.current
    if (!root) return
    const activeEl = root.querySelector<HTMLElement>(`[data-leaf-id="${activeId}"]`)
      ?? root.querySelector<HTMLElement>('[role="option"]')
    if (activeEl) {
      activeEl.focus()
      activeEl.scrollIntoView({ block: 'nearest' })
    }
  }, [open, activeId])

  function moveFocus(delta: 1 | -1) {
    const root = listboxRef.current
    if (!root) return
    const focused = document.activeElement as HTMLElement | null
    const currentId = focused?.getAttribute('data-leaf-id') ?? activeId
    const idx = orderedLeafIds.indexOf(currentId)
    const nextIdx = Math.max(0, Math.min(orderedLeafIds.length - 1, idx + delta))
    const nextId = orderedLeafIds[nextIdx]
    const next = root.querySelector<HTMLElement>(`[data-leaf-id="${nextId}"]`)
    next?.focus()
  }

  function handleListboxKeyDown(e: React.KeyboardEvent<HTMLUListElement>) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      moveFocus(1)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      moveFocus(-1)
    } else if (e.key === 'Enter' || e.key === ' ') {
      const focused = document.activeElement as HTMLElement | null
      const id = focused?.getAttribute('data-leaf-id')
      if (id) {
        e.preventDefault()
        onSelect(id)
        setOpen(false)
      }
    }
  }
```

Wire the ref and key handler onto the `<ul>`:

```tsx
          <ul
            id={panelId}
            ref={listboxRef}
            role="listbox"
            onKeyDown={handleListboxKeyDown}
            className="absolute left-0 right-0 mt-1.5 max-h-[min(70vh,460px)] overflow-y-auto rounded-md border border-white/12 bg-[#13101e] shadow-2xl z-30"
          >
```

Add `data-leaf-id` to each `LeafRow`:

```tsx
function LeafRow({ leaf, indented, active, accentColour, onClick }: LeafRowProps) {
  return (
    <li
      role="option"
      aria-selected={active}
      tabIndex={active ? 0 : -1}
      data-leaf-id={leaf.id}
      onClick={onClick}
      style={
        active
          ? { color: accentColour, backgroundColor: accentBackground(accentColour) }
          : undefined
      }
      className={[
        'flex items-center gap-2 cursor-pointer border-b border-white/4 last:border-b-0 outline-none focus:bg-white/8',
        indented ? 'pl-6 pr-3.5 py-2.5 text-[12.5px]' : 'px-3.5 py-2.5 text-[13px]',
        active ? '' : 'text-white/70',
      ].join(' ')}
    >
      <span className="flex-1">{leaf.label}</span>
      {leaf.badge && (
        <span
          data-testid="leaf-badge"
          aria-label="Attention required"
          title="Attention required"
          className="text-red-400 text-[10px]"
        >
          !
        </span>
      )}
    </li>
  )
}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pnpm vitest run src/app/components/overlay-mobile-nav/OverlayMobileNav.test.tsx
```
Expected: PASS, 17 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/overlay-mobile-nav/
git commit -m "Add keyboard navigation and initial focus to OverlayMobileNav"
```

---

## Task 9: userModalTree converter

**Files:**
- Modify: `frontend/src/app/components/user-modal/userModalTree.ts`

Add a `toMobileNavTree()` function that converts the existing `TABS_TREE` to `NavNode[]`. The conversion is a 1:1 map: top tabs without `children` become `NavLeaf`, top tabs with `children` become `NavSection`. The function takes optional `badges: Record<string, boolean>` so the caller (UserModal) can pass `{ 'llm-providers': hasNoLlmConnection }` and the badges flow through.

- [ ] **Step 1: Write the failing test**

Append to an existing test file. The simplest place is a new file because there is no existing test for `userModalTree.ts`:

Create `frontend/src/app/components/user-modal/userModalTree.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { toMobileNavTree } from './userModalTree'

describe('toMobileNavTree', () => {
  it('converts TABS_TREE to NavNode[] preserving order, leaves and sections', () => {
    const nodes = toMobileNavTree()
    // The first entry is About me — a leaf-only top tab.
    expect(nodes[0]).toEqual({ id: 'about-me', label: 'About me' })
    // Settings is a section with children.
    const settings = nodes.find((n) => n.id === 'settings')
    expect(settings).toBeTruthy()
    expect('children' in settings!).toBe(true)
    if ('children' in settings!) {
      expect(settings.children[0]).toEqual({ id: 'llm-providers', label: 'LLM Providers' })
    }
  })

  it('applies badges by leaf id', () => {
    const nodes = toMobileNavTree({ 'llm-providers': true })
    const settings = nodes.find((n) => n.id === 'settings')!
    if (!('children' in settings)) throw new Error('expected section')
    const llm = settings.children.find((c) => c.id === 'llm-providers')!
    expect(llm.badge).toBe(true)
    // Other leaves are not badged.
    const voice = settings.children.find((c) => c.id === 'voice')!
    expect(voice.badge).toBeUndefined()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pnpm vitest run src/app/components/user-modal/userModalTree.test.ts
```
Expected: FAIL — `toMobileNavTree` not exported.

- [ ] **Step 3: Add the converter**

Append to `frontend/src/app/components/user-modal/userModalTree.ts`:

```ts
import type { NavLeaf, NavNode, NavSection } from '../overlay-mobile-nav/types'

/**
 * Convert `TABS_TREE` to the shape `OverlayMobileNav` consumes.
 *
 * `badges` is keyed by leaf id; pass `true` to flag a leaf so the mobile
 * nav renders the leaf and its containing section header with the
 * red-`!` indicator.
 */
export function toMobileNavTree(
  badges: Record<string, boolean> = {},
): NavNode[] {
  return TABS_TREE.map((top): NavNode => {
    if (top.children) {
      const section: NavSection = {
        id: top.id,
        label: top.label,
        children: top.children.map(
          (sub): NavLeaf => ({
            id: sub.id,
            label: sub.label,
            badge: badges[sub.id] || undefined,
          }),
        ),
      }
      return section
    }
    const leaf: NavLeaf = {
      id: top.id,
      label: top.label,
      badge: badges[top.id] || undefined,
    }
    return leaf
  })
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pnpm vitest run src/app/components/user-modal/userModalTree.test.ts
```
Expected: PASS, 2 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/user-modal/userModalTree.ts \
        frontend/src/app/components/user-modal/userModalTree.test.ts
git commit -m "Add toMobileNavTree converter for UserModal mobile nav"
```

---

## Task 10: Mount OverlayMobileNav in UserModal

**Files:**
- Modify: `frontend/src/app/components/user-modal/UserModal.tsx`

Hide the existing top-tab and sub-tab rows below `lg:` and render `OverlayMobileNav` in their place. The active id is `activeSub ?? activeTop`. On select, look up the leaf with `resolveLeaf` (already exported from `userModalTree.ts`), call `setLastSub` for the parent, and call `onTabChange` with `(top, sub)` or `(top)`.

- [ ] **Step 1: Update the imports**

At the top of `UserModal.tsx`, add:

```tsx
import { OverlayMobileNav } from '../overlay-mobile-nav/OverlayMobileNav'
import { TABS_TREE, resolveLeaf, toMobileNavTree, type TopTabId, type SubTabId } from './userModalTree'
```

(replace the existing `TABS_TREE, type TopTabId, type SubTabId` import line.)

- [ ] **Step 2: Build the mobile nav inputs and handler**

Inside the `UserModal` function, after the `settingsHasProblem` line, add:

```tsx
  const mobileTree = toMobileNavTree({ 'llm-providers': hasNoLlmConnection })
  const mobileActiveId: string = activeSub ?? activeTop

  function handleMobileSelect(id: string) {
    const resolved = resolveLeaf(id)
    if (resolved.sub) {
      setLastSub(resolved.top, resolved.sub)
      onTabChange(resolved.top, resolved.sub)
    } else {
      onTabChange(resolved.top)
    }
  }
```

- [ ] **Step 3: Gate the desktop tab rows under `lg:` and add the mobile row**

Replace the existing top-tab `<div role="tablist" ...>` (line 172) `className` to start with `hidden lg:flex`:

```tsx
        <div role="tablist" aria-label="User area sections" className="hidden lg:flex flex-wrap border-b border-white/6 px-4 flex-shrink-0">
```

Replace the existing sub-tab `<div role="tablist" ...>` (line 204) `className` to start with `hidden lg:flex`:

```tsx
          <div role="tablist" aria-label={`${activeTopNode?.label ?? ''} sub-sections`} className="hidden lg:flex flex-wrap gap-1 px-4 py-2 border-b border-white/6 bg-white/2 flex-shrink-0">
```

Immediately after the closing `</div>` of the sub-tab block (after line 232, i.e. right above the `{/* Tab content */}` comment), insert the mobile nav row:

```tsx
        {/* Mobile nav row — replaces the desktop tab rows below lg */}
        <div className="lg:hidden border-b border-white/6 px-4 py-2 bg-white/2 flex-shrink-0">
          <OverlayMobileNav
            tree={mobileTree}
            activeId={mobileActiveId}
            onSelect={handleMobileSelect}
            ariaLabel="Open user area navigation"
          />
        </div>
```

- [ ] **Step 4: Build-check**

```bash
pnpm tsc --noEmit
pnpm vitest run src/app/components/user-modal/UserModal.test.tsx
```
Expected: clean tsc; existing UserModal tests still pass (they exercise the desktop path which is `lg:` only — render does not crash because both branches still render in jsdom).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/user-modal/UserModal.tsx
git commit -m "Mount OverlayMobileNav under lg: in UserModal"
```

---

## Task 11: Mount OverlayMobileNav in AdminModal

**Files:**
- Modify: `frontend/src/app/components/admin-modal/AdminModal.tsx`

Flat tab list: map the existing `TABS` array directly to `NavLeaf[]`.

- [ ] **Step 1: Update the imports and add the mobile mapping**

At the top of `AdminModal.tsx`, add:

```tsx
import { OverlayMobileNav } from '../overlay-mobile-nav/OverlayMobileNav'
import type { NavLeaf } from '../overlay-mobile-nav/types'
```

Inside the `AdminModal` function, after the `useEffect` that handles Escape / Tab, add:

```tsx
  const mobileTree: NavLeaf[] = TABS.map((tab) => ({ id: tab.id, label: tab.label }))
```

- [ ] **Step 2: Gate the desktop tab row and add the mobile row**

Replace the existing tab-bar `<div role="tablist" ...>` (line 100) `className` to start with `hidden lg:flex`:

```tsx
        <div role="tablist" aria-label="Admin sections" className="hidden lg:flex flex-wrap border-b border-white/6 px-4 flex-shrink-0">
```

Immediately after the closing `</div>` of that block (right above the `<div role="tabpanel"...>` content block, i.e. after line 124), insert:

```tsx
        {/* Mobile nav row — replaces the desktop tab row below lg */}
        <div className="lg:hidden border-b border-white/6 px-4 py-2 bg-white/2 flex-shrink-0">
          <OverlayMobileNav
            tree={mobileTree}
            activeId={activeTab}
            onSelect={(id) => onTabChange(id as AdminModalTab)}
            ariaLabel="Open admin navigation"
          />
        </div>
```

- [ ] **Step 3: Build-check**

```bash
pnpm tsc --noEmit
```
Expected: clean exit.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/admin-modal/AdminModal.tsx
git commit -m "Mount OverlayMobileNav under lg: in AdminModal"
```

---

## Task 12: Mount OverlayMobileNav in PersonaOverlay

**Files:**
- Modify: `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx`

Flat tab list with the existing filter rules (creation mode shows only `edit`; `voice` hidden when no engine resolved and not currently active). Pass `chakra.hex` as `accentColour` so the trigger and active row pick up the persona's colour.

- [ ] **Step 1: Update the imports and build the mobile mapping**

At the top of `PersonaOverlay.tsx`, add:

```tsx
import { OverlayMobileNav } from '../overlay-mobile-nav/OverlayMobileNav'
import type { NavLeaf } from '../overlay-mobile-nav/types'
```

Inside the `PersonaOverlay` function, after the existing `voiceEnabled` / `chakra` lines, add:

```tsx
  const mobileTree: NavLeaf[] = TABS.filter((tab) => {
    if (isCreating && tab.id !== 'edit') return false
    if (tab.id === 'voice' && !voiceEnabled && activeTab !== 'voice') return false
    return true
  }).map((tab) => ({ id: tab.id, label: tab.label }))
```

- [ ] **Step 2: Gate the desktop tab bar and add the mobile row**

Replace the existing `<div className="flex flex-wrap px-4 flex-shrink-0" role="tablist" ...>` (line 218) `className` to start with `hidden lg:flex`:

```tsx
        <div
          className="hidden lg:flex flex-wrap px-4 flex-shrink-0"
          role="tablist"
          aria-label="Persona sections"
          style={{ borderBottom: `1px solid ${borderColour}` }}
        >
```

Immediately after the closing `</div>` of that block (right above the `{/* Tab content */}` comment, around line 263), insert:

```tsx
        {/* Mobile nav row — replaces the desktop tab bar below lg */}
        <div
          className="lg:hidden px-4 py-2 flex-shrink-0"
          style={{
            borderBottom: `1px solid ${borderColour}`,
            background: 'rgba(255,255,255,0.02)',
          }}
        >
          <OverlayMobileNav
            tree={mobileTree}
            activeId={activeTab}
            onSelect={(id) => onTabChange(id as PersonaOverlayTab)}
            accentColour={chakra.hex}
            ariaLabel="Open persona navigation"
          />
        </div>
```

- [ ] **Step 3: Build-check**

```bash
pnpm tsc --noEmit
```
Expected: clean exit.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/persona-overlay/PersonaOverlay.tsx
git commit -m "Mount OverlayMobileNav under lg: in PersonaOverlay with chakra accent"
```

---

## Task 13: Final build verification

**Files:** none.

Make sure the whole frontend compiles and all tests pass.

- [ ] **Step 1: Run the full type check**

```bash
pnpm tsc --noEmit
```
Expected: clean exit.

- [ ] **Step 2: Run the full test suite**

```bash
pnpm vitest run
```
Expected: all tests pass (existing + the new ones added in Tasks 2–9).

- [ ] **Step 3: Run the production build**

```bash
pnpm run build
```
Expected: clean exit. `tsc -b` (which `pnpm run build` invokes) is stricter than `tsc --noEmit` and is the gate that CI runs.

- [ ] **Step 4: Manual verification on real device (Chris)**

Hand off to Chris for the manual-verification block in `devdocs/specs/2026-04-30-mobile-overlay-navigation.md` ("Manual verification" section). Do not mark this task complete from inside the agent — the human runs it on a phone.

---

## Out of scope

- Animation polish on the panel (slide / fade in).
- Replacing the burger icon in `AppLayout`.
- Touching the desktop tab styling.
- Tablet-specific tier — `< lg` is one treatment, `>= lg` is the other.

# Prototype Feedback Bug Bash Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement seven small frontend fixes from prototype-tester
feedback: persona-create routing bug, Personas-tab Import button,
AddPersonaCard split, API-key autofill suppression, history-item
rename, iPhone PWA safe-area-top, and iOS input-zoom prevention.

**Architecture:** All changes are frontend-only and target
`frontend/src/`. The chat-session-rename API used by Item 5 already
exists on both ends (`updateSession` in
`frontend/src/core/api/chat.ts:210`, handler in
`backend/modules/chat/_handlers.py:349`). No backend or shared-contract
changes.

**Tech Stack:** React 19, TypeScript, Tailwind, Vitest +
@testing-library/react. Existing back-button overlay system in
`frontend/src/core/hooks/useBackButtonClose.ts`.

---

## Global rules for every task

- After each task: run `pnpm run build` from `frontend/`. The build
  must pass — `pnpm tsc --noEmit` is **not** a substitute, the project
  uses `tsc -b` in `pnpm run build` and that catches stricter errors.
- After each task: run the touched tests with `pnpm vitest run <path>`.
- Commit after each task with a short imperative message.
- **Do not merge to master, do not push to origin, do not switch
  branches.** The dispatcher takes care of merge after the whole batch
  passes review.
- The user is Chris (German-speaking, British English in code). Code,
  comments, and identifiers stay in British English.

---

### Task 1: Fix `+ Create persona` overlay-swap race (Item 1)

**Files:**
- Modify: `frontend/src/app/layouts/AppLayout.tsx:163-170`

**Background:** `openPersonaOverlay` calls `setModalOpen(false)` and
`setAdminTab(null)` followed by `setPersonaOverlay({ ... })` in the
same tick. The user-modal's unmount fires `history.back()` (via
`useBackButtonClose` cleanup), the persona-overlay mount fires
`pushState`, the popstate from the back races and the global
`BackButtonProvider` interprets it as a user-back, immediately closing
the just-opened persona-overlay. The codebase already has the
remedy: `startOverlayTransition('source-id')` from
`useBackButtonClose.ts:17`, used by the sidebar at `Sidebar.tsx:166`
and `:177`. We need to call it before the cross-overlay swap.

- [ ] **Step 1: Read existing code to confirm imports and signature**

Run:
```bash
sed -n '1,40p' frontend/src/app/layouts/AppLayout.tsx
```
Expected: see the existing import block. Note whether
`startOverlayTransition` is already imported (it is **not**, as of the
spec — confirm).

- [ ] **Step 2: Add the import**

In `frontend/src/app/layouts/AppLayout.tsx`, find the existing import
of `useBackButtonClose` (search: `useBackButtonClose`). The hook lives
in `../../core/hooks/useBackButtonClose`.

If `useBackButtonClose` is imported, extend its import to also pull
`startOverlayTransition`:

```ts
import { useBackButtonClose, startOverlayTransition } from '../../core/hooks/useBackButtonClose'
```

If `useBackButtonClose` is **not** imported in this file, add a fresh
import:

```ts
import { startOverlayTransition } from '../../core/hooks/useBackButtonClose'
```

- [ ] **Step 3: Wrap the cross-overlay state changes**

Find the `openPersonaOverlay` callback at around line 163. Current
shape:

```ts
const openPersonaOverlay = useCallback(
  (personaId: string | null, tab: PersonaOverlayTab = "overview") => {
    setModalOpen(false)
    setAdminTab(null)
    setPersonaOverlay({ personaId, tab })
  },
  [],
)
```

Replace with:

```ts
const openPersonaOverlay = useCallback(
  (personaId: string | null, tab: PersonaOverlayTab = "overview") => {
    if (modalOpen) startOverlayTransition('user-modal')
    else if (adminTab !== null) startOverlayTransition('admin-modal')
    setModalOpen(false)
    setAdminTab(null)
    setPersonaOverlay({ personaId, tab })
  },
  [modalOpen, adminTab],
)
```

The `else if` matters: only one overlay can have the back-button slot
at any given time, so we donate from whichever is currently open.

- [ ] **Step 4: Audit other cross-overlay handlers in AppLayout**

Run:
```bash
rg -n "setModalOpen\(false\)|setAdminTab\(null\)|setPersonaOverlay" frontend/src/app/layouts/AppLayout.tsx
```

For every handler that sets one of these to a closed state and *also*
opens a different overlay in the same tick, apply the same
`startOverlayTransition('source-id')` treatment. If none other do,
move on.

- [ ] **Step 5: Verify build**

Run from `frontend/`:
```bash
pnpm run build
```
Expected: clean build, no TypeScript errors.

- [ ] **Step 6: Manual verification**

Start the dev server (`pnpm dev`), open the user-modal, navigate to
Personas tab, click `+ Create persona`. The user-modal closes and the
persona-overlay opens on the Edit tab, with name input focused (or at
least visible and editable). Verify on both desktop and mobile
viewport sizes (DevTools mobile emulation is fine for the swap test).

The fix is verified when the persona-overlay does not flash and
disappear.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/layouts/AppLayout.tsx
git commit -m "Fix overlay-swap race when opening persona-overlay from user-modal"
```

---

### Task 2: Add Rename to chat-history items (Item 5)

**Files:**
- Modify: `frontend/src/app/components/sidebar/HistoryItem.tsx`
- Modify (caller): `frontend/src/app/components/sidebar/Sidebar.tsx`
  (and any other place that renders `<HistoryItem>` — confirm via
  grep)
- Test: `frontend/src/app/components/sidebar/__tests__/HistoryItem.test.tsx`
  (create)

**Background:** Reuse the existing `chatApi.updateSession(sessionId,
{ title })` from `frontend/src/core/api/chat.ts:210`. The backend
already publishes `ChatSessionTitleUpdatedEvent` so other tabs pick
up the rename.

- [ ] **Step 1: Find all `HistoryItem` usages**

Run:
```bash
rg -n "HistoryItem" frontend/src --type-add 'tsx:*.tsx' -t tsx -t ts
```

Note every place that renders `<HistoryItem>`. The list will tell us
which call sites need the new `onRename` prop.

- [ ] **Step 2: Write the failing test**

Create `frontend/src/app/components/sidebar/__tests__/HistoryItem.test.tsx`:

```tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { HistoryItem } from '../HistoryItem'

function makeSession(overrides = {}) {
  return {
    id: 's1',
    persona_id: 'p1',
    title: 'Old title',
    updated_at: '2026-05-01T00:00:00Z',
    ...overrides,
  } as any
}

function renderItem(props: Partial<React.ComponentProps<typeof HistoryItem>> = {}) {
  return render(
    <MemoryRouter>
      <HistoryItem
        session={makeSession()}
        isPinned={false}
        isActive={false}
        onClick={vi.fn()}
        onDelete={vi.fn()}
        onTogglePin={vi.fn()}
        onRename={vi.fn()}
        {...props}
      />
    </MemoryRouter>,
  )
}

describe('HistoryItem rename', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows Rename in the overflow menu', () => {
    renderItem()
    fireEvent.click(screen.getByLabelText('More options'))
    expect(screen.getByText('Rename')).toBeInTheDocument()
  })

  it('clicking Rename activates inline edit mode pre-filled with the current title', () => {
    renderItem()
    fireEvent.click(screen.getByLabelText('More options'))
    fireEvent.click(screen.getByText('Rename'))
    const input = screen.getByDisplayValue('Old title') as HTMLInputElement
    expect(input).toHaveFocus()
  })

  it('Enter saves and calls onRename with trimmed value', () => {
    const onRename = vi.fn()
    renderItem({ onRename })
    fireEvent.click(screen.getByLabelText('More options'))
    fireEvent.click(screen.getByText('Rename'))
    const input = screen.getByDisplayValue('Old title')
    fireEvent.change(input, { target: { value: '  New title  ' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onRename).toHaveBeenCalledWith(expect.objectContaining({ id: 's1' }), 'New title')
  })

  it('Escape cancels and does not call onRename', () => {
    const onRename = vi.fn()
    renderItem({ onRename })
    fireEvent.click(screen.getByLabelText('More options'))
    fireEvent.click(screen.getByText('Rename'))
    const input = screen.getByDisplayValue('Old title')
    fireEvent.change(input, { target: { value: 'Discarded' } })
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(onRename).not.toHaveBeenCalled()
  })

  it('blur saves the current value', () => {
    const onRename = vi.fn()
    renderItem({ onRename })
    fireEvent.click(screen.getByLabelText('More options'))
    fireEvent.click(screen.getByText('Rename'))
    const input = screen.getByDisplayValue('Old title')
    fireEvent.change(input, { target: { value: 'Blurred' } })
    fireEvent.blur(input)
    expect(onRename).toHaveBeenCalledWith(expect.objectContaining({ id: 's1' }), 'Blurred')
  })

  it('rejects empty / whitespace-only input', () => {
    const onRename = vi.fn()
    renderItem({ onRename })
    fireEvent.click(screen.getByLabelText('More options'))
    fireEvent.click(screen.getByText('Rename'))
    const input = screen.getByDisplayValue('Old title')
    fireEvent.change(input, { target: { value: '   ' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onRename).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 3: Run test, verify it fails**

```bash
pnpm vitest run frontend/src/app/components/sidebar/__tests__/HistoryItem.test.tsx
```
Expected: FAIL — `onRename` prop does not exist; "Rename" text not
found in the menu.

- [ ] **Step 4: Implement Rename support in HistoryItem**

Edit `frontend/src/app/components/sidebar/HistoryItem.tsx`. Add the
new prop, edit state, input rendering, and Rename menu entry.

Replace the `interface HistoryItemProps` block:

```ts
interface HistoryItemProps {
  session: ChatSessionDto
  isPinned: boolean
  isActive: boolean
  monogram?: string
  colourScheme?: ChakraColour
  onClick: (session: ChatSessionDto) => void
  onDelete: (session: ChatSessionDto) => void
  onTogglePin?: (session: ChatSessionDto, pinned: boolean) => void
  onRename?: (session: ChatSessionDto, title: string) => void
}
```

In the function signature, accept the new prop:

```ts
export function HistoryItem({ session, isPinned, isActive, monogram, colourScheme, onClick, onDelete, onTogglePin, onRename }: HistoryItemProps) {
```

Below the existing `useState` lines for `menuOpen` and `confirmDelete`,
add:

```ts
const [editing, setEditing] = useState(false)
const [editValue, setEditValue] = useState('')
const inputRef = useRef<HTMLInputElement>(null)

useEffect(() => {
  if (editing) {
    inputRef.current?.focus()
    inputRef.current?.select()
  }
}, [editing])

const startRename = () => {
  setEditValue(session.title ?? '')
  setEditing(true)
  setMenuOpen(false)
}

const commitRename = () => {
  const trimmed = editValue.trim()
  if (!trimmed) {
    setEditing(false)
    return
  }
  onRename?.(session, trimmed)
  setEditing(false)
}

const cancelRename = () => {
  setEditing(false)
}
```

Replace the title-rendering block. Locate the existing JSX:

```tsx
<div className="flex flex-1 flex-col gap-0.5 overflow-hidden">
  <span className="truncate text-[13px]" title={session.title ?? undefined}>
    {session.title ?? formatSessionDate(session.updated_at)}
  </span>
  {session.title && (
    <span className="truncate text-[11px] opacity-50">
      {formatSessionDate(session.updated_at)}
    </span>
  )}
</div>
```

Replace with:

```tsx
<div className="flex flex-1 flex-col gap-0.5 overflow-hidden">
  {editing ? (
    <input
      ref={inputRef}
      type="text"
      value={editValue}
      onChange={(e) => setEditValue(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault()
          commitRename()
        } else if (e.key === 'Escape') {
          e.preventDefault()
          cancelRename()
        }
      }}
      onBlur={commitRename}
      onClick={(e) => e.stopPropagation()}
      className="w-full rounded border border-white/15 bg-black/30 px-1 py-0 text-[13px] text-white/90 outline-none focus:border-white/30"
    />
  ) : (
    <span className="truncate text-[13px]" title={session.title ?? undefined}>
      {session.title ?? formatSessionDate(session.updated_at)}
    </span>
  )}
  {!editing && session.title && (
    <span className="truncate text-[11px] opacity-50">
      {formatSessionDate(session.updated_at)}
    </span>
  )}
</div>
```

In the menu render block, add a Rename button between Pin/Unpin and
Delete. Locate the `{onTogglePin && ( ... )}` block, and right after it
(before the `Delete` block), insert:

```tsx
{onRename && (
  <button
    type="button"
    onClick={startRename}
    className="w-full px-3 py-1.5 text-left text-[13px] text-white/50 transition-colors hover:bg-white/6"
  >
    Rename
  </button>
)}
```

- [ ] **Step 5: Run tests, verify all pass**

```bash
pnpm vitest run frontend/src/app/components/sidebar/__tests__/HistoryItem.test.tsx
```
Expected: PASS, all six tests green.

- [ ] **Step 6: Wire onRename through the call sites**

For every call site identified in Step 1, add an `onRename` handler
that calls `chatApi.updateSession(session.id, { title })`. The
canonical wiring shape, applied in `Sidebar.tsx` (and any other
container that already wires `onClick` / `onDelete`):

```tsx
import { chatApi } from "../../../core/api/chat"

// inside the component:
const handleRename = async (session: ChatSessionDto, title: string) => {
  try {
    await chatApi.updateSession(session.id, { title })
    // No optimistic state update here: the backend publishes
    // ChatSessionTitleUpdatedEvent and `useChatSessions` already
    // listens for it.
  } catch (err) {
    // Notify the user via the global notification store, matching
    // the error-handling pattern used by handleDelete in this file.
  }
}

// Then on the <HistoryItem> render:
<HistoryItem ... onRename={handleRename} />
```

Confirm during implementation whether `Sidebar.tsx` already imports a
notification helper; if it does, mirror the existing error path. If
it does not, omit the catch-block notification — surface the error
through `console.error` only and let `useChatSessions` re-fetch on the
next event.

- [ ] **Step 7: Verify the live event listener already updates the title**

Run:
```bash
rg -n "CHAT_SESSION_TITLE_UPDATED|chat.session.title.updated|ChatSessionTitleUpdated" frontend/src
```

If `useChatSessions` (or wherever sessions are kept in store) already
subscribes to `CHAT_SESSION_TITLE_UPDATED`, no further work is needed.
If it does not, add a subscription that updates the matching session's
title when the event arrives. (The likely store hook to extend is
`frontend/src/core/hooks/useChatSessions.ts` — the dispatcher should
inspect the file and either add the subscription or confirm it is
already present.)

- [ ] **Step 8: Build**

```bash
cd frontend && pnpm run build
```
Expected: clean.

- [ ] **Step 9: Manual verification**

Open the app, hover or tap the `···` menu on a chat-history item,
click Rename, type a new name, press Enter. The list updates. Reload
the page — the new name persists. Reopen the menu, click Rename, type
nothing, press Enter — the row reverts to the previous title. Click
Rename, type something, press Esc — the row reverts.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/app/components/sidebar/HistoryItem.tsx \
        frontend/src/app/components/sidebar/__tests__/HistoryItem.test.tsx \
        frontend/src/app/components/sidebar/Sidebar.tsx \
        frontend/src/core/hooks/useChatSessions.ts # only if modified
git commit -m "Add Rename option to chat-history items"
```

---

### Task 3: Suppress browser password autofill on API-key fields (Item 4)

**Files:**
- Modify: `frontend/src/app/components/llm-providers/adapter-views/CommunityView.tsx:116-132`
- Modify: `frontend/src/app/components/llm-providers/adapter-views/OllamaHttpView.tsx:163-179`
- Modify: `frontend/src/app/components/llm-providers/adapter-views/XaiHttpView.tsx:87-103`

**Background:** Browsers ignore `autoComplete="new-password"` on
`type="password"` fields and still offer to save the value. We
convert each field to `type="text"` with CSS-level masking and add
the password-manager-bypass attributes.

- [ ] **Step 1: Define the input style helper once**

Create `frontend/src/app/components/llm-providers/adapter-views/_secretInputStyle.ts`:

```ts
import type { CSSProperties } from 'react'

/**
 * Inline style for "secret-like" inputs (API keys, tokens) that we want
 * masked visually but **not** treated as a password by the browser —
 * `type="password"` triggers the password-manager prompt, which is
 * unwanted for API-key entry.
 *
 * `-webkit-text-security: disc` is supported in Chrome, Safari, and
 * Firefox 111+ (March 2023 onwards). For very old Firefox the value
 * would render in plain text — accepted risk.
 */
export const SECRET_INPUT_STYLE: CSSProperties = {
  WebkitTextSecurity: 'disc',
} as CSSProperties

/** Spread on a secret-like input to disable browser + password-manager autofill. */
export const SECRET_INPUT_NO_AUTOFILL = {
  autoComplete: 'off',
  spellCheck: false,
  'data-1p-ignore': true,
  'data-lpignore': 'true',
  'data-bwignore': 'true',
} as const
```

The cast is necessary because `-webkit-text-security` is not in the
standard `CSSProperties` type. Keeping it in one helper avoids three
duplicates.

- [ ] **Step 2: Update CommunityView.tsx**

In `frontend/src/app/components/llm-providers/adapter-views/CommunityView.tsx`,
add the import at the top:

```ts
import { SECRET_INPUT_STYLE, SECRET_INPUT_NO_AUTOFILL } from './_secretInputStyle'
```

Find the `<input>` block near line 116-132 (the API-Key input). Change
`type="password"` to `type="text"`, replace `autoComplete="new-password"`
with `{...SECRET_INPUT_NO_AUTOFILL}`, and add the `style` prop.
Existing `spellCheck={false}` is now covered by the spread — remove
the duplicate.

Result:

```tsx
<input
  id={apiKeyInputId}
  type="text"
  value={apiKey}
  onChange={(e) => {
    setApiKey(e.target.value)
    if (e.target.value.length > 0) setClearApiKey(false)
  }}
  placeholder={
    apiKeyState?.is_set
      ? '••••••••  (leave empty to keep)'
      : 'csapi_…'
  }
  style={SECRET_INPUT_STYLE}
  {...SECRET_INPUT_NO_AUTOFILL}
  className="w-full rounded border border-white/10 bg-black/30 px-2 py-1.5 font-mono text-sm text-white outline-none focus:border-purple/60"
/>
```

- [ ] **Step 3: Update OllamaHttpView.tsx**

Same treatment for the input near line 163-179. Add the import,
change `type` and replace `autoComplete="new-password"` with the
spread + `style` prop. Keep `required={apiKeyRequired}` — that does
not interact with autofill.

Result:

```tsx
<input
  id={keyId}
  type="text"
  value={apiKey}
  onChange={(e) => {
    setApiKey(e.target.value)
    if (e.target.value.length > 0) setClearApiKey(false)
  }}
  placeholder={
    apiKeyState?.is_set
      ? '••••••••  (leave empty to keep)'
      : apiKeyRequired ? 'Required' : 'Optional'
  }
  required={apiKeyRequired}
  style={SECRET_INPUT_STYLE}
  {...SECRET_INPUT_NO_AUTOFILL}
  className="w-full rounded border border-white/10 bg-black/30 px-2 py-1.5 text-sm text-white outline-none focus:border-purple/60"
/>
```

- [ ] **Step 4: Update XaiHttpView.tsx**

Same treatment for the input near line 87-103.

Result:

```tsx
<input
  id={keyId}
  type="text"
  value={apiKey}
  onChange={(e) => {
    setApiKey(e.target.value)
    if (e.target.value.length > 0) setClearApiKey(false)
  }}
  placeholder={
    apiKeyState?.is_set
      ? '••••••••  (leave empty to keep)'
      : apiKeyRequired ? 'Required' : 'Optional'
  }
  required={apiKeyRequired}
  style={SECRET_INPUT_STYLE}
  {...SECRET_INPUT_NO_AUTOFILL}
  className="w-full rounded border border-white/10 bg-black/30 px-2 py-1.5 text-sm text-white outline-none focus:border-purple/60"
/>
```

- [ ] **Step 5: Confirm no other API-key fields slipped through**

Run:
```bash
rg -n 'type="password"' frontend/src/app/components/llm-providers/
```
Expected: only the password-input in any auth-related screens, **not**
in `adapter-views/`. If any password input remains under
`adapter-views/`, repeat the conversion. If any other secret-like
field outside `adapter-views/` shows the same pattern, leave it alone
unless it is clearly an API-key (login passwords are out of scope).

- [ ] **Step 6: Build**

```bash
cd frontend && pnpm run build
```
Expected: clean. The `as CSSProperties` cast prevents the strict-mode
"unknown style key" complaint; if it still complains the cast is in
the wrong place — re-check `_secretInputStyle.ts`.

- [ ] **Step 7: Manual verification**

Open the LLM Providers tab → click into any of the three adapters
(Community, Ollama HTTP, xAI HTTP). Focus the API-key field. The
browser does **not** offer to autofill or save a password. Typing
shows dots, not letters. Submit succeeds.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/app/components/llm-providers/adapter-views/
git commit -m "Suppress browser password autofill on API-key inputs"
```

---

### Task 4: Replace AddPersonaCard menu with vertical split (Item 3)

**Files:**
- Modify: `frontend/src/app/components/persona-card/AddPersonaCard.tsx`
- Delete: `frontend/src/app/components/persona-card/AddPersonaMenu.tsx`
- Modify: `frontend/src/app/pages/PersonasPage.tsx:113-122` (remove
  menu state and rendering)
- Test: `frontend/src/app/components/persona-card/__tests__/AddPersonaCard.test.tsx`
  (create — folder may need creating too)

- [ ] **Step 1: Confirm there are no other consumers of AddPersonaMenu**

Run:
```bash
rg -n "AddPersonaMenu" frontend/src
```
Expected: only `AddPersonaMenu.tsx` itself and `PersonasPage.tsx`. If
there are other consumers, surface them and stop — they all need
updating.

- [ ] **Step 2: Write the failing test**

Create
`frontend/src/app/components/persona-card/__tests__/AddPersonaCard.test.tsx`:

```tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import AddPersonaCard from '../AddPersonaCard'

describe('AddPersonaCard split', () => {
  it('renders both halves with distinct labels', () => {
    render(<AddPersonaCard onCreateNew={vi.fn()} onImport={vi.fn()} index={0} />)
    expect(screen.getByRole('button', { name: /create new persona/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /import persona from file/i })).toBeInTheDocument()
  })

  it('top half triggers onCreateNew', () => {
    const onCreateNew = vi.fn()
    render(<AddPersonaCard onCreateNew={onCreateNew} onImport={vi.fn()} index={0} />)
    fireEvent.click(screen.getByRole('button', { name: /create new persona/i }))
    expect(onCreateNew).toHaveBeenCalledTimes(1)
  })

  it('bottom half triggers onImport', () => {
    const onImport = vi.fn()
    render(<AddPersonaCard onCreateNew={vi.fn()} onImport={onImport} index={0} />)
    fireEvent.click(screen.getByRole('button', { name: /import persona from file/i }))
    expect(onImport).toHaveBeenCalledTimes(1)
  })
})
```

- [ ] **Step 3: Run test, verify it fails**

```bash
pnpm vitest run frontend/src/app/components/persona-card/__tests__/AddPersonaCard.test.tsx
```
Expected: FAIL — the props `onCreateNew` and `onImport` do not exist
yet; component still has `onClick`.

- [ ] **Step 4: Rewrite AddPersonaCard.tsx**

Replace the contents of
`frontend/src/app/components/persona-card/AddPersonaCard.tsx` with:

```tsx
interface AddPersonaCardProps {
  onCreateNew: () => void
  onImport: () => void
  index: number
}

const HALF_BASE = "relative flex flex-1 flex-col items-center justify-center gap-2 cursor-pointer transition-colors group"
const ICON_BG = "rgba(201,168,76,0.04)"
const BORDER_COLOUR = "rgba(201,168,76,0.3)"
const LABEL_COLOUR = "rgba(201,168,76,0.45)"
const HOVER_BG = "rgba(201,168,76,0.04)"

export default function AddPersonaCard({ onCreateNew, onImport, index }: AddPersonaCardProps) {
  const cardStyle: React.CSSProperties = {
    width: "clamp(160px, 42vw, 210px)",
    height: "clamp(240px, 63vw, 320px)",
    border: "1px dashed rgba(201,168,76,0.15)",
    animation: `card-entrance 0.6s cubic-bezier(0.16, 1, 0.3, 1) ${index * 0.1}s both`,
  }

  return (
    <div
      style={cardStyle}
      className="relative flex flex-col rounded-xl bg-transparent overflow-hidden hover:border-[rgba(201,168,76,0.35)]"
    >
      {/* Top half: Create new */}
      <button
        type="button"
        aria-label="Create new persona"
        onClick={onCreateNew}
        className={HALF_BASE}
        style={{ background: 'transparent' }}
        onMouseEnter={(e) => (e.currentTarget.style.background = HOVER_BG)}
        onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
      >
        <div
          className="w-9 h-9 rounded-full flex items-center justify-center"
          style={{ border: `1px dashed ${BORDER_COLOUR}`, color: LABEL_COLOUR, background: ICON_BG }}
        >
          <svg width="16" height="16" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <line x1="9" y1="3" x2="9" y2="15" />
            <line x1="3" y1="9" x2="15" y2="9" />
          </svg>
        </div>
        <span
          className="font-mono text-[10px] uppercase tracking-widest"
          style={{ color: LABEL_COLOUR }}
        >
          add persona
        </span>
      </button>

      {/* Divider */}
      <div className="h-px" style={{ background: "rgba(201,168,76,0.15)" }} aria-hidden="true" />

      {/* Bottom half: Import */}
      <button
        type="button"
        aria-label="Import persona from file"
        onClick={onImport}
        className={HALF_BASE}
        style={{ background: 'transparent' }}
        onMouseEnter={(e) => (e.currentTarget.style.background = HOVER_BG)}
        onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
      >
        <div
          className="w-9 h-9 rounded-full flex items-center justify-center"
          style={{ border: `1px dashed ${BORDER_COLOUR}`, color: LABEL_COLOUR, background: ICON_BG }}
        >
          {/* Down-arrow into a tray icon */}
          <svg width="16" height="16" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 3v8" />
            <path d="M5 7l4 4 4-4" />
            <path d="M3 14h12" />
          </svg>
        </div>
        <span
          className="font-mono text-[10px] uppercase tracking-widest"
          style={{ color: LABEL_COLOUR }}
        >
          import from file
        </span>
      </button>
    </div>
  )
}
```

- [ ] **Step 5: Run test, verify it passes**

```bash
pnpm vitest run frontend/src/app/components/persona-card/__tests__/AddPersonaCard.test.tsx
```
Expected: PASS, all three tests green.

- [ ] **Step 6: Update PersonasPage.tsx — remove menu state**

In `frontend/src/app/pages/PersonasPage.tsx`:

- Remove the `import { AddPersonaMenu } from "../components/persona-card/AddPersonaMenu"` line.
- Remove `const [menuOpen, setMenuOpen] = useState(false)` (around line 48).
- In `handleCreateNew`, remove the `setMenuOpen(false)` line.
- In `handleImportClick`, remove the `setMenuOpen(false)` line.
- Replace the `<div className="relative">` block (around lines 113-122) with:

```tsx
<AddPersonaCard
  onCreateNew={handleCreateNew}
  onImport={handleImportClick}
  index={filtered.length}
/>
```

(No surrounding `<div className="relative">` is needed any more.)

- [ ] **Step 7: Delete AddPersonaMenu.tsx**

```bash
rm frontend/src/app/components/persona-card/AddPersonaMenu.tsx
```

If the file has its own test (`AddPersonaMenu.test.tsx`), delete that
too:
```bash
rg -l "AddPersonaMenu" frontend/src
rm <any matching test path>
```

- [ ] **Step 8: Build**

```bash
cd frontend && pnpm run build
```
Expected: clean. If the build complains about a missing
`AddPersonaMenu` import anywhere, that means a consumer was missed in
Step 1 — search again and patch.

- [ ] **Step 9: Manual verification**

Navigate to `/personas`. The Add card now shows two stacked halves
with a thin gold divider between them. Top click opens the new-persona
edit overlay. Bottom click opens the file picker. No popover menu
appears.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/app/components/persona-card/ \
        frontend/src/app/pages/PersonasPage.tsx
git rm frontend/src/app/components/persona-card/AddPersonaMenu.tsx
git commit -m "Replace AddPersonaCard menu with vertical create/import split"
```

---

### Task 5: Add Import button to user-modal Personas tab (Item 2)

**Files:**
- Modify: `frontend/src/app/components/user-modal/PersonasTab.tsx`
- Modify: `frontend/src/app/components/user-modal/UserModal.tsx`
  (forward `onImportPersona` prop)
- Modify: `frontend/src/app/layouts/AppLayout.tsx` (provide the
  handler — likely extract from `PersonasPage.tsx`)
- Test: `frontend/src/app/components/user-modal/__tests__/PersonasTab.test.tsx`
  (extend existing file)

- [ ] **Step 1: Extend the failing test**

Open `frontend/src/app/components/user-modal/__tests__/PersonasTab.test.tsx`
and append:

```tsx
  it('renders an Import button alongside Create persona', () => {
    render(
      <PersonasTab
        onOpenPersonaOverlay={vi.fn()}
        onCreatePersona={vi.fn()}
        onImportPersona={vi.fn()}
      />,
    )
    expect(screen.getByRole('button', { name: /import/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /create persona/i })).toBeInTheDocument()
  })

  it('Import button calls onImportPersona', () => {
    const onImportPersona = vi.fn()
    render(
      <PersonasTab
        onOpenPersonaOverlay={vi.fn()}
        onCreatePersona={vi.fn()}
        onImportPersona={onImportPersona}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /import/i }))
    expect(onImportPersona).toHaveBeenCalledTimes(1)
  })
```

- [ ] **Step 2: Run, verify it fails**

```bash
pnpm vitest run frontend/src/app/components/user-modal/__tests__/PersonasTab.test.tsx
```
Expected: FAIL — `onImportPersona` not in props; no Import button.

- [ ] **Step 3: Add the Import button to PersonasTab**

In `frontend/src/app/components/user-modal/PersonasTab.tsx`:

```ts
interface PersonasTabProps {
  onOpenPersonaOverlay: (personaId: string) => void
  onCreatePersona: () => void
  onImportPersona: () => void
}

export function PersonasTab({ onOpenPersonaOverlay, onCreatePersona, onImportPersona }: PersonasTabProps) {
```

Replace the top-bar JSX (current lines 27-37):

```tsx
<div className="flex flex-shrink-0 items-center justify-end gap-2 px-4 pt-4 pb-2">
  <button
    type="button"
    onClick={onImportPersona}
    className="rounded-md border border-white/10 px-2.5 py-1 text-[12px] font-medium text-white/70 transition-colors hover:bg-white/6 hover:text-white/90"
    aria-label="Import persona from file"
    title="Import persona from file"
  >
    ⤓ Import
  </button>
  <button
    type="button"
    onClick={onCreatePersona}
    className="rounded-md border border-white/10 px-2.5 py-1 text-[12px] font-medium text-white/70 transition-colors hover:bg-white/6 hover:text-white/90"
    aria-label="Create persona"
    title="Create persona"
  >
    + Create persona
  </button>
</div>
```

- [ ] **Step 4: Run test, verify it passes**

```bash
pnpm vitest run frontend/src/app/components/user-modal/__tests__/PersonasTab.test.tsx
```
Expected: PASS for the new tests; existing tests still pass — they
pass `vi.fn()` for the new prop.

The existing test cases pass `onCreatePersona={vi.fn()}` only — they
will need `onImportPersona={vi.fn()}` too, otherwise TypeScript will
complain. Update each render call in the file accordingly.

- [ ] **Step 5: Forward the prop through UserModal**

In `frontend/src/app/components/user-modal/UserModal.tsx`:

Add `onImportPersona: () => void` to `UserModalProps`.

Add `onImportPersona` to the destructured args of the function.

Pass it to `PersonasTab`:

```tsx
{contentKey === 'personas' && (
  <PersonasTab
    onOpenPersonaOverlay={onOpenPersonaOverlay}
    onCreatePersona={onCreatePersona}
    onImportPersona={onImportPersona}
  />
)}
```

- [ ] **Step 6: Wire the handler in AppLayout**

In `frontend/src/app/layouts/AppLayout.tsx`:

We need a handler that opens the same file picker `PersonasPage` uses
and runs `personasApi.importPersona`. Easiest path: add a hidden
`<input type="file">` to AppLayout (since the user-modal closes after
clicking the button, the file picker must be triggered before close)
and define the handler.

Add near the existing `useState` calls:

```ts
const personaImportFileRef = useRef<HTMLInputElement>(null)
const [personaImporting, setPersonaImporting] = useState(false)
```

(Import `useRef` from React if not already imported, and import
`personasApi` from `../../core/api/personas`, `ApiError` from
`../../core/api/client`, `useNotificationStore` from
`../../core/store/notificationStore` if not already imported.)

Add the handler:

```ts
const handleImportPersona = useCallback(() => {
  personaImportFileRef.current?.click()
}, [])

const handlePersonaFileSelected = useCallback(
  async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null
    event.target.value = ""
    if (!file) return

    setPersonaImporting(true)
    try {
      const created = await personasApi.importPersona(file)
      addNotification({
        level: "success",
        title: "Persona imported",
        message: `${created.name} has been imported.`,
      })
      openPersonaOverlay(created.id, "overview")
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Failed to import persona."
      addNotification({
        level: "error",
        title: "Import failed",
        message,
      })
    } finally {
      setPersonaImporting(false)
    }
  },
  [addNotification, openPersonaOverlay],
)
```

(`addNotification` resolution: `const addNotification = useNotificationStore((s) => s.addNotification)` if not already declared.)

Pass `onImportPersona={handleImportPersona}` to the `<UserModal>`
render.

Add to the JSX (somewhere outside the modal, e.g. next to the
existing modals):

```tsx
<input
  ref={personaImportFileRef}
  type="file"
  accept=".tar.gz,.gz,application/gzip"
  className="hidden"
  onChange={handlePersonaFileSelected}
/>

{personaImporting && (
  <div
    className="fixed inset-0 z-[55] flex items-center justify-center bg-black/60"
    role="status"
    aria-live="polite"
    aria-label="Importing persona"
  >
    <div className="flex items-center gap-3 rounded-lg border border-white/8 bg-elevated px-5 py-4 shadow-2xl">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-gold/30 border-t-gold" />
      <span className="text-[13px] text-white/80">Importing persona…</span>
    </div>
  </div>
)}
```

This duplicates the spinner block from `PersonasPage.tsx`. Acceptable
duplication — one helper is not worth introducing for two callers; if a
third comes up, factor then.

- [ ] **Step 7: Update other UserModal call sites**

Run:
```bash
rg -n "<UserModal" frontend/src
```
Every site that renders `<UserModal>` now needs the `onImportPersona`
prop. The tests at
`frontend/src/app/components/user-modal/UserModal.test.tsx:68` will
fail to type-check otherwise — pass a `vi.fn()` there.

- [ ] **Step 8: Build**

```bash
cd frontend && pnpm run build
```
Expected: clean.

- [ ] **Step 9: Manual verification**

Open user-modal → Personas tab → click `⤓ Import`. The file picker
opens. Cancel the dialog: nothing happens, modal still open. Pick a
valid persona archive: notification shows "Persona imported", the
modal closes, you land on the new persona's overview.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/app/components/user-modal/ \
        frontend/src/app/layouts/AppLayout.tsx
git commit -m "Add Import-from-file button to user-modal Personas tab"
```

---

### Task 6: Bump mobile form-control font-size to prevent iOS zoom (Item 7)

**Files:**
- Modify: `frontend/src/index.css` (add a media-query block)

**Background:** iOS Safari zooms when an input/textarea has computed
font-size below 16px. The chat input uses `chat-text` whose
`--chat-font-size` is 14px. Force ≥ 16px on form controls below the
`lg` breakpoint (Tailwind's `lg` is 1024px → break at `1023.98px`).

- [ ] **Step 1: Add the media query**

In `frontend/src/index.css`, after the existing `.chat-text` block
(around line 99), add:

```css
/* iOS Safari zooms in on inputs whose computed font-size is below
   16px. Force ≥ 16px on form controls below the lg breakpoint. The
   chat-text rule still applies inside chat *messages* (rendered as
   <p>/<div>, not form controls), so the message body stays at the
   user-configured size. */
@media (max-width: 1023.98px) {
  input,
  textarea,
  select {
    font-size: 16px;
  }
}
```

- [ ] **Step 2: Build**

```bash
cd frontend && pnpm run build
```
Expected: clean.

- [ ] **Step 3: Manual sanity check (desktop)**

In DevTools, switch to a mobile viewport (e.g. iPhone 13) and look at
the chat input — text in the input is noticeably larger than the chat
bubble text (because messages stay at `--chat-font-size: 14px`). On
desktop (`lg+`), nothing changes.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/index.css
git commit -m "Force 16px form-control font-size on mobile to stop iOS zoom"
```

---

### Task 7: Apply safe-area-inset-top to mobile headers (Item 6)

**Files:** Audit-driven.

- Modify: `frontend/src/app/components/sidebar/MobileSidebarHeader.tsx`
- Modify: `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx`
  (header section near `196-225`)
- Modify: `frontend/src/app/components/user-modal/UserModal.tsx`
  (top header — confirm during implementation)
- Audit: any other full-screen mobile-only header.

- [ ] **Step 1: Audit all mobile-only / full-screen headers**

Run:
```bash
rg -n "lg:hidden" frontend/src/app/components/ | grep -i -E "header|top|fixed|inset-0"
rg -n "fixed inset-0|absolute inset-0" frontend/src/app/components/
```

For each result, open the file and check whether the topmost element
is a header/title-bar that lives at the top of the viewport on mobile.
Build a list. Expected entries (verify):

- `sidebar/MobileSidebarHeader.tsx` — confirmed.
- `persona-overlay/PersonaOverlay.tsx` — header at lines 196-225.
- `user-modal/UserModal.tsx` — needs confirmation.
- `admin-modal/*` — possible; audit.

- [ ] **Step 2: Apply padding to MobileSidebarHeader**

In `frontend/src/app/components/sidebar/MobileSidebarHeader.tsx`,
update the outer `<div>` (line 14):

```tsx
<div
  className="flex h-[50px] flex-shrink-0 items-center gap-1 border-b border-white/5 px-3.5"
  style={{ paddingTop: 'env(safe-area-inset-top)' }}
>
```

The fixed `h-[50px]` is still the *content* height; the padding
extends the bar upward into the safe-area zone. If this breaks
alignment with adjacent positioned elements (audit during the
manual-verification step), fall back to wrapping the div in a parent
div that holds the safe-area padding.

- [ ] **Step 3: Apply padding to PersonaOverlay header**

In `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx`,
the header `<div>` at line 197:

```tsx
<div
  className="flex items-center justify-between px-5 py-3 flex-shrink-0"
  style={{
    borderBottom: `1px solid ${borderColour}`,
    paddingTop: 'max(0.75rem, env(safe-area-inset-top))',
  }}
>
```

The `max()` keeps the original `py-3` (12px / 0.75rem) padding on
desktop where the safe-area inset is zero.

- [ ] **Step 4: Apply padding to UserModal header (if confirmed)**

Read `frontend/src/app/components/user-modal/UserModal.tsx` and locate
the topmost header. Apply the same `paddingTop: 'max(<existing>,
env(safe-area-inset-top))'` treatment. If the modal's outer container
already starts at `top: 0` and the inner header has its own padding,
attach the safe-area padding to the **outer** container to push the
whole modal down.

- [ ] **Step 5: Audit any other surfaced top elements**

Apply the same fix to any audit hit from Step 1 that visually sits at
top:0 on mobile. Skip elements that are anchored via
`bottom-[env(safe-area-inset-bottom)]` already — those are the bottom
of the viewport.

- [ ] **Step 6: Build**

```bash
cd frontend && pnpm run build
```
Expected: clean.

- [ ] **Step 7: Manual desktop sanity check**

On desktop the safe-area inset is 0, so visually nothing changes.
Confirm headers render exactly as before on a normal desktop window.

- [ ] **Step 8: Manual mobile / DevTools check**

In DevTools, force a non-zero safe-area-inset-top by opening the
console and running:

```js
document.documentElement.style.setProperty('--debug-sa-top', '40px')
document.documentElement.style.setProperty('env(safe-area-inset-top)', '40px')
```

Note: the `env()` value cannot actually be overridden from JS — but
you can verify the rule works by temporarily hard-coding the headers'
`paddingTop: '40px'` and visually inspecting that the header content
stays below 40px of empty space. Revert the hard-code before
committing.

A more reliable check is to test on a real iPhone-PWA after deploy —
that's Ksena's job.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/app/components/sidebar/MobileSidebarHeader.tsx \
        frontend/src/app/components/persona-overlay/PersonaOverlay.tsx \
        frontend/src/app/components/user-modal/UserModal.tsx
git commit -m "Pad mobile-overlay headers with safe-area-inset-top"
```

---

## Cross-cutting verification

After all seven tasks land, run:

- [ ] **Full test suite for touched areas**

```bash
cd frontend && pnpm vitest run \
  src/app/components/sidebar \
  src/app/components/persona-card \
  src/app/components/user-modal \
  src/app/components/persona-overlay
```
Expected: all green.

- [ ] **Full build**

```bash
cd frontend && pnpm run build
```
Expected: clean.

- [ ] **Manual smoke test (run through every spec acceptance row)**

Walk through the manual-verification checklist in
`devdocs/specs/2026-05-04-prototype-feedback-bug-bash-design.md`. Tick
every box. Ksena to verify Items 6 & 7 on iPhone after deploy.

---

## Merge handoff (dispatcher only — not for subagents)

After the cross-cutting verification passes:

```bash
# Confirm we are on the working branch (master, given current state)
git status
git log --oneline -10
```

Per project default (`CLAUDE.md`: "Please always merge to master after
implementation"), the dispatcher merges to master. If the work was
done on master directly, no merge is needed — just push. If a feature
branch was used, fast-forward into master, then push.

The subagents executing the tasks above must **never** merge, push,
or switch branches.

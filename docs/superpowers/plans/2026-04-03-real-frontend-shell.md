# Real Frontend Shell — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the prototype frontend shell (`src/prototype/`) with the production app shell: dark-themed sidebar, context-sensitive topbar, new routing, and login page — as specified in `docs/superpowers/specs/2026-04-03-real-frontend-shell-design.md`.

**Architecture:** The `core/` layer (api, hooks, store, types, websocket) is unchanged. New components live under `src/app/`. `AppLayout` lifts `usePersonas` and `useChatSessions` state and passes it to `Sidebar` and `Topbar` as props — one fetch per data type, no duplication. Active route context is detected via React Router's `useMatch` in `AppLayout`.

**Tech Stack:** React 19, TypeScript, Vite 8, Tailwind CSS v4 (configured via `@theme` in CSS — no `tailwind.config.js`), React Router v7, Zustand, Vitest + React Testing Library

---

## File Map

| Action | Path | Purpose |
|---|---|---|
| Modify | `frontend/src/index.css` | Add `@theme` design tokens |
| Modify | `frontend/src/App.tsx` | New routing tree, last-route persistence |
| Modify | `frontend/src/core/api/chat.ts` | Add `listSessions` |
| Create | `frontend/src/core/hooks/useChatSessions.ts` | Reactive sessions list |
| Create | `frontend/src/test/setup.ts` | Vitest global setup |
| Create | `frontend/src/app/layouts/AppLayout.tsx` | Shell: sidebar + topbar + outlet |
| Create | `frontend/src/app/pages/LoginPage.tsx` | Styled login |
| Create | `frontend/src/app/pages/PersonasPage.tsx` | Stub |
| Create | `frontend/src/app/pages/ChatPage.tsx` | Stub |
| Create | `frontend/src/app/pages/ProjectsPage.tsx` | Stub |
| Create | `frontend/src/app/pages/HistoryPage.tsx` | Stub |
| Create | `frontend/src/app/pages/KnowledgePage.tsx` | Stub |
| Create | `frontend/src/app/pages/AdminPage.tsx` | Stub |
| Create | `frontend/src/app/components/sidebar/NavRow.tsx` | Reusable nav row |
| Create | `frontend/src/app/components/sidebar/NavRow.test.tsx` | NavRow tests |
| Create | `frontend/src/app/components/sidebar/personaColour.ts` | Persona avatar utility |
| Create | `frontend/src/app/components/sidebar/personaColour.test.ts` | Colour utility tests |
| Create | `frontend/src/app/components/sidebar/PersonaItem.tsx` | Persona row + context menu |
| Create | `frontend/src/app/components/sidebar/PersonaItem.test.tsx` | PersonaItem tests |
| Create | `frontend/src/app/components/sidebar/HistoryItem.tsx` | History chat row |
| Create | `frontend/src/app/components/sidebar/Sidebar.tsx` | Full sidebar |
| Create | `frontend/src/app/components/topbar/Topbar.tsx` | Context-sensitive topbar |
| Delete | `frontend/src/prototype/` | Remove prototype |

---

## Task 1: Vitest + React Testing Library setup

**Files:**
- Modify: `frontend/vite.config.ts`
- Create: `frontend/src/test/setup.ts`

- [ ] **Step 1: Install test dependencies**

```bash
cd frontend
pnpm add -D vitest jsdom @testing-library/react @testing-library/user-event
```

Expected: packages installed, `frontend/package.json` updated.

- [ ] **Step 2: Update `frontend/vite.config.ts`**

```ts
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000"
const backendWs = backendUrl.replace(/^http/, "ws")

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      "/api": backendUrl,
      "/ws": {
        target: backendWs,
        ws: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/test/setup.ts"],
  },
})
```

- [ ] **Step 3: Create `frontend/src/test/setup.ts`**

```ts
import { afterEach } from "vitest"
import { cleanup } from "@testing-library/react"

afterEach(() => {
  cleanup()
})
```

- [ ] **Step 4: Verify setup works**

```bash
cd frontend
pnpm exec vitest run --reporter=verbose 2>&1 | head -20
```

Expected output contains `No test files found` or similar — no errors. If it crashes, check that `vite.config.ts` is valid TypeScript.

- [ ] **Step 5: Commit**

```bash
cd frontend
git add vite.config.ts package.json pnpm-lock.yaml src/test/setup.ts
git commit -m "Add Vitest + React Testing Library for frontend tests"
```

---

## Task 2: Design tokens (Tailwind v4 `@theme`)

**Files:**
- Modify: `frontend/src/index.css`

Tailwind v4 uses `@theme` inside CSS — no `tailwind.config.js` needed. Tokens defined in `@theme` become both CSS custom properties AND Tailwind utility classes. `--color-base` → `bg-base`, `text-base`, `border-base`, etc.

- [ ] **Step 1: Replace `frontend/src/index.css`**

```css
@import "tailwindcss";

@theme {
  /* Backgrounds */
  --color-base: #0a0810;
  --color-surface: #0f0d16;
  --color-elevated: #1a1528;

  /* Brand accents */
  --color-gold: #c9a84c;
  --color-live: #22c55e;
  --color-purple: #7c5cbf;
}
```

- [ ] **Step 2: Verify Tailwind generates classes**

Start the dev server and inspect that `bg-base`, `text-gold`, etc. are available (no red underlines in editor if using Tailwind IntelliSense). No runtime check needed — Tailwind v4 generates classes on demand.

```bash
cd frontend
pnpm dev &
# Open browser at http://localhost:5173, confirm no CSS errors in console
pkill -f "vite"
```

- [ ] **Step 3: Commit**

```bash
cd /home/chris/workspace/chatsune
git add frontend/src/index.css
git commit -m "Add Tailwind v4 design tokens for production shell"
```

---

## Task 3: Add `chatApi.listSessions` and `useChatSessions`

**Files:**
- Modify: `frontend/src/core/api/chat.ts`
- Create: `frontend/src/core/hooks/useChatSessions.ts`

The backend `GET /api/chat/sessions` endpoint already exists (see `backend/modules/chat/_handlers.py:43`). The frontend `chatApi` is missing the call.

- [ ] **Step 1: Add `listSessions` to `frontend/src/core/api/chat.ts`**

The current file exports `chatApi` with `createSession`, `getSession`, `getMessages`. Add `listSessions` to the object:

```ts
import { api } from "./client"

interface ChatSessionDto {
  id: string
  user_id: string
  persona_id: string
  model_unique_id: string
  state: "idle" | "streaming" | "requires_action"
  created_at: string
  updated_at: string
}

interface ChatMessageDto {
  id: string
  session_id: string
  role: "user" | "assistant" | "tool"
  content: string
  thinking: string | null
  token_count: number
  created_at: string
}

export type { ChatSessionDto, ChatMessageDto }

export const chatApi = {
  createSession: (personaId: string) =>
    api.post<ChatSessionDto>("/api/chat/sessions", { persona_id: personaId }),

  listSessions: () =>
    api.get<ChatSessionDto[]>("/api/chat/sessions"),

  getSession: (sessionId: string) =>
    api.get<ChatSessionDto>(`/api/chat/sessions/${sessionId}`),

  getMessages: (sessionId: string) =>
    api.get<ChatMessageDto[]>(`/api/chat/sessions/${sessionId}/messages`),
}
```

- [ ] **Step 2: Create `frontend/src/core/hooks/useChatSessions.ts`**

```ts
import { useCallback, useEffect, useState } from "react"
import { chatApi, type ChatSessionDto } from "../api/chat"

export function useChatSessions() {
  const [sessions, setSessions] = useState<ChatSessionDto[]>([])
  const [isLoading, setIsLoading] = useState(false)

  const fetch = useCallback(async () => {
    setIsLoading(true)
    try {
      const res = await chatApi.listSessions()
      // Newest first
      setSessions(res.sort((a, b) => b.updated_at.localeCompare(a.updated_at)))
    } catch {
      // Empty history is acceptable — API may not have sessions yet
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetch()
  }, [fetch])

  return { sessions, isLoading, refetch: fetch }
}
```

- [ ] **Step 3: Commit**

```bash
cd /home/chris/workspace/chatsune
git add frontend/src/core/api/chat.ts frontend/src/core/hooks/useChatSessions.ts
git commit -m "Add chatApi.listSessions and useChatSessions hook"
```

---

## Task 4: Persona colour utility

**Files:**
- Create: `frontend/src/app/components/sidebar/personaColour.ts`
- Create: `frontend/src/app/components/sidebar/personaColour.test.ts`

`PersonaDto.colour_scheme` is a free-form string. If it looks like a hex colour, use it. Otherwise deterministically pick from a palette based on the persona ID.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/app/components/sidebar/personaColour.test.ts`:

```ts
import { describe, it, expect } from "vitest"
import { personaGradient, personaInitial } from "./personaColour"
import type { PersonaDto } from "../../../core/types/persona"

const base: PersonaDto = {
  id: "abc123",
  user_id: "u1",
  name: "Lyra",
  tagline: "",
  model_unique_id: "test:model",
  system_prompt: "",
  temperature: 0.8,
  reasoning_enabled: false,
  colour_scheme: "",
  display_order: 0,
  created_at: "2026-01-01",
  updated_at: "2026-01-01",
}

describe("personaInitial", () => {
  it("returns uppercased first character of name", () => {
    expect(personaInitial({ ...base, name: "lyra" })).toBe("L")
    expect(personaInitial({ ...base, name: "Atlas" })).toBe("A")
  })
})

describe("personaGradient", () => {
  it("uses colour_scheme if it is a hex colour", () => {
    const g = personaGradient({ ...base, colour_scheme: "#7c5cbf" })
    expect(g).toContain("#7c5cbf")
  })

  it("returns a gradient string for personas without colour_scheme", () => {
    const g = personaGradient({ ...base, colour_scheme: "" })
    expect(g).toMatch(/linear-gradient/)
  })

  it("returns a consistent gradient for the same persona id", () => {
    const g1 = personaGradient({ ...base, colour_scheme: "" })
    const g2 = personaGradient({ ...base, colour_scheme: "" })
    expect(g1).toBe(g2)
  })
})
```

- [ ] **Step 2: Run test to confirm FAIL**

```bash
cd frontend
pnpm exec vitest run src/app/components/sidebar/personaColour.test.ts
```

Expected: FAIL — `Cannot find module './personaColour'`

- [ ] **Step 3: Create `frontend/src/app/components/sidebar/personaColour.ts`**

```ts
import type { PersonaDto } from "../../../core/types/persona"

const PALETTE: [string, string][] = [
  ["#7c5cbf", "#c9a84c"],
  ["#1e6fbf", "#34d399"],
  ["#bf4f1e", "#f59e0b"],
  ["#2e7d32", "#66bb6a"],
  ["#7b1fa2", "#e91e63"],
  ["#0277bd", "#80deea"],
]

function hashId(id: string): number {
  let h = 0
  for (let i = 0; i < id.length; i++) {
    h = (Math.imul(31, h) + id.charCodeAt(i)) | 0
  }
  return Math.abs(h)
}

export function personaGradient(persona: PersonaDto): string {
  if (/^#[0-9a-fA-F]{3,8}$/.test(persona.colour_scheme ?? "")) {
    return `linear-gradient(135deg, ${persona.colour_scheme}, ${persona.colour_scheme}88)`
  }
  const [from, to] = PALETTE[hashId(persona.id) % PALETTE.length]
  return `linear-gradient(135deg, ${from}, ${to})`
}

export function personaInitial(persona: PersonaDto): string {
  return persona.name.charAt(0).toUpperCase()
}
```

- [ ] **Step 4: Run test to confirm PASS**

```bash
cd frontend
pnpm exec vitest run src/app/components/sidebar/personaColour.test.ts
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/chris/workspace/chatsune
git add frontend/src/app/components/sidebar/personaColour.ts \
        frontend/src/app/components/sidebar/personaColour.test.ts
git commit -m "Add persona avatar colour utility with deterministic fallback palette"
```

---

## Task 5: NavRow component

**Files:**
- Create: `frontend/src/app/components/sidebar/NavRow.tsx`
- Create: `frontend/src/app/components/sidebar/NavRow.test.tsx`

`NavRow` is the primary nav item: icon + label (full row is a button with hover underline) + optional right-side action buttons. The label underlines on hover so the nav destination is unmistakable. Action buttons (search, collapse) stop click propagation so they don't trigger the nav.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/app/components/sidebar/NavRow.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { NavRow } from "./NavRow"

describe("NavRow", () => {
  it("renders the label", () => {
    render(<NavRow icon="◈" label="Chat" onClick={() => {}} />)
    expect(screen.getByText("Chat")).toBeDefined()
  })

  it("calls onClick when the row is clicked", async () => {
    const onClick = vi.fn()
    render(<NavRow icon="◈" label="Chat" onClick={onClick} />)
    await userEvent.click(screen.getByRole("button"))
    expect(onClick).toHaveBeenCalledOnce()
  })

  it("renders action elements when provided", () => {
    render(
      <NavRow
        icon="◈"
        label="History"
        onClick={() => {}}
        actions={<button data-testid="search-btn">🔍</button>}
      />,
    )
    expect(screen.getByTestId("search-btn")).toBeDefined()
  })

  it("does not trigger onClick when an action button is clicked", async () => {
    const onClick = vi.fn()
    const onSearch = vi.fn()
    render(
      <NavRow
        icon="◈"
        label="History"
        onClick={onClick}
        actions={<button onClick={onSearch}>🔍</button>}
      />,
    )
    await userEvent.click(screen.getByText("🔍"))
    expect(onSearch).toHaveBeenCalledOnce()
    expect(onClick).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run test to confirm FAIL**

```bash
cd frontend
pnpm exec vitest run src/app/components/sidebar/NavRow.test.tsx
```

Expected: FAIL — `Cannot find module './NavRow'`

- [ ] **Step 3: Create `frontend/src/app/components/sidebar/NavRow.tsx`**

```tsx
import type { ReactNode } from "react"

interface NavRowProps {
  icon: ReactNode
  label: string
  onClick: () => void
  actions?: ReactNode
}

export function NavRow({ icon, label, onClick, actions }: NavRowProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 mx-1.5 my-0.5 cursor-pointer transition-colors hover:bg-white/6"
      style={{ width: "calc(100% - 12px)" }}
    >
      <span className="w-4 flex-shrink-0 text-center text-sm text-white/50">{icon}</span>
      <span className="flex-1 text-left text-[13px] font-semibold text-white/60 underline-offset-2 transition-colors group-hover:text-white/90 group-hover:underline">
        {label}
      </span>
      {actions && (
        <div
          className="flex gap-0.5"
          onClick={(e) => e.stopPropagation()}
        >
          {actions}
        </div>
      )}
    </button>
  )
}
```

- [ ] **Step 4: Run test to confirm PASS**

```bash
cd frontend
pnpm exec vitest run src/app/components/sidebar/NavRow.test.tsx
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/chris/workspace/chatsune
git add frontend/src/app/components/sidebar/NavRow.tsx \
        frontend/src/app/components/sidebar/NavRow.test.tsx
git commit -m "Add NavRow sidebar component with hover-underline and action slot"
```

---

## Task 6: PersonaItem component

**Files:**
- Create: `frontend/src/app/components/sidebar/PersonaItem.tsx`
- Create: `frontend/src/app/components/sidebar/PersonaItem.test.tsx`

Persona row: drag handle (visual only in Phase 1) + avatar + name + `···` context menu (appears on hover). Menu items: New Chat, New Incognito Chat, Edit, Unpin.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/app/components/sidebar/PersonaItem.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { PersonaItem } from "./PersonaItem"
import type { PersonaDto } from "../../../core/types/persona"

const mockPersona: PersonaDto = {
  id: "p1",
  user_id: "u1",
  name: "Lyra",
  tagline: "Test persona",
  model_unique_id: "test:model",
  system_prompt: "",
  temperature: 0.8,
  reasoning_enabled: false,
  colour_scheme: "#7c5cbf",
  display_order: 0,
  created_at: "2026-01-01",
  updated_at: "2026-01-01",
}

const noop = () => {}

describe("PersonaItem", () => {
  it("renders persona name", () => {
    render(
      <PersonaItem persona={mockPersona} isActive={false}
        onSelect={noop} onNewChat={noop} onNewIncognitoChat={noop}
        onEdit={noop} onUnpin={noop} />
    )
    expect(screen.getByText("Lyra")).toBeDefined()
  })

  it("renders avatar initial", () => {
    render(
      <PersonaItem persona={mockPersona} isActive={false}
        onSelect={noop} onNewChat={noop} onNewIncognitoChat={noop}
        onEdit={noop} onUnpin={noop} />
    )
    expect(screen.getByText("L")).toBeDefined()
  })

  it("calls onSelect when row is clicked", async () => {
    const onSelect = vi.fn()
    render(
      <PersonaItem persona={mockPersona} isActive={false}
        onSelect={onSelect} onNewChat={noop} onNewIncognitoChat={noop}
        onEdit={noop} onUnpin={noop} />
    )
    await userEvent.click(screen.getByText("Lyra"))
    expect(onSelect).toHaveBeenCalledWith(mockPersona)
  })

  it("opens context menu and calls onEdit when Edit is clicked", async () => {
    const onEdit = vi.fn()
    render(
      <PersonaItem persona={mockPersona} isActive={false}
        onSelect={noop} onNewChat={noop} onNewIncognitoChat={noop}
        onEdit={onEdit} onUnpin={noop} />
    )
    await userEvent.click(screen.getByLabelText("More options"))
    await userEvent.click(screen.getByText("Edit"))
    expect(onEdit).toHaveBeenCalledWith(mockPersona)
  })
})
```

- [ ] **Step 2: Run test to confirm FAIL**

```bash
cd frontend
pnpm exec vitest run src/app/components/sidebar/PersonaItem.test.tsx
```

Expected: FAIL — `Cannot find module './PersonaItem'`

- [ ] **Step 3: Create `frontend/src/app/components/sidebar/PersonaItem.tsx`**

```tsx
import { useState, useRef, useEffect } from "react"
import type { PersonaDto } from "../../../core/types/persona"
import { personaGradient, personaInitial } from "./personaColour"

interface PersonaItemProps {
  persona: PersonaDto
  isActive: boolean
  onSelect: (persona: PersonaDto) => void
  onNewChat: (persona: PersonaDto) => void
  onNewIncognitoChat: (persona: PersonaDto) => void
  onEdit: (persona: PersonaDto) => void
  onUnpin: (persona: PersonaDto) => void
}

export function PersonaItem({
  persona,
  isActive,
  onSelect,
  onNewChat,
  onNewIncognitoChat,
  onEdit,
  onUnpin,
}: PersonaItemProps) {
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [menuOpen])

  const menuItems = [
    { label: "New Chat", action: () => { onNewChat(persona); setMenuOpen(false) } },
    { label: "New Incognito Chat", action: () => { onNewIncognitoChat(persona); setMenuOpen(false) } },
    { label: "Edit", action: () => { onEdit(persona); setMenuOpen(false) } },
    { label: "Unpin", action: () => { onUnpin(persona); setMenuOpen(false) }, muted: true },
  ]

  return (
    <div
      className={`group relative mx-1.5 flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 transition-colors
        ${isActive ? "bg-white/8" : "hover:bg-white/5"}`}
      onClick={() => onSelect(persona)}
    >
      <span className="cursor-grab select-none text-[10px] leading-none text-white/15 group-hover:text-white/30">
        ⠿
      </span>

      <div
        className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white"
        style={{ background: personaGradient(persona) }}
      >
        {personaInitial(persona)}
      </div>

      <span
        className={`flex-1 truncate text-[13px] transition-colors
          ${isActive ? "text-white/90" : "text-white/50 group-hover:text-white/75"}`}
      >
        {persona.name}
      </span>

      <button
        type="button"
        aria-label="More options"
        className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded text-sm text-white/30 opacity-0 transition-all hover:bg-white/10 hover:text-white/70 group-hover:opacity-100"
        onClick={(e) => { e.stopPropagation(); setMenuOpen(true) }}
      >
        ···
      </button>

      {menuOpen && (
        <div
          ref={menuRef}
          className="absolute right-2 top-8 z-50 w-48 rounded-lg border border-white/10 bg-elevated py-1 shadow-xl"
          onClick={(e) => e.stopPropagation()}
        >
          {menuItems.map(({ label, action, muted }) => (
            <button
              key={label}
              type="button"
              onClick={action}
              className={`w-full px-3 py-1.5 text-left text-[13px] transition-colors hover:bg-white/6
                ${muted ? "text-white/40" : "text-white/70"}`}
            >
              {label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run test to confirm PASS**

```bash
cd frontend
pnpm exec vitest run src/app/components/sidebar/PersonaItem.test.tsx
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/chris/workspace/chatsune
git add frontend/src/app/components/sidebar/PersonaItem.tsx \
        frontend/src/app/components/sidebar/PersonaItem.test.tsx
git commit -m "Add PersonaItem with avatar gradient, drag handle, and context menu"
```

---

## Task 7: HistoryItem component

**Files:**
- Create: `frontend/src/app/components/sidebar/HistoryItem.tsx`

Simple row: optional pin icon + truncated title. No test — it's a pure presentational component with no logic.

`ChatSessionDto` has no `title` field. Use `updated_at` formatted as a readable date as the display title.

- [ ] **Step 1: Create `frontend/src/app/components/sidebar/HistoryItem.tsx`**

```tsx
import type { ChatSessionDto } from "../../../core/api/chat"

function formatSessionDate(isoString: string): string {
  const d = new Date(isoString)
  return d.toLocaleDateString("de-DE", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  })
}

interface HistoryItemProps {
  session: ChatSessionDto
  isPinned: boolean
  isActive: boolean
  onClick: (session: ChatSessionDto) => void
}

export function HistoryItem({ session, isPinned, isActive, onClick }: HistoryItemProps) {
  return (
    <div
      className={`mx-1.5 flex cursor-pointer items-center gap-2 rounded-lg px-3 py-1 text-[12px] transition-colors
        ${isActive ? "bg-white/6 text-white/80" : "text-white/28 hover:bg-white/4 hover:text-white/55"}`}
      onClick={() => onClick(session)}
    >
      {isPinned && <span className="flex-shrink-0 text-[11px]">📌</span>}
      <span className="flex-1 truncate">{formatSessionDate(session.updated_at)}</span>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
cd /home/chris/workspace/chatsune
git add frontend/src/app/components/sidebar/HistoryItem.tsx
git commit -m "Add HistoryItem component for sidebar chat history list"
```

---

## Task 8: Sidebar component

**Files:**
- Create: `frontend/src/app/components/sidebar/Sidebar.tsx`

Assembles all sidebar sections. Receives `personas` and `sessions` as props from `AppLayout` — does not fetch its own data. Manages the Projects section collapse state in `localStorage`. For Phase 1: all personas are shown (no "pinned" concept yet — that requires a backend field). Projects section shows an empty state.

- [ ] **Step 1: Create `frontend/src/app/components/sidebar/Sidebar.tsx`**

```tsx
import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useAuthStore } from "../../../core/store/authStore"
import { useAuth } from "../../../core/hooks/useAuth"
import { NavRow } from "./NavRow"
import { PersonaItem } from "./PersonaItem"
import { HistoryItem } from "./HistoryItem"
import type { PersonaDto } from "../../../core/types/persona"
import type { ChatSessionDto } from "../../../core/api/chat"

interface SidebarProps {
  personas: PersonaDto[]
  sessions: ChatSessionDto[]
  activePersonaId: string | null
  activeSessionId: string | null
}

export function Sidebar({ personas, sessions, activePersonaId, activeSessionId }: SidebarProps) {
  const user = useAuthStore((s) => s.user)
  const { logout } = useAuth()
  const navigate = useNavigate()

  const isAdmin = user?.role === "admin" || user?.role === "master_admin"

  const [projectsOpen, setProjectsOpen] = useState(() => {
    return localStorage.getItem("chatsune_projects_open") === "true"
  })

  function toggleProjects() {
    const next = !projectsOpen
    setProjectsOpen(next)
    localStorage.setItem("chatsune_projects_open", String(next))
  }

  function handlePersonaSelect(persona: PersonaDto) {
    navigate(`/chat/${persona.id}`)
  }

  function handleNewChat(persona: PersonaDto) {
    // Navigation to new chat — ChatPage will handle session creation
    navigate(`/chat/${persona.id}?new=1`)
  }

  function handleSessionClick(session: ChatSessionDto) {
    navigate(`/chat/${session.persona_id}/${session.id}`)
  }

  return (
    <aside className="flex h-full w-[232px] flex-shrink-0 flex-col border-r border-white/6 bg-base">

      {/* Logo */}
      <div className="flex h-[50px] flex-shrink-0 items-center gap-2.5 border-b border-white/5 px-3.5">
        <span className="text-[17px]">⬡</span>
        <span className="text-[15px] font-semibold tracking-wide text-white/85">Chatsune</span>
      </div>

      {/* Admin banner — admins only */}
      {isAdmin && (
        <button
          type="button"
          onClick={() => navigate("/admin")}
          className="mx-2 mt-2 flex items-center gap-2 rounded-lg border border-gold/16 bg-gold/7 px-2.5 py-1.5 transition-colors hover:bg-gold/12"
        >
          <span className="text-[12px]">✦</span>
          <span className="flex-1 text-left text-[12px] font-bold uppercase tracking-widest text-gold">Admin</span>
          <span className="text-[11px] text-gold/50">›</span>
        </button>
      )}

      {/* CHAT */}
      <div className="mt-1.5 flex-shrink-0">
        <NavRow icon="◈" label="Chat" onClick={() => navigate("/personas")} />
        <div className="mt-0.5">
          {personas.map((p) => (
            <PersonaItem
              key={p.id}
              persona={p}
              isActive={p.id === activePersonaId}
              onSelect={handlePersonaSelect}
              onNewChat={handleNewChat}
              onNewIncognitoChat={(persona) => navigate(`/chat/${persona.id}?incognito=1`)}
              onEdit={(persona) => navigate(`/personas?edit=${persona.id}`)}
              onUnpin={() => {
                // Phase 2 — requires nsfw/pin field in backend
              }}
            />
          ))}
          {personas.length === 0 && (
            <p className="px-4 py-1 text-[12px] text-white/20">No personas yet</p>
          )}
        </div>
      </div>

      <div className="mx-2 my-1.5 h-px bg-white/4" />

      {/* Shared scroll zone: Projects + History */}
      <div className="min-h-0 flex-1 overflow-y-auto [&::-webkit-scrollbar]:w-[3px] [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/8">

        {/* PROJECTS */}
        <NavRow
          icon="◫"
          label="Projects"
          onClick={() => navigate("/projects")}
          actions={
            <>
              <button
                type="button"
                className="flex h-[22px] w-[22px] items-center justify-center rounded text-[11px] text-white/20 transition-colors hover:bg-white/8 hover:text-white/55"
                onClick={() => navigate("/projects?search=1")}
                aria-label="Search projects"
              >
                🔍
              </button>
              <button
                type="button"
                className="flex h-[22px] w-[22px] items-center justify-center rounded text-[11px] text-white/20 transition-colors hover:bg-white/8 hover:text-white/55"
                onClick={toggleProjects}
                aria-label={projectsOpen ? "Collapse projects" : "Expand projects"}
              >
                {projectsOpen ? "∨" : "›"}
              </button>
            </>
          }
        />

        {projectsOpen && (
          <p className="mx-3 py-1 text-[12px] text-white/20">No projects yet</p>
        )}

        <div className="mx-2 my-1 h-px bg-white/4" />

        {/* HISTORY */}
        <NavRow
          icon="◷"
          label="History"
          onClick={() => navigate("/history")}
          actions={
            <button
              type="button"
              className="flex h-[22px] w-[22px] items-center justify-center rounded text-[11px] text-white/20 transition-colors hover:bg-white/8 hover:text-white/55"
              onClick={() => navigate("/history?search=1")}
              aria-label="Search history"
            >
              🔍
            </button>
          }
        />

        <div className="mt-0.5 pb-2">
          {sessions.map((s) => (
            <HistoryItem
              key={s.id}
              session={s}
              isPinned={false}
              isActive={s.id === activeSessionId}
              onClick={handleSessionClick}
            />
          ))}
          {sessions.length === 0 && (
            <p className="px-4 py-1 text-[12px] text-white/20">No history yet</p>
          )}
        </div>

      </div>

      {/* Bottom */}
      <div className="flex-shrink-0 border-t border-white/5">
        <NavRow icon="🧠" label="Knowledge" onClick={() => navigate("/knowledge")} />

        {/* User row — entire area is the menu trigger */}
        <button
          type="button"
          onClick={() => logout()}
          className="flex w-full items-center gap-2.5 px-3 py-2.5 transition-colors hover:bg-white/4"
          title="Click to log out (settings menu coming soon)"
        >
          <div className="flex h-[30px] w-[30px] flex-shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-purple to-gold text-[12px] font-bold text-white">
            {user?.display_name?.charAt(0).toUpperCase() ?? user?.username?.charAt(0).toUpperCase() ?? "?"}
          </div>
          <div className="text-left">
            <p className="text-[13px] font-medium text-white/65">{user?.display_name || user?.username}</p>
            <p className="text-[10px] text-white/22">{user?.role}</p>
          </div>
        </button>
      </div>

    </aside>
  )
}
```

**Note:** The user row currently calls `logout()` directly — a proper user menu (settings, sanitized mode toggle) is Phase 2. The `title` attribute documents this for the implementer.

- [ ] **Step 2: Commit**

```bash
cd /home/chris/workspace/chatsune
git add frontend/src/app/components/sidebar/Sidebar.tsx
git commit -m "Add Sidebar component with CHAT, PROJECTS, HISTORY, KNOWLEDGE sections"
```

---

## Task 9: Topbar component

**Files:**
- Create: `frontend/src/app/components/topbar/Topbar.tsx`

Context-sensitive. Uses the current URL path to determine what to render:
- `/chat/:personaId` or `/chat/:personaId/:sessionId` → chat context (persona chip + session + model + live)
- `/admin/*` → admin context (section title + tab strip — tabs are stubs for now)
- Everything else → section title only

Receives `personas` as a prop so it can look up the active persona name without an extra API call.

- [ ] **Step 1: Create `frontend/src/app/components/topbar/Topbar.tsx`**

```tsx
import { useMatch, useNavigate } from "react-router-dom"
import { useEventStore } from "../../../core/store/eventStore"
import type { PersonaDto } from "../../../core/types/persona"

const SECTION_TITLES: Record<string, string> = {
  "/personas": "Personas",
  "/projects": "Projects",
  "/history": "History",
  "/knowledge": "Knowledge",
}

const ADMIN_TABS = ["Users", "Models", "System"]

interface TopbarProps {
  personas: PersonaDto[]
}

export function Topbar({ personas }: TopbarProps) {
  const wsStatus = useEventStore((s) => s.status)
  const navigate = useNavigate()

  const chatMatch = useMatch("/chat/:personaId/:sessionId?")
  const adminMatch = useMatch("/admin/*")

  const isLive = wsStatus === "connected"

  if (chatMatch) {
    const { personaId } = chatMatch.params
    const persona = personas.find((p) => p.id === personaId)

    return (
      <header className="flex h-[50px] flex-shrink-0 items-center gap-2.5 border-b border-white/6 bg-surface px-4">
        {persona && (
          <button
            type="button"
            onClick={() => navigate("/personas")}
            className="flex items-center gap-2 rounded-full border border-white/8 bg-white/5 px-3 py-1 text-[13px] font-medium text-white/75 transition-colors hover:bg-white/8"
          >
            <span className="h-2 w-2 rounded-full bg-purple" />
            {persona.name}
          </button>
        )}

        <span className="text-white/15">/</span>
        <span className="max-w-[260px] truncate text-[13px] text-white/32">
          {chatMatch.params.sessionId ? "Continued session" : "New chat"}
        </span>

        <div className="ml-auto flex items-center gap-1.5">
          {persona && (
            <span className="rounded-full border border-gold/20 bg-gold/5 px-2.5 py-0.5 font-mono text-[11px] text-gold">
              {persona.model_unique_id.split(":")[1] ?? persona.model_unique_id}
            </span>
          )}
          <span
            className={`flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-mono text-[11px]
              ${isLive
                ? "border-white/7 bg-white/4 text-white/35"
                : "border-white/5 bg-white/2 text-white/20"}`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${isLive ? "bg-live" : "bg-white/20"}`} />
            {wsStatus}
          </span>
        </div>
      </header>
    )
  }

  if (adminMatch) {
    return (
      <header className="flex h-[50px] flex-shrink-0 items-center gap-4 border-b border-white/6 bg-surface px-4">
        <span className="text-[13px] font-semibold text-white/60">Admin</span>
        <div className="flex gap-1">
          {ADMIN_TABS.map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => navigate(`/admin/${tab.toLowerCase()}`)}
              className="rounded-md px-3 py-1 text-[13px] text-white/40 transition-colors hover:bg-white/6 hover:text-white/70"
            >
              {tab}
            </button>
          ))}
        </div>
        <div className="ml-auto">
          <span
            className={`flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-mono text-[11px]
              ${isLive ? "border-white/7 bg-white/4 text-white/35" : "border-white/5 text-white/20"}`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${isLive ? "bg-live" : "bg-white/20"}`} />
            {wsStatus}
          </span>
        </div>
      </header>
    )
  }

  // Generic: section title
  const path = window.location.pathname
  const title = SECTION_TITLES[path] ?? ""

  return (
    <header className="flex h-[50px] flex-shrink-0 items-center gap-4 border-b border-white/6 bg-surface px-4">
      <span className="text-[13px] font-semibold text-white/60">{title}</span>
      <div className="ml-auto">
        <span
          className={`flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-mono text-[11px]
            ${isLive ? "border-white/7 bg-white/4 text-white/35" : "border-white/5 text-white/20"}`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${isLive ? "bg-live" : "bg-white/20"}`} />
          {wsStatus}
        </span>
      </div>
    </header>
  )
}
```

- [ ] **Step 2: Commit**

```bash
cd /home/chris/workspace/chatsune
git add frontend/src/app/components/topbar/Topbar.tsx
git commit -m "Add context-sensitive Topbar (chat, admin, generic section contexts)"
```

---

## Task 10: Stub pages

**Files:**
- Create: `frontend/src/app/pages/PersonasPage.tsx`
- Create: `frontend/src/app/pages/ChatPage.tsx`
- Create: `frontend/src/app/pages/ProjectsPage.tsx`
- Create: `frontend/src/app/pages/HistoryPage.tsx`
- Create: `frontend/src/app/pages/KnowledgePage.tsx`
- Create: `frontend/src/app/pages/AdminPage.tsx`

All stubs have the same shape — they hold the layout slot until the real page is implemented.

- [ ] **Step 1: Create all stub pages**

`frontend/src/app/pages/PersonasPage.tsx`:
```tsx
export default function PersonasPage() {
  return (
    <div className="flex flex-1 items-center justify-center text-[13px] text-white/20">
      Personas — coming soon
    </div>
  )
}
```

`frontend/src/app/pages/ChatPage.tsx`:
```tsx
export default function ChatPage() {
  return (
    <div className="flex flex-1 items-center justify-center text-[13px] text-white/20">
      Chat — coming soon
    </div>
  )
}
```

`frontend/src/app/pages/ProjectsPage.tsx`:
```tsx
export default function ProjectsPage() {
  return (
    <div className="flex flex-1 items-center justify-center text-[13px] text-white/20">
      Projects — coming soon
    </div>
  )
}
```

`frontend/src/app/pages/HistoryPage.tsx`:
```tsx
export default function HistoryPage() {
  return (
    <div className="flex flex-1 items-center justify-center text-[13px] text-white/20">
      History — coming soon
    </div>
  )
}
```

`frontend/src/app/pages/KnowledgePage.tsx`:
```tsx
export default function KnowledgePage() {
  return (
    <div className="flex flex-1 items-center justify-center text-[13px] text-white/20">
      Knowledge — coming soon
    </div>
  )
}
```

`frontend/src/app/pages/AdminPage.tsx`:
```tsx
export default function AdminPage() {
  return (
    <div className="flex flex-1 items-center justify-center text-[13px] text-white/20">
      Admin — coming soon
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
cd /home/chris/workspace/chatsune
git add frontend/src/app/pages/
git commit -m "Add stub pages for all app routes (personas, chat, projects, history, knowledge, admin)"
```

---

## Task 11: AppLayout

**Files:**
- Create: `frontend/src/app/layouts/AppLayout.tsx`

The shell wrapper. Lifts `usePersonas` and `useChatSessions` so both `Sidebar` and `Topbar` share the same data without duplicate API calls. Uses `useMatch` to determine the active persona and session IDs from the URL.

- [ ] **Step 1: Create `frontend/src/app/layouts/AppLayout.tsx`**

```tsx
import { Outlet, useMatch } from "react-router-dom"
import { useWebSocket } from "../../core/hooks/useWebSocket"
import { usePersonas } from "../../core/hooks/usePersonas"
import { useChatSessions } from "../../core/hooks/useChatSessions"
import { Sidebar } from "../components/sidebar/Sidebar"
import { Topbar } from "../components/topbar/Topbar"

export default function AppLayout() {
  useWebSocket()

  const { personas } = usePersonas()
  const { sessions } = useChatSessions()

  const chatMatch = useMatch("/chat/:personaId/:sessionId?")
  const activePersonaId = chatMatch?.params.personaId ?? null
  const activeSessionId = chatMatch?.params.sessionId ?? null

  return (
    <div className="flex h-screen overflow-hidden bg-base text-white">
      <Sidebar
        personas={personas}
        sessions={sessions}
        activePersonaId={activePersonaId}
        activeSessionId={activeSessionId}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar personas={personas} />
        <main className="flex-1 overflow-auto bg-surface">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
cd /home/chris/workspace/chatsune
git add frontend/src/app/layouts/AppLayout.tsx
git commit -m "Add AppLayout shell: sidebar + topbar + outlet with shared data"
```

---

## Task 12: Login page

**Files:**
- Create: `frontend/src/app/pages/LoginPage.tsx`

Centred card on dark background. Uses existing `useAuth` hook. Errors display inline on the form (not as toasts).

- [ ] **Step 1: Create `frontend/src/app/pages/LoginPage.tsx`**

```tsx
import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useAuth } from "../../core/hooks/useAuth"

export default function LoginPage() {
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const { login } = useAuth()
  const navigate = useNavigate()

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setIsLoading(true)
    try {
      await login(username, password)
      const last = localStorage.getItem("chatsune_last_route")
      navigate(last ?? "/personas", { replace: true })
    } catch {
      setError("Invalid username or password")
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-base">
      <div className="w-full max-w-sm rounded-xl border border-white/8 bg-surface p-8 shadow-2xl">
        <div className="mb-6 text-center">
          <span className="text-3xl">⬡</span>
          <h1 className="mt-2 text-xl font-semibold text-white/85">Chatsune</h1>
          <p className="mt-1 text-[13px] text-white/30">Sign in to continue</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1.5 block text-[12px] font-medium text-white/40">
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoFocus
              className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-[14px] text-white/85 placeholder-white/20 outline-none transition-colors focus:border-white/25 focus:bg-white/8"
            />
          </div>

          <div>
            <label className="mb-1.5 block text-[12px] font-medium text-white/40">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-[14px] text-white/85 placeholder-white/20 outline-none transition-colors focus:border-white/25 focus:bg-white/8"
            />
          </div>

          {error && (
            <p className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-[13px] text-red-400">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={isLoading}
            className="w-full rounded-lg bg-white/10 py-2 text-[14px] font-medium text-white/80 transition-colors hover:bg-white/15 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isLoading ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
cd /home/chris/workspace/chatsune
git add frontend/src/app/pages/LoginPage.tsx
git commit -m "Add styled LoginPage with inline error handling"
```

---

## Task 13: App.tsx routing overhaul + last-route persistence

**Files:**
- Modify: `frontend/src/App.tsx`

Replace prototype imports with `app/` imports. Add last-route persistence (`chatsune_last_route` in localStorage). Update `AuthGuard` to handle `isInitialising`. Remove `useWebSocket` from `AppRoutes` — it's now called inside `AppLayout`.

- [ ] **Step 1: Replace `frontend/src/App.tsx`**

```tsx
import { useEffect } from "react"
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom"
import { useAuthStore } from "./core/store/authStore"
import { useBootstrap } from "./core/hooks/useBootstrap"
import AppLayout from "./app/layouts/AppLayout"
import LoginPage from "./app/pages/LoginPage"
import PersonasPage from "./app/pages/PersonasPage"
import ChatPage from "./app/pages/ChatPage"
import ProjectsPage from "./app/pages/ProjectsPage"
import HistoryPage from "./app/pages/HistoryPage"
import KnowledgePage from "./app/pages/KnowledgePage"
import AdminPage from "./app/pages/AdminPage"

/** Persists current /chat/... route to localStorage for bootstrap redirect */
function LastRouteTracker() {
  const location = useLocation()
  useEffect(() => {
    if (location.pathname.startsWith("/chat/")) {
      localStorage.setItem("chatsune_last_route", location.pathname)
    }
  }, [location.pathname])
  return null
}

function AuthGuard({ children }: { children: React.ReactNode }) {
  const isInitialising = useAuthStore((s) => s.isInitialising)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const mustChangePassword = useAuthStore((s) => s.user?.must_change_password)

  if (isInitialising) return null
  if (!isAuthenticated) return <Navigate to="/login" replace />
  if (mustChangePassword) return <Navigate to="/login" replace />

  return <>{children}</>
}

function AppRoutes() {
  useBootstrap()

  return (
    <>
      <LastRouteTracker />
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          element={
            <AuthGuard>
              <AppLayout />
            </AuthGuard>
          }
        >
          <Route path="/personas" element={<PersonasPage />} />
          <Route path="/chat/:personaId/:sessionId?" element={<ChatPage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/knowledge" element={<KnowledgePage />} />
          <Route path="/admin/*" element={<AdminPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/personas" replace />} />
      </Routes>
    </>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend
pnpm exec tsc --noEmit
```

Expected: no errors. If errors appear, they will point to missing imports or type mismatches — fix them before committing.

- [ ] **Step 3: Commit**

```bash
cd /home/chris/workspace/chatsune
git add frontend/src/App.tsx
git commit -m "Replace prototype routing with app/ layout and last-route persistence"
```

---

## Task 14: Delete prototype and run full test suite

**Files:**
- Delete: `frontend/src/prototype/` (entire directory)

- [ ] **Step 1: Delete prototype directory**

```bash
rm -rf /home/chris/workspace/chatsune/frontend/src/prototype
```

- [ ] **Step 2: Verify no remaining imports**

```bash
cd /home/chris/workspace/chatsune
rg "from.*prototype" frontend/src --type ts --type tsx
```

Expected: no output. If any matches appear, update those files to use the `app/` equivalents.

- [ ] **Step 3: TypeScript check**

```bash
cd frontend
pnpm exec tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Run all tests**

```bash
cd frontend
pnpm exec vitest run
```

Expected: all tests PASS. Fix any failures before committing.

- [ ] **Step 5: Smoke-test in browser**

```bash
cd /home/chris/workspace/chatsune
docker compose up -d
# Open http://localhost:5173
```

Verify:
- Login page renders (dark card on dark background)
- Login with valid credentials → redirects to `/personas` (stub)
- Sidebar visible with all sections (ADMIN for admin user, CHAT, PROJECTS, HISTORY, KNOWLEDGE)
- Ctrl+F5 → stays logged in (bootstrap refresh works)
- Nav rows have hover-underline on label

- [ ] **Step 6: Commit**

```bash
cd /home/chris/workspace/chatsune
git add -A
git commit -m "Remove prototype frontend — production shell complete"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Login page → Task 12
- [x] Bootstrap / last-route persistence → Tasks 3 (useChatSessions), 13 (App.tsx)
- [x] Sidebar: logo, admin banner, CHAT+personas, PROJECTS (collapsed), HISTORY, KNOWLEDGE, user row → Task 8
- [x] NavRow dual-action headers → Task 5
- [x] PersonaItem with context menu → Task 6
- [x] HistoryItem → Task 7
- [x] Topbar: chat context, admin context, generic → Task 9
- [x] Design tokens → Task 2
- [x] Persona gradient utility → Task 4
- [x] Stub pages for all routes → Task 10
- [x] AuthGuard with isInitialising → Task 13
- [x] Delete prototype → Task 14
- [x] Sanitized mode: toggle is non-functional in Phase 1 per spec — **not implemented** (correct per spec)
- [x] Drag-and-drop reorder: handles visible, interaction is Phase 2 — **handle rendered, no dnd library** (correct per spec)

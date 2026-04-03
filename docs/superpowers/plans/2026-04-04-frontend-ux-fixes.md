# Frontend UX Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four independent UX issues: fox emoji favicon, close user overlay on navigation, apply display settings CSS vars (especially UI Scale), and implement a live-updating user display name via a `/me` backend endpoint and WebSocket event.

**Architecture:** Tasks 1–3 are self-contained frontend changes. Tasks 4–9 implement the display name feature end-to-end: shared contracts first, then backend endpoints, then frontend data loading and event subscription, and finally the About Me tab UI. Each task can be committed independently.

**Tech Stack:** React/TSX, Vite, Tailwind CSS, Vitest + @testing-library/react, FastAPI, Pydantic v2, Motor (async MongoDB), Redis-backed EventBus

---

## File Map

**Created:**
- `frontend/src/app/components/sidebar/Sidebar.test.tsx`
- `frontend/src/app/components/user-modal/AboutMeTab.test.tsx`

**Modified:**
- `frontend/public/favicon.svg` — fox emoji SVG
- `frontend/index.html` — page title → "Chatsune"
- `frontend/src/index.css` — `--ui-scale` default + `body { zoom }` + `.chat-text` class
- `frontend/src/app/components/sidebar/Sidebar.tsx` — `onCloseModal` prop + `'Unnamed User'` fallback
- `frontend/src/app/layouts/AppLayout.tsx` — pass `onCloseModal`, subscribe to `USER_PROFILE_UPDATED`
- `frontend/src/core/types/events.ts` — add `USER_PROFILE_UPDATED` to `Topics`
- `frontend/src/core/api/meApi.ts` — add `getMe()` and `updateDisplayName()`
- `frontend/src/core/hooks/useBootstrap.ts` — call `getMe()` after token refresh
- `frontend/src/core/hooks/useAuth.ts` — call `getMe()` after login
- `frontend/src/app/components/user-modal/AboutMeTab.tsx` — display name field
- `shared/topics.py` — `USER_PROFILE_UPDATED` constant
- `shared/events/auth.py` — `UserProfileUpdatedEvent`
- `shared/dtos/auth.py` — `UpdateDisplayNameDto`
- `backend/modules/user/_handlers.py` — `GET /users/me`, `PATCH /users/me/profile`, default display_name fix
- `backend/ws/event_bus.py` — add `USER_PROFILE_UPDATED` fanout rule

---

## Task 1: Fox Emoji Favicon and Page Title

**Files:**
- Modify: `frontend/public/favicon.svg`
- Modify: `frontend/index.html`

- [ ] **Step 1: Replace favicon.svg with fox emoji SVG**

  Replace the full contents of `frontend/public/favicon.svg` with:

  ```svg
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
    <text y=".9em" font-size="90">🦊</text>
  </svg>
  ```

- [ ] **Step 2: Update page title in index.html**

  In `frontend/index.html`, change:
  ```html
  <title>frontend</title>
  ```
  to:
  ```html
  <title>Chatsune</title>
  ```

- [ ] **Step 3: Verify visually**

  Run `cd frontend && pnpm dev` and open the browser. Confirm the fox emoji appears in the browser tab.

- [ ] **Step 4: Commit**

  ```bash
  git add frontend/public/favicon.svg frontend/index.html
  git commit -m "Use fox emoji as favicon and set page title to Chatsune"
  ```

---

## Task 2: Close User Overlay When Navigating Away

**Files:**
- Modify: `frontend/src/app/components/sidebar/Sidebar.tsx`
- Modify: `frontend/src/app/layouts/AppLayout.tsx`
- Create: `frontend/src/app/components/sidebar/Sidebar.test.tsx`

- [ ] **Step 1: Write the failing tests**

  Create `frontend/src/app/components/sidebar/Sidebar.test.tsx`:

  ```typescript
  import { describe, it, expect, vi, beforeEach } from 'vitest'
  import { render, screen } from '@testing-library/react'
  import userEvent from '@testing-library/user-event'
  import { MemoryRouter } from 'react-router-dom'
  import { Sidebar } from './Sidebar'

  const mockNavigate = vi.fn()

  vi.mock('react-router-dom', async () => {
    const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
    return { ...actual, useNavigate: () => mockNavigate }
  })

  vi.mock('../../../core/store/authStore', () => ({
    useAuthStore: (sel: (s: Record<string, unknown>) => unknown) =>
      sel({ user: { role: 'admin', display_name: 'Test Admin', username: 'admin' } }),
  }))

  vi.mock('../../../core/hooks/useAuth', () => ({
    useAuth: () => ({ logout: vi.fn() }),
  }))

  const defaults = {
    personas: [],
    sessions: [],
    activePersonaId: null,
    activeSessionId: null,
    onOpenModal: vi.fn(),
    onCloseModal: vi.fn(),
    activeModalTab: null as null,
  }

  function renderSidebar(overrides: Partial<typeof defaults> = {}) {
    return render(
      <MemoryRouter>
        <Sidebar {...defaults} {...overrides} />
      </MemoryRouter>
    )
  }

  beforeEach(() => {
    mockNavigate.mockClear()
  })

  describe('Sidebar — overlay close on navigation', () => {
    it('calls onCloseModal when Admin banner is clicked', async () => {
      const onCloseModal = vi.fn()
      renderSidebar({ onCloseModal })
      await userEvent.click(screen.getByText('Admin'))
      expect(onCloseModal).toHaveBeenCalledOnce()
    })

    it('calls onCloseModal when Chat NavRow is clicked', async () => {
      const onCloseModal = vi.fn()
      renderSidebar({ onCloseModal })
      await userEvent.click(screen.getByText('Chat'))
      expect(onCloseModal).toHaveBeenCalledOnce()
    })
  })
  ```

- [ ] **Step 2: Run tests to confirm they fail**

  ```bash
  cd frontend && pnpm exec vitest run src/app/components/sidebar/Sidebar.test.tsx
  ```

  Expected: compilation error — `onCloseModal` does not exist on `SidebarProps`.

- [ ] **Step 3: Add `onCloseModal` to Sidebar**

  In `frontend/src/app/components/sidebar/Sidebar.tsx`, update the interface and the two navigation handlers:

  ```typescript
  interface SidebarProps {
    personas: PersonaDto[]
    sessions: ChatSessionDto[]
    activePersonaId: string | null
    activeSessionId: string | null
    onOpenModal: (tab: UserModalTab) => void
    onCloseModal: () => void          // ← add this line
    activeModalTab: UserModalTab | null
  }

  export function Sidebar({
    personas,
    sessions,
    activePersonaId,
    activeSessionId,
    onOpenModal,
    onCloseModal,                     // ← destructure it
    activeModalTab,
  }: SidebarProps) {
  ```

  Change the Admin button's `onClick`:
  ```typescript
  onClick={() => { onCloseModal(); navigate("/admin") }}
  ```

  Change the Chat NavRow's `onClick`:
  ```typescript
  <NavRow icon="◈" label="Chat" onClick={() => { onCloseModal(); navigate("/personas") }} />
  ```

  Also update the display name fallback while here (line with `const displayName = ...`):
  ```typescript
  const displayName = user?.display_name || user?.username || 'Unnamed User'
  ```

- [ ] **Step 4: Wire `onCloseModal` in AppLayout**

  In `frontend/src/app/layouts/AppLayout.tsx`, add `onCloseModal={closeModal}` to `<Sidebar>`:

  ```tsx
  <Sidebar
    personas={personas}
    sessions={sessions}
    activePersonaId={activePersonaId}
    activeSessionId={activeSessionId}
    onOpenModal={openModal}
    onCloseModal={closeModal}
    activeModalTab={modalTab}
  />
  ```

- [ ] **Step 5: Run tests to confirm they pass**

  ```bash
  cd frontend && pnpm exec vitest run src/app/components/sidebar/Sidebar.test.tsx
  ```

  Expected: 2 tests pass.

- [ ] **Step 6: Run full test suite**

  ```bash
  cd frontend && pnpm exec vitest run
  ```

  Expected: all tests pass.

- [ ] **Step 7: Commit**

  ```bash
  git add frontend/src/app/components/sidebar/Sidebar.tsx \
          frontend/src/app/layouts/AppLayout.tsx \
          frontend/src/app/components/sidebar/Sidebar.test.tsx
  git commit -m "Close user overlay when navigating to Admin or Chat"
  ```

---

## Task 3: Apply Display Settings CSS Variables

**Files:**
- Modify: `frontend/src/index.css`

- [ ] **Step 1: Add `--ui-scale` default and `body { zoom }` to index.css**

  The current `:root` block in `frontend/src/index.css` ends after `--chat-line-height`. Add `--ui-scale` to it and then add a `body` rule directly after the `:root` block:

  ```css
  /* Chat font — overridden at runtime by displaySettingsStore */
  :root {
    --chat-font-family: 'Lora', Georgia, serif;
    --chat-font-size: 14px;
    --chat-line-height: 1.65;
    --ui-scale: 1;
  }

  body {
    zoom: var(--ui-scale, 1);
  }

  /* Applied to chat message text in ChatPage */
  .chat-text {
    font-family: var(--chat-font-family);
    font-size: var(--chat-font-size);
    line-height: var(--chat-line-height);
  }
  ```

  Note: `displaySettingsStore.ts` already calls `applyCssVars` on startup and on every change, which sets these vars via `document.documentElement.style.setProperty(...)`. The `body { zoom }` rule reads the var and applies the scale immediately.

- [ ] **Step 2: Verify UI Scale works**

  Start the dev server (`cd frontend && pnpm dev`). Open the app, go to Settings in the User Modal, change UI Scale to 110%. The entire UI should zoom in. Change back to 100% to confirm it's reversible. Reload — the setting should persist.

- [ ] **Step 3: Run tests**

  ```bash
  cd frontend && pnpm exec vitest run
  ```

  Expected: all tests pass (CSS changes don't affect unit tests).

- [ ] **Step 4: Commit**

  ```bash
  git add frontend/src/index.css
  git commit -m "Apply UI Scale via CSS zoom and define .chat-text class"
  ```

---

## Task 4: Shared Contracts for Display Name

**Files:**
- Modify: `shared/topics.py`
- Modify: `shared/events/auth.py`
- Modify: `shared/dtos/auth.py`

- [ ] **Step 1: Add `USER_PROFILE_UPDATED` topic**

  In `shared/topics.py`, add after `USER_PASSWORD_RESET`:

  ```python
  USER_PROFILE_UPDATED = "user.profile.updated"
  ```

- [ ] **Step 2: Add `UserProfileUpdatedEvent`**

  In `shared/events/auth.py`, add at the end of the file:

  ```python
  class UserProfileUpdatedEvent(BaseModel):
      type: str = "user.profile.updated"
      user_id: str
      display_name: str
      timestamp: datetime
  ```

- [ ] **Step 3: Add `UpdateDisplayNameDto`**

  In `shared/dtos/auth.py`, first update the import at the top of the file from:
  ```python
  from pydantic import BaseModel, EmailStr
  ```
  to:
  ```python
  from pydantic import BaseModel, EmailStr, Field, field_validator
  ```

  Then add at the end of the file (after the existing `UpdateAboutMeDto`):

  ```python
  class UpdateDisplayNameDto(BaseModel):
      display_name: str = Field(..., max_length=64)

      @field_validator("display_name")
      @classmethod
      def strip_and_validate(cls, v: str) -> str:
          stripped = v.strip()
          if not stripped:
              raise ValueError("Display name cannot be blank")
          return stripped
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add shared/topics.py shared/events/auth.py shared/dtos/auth.py
  git commit -m "Add USER_PROFILE_UPDATED event and UpdateDisplayNameDto to shared contracts"
  ```

---

## Task 5: Backend — GET /api/users/me + Default Display Name

**Files:**
- Modify: `backend/modules/user/_handlers.py`

- [ ] **Step 1: Add `GET /users/me` endpoint**

  In `backend/modules/user/_handlers.py`, add this endpoint directly after the existing `PATCH /users/me/about-me` endpoint (after line ~305):

  ```python
  @router.get("/users/me")
  async def get_me(user: dict = Depends(get_current_user)):
      repo = _user_repo()
      doc = await repo.find_by_id(user["sub"])
      if doc is None:
          raise HTTPException(status_code=404, detail="User not found")
      return UserRepository.to_dto(doc)
  ```

- [ ] **Step 2: Fix default display_name in `create_user` handler**

  In the `create_user` handler (around line 334), change:
  ```python
  doc = await repo.create(
      username=body.username,
      email=body.email,
      display_name=body.display_name,
      ...
  )
  ```
  to:
  ```python
  doc = await repo.create(
      username=body.username,
      email=body.email,
      display_name=body.display_name or "Unnamed User",
      ...
  )
  ```

- [ ] **Step 3: Verify with curl**

  With the backend running and a valid access token `$TOKEN`:

  ```bash
  curl -s http://localhost:8000/api/users/me \
    -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
  ```

  Expected: JSON with `id`, `username`, `display_name`, `email`, `role`, etc.

- [ ] **Step 4: Commit**

  ```bash
  git add backend/modules/user/_handlers.py
  git commit -m "Add GET /api/users/me endpoint and default display_name to Unnamed User"
  ```

---

## Task 6: Backend — PATCH /api/users/me/profile + WebSocket Event

**Files:**
- Modify: `backend/modules/user/_handlers.py`
- Modify: `backend/ws/event_bus.py`

- [ ] **Step 1: Import new shared contracts in `_handlers.py`**

  In `backend/modules/user/_handlers.py`, add to the existing imports from `shared/dtos/auth`:
  ```python
  from shared.dtos.auth import (
      ...
      UpdateDisplayNameDto,       # ← add this
  )
  ```

  And add to the existing imports from `shared/events/auth`:
  ```python
  from shared.events.auth import (
      UserCreatedEvent,
      UserDeactivatedEvent,
      UserPasswordResetEvent,
      UserUpdatedEvent,
      UserProfileUpdatedEvent,    # ← add this
  )
  ```

- [ ] **Step 2: Add `PATCH /users/me/profile` endpoint**

  In `backend/modules/user/_handlers.py`, add this endpoint after `GET /users/me`:

  ```python
  @router.patch("/users/me/profile")
  async def update_my_profile(
      body: UpdateDisplayNameDto,
      user: dict = Depends(get_current_user),
      event_bus: EventBus = Depends(get_event_bus),
  ):
      repo = _user_repo()
      doc = await repo.update(user["sub"], {"display_name": body.display_name})
      if doc is None:
          raise HTTPException(status_code=404, detail="User not found")

      await event_bus.publish(
          Topics.USER_PROFILE_UPDATED,
          UserProfileUpdatedEvent(
              user_id=user["sub"],
              display_name=doc["display_name"],
              timestamp=doc["updated_at"],
          ),
          target_user_ids=[user["sub"]],
      )

      return UserRepository.to_dto(doc)
  ```

- [ ] **Step 3: Add fan-out rule for `USER_PROFILE_UPDATED`**

  In `backend/ws/event_bus.py`, add to the `_FANOUT` dict (alongside the other user events):

  ```python
  _FANOUT: dict[str, tuple[list[str], bool]] = {
      Topics.USER_CREATED: (["admin", "master_admin"], False),
      Topics.USER_UPDATED: (["admin", "master_admin"], True),
      Topics.USER_DEACTIVATED: (["admin", "master_admin"], True),
      Topics.USER_PASSWORD_RESET: (["admin", "master_admin"], True),
      Topics.USER_PROFILE_UPDATED: ([], True),           # ← add this line
      ...
  }
  ```

- [ ] **Step 4: Verify with curl**

  ```bash
  curl -s -X PATCH http://localhost:8000/api/users/me/profile \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"display_name": "Chris"}' | python3 -m json.tool
  ```

  Expected: returns updated `UserDto` with `display_name: "Chris"`.

- [ ] **Step 5: Commit**

  ```bash
  git add backend/modules/user/_handlers.py backend/ws/event_bus.py
  git commit -m "Add PATCH /api/users/me/profile endpoint with USER_PROFILE_UPDATED event"
  ```

---

## Task 7: Frontend — meApi Extensions + Load User on Login/Bootstrap

**Files:**
- Modify: `frontend/src/core/api/meApi.ts`
- Modify: `frontend/src/core/hooks/useBootstrap.ts`
- Modify: `frontend/src/core/hooks/useAuth.ts`

- [ ] **Step 1: Add `getMe` and `updateDisplayName` to meApi**

  Replace the full contents of `frontend/src/core/api/meApi.ts`:

  ```typescript
  import { api } from './client'
  import type { UserDto } from '../types/auth'

  export interface AboutMeResponse {
    about_me: string | null
  }

  export interface UpdateAboutMeRequest {
    about_me: string | null
  }

  export const meApi = {
    getMe: () =>
      api.get<UserDto>('/api/users/me'),

    getAboutMe: () =>
      api.get<AboutMeResponse>('/api/users/me/about-me'),

    updateAboutMe: (about_me: string | null) =>
      api.patch<AboutMeResponse>('/api/users/me/about-me', { about_me } satisfies UpdateAboutMeRequest),

    updateDisplayName: (display_name: string) =>
      api.patch<UserDto>('/api/users/me/profile', { display_name }),
  }
  ```

- [ ] **Step 2: Call `getMe` after token refresh in `useBootstrap`**

  Replace the full contents of `frontend/src/core/hooks/useBootstrap.ts`:

  ```typescript
  import { useEffect, useRef } from "react"
  import { authApi } from "../api/auth"
  import { meApi } from "../api/meApi"
  import { useAuthStore } from "../store/authStore"

  /** Attempts a silent token refresh on mount to restore an existing session. */
  export function useBootstrap() {
    const setToken = useAuthStore((s) => s.setToken)
    const setUser = useAuthStore((s) => s.setUser)
    const setInitialised = useAuthStore((s) => s.setInitialised)
    const hasRun = useRef(false)

    useEffect(() => {
      if (hasRun.current) return
      hasRun.current = true

      authApi
        .refresh()
        .then(async (response) => {
          setToken(response.access_token)
          try {
            const me = await meApi.getMe()
            setUser(me)
          } catch {
            // getMe failed — user stays authenticated with fallback display name
          }
        })
        .catch(() => {
          // No valid session — stay logged out
        })
        .finally(() => {
          setInitialised()
        })
    }, [])
  }
  ```

- [ ] **Step 3: Call `getMe` after login in `useAuth`**

  In `frontend/src/core/hooks/useAuth.ts`, add the `meApi` import at the top:

  ```typescript
  import { meApi } from "../api/meApi"
  ```

  Replace the `login` callback:

  ```typescript
  const login = useCallback(async (data: LoginRequest) => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await authApi.login(data)
      setToken(res.access_token)
      try {
        const me = await meApi.getMe()
        setUser(me)
      } catch {
        // getMe failed — user stays authenticated with fallback display name
      }
      connect()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed")
      throw err
    } finally {
      setIsLoading(false)
    }
  }, [setToken, setUser])
  ```

- [ ] **Step 4: Run tests**

  ```bash
  cd frontend && pnpm exec vitest run
  ```

  Expected: all tests pass.

- [ ] **Step 5: Commit**

  ```bash
  git add frontend/src/core/api/meApi.ts \
          frontend/src/core/hooks/useBootstrap.ts \
          frontend/src/core/hooks/useAuth.ts
  git commit -m "Load full user data via getMe() after login and bootstrap"
  ```

---

## Task 8: Frontend — Event Subscription and Sidebar Fallback

**Files:**
- Modify: `frontend/src/core/types/events.ts`
- Modify: `frontend/src/app/layouts/AppLayout.tsx`

(Note: the `Sidebar.tsx` `'Unnamed User'` fallback was already applied in Task 2.)

- [ ] **Step 1: Add `USER_PROFILE_UPDATED` to frontend Topics**

  In `frontend/src/core/types/events.ts`, add to the `Topics` object:

  ```typescript
  export const Topics = {
    USER_CREATED: "user.created",
    USER_UPDATED: "user.updated",
    USER_DEACTIVATED: "user.deactivated",
    USER_PASSWORD_RESET: "user.password_reset",
    USER_PROFILE_UPDATED: "user.profile.updated",    // ← add this
    AUDIT_LOGGED: "audit.logged",
    ERROR: "error",
    PERSONA_CREATED: "persona.created",
    PERSONA_UPDATED: "persona.updated",
    PERSONA_DELETED: "persona.deleted",
    LLM_CREDENTIAL_SET: "llm.credential.set",
    LLM_CREDENTIAL_REMOVED: "llm.credential.removed",
    LLM_CREDENTIAL_TESTED: "llm.credential.tested",
    LLM_MODEL_CURATED: "llm.model.curated",
    LLM_MODELS_REFRESHED: "llm.models.refreshed",
    LLM_USER_MODEL_CONFIG_UPDATED: "llm.user_model_config.updated",
    SETTING_UPDATED: "setting.updated",
    SETTING_DELETED: "setting.deleted",
    SETTING_SYSTEM_PROMPT_UPDATED: "setting.system_prompt.updated",
  } as const
  ```

- [ ] **Step 2: Subscribe to `USER_PROFILE_UPDATED` in AppLayout**

  Replace the full contents of `frontend/src/app/layouts/AppLayout.tsx`:

  ```typescript
  import { useEffect, useState } from "react"
  import { Outlet, useMatch } from "react-router-dom"
  import { useWebSocket } from "../../core/hooks/useWebSocket"
  import { usePersonas } from "../../core/hooks/usePersonas"
  import { useChatSessions } from "../../core/hooks/useChatSessions"
  import { useAuthStore } from "../../core/store/authStore"
  import { useEventBus } from "../../core/hooks/useEventBus"
  import { Sidebar } from "../components/sidebar/Sidebar"
  import { Topbar } from "../components/topbar/Topbar"
  import { UserModal, type UserModalTab } from "../components/user-modal/UserModal"
  import { Topics } from "../../core/types/events"
  import type { UserDto } from "../../core/types/auth"

  export default function AppLayout() {
    useWebSocket()

    const { personas } = usePersonas()
    const { sessions } = useChatSessions()
    const user = useAuthStore((s) => s.user)
    const setUser = useAuthStore((s) => s.setUser)

    const chatMatch = useMatch("/chat/:personaId/:sessionId?")
    const activePersonaId = chatMatch?.params.personaId ?? null
    const activeSessionId = chatMatch?.params.sessionId ?? null

    const [modalTab, setModalTab] = useState<UserModalTab | null>(null)

    function openModal(tab: UserModalTab) {
      setModalTab(tab)
    }

    function closeModal() {
      setModalTab(null)
    }

    // Live-update display name when user changes it in another tab or device
    const { latest: profileUpdate } = useEventBus(Topics.USER_PROFILE_UPDATED)
    useEffect(() => {
      if (!profileUpdate || !user) return
      const payload = profileUpdate.payload as Pick<UserDto, 'display_name'>
      setUser({ ...user, display_name: payload.display_name })
    }, [profileUpdate])

    const displayName = user?.display_name || user?.username || 'Unnamed User'

    return (
      <div className="flex h-screen overflow-hidden bg-base text-white">
        <Sidebar
          personas={personas}
          sessions={sessions}
          activePersonaId={activePersonaId}
          activeSessionId={activeSessionId}
          onOpenModal={openModal}
          onCloseModal={closeModal}
          activeModalTab={modalTab}
        />
        <div className="relative flex min-w-0 flex-1 flex-col">
          <Topbar personas={personas} />
          <main className="relative flex-1 overflow-auto bg-surface">
            <Outlet />
            {modalTab !== null && (
              <UserModal
                activeTab={modalTab}
                onClose={closeModal}
                onTabChange={setModalTab}
                displayName={displayName}
              />
            )}
          </main>
        </div>
      </div>
    )
  }
  ```

- [ ] **Step 3: Run tests**

  ```bash
  cd frontend && pnpm exec vitest run
  ```

  Expected: all tests pass.

- [ ] **Step 4: Commit**

  ```bash
  git add frontend/src/core/types/events.ts frontend/src/app/layouts/AppLayout.tsx
  git commit -m "Subscribe to USER_PROFILE_UPDATED event to live-update display name in sidebar"
  ```

---

## Task 9: Frontend — Display Name Field in About Me Tab

**Files:**
- Modify: `frontend/src/app/components/user-modal/AboutMeTab.tsx`
- Create: `frontend/src/app/components/user-modal/AboutMeTab.test.tsx`

- [ ] **Step 1: Write the failing test**

  Create `frontend/src/app/components/user-modal/AboutMeTab.test.tsx`:

  ```typescript
  import { render, screen, waitFor } from '@testing-library/react'
  import userEvent from '@testing-library/user-event'
  import { describe, it, expect, vi, beforeEach } from 'vitest'
  import { AboutMeTab } from './AboutMeTab'

  vi.mock('../../../core/api/meApi', () => ({
    meApi: {
      getAboutMe: vi.fn().mockResolvedValue({ about_me: null }),
      updateAboutMe: vi.fn().mockResolvedValue({ about_me: null }),
      updateDisplayName: vi.fn().mockResolvedValue({
        id: '1',
        username: 'chris',
        email: 'chris@example.com',
        display_name: 'New Name',
        role: 'user',
        is_active: true,
        must_change_password: false,
        created_at: '',
        updated_at: '',
      }),
    },
  }))

  vi.mock('../../../core/store/authStore', () => ({
    useAuthStore: (sel: (s: Record<string, unknown>) => unknown) =>
      sel({ user: { display_name: 'Chris', username: 'chris', role: 'user' } }),
  }))

  describe('AboutMeTab — display name field', () => {
    beforeEach(() => {
      vi.clearAllMocks()
    })

    it('renders display name input with value from auth store', async () => {
      render(<AboutMeTab />)
      const input = await screen.findByLabelText(/display name/i)
      expect(input).toHaveValue('Chris')
    })

    it('calls updateDisplayName with the new value on save', async () => {
      const { meApi } = await import('../../../core/api/meApi')
      render(<AboutMeTab />)

      const input = await screen.findByLabelText(/display name/i)
      await userEvent.clear(input)
      await userEvent.type(input, 'New Name')

      const saveBtn = screen.getByRole('button', { name: /save display name/i })
      await userEvent.click(saveBtn)

      await waitFor(() => {
        expect(meApi.updateDisplayName).toHaveBeenCalledWith('New Name')
      })
    })
  })
  ```

- [ ] **Step 2: Run test to confirm it fails**

  ```bash
  cd frontend && pnpm exec vitest run src/app/components/user-modal/AboutMeTab.test.tsx
  ```

  Expected: fails — `AboutMeTab` does not yet have a display name input.

- [ ] **Step 3: Add the display name field to `AboutMeTab.tsx`**

  Replace the full contents of `frontend/src/app/components/user-modal/AboutMeTab.tsx`:

  ```typescript
  import { useEffect, useRef, useState } from 'react'
  import { meApi } from '../../../core/api/meApi'
  import { useAuthStore } from '../../../core/store/authStore'

  const MAX_LENGTH = 2000
  const LABEL = "block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-2 font-mono"

  type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'

  export function AboutMeTab() {
    const user = useAuthStore((s) => s.user)

    // --- Display Name ---
    const [displayName, setDisplayName] = useState(user?.display_name ?? '')
    const [dnOriginal, setDnOriginal] = useState(user?.display_name ?? '')
    const [dnStatus, setDnStatus] = useState<SaveStatus>('idle')
    const dnTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

    // --- About Me text ---
    const [text, setText] = useState('')
    const [original, setOriginal] = useState('')
    const [loading, setLoading] = useState(true)
    const [loadError, setLoadError] = useState(false)
    const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle')
    const savedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

    useEffect(() => {
      return () => {
        if (savedTimerRef.current) clearTimeout(savedTimerRef.current)
        if (dnTimerRef.current) clearTimeout(dnTimerRef.current)
      }
    }, [])

    useEffect(() => {
      meApi.getAboutMe()
        .then((data) => {
          const value = data.about_me ?? ''
          setText(value)
          setOriginal(value)
        })
        .catch(() => setLoadError(true))
        .finally(() => setLoading(false))
    }, [])

    async function handleSaveDisplayName() {
      setDnStatus('saving')
      try {
        const updated = await meApi.updateDisplayName(displayName)
        setDnOriginal(updated.display_name)
        setDisplayName(updated.display_name)
        setDnStatus('saved')
        if (dnTimerRef.current) clearTimeout(dnTimerRef.current)
        dnTimerRef.current = setTimeout(() => setDnStatus('idle'), 2000)
      } catch {
        setDnStatus('error')
      }
    }

    async function handleSave() {
      setSaveStatus('saving')
      try {
        const data = await meApi.updateAboutMe(text || null)
        const value = data.about_me ?? ''
        setText(value)
        setOriginal(value)
        setSaveStatus('saved')
        if (savedTimerRef.current) clearTimeout(savedTimerRef.current)
        savedTimerRef.current = setTimeout(() => setSaveStatus('idle'), 2000)
      } catch {
        setSaveStatus('error')
      }
    }

    const isDnDirty = displayName !== dnOriginal
    const isDirty = text !== original

    return (
      <div className="p-6 max-w-2xl flex flex-col gap-8">

        {/* Display Name */}
        <div>
          <label
            htmlFor="display-name-input"
            className={LABEL}
          >
            Display Name
          </label>
          <div className="flex items-center gap-3">
            <input
              id="display-name-input"
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              maxLength={64}
              placeholder="Unnamed User"
              className="flex-1 bg-white/[0.03] border border-white/10 rounded-lg px-4 py-2 text-white/75 font-mono text-[13px] outline-none focus:border-gold/30 transition-colors"
            />
            <div className="flex items-center gap-2">
              {dnStatus === 'saved' && (
                <span className="font-mono text-[10px] text-white/40 tracking-wider uppercase">Saved</span>
              )}
              {dnStatus === 'error' && (
                <span className="font-mono text-[10px] text-red-400/80 tracking-wider uppercase">Failed</span>
              )}
              <button
                type="button"
                aria-label="Save display name"
                onClick={handleSaveDisplayName}
                disabled={dnStatus === 'saving' || !isDnDirty}
                className={[
                  'font-mono text-[11px] uppercase tracking-[0.12em] px-5 py-2 rounded-lg transition-all border border-white/10',
                  isDnDirty
                    ? 'bg-white/8 text-white/80 hover:bg-white/12 cursor-pointer'
                    : 'bg-transparent text-white/25 cursor-default',
                ].join(' ')}
              >
                {dnStatus === 'saving' ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        </div>

        {/* About Me text */}
        {loading ? (
          <div className="text-[12px] text-white/30 font-mono tracking-widest uppercase">Loading...</div>
        ) : loadError ? (
          <div className="text-[12px] text-red-400/70 font-mono">
            Could not load profile — please try again later.
          </div>
        ) : (
          <div>
            <label htmlFor="about-me-textarea" className={LABEL}>
              About You
            </label>
            <p className="text-[12px] text-white/40 font-mono mb-4 leading-relaxed">
              Tell your personas about yourself — your name, interests, preferences. Included at low
              priority in every conversation.
            </p>
            <textarea
              id="about-me-textarea"
              value={text}
              onChange={(e) => {
                if (e.target.value.length <= MAX_LENGTH) setText(e.target.value)
              }}
              placeholder="e.g. My name is Chris, I'm a developer living in Vienna..."
              className="w-full bg-white/[0.03] border border-white/10 rounded-lg px-4 py-3 text-white/75 font-mono text-[13px] leading-relaxed outline-none focus:border-gold/30 transition-colors resize-y"
              style={{ minHeight: 160 }}
            />
            <div className="flex items-center justify-between mt-3">
              <span className="font-mono text-[10px] text-white/25 tracking-wider">
                {text.length} / {MAX_LENGTH}
              </span>
              <div className="flex items-center gap-3">
                {saveStatus === 'saved' && (
                  <span className="font-mono text-[10px] text-white/40 tracking-wider uppercase">Saved</span>
                )}
                {saveStatus === 'error' && (
                  <span className="font-mono text-[10px] text-red-400/80 tracking-wider uppercase">Save failed</span>
                )}
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={saveStatus === 'saving' || !isDirty}
                  className={[
                    'font-mono text-[11px] uppercase tracking-[0.12em] px-5 py-2 rounded-lg transition-all border border-white/10',
                    isDirty
                      ? 'bg-white/8 text-white/80 hover:bg-white/12 cursor-pointer'
                      : 'bg-transparent text-white/25 cursor-default',
                  ].join(' ')}
                >
                  {saveStatus === 'saving' ? 'Saving...' : 'Save'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    )
  }
  ```

- [ ] **Step 4: Run failing tests**

  ```bash
  cd frontend && pnpm exec vitest run src/app/components/user-modal/AboutMeTab.test.tsx
  ```

  Expected: 2 tests pass.

- [ ] **Step 5: Run full test suite**

  ```bash
  cd frontend && pnpm exec vitest run
  ```

  Expected: all tests pass.

- [ ] **Step 6: Commit**

  ```bash
  git add frontend/src/app/components/user-modal/AboutMeTab.tsx \
          frontend/src/app/components/user-modal/AboutMeTab.test.tsx
  git commit -m "Add display name field to About Me tab with save and live-update support"
  ```

---

## Final Verification

- [ ] Start backend and frontend
- [ ] Log in — sidebar should show your display name (not "?" or "Unnamed User")
- [ ] Open About Me tab — display name input shows the current name
- [ ] Change display name and save — sidebar updates immediately via WebSocket event
- [ ] Change UI Scale in Settings — whole page zooms instantly
- [ ] Browser tab shows fox emoji favicon and title "Chatsune"
- [ ] Click Admin or Chat while overlay is open — overlay closes before navigating
- [ ] Reload page — display name persists (loaded from backend), UI Scale persists (from localStorage)

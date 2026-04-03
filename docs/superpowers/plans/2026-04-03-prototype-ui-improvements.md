# Prototype UI Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 5 UI improvements from the first prototype test run: auto-detect master admin, toast notifications, ModelBrowser with filters, admin system prompt tab, and API key status per user in admin view.

**Architecture:** Each work package is independent and can be implemented in any order. The toast system (Task 2-3) should go first because other work packages use toasts for feedback. Backend changes add new endpoints without modifying existing ones. Frontend changes are localised to individual pages/components.

**Tech Stack:** Python/FastAPI (backend), React/TypeScript/Zustand/Tailwind (frontend), pytest with httpx AsyncClient (tests)

**Spec:** `docs/superpowers/specs/2026-04-03-prototype-ui-improvements-design.md`

---

## File Structure

### New files

| File | Responsibility |
|------|---------------|
| `frontend/src/core/store/notificationStore.ts` | Zustand store for toast notifications |
| `frontend/src/prototype/components/Toasts.tsx` | Toast display component (fixed bottom-right) |
| `frontend/src/prototype/components/ModelBrowser.tsx` | Reusable model browser with filter bar and sortable table |
| `tests/test_auth_status.py` | Tests for `GET /api/auth/status` endpoint |
| `tests/test_system_prompt.py` | Tests for system prompt GET/PUT endpoints |
| `tests/test_admin_credential_status.py` | Tests for `GET /api/llm/admin/credential-status` endpoint |

### Modified files

| File | Changes |
|------|---------|
| `backend/modules/user/_handlers.py` | Add `GET /api/auth/status` endpoint |
| `backend/modules/settings/_handlers.py` | Add system prompt GET/PUT endpoints |
| `backend/modules/llm/_handlers.py` | Add `GET /api/llm/admin/credential-status` endpoint |
| `backend/modules/llm/_credentials.py` | Add `list_all()` method to CredentialRepository |
| `shared/topics.py` | Add `SETTING_SYSTEM_PROMPT_UPDATED` constant |
| `shared/events/settings.py` | Add `SettingSystemPromptUpdatedEvent` class |
| `frontend/src/core/types/events.ts` | Add `SETTING_SYSTEM_PROMPT_UPDATED` topic |
| `frontend/src/core/api/auth.ts` | Add `status()` method |
| `frontend/src/core/api/settings.ts` | Add `getSystemPrompt()` and `setSystemPrompt()` methods |
| `frontend/src/core/api/llm.ts` | Add `adminCredentialStatus()` method |
| `frontend/src/prototype/pages/LoginPage.tsx` | Auto-detect setup mode on mount |
| `frontend/src/prototype/pages/AdminPage.tsx` | Add System Prompt tab |
| `frontend/src/prototype/pages/UsersPage.tsx` | Add API key status badges, replace `alert()` with toasts |
| `frontend/src/prototype/pages/LlmPage.tsx` | Replace tables with ModelBrowser component |
| `frontend/src/prototype/layouts/PrototypeLayout.tsx` | Mount `<Toasts />` component |
| `FOR_LATER.md` | Add deferred notification features |

---

## Task 1: Toast Notification Store

**Files:**
- Create: `frontend/src/core/store/notificationStore.ts`

- [ ] **Step 1: Create the notification store**

```typescript
import { create } from "zustand"

export interface AppNotification {
  id: string
  level: "success" | "error" | "info"
  title: string
  message: string
  timestamp: number
  dismissed: boolean
}

type NewNotification = Pick<AppNotification, "level" | "title" | "message">

interface NotificationState {
  notifications: AppNotification[]
  addNotification: (n: NewNotification) => void
  dismissToast: (id: string) => void
}

const MAX_NOTIFICATIONS = 20

export const useNotificationStore = create<NotificationState>((set) => ({
  notifications: [],

  addNotification: (n) =>
    set((state) => ({
      notifications: [
        {
          ...n,
          id: crypto.randomUUID(),
          timestamp: Date.now(),
          dismissed: false,
        },
        ...state.notifications,
      ].slice(0, MAX_NOTIFICATIONS),
    })),

  dismissToast: (id) =>
    set((state) => ({
      notifications: state.notifications.map((n) =>
        n.id === id ? { ...n, dismissed: true } : n,
      ),
    })),
}))
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/core/store/notificationStore.ts
git commit -m "Add toast notification Zustand store"
```

---

## Task 2: Toast Component

**Files:**
- Create: `frontend/src/prototype/components/Toasts.tsx`
- Modify: `frontend/src/prototype/layouts/PrototypeLayout.tsx`

- [ ] **Step 1: Create the Toasts component**

```tsx
import { useEffect, useRef } from "react"
import { useNotificationStore, type AppNotification } from "../../core/store/notificationStore"

const AUTO_DISMISS_MS = 5_000
const MAX_VISIBLE = 3

const levelStyles: Record<AppNotification["level"], string> = {
  success: "border-l-4 border-l-green-400 bg-green-50 text-green-800",
  error: "border-l-4 border-l-red-400 bg-red-50 text-red-800",
  info: "border-l-4 border-l-gray-400 bg-gray-50 text-gray-800",
}

export default function Toasts() {
  const notifications = useNotificationStore((s) => s.notifications)
  const dismissToast = useNotificationStore((s) => s.dismissToast)
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())

  const visible = notifications.filter((n) => !n.dismissed).slice(0, MAX_VISIBLE)

  useEffect(() => {
    for (const n of visible) {
      if (n.level === "error") continue
      if (timers.current.has(n.id)) continue
      const timer = setTimeout(() => {
        dismissToast(n.id)
        timers.current.delete(n.id)
      }, AUTO_DISMISS_MS)
      timers.current.set(n.id, timer)
    }

    return () => {
      for (const timer of timers.current.values()) clearTimeout(timer)
      timers.current.clear()
    }
  })

  if (visible.length === 0) return null

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 w-80">
      {visible.map((n) => (
        <div
          key={n.id}
          onClick={() => dismissToast(n.id)}
          className={`cursor-pointer rounded-lg px-4 py-3 shadow-md transition-opacity ${levelStyles[n.level]}`}
        >
          <p className="text-sm font-medium">{n.title}</p>
          {n.message && <p className="mt-0.5 text-xs opacity-80">{n.message}</p>}
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 2: Mount Toasts in PrototypeLayout**

In `frontend/src/prototype/layouts/PrototypeLayout.tsx`, add import and render:

```typescript
// Add import at top
import Toasts from "../components/Toasts"
```

Add `<Toasts />` just before the closing `</div>` of the root element (after `</main>`):

```tsx
      </main>
      <Toasts />
    </div>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/prototype/components/Toasts.tsx frontend/src/prototype/layouts/PrototypeLayout.tsx
git commit -m "Add toast notification component and mount in layout"
```

---

## Task 3: Replace alert() Calls with Toasts

**Files:**
- Modify: `frontend/src/prototype/pages/UsersPage.tsx`

- [ ] **Step 1: Replace alert() in UsersPage**

In `frontend/src/prototype/pages/UsersPage.tsx`:

Add import:
```typescript
import { useNotificationStore } from "../../core/store/notificationStore"
```

In the `UsersPage` component (line 135+), add store access and replace the two `alert()` calls:

```typescript
export default function UsersPage() {
  const { users, total, isLoading, error, create, update, deactivate, resetPassword } = useUsers()
  const addNotification = useNotificationStore((s) => s.addNotification)

  const handleCreate = async (data: CreateUserRequest) => {
    const res = await create(data)
    addNotification({
      level: "success",
      title: "User created",
      message: `Generated password: ${res.generated_password}`,
    })
  }

  const handleResetPassword = async (userId: string) => {
    const res = await resetPassword(userId)
    addNotification({
      level: "success",
      title: "Password reset",
      message: `New password: ${res.generated_password}`,
    })
  }
```

- [ ] **Step 2: Verify in browser**

Run: `cd frontend && pnpm dev`

Open the Users page, create a user. Verify a toast appears instead of a browser alert.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/prototype/pages/UsersPage.tsx
git commit -m "Replace alert() calls with toast notifications on UsersPage"
```

---

## Task 4: Add FOR_LATER.md Entries for Deferred Notification Features

**Files:**
- Modify: `FOR_LATER.md`

- [ ] **Step 1: Append deferred notification features to FOR_LATER.md**

Add the following section after the last existing entry:

```markdown
---

## Notification Bell & Flyout

**What:** A bell icon in the top-right corner with an unread badge count and a
flyout panel showing persistent notification history. Notifications would persist
across page navigation and show relative timestamps ("5m ago", "2h ago").
The previous prototype (chat-client-02) had this fully implemented with a
Zustand store, NotificationBell, and NotificationFlyout components.

**Why deferred:** The toast-only system is sufficient for the prototype. The bell
and flyout add complexity (read/unread state, flyout positioning, click-outside
dismiss) without validating new patterns. The toast store already supports the
data model needed — adding the bell/flyout is a UI-only extension.

---

## Backend-Driven Notifications

**What:** The backend publishes notification events via WebSocket (e.g. embedding
job completed, consolidation failed). The frontend notification store subscribes
to these events and creates toasts/entries automatically.

**Why deferred:** There are no background jobs yet that would produce
notifications. When the memory consolidation pipeline or other async processes
are added, this becomes relevant.
```

- [ ] **Step 2: Commit**

```bash
git add FOR_LATER.md
git commit -m "Add deferred notification features to FOR_LATER.md"
```

---

## Task 5: Auth Status Backend Endpoint

**Files:**
- Modify: `backend/modules/user/_handlers.py`
- Create: `tests/test_auth_status.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_auth_status.py`:

```python
import pytest
from httpx import AsyncClient


async def test_auth_status_no_admin_exists(client: AsyncClient):
    resp = await client.get("/api/auth/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_setup_complete"] is False


async def test_auth_status_after_setup(client: AsyncClient):
    await client.post(
        "/api/setup",
        json={
            "pin": "change-me-1234",
            "username": "admin",
            "email": "admin@example.com",
            "password": "SecurePass123",
        },
    )
    resp = await client.get("/api/auth/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_setup_complete"] is True


async def test_auth_status_requires_no_auth(client: AsyncClient):
    """Endpoint must be accessible without any auth token."""
    resp = await client.get("/api/auth/status")
    assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/test_auth_status.py -v`

Expected: FAIL — 404 because the endpoint does not exist yet.

- [ ] **Step 3: Implement the endpoint**

In `backend/modules/user/_handlers.py`, add this endpoint after the `_clear_refresh_cookie` function (before the `# --- Setup ---` comment, around line 73):

```python
# --- Auth Status ---


@router.get("/auth/status")
async def auth_status():
    repo = _user_repo()
    master_admin = await repo.find_by_role("master_admin")
    return {"is_setup_complete": master_admin is not None}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/test_auth_status.py -v`

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_auth_status.py backend/modules/user/_handlers.py
git commit -m "Add GET /api/auth/status endpoint for master admin detection"
```

---

## Task 6: Auto-detect Master Admin on LoginPage

**Files:**
- Modify: `frontend/src/core/api/auth.ts`
- Modify: `frontend/src/prototype/pages/LoginPage.tsx`

- [ ] **Step 1: Add status() to auth API**

In `frontend/src/core/api/auth.ts`, add a new method to the `authApi` object:

```typescript
  status: () =>
    apiRequest<{ is_setup_complete: boolean }>("GET", "/api/auth/status", undefined, true),
```

Add it after the `setup` method, before the closing `}`.

- [ ] **Step 2: Update LoginPage to auto-detect setup mode**

Replace the full content of `frontend/src/prototype/pages/LoginPage.tsx`. Key changes:
- Add `useEffect` import
- Change `Mode` type to include `"loading"`
- Default mode is `"loading"` instead of `"login"`
- On mount, fetch `/api/auth/status` and set mode accordingly
- Remove the "First time? Set up master admin" toggle button
- Add a loading spinner state

```tsx
import { useEffect, useState } from "react"
import { Navigate } from "react-router-dom"
import { useAuth } from "../../core/hooks/useAuth"
import { useAuthStore } from "../../core/store/authStore"
import { authApi } from "../../core/api/auth"

type Mode = "loading" | "login" | "setup" | "change-password"

export default function LoginPage() {
  const { login, setup, changePassword, isLoading, error } = useAuth()
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const mustChangePassword = useAuthStore((s) => s.user?.must_change_password)

  const [mode, setMode] = useState<Mode>("loading")
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [email, setEmail] = useState("")
  const [pin, setPin] = useState("")
  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [setupResult, setSetupResult] = useState<string | null>(null)

  useEffect(() => {
    authApi.status()
      .then((data) => setMode(data.is_setup_complete ? "login" : "setup"))
      .catch(() => setMode("login"))
  }, [])

  if (isAuthenticated && !mustChangePassword) {
    return <Navigate to="/dashboard" replace />
  }

  if (isAuthenticated && mustChangePassword && mode !== "change-password") {
    setMode("change-password")
  }

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await login({ username, password })
    } catch {
      // Error is displayed via the hook's error state
    }
  }

  const handleSetup = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      const res = await setup({ pin, username, email, password })
      setSetupResult(`Master admin created: ${res.user.username}`)
    } catch {
      // Error displayed via hook
    }
  }

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await changePassword({ current_password: currentPassword, new_password: newPassword })
    } catch {
      // Error displayed via hook
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50">
      <div className="w-full max-w-sm space-y-6 rounded-lg border border-gray-200 bg-white p-8 shadow-sm">
        <div>
          <h1 className="text-xl font-semibold">Chatsune</h1>
          <p className="text-sm text-gray-400">Prototype</p>
        </div>

        {error && (
          <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        )}

        {setupResult && (
          <div className="rounded border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700">
            {setupResult}
          </div>
        )}

        {mode === "loading" && (
          <div className="flex justify-center py-8">
            <span className="text-sm text-gray-400">Loading...</span>
          </div>
        )}

        {mode === "login" && (
          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700">Username</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                required
              />
            </div>
            <button
              type="submit"
              disabled={isLoading}
              className="w-full rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {isLoading ? "Logging in..." : "Login"}
            </button>
          </form>
        )}

        {mode === "setup" && (
          <form onSubmit={handleSetup} className="space-y-4">
            <p className="text-sm text-blue-700 bg-blue-50 border border-blue-200 rounded px-3 py-2">
              No master admin found. Please create one to get started.
            </p>
            <div>
              <label className="block text-sm font-medium text-gray-700">Setup PIN</label>
              <input
                type="password"
                value={pin}
                onChange={(e) => setPin(e.target.value)}
                className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Username</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                required
              />
            </div>
            <button
              type="submit"
              disabled={isLoading}
              className="w-full rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {isLoading ? "Setting up..." : "Create Master Admin"}
            </button>
          </form>
        )}

        {mode === "change-password" && (
          <form onSubmit={handleChangePassword} className="space-y-4">
            <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2">
              You must change your password before continuing.
            </p>
            <div>
              <label className="block text-sm font-medium text-gray-700">Current Password</label>
              <input
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">New Password</label>
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                required
              />
            </div>
            <button
              type="submit"
              disabled={isLoading}
              className="w-full rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {isLoading ? "Changing..." : "Change Password"}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Verify in browser**

Run: `cd frontend && pnpm dev`

1. Open the login page with a fresh database (no users) — should show setup form automatically with blue info banner.
2. After creating master admin, refresh the page — should show login form.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/core/api/auth.ts frontend/src/prototype/pages/LoginPage.tsx
git commit -m "Auto-detect master admin setup mode on LoginPage"
```

---

## Task 7: System Prompt Backend Endpoints

**Files:**
- Modify: `shared/topics.py`
- Modify: `shared/events/settings.py`
- Modify: `frontend/src/core/types/events.ts`
- Modify: `backend/modules/settings/_handlers.py`
- Create: `tests/test_system_prompt.py`

- [ ] **Step 1: Add topic constant and event class**

In `shared/topics.py`, add after line 18 (`SETTING_DELETED`):

```python
    SETTING_SYSTEM_PROMPT_UPDATED = "setting.system_prompt.updated"
```

In `shared/events/settings.py`, add after the `SettingDeletedEvent` class:

```python
class SettingSystemPromptUpdatedEvent(BaseModel):
    type: str = "setting.system_prompt.updated"
    content: str
    updated_by: str
    timestamp: datetime
```

In `frontend/src/core/types/events.ts`, add to the `Topics` object (before `} as const`):

```typescript
  SETTING_SYSTEM_PROMPT_UPDATED: "setting.system_prompt.updated",
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_system_prompt.py`:

```python
import pytest
from httpx import AsyncClient


async def _setup_admin(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/setup",
        json={
            "pin": "change-me-1234",
            "username": "admin",
            "email": "admin@example.com",
            "password": "SecurePass123",
        },
    )
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_get_system_prompt_default_empty(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.get("/api/settings/system-prompt", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == ""


async def test_set_and_get_system_prompt(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.put(
        "/api/settings/system-prompt",
        json={"content": "Be helpful and harmless."},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == "Be helpful and harmless."
    assert data["updated_by"] is not None

    resp = await client.get("/api/settings/system-prompt", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["content"] == "Be helpful and harmless."


async def test_update_system_prompt_overwrites(client: AsyncClient):
    token = await _setup_admin(client)
    await client.put(
        "/api/settings/system-prompt",
        json={"content": "Version 1"},
        headers=_auth(token),
    )
    resp = await client.put(
        "/api/settings/system-prompt",
        json={"content": "Version 2"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "Version 2"


async def test_system_prompt_requires_admin(client: AsyncClient):
    admin_token = await _setup_admin(client)
    create_resp = await client.post(
        "/api/admin/users",
        json={
            "username": "regular",
            "display_name": "Regular User",
            "email": "user@example.com",
        },
        headers=_auth(admin_token),
    )
    generated_pw = create_resp.json()["generated_password"]
    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "regular", "password": generated_pw},
    )
    user_token = login_resp.json()["access_token"]

    resp = await client.get("/api/settings/system-prompt", headers=_auth(user_token))
    assert resp.status_code == 403

    resp = await client.put(
        "/api/settings/system-prompt",
        json={"content": "nope"},
        headers=_auth(user_token),
    )
    assert resp.status_code == 403
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/test_system_prompt.py -v`

Expected: FAIL — 404 or 405 because the endpoints do not exist yet.

- [ ] **Step 4: Implement the system prompt endpoints**

In `backend/modules/settings/_handlers.py`, add these imports at the top (extend existing imports):

```python
from shared.events.settings import SettingDeletedEvent, SettingSystemPromptUpdatedEvent, SettingUpdatedEvent
```

Add the following two endpoints at the end of the file (after the `delete_setting` function):

```python
SYSTEM_PROMPT_KEY = "system_prompt"


@router.get("/system-prompt")
async def get_system_prompt(user: dict = Depends(require_admin)):
    repo = _repo()
    doc = await repo.find(SYSTEM_PROMPT_KEY)
    if not doc:
        return {"content": "", "updated_at": None, "updated_by": None}
    return {
        "content": doc["value"],
        "updated_at": doc["updated_at"],
        "updated_by": doc["updated_by"],
    }


@router.put("/system-prompt", status_code=200)
async def set_system_prompt(
    body: dict,
    user: dict = Depends(require_admin),
    event_bus: EventBus = Depends(get_event_bus),
):
    content = body.get("content", "")
    repo = _repo()
    doc = await repo.upsert(SYSTEM_PROMPT_KEY, content, user["sub"])

    await event_bus.publish(
        Topics.SETTING_SYSTEM_PROMPT_UPDATED,
        SettingSystemPromptUpdatedEvent(
            content=content,
            updated_by=user["sub"],
            timestamp=datetime.now(timezone.utc),
        ),
    )

    return {
        "content": doc["value"],
        "updated_at": doc["updated_at"],
        "updated_by": doc["updated_by"],
    }
```

Also add the missing `Topics` import if not already present (it should already be imported on line 11).

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/test_system_prompt.py -v`

Expected: all 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add shared/topics.py shared/events/settings.py frontend/src/core/types/events.ts backend/modules/settings/_handlers.py tests/test_system_prompt.py
git commit -m "Add system prompt GET/PUT endpoints with dedicated event"
```

---

## Task 8: Admin System Prompt Tab (Frontend)

**Files:**
- Modify: `frontend/src/core/api/settings.ts`
- Modify: `frontend/src/prototype/pages/AdminPage.tsx`

- [ ] **Step 1: Add system prompt API methods**

In `frontend/src/core/api/settings.ts`, add to the `settingsApi` object:

```typescript
  getSystemPrompt: () =>
    api.get<{ content: string; updated_at: string | null; updated_by: string | null }>("/api/settings/system-prompt"),

  setSystemPrompt: (content: string) =>
    api.put<{ content: string; updated_at: string; updated_by: string }>("/api/settings/system-prompt", { content }),
```

- [ ] **Step 2: Add System Prompt tab to AdminPage**

In `frontend/src/prototype/pages/AdminPage.tsx`:

Add imports at top:
```typescript
import { useEffect } from "react"
import { settingsApi } from "../../core/api/settings"
import { useNotificationStore } from "../../core/store/notificationStore"
```

Change the `Tab` type to include the new tab:
```typescript
type Tab = "system-prompt" | "settings" | "curation"
```

Add the `SystemPromptTab` component before the `AdminPage` export (after `CurationTab`):

```tsx
function SystemPromptTab() {
  const [content, setContent] = useState("")
  const [savedContent, setSavedContent] = useState("")
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const addNotification = useNotificationStore((s) => s.addNotification)

  useEffect(() => {
    settingsApi.getSystemPrompt().then((data) => {
      setContent(data.content)
      setSavedContent(data.content)
      setIsLoading(false)
    }).catch(() => setIsLoading(false))
  }, [])

  const isDirty = content !== savedContent

  const handleSave = async () => {
    setIsSaving(true)
    try {
      await settingsApi.setSystemPrompt(content)
      setSavedContent(content)
      addNotification({ level: "success", title: "System prompt saved", message: "" })
    } catch {
      addNotification({ level: "error", title: "Failed to save system prompt", message: "" })
    } finally {
      setIsSaving(false)
    }
  }

  if (isLoading) return <p className="text-sm text-gray-400">Loading...</p>

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500">
        This prompt is prepended to every inference request, regardless of persona.
        Use it to enforce safety rules and operational boundaries.
      </p>
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        maxLength={4000}
        rows={12}
        className="w-full rounded border border-gray-300 px-3 py-2 text-sm font-mono focus:border-blue-500 focus:outline-none"
        placeholder="Enter the global system prompt..."
      />
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-400">{content.length} / 4000</span>
        <button
          onClick={handleSave}
          disabled={!isDirty || isSaving}
          className="rounded bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {isSaving ? "Saving..." : "Save"}
        </button>
      </div>
    </div>
  )
}
```

Update the `AdminPage` component to include the new tab. Change default tab to `"system-prompt"` and add the tab button + conditional render:

```tsx
export default function AdminPage() {
  const [tab, setTab] = useState<Tab>("system-prompt")

  const tabClass = (t: Tab) =>
    `rounded-t px-4 py-2 text-sm ${tab === t ? "bg-white border-b-2 border-blue-600 font-medium" : "text-gray-500 hover:text-gray-700"}`

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Admin</h2>
      <div className="flex gap-1 border-b border-gray-200">
        <button onClick={() => setTab("system-prompt")} className={tabClass("system-prompt")}>System Prompt</button>
        <button onClick={() => setTab("settings")} className={tabClass("settings")}>Settings</button>
        <button onClick={() => setTab("curation")} className={tabClass("curation")}>Model Curation</button>
      </div>
      {tab === "system-prompt" && <SystemPromptTab />}
      {tab === "settings" && <SettingsTab />}
      {tab === "curation" && <CurationTab />}
    </div>
  )
}
```

- [ ] **Step 3: Verify in browser**

Open Admin page. Verify:
1. "System Prompt" tab is shown first
2. Textarea loads (initially empty)
3. Type text → Save button enables
4. Click Save → toast notification appears
5. Refresh page → saved content persists

- [ ] **Step 4: Commit**

```bash
git add frontend/src/core/api/settings.ts frontend/src/prototype/pages/AdminPage.tsx
git commit -m "Add System Prompt tab to AdminPage"
```

---

## Task 9: Admin Credential Status Backend Endpoint

**Files:**
- Modify: `backend/modules/llm/_credentials.py`
- Modify: `backend/modules/llm/_handlers.py`
- Create: `tests/test_admin_credential_status.py`

- [ ] **Step 1: Add list_all() to CredentialRepository**

In `backend/modules/llm/_credentials.py`, add this method after `list_for_user` (after line 66):

```python
    async def list_all(self) -> list[dict]:
        """List all credentials across all users. Admin use only."""
        cursor = self._collection.find({}, {"user_id": 1, "provider_id": 1, "_id": 0})
        return await cursor.to_list(length=10000)
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_admin_credential_status.py`:

```python
import pytest
from httpx import AsyncClient


async def _setup_admin(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/setup",
        json={
            "pin": "change-me-1234",
            "username": "admin",
            "email": "admin@example.com",
            "password": "SecurePass123",
        },
    )
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_credential_status_empty(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.get("/api/llm/admin/credential-status", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == []


async def test_credential_status_after_setting_key(client: AsyncClient):
    token = await _setup_admin(client)
    await client.put(
        "/api/llm/providers/ollama_cloud/key",
        json={"api_key": "test-key-123"},
        headers=_auth(token),
    )
    resp = await client.get("/api/llm/admin/credential-status", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["providers"][0]["provider_id"] == "ollama_cloud"
    assert data[0]["providers"][0]["is_configured"] is True


async def test_credential_status_requires_admin(client: AsyncClient):
    admin_token = await _setup_admin(client)
    create_resp = await client.post(
        "/api/admin/users",
        json={
            "username": "regular",
            "display_name": "Regular User",
            "email": "user@example.com",
        },
        headers=_auth(admin_token),
    )
    generated_pw = create_resp.json()["generated_password"]
    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "regular", "password": generated_pw},
    )
    user_token = login_resp.json()["access_token"]

    resp = await client.get("/api/llm/admin/credential-status", headers=_auth(user_token))
    assert resp.status_code == 403
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/test_admin_credential_status.py -v`

Expected: FAIL — 404 because the endpoint does not exist yet.

- [ ] **Step 4: Implement the endpoint**

In `backend/modules/llm/_handlers.py`, add a new import at the top (extend existing imports from `backend.dependencies`):

```python
from backend.dependencies import require_active_session, require_admin
```

Then add this endpoint at the end of the file (after `delete_user_model_config`):

```python
@router.get("/admin/credential-status")
async def admin_credential_status(user: dict = Depends(require_admin)):
    repo = _credential_repo()
    all_creds = await repo.list_all()

    by_user: dict[str, list[dict]] = {}
    for cred in all_creds:
        uid = cred["user_id"]
        if uid not in by_user:
            by_user[uid] = []
        by_user[uid].append({
            "provider_id": cred["provider_id"],
            "is_configured": True,
        })

    return [
        {"user_id": uid, "providers": providers}
        for uid, providers in by_user.items()
    ]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/test_admin_credential_status.py -v`

Expected: all 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_credentials.py backend/modules/llm/_handlers.py tests/test_admin_credential_status.py
git commit -m "Add GET /api/llm/admin/credential-status endpoint"
```

---

## Task 10: API Key Status Badges on UsersPage

**Files:**
- Modify: `frontend/src/core/api/llm.ts`
- Modify: `frontend/src/prototype/pages/UsersPage.tsx`

- [ ] **Step 1: Add admin credential status API method**

First read the current `frontend/src/core/api/llm.ts` to see the existing pattern, then add:

```typescript
  adminCredentialStatus: () =>
    api.get<{ user_id: string; providers: { provider_id: string; is_configured: boolean }[] }[]>(
      "/api/llm/admin/credential-status",
    ),
```

Add this to the existing `llmApi` object in the file.

- [ ] **Step 2: Add credential status to UsersPage**

In `frontend/src/prototype/pages/UsersPage.tsx`:

Add imports:
```typescript
import { useEffect } from "react"
import { llmApi } from "../../core/api/llm"
```

In the `UsersPage` component, add state and fetch for credential status:

```typescript
export default function UsersPage() {
  const { users, total, isLoading, error, create, update, deactivate, resetPassword } = useUsers()
  const addNotification = useNotificationStore((s) => s.addNotification)
  const [credentialStatus, setCredentialStatus] = useState<Map<string, string[]>>(new Map())

  useEffect(() => {
    llmApi.adminCredentialStatus()
      .then((data) => {
        const map = new Map<string, string[]>()
        for (const entry of data) {
          map.set(entry.user_id, entry.providers.map((p) => p.provider_id))
        }
        setCredentialStatus(map)
      })
      .catch(() => {})
  }, [])
```

Add a new table column header "API Keys" after "Status":

```tsx
<th className="px-4 py-2 text-left text-xs font-medium text-gray-500">API Keys</th>
```

Update the `colSpan` in both loading/empty rows from `6` to `7`.

Pass `credentialStatus` to `UserRow`:

```tsx
<UserRow key={u.id} user={u} onUpdate={update} onDeactivate={deactivate} onResetPassword={handleResetPassword} providerIds={credentialStatus.get(u.id) ?? []} />
```

Update the `UserRow` component to accept and display `providerIds`:

Add `providerIds: string[]` to the props type:

```typescript
function UserRow({
  user,
  onUpdate,
  onDeactivate,
  onResetPassword,
  providerIds,
}: {
  user: UserDto
  onUpdate: (id: string, data: UpdateUserRequest) => Promise<unknown>
  onDeactivate: (id: string) => Promise<unknown>
  onResetPassword: (id: string) => Promise<void>
  providerIds: string[]
}) {
```

Add a new `<td>` after the Status column in the row JSX:

```tsx
      <td className="px-4 py-2 text-sm">
        {providerIds.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {providerIds.map((pid) => (
              <span key={pid} className="rounded bg-green-100 px-1.5 py-0.5 text-xs text-green-700">{pid}</span>
            ))}
          </div>
        ) : (
          <span className="text-xs text-gray-300">No keys</span>
        )}
      </td>
```

- [ ] **Step 3: Verify in browser**

Open Users page as admin. Verify:
1. New "API Keys" column is visible
2. Users with configured providers show green badges
3. Users without keys show "No keys" hint

- [ ] **Step 4: Commit**

```bash
git add frontend/src/core/api/llm.ts frontend/src/prototype/pages/UsersPage.tsx
git commit -m "Add API key status badges to admin UsersPage"
```

---

## Task 11: ModelBrowser Component

**Files:**
- Create: `frontend/src/prototype/components/ModelBrowser.tsx`

- [ ] **Step 1: Create the ModelBrowser component**

```tsx
import { useMemo, useState } from "react"
import type { ModelMetaDto, UserModelConfigDto } from "../../core/types/llm"

type SortField = "name" | "context"
type SortDir = "asc" | "desc"

interface ModelBrowserProps {
  models: ModelMetaDto[]
  userConfigs?: UserModelConfigDto[]
  onSelect?: (model: ModelMetaDto) => void
  onToggleFavourite?: (model: ModelMetaDto) => void
  onToggleHidden?: (model: ModelMetaDto) => void
  selectedModelId?: string | null
  showConfigActions?: boolean
}

export default function ModelBrowser({
  models,
  userConfigs = [],
  onSelect,
  onToggleFavourite,
  onToggleHidden,
  selectedModelId,
  showConfigActions = true,
}: ModelBrowserProps) {
  const [search, setSearch] = useState("")
  const [providerFilter, setProviderFilter] = useState<string | null>(null)
  const [capFilters, setCapFilters] = useState<Set<string>>(new Set())
  const [showFavourites, setShowFavourites] = useState(false)
  const [sortField, setSortField] = useState<SortField | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>("asc")

  const configMap = useMemo(
    () => new Map(userConfigs.map((c) => [c.model_unique_id, c])),
    [userConfigs],
  )

  const providers = useMemo(
    () => [...new Set(models.map((m) => m.provider_id))],
    [models],
  )

  const toggleCap = (cap: string) => {
    setCapFilters((prev) => {
      const next = new Set(prev)
      if (next.has(cap)) next.delete(cap)
      else next.add(cap)
      return next
    })
  }

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      if (sortDir === "asc") setSortDir("desc")
      else { setSortField(null); setSortDir("asc") }
    } else {
      setSortField(field)
      setSortDir("asc")
    }
  }

  const filtered = useMemo(() => {
    let result = models

    if (search) {
      const terms = search.toLowerCase().split(/\s+/)
      result = result.filter((m) => {
        const haystack = `${m.display_name} ${m.model_id}`.toLowerCase()
        return terms.every((t) => haystack.includes(t))
      })
    }

    if (providerFilter) {
      result = result.filter((m) => m.provider_id === providerFilter)
    }

    if (capFilters.has("tools")) result = result.filter((m) => m.supports_tool_calls)
    if (capFilters.has("vision")) result = result.filter((m) => m.supports_vision)
    if (capFilters.has("reasoning")) result = result.filter((m) => m.supports_reasoning)

    if (showFavourites) {
      result = result.filter((m) => configMap.get(m.unique_id)?.is_favourite)
    }

    if (sortField) {
      result = [...result].sort((a, b) => {
        let cmp = 0
        if (sortField === "name") cmp = a.display_name.localeCompare(b.display_name)
        if (sortField === "context") cmp = a.context_window - b.context_window
        return sortDir === "desc" ? -cmp : cmp
      })
    }

    return result
  }, [models, search, providerFilter, capFilters, showFavourites, sortField, sortDir, configMap])

  const sortIndicator = (field: SortField) => {
    if (sortField !== field) return ""
    return sortDir === "asc" ? " \u2191" : " \u2193"
  }

  const capBtnClass = (cap: string, activeColour: string) =>
    `rounded px-2 py-1 text-xs font-mono ${capFilters.has(cap) ? activeColour : "bg-gray-100 text-gray-400"}`

  return (
    <div className="space-y-3">
      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="text"
          placeholder="Search models..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
        />

        {providers.length > 1 && (
          <>
            {providers.map((pid) => (
              <button
                key={pid}
                onClick={() => setProviderFilter(providerFilter === pid ? null : pid)}
                className={`rounded px-2 py-1 text-xs ${providerFilter === pid ? "bg-blue-600 text-white" : "bg-gray-100 hover:bg-gray-200"}`}
              >
                {pid}
              </button>
            ))}
          </>
        )}

        <button onClick={() => toggleCap("tools")} className={capBtnClass("tools", "bg-green-100 text-green-700")}>T</button>
        <button onClick={() => toggleCap("vision")} className={capBtnClass("vision", "bg-blue-100 text-blue-700")}>V</button>
        <button onClick={() => toggleCap("reasoning")} className={capBtnClass("reasoning", "bg-yellow-100 text-yellow-700")}>R</button>

        {showConfigActions && (
          <button
            onClick={() => setShowFavourites(!showFavourites)}
            className={`rounded px-2 py-1 text-xs ${showFavourites ? "bg-yellow-100 text-yellow-700" : "bg-gray-100 text-gray-400"}`}
          >
            Favourites
          </button>
        )}

        <span className="text-xs text-gray-400 ml-auto">{filtered.length} models</span>
      </div>

      {/* Table */}
      <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-200 bg-gray-50">
              <th
                onClick={() => handleSort("name")}
                className="cursor-pointer px-4 py-2 text-left text-xs font-medium text-gray-500 hover:text-gray-700"
              >
                Model{sortIndicator("name")}
              </th>
              <th
                onClick={() => handleSort("context")}
                className="cursor-pointer px-4 py-2 text-left text-xs font-medium text-gray-500 hover:text-gray-700 w-24"
              >
                Context{sortIndicator("context")}
              </th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Capabilities</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Rating</th>
              {showConfigActions && (
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Actions</th>
              )}
            </tr>
          </thead>
          <tbody>
            {filtered.map((m) => {
              const config = configMap.get(m.unique_id)
              const isSelected = m.unique_id === selectedModelId
              return (
                <tr
                  key={m.unique_id}
                  onClick={() => onSelect?.(m)}
                  className={`border-b border-gray-100 ${onSelect ? "cursor-pointer hover:bg-gray-50" : ""} ${isSelected ? "bg-blue-50 border-l-2 border-l-blue-500" : ""}`}
                >
                  <td className="px-4 py-2">
                    <div className="text-sm font-medium">{m.display_name}</div>
                    <div className="text-xs text-gray-400">{m.model_id}</div>
                  </td>
                  <td className="px-4 py-2 text-sm">{m.context_window > 0 ? `${(m.context_window / 1024).toFixed(0)}k` : "-"}</td>
                  <td className="px-4 py-2 text-sm space-x-1">
                    {m.supports_reasoning && <span className="rounded bg-yellow-50 px-1.5 py-0.5 text-xs text-yellow-600">R</span>}
                    {m.supports_vision && <span className="rounded bg-blue-50 px-1.5 py-0.5 text-xs text-blue-600">V</span>}
                    {m.supports_tool_calls && <span className="rounded bg-green-50 px-1.5 py-0.5 text-xs text-green-600">T</span>}
                  </td>
                  <td className="px-4 py-2 text-sm">
                    {m.curation ? (
                      <span className={`rounded px-2 py-0.5 text-xs ${
                        m.curation.overall_rating === "recommended" ? "bg-green-100 text-green-700" :
                        m.curation.overall_rating === "not_recommended" ? "bg-red-100 text-red-700" :
                        "bg-gray-100 text-gray-600"
                      }`}>
                        {m.curation.overall_rating}
                      </span>
                    ) : (
                      <span className="text-xs text-gray-400">uncurated</span>
                    )}
                  </td>
                  {showConfigActions && (
                    <td className="px-4 py-2 text-sm space-x-1">
                      <button
                        onClick={(e) => { e.stopPropagation(); onToggleFavourite?.(m) }}
                        className={`rounded px-2 py-1 text-xs ${config?.is_favourite ? "bg-yellow-100 text-yellow-700" : "bg-gray-100 text-gray-500"}`}
                      >
                        {config?.is_favourite ? "Favourited" : "Favourite"}
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); onToggleHidden?.(m) }}
                        className={`rounded px-2 py-1 text-xs ${config?.is_hidden ? "bg-gray-300 text-gray-700" : "bg-gray-100 text-gray-500"}`}
                      >
                        {config?.is_hidden ? "Hidden" : "Hide"}
                      </button>
                    </td>
                  )}
                </tr>
              )
            })}
            {filtered.length === 0 && (
              <tr><td colSpan={showConfigActions ? 5 : 4} className="px-4 py-8 text-center text-sm text-gray-400">No models match filters</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/prototype/components/ModelBrowser.tsx
git commit -m "Add ModelBrowser component with filters and sortable table"
```

---

## Task 12: Integrate ModelBrowser into LlmPage

**Files:**
- Modify: `frontend/src/prototype/pages/LlmPage.tsx`

- [ ] **Step 1: Replace Models Tab and Config Tab with ModelBrowser**

In `frontend/src/prototype/pages/LlmPage.tsx`:

Add import at top:
```typescript
import ModelBrowser from "../components/ModelBrowser"
```

Replace the `ModelsTab` function (lines 80-154) with:

```tsx
function ModelsTab() {
  const { providers, models, fetchModels } = useLlm()
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null)

  const handleSelectProvider = (providerId: string) => {
    setSelectedProvider(providerId)
    if (!models.has(providerId)) {
      fetchModels(providerId)
    }
  }

  const providerModels: ModelMetaDto[] = selectedProvider ? (models.get(selectedProvider) ?? []) : []

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        {providers.map((p) => (
          <button
            key={p.provider_id}
            onClick={() => handleSelectProvider(p.provider_id)}
            className={`rounded px-3 py-1.5 text-sm ${selectedProvider === p.provider_id ? "bg-blue-600 text-white" : "bg-gray-100 hover:bg-gray-200"}`}
          >
            {p.display_name}
          </button>
        ))}
      </div>

      {selectedProvider && (
        <ModelBrowser models={providerModels} showConfigActions={false} />
      )}
    </div>
  )
}
```

Replace the `UserConfigTab` function (lines 157-229) with:

```tsx
function UserConfigTab() {
  const { userConfigs, providers, models, fetchModels, setUserConfig } = useLlm()
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null)

  const handleSelectProvider = (providerId: string) => {
    setSelectedProvider(providerId)
    if (!models.has(providerId)) {
      fetchModels(providerId)
    }
  }

  const providerModels = selectedProvider ? (models.get(selectedProvider) ?? []) : []

  const handleToggleFavourite = async (model: ModelMetaDto) => {
    const config = userConfigs.find((c) => c.model_unique_id === model.unique_id)
    const [providerId, ...slugParts] = model.unique_id.split(":")
    const modelSlug = slugParts.join(":")
    await setUserConfig(providerId, modelSlug, { is_favourite: !(config?.is_favourite ?? false) })
  }

  const handleToggleHidden = async (model: ModelMetaDto) => {
    const config = userConfigs.find((c) => c.model_unique_id === model.unique_id)
    const [providerId, ...slugParts] = model.unique_id.split(":")
    const modelSlug = slugParts.join(":")
    await setUserConfig(providerId, modelSlug, { is_hidden: !(config?.is_hidden ?? false) })
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        {providers.map((p) => (
          <button
            key={p.provider_id}
            onClick={() => handleSelectProvider(p.provider_id)}
            className={`rounded px-3 py-1.5 text-sm ${selectedProvider === p.provider_id ? "bg-blue-600 text-white" : "bg-gray-100 hover:bg-gray-200"}`}
          >
            {p.display_name}
          </button>
        ))}
      </div>

      {selectedProvider && (
        <ModelBrowser
          models={providerModels}
          userConfigs={userConfigs}
          onToggleFavourite={handleToggleFavourite}
          onToggleHidden={handleToggleHidden}
          showConfigActions={true}
        />
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify in browser**

Open Models page. Verify:
1. Models Tab: search, capability filters (T/V/R), sorting work
2. My Config Tab: favourite/hide buttons work, favourites filter works

- [ ] **Step 3: Commit**

```bash
git add frontend/src/prototype/pages/LlmPage.tsx
git commit -m "Replace LlmPage tables with ModelBrowser component"
```

---

## Task 13: Run Full Test Suite

- [ ] **Step 1: Run all backend tests**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/ -v`

Expected: all tests PASS, including the 3 new test files.

- [ ] **Step 2: Run frontend type check**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`

Expected: no type errors.

- [ ] **Step 3: Commit any fixes if needed**

If any tests fail or type errors are found, fix them and commit.

---

## Task 14: Merge to Master

- [ ] **Step 1: Verify clean git status**

Run: `git status`

All changes should be committed. No uncommitted files.

- [ ] **Step 2: Already on master**

Per CLAUDE.md, we work on master and merge after implementation. Since we are on master already, this is just a verification step.

# Auth and WebSocket Resilience — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the frontend reliably detect when the backend is gone and never silently log the user out without a toast and a redirect to `/login`.

**Architecture:** A backend-emitted marker header (`X-Chatsune-Backend`) lets the frontend distinguish authentic backend responses from proxy fall-throughs. An always-on health monitor and a header-aware API client convert that signal into either the "backend unavailable" screen or a centralised, user-facing logout. A WebSocket pong timeout closes dead-but-not-closed sockets so the reconnect loop reflects reality.

**Tech Stack:** Backend FastAPI middleware (Starlette `BaseHTTPMiddleware`), pytest. Frontend TypeScript / React, Zustand stores, react-router-dom v6.

---

## File Structure

### Backend (new + modified)

- **Create** `backend/_middleware.py` — single-file middleware module. Contains `BackendMarkerMiddleware`. Single responsibility: tag every `/api/*` response with the marker header.
- **Modify** `backend/main.py:597-628` — register the middleware once after the FastAPI app is created and before/alongside CORS.
- **Create** `backend/tests/test_backend_marker_middleware.py` — pytest verifying the header appears on `/api/health` and is absent on non-`/api` paths.

### Frontend (new + modified)

- **Create** `frontend/src/core/auth/logoutCoordinator.ts` — exports `logout()`, `forceLogout(reason, message)`, `setNavigate(navigate)`. Holds the navigate ref so the WS layer and API client (both non-React contexts) can route the user.
- **Create** `frontend/src/core/health/healthMonitor.ts` — exports `startHealthMonitor()`, `stopHealthMonitor()`. Polls `/api/health`, validates status 200 + marker header, drives `eventStore.backendAvailable`.
- **Modify** `frontend/src/core/api/client.ts` — adds `BackendUnavailableError`, header check on every response, header-aware refresh routing.
- **Modify** `frontend/src/core/websocket/connection.ts` — adds pong timeout, routes 4001/4003 close codes through `forceLogout` instead of inline clearing.
- **Modify** `frontend/src/core/hooks/useAuth.ts` — logout button calls `coordinator.logout()`.
- **Modify** `frontend/src/app/pages/BackendUnavailablePage.tsx` — strip internal poll, become pure presentation.
- **Modify** `frontend/src/App.tsx` — start the health monitor, wire `setNavigate` from `useNavigate`.

### Manual verification scenarios

Six scenarios in the spec at `devdocs/specs/2026-05-01-auth-ws-resilience-design.md` § Manual verification. Run after Task 5 against the deployed backend.

---

## Task 1: Backend marker header middleware

**Files:**
- Create: `backend/_middleware.py`
- Modify: `backend/main.py:597-604`
- Test: `backend/tests/test_backend_marker_middleware.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_backend_marker_middleware.py`:

```python
"""Tests for BackendMarkerMiddleware: every /api/* response carries
X-Chatsune-Backend so the frontend can distinguish authentic backend
responses from proxy fall-throughs."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend._middleware import BackendMarkerMiddleware


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(BackendMarkerMiddleware)

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/error")
    async def error():
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="bad")

    @app.get("/non-api")
    async def non_api():
        return {"ok": True}

    return app


def test_marker_header_present_on_api_success():
    client = TestClient(_app())
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.headers.get("X-Chatsune-Backend") == "1"


def test_marker_header_present_on_api_error():
    client = TestClient(_app())
    response = client.get("/api/error")
    assert response.status_code == 400
    assert response.headers.get("X-Chatsune-Backend") == "1"


def test_marker_header_absent_on_non_api_path():
    client = TestClient(_app())
    response = client.get("/non-api")
    assert response.status_code == 200
    assert "X-Chatsune-Backend" not in response.headers
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/chris/workspace/chatsune
uv run pytest backend/tests/test_backend_marker_middleware.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` for `backend._middleware`.

- [ ] **Step 3: Implement the middleware**

Create `backend/_middleware.py`:

```python
"""HTTP middleware shared by the FastAPI app."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Marker header tagged on every backend-originated response under /api.
# The frontend uses this to distinguish authentic backend responses from
# proxy fall-throughs (e.g. Traefik routing /api/* to the frontend
# catch-all when the backend container is stopped).
BACKEND_MARKER_HEADER = "X-Chatsune-Backend"
BACKEND_MARKER_VALUE = "1"


class BackendMarkerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        if request.url.path.startswith("/api"):
            response.headers[BACKEND_MARKER_HEADER] = BACKEND_MARKER_VALUE
        return response
```

- [ ] **Step 4: Register the middleware in main.py**

In `backend/main.py`, locate the section after `app = FastAPI(...)` (around line 597). Add the import at the top of the file alongside the other backend imports, and register the middleware *before* `CORSMiddleware`. Order matters: middleware added later runs first on the request side and last on the response side, and we want our marker on every response, so we add it first (it will run last on responses).

Add at the top of `backend/main.py` (with the other `from backend...` imports):

```python
from backend._middleware import BackendMarkerMiddleware
```

Replace the existing block at line 598-604:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

with:

```python
app.add_middleware(BackendMarkerMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd /home/chris/workspace/chatsune
uv run pytest backend/tests/test_backend_marker_middleware.py -v
```

Expected: 3 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/_middleware.py backend/main.py backend/tests/test_backend_marker_middleware.py
git commit -m "Add backend marker header middleware for /api routes"
```

---

## Task 2: Frontend logout coordinator

**Files:**
- Create: `frontend/src/core/auth/logoutCoordinator.ts`
- Modify: `frontend/src/App.tsx` (wire `setNavigate`)

- [ ] **Step 1: Create the coordinator module**

Create `frontend/src/core/auth/logoutCoordinator.ts`:

```typescript
import { authApi } from "../api/auth"
import { disconnect } from "../websocket/connection"
import { useAuthStore } from "../store/authStore"
import { useNotificationStore } from "../store/notificationStore"

type ForceLogoutReason =
  | "session_expired"
  | "must_change_password"
  | "admin_revoked"

// Holds a navigate function set up by App.tsx during mount. Required
// because forceLogout/logout are called from non-React contexts
// (WebSocket close handlers, API client refresh failures) where
// useNavigate() is not available.
let _navigate: ((path: string) => void) | null = null

export function setNavigate(navigate: (path: string) => void): void {
  _navigate = navigate
}

async function _doLogout(): Promise<void> {
  try {
    await authApi.logout()
  } catch {
    // Best effort; if the server logout call fails we still clean up
    // locally. The user is leaving the session either way.
  }
  disconnect()
  useAuthStore.getState().clear()
  if (_navigate) _navigate("/login")
}

// User pressed the logout button. Quiet, no toast.
export async function logout(): Promise<void> {
  await _doLogout()
}

// System-initiated logout. Always shows a toast on /login so the user
// understands why they were sent here.
export async function forceLogout(
  reason: ForceLogoutReason,
  userMessage: string,
): Promise<void> {
  await _doLogout()
  useNotificationStore.getState().addNotification({
    level: reason === "admin_revoked" ? "warning" : "info",
    title: "Abgemeldet",
    message: userMessage,
  })
}
```

- [ ] **Step 2: Wire `setNavigate` in App.tsx**

In `frontend/src/App.tsx`, import and use `useNavigate` from `react-router-dom` (already imported as part of `Routes`). Add an effect that pushes the navigate function into the coordinator after mount.

Add to the imports at the top of `App.tsx`:

```tsx
import { useNavigate } from "react-router-dom"
import { setNavigate } from "./core/auth/logoutCoordinator"
```

Inside the `App` component (or wherever the existing effects live), add:

```tsx
const navigate = useNavigate()
useEffect(() => {
  setNavigate(navigate)
}, [navigate])
```

If `App` is not currently inside a `<BrowserRouter>` (i.e. `useNavigate` would throw), this hook must be added to the topmost component that *is* inside the router. Inspect the structure: `useNavigate` only works inside the router context. If `App` itself is the router root, move this effect into a small inner component that lives inside `<Routes>` or the immediate child of `<BrowserRouter>`.

- [ ] **Step 3: Build and verify it compiles**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm run build
```

Expected: clean build, no TypeScript errors. If the import path for `authApi` does not exist as `../api/auth`, adjust to the actual path (`./auth` or whichever module exports `authApi`). The conventional location based on the codebase is `frontend/src/core/api/auth.ts`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/core/auth/logoutCoordinator.ts frontend/src/App.tsx
git commit -m "Add centralised logout coordinator with navigate ref"
```

---

## Task 3: API client header check

**Files:**
- Modify: `frontend/src/core/api/client.ts` (full rewrite of the request flow; preserve `configureClient`, `apiUrl`, `currentAccessToken`, and the `api` shorthand object)

- [ ] **Step 1: Add the new error class and header constant**

Open `frontend/src/core/api/client.ts`. At the top of the file, after the `type HttpMethod` line, add:

```typescript
const BACKEND_MARKER_HEADER = "X-Chatsune-Backend"

export class BackendUnavailableError extends Error {
  constructor(reason: string) {
    super(`Backend unavailable: ${reason}`)
    this.name = "BackendUnavailableError"
  }
}
```

- [ ] **Step 2: Replace `apiRequest` with the header-aware version**

Replace the body of `apiRequest` (currently lines 62-127) with:

```typescript
export async function apiRequest<T>(
  method: HttpMethod,
  path: string,
  body?: unknown,
  skipAuth = false,
): Promise<T> {
  const headers: Record<string, string> = {}

  if (body !== undefined) {
    headers["Content-Type"] = "application/json"
  }

  if (!skipAuth) {
    const token = getAccessToken()
    if (token) {
      headers["Authorization"] = `Bearer ${token}`
    }
  }

  let res: Response
  try {
    res = await fetch(apiUrl(path), {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      credentials: "include",
    })
  } catch (err) {
    if (isNetworkError(err)) {
      onBackendUnavailable()
      throw new BackendUnavailableError("network error")
    }
    throw err
  }

  // If the response did not come from our backend (proxy fall-through,
  // frontend nginx, browser cache, etc.), the marker header is absent.
  // Treat this as "backend unreachable", not as an authoritative result.
  if (!res.headers.has(BACKEND_MARKER_HEADER)) {
    onBackendUnavailable()
    throw new BackendUnavailableError(`no marker header (status ${res.status})`)
  }

  if (res.status === 401 && !skipAuth) {
    const refreshed = await refreshToken()
    if (refreshed === "ok") {
      const token = getAccessToken()
      if (token) {
        headers["Authorization"] = `Bearer ${token}`
      }
      res = await fetch(apiUrl(path), {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
        credentials: "include",
      })
      if (!res.headers.has(BACKEND_MARKER_HEADER)) {
        onBackendUnavailable()
        throw new BackendUnavailableError("retry response missing marker")
      }
    } else if (refreshed === "backend_unavailable") {
      onBackendUnavailable()
      throw new BackendUnavailableError("refresh failed: backend unavailable")
    } else {
      // refreshed === "auth_failed": the backend authoritatively rejected
      // the refresh. The user's session is over.
      onAuthFailure()
      throw new ApiError(401, "Authentication failed")
    }
  }

  if (!res.ok) {
    const errorBody = await res.json().catch(() => null)
    throw new ApiError(res.status, errorBody?.detail ?? res.statusText, errorBody)
  }

  if (res.status === 204) return undefined as T

  return res.json() as Promise<T>
}
```

- [ ] **Step 3: Replace `refreshToken` with the header-aware version (and export it)**

Replace the existing `refreshToken` function (lines 38-60) with the version below. Note the `export` keywords on both `RefreshOutcome` and `refreshToken` — they need to be reachable from `connection.ts` in Task 5.

```typescript
export type RefreshOutcome = "ok" | "auth_failed" | "backend_unavailable"

let currentRefresh: Promise<RefreshOutcome> | null = null

export async function refreshToken(): Promise<RefreshOutcome> {
  // Share the in-flight refresh promise so parallel 401s coalesce into a
  // single refresh call.
  if (currentRefresh) return currentRefresh
  currentRefresh = (async () => {
    try {
      const res = await fetch(apiUrl("/api/auth/refresh"), {
        method: "POST",
        credentials: "include",
      })
      // No marker header → response did not come from our backend
      // (proxy fall-through). This is NOT an auth failure; do not log
      // the user out. The health monitor will pick up the backend-down
      // state.
      if (!res.headers.has(BACKEND_MARKER_HEADER)) {
        return "backend_unavailable"
      }
      if (!res.ok) return "auth_failed"
      const data = await res.json()
      setAccessToken(data.access_token)
      return "ok"
    } catch (err) {
      return isNetworkError(err) ? "backend_unavailable" : "auth_failed"
    } finally {
      currentRefresh = null
    }
  })()
  return currentRefresh
}
```

- [ ] **Step 4: Wire `onAuthFailure` to call `forceLogout`**

The existing `configureClient` accepts an `onAuthFailure` callback. The wiring of that callback lives in whatever module configures the client (typically `frontend/src/core/store/authStore.ts` or a setup module — find it via `rg -n "configureClient" frontend/src`). Update the configuration site so that `onAuthFailure` calls the coordinator:

```typescript
import { forceLogout } from "../auth/logoutCoordinator"

configureClient({
  // ... existing fields ...
  onAuthFailure: () => {
    void forceLogout(
      "session_expired",
      "Deine Sitzung ist abgelaufen. Bitte melde dich erneut an.",
    )
  },
})
```

If `onAuthFailure` is currently doing additional state management (e.g. directly calling `clear()` on the auth store), remove that — `forceLogout` now owns the clear + navigate + toast sequence.

- [ ] **Step 5: Build and verify**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm run build
```

Expected: clean build. If a downstream caller of the deleted `boolean | "network_error"` return type breaks, locate the caller (`rg -n "refreshToken|currentRefresh"` inside `frontend/src/core/api/client.ts`) — these were internal-only.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/core/api/client.ts frontend/src/core/store/authStore.ts
git commit -m "Header-aware API client refresh and error routing"
```

(Adjust the second path if the `configureClient` site lives elsewhere — only commit files you actually changed.)

---

## Task 4: Frontend health monitor

**Files:**
- Create: `frontend/src/core/health/healthMonitor.ts`
- Modify: `frontend/src/App.tsx` (start the monitor on mount)
- Modify: `frontend/src/app/pages/BackendUnavailablePage.tsx` (strip internal poll)

- [ ] **Step 1: Create the health monitor**

Create `frontend/src/core/health/healthMonitor.ts`:

```typescript
import { apiUrl } from "../api/client"
import { useEventStore } from "../store/eventStore"

const BACKEND_MARKER_HEADER = "X-Chatsune-Backend"
const POLL_OK_MS = 5_000
const POLL_FAIL_MS = 1_000

let timer: ReturnType<typeof setTimeout> | null = null
let stopped = false

async function probe(): Promise<boolean> {
  try {
    const res = await fetch(apiUrl("/api/health"), { credentials: "include" })
    if (res.status !== 200) return false
    if (!res.headers.has(BACKEND_MARKER_HEADER)) return false
    return true
  } catch {
    return false
  }
}

async function tick(): Promise<void> {
  if (stopped) return
  // Skip while the tab is hidden — wakes back up via visibilitychange.
  if (typeof document !== "undefined" && document.hidden) {
    schedule(POLL_OK_MS)
    return
  }
  const ok = await probe()
  const setBackendAvailable = useEventStore.getState().setBackendAvailable
  setBackendAvailable(ok)
  schedule(ok ? POLL_OK_MS : POLL_FAIL_MS)
}

function schedule(delayMs: number): void {
  if (stopped) return
  timer = setTimeout(() => {
    void tick()
  }, delayMs)
}

function onVisibilityChange(): void {
  if (!document.hidden && !stopped) {
    if (timer) clearTimeout(timer)
    void tick()
  }
}

export function startHealthMonitor(): void {
  stopped = false
  if (typeof document !== "undefined") {
    document.addEventListener("visibilitychange", onVisibilityChange)
  }
  void tick()
}

export function stopHealthMonitor(): void {
  stopped = true
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
  if (typeof document !== "undefined") {
    document.removeEventListener("visibilitychange", onVisibilityChange)
  }
}
```

If `useEventStore.getState()` does not currently expose a `setBackendAvailable` setter, look for the existing setter (likely `setBackendAvailable` or similar) — the spec says the `backendAvailable` flag already exists in the store. If only the flag exists without a setter, add a setter following the existing store pattern. Inspect `frontend/src/core/store/eventStore.ts` first.

- [ ] **Step 2: Start the health monitor in App.tsx**

In `frontend/src/App.tsx`, alongside the other top-level mount effects, add:

```tsx
import { startHealthMonitor, stopHealthMonitor } from "./core/health/healthMonitor"

// ...

useEffect(() => {
  startHealthMonitor()
  return () => stopHealthMonitor()
}, [])
```

The `useEffect` should NOT depend on `isAuthenticated` — the health monitor runs whether or not the user is logged in (the login page itself benefits from the backend-down detection).

- [ ] **Step 3: Strip the internal poll from BackendUnavailablePage**

Open `frontend/src/app/pages/BackendUnavailablePage.tsx`. Remove the `useEffect` that polls `/api/health`, the local state for `attempts` / `lastCheck`, and any related logic. Keep only the presentational JSX. The page now reads `backendAvailable` purely as a render input from the existing `eventStore` selector (used by the gating in `App.tsx:101`).

If the page currently shows a "Retry now" button, keep it but rewire it to call `tick()` from the health monitor by exporting a `probeNow()` function from `healthMonitor.ts`:

```typescript
export async function probeNow(): Promise<void> {
  if (timer) clearTimeout(timer)
  await tick()
}
```

Then in `BackendUnavailablePage.tsx`:

```tsx
import { probeNow } from "../../core/health/healthMonitor"

// inside the button onClick:
onClick={() => void probeNow()}
```

- [ ] **Step 4: Build and verify**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm run build
```

Expected: clean build.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/health/healthMonitor.ts \
        frontend/src/app/pages/BackendUnavailablePage.tsx \
        frontend/src/App.tsx \
        frontend/src/core/store/eventStore.ts
git commit -m "Add always-on health monitor with header-aware probe"
```

(Only stage `eventStore.ts` if you actually had to add the setter.)

---

## Task 5: WS pong timeout, close-code routing, logout button

**Files:**
- Modify: `frontend/src/core/websocket/connection.ts`
- Modify: `frontend/src/core/hooks/useAuth.ts`

- [ ] **Step 1: Add the pong timeout to the WebSocket**

Open `frontend/src/core/websocket/connection.ts`. Near the existing `PING_INTERVAL_MS` constant (around line 6), add:

```typescript
const PONG_TIMEOUT_MS = 10_000
```

Find the ping-sending logic (the interval that sends `{type: "ping"}` every 30 seconds). Each time a ping is sent, start a timer; clear it when a `pong` arrives.

Add module-level state next to the existing socket / interval refs:

```typescript
let pongTimer: ReturnType<typeof setTimeout> | null = null
```

In the ping-sending block (where `socket.send(JSON.stringify({type: "ping"}))` lives), after the send call, add:

```typescript
if (pongTimer) clearTimeout(pongTimer)
pongTimer = setTimeout(() => {
  // Pong did not arrive within PONG_TIMEOUT_MS — the socket is dead but
  // the browser hasn't noticed. Force-close so the existing reconnect
  // logic engages.
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.close(1000, "pong timeout")
  }
}, PONG_TIMEOUT_MS)
```

In the `onmessage` handler, where the code currently ignores `pong` events (around line 60 per the previous mapping), clear the timer:

```typescript
if (msg.type === "pong") {
  if (pongTimer) {
    clearTimeout(pongTimer)
    pongTimer = null
  }
  return
}
```

In `onclose` and in the `disconnect()` function, also clear the timer:

```typescript
if (pongTimer) {
  clearTimeout(pongTimer)
  pongTimer = null
}
```

- [ ] **Step 2: Route close codes 4001/4003 through forceLogout**

Still in `connection.ts`, find the `onclose` handler (around lines 85-98 per the previous mapping). The existing logic invokes `handleTokenRefresh()` on 4001 and reconnects on other non-intentional codes. Replace that block with:

```typescript
socket.onclose = (ev) => {
  if (pongTimer) {
    clearTimeout(pongTimer)
    pongTimer = null
  }

  if (ev.code === 4003) {
    void forceLogout(
      "must_change_password",
      "Bitte ändere dein Passwort, um fortzufahren.",
    )
    return
  }

  if (ev.code === 4001) {
    void handleTokenRefresh()
    return
  }

  if (!intentionalClose) {
    scheduleReconnect()
  }
}
```

Add the import at the top of `connection.ts`:

```typescript
import { forceLogout } from "../auth/logoutCoordinator"
```

- [ ] **Step 3: Update `handleTokenRefresh` to call forceLogout when refresh fails**

In `connection.ts`, find `handleTokenRefresh` (around lines 161-186 per the mapping). The current behaviour calls `clear()` on refresh failure; change it to delegate to `forceLogout` (which clears, navigates, and toasts). Replace the failure branch:

```typescript
async function handleTokenRefresh(): Promise<void> {
  try {
    const ok = await refreshAccessToken()
    if (ok === "ok") {
      // Token refreshed; reconnect with the new token.
      reconnect()
      return
    }
    if (ok === "backend_unavailable") {
      // Health monitor will surface the backend-down state. Do NOT log
      // the user out for a transient backend hiccup.
      scheduleReconnect()
      return
    }
    // ok === "auth_failed": the backend authoritatively rejected the
    // refresh. End the session.
    void forceLogout(
      "session_expired",
      "Deine Sitzung ist abgelaufen. Bitte melde dich erneut an.",
    )
  } catch {
    // Network or unknown error — let the reconnect loop continue; the
    // health monitor decides whether to show the backend-down screen.
    scheduleReconnect()
  }
}
```

`refreshToken` and the `RefreshOutcome` type were already exported from `client.ts` in Task 3 Step 3. Import them in `connection.ts`:

```typescript
import { refreshToken as refreshAccessToken } from "../api/client"
```

If `connection.ts` currently has its own inline refresh implementation, delete it and use the imported one. If it has a thin wrapper, replace the wrapper's body with `return refreshAccessToken()` and adjust the return type to `RefreshOutcome`.

- [ ] **Step 4: Update the logout button path**

Open `frontend/src/core/hooks/useAuth.ts`. Find the `logout` function (around lines 99-108 per the mapping). Replace its body with a call to the coordinator:

```typescript
import { logout as coordinatorLogout } from "../auth/logoutCoordinator"

// ...inside the hook:
const logout = useCallback(async () => {
  await coordinatorLogout()
}, [])
```

Drop any inline calls to `authApi.logout()`, `disconnect()`, `clear()` — `coordinatorLogout` owns that sequence now.

If the hook also exposes `deleteAccount` or other paths that previously inlined a similar sequence, leave those alone for this task — they have account-deletion-specific cleanup and are out of scope.

- [ ] **Step 5: Build and verify**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm run build
```

Expected: clean build.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/core/websocket/connection.ts \
        frontend/src/core/hooks/useAuth.ts \
        frontend/src/core/api/client.ts
git commit -m "WS pong timeout, header-aware refresh, centralised logout"
```

---

## Final manual verification

After Task 5 is committed, the product owner runs the six manual scenarios from the spec at `devdocs/specs/2026-05-01-auth-ws-resilience-design.md` § Manual verification, against the deployed environment.

If any scenario fails, do NOT re-commit fixes silently. Open a follow-up task with the symptom (which scenario, what was observed, what was expected).

---

## Constraints for all tasks

- Do NOT merge to master, do NOT push, do NOT switch branches, do NOT amend prior commits.
- Do NOT run the full backend test suite without the project's host-mode ignore list (MongoDB-dependent tests will fail without Docker). The middleware test introduced in Task 1 is self-contained and does not need MongoDB.
- For the frontend, always use `pnpm run build` (which runs `tsc -b`) as the build check, not `pnpm tsc --noEmit` — `tsc -b` is stricter.
- Do NOT touch files outside the file lists in each task. If a downstream caller breaks because of a signature change, surface it as DONE_WITH_CONCERNS rather than ad-hoc-fixing it.
- All toasts use German user-facing text. All code identifiers stay British English.

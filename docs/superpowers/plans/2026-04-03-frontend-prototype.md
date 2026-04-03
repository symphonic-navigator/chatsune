# Frontend Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a functional frontend prototype with a reusable core logic layer and throwaway prototype UI that validates the full backend stack end-to-end.

**Architecture:** Two-layer split inside `frontend/src/`: `core/` contains all permanent logic (types, hooks, API client, WebSocket, stores) with zero UI code; `prototype/` contains throwaway pages and components. Hooks are the public API between layers.

**Tech Stack:** React 19, TypeScript, Vite, Tailwind CSS v4, Zustand, react-router-dom, pnpm

**Spec:** `docs/superpowers/specs/2026-04-03-frontend-prototype-design.md`

---

## Task 1: Project Scaffolding

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.app.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/tailwind.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/index.css`
- Create: `frontend/.env.example`
- Modify: `frontend/.gitkeep` (delete)

- [ ] **Step 1: Initialise Vite project**

Run from `frontend/`:
```bash
pnpm create vite@latest . --template react-ts
```

If the directory is not empty (has .gitkeep), remove `.gitkeep` first:
```bash
rm frontend/.gitkeep
```

- [ ] **Step 2: Install dependencies**

```bash
cd frontend && pnpm add react-router-dom zustand && pnpm add -D tailwindcss @tailwindcss/vite
```

- [ ] **Step 3: Configure Tailwind with Vite plugin**

Replace `frontend/vite.config.ts`:

```typescript
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
    },
  },
})
```

Replace `frontend/src/index.css`:

```css
@import "tailwindcss";
```

- [ ] **Step 4: Create environment config**

Create `frontend/.env.example`:
```
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
```

Create `frontend/.env`:
```
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
```

Add to `frontend/.gitignore` (append):
```
.env
```

- [ ] **Step 5: Create minimal App shell**

Replace `frontend/src/App.tsx`:

```tsx
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom"

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<div className="p-8 text-lg">Chatsune Prototype</div>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
```

Replace `frontend/src/main.tsx`:

```tsx
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import App from "./App"
import "./index.css"

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
```

- [ ] **Step 6: Clean up Vite scaffolding**

Delete files created by Vite template that we do not need:
- `frontend/src/App.css`
- `frontend/src/assets/` (entire directory)
- `frontend/public/vite.svg` (if created)

- [ ] **Step 7: Verify build**

```bash
cd frontend && pnpm run dev
```

Open `http://localhost:5173` — should show "Chatsune Prototype" with Tailwind styling applied (no browser default serif font).

Press Ctrl+C to stop.

- [ ] **Step 8: Commit**

```bash
git add frontend/
git commit -m "Scaffold frontend with Vite, React, TypeScript, Tailwind, Zustand"
```

---

## Task 2: Core Types

**Files:**
- Create: `frontend/src/core/types/auth.ts`
- Create: `frontend/src/core/types/events.ts`
- Create: `frontend/src/core/types/llm.ts`
- Create: `frontend/src/core/types/persona.ts`
- Create: `frontend/src/core/types/settings.ts`

All types are manually derived from the Python Pydantic models in `shared/`. Field names match exactly.

- [ ] **Step 1: Create auth types**

Create `frontend/src/core/types/auth.ts`:

```typescript
export interface UserDto {
  id: string
  username: string
  email: string
  display_name: string
  role: "user" | "admin" | "master_admin"
  is_active: boolean
  must_change_password: boolean
  created_at: string
  updated_at: string
}

export interface LoginRequest {
  username: string
  password: string
}

export interface SetupRequest {
  pin: string
  username: string
  email: string
  password: string
}

export interface ChangePasswordRequest {
  current_password: string
  new_password: string
}

export interface TokenResponse {
  access_token: string
  token_type: "bearer"
  expires_in: number
}

export interface SetupResponse {
  user: UserDto
  access_token: string
  token_type: "bearer"
  expires_in: number
}

export interface CreateUserRequest {
  username: string
  email: string
  display_name: string
  role?: string
}

export interface UpdateUserRequest {
  display_name?: string
  email?: string
  is_active?: boolean
  role?: string
}

export interface CreateUserResponse {
  user: UserDto
  generated_password: string
}

export interface ResetPasswordResponse {
  user: UserDto
  generated_password: string
}

export interface UsersListResponse {
  users: UserDto[]
  total: number
  skip: number
  limit: number
}

export interface AuditLogEntryDto {
  id: string
  timestamp: string
  actor_id: string
  action: string
  resource_type: string
  resource_id: string | null
  detail: Record<string, unknown> | null
}

export interface AuditLogResponse {
  entries: AuditLogEntryDto[]
  skip: number
  limit: number
}
```

- [ ] **Step 2: Create event types**

Create `frontend/src/core/types/events.ts`:

```typescript
export interface BaseEvent {
  id: string
  type: string
  sequence: string
  scope: string
  correlation_id: string
  timestamp: string
  payload: Record<string, unknown>
}

export interface ErrorEventPayload {
  correlation_id: string
  error_code: string
  recoverable: boolean
  user_message: string
  detail: string | null
}

export const Topics = {
  USER_CREATED: "user.created",
  USER_UPDATED: "user.updated",
  USER_DEACTIVATED: "user.deactivated",
  USER_PASSWORD_RESET: "user.password_reset",
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
} as const

export type TopicType = (typeof Topics)[keyof typeof Topics]
```

- [ ] **Step 3: Create LLM types**

Create `frontend/src/core/types/llm.ts`:

```typescript
export interface ProviderCredentialDto {
  provider_id: string
  display_name: string
  is_configured: boolean
  created_at: string | null
}

export interface SetProviderKeyRequest {
  api_key: string
}

export type ModelRating = "available" | "recommended" | "not_recommended"

export interface ModelCurationDto {
  overall_rating: ModelRating
  hidden: boolean
  admin_description: string | null
  last_curated_at: string | null
  last_curated_by: string | null
}

export interface SetModelCurationRequest {
  overall_rating: ModelRating
  hidden: boolean
  admin_description?: string | null
}

export interface ModelMetaDto {
  provider_id: string
  model_id: string
  display_name: string
  context_window: number
  supports_reasoning: boolean
  supports_vision: boolean
  supports_tool_calls: boolean
  parameter_count: string | null
  quantisation_level: string | null
  curation: ModelCurationDto | null
  unique_id: string
}

export interface UserModelConfigDto {
  model_unique_id: string
  is_favourite: boolean
  is_hidden: boolean
  notes: string | null
  system_prompt_addition: string | null
}

export interface SetUserModelConfigRequest {
  is_favourite?: boolean
  is_hidden?: boolean
  notes?: string | null
  system_prompt_addition?: string | null
}

export interface TestKeyResponse {
  valid: boolean
}
```

- [ ] **Step 4: Create persona types**

Create `frontend/src/core/types/persona.ts`:

```typescript
export interface PersonaDto {
  id: string
  user_id: string
  name: string
  tagline: string
  model_unique_id: string
  system_prompt: string
  temperature: number
  reasoning_enabled: boolean
  colour_scheme: string
  display_order: number
  created_at: string
  updated_at: string
}

export interface CreatePersonaRequest {
  name: string
  tagline: string
  model_unique_id: string
  system_prompt: string
  temperature?: number
  reasoning_enabled?: boolean
  colour_scheme?: string
  display_order?: number
}

export interface UpdatePersonaRequest {
  name?: string
  tagline?: string
  model_unique_id?: string
  system_prompt?: string
  temperature?: number
  reasoning_enabled?: boolean
  colour_scheme?: string
  display_order?: number
}
```

- [ ] **Step 5: Create settings types**

Create `frontend/src/core/types/settings.ts`:

```typescript
export interface AppSettingDto {
  key: string
  value: string
  updated_at: string
  updated_by: string
}

export interface SetSettingRequest {
  value: string
}
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/core/types/
git commit -m "Add TypeScript types derived from shared Python DTOs"
```

---

## Task 3: API Client

**Files:**
- Create: `frontend/src/core/api/client.ts`

The API client is a thin fetch wrapper that auto-injects the auth token and handles 401 refresh.

- [ ] **Step 1: Create the API client**

Create `frontend/src/core/api/client.ts`:

```typescript
type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE"

let getAccessToken: () => string | null = () => null
let setAccessToken: (token: string) => void = () => {}
let onAuthFailure: () => void = () => {}

export function configureClient(config: {
  getAccessToken: () => string | null
  setAccessToken: (token: string) => void
  onAuthFailure: () => void
}) {
  getAccessToken = config.getAccessToken
  setAccessToken = config.setAccessToken
  onAuthFailure = config.onAuthFailure
}

function baseUrl(): string {
  return import.meta.env.VITE_API_URL ?? ""
}

async function refreshToken(): Promise<boolean> {
  try {
    const res = await fetch(`${baseUrl()}/api/auth/refresh`, {
      method: "POST",
      credentials: "include",
    })
    if (!res.ok) return false
    const data = await res.json()
    setAccessToken(data.access_token)
    return true
  } catch {
    return false
  }
}

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

  let res = await fetch(`${baseUrl()}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: "include",
  })

  if (res.status === 401 && !skipAuth) {
    const refreshed = await refreshToken()
    if (refreshed) {
      const token = getAccessToken()
      if (token) {
        headers["Authorization"] = `Bearer ${token}`
      }
      res = await fetch(`${baseUrl()}${path}`, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
        credentials: "include",
      })
    } else {
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

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body?: unknown,
  ) {
    super(message)
    this.name = "ApiError"
  }
}

export const api = {
  get: <T>(path: string) => apiRequest<T>("GET", path),
  post: <T>(path: string, body?: unknown) => apiRequest<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => apiRequest<T>("PUT", path, body),
  patch: <T>(path: string, body?: unknown) => apiRequest<T>("PATCH", path, body),
  delete: <T>(path: string) => apiRequest<T>("DELETE", path),
  postNoAuth: <T>(path: string, body?: unknown) => apiRequest<T>("POST", path, body, true),
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/core/api/client.ts
git commit -m "Add API client with auto-refresh on 401"
```

---

## Task 4: Auth Store and API

**Files:**
- Create: `frontend/src/core/store/authStore.ts`
- Create: `frontend/src/core/api/auth.ts`

- [ ] **Step 1: Create auth API functions**

Create `frontend/src/core/api/auth.ts`:

```typescript
import { api, apiRequest } from "./client"
import type {
  LoginRequest,
  SetupRequest,
  SetupResponse,
  TokenResponse,
  ChangePasswordRequest,
} from "../types/auth"

export const authApi = {
  login: (data: LoginRequest) =>
    apiRequest<TokenResponse>("POST", "/api/auth/login", data, true),

  refresh: () =>
    apiRequest<TokenResponse>("POST", "/api/auth/refresh", undefined, true),

  logout: () => api.post<{ status: string }>("/api/auth/logout"),

  changePassword: (data: ChangePasswordRequest) =>
    api.patch<TokenResponse>("/api/auth/password", data),

  setup: (data: SetupRequest) =>
    apiRequest<SetupResponse>("POST", "/api/setup", data, true),
}
```

- [ ] **Step 2: Create the auth store**

Create `frontend/src/core/store/authStore.ts`:

```typescript
import { create } from "zustand"
import type { UserDto } from "../types/auth"
import { configureClient } from "../api/client"

function decodeJwtPayload(token: string): Record<string, unknown> {
  const base64 = token.split(".")[1]
  const json = atob(base64.replace(/-/g, "+").replace(/_/g, "/"))
  return JSON.parse(json)
}

function extractUserFromToken(token: string): UserDto | null {
  try {
    const payload = decodeJwtPayload(token)
    return {
      id: payload.sub as string,
      username: "",
      email: "",
      display_name: "",
      role: payload.role as UserDto["role"],
      is_active: true,
      must_change_password: (payload.mcp as boolean) ?? false,
      created_at: "",
      updated_at: "",
    }
  } catch {
    return null
  }
}

interface AuthState {
  accessToken: string | null
  user: UserDto | null
  isAuthenticated: boolean

  setToken: (token: string) => void
  setUser: (user: UserDto) => void
  clear: () => void
}

export const useAuthStore = create<AuthState>((set, get) => ({
  accessToken: null,
  user: null,
  isAuthenticated: false,

  setToken: (token: string) => {
    const partial = extractUserFromToken(token)
    const current = get().user
    const user = current
      ? { ...current, role: partial?.role ?? current.role, must_change_password: partial?.must_change_password ?? false }
      : partial
    set({ accessToken: token, user, isAuthenticated: true })
  },

  setUser: (user: UserDto) => set({ user }),

  clear: () => set({ accessToken: null, user: null, isAuthenticated: false }),
}))

// Wire up the API client to use the auth store
configureClient({
  getAccessToken: () => useAuthStore.getState().accessToken,
  setAccessToken: (token: string) => useAuthStore.getState().setToken(token),
  onAuthFailure: () => useAuthStore.getState().clear(),
})
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/core/api/auth.ts frontend/src/core/store/authStore.ts
git commit -m "Add auth store and auth API functions"
```

---

## Task 5: WebSocket Connection and Event Bus

**Files:**
- Create: `frontend/src/core/websocket/connection.ts`
- Create: `frontend/src/core/websocket/eventBus.ts`
- Create: `frontend/src/core/store/eventStore.ts`

- [ ] **Step 1: Create the event store**

Create `frontend/src/core/store/eventStore.ts`:

```typescript
import { create } from "zustand"

export type ConnectionStatus = "disconnected" | "connecting" | "connected" | "reconnecting"

interface EventState {
  status: ConnectionStatus
  lastSequence: string
  setStatus: (status: ConnectionStatus) => void
  setLastSequence: (seq: string) => void
}

export const useEventStore = create<EventState>((set) => ({
  status: "disconnected",
  lastSequence: "",
  setStatus: (status) => set({ status }),
  setLastSequence: (lastSequence) => set({ lastSequence }),
}))
```

- [ ] **Step 2: Create the event bus**

Create `frontend/src/core/websocket/eventBus.ts`:

```typescript
import type { BaseEvent } from "../types/events"

type EventCallback = (event: BaseEvent) => void

class EventBus {
  private listeners = new Map<string, Set<EventCallback>>()

  on(eventType: string, callback: EventCallback): () => void {
    if (!this.listeners.has(eventType)) {
      this.listeners.set(eventType, new Set())
    }
    this.listeners.get(eventType)!.add(callback)

    return () => {
      this.listeners.get(eventType)?.delete(callback)
    }
  }

  emit(event: BaseEvent) {
    // Notify exact type subscribers
    this.listeners.get(event.type)?.forEach((cb) => cb(event))

    // Notify wildcard subscribers
    if (event.type !== "*") {
      this.listeners.get("*")?.forEach((cb) => cb(event))
    }

    // Notify prefix subscribers (e.g. "persona.*" matches "persona.created")
    const parts = event.type.split(".")
    if (parts.length > 1) {
      const prefix = parts[0] + ".*"
      this.listeners.get(prefix)?.forEach((cb) => cb(event))
    }
  }

  clear() {
    this.listeners.clear()
  }
}

export const eventBus = new EventBus()
```

- [ ] **Step 3: Create the WebSocket connection manager**

Create `frontend/src/core/websocket/connection.ts`:

```typescript
import type { BaseEvent } from "../types/events"
import { eventBus } from "./eventBus"
import { useEventStore } from "../store/eventStore"
import { useAuthStore } from "../store/authStore"
import { authApi } from "../api/auth"

const MAX_RECONNECT_DELAY = 30_000
const INITIAL_RECONNECT_DELAY = 1_000

let ws: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let reconnectDelay = INITIAL_RECONNECT_DELAY
let intentionalClose = false

function wsUrl(): string {
  return import.meta.env.VITE_WS_URL ?? ""
}

export function connect() {
  const token = useAuthStore.getState().accessToken
  if (!token) return

  intentionalClose = false
  const { setStatus, lastSequence } = useEventStore.getState()
  setStatus("connecting")

  let url = `${wsUrl()}/ws?token=${encodeURIComponent(token)}`
  if (lastSequence) {
    url += `&since=${encodeURIComponent(lastSequence)}`
  }

  ws = new WebSocket(url)

  ws.onopen = () => {
    reconnectDelay = INITIAL_RECONNECT_DELAY
    useEventStore.getState().setStatus("connected")
  }

  ws.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data)

      if (data.type === "pong") return

      if (data.type === "token.expiring_soon") {
        handleTokenRefresh()
        return
      }

      const event = data as BaseEvent
      if (event.sequence) {
        useEventStore.getState().setLastSequence(event.sequence)
      }
      eventBus.emit(event)
    } catch {
      // Ignore malformed messages
    }
  }

  ws.onclose = (ev) => {
    useEventStore.getState().setStatus("disconnected")
    ws = null

    if (!intentionalClose && ev.code !== 4001 && ev.code !== 4003) {
      scheduleReconnect()
    }

    if (ev.code === 4001) {
      // Invalid token — try refresh
      handleTokenRefresh()
    }

    if (ev.code === 4003) {
      // Must change password — auth store handles redirect
    }
  }

  ws.onerror = () => {
    // onclose will fire after onerror, reconnect handled there
  }
}

export function disconnect() {
  intentionalClose = true
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  ws?.close()
  ws = null
  useEventStore.getState().setStatus("disconnected")
}

export function sendPing() {
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "ping" }))
  }
}

function scheduleReconnect() {
  useEventStore.getState().setStatus("reconnecting")
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY)
    connect()
  }, reconnectDelay)
}

async function handleTokenRefresh() {
  try {
    const res = await authApi.refresh()
    useAuthStore.getState().setToken(res.access_token)
    // Reconnect with new token
    disconnect()
    intentionalClose = false
    connect()
  } catch {
    useAuthStore.getState().clear()
  }
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/core/websocket/ frontend/src/core/store/eventStore.ts
git commit -m "Add WebSocket connection manager, event bus, and event store"
```

---

## Task 6: Core Hooks — Auth, WebSocket, EventBus

**Files:**
- Create: `frontend/src/core/hooks/useAuth.ts`
- Create: `frontend/src/core/hooks/useWebSocket.ts`
- Create: `frontend/src/core/hooks/useEventBus.ts`

- [ ] **Step 1: Create useAuth hook**

Create `frontend/src/core/hooks/useAuth.ts`:

```typescript
import { useCallback, useState } from "react"
import { useAuthStore } from "../store/authStore"
import { authApi } from "../api/auth"
import { connect, disconnect } from "../websocket/connection"
import type {
  LoginRequest,
  SetupRequest,
  ChangePasswordRequest,
  UserDto,
} from "../types/auth"

export function useAuth() {
  const { user, isAuthenticated, accessToken, setToken, setUser, clear } =
    useAuthStore()
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const login = useCallback(async (data: LoginRequest) => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await authApi.login(data)
      setToken(res.access_token)
      connect()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed")
      throw err
    } finally {
      setIsLoading(false)
    }
  }, [setToken])

  const setup = useCallback(async (data: SetupRequest) => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await authApi.setup(data)
      setToken(res.access_token)
      setUser(res.user)
      connect()
      return res
    } catch (err) {
      setError(err instanceof Error ? err.message : "Setup failed")
      throw err
    } finally {
      setIsLoading(false)
    }
  }, [setToken, setUser])

  const changePassword = useCallback(async (data: ChangePasswordRequest) => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await authApi.changePassword(data)
      setToken(res.access_token)
      disconnect()
      connect()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Password change failed")
      throw err
    } finally {
      setIsLoading(false)
    }
  }, [setToken])

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } catch {
      // Logout should succeed even if the API call fails
    } finally {
      disconnect()
      clear()
    }
  }, [clear])

  return {
    user,
    isAuthenticated,
    accessToken,
    isLoading,
    error,
    login,
    setup,
    changePassword,
    logout,
  }
}
```

- [ ] **Step 2: Create useWebSocket hook**

Create `frontend/src/core/hooks/useWebSocket.ts`:

```typescript
import { useEffect, useRef } from "react"
import { useEventStore } from "../store/eventStore"
import { useAuthStore } from "../store/authStore"
import { connect, disconnect, sendPing } from "../websocket/connection"

const PING_INTERVAL = 30_000

export function useWebSocket() {
  const status = useEventStore((s) => s.status)
  const lastSequence = useEventStore((s) => s.lastSequence)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const pingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (isAuthenticated) {
      connect()
      pingRef.current = setInterval(sendPing, PING_INTERVAL)
    }

    return () => {
      if (pingRef.current) {
        clearInterval(pingRef.current)
        pingRef.current = null
      }
      disconnect()
    }
  }, [isAuthenticated])

  return { status, lastSequence }
}
```

- [ ] **Step 3: Create useEventBus hook**

Create `frontend/src/core/hooks/useEventBus.ts`:

```typescript
import { useEffect, useRef, useState } from "react"
import { eventBus } from "../websocket/eventBus"
import type { BaseEvent } from "../types/events"

export function useEventBus(eventType: string, maxHistory = 100) {
  const [events, setEvents] = useState<BaseEvent[]>([])
  const eventsRef = useRef<BaseEvent[]>([])

  useEffect(() => {
    eventsRef.current = []
    setEvents([])

    const unsubscribe = eventBus.on(eventType, (event) => {
      eventsRef.current = [...eventsRef.current.slice(-(maxHistory - 1)), event]
      setEvents(eventsRef.current)
    })

    return unsubscribe
  }, [eventType, maxHistory])

  const clear = () => {
    eventsRef.current = []
    setEvents([])
  }

  return { events, latest: events[events.length - 1] ?? null, clear }
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/core/hooks/useAuth.ts frontend/src/core/hooks/useWebSocket.ts frontend/src/core/hooks/useEventBus.ts
git commit -m "Add core hooks: useAuth, useWebSocket, useEventBus"
```

---

## Task 7: Core Hooks — Users, LLM, Personas, Settings

**Files:**
- Create: `frontend/src/core/api/users.ts`
- Create: `frontend/src/core/api/llm.ts`
- Create: `frontend/src/core/api/personas.ts`
- Create: `frontend/src/core/api/settings.ts`
- Create: `frontend/src/core/hooks/useUsers.ts`
- Create: `frontend/src/core/hooks/useLlm.ts`
- Create: `frontend/src/core/hooks/usePersonas.ts`
- Create: `frontend/src/core/hooks/useSettings.ts`

- [ ] **Step 1: Create users API and hook**

Create `frontend/src/core/api/users.ts`:

```typescript
import { api } from "./client"
import type {
  UserDto,
  UsersListResponse,
  CreateUserRequest,
  CreateUserResponse,
  UpdateUserRequest,
  ResetPasswordResponse,
  AuditLogResponse,
} from "../types/auth"

export const usersApi = {
  list: (skip = 0, limit = 50) =>
    api.get<UsersListResponse>(`/api/admin/users?skip=${skip}&limit=${limit}`),

  get: (userId: string) =>
    api.get<UserDto>(`/api/admin/users/${userId}`),

  create: (data: CreateUserRequest) =>
    api.post<CreateUserResponse>("/api/admin/users", data),

  update: (userId: string, data: UpdateUserRequest) =>
    api.patch<UserDto>(`/api/admin/users/${userId}`, data),

  deactivate: (userId: string) =>
    api.delete<{ status: string }>(`/api/admin/users/${userId}`),

  resetPassword: (userId: string) =>
    api.post<ResetPasswordResponse>(`/api/admin/users/${userId}/reset-password`),

  auditLog: (params?: { skip?: number; limit?: number; action?: string; actor_id?: string }) => {
    const query = new URLSearchParams()
    if (params?.skip !== undefined) query.set("skip", String(params.skip))
    if (params?.limit !== undefined) query.set("limit", String(params.limit))
    if (params?.action) query.set("action", params.action)
    if (params?.actor_id) query.set("actor_id", params.actor_id)
    return api.get<AuditLogResponse>(`/api/admin/audit-log?${query}`)
  },
}
```

Create `frontend/src/core/hooks/useUsers.ts`:

```typescript
import { useCallback, useEffect, useState } from "react"
import { usersApi } from "../api/users"
import { eventBus } from "../websocket/eventBus"
import { Topics } from "../types/events"
import type { UserDto, CreateUserRequest, UpdateUserRequest } from "../types/auth"

export function useUsers() {
  const [users, setUsers] = useState<UserDto[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetch = useCallback(async (skip = 0, limit = 50) => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await usersApi.list(skip, limit)
      setUsers(res.users)
      setTotal(res.total)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load users")
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetch()

    const unsubs = [
      eventBus.on(Topics.USER_CREATED, () => fetch()),
      eventBus.on(Topics.USER_UPDATED, () => fetch()),
      eventBus.on(Topics.USER_DEACTIVATED, () => fetch()),
    ]

    return () => unsubs.forEach((u) => u())
  }, [fetch])

  const create = useCallback(async (data: CreateUserRequest) => {
    return usersApi.create(data)
  }, [])

  const update = useCallback(async (userId: string, data: UpdateUserRequest) => {
    return usersApi.update(userId, data)
  }, [])

  const deactivate = useCallback(async (userId: string) => {
    return usersApi.deactivate(userId)
  }, [])

  const resetPassword = useCallback(async (userId: string) => {
    return usersApi.resetPassword(userId)
  }, [])

  return { users, total, isLoading, error, fetch, create, update, deactivate, resetPassword }
}
```

- [ ] **Step 2: Create LLM API and hook**

Create `frontend/src/core/api/llm.ts`:

```typescript
import { api } from "./client"
import type {
  ProviderCredentialDto,
  SetProviderKeyRequest,
  ModelMetaDto,
  ModelCurationDto,
  SetModelCurationRequest,
  UserModelConfigDto,
  SetUserModelConfigRequest,
  TestKeyResponse,
} from "../types/llm"

export const llmApi = {
  listProviders: () =>
    api.get<ProviderCredentialDto[]>("/api/llm/providers"),

  setKey: (providerId: string, data: SetProviderKeyRequest) =>
    api.put<ProviderCredentialDto>(`/api/llm/providers/${providerId}/key`, data),

  removeKey: (providerId: string) =>
    api.delete<{ status: string }>(`/api/llm/providers/${providerId}/key`),

  testKey: (providerId: string, data: SetProviderKeyRequest) =>
    api.post<TestKeyResponse>(`/api/llm/providers/${providerId}/test`, data),

  listModels: (providerId: string) =>
    api.get<ModelMetaDto[]>(`/api/llm/providers/${providerId}/models`),

  setCuration: (providerId: string, modelSlug: string, data: SetModelCurationRequest) =>
    api.put<ModelCurationDto>(`/api/llm/providers/${providerId}/models/${encodeURIComponent(modelSlug)}/curation`, data),

  removeCuration: (providerId: string, modelSlug: string) =>
    api.delete<{ status: string }>(`/api/llm/providers/${providerId}/models/${encodeURIComponent(modelSlug)}/curation`),

  listUserConfigs: () =>
    api.get<UserModelConfigDto[]>("/api/llm/user-model-configs"),

  getUserConfig: (providerId: string, modelSlug: string) =>
    api.get<UserModelConfigDto>(`/api/llm/providers/${providerId}/models/${encodeURIComponent(modelSlug)}/user-config`),

  setUserConfig: (providerId: string, modelSlug: string, data: SetUserModelConfigRequest) =>
    api.put<UserModelConfigDto>(`/api/llm/providers/${providerId}/models/${encodeURIComponent(modelSlug)}/user-config`, data),

  deleteUserConfig: (providerId: string, modelSlug: string) =>
    api.delete<UserModelConfigDto>(`/api/llm/providers/${providerId}/models/${encodeURIComponent(modelSlug)}/user-config`),
}
```

Create `frontend/src/core/hooks/useLlm.ts`:

```typescript
import { useCallback, useEffect, useState } from "react"
import { llmApi } from "../api/llm"
import { eventBus } from "../websocket/eventBus"
import { Topics } from "../types/events"
import type {
  ProviderCredentialDto,
  ModelMetaDto,
  UserModelConfigDto,
  SetProviderKeyRequest,
  SetModelCurationRequest,
  SetUserModelConfigRequest,
} from "../types/llm"

export function useLlm() {
  const [providers, setProviders] = useState<ProviderCredentialDto[]>([])
  const [models, setModels] = useState<Map<string, ModelMetaDto[]>>(new Map())
  const [userConfigs, setUserConfigs] = useState<UserModelConfigDto[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchProviders = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await llmApi.listProviders()
      setProviders(res)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load providers")
    } finally {
      setIsLoading(false)
    }
  }, [])

  const fetchModels = useCallback(async (providerId: string) => {
    try {
      const res = await llmApi.listModels(providerId)
      setModels((prev) => new Map(prev).set(providerId, res))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load models")
    }
  }, [])

  const fetchUserConfigs = useCallback(async () => {
    try {
      const res = await llmApi.listUserConfigs()
      setUserConfigs(res)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load user configs")
    }
  }, [])

  useEffect(() => {
    fetchProviders()
    fetchUserConfigs()

    const unsubs = [
      eventBus.on(Topics.LLM_CREDENTIAL_SET, () => fetchProviders()),
      eventBus.on(Topics.LLM_CREDENTIAL_REMOVED, () => fetchProviders()),
      eventBus.on(Topics.LLM_MODEL_CURATED, () => {
        // Refetch models for all loaded providers
        models.forEach((_, pid) => fetchModels(pid))
      }),
      eventBus.on(Topics.LLM_MODELS_REFRESHED, () => {
        models.forEach((_, pid) => fetchModels(pid))
      }),
      eventBus.on(Topics.LLM_USER_MODEL_CONFIG_UPDATED, () => fetchUserConfigs()),
    ]

    return () => unsubs.forEach((u) => u())
  }, [fetchProviders, fetchModels, fetchUserConfigs])

  const setKey = useCallback(async (providerId: string, data: SetProviderKeyRequest) => {
    return llmApi.setKey(providerId, data)
  }, [])

  const removeKey = useCallback(async (providerId: string) => {
    return llmApi.removeKey(providerId)
  }, [])

  const testKey = useCallback(async (providerId: string, data: SetProviderKeyRequest) => {
    return llmApi.testKey(providerId, data)
  }, [])

  const setCuration = useCallback(async (providerId: string, modelSlug: string, data: SetModelCurationRequest) => {
    return llmApi.setCuration(providerId, modelSlug, data)
  }, [])

  const removeCuration = useCallback(async (providerId: string, modelSlug: string) => {
    return llmApi.removeCuration(providerId, modelSlug)
  }, [])

  const setUserConfig = useCallback(async (providerId: string, modelSlug: string, data: SetUserModelConfigRequest) => {
    return llmApi.setUserConfig(providerId, modelSlug, data)
  }, [])

  const deleteUserConfig = useCallback(async (providerId: string, modelSlug: string) => {
    return llmApi.deleteUserConfig(providerId, modelSlug)
  }, [])

  return {
    providers,
    models,
    userConfigs,
    isLoading,
    error,
    fetchProviders,
    fetchModels,
    fetchUserConfigs,
    setKey,
    removeKey,
    testKey,
    setCuration,
    removeCuration,
    setUserConfig,
    deleteUserConfig,
  }
}
```

- [ ] **Step 3: Create personas API and hook**

Create `frontend/src/core/api/personas.ts`:

```typescript
import { api } from "./client"
import type {
  PersonaDto,
  CreatePersonaRequest,
  UpdatePersonaRequest,
} from "../types/persona"

export const personasApi = {
  list: () =>
    api.get<PersonaDto[]>("/api/personas"),

  get: (personaId: string) =>
    api.get<PersonaDto>(`/api/personas/${personaId}`),

  create: (data: CreatePersonaRequest) =>
    api.post<PersonaDto>("/api/personas", data),

  replace: (personaId: string, data: CreatePersonaRequest) =>
    api.put<PersonaDto>(`/api/personas/${personaId}`, data),

  update: (personaId: string, data: UpdatePersonaRequest) =>
    api.patch<PersonaDto>(`/api/personas/${personaId}`, data),

  remove: (personaId: string) =>
    api.delete<{ status: string }>(`/api/personas/${personaId}`),
}
```

Create `frontend/src/core/hooks/usePersonas.ts`:

```typescript
import { useCallback, useEffect, useState } from "react"
import { personasApi } from "../api/personas"
import { eventBus } from "../websocket/eventBus"
import { Topics } from "../types/events"
import type { PersonaDto, CreatePersonaRequest, UpdatePersonaRequest } from "../types/persona"

export function usePersonas() {
  const [personas, setPersonas] = useState<PersonaDto[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetch = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await personasApi.list()
      setPersonas(res)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load personas")
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetch()

    const unsubs = [
      eventBus.on(Topics.PERSONA_CREATED, () => fetch()),
      eventBus.on(Topics.PERSONA_UPDATED, () => fetch()),
      eventBus.on(Topics.PERSONA_DELETED, () => fetch()),
    ]

    return () => unsubs.forEach((u) => u())
  }, [fetch])

  const create = useCallback(async (data: CreatePersonaRequest) => {
    return personasApi.create(data)
  }, [])

  const update = useCallback(async (personaId: string, data: UpdatePersonaRequest) => {
    return personasApi.update(personaId, data)
  }, [])

  const remove = useCallback(async (personaId: string) => {
    return personasApi.remove(personaId)
  }, [])

  return { personas, isLoading, error, fetch, create, update, remove }
}
```

- [ ] **Step 4: Create settings API and hook**

Create `frontend/src/core/api/settings.ts`:

```typescript
import { api } from "./client"
import type { AppSettingDto, SetSettingRequest } from "../types/settings"

export const settingsApi = {
  list: () =>
    api.get<AppSettingDto[]>("/api/settings"),

  get: (key: string) =>
    api.get<AppSettingDto>(`/api/settings/${encodeURIComponent(key)}`),

  set: (key: string, data: SetSettingRequest) =>
    api.put<AppSettingDto>(`/api/settings/${encodeURIComponent(key)}`, data),

  remove: (key: string) =>
    api.delete<{ status: string }>(`/api/settings/${encodeURIComponent(key)}`),
}
```

Create `frontend/src/core/hooks/useSettings.ts`:

```typescript
import { useCallback, useEffect, useState } from "react"
import { settingsApi } from "../api/settings"
import { eventBus } from "../websocket/eventBus"
import { Topics } from "../types/events"
import type { AppSettingDto, SetSettingRequest } from "../types/settings"

export function useSettings() {
  const [settings, setSettings] = useState<AppSettingDto[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetch = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await settingsApi.list()
      setSettings(res)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load settings")
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetch()

    const unsubs = [
      eventBus.on(Topics.SETTING_UPDATED, () => fetch()),
      eventBus.on(Topics.SETTING_DELETED, () => fetch()),
    ]

    return () => unsubs.forEach((u) => u())
  }, [fetch])

  const set = useCallback(async (key: string, data: SetSettingRequest) => {
    return settingsApi.set(key, data)
  }, [])

  const remove = useCallback(async (key: string) => {
    return settingsApi.remove(key)
  }, [])

  return { settings, isLoading, error, fetch, set, remove }
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/api/ frontend/src/core/hooks/
git commit -m "Add API functions and hooks for users, LLM, personas, settings"
```

---

## Task 8: Prototype Layout and Routing

**Files:**
- Create: `frontend/src/prototype/layouts/PrototypeLayout.tsx`
- Create: `frontend/src/prototype/components/StatusBar.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Create StatusBar component**

Create `frontend/src/prototype/components/StatusBar.tsx`:

```tsx
import { useAuthStore } from "../../core/store/authStore"
import { useEventStore, type ConnectionStatus } from "../../core/store/eventStore"

const statusColours: Record<ConnectionStatus, string> = {
  connected: "bg-green-500",
  connecting: "bg-yellow-500",
  reconnecting: "bg-yellow-500",
  disconnected: "bg-red-500",
}

const statusLabels: Record<ConnectionStatus, string> = {
  connected: "Connected",
  connecting: "Connecting...",
  reconnecting: "Reconnecting...",
  disconnected: "Disconnected",
}

export default function StatusBar() {
  const status = useEventStore((s) => s.status)
  const user = useAuthStore((s) => s.user)

  return (
    <div className="flex items-center justify-between border-b border-gray-200 bg-white px-6 py-3">
      <div className="flex items-center gap-3">
        <span className={`inline-block h-2.5 w-2.5 rounded-full ${statusColours[status]}`} />
        <span className="text-sm text-gray-600">{statusLabels[status]}</span>
      </div>
      {user && (
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium">{user.display_name || user.username}</span>
          <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
            {user.role}
          </span>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Create PrototypeLayout**

Create `frontend/src/prototype/layouts/PrototypeLayout.tsx`:

```tsx
import { NavLink, Outlet } from "react-router-dom"
import { useAuthStore } from "../../core/store/authStore"
import { useAuth } from "../../core/hooks/useAuth"
import { useEventStore, type ConnectionStatus } from "../../core/store/eventStore"
import StatusBar from "../components/StatusBar"

const statusColours: Record<ConnectionStatus, string> = {
  connected: "bg-green-500",
  connecting: "bg-yellow-500",
  reconnecting: "bg-yellow-500",
  disconnected: "bg-red-500",
}

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `block rounded px-3 py-2 text-sm ${isActive ? "bg-gray-200 font-medium" : "text-gray-600 hover:bg-gray-100"}`

export default function PrototypeLayout() {
  const user = useAuthStore((s) => s.user)
  const status = useEventStore((s) => s.status)
  const { logout } = useAuth()
  const isAdmin = user?.role === "admin" || user?.role === "master_admin"

  return (
    <div className="flex h-screen bg-gray-50">
      {/* Sidebar */}
      <aside className="flex w-56 flex-col border-r border-gray-200 bg-white">
        <div className="border-b border-gray-200 px-4 py-4">
          <h1 className="text-lg font-semibold">Chatsune</h1>
          <p className="text-xs text-gray-400">Prototype</p>
        </div>

        <nav className="flex-1 space-y-1 p-3">
          <NavLink to="/dashboard" className={navLinkClass}>Dashboard</NavLink>
          {isAdmin && <NavLink to="/users" className={navLinkClass}>Users</NavLink>}
          <NavLink to="/llm" className={navLinkClass}>LLM</NavLink>
          <NavLink to="/personas" className={navLinkClass}>Personas</NavLink>
          {isAdmin && <NavLink to="/admin" className={navLinkClass}>Admin</NavLink>}
        </nav>

        <div className="border-t border-gray-200 p-3 space-y-2">
          <div className="flex items-center gap-2 px-1">
            <span className={`inline-block h-2 w-2 rounded-full ${statusColours[status]}`} />
            <span className="text-xs text-gray-500">{status}</span>
          </div>
          <div className="px-1">
            <p className="text-sm font-medium">{user?.display_name || user?.username}</p>
            <p className="text-xs text-gray-400">{user?.role}</p>
          </div>
          <button
            onClick={logout}
            className="w-full rounded px-3 py-1.5 text-left text-sm text-gray-600 hover:bg-gray-100"
          >
            Logout
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex flex-1 flex-col overflow-hidden">
        <StatusBar />
        <div className="flex-1 overflow-auto p-6">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
```

- [ ] **Step 3: Set up routing in App.tsx**

Replace `frontend/src/App.tsx`:

```tsx
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom"
import { useAuthStore } from "./core/store/authStore"
import { useWebSocket } from "./core/hooks/useWebSocket"
import PrototypeLayout from "./prototype/layouts/PrototypeLayout"

// Lazy-load pages to keep App.tsx clean
import LoginPage from "./prototype/pages/LoginPage"
import DashboardPage from "./prototype/pages/DashboardPage"
import UsersPage from "./prototype/pages/UsersPage"
import LlmPage from "./prototype/pages/LlmPage"
import PersonasPage from "./prototype/pages/PersonasPage"
import AdminPage from "./prototype/pages/AdminPage"

function AuthGuard({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const mustChangePassword = useAuthStore((s) => s.user?.must_change_password)

  if (!isAuthenticated) return <Navigate to="/login" replace />
  if (mustChangePassword) return <Navigate to="/login" replace />

  return <>{children}</>
}

function AppRoutes() {
  // Manage WebSocket lifecycle at the top level
  useWebSocket()

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <AuthGuard>
            <PrototypeLayout />
          </AuthGuard>
        }
      >
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/users" element={<UsersPage />} />
        <Route path="/llm" element={<LlmPage />} />
        <Route path="/personas" element={<PersonasPage />} />
        <Route path="/admin" element={<AdminPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
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

Note: The page imports will fail at this point because the page files don't exist yet. Create placeholder pages in the next steps. You can also skip this step and do it after all pages are created — but then you need to come back and wire up `App.tsx`.

- [ ] **Step 4: Create placeholder pages**

Create stub files so the app compiles. Each page will be properly implemented in later tasks.

Create `frontend/src/prototype/pages/LoginPage.tsx`:
```tsx
export default function LoginPage() {
  return <div className="p-8">LoginPage — TODO</div>
}
```

Create `frontend/src/prototype/pages/DashboardPage.tsx`:
```tsx
export default function DashboardPage() {
  return <div>DashboardPage — TODO</div>
}
```

Create `frontend/src/prototype/pages/UsersPage.tsx`:
```tsx
export default function UsersPage() {
  return <div>UsersPage — TODO</div>
}
```

Create `frontend/src/prototype/pages/LlmPage.tsx`:
```tsx
export default function LlmPage() {
  return <div>LlmPage — TODO</div>
}
```

Create `frontend/src/prototype/pages/PersonasPage.tsx`:
```tsx
export default function PersonasPage() {
  return <div>PersonasPage — TODO</div>
}
```

Create `frontend/src/prototype/pages/AdminPage.tsx`:
```tsx
export default function AdminPage() {
  return <div>AdminPage — TODO</div>
}
```

- [ ] **Step 5: Verify the app compiles**

```bash
cd frontend && pnpm run build
```

Expected: Build succeeds with no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/prototype/ frontend/src/App.tsx
git commit -m "Add prototype layout, routing, StatusBar, and placeholder pages"
```

---

## Task 9: Login Page

**Files:**
- Modify: `frontend/src/prototype/pages/LoginPage.tsx`

- [ ] **Step 1: Implement LoginPage**

Replace `frontend/src/prototype/pages/LoginPage.tsx`:

```tsx
import { useState } from "react"
import { Navigate } from "react-router-dom"
import { useAuth } from "../../core/hooks/useAuth"
import { useAuthStore } from "../../core/store/authStore"

type Mode = "login" | "setup" | "change-password"

export default function LoginPage() {
  const { login, setup, changePassword, isLoading, error } = useAuth()
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const mustChangePassword = useAuthStore((s) => s.user?.must_change_password)

  const [mode, setMode] = useState<Mode>("login")
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [email, setEmail] = useState("")
  const [pin, setPin] = useState("")
  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [setupResult, setSetupResult] = useState<string | null>(null)

  if (isAuthenticated && !mustChangePassword) {
    return <Navigate to="/dashboard" replace />
  }

  // Force password change mode
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
            <button
              type="button"
              onClick={() => setMode("setup")}
              className="w-full text-center text-sm text-gray-500 hover:text-gray-700"
            >
              First time? Set up master admin
            </button>
          </form>
        )}

        {mode === "setup" && (
          <form onSubmit={handleSetup} className="space-y-4">
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
            <button
              type="button"
              onClick={() => setMode("login")}
              className="w-full text-center text-sm text-gray-500 hover:text-gray-700"
            >
              Back to login
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

- [ ] **Step 2: Commit**

```bash
git add frontend/src/prototype/pages/LoginPage.tsx
git commit -m "Implement LoginPage with login, setup, and password change modes"
```

---

## Task 10: EventLog Component and Dashboard Page

**Files:**
- Create: `frontend/src/prototype/components/EventLog.tsx`
- Modify: `frontend/src/prototype/pages/DashboardPage.tsx`

- [ ] **Step 1: Create EventLog component**

Create `frontend/src/prototype/components/EventLog.tsx`:

```tsx
import { useEffect, useRef, useState } from "react"
import { useEventBus } from "../../core/hooks/useEventBus"
import type { BaseEvent } from "../../core/types/events"

const categoryColours: Record<string, string> = {
  user: "text-blue-600 bg-blue-50",
  llm: "text-green-600 bg-green-50",
  persona: "text-purple-600 bg-purple-50",
  setting: "text-orange-600 bg-orange-50",
  audit: "text-gray-600 bg-gray-50",
  error: "text-red-600 bg-red-50",
}

function getCategoryColour(eventType: string): string {
  const prefix = eventType.split(".")[0]
  return categoryColours[prefix] ?? "text-gray-600 bg-gray-50"
}

function formatTimestamp(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString()
  } catch {
    return ts
  }
}

interface EventRowProps {
  event: BaseEvent
}

function EventRow({ event }: EventRowProps) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="border-b border-gray-100 px-3 py-2 text-sm">
      <div
        className="flex cursor-pointer items-center gap-3"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="w-20 shrink-0 text-xs text-gray-400">
          {formatTimestamp(event.timestamp)}
        </span>
        <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${getCategoryColour(event.type)}`}>
          {event.type}
        </span>
        <span className="text-xs text-gray-400">{event.scope}</span>
        <span className="ml-auto text-xs text-gray-300">{expanded ? "▼" : "▶"}</span>
      </div>
      {expanded && (
        <div className="mt-2 ml-20">
          <div className="text-xs text-gray-400 mb-1">
            id: {event.id} | correlation: {event.correlation_id} | seq: {event.sequence}
          </div>
          <pre className="rounded bg-gray-50 p-2 text-xs text-gray-700 overflow-auto max-h-48">
            {JSON.stringify(event.payload, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}

interface EventLogProps {
  maxHeight?: string
  filter?: string
}

export default function EventLog({ maxHeight = "calc(100vh - 300px)", filter }: EventLogProps) {
  const { events, clear } = useEventBus(filter ?? "*", 500)
  const [paused, setPaused] = useState(false)
  const [typeFilter, setTypeFilter] = useState("")
  const containerRef = useRef<HTMLDivElement>(null)

  const displayedEvents = typeFilter
    ? events.filter((e) => e.type.includes(typeFilter))
    : events

  useEffect(() => {
    if (!paused && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [displayedEvents.length, paused])

  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <div className="flex items-center justify-between border-b border-gray-200 px-4 py-2">
        <h3 className="text-sm font-medium">Event Log</h3>
        <div className="flex items-center gap-2">
          <input
            type="text"
            placeholder="Filter by type..."
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="rounded border border-gray-200 px-2 py-1 text-xs focus:border-blue-500 focus:outline-none"
          />
          <span className="text-xs text-gray-400">{displayedEvents.length} events</span>
          <button
            onClick={() => setPaused(!paused)}
            className={`rounded px-2 py-1 text-xs ${paused ? "bg-amber-100 text-amber-700" : "bg-gray-100 text-gray-600"}`}
          >
            {paused ? "Paused" : "Pause"}
          </button>
          <button
            onClick={clear}
            className="rounded bg-gray-100 px-2 py-1 text-xs text-gray-600 hover:bg-gray-200"
          >
            Clear
          </button>
        </div>
      </div>
      <div ref={containerRef} className="overflow-auto" style={{ maxHeight }}>
        {displayedEvents.length === 0 ? (
          <p className="p-4 text-center text-sm text-gray-400">No events yet</p>
        ) : (
          displayedEvents.map((event) => <EventRow key={event.id} event={event} />)
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Implement DashboardPage**

Replace `frontend/src/prototype/pages/DashboardPage.tsx`:

```tsx
import { useAuthStore } from "../../core/store/authStore"
import { useEventStore } from "../../core/store/eventStore"
import EventLog from "../components/EventLog"

export default function DashboardPage() {
  const user = useAuthStore((s) => s.user)
  const status = useEventStore((s) => s.status)
  const lastSequence = useEventStore((s) => s.lastSequence)

  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold">Dashboard</h2>

      <div className="grid grid-cols-3 gap-4">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-sm text-gray-500">User</p>
          <p className="text-lg font-medium">{user?.display_name || user?.username}</p>
          <p className="text-xs text-gray-400">{user?.role}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-sm text-gray-500">WebSocket</p>
          <p className="text-lg font-medium capitalize">{status}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-sm text-gray-500">Last Sequence</p>
          <p className="text-lg font-medium font-mono">{lastSequence || "—"}</p>
        </div>
      </div>

      <EventLog />
    </div>
  )
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/prototype/components/EventLog.tsx frontend/src/prototype/pages/DashboardPage.tsx
git commit -m "Add EventLog component and DashboardPage"
```

---

## Task 11: Users Page

**Files:**
- Modify: `frontend/src/prototype/pages/UsersPage.tsx`

- [ ] **Step 1: Implement UsersPage**

Replace `frontend/src/prototype/pages/UsersPage.tsx`:

```tsx
import { useState } from "react"
import { useUsers } from "../../core/hooks/useUsers"
import type { CreateUserRequest, UpdateUserRequest, UserDto } from "../../core/types/auth"

function CreateUserForm({ onCreate }: { onCreate: (data: CreateUserRequest) => Promise<void> }) {
  const [username, setUsername] = useState("")
  const [email, setEmail] = useState("")
  const [displayName, setDisplayName] = useState("")
  const [role, setRole] = useState("user")
  const [result, setResult] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setResult(null)
    try {
      await onCreate({ username, email, display_name: displayName, role })
      setUsername("")
      setEmail("")
      setDisplayName("")
      setRole("user")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create user")
    }
  }

  return (
    <form onSubmit={handleSubmit} className="rounded-lg border border-gray-200 bg-white p-4 space-y-3">
      <h3 className="text-sm font-medium">Create User</h3>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {result && <p className="text-sm text-green-600">{result}</p>}
      <div className="grid grid-cols-2 gap-3">
        <input
          type="text" placeholder="Username" value={username}
          onChange={(e) => setUsername(e.target.value)} required
          className="rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
        />
        <input
          type="email" placeholder="Email" value={email}
          onChange={(e) => setEmail(e.target.value)} required
          className="rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
        />
        <input
          type="text" placeholder="Display Name" value={displayName}
          onChange={(e) => setDisplayName(e.target.value)} required
          className="rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
        />
        <select
          value={role} onChange={(e) => setRole(e.target.value)}
          className="rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
        >
          <option value="user">User</option>
          <option value="admin">Admin</option>
        </select>
      </div>
      <button type="submit" className="rounded bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-700">
        Create
      </button>
    </form>
  )
}

function UserRow({
  user,
  onUpdate,
  onDeactivate,
  onResetPassword,
}: {
  user: UserDto
  onUpdate: (id: string, data: UpdateUserRequest) => Promise<void>
  onDeactivate: (id: string) => Promise<void>
  onResetPassword: (id: string) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [displayName, setDisplayName] = useState(user.display_name)
  const [email, setEmail] = useState(user.email)
  const [generatedPassword, setGeneratedPassword] = useState<string | null>(null)

  const handleSave = async () => {
    await onUpdate(user.id, { display_name: displayName, email })
    setEditing(false)
  }

  const handleReset = async () => {
    setGeneratedPassword(null)
    await onResetPassword(user.id)
  }

  return (
    <tr className="border-b border-gray-100">
      <td className="px-4 py-2 text-sm">{user.username}</td>
      <td className="px-4 py-2 text-sm">
        {editing ? (
          <input
            value={displayName} onChange={(e) => setDisplayName(e.target.value)}
            className="rounded border border-gray-300 px-2 py-1 text-sm w-full"
          />
        ) : (
          user.display_name
        )}
      </td>
      <td className="px-4 py-2 text-sm">
        {editing ? (
          <input
            value={email} onChange={(e) => setEmail(e.target.value)}
            className="rounded border border-gray-300 px-2 py-1 text-sm w-full"
          />
        ) : (
          user.email
        )}
      </td>
      <td className="px-4 py-2 text-sm">
        <span className="rounded bg-gray-100 px-2 py-0.5 text-xs">{user.role}</span>
      </td>
      <td className="px-4 py-2 text-sm">
        <span className={`rounded px-2 py-0.5 text-xs ${user.is_active ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>
          {user.is_active ? "Active" : "Inactive"}
        </span>
      </td>
      <td className="px-4 py-2 text-sm space-x-1">
        {editing ? (
          <>
            <button onClick={handleSave} className="rounded bg-green-100 px-2 py-1 text-xs text-green-700 hover:bg-green-200">Save</button>
            <button onClick={() => setEditing(false)} className="rounded bg-gray-100 px-2 py-1 text-xs hover:bg-gray-200">Cancel</button>
          </>
        ) : (
          <>
            <button onClick={() => setEditing(true)} className="rounded bg-gray-100 px-2 py-1 text-xs hover:bg-gray-200">Edit</button>
            {user.is_active && user.role !== "master_admin" && (
              <button onClick={() => onDeactivate(user.id)} className="rounded bg-red-100 px-2 py-1 text-xs text-red-700 hover:bg-red-200">Deactivate</button>
            )}
            <button onClick={handleReset} className="rounded bg-amber-100 px-2 py-1 text-xs text-amber-700 hover:bg-amber-200">Reset PW</button>
          </>
        )}
        {generatedPassword && (
          <span className="ml-2 text-xs font-mono text-green-700">PW: {generatedPassword}</span>
        )}
      </td>
    </tr>
  )
}

export default function UsersPage() {
  const { users, total, isLoading, error, create, update, deactivate, resetPassword } = useUsers()

  const handleCreate = async (data: CreateUserRequest) => {
    const res = await create(data)
    alert(`User created. Generated password: ${res.generated_password}`)
  }

  const handleResetPassword = async (userId: string) => {
    const res = await resetPassword(userId)
    alert(`Password reset. New password: ${res.generated_password}`)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Users</h2>
        <span className="text-sm text-gray-400">{total} total</span>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <CreateUserForm onCreate={handleCreate} />

      <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-200 bg-gray-50">
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Username</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Display Name</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Email</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Role</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Status</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && users.length === 0 ? (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-sm text-gray-400">Loading...</td></tr>
            ) : users.length === 0 ? (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-sm text-gray-400">No users</td></tr>
            ) : (
              users.map((u) => (
                <UserRow key={u.id} user={u} onUpdate={update} onDeactivate={deactivate} onResetPassword={handleResetPassword} />
              ))
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
git add frontend/src/prototype/pages/UsersPage.tsx
git commit -m "Implement UsersPage with CRUD and live event updates"
```

---

## Task 12: LLM Page

**Files:**
- Modify: `frontend/src/prototype/pages/LlmPage.tsx`

- [ ] **Step 1: Implement LlmPage**

Replace `frontend/src/prototype/pages/LlmPage.tsx`:

```tsx
import { useState } from "react"
import { useLlm } from "../../core/hooks/useLlm"
import type { ModelMetaDto } from "../../core/types/llm"

type Tab = "credentials" | "models" | "config"

function CredentialsTab() {
  const { providers, setKey, removeKey, testKey, isLoading } = useLlm()
  const [editingProvider, setEditingProvider] = useState<string | null>(null)
  const [apiKey, setApiKey] = useState("")
  const [testResult, setTestResult] = useState<{ provider: string; valid: boolean } | null>(null)

  const handleSetKey = async (providerId: string) => {
    await setKey(providerId, { api_key: apiKey })
    setEditingProvider(null)
    setApiKey("")
  }

  const handleTest = async (providerId: string) => {
    if (!apiKey) return
    const res = await testKey(providerId, { api_key: apiKey })
    setTestResult({ provider: providerId, valid: res.valid })
  }

  return (
    <div className="space-y-3">
      {providers.map((p) => (
        <div key={p.provider_id} className="rounded border border-gray-200 bg-white p-4">
          <div className="flex items-center justify-between">
            <div>
              <span className="font-medium text-sm">{p.display_name}</span>
              <span className="ml-2 text-xs text-gray-400">{p.provider_id}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className={`rounded px-2 py-0.5 text-xs ${p.is_configured ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"}`}>
                {p.is_configured ? "Configured" : "Not configured"}
              </span>
              {p.is_configured && (
                <button onClick={() => removeKey(p.provider_id)} className="rounded bg-red-100 px-2 py-1 text-xs text-red-700 hover:bg-red-200">
                  Remove
                </button>
              )}
              <button onClick={() => { setEditingProvider(p.provider_id); setApiKey(""); setTestResult(null) }} className="rounded bg-gray-100 px-2 py-1 text-xs hover:bg-gray-200">
                {p.is_configured ? "Change Key" : "Set Key"}
              </button>
            </div>
          </div>
          {editingProvider === p.provider_id && (
            <div className="mt-3 flex items-center gap-2">
              <input
                type="password" placeholder="API Key" value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                className="flex-1 rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
              />
              <button onClick={() => handleTest(p.provider_id)} className="rounded bg-amber-100 px-3 py-1.5 text-xs text-amber-700 hover:bg-amber-200">
                Test
              </button>
              <button onClick={() => handleSetKey(p.provider_id)} className="rounded bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-700">
                Save
              </button>
              <button onClick={() => setEditingProvider(null)} className="rounded bg-gray-100 px-3 py-1.5 text-xs hover:bg-gray-200">
                Cancel
              </button>
              {testResult?.provider === p.provider_id && (
                <span className={`text-xs ${testResult.valid ? "text-green-600" : "text-red-600"}`}>
                  {testResult.valid ? "Valid" : "Invalid"}
                </span>
              )}
            </div>
          )}
        </div>
      ))}
      {providers.length === 0 && !isLoading && (
        <p className="text-sm text-gray-400">No providers available</p>
      )}
    </div>
  )
}

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
        {providers.filter((p) => p.is_configured).map((p) => (
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
        <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-200 bg-gray-50">
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Model</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Context</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Capabilities</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Rating</th>
              </tr>
            </thead>
            <tbody>
              {providerModels.map((m) => (
                <tr key={m.unique_id} className="border-b border-gray-100">
                  <td className="px-4 py-2">
                    <div className="text-sm font-medium">{m.display_name}</div>
                    <div className="text-xs text-gray-400">{m.model_id}</div>
                  </td>
                  <td className="px-4 py-2 text-sm">{(m.context_window / 1024).toFixed(0)}k</td>
                  <td className="px-4 py-2 text-sm space-x-1">
                    {m.supports_reasoning && <span className="rounded bg-blue-50 px-1.5 py-0.5 text-xs text-blue-600">reasoning</span>}
                    {m.supports_vision && <span className="rounded bg-green-50 px-1.5 py-0.5 text-xs text-green-600">vision</span>}
                    {m.supports_tool_calls && <span className="rounded bg-purple-50 px-1.5 py-0.5 text-xs text-purple-600">tools</span>}
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
                </tr>
              ))}
              {providerModels.length === 0 && (
                <tr><td colSpan={4} className="px-4 py-8 text-center text-sm text-gray-400">No models loaded</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function UserConfigTab() {
  const { userConfigs, providers, models, fetchModels, setUserConfig, deleteUserConfig } = useLlm()
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null)

  const handleSelectProvider = (providerId: string) => {
    setSelectedProvider(providerId)
    if (!models.has(providerId)) {
      fetchModels(providerId)
    }
  }

  const providerModels = selectedProvider ? (models.get(selectedProvider) ?? []) : []
  const configMap = new Map(userConfigs.map((c) => [c.model_unique_id, c]))

  const toggleFavourite = async (model: ModelMetaDto) => {
    const current = configMap.get(model.unique_id)
    const [providerId, ...slugParts] = model.unique_id.split(":")
    const modelSlug = slugParts.join(":")
    await setUserConfig(providerId, modelSlug, { is_favourite: !(current?.is_favourite ?? false) })
  }

  const toggleHidden = async (model: ModelMetaDto) => {
    const current = configMap.get(model.unique_id)
    const [providerId, ...slugParts] = model.unique_id.split(":")
    const modelSlug = slugParts.join(":")
    await setUserConfig(providerId, modelSlug, { is_hidden: !(current?.is_hidden ?? false) })
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        {providers.filter((p) => p.is_configured).map((p) => (
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
        <div className="space-y-2">
          {providerModels.map((m) => {
            const config = configMap.get(m.unique_id)
            return (
              <div key={m.unique_id} className="flex items-center justify-between rounded border border-gray-200 bg-white px-4 py-3">
                <div>
                  <span className="text-sm font-medium">{m.display_name}</span>
                  <span className="ml-2 text-xs text-gray-400">{m.model_id}</span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => toggleFavourite(m)}
                    className={`rounded px-2 py-1 text-xs ${config?.is_favourite ? "bg-yellow-100 text-yellow-700" : "bg-gray-100 text-gray-500"}`}
                  >
                    {config?.is_favourite ? "Favourited" : "Favourite"}
                  </button>
                  <button
                    onClick={() => toggleHidden(m)}
                    className={`rounded px-2 py-1 text-xs ${config?.is_hidden ? "bg-gray-300 text-gray-700" : "bg-gray-100 text-gray-500"}`}
                  >
                    {config?.is_hidden ? "Hidden" : "Hide"}
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default function LlmPage() {
  const [tab, setTab] = useState<Tab>("credentials")

  const tabClass = (t: Tab) =>
    `rounded-t px-4 py-2 text-sm ${tab === t ? "bg-white border-b-2 border-blue-600 font-medium" : "text-gray-500 hover:text-gray-700"}`

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">LLM</h2>
      <div className="flex gap-1 border-b border-gray-200">
        <button onClick={() => setTab("credentials")} className={tabClass("credentials")}>Credentials</button>
        <button onClick={() => setTab("models")} className={tabClass("models")}>Models</button>
        <button onClick={() => setTab("config")} className={tabClass("config")}>My Config</button>
      </div>
      {tab === "credentials" && <CredentialsTab />}
      {tab === "models" && <ModelsTab />}
      {tab === "config" && <UserConfigTab />}
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/prototype/pages/LlmPage.tsx
git commit -m "Implement LlmPage with credentials, models, and user config tabs"
```

---

## Task 13: Personas Page

**Files:**
- Modify: `frontend/src/prototype/pages/PersonasPage.tsx`

- [ ] **Step 1: Implement PersonasPage**

Replace `frontend/src/prototype/pages/PersonasPage.tsx`:

```tsx
import { useState } from "react"
import { usePersonas } from "../../core/hooks/usePersonas"
import type { PersonaDto, CreatePersonaRequest, UpdatePersonaRequest } from "../../core/types/persona"

function PersonaForm({
  initial,
  onSubmit,
  onCancel,
  submitLabel,
}: {
  initial?: Partial<PersonaDto>
  onSubmit: (data: CreatePersonaRequest | UpdatePersonaRequest) => Promise<void>
  onCancel: () => void
  submitLabel: string
}) {
  const [name, setName] = useState(initial?.name ?? "")
  const [tagline, setTagline] = useState(initial?.tagline ?? "")
  const [modelUniqueId, setModelUniqueId] = useState(initial?.model_unique_id ?? "")
  const [systemPrompt, setSystemPrompt] = useState(initial?.system_prompt ?? "")
  const [temperature, setTemperature] = useState(initial?.temperature ?? 0.8)
  const [reasoningEnabled, setReasoningEnabled] = useState(initial?.reasoning_enabled ?? false)
  const [colourScheme, setColourScheme] = useState(initial?.colour_scheme ?? "")
  const [displayOrder, setDisplayOrder] = useState(initial?.display_order ?? 0)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    try {
      await onSubmit({
        name,
        tagline,
        model_unique_id: modelUniqueId,
        system_prompt: systemPrompt,
        temperature,
        reasoning_enabled: reasoningEnabled,
        colour_scheme: colourScheme,
        display_order: displayOrder,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : "Operation failed")
    }
  }

  return (
    <form onSubmit={handleSubmit} className="rounded-lg border border-gray-200 bg-white p-4 space-y-3">
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Name</label>
          <input
            type="text" value={name} onChange={(e) => setName(e.target.value)} required
            className="w-full rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Tagline</label>
          <input
            type="text" value={tagline} onChange={(e) => setTagline(e.target.value)} required
            className="w-full rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Model ID</label>
          <input
            type="text" value={modelUniqueId} onChange={(e) => setModelUniqueId(e.target.value)} required
            placeholder="provider:model_slug"
            className="w-full rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Colour Scheme</label>
          <input
            type="text" value={colourScheme} onChange={(e) => setColourScheme(e.target.value)}
            className="w-full rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Temperature ({temperature})</label>
          <input
            type="range" min="0" max="2" step="0.1" value={temperature}
            onChange={(e) => setTemperature(parseFloat(e.target.value))}
            className="w-full"
          />
        </div>
        <div className="flex items-center gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Display Order</label>
            <input
              type="number" value={displayOrder} onChange={(e) => setDisplayOrder(parseInt(e.target.value) || 0)}
              className="w-20 rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>
          <label className="flex items-center gap-2 mt-4">
            <input type="checkbox" checked={reasoningEnabled} onChange={(e) => setReasoningEnabled(e.target.checked)} />
            <span className="text-sm">Reasoning</span>
          </label>
        </div>
      </div>
      <div>
        <label className="block text-xs font-medium text-gray-500 mb-1">System Prompt</label>
        <textarea
          value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)} required rows={4}
          className="w-full rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
        />
      </div>
      <div className="flex gap-2">
        <button type="submit" className="rounded bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-700">
          {submitLabel}
        </button>
        <button type="button" onClick={onCancel} className="rounded bg-gray-100 px-4 py-1.5 text-sm hover:bg-gray-200">
          Cancel
        </button>
      </div>
    </form>
  )
}

function PersonaCard({
  persona,
  onEdit,
  onDelete,
}: {
  persona: PersonaDto
  onEdit: (p: PersonaDto) => void
  onDelete: (id: string) => void
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="flex items-start justify-between">
        <div>
          <h3 className="font-medium text-sm">{persona.name}</h3>
          <p className="text-xs text-gray-500 mt-0.5">{persona.tagline}</p>
        </div>
        <div className="flex gap-1">
          <button onClick={() => onEdit(persona)} className="rounded bg-gray-100 px-2 py-1 text-xs hover:bg-gray-200">Edit</button>
          <button onClick={() => onDelete(persona.id)} className="rounded bg-red-100 px-2 py-1 text-xs text-red-700 hover:bg-red-200">Delete</button>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2 text-xs text-gray-500">
        <span className="rounded bg-gray-50 px-2 py-0.5">{persona.model_unique_id}</span>
        <span className="rounded bg-gray-50 px-2 py-0.5">temp: {persona.temperature}</span>
        {persona.reasoning_enabled && <span className="rounded bg-blue-50 px-2 py-0.5 text-blue-600">reasoning</span>}
        {persona.colour_scheme && <span className="rounded bg-gray-50 px-2 py-0.5">colour: {persona.colour_scheme}</span>}
        <span className="rounded bg-gray-50 px-2 py-0.5">order: {persona.display_order}</span>
      </div>
      <p className="mt-2 text-xs text-gray-400 line-clamp-2">{persona.system_prompt}</p>
    </div>
  )
}

export default function PersonasPage() {
  const { personas, isLoading, error, create, update, remove } = usePersonas()
  const [showCreate, setShowCreate] = useState(false)
  const [editing, setEditing] = useState<PersonaDto | null>(null)

  const handleCreate = async (data: CreatePersonaRequest | UpdatePersonaRequest) => {
    await create(data as CreatePersonaRequest)
    setShowCreate(false)
  }

  const handleUpdate = async (data: CreatePersonaRequest | UpdatePersonaRequest) => {
    if (!editing) return
    await update(editing.id, data as UpdatePersonaRequest)
    setEditing(null)
  }

  const handleDelete = async (id: string) => {
    if (confirm("Delete this persona?")) {
      await remove(id)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Personas</h2>
        <button
          onClick={() => { setShowCreate(true); setEditing(null) }}
          className="rounded bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-700"
        >
          Create Persona
        </button>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {showCreate && (
        <PersonaForm onSubmit={handleCreate} onCancel={() => setShowCreate(false)} submitLabel="Create" />
      )}

      {editing && (
        <PersonaForm initial={editing} onSubmit={handleUpdate} onCancel={() => setEditing(null)} submitLabel="Update" />
      )}

      {isLoading && personas.length === 0 ? (
        <p className="text-sm text-gray-400">Loading...</p>
      ) : personas.length === 0 ? (
        <p className="text-sm text-gray-400">No personas yet</p>
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {personas.map((p) => (
            <PersonaCard key={p.id} persona={p} onEdit={setEditing} onDelete={handleDelete} />
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/prototype/pages/PersonasPage.tsx
git commit -m "Implement PersonasPage with CRUD and live event updates"
```

---

## Task 14: Admin Page

**Files:**
- Modify: `frontend/src/prototype/pages/AdminPage.tsx`

- [ ] **Step 1: Implement AdminPage**

Replace `frontend/src/prototype/pages/AdminPage.tsx`:

```tsx
import { useState } from "react"
import { useSettings } from "../../core/hooks/useSettings"
import { useLlm } from "../../core/hooks/useLlm"
import type { ModelMetaDto, ModelRating } from "../../core/types/llm"

type Tab = "settings" | "curation"

function SettingsTab() {
  const { settings, isLoading, error, set, remove } = useSettings()
  const [newKey, setNewKey] = useState("")
  const [newValue, setNewValue] = useState("")
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [editValue, setEditValue] = useState("")

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    await set(newKey, { value: newValue })
    setNewKey("")
    setNewValue("")
  }

  const handleUpdate = async (key: string) => {
    await set(key, { value: editValue })
    setEditingKey(null)
  }

  const handleDelete = async (key: string) => {
    if (confirm(`Delete setting "${key}"?`)) {
      await remove(key)
    }
  }

  return (
    <div className="space-y-4">
      {error && <p className="text-sm text-red-600">{error}</p>}

      <form onSubmit={handleCreate} className="flex gap-2">
        <input
          type="text" placeholder="Key" value={newKey} onChange={(e) => setNewKey(e.target.value)} required
          className="rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
        />
        <input
          type="text" placeholder="Value" value={newValue} onChange={(e) => setNewValue(e.target.value)} required
          className="flex-1 rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
        />
        <button type="submit" className="rounded bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-700">
          Add
        </button>
      </form>

      <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-200 bg-gray-50">
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Key</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Value</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Updated</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-500">Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && settings.length === 0 ? (
              <tr><td colSpan={4} className="px-4 py-8 text-center text-sm text-gray-400">Loading...</td></tr>
            ) : settings.length === 0 ? (
              <tr><td colSpan={4} className="px-4 py-8 text-center text-sm text-gray-400">No settings</td></tr>
            ) : (
              settings.map((s) => (
                <tr key={s.key} className="border-b border-gray-100">
                  <td className="px-4 py-2 text-sm font-mono">{s.key}</td>
                  <td className="px-4 py-2 text-sm">
                    {editingKey === s.key ? (
                      <input
                        value={editValue} onChange={(e) => setEditValue(e.target.value)}
                        className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
                      />
                    ) : (
                      <span className="font-mono">{s.value}</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-400">
                    {new Date(s.updated_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2 text-sm space-x-1">
                    {editingKey === s.key ? (
                      <>
                        <button onClick={() => handleUpdate(s.key)} className="rounded bg-green-100 px-2 py-1 text-xs text-green-700">Save</button>
                        <button onClick={() => setEditingKey(null)} className="rounded bg-gray-100 px-2 py-1 text-xs">Cancel</button>
                      </>
                    ) : (
                      <>
                        <button onClick={() => { setEditingKey(s.key); setEditValue(s.value) }} className="rounded bg-gray-100 px-2 py-1 text-xs hover:bg-gray-200">Edit</button>
                        <button onClick={() => handleDelete(s.key)} className="rounded bg-red-100 px-2 py-1 text-xs text-red-700 hover:bg-red-200">Delete</button>
                      </>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function CurationTab() {
  const { providers, models, fetchModels, setCuration, removeCuration } = useLlm()
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null)

  const handleSelectProvider = (providerId: string) => {
    setSelectedProvider(providerId)
    if (!models.has(providerId)) {
      fetchModels(providerId)
    }
  }

  const providerModels: ModelMetaDto[] = selectedProvider ? (models.get(selectedProvider) ?? []) : []

  const handleSetRating = async (model: ModelMetaDto, rating: ModelRating) => {
    await setCuration(model.provider_id, model.model_id, {
      overall_rating: rating,
      hidden: model.curation?.hidden ?? false,
      admin_description: model.curation?.admin_description ?? null,
    })
  }

  const handleToggleHidden = async (model: ModelMetaDto) => {
    const hidden = !(model.curation?.hidden ?? false)
    await setCuration(model.provider_id, model.model_id, {
      overall_rating: model.curation?.overall_rating ?? "available",
      hidden,
      admin_description: model.curation?.admin_description ?? null,
    })
  }

  const handleRemoveCuration = async (model: ModelMetaDto) => {
    await removeCuration(model.provider_id, model.model_id)
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        {providers.filter((p) => p.is_configured).map((p) => (
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
        <div className="space-y-2">
          {providerModels.map((m) => (
            <div key={m.unique_id} className="rounded border border-gray-200 bg-white p-4">
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-sm font-medium">{m.display_name}</span>
                  <span className="ml-2 text-xs text-gray-400">{m.model_id}</span>
                </div>
                <div className="flex items-center gap-2">
                  {(["available", "recommended", "not_recommended"] as ModelRating[]).map((rating) => (
                    <button
                      key={rating}
                      onClick={() => handleSetRating(m, rating)}
                      className={`rounded px-2 py-1 text-xs ${
                        m.curation?.overall_rating === rating
                          ? rating === "recommended" ? "bg-green-200 text-green-800"
                            : rating === "not_recommended" ? "bg-red-200 text-red-800"
                            : "bg-blue-200 text-blue-800"
                          : "bg-gray-100 text-gray-500 hover:bg-gray-200"
                      }`}
                    >
                      {rating}
                    </button>
                  ))}
                  <button
                    onClick={() => handleToggleHidden(m)}
                    className={`rounded px-2 py-1 text-xs ${m.curation?.hidden ? "bg-gray-300 text-gray-700" : "bg-gray-100 text-gray-500"}`}
                  >
                    {m.curation?.hidden ? "Hidden" : "Visible"}
                  </button>
                  {m.curation && (
                    <button
                      onClick={() => handleRemoveCuration(m)}
                      className="rounded bg-red-100 px-2 py-1 text-xs text-red-700 hover:bg-red-200"
                    >
                      Clear
                    </button>
                  )}
                </div>
              </div>
              {m.curation?.admin_description && (
                <p className="mt-1 text-xs text-gray-400">{m.curation.admin_description}</p>
              )}
            </div>
          ))}
          {providerModels.length === 0 && (
            <p className="text-sm text-gray-400">No models loaded</p>
          )}
        </div>
      )}
    </div>
  )
}

export default function AdminPage() {
  const [tab, setTab] = useState<Tab>("settings")

  const tabClass = (t: Tab) =>
    `rounded-t px-4 py-2 text-sm ${tab === t ? "bg-white border-b-2 border-blue-600 font-medium" : "text-gray-500 hover:text-gray-700"}`

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Admin</h2>
      <div className="flex gap-1 border-b border-gray-200">
        <button onClick={() => setTab("settings")} className={tabClass("settings")}>Settings</button>
        <button onClick={() => setTab("curation")} className={tabClass("curation")}>Model Curation</button>
      </div>
      {tab === "settings" && <SettingsTab />}
      {tab === "curation" && <CurationTab />}
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/prototype/pages/AdminPage.tsx
git commit -m "Implement AdminPage with settings and model curation tabs"
```

---

## Task 15: Final Build Verification and Cleanup

**Files:**
- Possibly modify: any files with TypeScript errors

- [ ] **Step 1: Run TypeScript type check**

```bash
cd frontend && pnpm exec tsc --noEmit
```

Expected: No errors. If there are errors, fix them.

- [ ] **Step 2: Run build**

```bash
cd frontend && pnpm run build
```

Expected: Build succeeds. Output in `frontend/dist/`.

- [ ] **Step 3: Run dev server and smoke test**

```bash
cd frontend && pnpm run dev
```

Open `http://localhost:5173`:
- LoginPage should render
- No console errors
- Tailwind styles applied (inputs have borders, buttons have colours)

Press Ctrl+C to stop.

- [ ] **Step 4: Verify .gitignore**

Ensure `frontend/.gitignore` includes:
```
node_modules
dist
.env
```

- [ ] **Step 5: Final commit**

```bash
git add frontend/
git commit -m "Complete frontend prototype: all pages, core hooks, WebSocket, auth flow"
```

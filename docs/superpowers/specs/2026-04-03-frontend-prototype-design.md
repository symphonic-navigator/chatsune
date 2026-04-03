# Frontend Prototype Design

**Date:** 2026-04-03
**Status:** Draft
**Scope:** Two-stage frontend approach -- shared core logic + throwaway prototype UI

---

## Goal

Build a functional frontend prototype that validates the full backend stack end-to-end.
The prototype is intentionally plain -- clean but not designed. It exists to test technical
flows (auth, WebSocket events, CRUD operations) and to produce a reusable core logic layer
that the final, designed frontend will build upon.

### Two-Stage Approach

1. **Now:** Core logic layer (`core/`) + prototype UI (`prototype/`) -- functional, not pretty
2. **Later:** Replace `prototype/` with a fully designed UI/UX -- the core layer stays

### What is Shared vs. Throwaway

| Layer | Location | Lifespan |
|---|---|---|
| TypeScript types | `core/types/` | Permanent |
| WebSocket client + Event Bus | `core/websocket/` | Permanent |
| REST API client | `core/api/` | Permanent |
| React Hooks | `core/hooks/` | Permanent |
| Zustand stores | `core/store/` | Permanent |
| Prototype pages + components | `prototype/` | Replaced when real UI ships |

---

## Project Structure

```
frontend/
  index.html
  vite.config.ts
  tailwind.config.ts
  tsconfig.json
  package.json                    (pnpm)
  .env.example
  src/
    main.tsx                      App entry point
    App.tsx                       Router setup

    core/                         SHARED LOGIC (permanent)
      types/
        auth.ts                   UserDto, LoginRequest, TokenResponse, etc.
        events.ts                 BaseEvent, ErrorEvent, Topics constants
        llm.ts                    ProviderCredentialDto, ModelMetaDto, UserModelConfigDto
        persona.ts                PersonaDto, CreatePersonaRequest, etc.
        settings.ts               SettingDto
      hooks/
        useAuth.ts                Login, logout, token state, isAuthenticated
        useWebSocket.ts           Connection status, last event
        useEventBus.ts            Subscribe to event types, wildcard support
        useUsers.ts               User CRUD, live event updates (admin)
        useLlm.ts                 Credentials, models, user config
        usePersonas.ts            Persona CRUD, live event updates
        useSettings.ts            Global settings CRUD (admin)
      api/
        client.ts                 Fetch wrapper with auth headers, auto-refresh on 401
        auth.ts                   Login, refresh, change password endpoints
        users.ts                  User CRUD endpoints
        llm.ts                    Credentials, models, curation endpoints
        personas.ts               Persona CRUD endpoints
        settings.ts               Settings CRUD endpoints
      websocket/
        connection.ts             Connect, reconnect, token refresh handling
        eventBus.ts               Subscribe/unsubscribe on event types
      store/
        authStore.ts              User, tokens, login status
        eventStore.ts             Last sequence counter, connection status

    prototype/                    PROTOTYPE UI (throwaway)
      layouts/
        PrototypeLayout.tsx       Sidebar + content area
      pages/
        LoginPage.tsx
        DashboardPage.tsx         Overview + EventLog
        UsersPage.tsx             User CRUD (admin/master_admin only)
        LlmPage.tsx               Credentials, model catalogue, user config
        PersonasPage.tsx          Persona CRUD
        AdminPage.tsx             Global settings + model curation (admin only)
      components/
        EventLog.tsx              Live event stream with filtering
        StatusBar.tsx             Connection status, user info
```

---

## Core Layer Detail

### TypeScript Types (`core/types/`)

Manually derived from Python Pydantic models in `shared/`. No code generator -- the
contract surface is small (~20 types) and changes infrequently. If this becomes
error-prone, a generator can be introduced later.

All types mirror the Python DTOs exactly: same field names, same structure, translated
to TypeScript idioms (interfaces, union types, string literals for enums).

Topics constants are defined as a `const` object mirroring `shared/topics.py`.

### WebSocket Connection (`core/websocket/connection.ts`)

- Connects to `${VITE_WS_URL}/ws?token=<jwt>`
- Automatic reconnect with exponential backoff: 1s, 2s, 4s, ... max 30s
- On reconnect: appends `&since=<lastSequence>` for catchup from Redis Streams
- Listens for `token.expiring_soon` event -- triggers token refresh via REST, then reconnects with new token
- Exposes connection status: `connecting | connected | disconnected | reconnecting`

### Event Bus (`core/websocket/eventBus.ts`)

- Receives all events from the WebSocket connection
- Components subscribe by event type: `eventBus.on("persona.created", callback)`
- Wildcard support: `eventBus.on("*", callback)` for the EventLog
- Tracks `lastSequence` for reconnect catchup
- No frontend persistence -- events are transient, state lives in Zustand stores and hook-local state

### REST Client (`core/api/client.ts`)

- Thin fetch wrapper, auto-sets `Authorization: Bearer <token>` from auth store
- Base URL from `VITE_API_URL` environment variable
- On 401: attempts token refresh via `POST /api/auth/refresh`, retries original request once
- Returns typed responses via generics

### Zustand Stores (`core/store/`)

Only two global stores -- kept intentionally slim:

- **authStore:** Current user (UserDto | null), access token, login/logout actions, `isAuthenticated` derived state
- **eventStore:** Last seen sequence number, WebSocket connection status

Module-specific data (users list, personas, LLM models) is NOT stored globally.
It lives locally in the respective hooks. For example, `usePersonas()` fetches on
mount and updates itself via event bus subscriptions. This avoids a bloated global
store and keeps data ownership clear.

### Hooks as Public API (`core/hooks/`)

Every hook encapsulates: REST calls + event bus subscription + local state.
Prototype components (and later the real UI) only interact through these hooks.

```typescript
// Auth
const { user, isAuthenticated, login, logout, isLoading } = useAuth()

// WebSocket status
const { status, lastEvent } = useWebSocket()

// Event subscriptions
const { events } = useEventBus("*")          // all events
const { events } = useEventBus("persona.*")  // filtered

// Module data
const { users, create, update, deactivate, isLoading } = useUsers()
const { personas, create, update, remove, isLoading } = usePersonas()
const { credentials, models, userConfig, ... } = useLlm()
const { settings, update, isLoading } = useSettings()
```

### Auth Flow (Complete Lifecycle)

1. **Login:** `useAuth().login(username, password)` calls REST endpoint. Access token stored in Zustand auth store. Refresh token arrives as httpOnly cookie (set by backend, not accessible to JS).
2. **Every REST request:** `client.ts` reads token from auth store, sets `Authorization` header.
3. **Token expiry (REST):** 401 response triggers `POST /api/auth/refresh` (cookie sent automatically). New access token stored. Original request retried once.
4. **Token expiry (WebSocket):** Backend sends `token.expiring_soon` event 2 minutes before expiry. Frontend calls refresh endpoint, gets new token, reconnects WebSocket with new token.
5. **Logout:** Clear token from auth store, close WebSocket connection, redirect to login.
6. **First login (must_change_password):** After successful login, if `user.must_change_password` is true, redirect to password change form before allowing access.

---

## Prototype UI Detail

### Visual Style

Clean but deliberately undesigned. Tailwind utility classes for spacing, typography,
and basic colour. No component library, no design tokens, no custom theme. The visual
plainness signals "this is a development intermediate."

- White/grey background, dark text
- System font stack
- Subtle borders and shadows for card separation
- Colour accents only for status indicators and the EventLog

### Layout

**PrototypeLayout:** Fixed sidebar (left) + scrollable content area (right).

Sidebar contains:
- Navigation links: Dashboard, Users (admin only), LLM, Personas, Admin (admin only)
- Bottom: connection status indicator (green/red dot), current user + role, logout button

**StatusBar:** Top of content area. Shows WebSocket connection status, current user display name, and role badge.

### Pages

**LoginPage:**
- Username + password fields, login button
- Error display on failed login
- Password change form when `must_change_password` is true
- No "forgot password", no registration -- prototype scope

**DashboardPage:**
- Top: quick stats (number of users, personas, connection uptime)
- Bottom: EventLog component (takes up most of the page)

**UsersPage (admin/master_admin only):**
- Table of all users with columns: username, display name, role, active status
- Create user button opens inline form
- Edit/deactivate actions per row
- Live updates via `user.created`, `user.updated` events

**LlmPage:**
- Tab 1 -- Credentials: list provider credentials, set/test/remove API keys
- Tab 2 -- Models: browsable model catalogue (only curated/enabled models visible to non-admins)
- Tab 3 -- My Config: per-model favourites, hidden, notes, system prompt addition

**PersonasPage:**
- List/card view of all personas for the current user
- Create button, edit form with all fields: name, tagline, model, system prompt, temperature, reasoning, colour scheme, display order
- Live updates via `persona.created`, `persona.updated`, `persona.deleted` events

**AdminPage (admin/master_admin only):**
- Tab 1 -- Settings: key-value table, editable values, live updates via `setting.updated`
- Tab 2 -- Model Curation: enable/disable models for the platform, set display names

### EventLog Component

The centrepiece debug tool for the prototype phase.

- Subscribes to `eventBus.on("*")`
- Displays per event: timestamp, event type, scope, correlation ID, payload (expandable)
- Colour coding by category: auth=blue, LLM=green, persona=purple, settings/admin=orange, error=red
- Filterable by event type and scope
- Auto-scrolls to latest, with pause button
- Available on DashboardPage as main content, potentially embeddable elsewhere

---

## Dependencies

### Runtime

| Package | Purpose |
|---|---|
| `react` + `react-dom` | UI framework |
| `react-router-dom` | Client-side routing |
| `zustand` | State management (~2kb, zero boilerplate) |

### Dev

| Package | Purpose |
|---|---|
| `vite` | Build tool |
| `typescript` | Type checking |
| `tailwindcss` + `@tailwindcss/vite` | Utility-first CSS |
| `eslint` | Linting |

Deliberately minimal. No Axios (fetch is sufficient), no React Query (hooks handle
caching and invalidation via events), no UI component library (Tailwind suffices for
the prototype).

---

## Environment Variables

```
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
```

Provided via `.env.example` with these defaults. `.env` is gitignored.

---

## Scope Boundaries

### In Scope

- Complete auth flow including token refresh and WebSocket token management
- WebSocket connection with reconnect and event catchup
- Event bus with typed subscriptions
- CRUD UI for all backend modules: Users, LLM, Personas, Admin (Settings + Curation)
- Live event-driven updates across all pages
- EventLog debug component

### Out of Scope

- Chat functionality (backend module not yet implemented)
- Any design work, design tokens, or theming beyond basic Tailwind
- Internationalisation
- Mobile responsiveness (desktop-only prototype)
- Testing (prototype is throwaway; core layer tests come with the real frontend)
- Code generation for TypeScript types
- SSR or any server-side rendering

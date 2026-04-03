# Prototype UI Improvements -- Design Spec

Date: 2026-04-03

## Context

After the first prototype test run, 8 improvement points were identified.
Two quick fixes (sidebar "LLM" → "Models" rename, models visible without API key)
have already been applied. This spec covers the remaining 6 points, consolidated
into 5 work packages.

Reference: the previous prototype at `/home/chris/workspace/chat-client-02/frontend`
was analysed for proven patterns. Several patterns (ModelBrowser filters, toast system,
auth status detection) are adapted from there.

---

## Work Package 1: Auto-detect Master Admin

### Problem

The LoginPage currently shows a manual toggle button ("First time? Set up master admin")
to switch between login and setup mode. The previous prototype auto-detected this.

### Backend

New endpoint in the User module (`backend/modules/user/_handlers.py`):

```
GET /api/auth/status
```

- No authentication required (must be callable before login)
- Checks whether at least one user with `role=master_admin` exists in the database
- Response: `{ "is_setup_complete": bool }`
- Exposed via `backend/modules/user/__init__.py`

### Frontend

Changes to `frontend/src/prototype/pages/LoginPage.tsx`:

- On mount: fetch `GET /api/auth/status`
- While loading: show spinner (no login form, no setup form)
- `is_setup_complete === false` → show setup form automatically
- `is_setup_complete === true` → show login form
- Fetch failure → fallback to login form
- Remove the manual "First time?" toggle button entirely

---

## Work Package 2: Toast Notification System

### Problem

The prototype uses `alert()` for user feedback (generated passwords, confirmations).
There is no global notification system.

### Scope

Toast-only system. Bell icon with flyout and persistent notification history are
deferred to FOR_LATER.md.

### Store

New Zustand store at `frontend/src/core/store/notificationStore.ts`:

```typescript
interface AppNotification {
  id: string              // crypto.randomUUID()
  level: 'success' | 'error' | 'info'
  title: string
  message: string
  timestamp: number
  dismissed: boolean
}

interface NotificationState {
  notifications: AppNotification[]
  addNotification: (n: Omit<AppNotification, 'id' | 'timestamp' | 'dismissed'>) => void
  dismissToast: (id: string) => void
}
```

- Max 20 notifications in memory (FIFO, oldest removed)
- New notifications prepended (most recent first)

### Component

New component at `frontend/src/prototype/components/Toasts.tsx`:

- Fixed position, bottom-right
- Max 3 visible toasts at once
- Auto-dismiss: success/info after 5 seconds, errors persist until manually closed
- Click anywhere on toast to dismiss
- Colour scheme (Catppuccin-inspired):
  - Success: green accent (#a6e3a1)
  - Error: red accent (#f38ba8)
  - Info: neutral accent

### Integration

- Mount `<Toasts />` once in `PrototypeLayout.tsx`
- Callable everywhere via `useNotificationStore().addNotification()`
- Replace all `alert()` calls:
  - `UsersPage`: generated passwords → success toast
  - `LlmPage`: key test results → success/error toast

### Deferred (FOR_LATER.md)

- NotificationBell component with unread badge
- NotificationFlyout with persistent history
- Backend-driven notifications via WebSocket events

---

## Work Package 3: ModelBrowser with Filters

### Problem

The Models page shows a plain table without search or filtering. The previous
prototype had a full ModelBrowser with comprehensive filters. We build a reduced
version that covers the essential use cases.

### Component

New reusable component at `frontend/src/prototype/components/ModelBrowser.tsx`:

**Props:**

| Prop | Type | Description |
|------|------|-------------|
| `models` | `ModelMetaDto[]` | Models to display |
| `userConfigs` | `UserModelConfigDto[]` | User's favourite/hidden configs |
| `onSelect` | `(model) => void` | Optional selection callback (for future chat) |
| `onToggleFavourite` | `(model) => void` | Favourite toggle |
| `onEditConfig` | `(model) => void` | Open config editing |
| `selectedModelId` | `string` | Highlight selected model |
| `showConfigActions` | `boolean` | Show favourite/hide buttons (default true) |

**Filter bar (above table):**

| Filter | Type | Behaviour |
|--------|------|-----------|
| Text search | Input | Filters on `display_name` and `model_id` |
| Provider | Single-select buttons | Derived from models in list |
| Capabilities | Toggle buttons (T/V/R) | Tools (green), Vision (blue), Reasoning (yellow) |
| Favourites | Toggle button | Show only favourited models |

All filters are AND-combined. Filter state is local to the component (useState + useMemo).

**Table columns:**

| Column | Content | Sortable |
|--------|---------|----------|
| Name | `display_name` + `model_id` as subtext | Yes |
| Context | `context_window` displayed as "Xk" | Yes |
| Capabilities | Coloured badges (reasoning, vision, tools) | No |
| Rating | Curation badge or "uncurated" | No |
| Actions | Favourite/Hide buttons (when `showConfigActions`) | No |

Sorting: click column header to toggle asc → desc → none.

### Integration on LlmPage

- **Models Tab**: Provider selector buttons remain (loads models per provider).
  The plain `<table>` is replaced by `<ModelBrowser>`.
- **My Config Tab**: Replaced by `<ModelBrowser showConfigActions={true}>` with
  favourite/hide actions wired to `useLlm().setUserConfig()`.

### Not included

- Billing filter (no billing in prototype)
- Curation filter (too few curated models at this stage)
- Full 9-column grid layout from previous prototype
- ModelConfigModal for notes/system prompt addition editing (exists in hooks already,
  can be added later)

---

## Work Package 4: Admin System Prompt Tab

### Problem

The application needs a global system prompt that is prepended to every inference
request regardless of persona. This is the central safety feature for platform
operators.

### Context

The system prompt hierarchy is documented in INSIGHTS.md INS-007. The
context/session management layer (being designed in a parallel session) will be
responsible for assembling the final prompt. This work package covers the admin UI
and storage only.

### Backend

Uses the existing Settings module. The global system prompt is stored in the
`app_settings` collection with key `system_prompt`, but accessed through a
dedicated typed endpoint (not the generic key-value API).

```
GET  /api/settings/system-prompt    → { content: str, updated_at: datetime, updated_by: str }
PUT  /api/settings/system-prompt    → Body: { content: str }
```

- Both endpoints require `admin` or `master_admin` role
- PUT publishes `SETTING_SYSTEM_PROMPT_UPDATED` event
- GET returns `{ content: "" }` if no system prompt has been set yet

New topic constant in `shared/topics.py`:

```python
SETTING_SYSTEM_PROMPT_UPDATED = "setting.system_prompt.updated"
```

### Frontend

New tab "System Prompt" on `AdminPage.tsx` (alongside Settings and Model Curation):

- Textarea with current system prompt content
- Character counter (limit: 4000 characters)
- Save button, disabled when not dirty
- Success feedback via toast notification
- Explanatory text: "This prompt is prepended to every inference request, regardless
  of persona. Use it to enforce safety rules and operational boundaries."
- Fetches on tab activation, not on page mount

---

## Work Package 5: API Key Status per User (Admin View)

### Problem

Admins cannot see which users have configured API keys for which providers.
This information is needed to support users and verify platform readiness.

### Backend

New admin endpoint in the LLM module (`backend/modules/llm/_handlers.py`):

```
GET /api/llm/admin/credential-status
```

- Requires `admin` or `master_admin` role
- Reads from `llm_user_credentials` collection, grouped by `user_id`
- Response:

```json
[
  {
    "user_id": "abc123",
    "providers": [
      { "provider_id": "ollama_cloud", "is_configured": true }
    ]
  }
]
```

- Only exposes `is_configured`, never the key itself
- No new shared DTO needed -- response type is internal to LLM module

### Frontend

Changes to `frontend/src/prototype/pages/UsersPage.tsx`:

- Second fetch on mount: `GET /api/llm/admin/credential-status`
- Merge with user list in frontend (by `user_id`)
- Per user in table: small coloured chips showing configured providers
  (e.g. "Ollama Cloud" as green chip)
- No providers configured: subtle "No keys" hint in grey
- Both fetches are independent (parallel, no dependency)

### Module boundaries

- User module knows nothing about LLM module
- Frontend makes two independent fetches and merges client-side
- No cross-module DB access, no cross-module imports

---

## Summary of Changes by File

### New files

| File | Description |
|------|-------------|
| `frontend/src/core/store/notificationStore.ts` | Toast notification Zustand store |
| `frontend/src/prototype/components/Toasts.tsx` | Toast display component |
| `frontend/src/prototype/components/ModelBrowser.tsx` | Reusable model browser with filters |

### Modified files

| File | Changes |
|------|---------|
| `frontend/src/prototype/pages/LoginPage.tsx` | Auto-detect setup mode via `/api/auth/status` |
| `frontend/src/prototype/pages/LlmPage.tsx` | Replace tables with ModelBrowser component |
| `frontend/src/prototype/pages/UsersPage.tsx` | Add API key status badges, replace `alert()` with toasts |
| `frontend/src/prototype/pages/AdminPage.tsx` | Add System Prompt tab |
| `frontend/src/prototype/layouts/PrototypeLayout.tsx` | Mount `<Toasts />` component |
| `backend/modules/user/_handlers.py` | Add `GET /api/auth/status` endpoint |
| `backend/modules/llm/_handlers.py` | Add `GET /api/llm/admin/credential-status` endpoint |
| `backend/modules/settings/_handlers.py` | Add system prompt GET/PUT endpoints |
| `shared/topics.py` | Add `SETTING_SYSTEM_PROMPT_UPDATED` constant |
| `shared/events/settings.py` | Add `SettingSystemPromptUpdatedEvent` (if not exists) |

### Files for deferred items

| File | Items to add |
|------|-------------|
| `FOR_LATER.md` | Bell/Flyout notification system, backend-driven notifications |

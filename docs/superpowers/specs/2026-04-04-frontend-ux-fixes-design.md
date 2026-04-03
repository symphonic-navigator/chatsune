# Frontend UX Fixes — Design Spec

**Date:** 2026-04-04
**Scope:** Four small, independent improvements to the frontend UX layer.

---

## 1. Close User Overlay When Navigating Away

### Problem
When the user opens the User Modal (overlay) and then clicks **Admin** or **Chat** in the sidebar, the modal stays open while the page navigates. This looks broken.

### Behaviour
- Clicking **Admin** or **Chat (Personas)** in the sidebar: close the modal first, then navigate.
- Clicking **Projects**, **History**, **Knowledge**, avatar, or settings gear: keep current behaviour (opens/switches modal tabs).

### Implementation
- Add `onCloseModal: () => void` to `SidebarProps`.
- In `Sidebar.tsx`: call `onCloseModal()` inside the Admin button's `onClick` and the Chat NavRow's `onClick`, before `navigate(...)`.
- In `AppLayout.tsx`: pass `onCloseModal={closeModal}`.

---

## 2. Apply Display Settings CSS Variables

### Problem
`displaySettingsStore.ts` correctly writes CSS variables (`--chat-font-family`, `--chat-font-size`, `--chat-line-height`, `--ui-scale`) to `document.documentElement`, but no CSS rule or component actually reads them — so they have no visual effect.

### Solution

**UI Scale** (`--ui-scale`):
- `applyCssVars` already writes `--ui-scale: 1.0 | 1.1 | 1.2 | 1.3`.
- Add `zoom: var(--ui-scale, 1);` to `body` in `index.css`.
- Also add `--ui-scale: 1;` to the `:root` block as the CSS-level default.
- `zoom` is now stable across all modern browsers and correctly scales layout.

**Chat font/size/line-height**:
- Add a CSS class `.chat-text` in `index.css` that reads the three vars:
  ```css
  .chat-text {
    font-family: var(--chat-font-family);
    font-size: var(--chat-font-size);
    line-height: var(--chat-line-height);
  }
  ```
- Apply `className="chat-text"` to the chat message text container in `ChatPage`.

---

## 3. User Display Name — `/me` Endpoint, Events, About Me Tab

### Problem
- `extractUserFromToken` populates only `id` and `role` from the JWT; `username` and `display_name` are left as empty strings.
- Neither the login nor the bootstrap flow calls a `/me` endpoint to load full user data.
- Result: Sidebar falls back to `'?'`.

### Backend Changes

**New endpoint:** `GET /api/users/me`
- Requires `get_current_user` dependency.
- Returns `UserResponseDto` (same shape as `UserDto` on the frontend) for the authenticated user.

**New endpoint:** `PATCH /api/users/me/profile`
- Body: `{ display_name: str }` (validated: 1–64 chars, stripped).
- Saves to MongoDB.
- Publishes `UserProfileUpdatedEvent` to the user's WebSocket scope.
- Returns the updated user.

**New shared contract:**
- `shared/events/auth.py`: add `UserProfileUpdatedEvent` with payload containing the full updated `UserDto`.
- `shared/topics.py`: add `USER_PROFILE_UPDATED = "user.profile.updated"`.

**Default display name:**
- When creating a user, if `display_name` is empty/None, set it to `"Unnamed User"`.
- The `GET /api/users/me` endpoint returns the stored value; no server-side fallback needed after the default is written on creation.

### Frontend Changes

**`meApi.ts`:**
- Add `getMe(): Promise<UserDto>` → `GET /api/users/me`.
- Add `updateDisplayName(name: string): Promise<UserDto>` → `PATCH /api/users/me/profile`.

**`useBootstrap.ts`:**
- After `setToken(response.access_token)`, call `meApi.getMe()` → `setUser(user)`.

**`useAuth.ts` — `login()`:**
- After `setToken(res.access_token)`, call `meApi.getMe()` → `setUser(user)`.

**`AppLayout.tsx`:**
- Subscribe to `Topics.USER_PROFILE_UPDATED` via `useEventBus`.
- On event: call `setUser(event.payload)` to update the auth store live.

**`AboutMeTab.tsx`:**
- Add a **Display Name** input field at the top, above the existing free-text area.
- Loads initial value from `meApi.getMe()` (or reads from auth store — prefer auth store to avoid a second network call).
- Has its own Save button with the same UX pattern as the existing about-me save.
- On save: calls `meApi.updateDisplayName(name)`.
- No need to manually update the store — the `USER_PROFILE_UPDATED` event from the backend triggers the update in `AppLayout`.

**`Sidebar.tsx` fallback:**
- Change `user?.display_name || user?.username || '?'` to `user?.display_name || user?.username || 'Unnamed User'`.

---

## 4. Fox Emoji Favicon

### Problem
The browser tab shows a generic page icon.

### Solution
- In `frontend/index.html`: replace (or add) the `<link rel="icon">` with an SVG data URI that renders the fox emoji:
  ```html
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🦊</text></svg>">
  ```
- No build step, no image file, works in all modern browsers.

---

## Out of Scope

- Changing the existing about-me free-text behaviour.
- Persisting display settings to the backend (localStorage only for now).
- Any Admin UI changes.

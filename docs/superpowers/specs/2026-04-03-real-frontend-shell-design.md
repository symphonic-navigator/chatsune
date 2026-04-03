# Real Frontend — Phase 1: App Shell

**Date:** 2026-04-03  
**Scope:** App shell only — login page, sidebar, topbar, routing skeleton. No chat UI, no persona management screens, no knowledge management. Subsequent phases build on this foundation.

---

## Goals

Replace the prototype frontend shell with the production shell design. All existing backend features (auth, chat, personas, models) continue to work via the same `core/` layer. The prototype layout (`src/prototype/`) is deleted and replaced by `src/app/`.

---

## Entry-Point Behaviour

After login (or on hard refresh), the app bootstraps via the refresh token cookie — this is already implemented. On success the user lands on their **last active chat**. This mirrors Claude Desktop's "continue where you left off" default. Navigation to other personas, history, or projects is always one click away in the sidebar.

**Last active chat persistence:** Stored in `localStorage` as `chatsune_last_route` (e.g. `/chat/abc123/xyz789`). Written on every navigation to a chat route. On bootstrap success, the app reads this value and redirects there. If the value is absent or the route 404s, fall back to `/personas`.

---

## Architecture

### Directory Structure

```
frontend/src/
  core/              ← unchanged (api, hooks, store, types, websocket)
  app/
    layouts/
      AppLayout.tsx  ← sidebar + topbar shell
    pages/
      LoginPage.tsx
    components/
      sidebar/
        Sidebar.tsx
        PersonaItem.tsx
        ProjectItem.tsx
        HistoryItem.tsx
      topbar/
        Topbar.tsx
  main.tsx
  App.tsx            ← routing, AuthGuard, bootstrap
```

The `prototype/` directory is removed entirely once `app/` is in place.

### Routing

| Path | Component | Guard |
|---|---|---|
| `/login` | `LoginPage` | — |
| `/` (and `*`) | redirect to last active chat or `/chat/...` | AuthGuard |
| `/chat/:personaId/:sessionId?` | `ChatPage` (stub) | AuthGuard |
| `/personas` | `PersonasPage` (stub) | AuthGuard |
| `/projects` | `ProjectsPage` (stub) | AuthGuard |
| `/history` | `HistoryPage` (stub) | AuthGuard |
| `/knowledge` | `KnowledgePage` (stub) | AuthGuard |
| `/admin/*` | `AdminLayout` (stub) | AuthGuard + admin role |

Stub pages render a placeholder — they exist so nav links work and routes don't 404.

---

## Login Page

- Centred card on a dark background matching the app palette.
- Username + password fields, submit button.
- On success: bootstrap sets token, redirect to last active chat.
- On failure: inline error message (no toast — error belongs on the form).

---

## App Shell Layout

```
┌─────────────────────────────────────────────┐
│ Sidebar (232px) │ Topbar (context-specific)  │
│                 │─────────────────────────── │
│                 │                            │
│                 │   Main content area        │
│                 │                            │
└─────────────────────────────────────────────┘
```

### Responsive

On viewports below 768px the sidebar collapses to a hamburger menu (overlay drawer), matching the Claude mobile app pattern. Phase 1 implements desktop only; the hamburger is a Phase 2 concern.

---

## Sidebar

**Fixed width:** 232px. Not collapsible to icon-strip in Phase 1 (can be added later).

### Sections (top to bottom)

#### 1. Logo bar
App name + icon. Static. No action.

#### 2. Admin banner _(admin/master_admin only)_
Full-width row with gold accent colour and `›` arrow. Navigates to `/admin`. Clearly visible, never hidden behind a menu — explicit anti-pattern vs. Open WebUI.

#### 3. CHAT _(primary nav row)_
Icon + "Chat" label as a full-row button. Hover shows background highlight. Clicking navigates to `/personas` (the persona selection/management screen).

Below the nav row: **pinned personas**, always visible, no collapse.

Each persona row:
- Drag handle (reorder via mouse/touch, order persisted in user preferences)
- Avatar (colour-gradient, initial letter)
- Name
- `···` context menu (appears on hover): **New Chat**, **New Incognito Chat**, **Edit**, **Unpin**

Clicking a persona (not the menu): **resumes the last chat with that persona**.

#### 4. Shared scrollable middle

Projects and History share a single scroll container. When Projects is expanded the user scrolls through project items and continues into History items — one unified list.

**PROJECTS nav row:** Icon + "Projects" label + 🔍 search icon + ∨ collapse toggle.  
Collapsed by default; last state persisted in `localStorage`.  
Project items are drag-reorderable.  
Clicking the "Projects" label navigates to `/projects`.

**HISTORY nav row:** Icon + "History" label + 🔍 search icon. No collapse (always visible).  
Clicking "History" opens the history management screen (`/history`) — full filtering by persona, date, tags.  
Chats within a project do **not** appear here.  
Items can be pinned (📌 floats to top, persists in user preferences).  
History fades older items (opacity decreases with age) to visually de-emphasise stale sessions.

#### 5. Bottom (fixed)

**KNOWLEDGE nav row:** Icon + "Knowledge" label. Full-row button, navigates to `/knowledge`. No expand/collapse — knowledge lives on its own screen.

**User row:** Avatar + display name + role. The entire row is the menu button — no separate icon. Clicking opens a user menu: Settings, Change Password, Sanitized Mode toggle, Logout.

---

## Topbar

Context-specific. Changes based on the active section.

### Chat context (default)
```
[ Persona chip: ● Lyra ]  /  Session title         llama3.2  ● live
```
- **Persona chip:** rounded pill, persona accent colour dot + name. Clicking opens persona switcher.
- **Session title:** current session name (editable on double-click, Phase 2).
- **Model pill:** shows active model. Clicking opens model selector (Phase 2).
- **Live indicator:** WebSocket connection status dot + label.

### Admin context
```
  Admin                  [ Users ] [ Models ] [ System ] [ Settings ]
```
Tab-bar for admin sub-sections, rendered in the topbar.

### Other sections (Personas, Projects, History, Knowledge)
Section title + optional action buttons (e.g. "New Project", "New Knowledge Folder") on the right.

---

## Design System

### Colour palette (CSS custom properties)

| Token | Value | Usage |
|---|---|---|
| `--bg-base` | `#0a0810` | Sidebar, page background |
| `--bg-surface` | `#0f0d16` | Main content area |
| `--bg-hover` | `rgba(255,255,255,0.06)` | Row hover state |
| `--bg-active` | `rgba(255,255,255,0.08)` | Active/selected row |
| `--border-subtle` | `rgba(255,255,255,0.06)` | Dividers, borders |
| `--text-primary` | `rgba(255,255,255,0.85)` | Headings, active items |
| `--text-secondary` | `rgba(255,255,255,0.50)` | Body, inactive items |
| `--text-muted` | `rgba(255,255,255,0.25)` | Labels, metadata |
| `--accent-gold` | `#c9a84c` | Admin accent, model pill |
| `--accent-live` | `#22c55e` | WebSocket live indicator |

Persona avatars use unique gradient pairs generated deterministically from persona ID — no two personas share the same gradient.

### Typography
- UI font: system-ui / Inter (already in Vite setup)
- Monospace (pills, model names): JetBrains Mono or `monospace` fallback
- Section headers: 13px, 600 weight
- Body / item text: 13px, 400–500 weight
- Labels / metadata: 10–11px, uppercase where appropriate

### Tailwind
All styling via Tailwind utility classes. CSS custom properties declared in `index.css` and referenced via `bg-[var(--bg-base)]` syntax where Tailwind tokens are insufficient.

---

## Sanitized Mode

Defined in INS-008. Toggle lives in the user menu (bottom of sidebar). When active:
- NSFW-flagged personas are hidden from sidebar and all screens.
- NSFW-flagged projects and knowledge entries are hidden.
- If the current chat involves an NSFW persona, redirect to last non-NSFW persona or new-chat state.

The flag is a per-resource attribute; the toggle is a per-user preference stored in the backend.

**Phase 1:** The toggle UI is present in the user menu (checkbox/switch), but is non-functional — the `nsfw` flag does not yet exist in the API. The toggle renders as disabled with a tooltip "Coming soon". No backend changes in Phase 1.

**Phase 2:** Backend adds `nsfw: bool` field to persona, project, and knowledge entry schemas. Frontend filter logic activates automatically once the field is present.

---

## What is explicitly OUT of scope for Phase 1

- Chat UI (messages, input, streaming)
- Persona creation / editing screens
- Project management screens
- Knowledge management screens
- History management / filter screen
- Model selector interaction
- File upload
- Artefacts
- Admin screens (stub only)
- Hamburger / responsive sidebar
- Session title editing
- Drag-and-drop reordering (sidebar renders order from store; reorder interaction is Phase 2)

---

## Success Criteria

- Login → bootstrap → redirect to last active chat (or `/personas` if no prior chat).
- Sidebar renders correctly with real data (pinned personas from API, empty states handled).
- All nav rows navigate to correct routes (stub pages acceptable).
- Topbar shows correct context (persona + session name + model + live status in chat context).
- Admin banner visible for admin/master_admin, hidden for regular users.
- User menu opens from user row, logout works.
- Prototype layout deleted; no dead code remains.

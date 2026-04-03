# User Area & Sidebar Upgrade — Design Spec

**Date:** 2026-04-03  
**Status:** Approved

---

## Overview

Replace the current per-page navigation model with a modal-based User Area that the user accesses from the sidebar. The Personas page remains the app home/greeting screen. Everything else — history, projects, knowledge, settings, and personal profile — lives inside a single modal overlay.

---

## Navigation Model

### Sidebar links

| Element | Behaviour |
|---|---|
| 🦊 logo + "Chatsune" | No action (branding only) |
| ◈ **Chat** NavRow | Navigate to `/personas` — greeting page, start a chat |
| ◫ **Projects** NavRow | Open User Modal → Projects tab |
| ◷ **History** NavRow | Open User Modal → History tab |
| 🧠 **Knowledge** NavRow | Open User Modal → Knowledge tab |
| **User avatar row** | Open User Modal → About me tab |
| **`···` button** (next to avatar) | Open User Modal → Settings tab |
| **Log out** button | Separate small button below the avatar row; logs the user out |

### Active state (sidebar)

When the modal is open, the NavRow that triggered the currently visible tab is highlighted gold (Option A from brainstorm). The user avatar row does **not** change appearance when the modal is open — the NavRow is the single source of truth.

- When modal was opened via **avatar** → About me tab → no NavRow is highlighted; avatar row uses a subtle gold tint instead.
- When modal was opened via **`···`** → Settings tab → same as above (no NavRow highlighted; avatar row subtle gold tint).

The existing admin panel link uses the same gold-underline active indicator pattern.

---

## User Modal

The modal overlays the **main content area only** (right of the sidebar). The sidebar remains fully visible and interactive while the modal is open — clicking a sidebar NavRow switches the modal to the corresponding tab; clicking Chat closes the modal and navigates to `/personas`. A dim backdrop covers only the main content area behind the modal box. Closing the modal (✕ button or Escape) returns to whatever was visible before.

### Tab structure

```
About me  |  Projects  |  History  |  Knowledge  |  Settings
```

Tabs are arranged horizontally at the top of the modal body, gold underline on the active tab.

### Tab content

**About me**  
Free-text textarea for the user's personal system prompt contribution. Character limit 2 000. Dirty-state tracking with Save button. Connects to existing backend endpoints:
- `GET /users/me/about-me` — load current value
- `PATCH /users/me/about-me` — save changes

Matches the `AboutMeTab` implementation from chat-client-02.

**Projects**  
Project list. Placeholder content for now — the backend contract does not yet exist.

**History**  
Filterable and full-text searchable chat history. Search bar at the top, grouped by date (Today / Yesterday / This Week / This Month / older). Each entry shows persona name, session title, and date. Clicking opens the session in the chat view and closes the modal.

**Knowledge**  
Knowledgebase management — same content currently shown at `/knowledge`. The `/knowledge` route stays as a redirect or can be removed once the modal is wired up.

**Settings**  
Display settings ported 1:1 from chat-client-02 `DisplaySettings` component:

| Setting | Options |
|---|---|
| Chat font | Serif (Lora) / Sans-serif (system-ui) |
| Font size | Normal (14 px) / Large (16 px) / Very Large (19 px) |
| Line spacing | Small 1.5 / Normal 1.65 / Large 1.9 / XL 2.1 |
| UI scale | 100 % / 110 % / 120 % / 130 % |
| White Script | On / Off (high-contrast chat text mode) |

Settings are persisted in `localStorage` under the same key structure as chat-client-02. Applied via CSS variables on the root element at boot.

---

## Sidebar Changes

### Logo area

Replace the current `⬡` hex icon with 🦊 emoji, keeping "Chatsune" text beside it — matching the chat-client-02 sidebar treatment.

### Logout

Move logout out of the avatar click target. Add a small, low-prominence "↪ Log out" button directly below the avatar row. The avatar row itself now navigates to the User Modal.

### `···` button

A small button that appears on the right side of the avatar row (visible on hover or always-visible at low opacity). Clicking it opens the modal directly to the Settings tab.

---

## Fonts

Copy woff2 files from `chat-client-02/frontend/public/fonts/` into `frontend/public/fonts/`:
- `Lora-Regular.woff2`
- `Lora-Italic.woff2`
- `InstrumentSerif-Regular.woff2` (optional, if used)

Load JetBrains Mono from Google Fonts in `index.html` (already present in chat-client-02).

Define font stacks in `index.css`:
```css
--font-serif: 'Lora', Georgia, serif;
--font-sans: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
--font-mono: 'JetBrains Mono', 'Courier New', monospace;
```

The selected chat font family is applied dynamically via `DisplaySettings`.

---

## Accessibility / Contrast

Raise minimum text opacity for all secondary/inactive text from ~0.3 to **0.5**. Interactive elements (buttons, nav items) must reach at least **0.65** opacity on hover. This addresses the contrast concerns raised by the accessibility feedback.

Concrete changes:
- Sidebar NavRow inactive text: `text-white/30` → `text-white/50`
- Sidebar section labels: `text-white/20` → `text-white/40`
- History items, placeholder text: audit and raise to minimum 0.4
- All hover states: ensure reaching 0.65+

---

## What is NOT changing

- The `/personas` route — stays exactly as-is; it is the app home and greeting screen
- Persona management (edit/delete) remains on the Personas page via existing edit buttons/flows
- The Admin area — its tab structure and routing are unchanged; only the gold-underline active indicator is unified with the user area style
- Modal state is local (React state), not persisted in the URL — the modal has no route of its own

---

## Open questions (deferred)

- **Projects backend** — no contract exists yet; Projects tab is a placeholder
- **Knowledge modal tab** — whether `/knowledge` route is removed or redirects to modal is decided when Knowledge is wired up

# Artefact System — Design Spec

**Date:** 2026-04-06
**Status:** Draft

---

## Overview

A session-scoped artefact system for Chatsune. LLMs can create, read, update, and list
artefacts during chat via tool calls. Users view, edit, and manage artefacts through a
right-side rail/sidebar and a chat-area overlay.

Design philosophy: Claude-style sidebar-fixed approach with progressive discovery.
The artefact panel only appears when artefacts exist, and the full editor opens as an
overlay on demand.

---

## Scope

- **Session-scoped:** Artefacts live and die with the chat session
- **Six types:** `markdown`, `code`, `html`, `svg`, `jsx`, `mermaid`
- **Undo/Redo stack:** Internal versioning (max 20), no version browser UI
- **No persona-scoping:** Deliberately avoided to keep things simple for users;
  project-level artefacts will come later with the Projects feature

---

## LLM Tools

Four tools registered in the tool system (`backend/modules/tools/`):

### `create_artefact`

| Parameter  | Type   | Required | Description                                      |
|------------|--------|----------|--------------------------------------------------|
| `handle`   | string | yes      | LLM-chosen short name, session-unique             |
| `title`    | string | yes      | Human-readable title                              |
| `type`     | enum   | yes      | `markdown\|code\|html\|svg\|jsx\|mermaid`         |
| `content`  | string | yes      | Full artefact content                             |
| `language` | string | no       | Programming language (only relevant for `code`)   |

Returns: confirmation with handle.

Handle validation: lowercase alphanumeric + hyphens, max 64 characters, must be unique
within the session. If the LLM attempts to create with a duplicate handle, the tool
returns an error message instructing it to choose a different handle.

### `update_artefact`

| Parameter | Type   | Required | Description                         |
|-----------|--------|----------|-------------------------------------|
| `handle`  | string | yes      | Existing artefact handle            |
| `content` | string | yes      | New full content                    |
| `title`   | string | no       | Updated title (keeps old if absent) |

Returns: confirmation with new version number.

Pushes previous content onto the undo stack. Clears any redo history.

### `read_artefact`

| Parameter | Type   | Required | Description              |
|-----------|--------|----------|--------------------------|
| `handle`  | string | yes      | Existing artefact handle |

Returns: full content + metadata (title, type, language, version, size).

### `list_artefacts`

No parameters.

Returns: array of `{ handle, title, type, language, size_bytes, version }` for all
artefacts in the current session. Token-efficient summary for LLM context.

---

## Data Model

### Collection: `artefacts`

```
{
  _id: ObjectId,
  session_id: str,
  user_id: str,
  handle: str,
  title: str,
  type: str,                // markdown|code|html|svg|jsx|mermaid
  language: str | null,     // only for type=code
  content: str,
  size_bytes: int,
  version: int,             // starts at 1, increments on update
  created_at: datetime,
  updated_at: datetime
}
```

Index: `(session_id, handle)` unique.

### Collection: `artefact_versions`

```
{
  _id: ObjectId,
  artefact_id: ObjectId,
  version: int,
  content: str,
  created_at: datetime
}
```

Internal backing for undo/redo. Max 20 versions per artefact; oldest pruned on overflow.
No direct API access.

### Undo/Redo Logic

- Pointer tracks current version number on the artefact document
- **Undo:** Decrements version pointer, restores content from `artefact_versions`
- **Redo:** Increments version pointer, restores content from `artefact_versions`
- **New update:** Deletes all versions above current pointer (clears redo history),
  saves current content as new version, increments pointer

---

## Event System

All events are session-scoped and flow through the existing WebSocket event bus.

| Event              | Payload                                          | Purpose                          |
|--------------------|--------------------------------------------------|----------------------------------|
| `artefact.created` | handle, title, type, language, size_bytes         | Rail update + inline card        |
| `artefact.updated` | handle, title, type, size_bytes, version          | Rail update + inline card        |
| `artefact.deleted` | handle                                           | Remove from rail                 |
| `artefact.undo`    | handle, version                                  | Refresh overlay content          |
| `artefact.redo`    | handle, version                                  | Refresh overlay content          |

Design decisions:
- **No content in events** — artefact content can be large. Frontend fetches via REST
  when the user opens the overlay.
- **`correlation_id`** inherited from the active chat stream, so inline cards appear
  at the correct position in the message flow.
- **Delete is user-only** — no LLM tool for deletion. Only the user can delete artefacts
  through the sidebar context menu.

---

## REST Endpoints

All under `/api/sessions/{session_id}/artefacts/`:

| Method | Path                    | Purpose                    |
|--------|-------------------------|----------------------------|
| GET    | `/`                     | List artefacts for session |
| GET    | `/{artefact_id}`        | Get artefact with content  |
| DELETE | `/{artefact_id}`        | Delete artefact            |
| PATCH  | `/{artefact_id}`        | Update artefact (rename, edit content) |
| POST   | `/{artefact_id}/undo`   | Undo last change           |
| POST   | `/{artefact_id}/redo`   | Redo last undone change    |

These are for user actions (UI). LLM actions go through the tool system.

---

## Frontend Architecture

### Rail (Collapsed State)

- **Width:** 40px
- **Visibility:** Only appears when the session has at least one artefact
- **Content:** Expand arrow + artefact count badge
- **Interaction:** Entire rail is clickable to expand
- **Position:** Right side of the chat area

### Sidebar (Expanded State)

- **Width:** ~280px
- **Behaviour:** Push — chat area narrows, content reflows (not an overlay)
- **Content:**
  - Header with "Artefacts" label and collapse arrow
  - Artefact list: handle, title, type badge, size
  - Per-artefact context menu: Rename, Delete, Copy, Download
- **Interaction:** Click artefact to open overlay; collapse arrow to return to rail

### Overlay (Artefact Viewer/Editor)

- **Coverage:** Chat area only — sidebars and topbar remain visible and interactive
- **Close:** X button, Escape key, or click outside (on sidebars/topbar)
- **Toolbar:** Title, type badge, Edit/Preview toggle, Copy, Download, Undo, Redo, X
- **Edit mode:** Textarea with monospace font for raw content editing. User edits are
  saved via `PATCH /api/sessions/{session_id}/artefacts/{artefact_id}` on blur or
  explicit save. Each save pushes to the undo stack just like LLM updates.
- **Preview mode** (varies by type):
  - `markdown` — rendered with ReactMarkdown + remark-gfm (`.markdown-preview` styles)
  - `code` — syntax highlighted via Shiki (with language from artefact metadata)
  - `html` — iframe with `srcDoc`
  - `svg` — rendered as inline image (base64 data URI)
  - `jsx` — iframe with Babel transpiler + React 18 UMD bundles
  - `mermaid` — dynamically rendered with Mermaid library, dark theme

### Inline Card (Chat Stream)

- Appears in the message flow when `create_artefact` or `update_artefact` tool calls occur
- Compact card showing: handle, title, type badge, "Open" button
- Click "Open" opens the overlay for that artefact
- Visually distinct from regular tool-call activity cards

### State Management

New Zustand store `artefactStore`:
- `artefacts: Map<handle, ArtefactSummary>` — session's artefact list
- `sidebarOpen: boolean` — rail vs expanded sidebar
- `activeArtefactHandle: string | null` — which artefact is open in the overlay
- Actions: `onCreated`, `onUpdated`, `onDeleted`, `openOverlay`, `closeOverlay`,
  `toggleSidebar`

---

## Integration Points

### Backend

1. **New module:** `backend/modules/artefact/` with `__init__.py`, `_repository.py`,
   `_handlers.py`, `_models.py`
2. **Tool registration:** Four tools registered in `backend/modules/tools/_registry.py`
3. **Tool executor:** New `ArtefactToolExecutor` implementing the existing executor protocol
4. **Event publishing:** Via existing event bus with new topic constants in `shared/topics.py`
5. **REST routes:** Mounted on the FastAPI app under `/api/sessions/{session_id}/artefacts`

### Frontend

1. **ChatView.tsx:** Add artefact rail/sidebar to the right of the chat area
2. **useChatStream.ts:** Handle new artefact event types
3. **MessageList/ToolCallActivity:** Render inline artefact cards for tool calls
4. **New components:** `ArtefactRail`, `ArtefactSidebar`, `ArtefactOverlay`,
   `ArtefactCard` (inline), `ArtefactPreview` (per-type renderers)

### Shared Contracts

New files in `shared/`:
- `shared/dtos/artefact.py` — `ArtefactSummaryDto`, `ArtefactDetailDto`
- `shared/events/artefact.py` — all artefact events
- `shared/topics.py` — new `ARTEFACT_*` constants

---

## Dependencies

### New Frontend Packages

- `mermaid` — for Mermaid diagram rendering
- `@babel/standalone` — for JSX transpilation in iframe (or load via CDN in iframe)

### Existing (Already Available)

- `react-markdown` + `remark-gfm` — markdown preview
- `shiki` — code syntax highlighting
- Zustand — state management

---

## Out of Scope

- Persona-scoped or cross-session artefacts (future: Projects feature)
- Version browser UI (internal undo/redo stack only)
- LLM-initiated deletion (user action only)
- Collaborative editing / real-time sync
- Artefact search or filtering (not needed with session scope)

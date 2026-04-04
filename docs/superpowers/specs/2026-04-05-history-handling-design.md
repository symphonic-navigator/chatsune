# History Handling Improvements

**Date:** 2026-04-05
**Scope:** Sidebar history menu, HistoryTab in user modal, reactive session updates, new backend endpoints

---

## Context

Chat history management is incomplete:
- No way to delete sessions from sidebar or user modal
- HistoryTab shows no session titles
- No persona filtering in HistoryTab
- No way to rename sessions or request title regeneration
- New chat creation does not update the sidebar (missing event handlers)

Design principle: the chat is the central interface. All management UI lives in the user modal, never as a standalone page. The `/history` route opens the modal directly.

---

## 1. Sidebar: Hover Menu for HistoryItem

Adopt the same pattern as `PersonaItem`:
- `···` button appears on hover (right side of the row)
- Dropdown menu with click-outside-to-close behaviour
- Initial menu item: **Delete** only (more items later)
- Delete shows a confirmation dialog before executing
- On success, session is removed from the list via `chat.session.deleted` event

**Files affected:**
- `frontend/src/app/components/sidebar/HistoryItem.tsx` — add menu state, button, dropdown

---

## 2. HistoryTab in User Modal

### 2a. Show Session Titles

Each session row displays:
- **Title** (or fallback to formatted date if no title)
- **Persona name** as subtitle
- **Date** as secondary info

### 2b. Persona Filter Dropdown

- Dropdown above the session list, alongside existing search input
- Default value: "All Personas"
- Options: all personas the user has sessions with
- Sanitised mode filters NSFW personas from the dropdown AND from the session list
- Filter applies in combination with existing text search

### 2c. Inline Rename

- Click on a session title turns it into an editable text field (same pattern as API key names)
- **Enter** or **blur** saves the new title via `PATCH /api/chat/sessions/{id}`
- **Escape** cancels without saving
- Empty input reverts to previous title (no blank titles)

### 2d. Request Title Generation

- Small refresh/regenerate icon button next to the title
- Calls `POST /api/chat/sessions/{id}/generate-title`
- Triggers existing `TITLE_GENERATION` background job
- Title arrives asynchronously via `chat.session.title_updated` event
- Button disabled while generation is in-flight (track via correlation ID or optimistic state)

### 2e. Delete Sessions

- Delete action per session row (trash icon or menu item)
- Confirmation dialog before deletion
- Calls `DELETE /api/chat/sessions/{id}` (existing endpoint)
- Session removed from list via `chat.session.deleted` event

**Files affected:**
- `frontend/src/app/components/user-modal/HistoryTab.tsx` — major rework

---

## 3. New Backend Endpoints

### PATCH /api/chat/sessions/{session_id}

Manual rename of a session title.

- **Body:** `{ "title": "string" }`
- **Auth:** session must belong to authenticated user
- **Response:** updated `ChatSessionDto`
- **Side effect:** publishes `chat.session.title_updated` event

### POST /api/chat/sessions/{session_id}/generate-title

Request asynchronous title generation.

- **Auth:** session must belong to authenticated user
- **Precondition:** session must have at least 2 messages
- **Response:** 202 Accepted (job submitted)
- **Side effect:** submits `TITLE_GENERATION` job; title arrives via `chat.session.title_updated` event

**Files affected:**
- `backend/modules/chat/_handlers.py` — add two new route handlers
- `backend/modules/chat/__init__.py` — add public API methods if needed

---

## 4. New Events

### chat.session.created

Published when a new chat session is created.

- **Topic constant:** `Topics.CHAT_SESSION_CREATED`
- **Event class:** `ChatSessionCreatedEvent`
- **Payload:** full `ChatSessionDto`
- **Scope:** `session:{session_id}`
- **Fan-out:** target user only

### chat.session.deleted

Published when a chat session is deleted.

- **Topic constant:** `Topics.CHAT_SESSION_DELETED`
- **Event class:** `ChatSessionDeletedEvent`
- **Payload:** `{ session_id: string }`
- **Scope:** `session:{session_id}`
- **Fan-out:** target user only

### chat.session.title_updated (existing)

Already implemented in backend. Frontend must now subscribe to it.

**Files affected:**
- `shared/events/chat.py` — add `ChatSessionCreatedEvent`, `ChatSessionDeletedEvent`
- `shared/topics.py` — add `CHAT_SESSION_CREATED`, `CHAT_SESSION_DELETED`
- `backend/ws/event_bus.py` — add fan-out rules for new events
- `backend/modules/chat/_handlers.py` — publish events on create/delete

---

## 5. Reactive Session Hook

Extend `useChatSessions` to subscribe to WebSocket events after initial fetch:

| Event | Action |
|-------|--------|
| `chat.session.created` | Prepend session to list |
| `chat.session.deleted` | Remove session from list |
| `chat.session.title_updated` | Update title in-place |

No polling, no full refetch — purely event-driven updates after mount.

**Files affected:**
- `frontend/src/core/hooks/useChatSessions.ts` — add event subscriptions in useEffect

---

## 6. Sanitised Mode

Sanitised mode must be respected consistently:

- **Sidebar history:** NSFW persona sessions hidden (already implemented in `AppLayout`)
- **HistoryTab sessions:** filtered before display
- **HistoryTab persona dropdown:** NSFW personas excluded from filter options
- **No leakage:** switching sanitised mode on immediately hides NSFW content everywhere

No new sanitised mode logic needed — existing `useSanitisedMode()` store and persona `nsfw` flag are sufficient. Filtering is applied at the component level.

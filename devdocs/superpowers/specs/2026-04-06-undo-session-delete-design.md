# Undo Session Deletion (Soft-Delete) — Design Spec

**Date:** 2026-04-06
**Status:** Approved
**Addresses:** UX-004

---

## Overview

Replace the hard-delete of chat sessions with a soft-delete mechanism. Deleted sessions are marked with a `deleted_at` timestamp and can be restored within a time window. A background cleanup process permanently removes soft-deleted sessions after 1 hour. The frontend shows an "Undo" toast after deletion using the toast notification system (UX-002).

---

## Backend Changes

### 1. Repository (`backend/modules/chat/_repository.py`)

**Modified methods:**

- `delete_session(session_id, user_id)` → renamed to `soft_delete_session(session_id, user_id)`:
  Sets `deleted_at: datetime.utcnow()` via `update_one` instead of `delete_one`. Does NOT delete messages or bookmarks.

- `get_session(session_id, user_id)`:
  Add filter `{"deleted_at": None}` so soft-deleted sessions are invisible to normal lookups.

- `list_sessions(user_id)`:
  Add `{"deleted_at": None}` to the `$match` stage so soft-deleted sessions do not appear in the session list.

- `delete_stale_empty_sessions(max_age_minutes)`:
  Add `{"deleted_at": None}` to the `$match` stage so soft-deleted sessions are not double-counted.

**New methods:**

- `restore_session(session_id, user_id) -> dict | None`:
  Sets `deleted_at: None` via `update_one` with filter `{"_id": session_id, "user_id": user_id, "deleted_at": {"$ne": None}}`. Returns the updated session document, or `None` if not found.

- `hard_delete_expired_sessions(max_age_minutes=60) -> list[str]`:
  Finds all sessions where `deleted_at` is not `None` and `deleted_at < now - max_age_minutes`. Hard-deletes those sessions and their messages (`delete_one` + `delete_many`). Returns list of deleted session IDs.

### 2. Handlers (`backend/modules/chat/_handlers.py`)

**Modified endpoint:**

- `DELETE /sessions/{session_id}`:
  Calls `soft_delete_session` instead of `delete_session`. Does NOT cascade-delete bookmarks (deferred to hard-delete). Still publishes `ChatSessionDeletedEvent`.

**New endpoint:**

- `POST /sessions/{session_id}/restore`:
  Calls `restore_session`. If successful, publishes `ChatSessionRestoredEvent` (carrying the full session DTO). Returns `{"status": "ok"}`. If not found, returns 404.

### 3. Cleanup (`backend/modules/chat/__init__.py`)

**New function:**

- `cleanup_soft_deleted_sessions() -> int`:
  Calls `repo.hard_delete_expired_sessions(max_age_minutes=60)`. For each deleted session ID, cascades bookmark deletion via `delete_bookmarks_for_session`. Returns count.

**Integration into existing loop (`backend/main.py`):**

The existing `_session_cleanup_loop` runs every 3600s (1 hour). Change its interval to **600s (10 minutes)** and add a call to `cleanup_soft_deleted_sessions()` alongside the existing `cleanup_stale_empty_sessions()`. This ensures soft-deleted sessions are cleaned up within ~10 minutes of the 1-hour mark, rather than potentially waiting up to 2 hours.

### 4. Shared Contracts

**New event (`shared/events/chat.py`):**

```python
class ChatSessionRestoredEvent(BaseModel):
    type: str = "chat.session.restored"
    session_id: str
    session: ChatSessionDto
    correlation_id: str
    timestamp: datetime
```

The restored event carries the full `ChatSessionDto` so the frontend can re-insert the session into its list without an additional API call.

**New topic (`shared/topics.py`):**

```python
CHAT_SESSION_RESTORED = "chat.session.restored"
```

---

## Frontend Changes

### 1. Chat API (`frontend/src/core/api/chat.ts`)

New method:

```typescript
restoreSession: (sessionId: string) =>
  api.post<{ status: string }>(`/api/chat/sessions/${sessionId}/restore`),
```

### 2. Event Types (`frontend/src/core/types/events.ts`)

Add `CHAT_SESSION_RESTORED: "chat.session.restored"` to the `Topics` object.

### 3. useChatSessions Hook (`frontend/src/core/hooks/useChatSessions.ts`)

New event subscription for `Topics.CHAT_SESSION_RESTORED`:
- Extracts the `session` (ChatSessionDto) from `event.payload`
- Inserts it back into the sessions list (sorted by `updated_at`)

### 4. Sidebar (`frontend/src/app/components/sidebar/Sidebar.tsx`)

Modify `handleDeleteSession`:
- After successful `chatApi.deleteSession()`, show a toast:
  - `level: "success"`
  - `title: "Session deleted"`
  - `message: session title or "Untitled session"`
  - `duration: 8000` (8 seconds for undo window)
  - `action: { label: "Undo", onClick: () => chatApi.restoreSession(sessionId) }`
- Navigation to `/personas` on active session deletion remains unchanged.

---

## Data Flow

### Delete:
1. User clicks Delete → Confirm
2. Frontend calls `DELETE /api/chat/sessions/{id}`
3. Backend sets `deleted_at = now()` on session document
4. Backend publishes `ChatSessionDeletedEvent`
5. Frontend removes session from list (via event bus)
6. Frontend shows toast with Undo button (8s)

### Undo:
1. User clicks Undo on toast
2. Frontend calls `POST /api/chat/sessions/{id}/restore`
3. Backend sets `deleted_at = None`
4. Backend publishes `ChatSessionRestoredEvent` (with full session DTO)
5. Frontend re-inserts session into list (via event bus)
6. Toast is dismissed

### Permanent deletion:
1. Background loop runs every 10 minutes
2. Finds sessions with `deleted_at` older than 1 hour
3. Hard-deletes session documents, messages, and bookmarks
4. No event published (session already removed from UI)

---

## Constraints

- No new dependencies
- `deleted_at` field is `None` by default (not set on existing sessions — MongoDB queries with `{"deleted_at": None}` match documents where the field is absent)
- No migration needed — existing sessions without `deleted_at` are treated as not-deleted
- Bookmarks are preserved during soft-delete, only removed on hard-delete
- Messages are preserved during soft-delete, only removed on hard-delete

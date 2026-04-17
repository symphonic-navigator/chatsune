# Undo Session Deletion (Soft-Delete) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hard-delete of chat sessions with soft-delete (`deleted_at` field), add a restore endpoint, show an "Undo" toast after deletion, and clean up soft-deleted sessions after 1 hour.

**Architecture:** Add `deleted_at` field to session documents. Modify repository queries to exclude soft-deleted sessions. Add restore endpoint and event. Extend the existing cleanup loop to hard-delete expired soft-deleted sessions. Frontend shows undo toast using the toast system built in UX-002.

**Tech Stack:** Python/FastAPI, MongoDB, React, Zustand, WebSocket events

**Spec:** `docs/superpowers/specs/2026-04-06-undo-session-delete-design.md`

---

### Task 1: Add shared contracts (event + topic)

**Files:**
- Modify: `shared/events/chat.py`
- Modify: `shared/topics.py`
- Modify: `frontend/src/core/types/events.ts`

- [ ] **Step 1: Add ChatSessionRestoredEvent to shared/events/chat.py**

Add the following import at the top of the file (line 1) and the new event class after `ChatSessionDeletedEvent` (after line 98):

```python
from shared.dtos.chat import ChatSessionDto
```

```python
class ChatSessionRestoredEvent(BaseModel):
    type: str = "chat.session.restored"
    session_id: str
    session: dict
    correlation_id: str
    timestamp: datetime
```

Note: `session` is `dict` (the serialised ChatSessionDto), not the Pydantic model directly, because BaseEvent payloads are dicts.

- [ ] **Step 2: Add topic constant to shared/topics.py**

Add after `CHAT_SESSION_DELETED = "chat.session.deleted"` (line 35):

```python
    CHAT_SESSION_RESTORED = "chat.session.restored"
```

- [ ] **Step 3: Add topic to frontend/src/core/types/events.ts**

Add after `CHAT_SESSION_DELETED: "chat.session.deleted",` (line 51):

```typescript
  CHAT_SESSION_RESTORED: "chat.session.restored",
```

- [ ] **Step 4: Verify**

Run: `cd /home/chris/workspace/chatsune && uv run python -m py_compile shared/events/chat.py && uv run python -m py_compile shared/topics.py`
Expected: No errors.

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`
Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add shared/events/chat.py shared/topics.py frontend/src/core/types/events.ts
git commit -m "Add ChatSessionRestoredEvent and CHAT_SESSION_RESTORED topic"
```

---

### Task 2: Modify repository for soft-delete

**Files:**
- Modify: `backend/modules/chat/_repository.py`

- [ ] **Step 1: Modify `delete_session` to soft-delete**

Replace the `delete_session` method (lines 123-128) with:

```python
    async def soft_delete_session(self, session_id: str, user_id: str) -> bool:
        result = await self._sessions.update_one(
            {"_id": session_id, "user_id": user_id, "deleted_at": None},
            {"$set": {"deleted_at": datetime.now(UTC)}},
        )
        return result.modified_count > 0
```

- [ ] **Step 2: Add `restore_session` method**

Add after `soft_delete_session`:

```python
    async def restore_session(self, session_id: str, user_id: str) -> dict | None:
        result = await self._sessions.update_one(
            {"_id": session_id, "user_id": user_id, "deleted_at": {"$ne": None}},
            {"$set": {"deleted_at": None}},
        )
        if result.modified_count == 0:
            return None
        return await self._sessions.find_one({"_id": session_id})
```

- [ ] **Step 3: Add `hard_delete_expired_sessions` method**

Add after `restore_session`:

```python
    async def hard_delete_expired_sessions(self, max_age_minutes: int = 60) -> list[str]:
        """Hard-delete sessions where deleted_at is older than max_age_minutes. Returns list of deleted IDs."""
        cutoff = datetime.now(UTC) - timedelta(minutes=max_age_minutes)
        cursor = self._sessions.find(
            {"deleted_at": {"$ne": None, "$lt": cutoff}},
            {"_id": 1},
        )
        docs = await cursor.to_list(length=1000)
        if not docs:
            return []
        ids = [doc["_id"] for doc in docs]
        await self._sessions.delete_many({"_id": {"$in": ids}})
        await self._messages.delete_many({"session_id": {"$in": ids}})
        return ids
```

- [ ] **Step 4: Add `deleted_at: None` filter to `get_session`**

Change line 36 from:

```python
        return await self._sessions.find_one({"_id": session_id, "user_id": user_id})
```

to:

```python
        return await self._sessions.find_one({"_id": session_id, "user_id": user_id, "deleted_at": None})
```

- [ ] **Step 5: Add `deleted_at: None` filter to `list_sessions`**

Change the `$match` stage at line 41 from:

```python
            {"$match": {"user_id": user_id}},
```

to:

```python
            {"$match": {"user_id": user_id, "deleted_at": None}},
```

- [ ] **Step 6: Add `deleted_at: None` filter to `delete_stale_empty_sessions`**

Change the `$match` stage at line 105 from:

```python
            {"$match": {"created_at": {"$lt": cutoff}}},
```

to:

```python
            {"$match": {"created_at": {"$lt": cutoff}, "deleted_at": None}},
```

- [ ] **Step 7: Verify**

Run: `cd /home/chris/workspace/chatsune && uv run python -m py_compile backend/modules/chat/_repository.py`
Expected: No errors.

- [ ] **Step 8: Commit**

```bash
git add backend/modules/chat/_repository.py
git commit -m "Convert session deletion to soft-delete with restore and hard-delete support"
```

---

### Task 3: Modify handlers for soft-delete + add restore endpoint

**Files:**
- Modify: `backend/modules/chat/_handlers.py`

- [ ] **Step 1: Add ChatSessionRestoredEvent to imports**

Change the import block (lines 15-21) to include the new event:

```python
from shared.events.chat import (
    ChatSessionCreatedEvent,
    ChatSessionDeletedEvent,
    ChatSessionPinnedUpdatedEvent,
    ChatSessionRestoredEvent,
    ChatSessionTitleUpdatedEvent,
    ChatSessionToolsUpdatedEvent,
)
```

- [ ] **Step 2: Modify delete_session handler to use soft-delete**

Replace the `delete_session` function (lines 102-127) with:

```python
@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user: dict = Depends(require_active_session)):
    repo = _chat_repo()
    deleted = await repo.soft_delete_session(session_id, user["sub"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.CHAT_SESSION_DELETED,
        ChatSessionDeletedEvent(
            session_id=session_id,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )

    return {"status": "ok"}
```

Note: No bookmark cascade here — bookmarks are preserved until hard-delete.

- [ ] **Step 3: Add restore_session endpoint**

Add after the `delete_session` function:

```python
@router.post("/sessions/{session_id}/restore")
async def restore_session(session_id: str, user: dict = Depends(require_active_session)):
    repo = _chat_repo()
    doc = await repo.restore_session(session_id, user["sub"])
    if not doc:
        raise HTTPException(status_code=404, detail="Session not found or not deleted")

    dto = ChatRepository.session_to_dto(doc)

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.CHAT_SESSION_RESTORED,
        ChatSessionRestoredEvent(
            session_id=dto.id,
            session=dto.model_dump(mode="json"),
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"session:{dto.id}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )

    return {"status": "ok"}
```

- [ ] **Step 4: Remove bookmark cascade import if it is only used in delete_session**

Check: `delete_bookmarks_for_session` is imported at line 13. It was previously called in `delete_session`. Since soft-delete no longer cascades bookmarks, check if it is used elsewhere in this file. If not, remove the import line:

```python
from backend.modules.bookmark import delete_bookmarks_for_session
```

If it IS used elsewhere, keep the import.

- [ ] **Step 5: Verify**

Run: `cd /home/chris/workspace/chatsune && uv run python -m py_compile backend/modules/chat/_handlers.py`
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/chat/_handlers.py
git commit -m "Switch delete endpoint to soft-delete, add restore endpoint"
```

---

### Task 4: Extend cleanup loop

**Files:**
- Modify: `backend/modules/chat/__init__.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Add `cleanup_soft_deleted_sessions` function to `__init__.py`**

Add after `cleanup_stale_empty_sessions` (after line 684):

```python
async def cleanup_soft_deleted_sessions() -> int:
    """Hard-delete sessions that were soft-deleted more than 1 hour ago. Returns count."""
    from backend.modules.bookmark import delete_bookmarks_for_session
    db = get_db()
    repo = ChatRepository(db)
    deleted_ids = await repo.hard_delete_expired_sessions(max_age_minutes=60)
    if deleted_ids:
        for sid in deleted_ids:
            await delete_bookmarks_for_session(sid)
        _log.info("Hard-deleted %d soft-deleted sessions", len(deleted_ids))
    return len(deleted_ids)
```

- [ ] **Step 2: Export the new function**

Add `cleanup_soft_deleted_sessions` to the `__all__` list in `__init__.py`.

- [ ] **Step 3: Update cleanup loop in main.py**

First, add the import. Change the existing import from the chat module to also include the new function. Find where `cleanup_stale_empty_sessions` is imported (likely near the top of main.py) and add `cleanup_soft_deleted_sessions` to the same import.

Then replace the `_session_cleanup_loop` function (lines 44-52) with:

```python
    # Start periodic session cleanup (every 10 minutes)
    async def _session_cleanup_loop() -> None:
        while True:
            await asyncio.sleep(600)
            try:
                await cleanup_stale_empty_sessions()
            except Exception:
                pass
            try:
                await cleanup_soft_deleted_sessions()
            except Exception:
                pass

    cleanup_task = asyncio.create_task(_session_cleanup_loop())
```

Note: Interval changed from 3600s (1 hour) to 600s (10 minutes) so soft-deleted sessions are cleaned up promptly after the 1-hour mark.

- [ ] **Step 4: Verify**

Run: `cd /home/chris/workspace/chatsune && uv run python -m py_compile backend/modules/chat/__init__.py && uv run python -m py_compile backend/main.py`
Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/__init__.py backend/main.py
git commit -m "Add soft-delete cleanup loop, run every 10 minutes"
```

---

### Task 5: Frontend — API + event subscription

**Files:**
- Modify: `frontend/src/core/api/chat.ts`
- Modify: `frontend/src/core/hooks/useChatSessions.ts`

- [ ] **Step 1: Add restoreSession to chat API**

Add after `deleteSession` (after line 61) in `frontend/src/core/api/chat.ts`:

```typescript
  restoreSession: (sessionId: string) =>
    api.post<{ status: string }>(`/api/chat/sessions/${sessionId}/restore`),
```

- [ ] **Step 2: Add CHAT_SESSION_RESTORED subscription to useChatSessions hook**

In `frontend/src/core/hooks/useChatSessions.ts`, add a new subscription inside the `useEffect` block (after the `unsubPinned` subscription, around line 68):

```typescript
    const unsubRestored = eventBus.on(Topics.CHAT_SESSION_RESTORED, (event: BaseEvent) => {
      const session = event.payload.session as ChatSessionDto
      if (!session) return
      setSessions((prev) =>
        prev.some((s) => s.id === session.id)
          ? prev
          : [...prev, session].sort((a, b) => b.updated_at.localeCompare(a.updated_at)),
      )
    })
```

And add `unsubRestored()` to the cleanup return (line 70-75):

```typescript
    return () => {
      unsubCreated()
      unsubDeleted()
      unsubTitle()
      unsubPinned()
      unsubRestored()
    }
```

- [ ] **Step 3: Verify**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`
Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/core/api/chat.ts frontend/src/core/hooks/useChatSessions.ts
git commit -m "Add restoreSession API call and CHAT_SESSION_RESTORED event subscription"
```

---

### Task 6: Frontend — Undo toast in Sidebar

**Files:**
- Modify: `frontend/src/app/components/sidebar/Sidebar.tsx`

- [ ] **Step 1: Add imports**

Add the notification store import near the top of `Sidebar.tsx`:

```typescript
import { useNotificationStore } from "../../../core/store/notificationStore"
```

- [ ] **Step 2: Add store hook inside the component**

Inside the Sidebar component function, add:

```typescript
  const addNotification = useNotificationStore((s) => s.addNotification)
```

- [ ] **Step 3: Modify handleDeleteSession to show undo toast**

Replace `handleDeleteSession` (lines 305-313) with:

```typescript
  async function handleDeleteSession(session: ChatSessionDto) {
    const wasActive = session.id === activeSessionId
    try {
      await chatApi.deleteSession(session.id)
      if (wasActive) navigate('/personas')
      addNotification({
        level: "success",
        title: "Session deleted",
        message: session.title || "Untitled session",
        duration: 8000,
        action: {
          label: "Undo",
          onClick: () => {
            chatApi.restoreSession(session.id).catch(() => {
              addNotification({
                level: "error",
                title: "Restore failed",
                message: "Could not restore the session.",
              })
            })
          },
        },
      })
    } catch {
      addNotification({
        level: "error",
        title: "Delete failed",
        message: "Could not delete the session.",
      })
    }
  }
```

- [ ] **Step 4: Verify**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`
Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/sidebar/Sidebar.tsx
git commit -m "Show undo toast after session deletion (UX-004)"
```

---

### Task 7: Manual smoke test

- [ ] **Step 1: Start the full stack**

Ensure Docker (MongoDB, Redis) and both frontend (`pnpm dev`) and backend are running.

- [ ] **Step 2: Test delete + undo flow**

1. Create a chat session with at least one message
2. Delete the session via the sidebar context menu
3. Verify: Session disappears from sidebar, toast appears with "Undo" button (8s timer)
4. Click "Undo" within 8 seconds
5. Verify: Session reappears in sidebar with all messages intact

- [ ] **Step 3: Test delete without undo**

1. Delete another session
2. Let the toast expire (8 seconds)
3. Verify: Session stays deleted, does not reappear

- [ ] **Step 4: Test delete of active session**

1. Open a chat session
2. Delete it while viewing it
3. Verify: Redirected to `/personas`, toast with undo appears
4. Click undo
5. Verify: Session reappears in sidebar (may need to navigate back to it)

- [ ] **Step 5: Commit final**

```bash
git add -A
git commit -m "Complete undo session deletion feature (UX-004)"
```

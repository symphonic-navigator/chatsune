# Memory Body Edit, Version Delete & Extract Button — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add memory body editing (creating new versions), version deletion, and a force-extract button on the Memories page.

**Architecture:** Three independent features sharing the same backend module (`backend/modules/memory/`) and frontend components. Each feature adds a backend endpoint + event + frontend UI changes. No new modules or files needed — all changes extend existing files.

**Tech Stack:** Python/FastAPI backend, React/TSX frontend, MongoDB, Redis, Zustand store, WebSocket event bus.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `shared/topics.py` | Modify (lines 87-88) | Add 2 new topic constants |
| `shared/events/memory.py` | Modify (after line 137) | Add 2 new event classes |
| `backend/modules/memory/_repository.py` | Modify (after line 271) | Add `delete_memory_body_version()` method |
| `backend/modules/memory/_handlers.py` | Modify (lines 30-36, 58-71, 282-452) | Add 2 new endpoints, modify extract endpoint |
| `frontend/src/core/api/memory.ts` | Modify (lines 63-73) | Add 2 new API methods, modify `triggerExtraction` |
| `frontend/src/core/types/events.ts` | Modify (line 80) | Add 2 new topic constants |
| `frontend/src/core/store/memoryStore.ts` | Modify | Add `removeBodyVersion` action |
| `frontend/src/features/memory/useMemoryEvents.ts` | Modify (after line 133) | Handle 2 new event types |
| `frontend/src/features/memory/MemoryBodySection.tsx` | Modify | Add edit UI and delete button |
| `frontend/src/app/components/persona-overlay/MemoriesTab.tsx` | Modify (lines 73-96) | Add Extract Now button |

---

### Task 1: Add shared contracts (topics + events)

**Files:**
- Modify: `shared/topics.py:87-88`
- Modify: `shared/events/memory.py:130-137`

- [ ] **Step 1: Add new topic constants**

In `shared/topics.py`, insert two new constants after `MEMORY_BODY_ROLLBACK` (line 87):

```python
    MEMORY_BODY_UPDATED = "memory.body.updated"
    MEMORY_BODY_VERSION_DELETED = "memory.body.version_deleted"
```

- [ ] **Step 2: Add new event classes**

In `shared/events/memory.py`, append after the `MemoryBodyRollbackEvent` class (after line 137):

```python
class MemoryBodyUpdatedEvent(BaseModel):
    type: str = "memory.body.updated"
    persona_id: str
    version: int
    token_count: int
    edited_by: str
    correlation_id: str
    timestamp: datetime


class MemoryBodyVersionDeletedEvent(BaseModel):
    type: str = "memory.body.version_deleted"
    persona_id: str
    deleted_version: int
    correlation_id: str
    timestamp: datetime
```

- [ ] **Step 3: Verify syntax**

Run: `uv run python -m py_compile shared/topics.py && uv run python -m py_compile shared/events/memory.py`
Expected: no output (clean compilation)

- [ ] **Step 4: Commit**

```bash
git add shared/topics.py shared/events/memory.py
git commit -m "Add shared contracts for memory body update and version delete"
```

---

### Task 2: Add repository method for version deletion

**Files:**
- Modify: `backend/modules/memory/_repository.py:254-271`

- [ ] **Step 1: Add `delete_memory_body_version()` method**

In `_repository.py`, add this method after `rollback_memory_body()` (after line 271):

```python
    async def delete_memory_body_version(
        self, user_id: str, persona_id: str, *, version: int,
    ) -> None:
        """Delete a specific memory body version. Raises ValueError if it is the current (latest) version."""
        latest = await self._bodies.find_one(
            {"user_id": user_id, "persona_id": persona_id},
            sort=[("version", -1)],
        )
        if latest and latest["version"] == version:
            raise ValueError("Cannot delete the current memory body version")

        result = await self._bodies.delete_one(
            {"user_id": user_id, "persona_id": persona_id, "version": version},
        )
        if result.deleted_count == 0:
            msg = f"Memory body version {version} not found for persona {persona_id}"
            raise ValueError(msg)
```

- [ ] **Step 2: Verify syntax**

Run: `uv run python -m py_compile backend/modules/memory/_repository.py`
Expected: no output (clean compilation)

- [ ] **Step 3: Commit**

```bash
git add backend/modules/memory/_repository.py
git commit -m "Add delete_memory_body_version to memory repository"
```

---

### Task 3: Add backend endpoints (update body, delete version, force extract)

**Files:**
- Modify: `backend/modules/memory/_handlers.py`

- [ ] **Step 1: Add new imports and request model**

In `_handlers.py`, add the two new event imports to the import block (lines 30-36). The full import block from `shared.events.memory` should become:

```python
from shared.events.memory import (
    MemoryBodyRollbackEvent,
    MemoryBodyUpdatedEvent,
    MemoryBodyVersionDeletedEvent,
    MemoryEntryCommittedEvent,
    MemoryEntryDeletedEvent,
    MemoryEntryUpdatedEvent,
    MemoryExtractionStartedEvent,
    MemoryDreamStartedEvent,
)
```

Add a new request model after `RollbackRequest` (after line 71):

```python
class UpdateBodyRequest(BaseModel):
    content: str
```

- [ ] **Step 2: Add `PUT /{persona_id}/body` endpoint**

Insert this endpoint after the `rollback_memory_body` handler (after line 314), before the Context section comment:

```python
@router.put("/{persona_id}/body")
async def update_memory_body(
    persona_id: str,
    body: UpdateBodyRequest,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
) -> dict:
    from backend.token_counter import count_tokens

    user_id = user["sub"]
    repo = _memory_repo()
    token_count = count_tokens(body.content)

    new_version = await repo.save_memory_body(
        user_id=user_id,
        persona_id=persona_id,
        content=body.content,
        token_count=token_count,
        entries_processed=0,
    )

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)

    await event_bus.publish(
        Topics.MEMORY_BODY_UPDATED,
        MemoryBodyUpdatedEvent(
            persona_id=persona_id,
            version=new_version,
            token_count=token_count,
            edited_by="user",
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"persona:{persona_id}",
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )

    return {"version": new_version, "token_count": token_count}
```

- [ ] **Step 3: Add `DELETE /{persona_id}/body/versions/{version}` endpoint**

Insert this endpoint after the new `update_memory_body` handler:

```python
@router.delete("/{persona_id}/body/versions/{version}")
async def delete_memory_body_version(
    persona_id: str,
    version: int,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
) -> dict:
    repo = _memory_repo()
    try:
        await repo.delete_memory_body_version(
            user["sub"], persona_id, version=version,
        )
    except ValueError as exc:
        detail = str(exc)
        status = 409 if "current" in detail.lower() else 404
        raise HTTPException(status_code=status, detail=detail)

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)

    await event_bus.publish(
        Topics.MEMORY_BODY_VERSION_DELETED,
        MemoryBodyVersionDeletedEvent(
            persona_id=persona_id,
            deleted_version=version,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"persona:{persona_id}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )

    return {"deleted_version": version}
```

- [ ] **Step 4: Add `force` query parameter to extract endpoint**

Modify the `trigger_extraction` handler (line 388-452). Add a `force` query parameter and skip cooldown/threshold checks when it is true.

Change the function signature from:

```python
@router.post("/{persona_id}/extract", status_code=202)
async def trigger_extraction(
    persona_id: str,
    user: dict = Depends(require_active_session),
) -> dict:
```

to:

```python
@router.post("/{persona_id}/extract", status_code=202)
async def trigger_extraction(
    persona_id: str,
    force: bool = Query(False),
    user: dict = Depends(require_active_session),
) -> dict:
```

No other changes needed — the extract endpoint currently does not check cooldown or message count (those checks only exist in the `get_memory_context` endpoint for the `can_trigger_extraction` field). The `force` parameter is passed through so the frontend can distinguish forced from normal extraction in the log line. Update the log message at line 447 to include the force flag:

```python
    _log.info(
        "Manual extraction triggered for persona=%s user=%s force=%s correlation=%s",
        persona_id, user_id, force, correlation_id,
    )
```

- [ ] **Step 5: Verify syntax**

Run: `uv run python -m py_compile backend/modules/memory/_handlers.py`
Expected: no output (clean compilation)

- [ ] **Step 6: Commit**

```bash
git add backend/modules/memory/_handlers.py
git commit -m "Add endpoints for memory body update, version delete, and force extract"
```

---

### Task 4: Add frontend API methods and topic constants

**Files:**
- Modify: `frontend/src/core/api/memory.ts:63-73`
- Modify: `frontend/src/core/types/events.ts:80`

- [ ] **Step 1: Add API methods and update triggerExtraction**

In `frontend/src/core/api/memory.ts`, add two new methods and update `triggerExtraction`:

Replace the existing `triggerExtraction` method (lines 69-70) with:

```typescript
  triggerExtraction: (personaId: string, force = false) => {
    const query = force ? '?force=true' : ''
    return api.post<void>(`/api/memory/${personaId}/extract${query}`)
  },
```

Add these two new methods before the closing `}` of the `memoryApi` object (before `triggerDream`):

```typescript
  updateBody: (personaId: string, content: string) =>
    api.put<{ version: number; token_count: number }>(`/api/memory/${personaId}/body`, { content }),

  deleteBodyVersion: (personaId: string, version: number) =>
    api.delete<void>(`/api/memory/${personaId}/body/versions/${version}`),
```

- [ ] **Step 2: Add topic constants**

In `frontend/src/core/types/events.ts`, add after `MEMORY_BODY_ROLLBACK` (line 80):

```typescript
  MEMORY_BODY_UPDATED: "memory.body.updated",
  MEMORY_BODY_VERSION_DELETED: "memory.body.version_deleted",
```

- [ ] **Step 3: Verify build**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/core/api/memory.ts frontend/src/core/types/events.ts
git commit -m "Add frontend API methods and topic constants for body update and version delete"
```

---

### Task 5: Add store action and event handlers

**Files:**
- Modify: `frontend/src/core/store/memoryStore.ts`
- Modify: `frontend/src/features/memory/useMemoryEvents.ts`

- [ ] **Step 1: Add `removeBodyVersion` action to store**

In `memoryStore.ts`, add a new action to the store interface and implementation. Add this action alongside the existing `setBodyVersions`:

```typescript
  removeBodyVersion: (personaId: string, version: number) => void
```

Implementation:

```typescript
  removeBodyVersion: (personaId, version) =>
    set((s) => ({
      bodyVersions: {
        ...s.bodyVersions,
        [personaId]: (s.bodyVersions[personaId] ?? []).filter(
          (v) => v.version !== version,
        ),
      },
    })),
```

- [ ] **Step 2: Add event handlers for new events**

In `useMemoryEvents.ts`, add two new cases in the `switch` block, after the `MEMORY_BODY_ROLLBACK` case (after line 133):

```typescript
        case Topics.MEMORY_BODY_UPDATED: {
          if (!_toastedCorrelations.has(event.correlation_id)) {
            _toastedCorrelations.add(event.correlation_id)
            notify().addNotification({
              level: 'info',
              title: 'Memory updated',
              message: `Memory body saved as version ${p.version as number}.`,
            })
          }
          break
        }
        case Topics.MEMORY_BODY_VERSION_DELETED: {
          store().removeBodyVersion(personaId, p.deleted_version as number)
          if (!_toastedCorrelations.has(event.correlation_id)) {
            _toastedCorrelations.add(event.correlation_id)
            notify().addNotification({
              level: 'info',
              title: 'Version deleted',
              message: `Memory body version ${p.deleted_version as number} has been deleted.`,
            })
          }
          break
        }
```

- [ ] **Step 3: Verify build**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/core/store/memoryStore.ts frontend/src/features/memory/useMemoryEvents.ts
git commit -m "Add store action and event handlers for body update and version delete"
```

---

### Task 6: Add edit UI to MemoryBodySection

**Files:**
- Modify: `frontend/src/features/memory/MemoryBodySection.tsx`

- [ ] **Step 1: Add editing state and handlers**

Add state variables after the existing `loadingVersion` state (line 20):

```typescript
  const [editing, setEditing] = useState(false)
  const [editContent, setEditContent] = useState('')
  const [saving, setSaving] = useState(false)
```

Add handler functions after `handleRollback` (after line 88):

```typescript
  const handleStartEdit = () => {
    if (!body) return
    setEditContent(body.content)
    setEditing(true)
  }

  const handleSaveEdit = async () => {
    if (saving) return
    setSaving(true)
    try {
      await memoryApi.updateBody(personaId, editContent)
      setEditing(false)
      // Reload body and versions to reflect new version
      cancelRef.current.value = true
      cancelRef.current = { value: false }
      loadBodyAndVersions(cancelRef.current)
    } finally {
      setSaving(false)
    }
  }

  const handleCancelEdit = () => {
    setEditing(false)
    setEditContent('')
  }
```

- [ ] **Step 2: Add delete version handler**

Add after the edit handlers:

```typescript
  const [deleteBusy, setDeleteBusy] = useState(false)

  const handleDeleteVersion = async () => {
    if (!viewingVersion || deleteBusy) return
    setDeleteBusy(true)
    try {
      await memoryApi.deleteBodyVersion(personaId, viewingVersion.version)
      setViewingVersion(null)
      // Reload versions
      cancelRef.current.value = true
      cancelRef.current = { value: false }
      loadBodyAndVersions(cancelRef.current)
    } finally {
      setDeleteBusy(false)
    }
  }
```

- [ ] **Step 3: Add Edit button to header**

In the header `<div>` (line 95-111), add an Edit button after the token count span but before the dreaming indicator. Only show when not editing and viewing the current version:

```tsx
        {body && !editing && !isViewingOld && !isDreaming && (
          <button
            onClick={handleStartEdit}
            className="ml-auto px-2.5 py-1 rounded text-[11px] text-white/40 hover:text-white/60 hover:bg-white/5 transition-colors"
          >
            Edit
          </button>
        )}
```

- [ ] **Step 4: Add Delete button to old-version banner**

In the `isViewingOld` banner (lines 114-135), add a Delete button after the "Rollback to this version" button:

```tsx
              <button
                onClick={handleDeleteVersion}
                disabled={deleteBusy}
                className="px-2.5 py-1 rounded text-[11px] bg-red-500/10 text-red-400 hover:bg-red-500/20 disabled:opacity-40 transition-colors"
              >
                Delete this version
              </button>
```

- [ ] **Step 5: Replace content display with edit/view toggle**

Replace the content display block (lines 137-145) with a conditional edit/view:

```tsx
        {editing ? (
          <div className="space-y-2">
            <textarea
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              className="w-full min-h-[200px] bg-white/5 border border-white/10 rounded-md p-3 text-sm text-white/80 leading-relaxed font-sans resize-y focus:outline-none focus:border-white/20"
            />
            <div className="flex gap-2 justify-end">
              <button
                onClick={handleCancelEdit}
                className="px-3 py-1.5 rounded text-[11px] text-white/40 hover:text-white/60 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveEdit}
                disabled={saving}
                className="px-3 py-1.5 rounded text-[11px] bg-purple-500/10 text-purple-400 hover:bg-purple-500/20 disabled:opacity-40 transition-colors"
              >
                {saving ? 'Saving...' : 'Save as new version'}
              </button>
            </div>
          </div>
        ) : displayed ? (
          <pre className="text-sm text-white/80 whitespace-pre-wrap leading-relaxed font-sans">
            {displayed.content}
          </pre>
        ) : (
          <p className="text-[13px] text-white/20 text-center py-6">
            No memory body yet — trigger a dream to generate one
          </p>
        )}
```

- [ ] **Step 6: Verify build**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/memory/MemoryBodySection.tsx
git commit -m "Add edit and delete UI to MemoryBodySection"
```

---

### Task 7: Add Extract Now button to MemoriesTab

**Files:**
- Modify: `frontend/src/app/components/persona-overlay/MemoriesTab.tsx`

- [ ] **Step 1: Add extraction state and handler**

Add state and store selection after the existing `dreamBusy` state (line 21):

```typescript
  const [extractBusy, setExtractBusy] = useState(false)
  const isExtracting = useMemoryStore((s) => s.isExtracting[personaId] ?? false)
```

Add handler after `handleDream` (after line 71):

```typescript
  const handleExtract = async () => {
    if (extractBusy || isExtracting) return
    setExtractBusy(true)
    try {
      await memoryApi.triggerExtraction(personaId, true)
    } finally {
      setExtractBusy(false)
    }
  }
```

- [ ] **Step 2: Add Extract Now button to header**

Add the Extract Now button in the header area (line 87-95), next to the Dream Now button. Replace the button container to include both buttons:

```tsx
        <div className="flex items-center gap-2">
          <button
            onClick={handleExtract}
            disabled={extractBusy || isExtracting}
            className="px-3 py-1.5 rounded-md text-xs bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            title="Extract memories from recent chat messages"
          >
            {isExtracting ? 'Extracting...' : 'Extract Now'}
          </button>
          <button
            onClick={handleDream}
            disabled={dreamDisabled}
            className="px-3 py-1.5 rounded-md text-xs bg-purple-500/10 text-purple-400 hover:bg-purple-500/20 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            title={committedEntries.length === 0 ? 'No committed entries to consolidate' : 'Consolidate committed entries into memory body'}
          >
            Dream Now
          </button>
        </div>
```

- [ ] **Step 3: Verify build**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/persona-overlay/MemoriesTab.tsx
git commit -m "Add Extract Now button to MemoriesTab"
```

---

### Task 8: Integration verification

- [ ] **Step 1: Full frontend build**

Run: `cd frontend && pnpm run build`
Expected: clean build, no errors

- [ ] **Step 2: Full backend syntax check**

Run: `uv run python -m py_compile backend/modules/memory/_handlers.py && uv run python -m py_compile backend/modules/memory/_repository.py && uv run python -m py_compile shared/events/memory.py && uv run python -m py_compile shared/topics.py`
Expected: no output (clean compilation)

- [ ] **Step 3: Start Docker stack and verify**

Run: `docker compose up -d`

Manual verification checklist:
1. Open the Memories page for a persona
2. Verify the "Extract Now" button is visible and clickable
3. If a memory body exists, verify the "Edit" button is visible
4. Click Edit, modify content, click "Save as new version" — verify new version appears in history
5. Click an older version — verify "Delete this version" button appears in amber banner alongside Rollback
6. Delete an older version — verify it disappears from version list and view returns to current

- [ ] **Step 4: Update TODO.md**

Remove the two completed "Missing features" items from `TODO.md`.

- [ ] **Step 5: Commit**

```bash
git add TODO.md
git commit -m "Mark memory edit and extract button features as done in TODO"
```

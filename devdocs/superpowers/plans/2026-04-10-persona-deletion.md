# Persona Deletion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to permanently delete a persona and all associated data (sessions, messages, memories, uploads, artefacts, avatar) with two-click confirmation.

**Architecture:** The existing `DELETE /api/personas/{persona_id}` endpoint is extended with cascading cleanup. Each module exposes a `delete_by_persona` (or `delete_by_session_ids` for artefacts) method via its public `__init__.py`. The frontend adds a delete button with inline confirmation to the persona overlay's Overview tab.

**Tech Stack:** Python/FastAPI backend, React/TSX frontend, MongoDB

---

### Task 1: Chat module — bulk delete by persona

**Files:**
- Modify: `backend/modules/chat/_repository.py`
- Modify: `backend/modules/chat/__init__.py`

- [ ] **Step 1: Add `delete_by_persona` to ChatRepository**

In `backend/modules/chat/_repository.py`, add this method after `hard_delete_expired_sessions` (after line ~285):

```python
async def delete_by_persona(self, user_id: str, persona_id: str) -> int:
    """Hard-delete all sessions and their messages for a persona."""
    cursor = self._sessions.find(
        {"user_id": user_id, "persona_id": persona_id},
        projection={"_id": 1},
    )
    session_ids = [doc["_id"] async for doc in cursor]
    if not session_ids:
        return 0
    await self._messages.delete_many({"session_id": {"$in": session_ids}})
    result = await self._sessions.delete_many({"_id": {"$in": session_ids}})
    return result.deleted_count
```

- [ ] **Step 2: Expose from chat module public API**

In `backend/modules/chat/__init__.py`, add a module-level function and export it.

Add the function:

```python
async def delete_by_persona(user_id: str, persona_id: str) -> int:
    """Delete all chat sessions and messages for a persona."""
    from backend.modules.chat._repository import ChatRepository
    from backend.database import get_db
    repo = ChatRepository(await get_db())
    return await repo.delete_by_persona(user_id, persona_id)
```

Add `"delete_by_persona"` to the `__all__` list.

- [ ] **Step 3: Verify syntax**

```bash
uv run python -m py_compile backend/modules/chat/_repository.py
uv run python -m py_compile backend/modules/chat/__init__.py
```

- [ ] **Step 4: Commit**

```bash
git add backend/modules/chat/_repository.py backend/modules/chat/__init__.py
git commit -m "Add chat.delete_by_persona for cascading persona deletion"
```

---

### Task 2: Memory module — bulk delete by persona

**Files:**
- Modify: `backend/modules/memory/_repository.py`
- Modify: `backend/modules/memory/__init__.py`

- [ ] **Step 1: Add `delete_by_persona` to MemoryRepository**

In `backend/modules/memory/_repository.py`, add after the existing `delete_entry` method:

```python
async def delete_by_persona(self, user_id: str, persona_id: str) -> int:
    """Delete all journal entries and memory bodies for a persona."""
    entries_result = await self._entries.delete_many(
        {"user_id": user_id, "persona_id": persona_id}
    )
    await self._bodies.delete_many(
        {"user_id": user_id, "persona_id": persona_id}
    )
    return entries_result.deleted_count
```

- [ ] **Step 2: Expose from memory module public API**

In `backend/modules/memory/__init__.py`, add a module-level function:

```python
async def delete_by_persona(user_id: str, persona_id: str) -> int:
    """Delete all memory data for a persona."""
    from backend.modules.memory._repository import MemoryRepository
    from backend.database import get_db
    repo = MemoryRepository(await get_db())
    return await repo.delete_by_persona(user_id, persona_id)
```

Add `"delete_by_persona"` to the `__all__` list.

- [ ] **Step 3: Verify syntax**

```bash
uv run python -m py_compile backend/modules/memory/_repository.py
uv run python -m py_compile backend/modules/memory/__init__.py
```

- [ ] **Step 4: Commit**

```bash
git add backend/modules/memory/_repository.py backend/modules/memory/__init__.py
git commit -m "Add memory.delete_by_persona for cascading persona deletion"
```

---

### Task 3: Storage module — bulk delete by persona (DB + physical files)

**Files:**
- Modify: `backend/modules/storage/_repository.py`
- Modify: `backend/modules/storage/__init__.py`

- [ ] **Step 1: Add `delete_by_persona` to StorageRepository**

In `backend/modules/storage/_repository.py`, add after the existing `delete` method. The method must delete physical files via BlobStore and then remove DB records:

```python
async def delete_by_persona(self, user_id: str, persona_id: str) -> int:
    """Delete all storage files (DB + physical) for a persona."""
    cursor = self._col.find(
        {"user_id": user_id, "persona_id": persona_id},
        projection={"_id": 1},
    )
    file_ids = [doc["_id"] async for doc in cursor]
    if not file_ids:
        return 0
    for file_id in file_ids:
        blob_store.delete(user_id, file_id)
    result = await self._col.delete_many({"_id": {"$in": file_ids}})
    return result.deleted_count
```

Note: `blob_store` is already instantiated at module level in this file (check the existing import pattern — it's `from backend.modules.storage._blob_store import BlobStore` with `blob_store = BlobStore()` at module level in `__init__.py`). If `blob_store` is not available in the repository, import it: `from backend.modules.storage._blob_store import BlobStore` and instantiate locally, or pass it in. Check the existing `delete` method pattern for how blob deletion is handled.

- [ ] **Step 2: Expose from storage module public API**

In `backend/modules/storage/__init__.py`, add a module-level function:

```python
async def delete_by_persona(user_id: str, persona_id: str) -> int:
    """Delete all storage files for a persona."""
    from backend.modules.storage._repository import StorageRepository
    from backend.database import get_db
    repo = StorageRepository(await get_db())
    return await repo.delete_by_persona(user_id, persona_id)
```

Add `"delete_by_persona"` to the `__all__` list.

- [ ] **Step 3: Verify syntax**

```bash
uv run python -m py_compile backend/modules/storage/_repository.py
uv run python -m py_compile backend/modules/storage/__init__.py
```

- [ ] **Step 4: Commit**

```bash
git add backend/modules/storage/_repository.py backend/modules/storage/__init__.py
git commit -m "Add storage.delete_by_persona for cascading persona deletion"
```

---

### Task 4: Artefact module — bulk delete by session IDs

**Files:**
- Modify: `backend/modules/artefact/_repository.py`
- Modify: `backend/modules/artefact/__init__.py`

- [ ] **Step 1: Add `delete_by_session_ids` to ArtefactRepository**

In `backend/modules/artefact/_repository.py`, add after the existing `delete` method:

```python
async def delete_by_session_ids(self, session_ids: list[str]) -> int:
    """Delete all artefacts and their versions for the given sessions."""
    if not session_ids:
        return 0
    cursor = self._artefacts.find(
        {"session_id": {"$in": session_ids}},
        projection={"_id": 1},
    )
    artefact_ids = [str(doc["_id"]) async for doc in cursor]
    if not artefact_ids:
        return 0
    await self._versions.delete_many({"artefact_id": {"$in": artefact_ids}})
    from bson import ObjectId
    result = await self._artefacts.delete_many(
        {"_id": {"$in": [ObjectId(aid) for aid in artefact_ids]}}
    )
    return result.deleted_count
```

- [ ] **Step 2: Expose from artefact module public API**

In `backend/modules/artefact/__init__.py`, add a module-level function:

```python
async def delete_by_session_ids(session_ids: list[str]) -> int:
    """Delete all artefacts for the given session IDs."""
    from backend.modules.artefact._repository import ArtefactRepository
    from backend.database import get_db
    repo = ArtefactRepository(await get_db())
    return await repo.delete_by_session_ids(session_ids)
```

Add `"delete_by_session_ids"` to the `__all__` list.

- [ ] **Step 3: Verify syntax**

```bash
uv run python -m py_compile backend/modules/artefact/_repository.py
uv run python -m py_compile backend/modules/artefact/__init__.py
```

- [ ] **Step 4: Commit**

```bash
git add backend/modules/artefact/_repository.py backend/modules/artefact/__init__.py
git commit -m "Add artefact.delete_by_session_ids for cascading persona deletion"
```

---

### Task 5: Extend persona delete endpoint with cascading cleanup

**Files:**
- Modify: `backend/modules/persona/_handlers.py`

- [ ] **Step 1: Extend the delete endpoint**

In `backend/modules/persona/_handlers.py`, replace the existing `delete_persona` function (lines 284-306) with the cascading version. The function needs to:

1. Verify persona exists first
2. Find session IDs for artefact cascade
3. Delete artefacts by session IDs
4. Delete chat sessions + messages
5. Delete memory entries + bodies
6. Delete storage files + physical blobs
7. Delete avatar file if it exists
8. Delete the persona document
9. Publish the event

```python
@router.delete("/{persona_id}")
async def delete_persona(
    persona_id: str,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    user_id = user["sub"]
    repo = _persona_repo()

    # Verify persona exists and belongs to user
    persona = await repo.find_by_id(persona_id, user_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    # Cascade: find session IDs for artefact cleanup
    from backend.database import get_db
    db = await get_db()
    cursor = db["chat_sessions"].find(
        {"user_id": user_id, "persona_id": persona_id},
        projection={"_id": 1},
    )
    session_ids = [doc["_id"] async for doc in cursor]

    # Cascade: artefacts (must happen before sessions are deleted)
    from backend.modules.artefact import delete_by_session_ids as delete_artefacts
    await delete_artefacts(session_ids)

    # Cascade: chat sessions + messages
    from backend.modules.chat import delete_by_persona as delete_chats
    await delete_chats(user_id, persona_id)

    # Cascade: memory
    from backend.modules.memory import delete_by_persona as delete_memories
    await delete_memories(user_id, persona_id)

    # Cascade: storage files
    from backend.modules.storage import delete_by_persona as delete_storage
    await delete_storage(user_id, persona_id)

    # Cascade: avatar file
    if persona.get("profile_image"):
        avatar_store = AvatarStore()
        avatar_store.delete(persona["profile_image"])

    # Delete the persona itself
    await repo.delete(persona_id, user_id)

    await event_bus.publish(
        Topics.PERSONA_DELETED,
        PersonaDeletedEvent(
            persona_id=persona_id,
            user_id=user_id,
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"persona:{persona_id}",
        target_user_ids=[user_id],
    )

    return {"status": "ok"}
```

Note: The imports `AvatarStore`, `PersonaDeletedEvent`, `Topics`, `datetime`, `timezone` are already imported at the top of `_handlers.py`. The cascade imports are done inline to avoid circular dependencies.

- [ ] **Step 2: Verify syntax**

```bash
uv run python -m py_compile backend/modules/persona/_handlers.py
```

- [ ] **Step 3: Commit**

```bash
git add backend/modules/persona/_handlers.py
git commit -m "Extend persona delete endpoint with cascading data cleanup"
```

---

### Task 6: Frontend — delete button with confirmation on OverviewTab

**Files:**
- Modify: `frontend/src/app/components/persona-overlay/OverviewTab.tsx`
- Modify: `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx`

- [ ] **Step 1: Add `onDelete` prop and delete UI to OverviewTab**

In `frontend/src/app/components/persona-overlay/OverviewTab.tsx`:

Add `onDelete` to the props interface:

```typescript
interface OverviewTabProps {
  persona: PersonaDto
  chakra: ChakraPaletteEntry
  onContinue: () => void
  onNewChat: () => void
  onNewIncognitoChat: () => void
  hasLastChat: boolean
  chatCount: number
  onGoToHistory: () => void
  onDelete: () => Promise<void>
}
```

Add state for the confirmation flow. After the existing `useState` calls (line 24):

```typescript
const [confirmDelete, setConfirmDelete] = useState(false)
const [deleting, setDeleting] = useState(false)
```

Add the delete handler:

```typescript
async function handleDelete() {
  setDeleting(true)
  try {
    await onDelete()
  } catch {
    setDeleting(false)
    setConfirmDelete(false)
  }
}
```

Add the delete section in the JSX, after the "Created date" paragraph (line 229), before the closing `</div>`:

```tsx
{/* Danger zone — delete */}
<div className="w-full max-w-sm mt-4 pt-4" style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
  {!confirmDelete ? (
    <button
      type="button"
      onClick={() => setConfirmDelete(true)}
      className="w-full rounded-lg py-2 text-[12px] font-medium text-red-400/60 transition-colors hover:bg-red-400/8 hover:text-red-400/80"
      style={{ border: '1px solid rgba(248,113,113,0.15)' }}
    >
      Delete persona
    </button>
  ) : (
    <div className="rounded-lg p-3" style={{ border: '1px solid rgba(248,113,113,0.25)', background: 'rgba(248,113,113,0.06)' }}>
      <p className="text-[12px] text-red-300/70 mb-3">
        This will permanently delete <strong className="text-red-300/90">{persona.name}</strong>, all chat history, memories, uploads and artefacts. This cannot be undone.
      </p>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={handleDelete}
          disabled={deleting}
          className="flex-1 rounded-lg py-2 text-[12px] font-medium text-white bg-red-500/80 hover:bg-red-500 transition-colors disabled:opacity-50"
        >
          {deleting ? 'Deleting...' : 'Delete permanently'}
        </button>
        <button
          type="button"
          onClick={() => setConfirmDelete(false)}
          disabled={deleting}
          className="px-3 rounded-lg py-2 text-[12px] text-white/50 hover:text-white/70 transition-colors disabled:opacity-50"
        >
          Cancel
        </button>
      </div>
    </div>
  )}
</div>
```

Update the function signature to include `onDelete`:

```typescript
export function OverviewTab({ persona, chakra, onContinue, onNewChat, onNewIncognitoChat, hasLastChat, chatCount, onGoToHistory, onDelete }: OverviewTabProps) {
```

- [ ] **Step 2: Wire up onDelete in PersonaOverlay**

In `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx`:

Add imports at the top:

```typescript
import { personasApi } from '../../../core/api/personas'
import { useNotificationStore } from '../../../core/store/notificationStore'
```

Inside the component, before the return statement, add the notification store and delete handler:

```typescript
const addNotification = useNotificationStore((s) => s.addNotification)

const handleDeletePersona = async () => {
  if (!resolved?.id) return
  await personasApi.remove(resolved.id)
  onClose()
  onNavigate?.('/personas')
  addNotification({
    level: 'success',
    title: 'Persona deleted',
    message: `${resolved.name} has been permanently deleted.`,
  })
}
```

Then in the JSX where `OverviewTab` is rendered (line ~210), add the `onDelete` prop:

```tsx
<OverviewTab
  persona={resolved}
  chakra={chakra}
  hasLastChat={!!(sessions ?? []).find((s) => s.persona_id === resolved.id)}
  onContinue={() => { /* existing */ }}
  onNewChat={() => { /* existing */ }}
  onNewIncognitoChat={() => { /* existing */ }}
  chatCount={(sessions ?? []).filter((s) => s.persona_id === resolved.id).length}
  onGoToHistory={() => onTabChange('history')}
  onDelete={handleDeletePersona}
/>
```

- [ ] **Step 3: Build and verify**

```bash
cd frontend && pnpm run build
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/persona-overlay/OverviewTab.tsx frontend/src/app/components/persona-overlay/PersonaOverlay.tsx
git commit -m "Add persona delete button with two-click confirmation to overview tab"
```

# Memory Body Edit, Version Delete & Extract Button

**Date:** 2026-04-12
**Status:** Approved

---

## Summary

Three enhancements to the memory subsystem:

1. **Memory Body editing** — users can edit the consolidated memory body, creating a new version
2. **Version deletion** — users can delete older (non-current) memory body versions
3. **Extract button on Memories page** — force-trigger memory extraction without cooldown/threshold restrictions

---

## Feature 1: Memory Body Editing

### Motivation

Users need to correct misunderstandings in the consolidated memory. Currently the only
options are rollback (losing newer content) or waiting for the next dream cycle. Direct
editing lets users fix issues immediately.

### Backend

**Endpoint:** `PUT /api/memory/{persona_id}/body`

**Request body:**
```json
{ "content": "string" }
```

**Behaviour:**
- Creates a new version (increments `version` field), identical to how dreaming creates versions
- Token count is computed server-side (same tokeniser as consolidation)
- Existing pruning applies (max 5 versions, oldest pruned)
- Publishes `MemoryBodyUpdatedEvent`

**New event** (`shared/events/memory.py`):
```python
class MemoryBodyUpdatedEvent(BaseModel):
    persona_id: str
    version: int
    token_count: int
    edited_by: Literal["user"]
```

**New topic** (`shared/topics.py`):
```python
MEMORY_BODY_UPDATED = "memory.body.updated"
```

### Frontend (MemoryBodySection)

- "Edit" button next to the current version header
- Click opens a textarea pre-filled with current body content
- Save / Cancel buttons below the textarea
- Save calls `PUT /api/memory/{persona_id}/body`
- On success: version list and body content refresh
- Event handler for `MemoryBodyUpdatedEvent` updates store + shows toast
- Edit button only visible when viewing the current (latest) version

### API Client Addition (`memory.ts`)

```typescript
updateBody(personaId: string, content: string): Promise<void>
```

---

## Feature 2: Version Deletion

### Motivation

Over time, outdated or incorrect versions accumulate. Users should be able to
clean up old versions they no longer need, without affecting the current memory.

### Backend

**Endpoint:** `DELETE /api/memory/{persona_id}/body/versions/{version}`

**Behaviour:**
- Returns 409 Conflict if `version` equals the current (latest) version
- Deletes the specified version document from MongoDB
- Publishes `MemoryBodyVersionDeletedEvent`

**New event** (`shared/events/memory.py`):
```python
class MemoryBodyVersionDeletedEvent(BaseModel):
    persona_id: str
    deleted_version: int
```

**New topic** (`shared/topics.py`):
```python
MEMORY_BODY_VERSION_DELETED = "memory.body.version_deleted"
```

### Frontend (MemoryBodySection)

- When viewing an older (non-current) version: "Delete" button appears in the
  amber banner alongside the existing "Rollback to this version" button
- After deletion: view returns to the current version, version list refreshes
- Event handler updates version list in store + shows toast

### API Client Addition (`memory.ts`)

```typescript
deleteBodyVersion(personaId: string, version: number): Promise<void>
```

---

## Feature 3: Extract Button on Memories Page

### Motivation

Beta testers expect to trigger memory extraction from the Memories page. The
existing "Extract Now" button in the JournalDropdown (chat view) enforces
cooldown and message-count thresholds. The Memories page is a power-user area
where these restrictions should not apply.

### Backend

**Change to existing endpoint:** `POST /api/memory/{persona_id}/extract`

- Add query parameter `?force=true`
- When `force=true`: skip cooldown check and message-count threshold
- In-flight protection remains active (Redis slot, 409 if extraction already running)
- All existing extraction events (Started/Completed/Failed/Skipped) remain unchanged

### Frontend (MemoriesTab)

- "Extract Now" button in the Memories page header area
- Calls `/api/memory/{persona_id}/extract?force=true`
- Disabled only when `isExtracting` is true for this persona
- No other changes needed — existing `useMemoryEvents` hook already handles
  all extraction events

### API Client Addition (`memory.ts`)

```typescript
triggerExtraction(personaId: string, force?: boolean): Promise<void>
```

Update the existing `triggerExtraction` method to accept an optional `force` parameter.

---

## Out of Scope

- Editing individual journal entries (already implemented)
- Memory body content validation or length limits beyond token counting
- Changes to the dreaming/consolidation process itself
- Changes to the JournalDropdown Extract button behaviour

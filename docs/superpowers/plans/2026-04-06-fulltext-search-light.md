# Fulltext Search (Light) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add server-side fulltext search across chat message content and session titles, returning matching sessions (no previews/snippets).

**Architecture:** MongoDB `$text` index on `chat_messages.content` for fast AND-linked keyword search. Session titles searched via regex (small result set per user, max 200). New `GET /api/chat/sessions/search` endpoint. Frontend calls backend when search text is present, keeps existing client-side filtering for empty search.

**Tech Stack:** MongoDB text index, FastAPI, React

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `backend/modules/chat/_repository.py` | Add text index, add `search_sessions()` method |
| Modify | `backend/modules/chat/_handlers.py` | Add `GET /api/chat/sessions/search` endpoint |
| Modify | `backend/modules/chat/__init__.py` | Re-export if needed (check `__all__`) |
| Modify | `frontend/src/core/api/chat.ts` | Add `searchSessions()` API method |
| Modify | `frontend/src/app/components/user-modal/HistoryTab.tsx` | Use backend search when query present |
| Modify | `frontend/src/app/components/persona-overlay/HistoryTab.tsx` | Use backend search when query present |

---

### Task 1: MongoDB Text Index and Search Repository Method

**Files:**
- Modify: `backend/modules/chat/_repository.py:15-19` (add text index)
- Modify: `backend/modules/chat/_repository.py` (add `search_sessions` method)

- [ ] **Step 1: Add text index on `chat_messages.content`**

In `create_indexes()`, add the text index after the existing indexes:

```python
async def create_indexes(self) -> None:
    await self._sessions.create_index("user_id")
    await self._sessions.create_index([("user_id", 1), ("updated_at", -1)])
    await self._messages.create_index("session_id")
    await self._messages.create_index([("session_id", 1), ("created_at", 1)])
    await self._messages.create_index(
        [("content", "text")],
        default_language="english",
        name="content_text",
    )
```

Note: MongoDB allows only one `$text` index per collection. This is the only text index we need on `chat_messages`.

- [ ] **Step 2: Add `search_sessions` method to `ChatRepository`**

Add this method after `list_sessions()`:

```python
async def search_sessions(
    self,
    user_id: str,
    query: str,
    persona_id: str | None = None,
    exclude_persona_ids: list[str] | None = None,
) -> list[dict]:
    """Search sessions by message content ($text) and session title (regex).

    Returns sessions sorted by pinned desc, updated_at desc.
    Only user and assistant messages are searched (not tool messages).
    """
    # Step 1: Build session filter
    session_filter: dict = {"user_id": user_id, "deleted_at": None}
    if persona_id:
        session_filter["persona_id"] = persona_id
    if exclude_persona_ids:
        session_filter.setdefault("persona_id", {})
        if isinstance(session_filter["persona_id"], str):
            # persona_id is already set — no exclusion needed, it's a single filter
            pass
        else:
            session_filter["persona_id"] = {"$nin": exclude_persona_ids}

    # Step 2: Get candidate session IDs for this user
    candidate_docs = await self._sessions.find(
        session_filter, {"_id": 1},
    ).to_list(length=500)
    candidate_ids = [doc["_id"] for doc in candidate_docs]
    if not candidate_ids:
        return []

    # Step 3: Text search on messages (user + assistant only)
    message_hits = await self._messages.find(
        {
            "$text": {"$search": query},
            "session_id": {"$in": candidate_ids},
            "role": {"$in": ["user", "assistant"]},
        },
        {"session_id": 1},
    ).to_list(length=5000)
    message_session_ids = {doc["session_id"] for doc in message_hits}

    # Step 4: Regex search on session titles
    # Build a regex that requires ALL terms (AND logic)
    terms = query.strip().split()
    title_filter = dict(session_filter)
    title_filter["_id"] = {"$in": candidate_ids}
    if terms:
        title_filter["$and"] = [
            {"title": {"$regex": re.escape(term), "$options": "i"}}
            for term in terms
        ]
    title_hits = await self._sessions.find(
        title_filter, {"_id": 1},
    ).to_list(length=500)
    title_session_ids = {doc["_id"] for doc in title_hits}

    # Step 5: Union and fetch full session docs
    matching_ids = list(message_session_ids | title_session_ids)
    if not matching_ids:
        return []

    pipeline = [
        {"$match": {"_id": {"$in": matching_ids}}},
        {"$sort": {"pinned": -1, "updated_at": -1}},
        {"$limit": 200},
    ]
    return await self._sessions.aggregate(pipeline).to_list(length=200)
```

- [ ] **Step 3: Add `import re` at top of file**

Add `import re` to the imports at the top of `_repository.py`:

```python
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4
```

- [ ] **Step 4: Verify syntax**

Run: `uv run python -m py_compile backend/modules/chat/_repository.py`
Expected: No output (clean compile)

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/_repository.py
git commit -m "Add fulltext search index and search_sessions repository method"
```

---

### Task 2: Search API Endpoint

**Files:**
- Modify: `backend/modules/chat/_handlers.py` (add search endpoint)

- [ ] **Step 1: Add search endpoint**

Add this endpoint BEFORE the `get_session` route (important: `/sessions/search` must come before `/sessions/{session_id}` so FastAPI doesn't treat "search" as a session_id):

```python
from fastapi import Query


@router.get("/sessions/search")
async def search_sessions(
    q: str = Query(min_length=1, max_length=200, strip_whitespace=True),
    persona_id: str | None = Query(default=None),
    exclude_persona_ids: str | None = Query(default=None),
    user: dict = Depends(require_active_session),
):
    repo = _chat_repo()
    excluded = (
        [pid.strip() for pid in exclude_persona_ids.split(",") if pid.strip()]
        if exclude_persona_ids
        else None
    )
    docs = await repo.search_sessions(
        user_id=user["sub"],
        query=q,
        persona_id=persona_id,
        exclude_persona_ids=excluded,
    )
    return [ChatRepository.session_to_dto(d) for d in docs]
```

Note on imports: `Query` is already available from FastAPI — just add it to the existing import line: `from fastapi import APIRouter, Depends, HTTPException, Query`.

- [ ] **Step 2: Ensure route ordering**

The new `/sessions/search` endpoint MUST be placed before `@router.get("/sessions/{session_id}")` in the file. FastAPI matches routes in definition order — if `{session_id}` comes first, it will capture "search" as a session ID.

Place it directly after the `list_sessions` endpoint (after line 80).

- [ ] **Step 3: Verify syntax**

Run: `uv run python -m py_compile backend/modules/chat/_handlers.py`
Expected: No output (clean compile)

- [ ] **Step 4: Commit**

```bash
git add backend/modules/chat/_handlers.py
git commit -m "Add GET /api/chat/sessions/search endpoint"
```

---

### Task 3: Frontend API Client

**Files:**
- Modify: `frontend/src/core/api/chat.ts`

- [ ] **Step 1: Add `searchSessions` method**

Add to the `chatApi` object, after `listSessions`:

```typescript
searchSessions: (params: {
  q: string
  persona_id?: string
  exclude_persona_ids?: string[]
}) => {
  const searchParams = new URLSearchParams({ q: params.q })
  if (params.persona_id) searchParams.set('persona_id', params.persona_id)
  if (params.exclude_persona_ids?.length) {
    searchParams.set('exclude_persona_ids', params.exclude_persona_ids.join(','))
  }
  return api.get<ChatSessionDto[]>(`/api/chat/sessions/search?${searchParams}`)
},
```

- [ ] **Step 2: Verify build**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/core/api/chat.ts
git commit -m "Add searchSessions to chat API client"
```

---

### Task 4: User-Modal HistoryTab — Backend Search Integration

**Files:**
- Modify: `frontend/src/app/components/user-modal/HistoryTab.tsx`

- [ ] **Step 1: Add search state and debounced query**

Add imports and state for backend search results. The approach: when search is non-empty, debounce 300ms, then call the backend. When search is empty, use existing client-side filtering.

Add to imports at top of file:

```typescript
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
```

(Already imported — no change needed for these.)

Add `chatApi` import alongside existing import — it's already imported on line 3:

```typescript
import { chatApi, type ChatSessionDto } from '../../../core/api/chat'
```

(Already present — no change.)

- [ ] **Step 2: Add debounced backend search**

Inside the `HistoryTab` component, after the existing state declarations (line 56), add:

```typescript
const [searchResults, setSearchResults] = useState<ChatSessionDto[] | null>(null)
const [isSearching, setIsSearching] = useState(false)
const searchTimer = useRef<ReturnType<typeof setTimeout>>()

// Debounced backend search
useEffect(() => {
  if (searchTimer.current) clearTimeout(searchTimer.current)

  const trimmed = search.trim()
  if (!trimmed) {
    setSearchResults(null)
    setIsSearching(false)
    return
  }

  setIsSearching(true)
  searchTimer.current = setTimeout(async () => {
    try {
      const excludeIds = isSanitised
        ? personas.filter((p) => p.nsfw).map((p) => p.id)
        : undefined
      const results = await chatApi.searchSessions({
        q: trimmed,
        persona_id: personaFilter !== 'all' ? personaFilter : undefined,
        exclude_persona_ids: excludeIds,
      })
      setSearchResults(results)
    } catch {
      setSearchResults([])
    } finally {
      setIsSearching(false)
    }
  }, 300)

  return () => {
    if (searchTimer.current) clearTimeout(searchTimer.current)
  }
}, [search, personaFilter, isSanitised, personas])
```

- [ ] **Step 3: Update the `filtered` memo to use search results when available**

Replace the existing `filtered` useMemo (lines 66-94) with:

```typescript
const filtered = useMemo(() => {
  // When backend search is active, use those results
  if (searchResults !== null) {
    return searchResults
  }

  // No search query — client-side filtering only
  let result = sessions

  if (isSanitised) {
    result = result.filter((s) => !nsfwPersonaIds.has(s.persona_id))
  }

  if (personaFilter !== 'all') {
    result = result.filter((s) => s.persona_id === personaFilter)
  }

  return result
}, [sessions, searchResults, personaFilter, isSanitised, nsfwPersonaIds])
```

- [ ] **Step 4: Update loading state**

In the JSX, update the loading indicator to also show during search. Change line 140-142:

```tsx
{(isLoading || isSearching) && (
  <p className="px-4 py-3 text-[12px] text-white/30 font-mono">
    {isSearching ? 'Searching...' : 'Loading...'}
  </p>
)}
```

- [ ] **Step 5: Verify build**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/components/user-modal/HistoryTab.tsx
git commit -m "Integrate backend fulltext search in user history tab"
```

---

### Task 5: Persona-Overlay HistoryTab — Backend Search Integration

**Files:**
- Modify: `frontend/src/app/components/persona-overlay/HistoryTab.tsx`

- [ ] **Step 1: Add search state and debounced query**

Inside the `HistoryTab` component, after line 55 (`const navigate = useNavigate()`), add:

```typescript
const [searchResults, setSearchResults] = useState<ChatSessionDto[] | null>(null)
const [isSearching, setIsSearching] = useState(false)
const searchTimer = useRef<ReturnType<typeof setTimeout>>()

useEffect(() => {
  if (searchTimer.current) clearTimeout(searchTimer.current)

  const trimmed = search.trim()
  if (!trimmed) {
    setSearchResults(null)
    setIsSearching(false)
    return
  }

  setIsSearching(true)
  searchTimer.current = setTimeout(async () => {
    try {
      const results = await chatApi.searchSessions({
        q: trimmed,
        persona_id: persona.id,
      })
      setSearchResults(results)
    } catch {
      setSearchResults([])
    } finally {
      setIsSearching(false)
    }
  }, 300)

  return () => {
    if (searchTimer.current) clearTimeout(searchTimer.current)
  }
}, [search, persona.id])
```

- [ ] **Step 2: Update the `filtered` memo**

Replace the existing `filtered` useMemo (lines 57-69) with:

```typescript
const filtered = useMemo(() => {
  if (searchResults !== null) {
    return searchResults
  }
  return sessions.filter((s) => s.persona_id === persona.id)
}, [sessions, searchResults, persona.id])
```

- [ ] **Step 3: Update loading state in JSX**

Change the loading indicator (around line 97):

```tsx
{(isLoading || isSearching) && (
  <p className="px-4 py-3 text-[12px] text-white/30 font-mono">
    {isSearching ? 'Searching...' : 'Loading...'}
  </p>
)}
```

- [ ] **Step 4: Verify build**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/persona-overlay/HistoryTab.tsx
git commit -m "Integrate backend fulltext search in persona history tab"
```

---

### Task 6: Build Verification and Manual Test

- [ ] **Step 1: Full frontend build**

Run: `cd frontend && pnpm run build`
Expected: Clean build, no errors

- [ ] **Step 2: Backend syntax check on all modified files**

Run:
```bash
uv run python -m py_compile backend/modules/chat/_repository.py
uv run python -m py_compile backend/modules/chat/_handlers.py
```
Expected: No output (clean compile)

- [ ] **Step 3: Verify text index creation**

Start the application and check MongoDB logs or run a quick test:

```bash
# After app startup, the index should be created automatically.
# Verify by checking the logs for any index creation errors.
```

- [ ] **Step 4: Final commit (if any fixups needed)**

```bash
git add -A
git commit -m "Fix any build issues from fulltext search integration"
```

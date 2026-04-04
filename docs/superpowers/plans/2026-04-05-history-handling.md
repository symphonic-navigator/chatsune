# History Handling Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add session delete, title display, persona filtering, inline rename, title regeneration, and reactive event-driven updates to chat history across sidebar and user modal.

**Architecture:** Backend gets two new endpoints (PATCH rename, POST generate-title) and two new events (session.created, session.deleted). Frontend `useChatSessions` hook subscribes to WebSocket events for real-time list updates. HistoryTab gets a full rework with persona filter dropdown, inline rename, and action buttons. Sidebar HistoryItem gets a hover menu with delete.

**Tech Stack:** FastAPI, Pydantic, MongoDB, Redis Streams, React, Zustand, TypeScript

---

### Task 1: Add shared contracts — new events and topics

**Files:**
- Modify: `shared/topics.py:33` — add two new topic constants
- Modify: `shared/events/chat.py:72-77` — add two new event classes
- Modify: `frontend/src/core/types/events.ts:49-50` — add two new topic constants

- [ ] **Step 1: Add topic constants to backend**

In `shared/topics.py`, add after line 33 (`CHAT_SESSION_TITLE_UPDATED`):

```python
    CHAT_SESSION_CREATED = "chat.session.created"
    CHAT_SESSION_DELETED = "chat.session.deleted"
```

- [ ] **Step 2: Add event classes to backend**

In `shared/events/chat.py`, add after `ChatSessionTitleUpdatedEvent` (line 77):

```python


class ChatSessionCreatedEvent(BaseModel):
    type: str = "chat.session.created"
    session_id: str
    user_id: str
    persona_id: str
    model_unique_id: str
    title: str | None = None
    created_at: str
    updated_at: str
    correlation_id: str
    timestamp: datetime


class ChatSessionDeletedEvent(BaseModel):
    type: str = "chat.session.deleted"
    session_id: str
    correlation_id: str
    timestamp: datetime
```

- [ ] **Step 3: Add topic constants to frontend**

In `frontend/src/core/types/events.ts`, add after `CHAT_SESSION_TITLE_UPDATED` (line 49):

```typescript
  CHAT_SESSION_CREATED: "chat.session.created",
  CHAT_SESSION_DELETED: "chat.session.deleted",
```

- [ ] **Step 4: Add fan-out rules for new events**

In `backend/ws/event_bus.py`, add to the `_FANOUT` dict after `Topics.CHAT_SESSION_TITLE_UPDATED` (line 40):

```python
    Topics.CHAT_SESSION_CREATED: ([], True),
    Topics.CHAT_SESSION_DELETED: ([], True),
```

- [ ] **Step 5: Commit**

```bash
git add shared/topics.py shared/events/chat.py frontend/src/core/types/events.ts backend/ws/event_bus.py
git commit -m "Add chat.session.created and chat.session.deleted events and topics"
```

---

### Task 2: Backend — publish events on create and delete, add PATCH and generate-title endpoints

**Files:**
- Modify: `backend/modules/chat/_handlers.py` — publish events on create/delete, add PATCH and POST generate-title endpoints
- Modify: `backend/modules/chat/__init__.py:28-38` — add new event imports to `__init__.py`

- [ ] **Step 1: Update `_handlers.py` imports**

Replace the imports at the top of `backend/modules/chat/_handlers.py`:

```python
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.database import get_db
from backend.dependencies import require_active_session
from backend.jobs import submit, JobType
from backend.modules.chat._repository import ChatRepository
from backend.modules.persona._repository import PersonaRepository
from backend.ws.event_bus import get_event_bus
from shared.events.chat import (
    ChatSessionCreatedEvent,
    ChatSessionDeletedEvent,
    ChatSessionTitleUpdatedEvent,
)
from shared.topics import Topics
```

- [ ] **Step 2: Publish `chat.session.created` event in `create_session`**

Replace the `create_session` handler in `_handlers.py`:

```python
@router.post("/sessions", status_code=201)
async def create_session(
    body: CreateSessionRequest,
    user: dict = Depends(require_active_session),
):
    persona_repo = _persona_repo()
    persona = await persona_repo.find_by_id(body.persona_id, user["sub"])
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    repo = _chat_repo()
    doc = await repo.create_session(
        user_id=user["sub"],
        persona_id=persona["_id"],
        model_unique_id=persona["model_unique_id"],
    )
    dto = ChatRepository.session_to_dto(doc)

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.CHAT_SESSION_CREATED,
        ChatSessionCreatedEvent(
            session_id=dto.id,
            user_id=dto.user_id,
            persona_id=dto.persona_id,
            model_unique_id=dto.model_unique_id,
            title=dto.title,
            created_at=dto.created_at.isoformat(),
            updated_at=dto.updated_at.isoformat(),
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"session:{dto.id}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )

    return dto
```

- [ ] **Step 3: Publish `chat.session.deleted` event in `delete_session`**

Replace the `delete_session` handler in `_handlers.py`:

```python
@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user: dict = Depends(require_active_session)):
    repo = _chat_repo()
    deleted = await repo.delete_session(session_id, user["sub"])
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

- [ ] **Step 4: Add PATCH rename endpoint**

Add a new request model and endpoint after `delete_session` in `_handlers.py`:

```python
class UpdateSessionRequest(BaseModel):
    title: str


@router.patch("/sessions/{session_id}")
async def update_session(
    session_id: str,
    body: UpdateSessionRequest,
    user: dict = Depends(require_active_session),
):
    repo = _chat_repo()
    session = await repo.get_session(session_id, user["sub"])
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await repo.update_session_title(session_id, body.title)

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.CHAT_SESSION_TITLE_UPDATED,
        ChatSessionTitleUpdatedEvent(
            session_id=session_id,
            title=body.title,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user["sub"]],
        correlation_id=correlation_id,
    )

    doc = await repo.get_session(session_id, user["sub"])
    return ChatRepository.session_to_dto(doc)
```

- [ ] **Step 5: Add POST generate-title endpoint**

Add after the PATCH endpoint in `_handlers.py`:

```python
@router.post("/sessions/{session_id}/generate-title", status_code=202)
async def generate_title(
    session_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _chat_repo()
    session = await repo.get_session(session_id, user["sub"])
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = await repo.list_messages(session_id)
    if len(messages) < 2:
        raise HTTPException(status_code=400, detail="Session needs at least 2 messages")

    first_user = next((m for m in messages if m["role"] == "user"), None)
    first_assistant = next((m for m in messages if m["role"] == "assistant"), None)
    if not first_user or not first_assistant:
        raise HTTPException(status_code=400, detail="Session needs at least one user and one assistant message")

    model_unique_id = session.get("model_unique_id", "")
    correlation_id = str(uuid4())

    await submit(
        job_type=JobType.TITLE_GENERATION,
        user_id=user["sub"],
        model_unique_id=model_unique_id,
        payload={
            "session_id": session_id,
            "messages": [
                {"role": "user", "content": first_user["content"]},
                {"role": "assistant", "content": first_assistant["content"]},
            ],
        },
        correlation_id=correlation_id,
    )

    return {"status": "submitted"}
```

- [ ] **Step 6: Update `__init__.py` imports**

In `backend/modules/chat/__init__.py`, add the new event imports to the existing import block (line 28-38):

```python
from shared.events.chat import (
    ChatContentDeltaEvent,
    ChatMessageDeletedEvent,
    ChatMessagesTruncatedEvent,
    ChatMessageUpdatedEvent,
    ChatSessionCreatedEvent,
    ChatSessionDeletedEvent,
    ChatSessionTitleUpdatedEvent,
    ChatStreamEndedEvent,
    ChatStreamErrorEvent,
    ChatStreamStartedEvent,
    ChatThinkingDeltaEvent,
)
```

- [ ] **Step 7: Commit**

```bash
git add backend/modules/chat/_handlers.py backend/modules/chat/__init__.py
git commit -m "Add PATCH rename and POST generate-title endpoints, publish session events"
```

---

### Task 3: Frontend API — add new chat API methods

**Files:**
- Modify: `frontend/src/core/api/chat.ts` — add `deleteSession`, `updateSession`, `generateTitle`

- [ ] **Step 1: Add new API methods**

In `frontend/src/core/api/chat.ts`, add to the `chatApi` object after `getMessages`:

```typescript
  deleteSession: (sessionId: string) =>
    api.delete<{ status: string }>(`/api/chat/sessions/${sessionId}`),

  updateSession: (sessionId: string, body: { title: string }) =>
    api.patch<ChatSessionDto>(`/api/chat/sessions/${sessionId}`, body),

  generateTitle: (sessionId: string) =>
    api.post<{ status: string }>(`/api/chat/sessions/${sessionId}/generate-title`),
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/core/api/chat.ts
git commit -m "Add deleteSession, updateSession, generateTitle to chat API client"
```

---

### Task 4: Reactive `useChatSessions` hook — subscribe to WebSocket events

**Files:**
- Modify: `frontend/src/core/hooks/useChatSessions.ts` — add event subscriptions

- [ ] **Step 1: Rewrite the hook to subscribe to events**

Replace the entire content of `frontend/src/core/hooks/useChatSessions.ts`:

```typescript
import { useCallback, useEffect, useState } from "react"
import { chatApi, type ChatSessionDto } from "../api/chat"
import { eventBus } from "../websocket/eventBus"
import { Topics } from "../types/events"
import type { BaseEvent } from "../types/events"

export function useChatSessions() {
  const [sessions, setSessions] = useState<ChatSessionDto[]>([])
  const [isLoading, setIsLoading] = useState(false)

  const fetch = useCallback(async () => {
    setIsLoading(true)
    try {
      const res = await chatApi.listSessions()
      setSessions(res.sort((a, b) => b.updated_at.localeCompare(a.updated_at)))
    } catch {
      // Empty history is acceptable — API may not have sessions yet
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetch()
  }, [fetch])

  // Subscribe to session lifecycle events
  useEffect(() => {
    const unsubCreated = eventBus.on(Topics.CHAT_SESSION_CREATED, (event: BaseEvent) => {
      const p = event.payload
      const newSession: ChatSessionDto = {
        id: p.session_id as string,
        user_id: p.user_id as string,
        persona_id: p.persona_id as string,
        model_unique_id: p.model_unique_id as string,
        state: "idle",
        title: (p.title as string) ?? null,
        created_at: p.created_at as string,
        updated_at: p.updated_at as string,
      }
      setSessions((prev) => [newSession, ...prev])
    })

    const unsubDeleted = eventBus.on(Topics.CHAT_SESSION_DELETED, (event: BaseEvent) => {
      const sessionId = event.payload.session_id as string
      setSessions((prev) => prev.filter((s) => s.id !== sessionId))
    })

    const unsubTitle = eventBus.on(Topics.CHAT_SESSION_TITLE_UPDATED, (event: BaseEvent) => {
      const sessionId = event.payload.session_id as string
      const title = event.payload.title as string
      setSessions((prev) =>
        prev.map((s) => (s.id === sessionId ? { ...s, title } : s)),
      )
    })

    return () => {
      unsubCreated()
      unsubDeleted()
      unsubTitle()
    }
  }, [])

  return { sessions, isLoading, refetch: fetch }
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/core/hooks/useChatSessions.ts
git commit -m "Make useChatSessions reactive via WebSocket event subscriptions"
```

---

### Task 5: Sidebar HistoryItem — add hover menu with delete

**Files:**
- Modify: `frontend/src/app/components/sidebar/HistoryItem.tsx` — add menu with delete action
- Modify: `frontend/src/app/components/sidebar/Sidebar.tsx:100-103,391-400` — pass `onDelete` to HistoryItem, add delete handler

- [ ] **Step 1: Rewrite HistoryItem with hover menu**

Replace the entire content of `frontend/src/app/components/sidebar/HistoryItem.tsx`:

```typescript
import { useState, useRef, useEffect } from "react"
import type { ChatSessionDto } from "../../../core/api/chat"

function formatSessionDate(isoString: string): string {
  const d = new Date(isoString)
  return d.toLocaleDateString("de-DE", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  })
}

interface HistoryItemProps {
  session: ChatSessionDto
  isPinned: boolean
  isActive: boolean
  onClick: (session: ChatSessionDto) => void
  onDelete: (session: ChatSessionDto) => void
}

export function HistoryItem({ session, isPinned, isActive, onClick, onDelete }: HistoryItemProps) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
        setConfirmDelete(false)
      }
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [menuOpen])

  return (
    <div
      className={`group relative mx-1.5 flex cursor-pointer items-center gap-2 rounded-lg px-3 py-1 text-[12px] transition-colors
        ${isActive ? "bg-white/6 text-white/80" : "text-white/28 hover:bg-white/4 hover:text-white/55"}`}
      onClick={() => onClick(session)}
    >
      {isPinned && <span className="flex-shrink-0 text-[11px]">📌</span>}
      <div className="flex flex-1 flex-col gap-0.5 overflow-hidden">
        <span className="truncate text-[13px]">
          {session.title ?? formatSessionDate(session.updated_at)}
        </span>
        {session.title && (
          <span className="truncate text-[11px] opacity-50">
            {formatSessionDate(session.updated_at)}
          </span>
        )}
      </div>

      <button
        type="button"
        aria-label="More options"
        className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded text-sm text-white/30 opacity-0 transition-all hover:bg-white/10 hover:text-white/70 group-hover:opacity-100"
        onClick={(e) => { e.stopPropagation(); setMenuOpen(true) }}
      >
        ···
      </button>

      {menuOpen && (
        <div
          ref={menuRef}
          className="absolute right-2 top-8 z-50 w-40 rounded-lg border border-white/10 bg-elevated py-1 shadow-xl"
          onClick={(e) => e.stopPropagation()}
        >
          {confirmDelete ? (
            <button
              type="button"
              onClick={() => {
                onDelete(session)
                setMenuOpen(false)
                setConfirmDelete(false)
              }}
              className="w-full px-3 py-1.5 text-left text-[13px] text-red-400 transition-colors hover:bg-red-400/10"
            >
              Confirm delete?
            </button>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmDelete(true)}
              className="w-full px-3 py-1.5 text-left text-[13px] text-white/50 transition-colors hover:bg-white/6"
            >
              Delete
            </button>
          )}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Add delete handler and pass it to HistoryItem in Sidebar**

In `frontend/src/app/components/sidebar/Sidebar.tsx`, add a new import at the top:

```typescript
import { chatApi } from "../../../core/api/chat"
```

Then add a `handleDeleteSession` function after `handleContinue` (around line 109):

```typescript
  async function handleDeleteSession(session: ChatSessionDto) {
    try {
      await chatApi.deleteSession(session.id)
    } catch {
      // Event-driven removal handles the UI update; error is non-critical
    }
  }
```

Then update the `HistoryItem` usage (around line 392-400) to pass `onDelete`:

```typescript
          {sessions.map((s) => (
            <HistoryItem
              key={s.id}
              session={s}
              isPinned={false}
              isActive={s.id === activeSessionId}
              onClick={handleSessionClick}
              onDelete={handleDeleteSession}
            />
          ))}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/components/sidebar/HistoryItem.tsx frontend/src/app/components/sidebar/Sidebar.tsx
git commit -m "Add hover menu with delete action to sidebar HistoryItem"
```

---

### Task 6: HistoryTab — full rework with titles, persona filter, inline rename, title generation, delete

**Files:**
- Modify: `frontend/src/app/components/user-modal/HistoryTab.tsx` — complete rewrite

- [ ] **Step 1: Rewrite HistoryTab**

Replace the entire content of `frontend/src/app/components/user-modal/HistoryTab.tsx`:

```typescript
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { chatApi, type ChatSessionDto } from '../../../core/api/chat'
import { useChatSessions } from '../../../core/hooks/useChatSessions'
import { usePersonas } from '../../../core/hooks/usePersonas'
import { useSanitisedMode } from '../../../core/store/sanitisedModeStore'

interface HistoryTabProps {
  onClose: () => void
}

function getDateGroup(isoString: string): string {
  const date = new Date(isoString)
  const now = new Date()
  const today = now.toDateString()
  const yesterday = new Date(now.getTime() - 86_400_000).toDateString()
  const weekAgo = new Date(now.getTime() - 7 * 86_400_000)
  const monthAgo = new Date(now.getTime() - 30 * 86_400_000)

  if (date.toDateString() === today) return 'Today'
  if (date.toDateString() === yesterday) return 'Yesterday'
  if (date > weekAgo) return 'This Week'
  if (date > monthAgo) return 'This Month'
  return date.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
}

function groupSessions(sessions: ChatSessionDto[]): [string, ChatSessionDto[]][] {
  const map = new Map<string, ChatSessionDto[]>()
  for (const s of sessions) {
    const group = getDateGroup(s.updated_at)
    const existing = map.get(group) ?? []
    map.set(group, [...existing, s])
  }
  return Array.from(map.entries())
}

function formatDate(isoString: string): string {
  return new Date(isoString).toLocaleDateString('de-DE', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const BTN = 'px-1.5 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider border transition-colors cursor-pointer'
const BTN_NEUTRAL = `${BTN} border-white/8 text-white/40 hover:text-white/60 hover:border-white/15`
const BTN_RED = `${BTN} border-red-400/30 text-red-400 bg-red-400/10 hover:bg-red-400/15`

export function HistoryTab({ onClose }: HistoryTabProps) {
  const { sessions, isLoading } = useChatSessions()
  const { personas } = usePersonas()
  const isSanitised = useSanitisedMode((s) => s.isSanitised)
  const [search, setSearch] = useState('')
  const [personaFilter, setPersonaFilter] = useState<string>('all')
  const navigate = useNavigate()

  // Sanitised mode: build set of NSFW persona IDs
  const nsfwPersonaIds = useMemo(
    () => new Set(personas.filter((p) => p.nsfw).map((p) => p.id)),
    [personas],
  )

  // Filter sessions by sanitised mode, persona filter, and search
  const filtered = useMemo(() => {
    let result = sessions

    // Sanitised mode
    if (isSanitised) {
      result = result.filter((s) => !nsfwPersonaIds.has(s.persona_id))
    }

    // Persona filter
    if (personaFilter !== 'all') {
      result = result.filter((s) => s.persona_id === personaFilter)
    }

    // Text search
    if (search.trim()) {
      const term = search.toLowerCase()
      result = result.filter((s) => {
        const name = personas.find((p) => p.id === s.persona_id)?.name ?? s.persona_id
        const title = s.title ?? ''
        return (
          name.toLowerCase().includes(term) ||
          title.toLowerCase().includes(term) ||
          s.id.toLowerCase().includes(term)
        )
      })
    }

    return result
  }, [sessions, search, personas, personaFilter, isSanitised, nsfwPersonaIds])

  // Personas available for the filter dropdown (only those with sessions, respecting sanitised mode)
  const filterPersonas = useMemo(() => {
    const personaIdsWithSessions = new Set(sessions.map((s) => s.persona_id))
    return personas
      .filter((p) => personaIdsWithSessions.has(p.id))
      .filter((p) => !isSanitised || !p.nsfw)
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [personas, sessions, isSanitised])

  const grouped = useMemo(() => groupSessions(filtered), [filtered])

  function handleOpen(session: ChatSessionDto) {
    navigate(`/chat/${session.persona_id}/${session.id}`)
    onClose()
  }

  return (
    <div className="flex flex-col h-full">
      {/* Filters */}
      <div className="px-4 pt-4 pb-2 flex-shrink-0 flex gap-2">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search history..."
          aria-label="Search session history"
          className="flex-1 bg-white/[0.04] border border-white/8 rounded-lg px-3 py-2 text-[13px] text-white/75 placeholder:text-white/30 outline-none focus:border-gold/30 transition-colors font-mono"
        />
        <select
          value={personaFilter}
          onChange={(e) => setPersonaFilter(e.target.value)}
          aria-label="Filter by persona"
          className="bg-white/[0.04] border border-white/8 rounded-lg px-3 py-2 text-[13px] text-white/75 outline-none focus:border-gold/30 transition-colors font-mono cursor-pointer appearance-none min-w-[140px]"
        >
          <option value="all">All Personas</option>
          {filterPersonas.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto px-2 pb-4 [&::-webkit-scrollbar]:w-[3px] [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10">
        {isLoading && (
          <p className="px-4 py-3 text-[12px] text-white/30 font-mono">Loading...</p>
        )}
        {!isLoading && filtered.length === 0 && (
          <p className="px-4 py-3 text-[12px] text-white/30 font-mono">No sessions found.</p>
        )}
        {grouped.map(([group, groupSessions]) => (
          <div key={group}>
            <div className="px-3 pt-4 pb-1 text-[10px] uppercase tracking-widest text-white/30 font-mono">
              {group}
            </div>
            {groupSessions.map((s) => (
              <SessionRow
                key={s.id}
                session={s}
                personaName={personas.find((p) => p.id === s.persona_id)?.name ?? s.persona_id}
                onOpen={() => handleOpen(s)}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}


interface SessionRowProps {
  session: ChatSessionDto
  personaName: string
  onOpen: () => void
}

function SessionRow({ session, personaName, onOpen }: SessionRowProps) {
  const [editing, setEditing] = useState(false)
  const [editValue, setEditValue] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [generating, setGenerating] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const deleteTimer = useRef<ReturnType<typeof setTimeout>>()

  useEffect(() => {
    if (editing) inputRef.current?.focus()
  }, [editing])

  // Auto-dismiss delete confirmation
  useEffect(() => {
    return () => {
      if (deleteTimer.current) clearTimeout(deleteTimer.current)
    }
  }, [])

  const startEdit = useCallback(() => {
    setEditValue(session.title ?? '')
    setEditing(true)
  }, [session.title])

  const cancelEdit = useCallback(() => {
    setEditing(false)
    setEditValue('')
  }, [])

  const saveEdit = useCallback(async () => {
    const trimmed = editValue.trim()
    if (!trimmed || trimmed === session.title) {
      cancelEdit()
      return
    }
    try {
      await chatApi.updateSession(session.id, { title: trimmed })
    } catch {
      // Title update arrives via event; error is non-critical
    }
    setEditing(false)
  }, [editValue, session.id, session.title, cancelEdit])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') saveEdit()
    if (e.key === 'Escape') cancelEdit()
  }, [saveEdit, cancelEdit])

  const handleGenerateTitle = useCallback(async () => {
    setGenerating(true)
    try {
      await chatApi.generateTitle(session.id)
    } catch {
      // Title arrives via event
    } finally {
      // Keep generating state for a short time to show feedback
      setTimeout(() => setGenerating(false), 2000)
    }
  }, [session.id])

  const handleDelete = useCallback(async () => {
    try {
      await chatApi.deleteSession(session.id)
    } catch {
      // Removal via event
    }
    setConfirmDelete(false)
  }, [session.id])

  const startDeleteConfirm = useCallback(() => {
    if (deleteTimer.current) clearTimeout(deleteTimer.current)
    setConfirmDelete(true)
    deleteTimer.current = setTimeout(() => setConfirmDelete(false), 3000)
  }, [])

  return (
    <div className="group rounded-lg transition-colors hover:bg-white/4">
      <div className="flex items-center gap-3 px-3 py-2.5">
        {/* Main content — clickable to open chat */}
        <button
          type="button"
          onClick={onOpen}
          className="flex-1 min-w-0 text-left"
        >
          <div className="flex items-center gap-2">
            {editing ? (
              <input
                ref={inputRef}
                type="text"
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                onKeyDown={handleKeyDown}
                onBlur={saveEdit}
                onClick={(e) => e.stopPropagation()}
                className="flex-1 bg-white/[0.04] border border-gold/30 rounded px-2 py-0.5 text-[13px] text-white/80 outline-none font-mono"
              />
            ) : (
              <p className="text-[13px] text-white/65 group-hover:text-white/80 truncate transition-colors">
                {session.title ?? formatDate(session.updated_at)}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <p className="text-[10px] text-white/40 font-mono truncate">
              {personaName}
            </p>
            <span className="text-[10px] text-white/20">·</span>
            <p className="text-[10px] text-white/30 font-mono">
              {formatDate(session.updated_at)}
            </p>
          </div>
        </button>

        {/* Actions — visible on hover */}
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
          <button
            type="button"
            onClick={startEdit}
            title="Rename"
            className={BTN_NEUTRAL}
          >
            REN
          </button>
          <button
            type="button"
            onClick={handleGenerateTitle}
            disabled={generating}
            title="Generate title"
            className={`${BTN_NEUTRAL} ${generating ? 'opacity-30 cursor-not-allowed' : ''}`}
          >
            {generating ? '...' : 'GEN'}
          </button>
          {confirmDelete ? (
            <button type="button" onClick={handleDelete} className={BTN_RED}>
              SURE?
            </button>
          ) : (
            <button type="button" onClick={startDeleteConfirm} className={BTN_NEUTRAL}>
              DEL
            </button>
          )}
        </div>

        {/* Open arrow */}
        <span
          className="text-[11px] text-white/20 group-hover:text-gold/50 transition-colors flex-shrink-0 cursor-pointer"
          onClick={onOpen}
        >
          ›
        </span>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/components/user-modal/HistoryTab.tsx
git commit -m "Rework HistoryTab with titles, persona filter, inline rename, title generation, delete"
```

---

### Task 7: Verify and fix — end-to-end smoke test

**Files:**
- No new files — verification only

- [ ] **Step 1: Verify backend starts**

Run: `cd /home/chris/workspace/chatsune && uv run python -c "from backend.modules.chat._handlers import router; print('OK')"`

Expected: `OK`

- [ ] **Step 2: Verify frontend compiles**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`

Expected: No errors

- [ ] **Step 3: Verify frontend dev server starts**

Run: `cd /home/chris/workspace/chatsune/frontend && timeout 15 pnpm dev 2>&1 | head -20`

Expected: Vite dev server starts without errors

- [ ] **Step 4: Commit final fixes if needed**

Only if steps 1-3 revealed issues. Fix and commit with descriptive message.

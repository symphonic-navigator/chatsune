# Artefacts Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the placeholder Artefacts tab in the user modal with a working global artefacts browser (filter by persona/type, AND-token search, inline rename, delete, jump-to-chat with auto-open), respecting global sanitised mode.

**Architecture:** New read-only backend endpoint `GET /api/artefacts/` enriches artefact rows with `session_title`, `persona_id`, `persona_name`, `persona_accent` via the chat and persona module public APIs (no cross-module DB access). Frontend tab mirrors `HistoryTab` patterns and reuses existing `PATCH`/`DELETE` artefact endpoints (which already publish `ARTEFACT_UPDATED` and `ARTEFACT_DELETED` events). Jump-to-chat passes `pendingArtefactId` via `react-router` location state; `ChatView` consumes it after artefact load and opens the existing overlay.

**Tech Stack:** FastAPI · Pydantic v2 · MongoDB · React + TSX · Tailwind · Zustand · pytest · Vitest

---

## File Map

**Backend — create:**
- (none)

**Backend — modify:**
- `shared/dtos/artefact.py` — add `ArtefactListItemDto`
- `backend/modules/chat/__init__.py` — add public helper `get_session_summaries(session_ids, user_id)`
- `backend/modules/chat/_repository.py` — add `find_sessions_by_ids(session_ids, user_id)`
- `backend/modules/artefact/_repository.py` — add `list_by_user(user_id)`
- `backend/modules/artefact/_handlers.py` — add `GET /api/artefacts/` mounted on a new router
- `backend/modules/artefact/__init__.py` — export the new router (or add a second router)
- `backend/main.py` — include the new router

**Backend — test:**
- `backend/tests/modules/artefact/test_list_user_artefacts.py`

**Frontend — modify:**
- `frontend/src/core/types/artefact.ts` — add `ArtefactListItem`
- `frontend/src/core/api/artefact.ts` — add `listAll()`
- `frontend/src/app/components/user-modal/ArtefactsTab.tsx` — replace placeholder with full implementation
- `frontend/src/features/chat/ChatView.tsx` — consume `location.state.pendingArtefactId` after artefact load and open overlay

**Frontend — test:**
- `frontend/src/app/components/user-modal/__tests__/ArtefactsTab.filter.test.ts` — pure-function tests for the filter/search reducer

---

## Pre-flight: Event Audit

- [ ] **Step 1: Read `shared/events/artefact.py` end-to-end and `shared/topics.py` for `ARTEFACT_*` constants**

Verify these events exist and contain at minimum the fields the tab needs:

| Event | Required fields |
|-------|-----------------|
| `ARTEFACT_CREATED` | `session_id`, `artefact_id`/`handle`, `title`, `artefact_type` |
| `ARTEFACT_UPDATED` | `session_id`, `handle`, `title`, `artefact_type`, `size_bytes`, `version` |
| `ARTEFACT_DELETED` | `session_id`, `handle` |

If any field is missing, **stop and add it to the existing event DTO** before continuing — do not invent new events.

- [ ] **Step 2: Confirm the tab can locate an artefact row from `(session_id, handle)`**

The `ARTEFACT_UPDATED` and `ARTEFACT_DELETED` events carry `(session_id, handle)`, not the artefact `_id`. The tab’s row state must therefore include both so events can match. Note this — Task 5 will use it.

- [ ] **Step 3: Commit any event-DTO additions (if needed)**

```bash
git add shared/events/artefact.py
git commit -m "Extend artefact events with fields needed by global list view"
```

If no changes were needed, skip the commit.

---

## Task 1 — Backend DTO

**Files:**
- Modify: `shared/dtos/artefact.py`

- [ ] **Step 1: Add `ArtefactListItemDto`**

Append to `shared/dtos/artefact.py`:

```python
class ArtefactListItemDto(BaseModel):
    """Row in the global artefacts list — enriched with session and persona context."""
    id: str
    handle: str
    title: str
    type: ArtefactType
    language: str | None = None
    size_bytes: int
    version: int
    created_at: datetime
    updated_at: datetime
    session_id: str
    session_title: str | None
    persona_id: str
    persona_name: str
    persona_monogram: str
    persona_colour_scheme: str  # chakra colour key, e.g. "throat"
```

- [ ] **Step 2: Syntax check**

Run: `uv run python -m py_compile shared/dtos/artefact.py`
Expected: no output, exit 0.

- [ ] **Step 3: Commit**

```bash
git add shared/dtos/artefact.py
git commit -m "Add ArtefactListItemDto for global artefacts list"
```

---

## Task 2 — Chat module: session summaries by ids

**Files:**
- Modify: `backend/modules/chat/_repository.py`
- Modify: `backend/modules/chat/__init__.py`

Goal: expose a public way for the artefact module to obtain `{session_id: {title, persona_id}}` for a set of session ids belonging to one user, without leaking the chat collection.

- [ ] **Step 1: Add repository method**

In `backend/modules/chat/_repository.py`, add (after `list_sessions`):

```python
async def find_sessions_by_ids(self, session_ids: list[str], user_id: str) -> list[dict]:
    """Return raw session docs for the given ids that belong to the user. Soft-deleted included."""
    if not session_ids:
        return []
    cursor = self._sessions.find({
        "_id": {"$in": session_ids},
        "user_id": user_id,
    })
    return await cursor.to_list(length=len(session_ids))
```

(If sessions use a different `_id` type — verify by reading the existing `get_session` method and matching it. If `_id` is an `ObjectId`, convert with `ObjectId(sid)` for each id; if it’s a string uuid, leave as-is. Match the existing pattern in the file.)

- [ ] **Step 2: Add public API helper**

In `backend/modules/chat/__init__.py`, add before `__all__`:

```python
async def get_session_summaries(session_ids: list[str], user_id: str) -> dict[str, dict]:
    """Return ``{session_id: {"title": str | None, "persona_id": str}}`` for the given ids.

    Public-API helper so other modules (artefact list view) can enrich rows with
    session context without reaching into the chat repository directly.
    """
    repo = ChatRepository(get_db())
    docs = await repo.find_sessions_by_ids(session_ids, user_id)
    return {
        str(d["_id"]): {"title": d.get("title"), "persona_id": d.get("persona_id")}
        for d in docs
    }
```

Add `"get_session_summaries"` to `__all__`.

- [ ] **Step 3: Syntax check**

Run: `uv run python -m py_compile backend/modules/chat/_repository.py backend/modules/chat/__init__.py`
Expected: no output, exit 0.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/chat/_repository.py backend/modules/chat/__init__.py
git commit -m "Expose chat.get_session_summaries for cross-module enrichment"
```

---

## Task 3 — Artefact repo: list by user

**Files:**
- Modify: `backend/modules/artefact/_repository.py`

- [ ] **Step 1: Add method**

In `backend/modules/artefact/_repository.py`, add after `list_by_session`:

```python
async def list_by_user(self, user_id: str) -> list[dict]:
    """List all artefacts owned by ``user_id`` across all sessions, newest first."""
    cursor = self._artefacts.find(
        {"user_id": user_id},
    ).sort("updated_at", -1)
    return await cursor.to_list(length=2000)
```

- [ ] **Step 2: Syntax check**

Run: `uv run python -m py_compile backend/modules/artefact/_repository.py`
Expected: no output, exit 0.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/artefact/_repository.py
git commit -m "Add ArtefactRepository.list_by_user"
```

---

## Task 4 — Backend endpoint and test

**Files:**
- Modify: `backend/modules/artefact/_handlers.py`
- Modify: `backend/modules/artefact/__init__.py`
- Modify: `backend/main.py`
- Create: `backend/tests/modules/artefact/test_list_user_artefacts.py`

- [ ] **Step 1: Write the failing test first**

Create `backend/tests/modules/artefact/test_list_user_artefacts.py`. Match the style of other tests under `backend/tests/modules/` — find a sibling test for an existing artefact endpoint (e.g. `grep -rln "ArtefactRepository\|/api/chat/sessions.*artefacts" backend/tests/`) and copy its fixtures (in-memory mongo or test client). The test must:

1. Seed two users (`alice`, `bob`).
2. For `alice`, seed two personas with different `colour_scheme` and `monogram`.
3. For `alice`, seed two sessions (one per persona) with titles.
4. For `alice`, seed three artefacts across the two sessions with different types and timestamps.
5. For `bob`, seed one persona, one session, one artefact (must NOT appear in alice’s list).
6. Authenticate as `alice` and `GET /api/artefacts/`.
7. Assert exactly three rows are returned, sorted by `updated_at desc`.
8. For each row assert: `id`, `handle`, `title`, `type`, `session_id`, `session_title`, `persona_id`, `persona_name`, `persona_monogram`, `persona_colour_scheme` are populated and correct.
9. Assert `bob`’s artefact is absent.

If the existing test infra uses fakes for `PersonaService.get_persona`, follow the same pattern. If it uses a real test database, seed the personas collection through the persona module’s public API.

- [ ] **Step 2: Run the test, expect failure**

Run: `uv run pytest backend/tests/modules/artefact/test_list_user_artefacts.py -v`
Expected: FAIL with 404 (route not registered) or ImportError.

- [ ] **Step 3: Add a second router for the global endpoint**

In `backend/modules/artefact/_handlers.py`, at the bottom of the file (after the existing session-scoped router and handlers), add:

```python
from backend.modules.chat import get_session_summaries
from backend.modules.persona import get_persona
from shared.dtos.artefact import ArtefactListItemDto

global_router = APIRouter(prefix="/api/artefacts", tags=["artefacts"])


@global_router.get("/")
async def list_user_artefacts(
    user: dict = Depends(require_active_session),
) -> list[ArtefactListItemDto]:
    """Return every artefact owned by the authenticated user across all sessions."""
    repo = _repo()
    artefacts = await repo.list_by_user(user["sub"])
    if not artefacts:
        return []

    session_ids = list({a["session_id"] for a in artefacts})
    sessions = await get_session_summaries(session_ids, user["sub"])

    persona_ids = {info["persona_id"] for info in sessions.values() if info.get("persona_id")}
    personas: dict[str, dict] = {}
    for pid in persona_ids:
        p = await get_persona(pid, user["sub"])
        if p:
            personas[pid] = p

    rows: list[ArtefactListItemDto] = []
    for a in artefacts:
        sid = a["session_id"]
        sess = sessions.get(sid)
        if not sess:
            # Session was hard-deleted; skip orphans rather than crash.
            continue
        persona_id = sess.get("persona_id") or ""
        persona = personas.get(persona_id)
        if not persona:
            continue
        rows.append(ArtefactListItemDto(
            id=str(a["_id"]),
            handle=a["handle"],
            title=a["title"],
            type=a["type"],
            language=a.get("language"),
            size_bytes=a["size_bytes"],
            version=a["version"],
            created_at=a["created_at"],
            updated_at=a["updated_at"],
            session_id=sid,
            session_title=sess.get("title"),
            persona_id=persona_id,
            persona_name=persona.get("name", ""),
            persona_monogram=persona.get("monogram") or (persona.get("name", "?")[:1].upper()),
            persona_colour_scheme=persona.get("colour_scheme") or "throat",
        ))
    return rows
```

If `get_persona` returns a Pydantic model rather than a dict in this codebase, switch the field accesses (`p.name`, `p.monogram`, `p.colour_scheme`) accordingly. Verify by reading `backend/modules/persona/__init__.py:get_persona`.

- [ ] **Step 4: Export the new router**

In `backend/modules/artefact/__init__.py`, change the import and `__all__`:

```python
from backend.modules.artefact._handlers import router, global_router
...
__all__ = [
    "router",
    "global_router",
    "init_indexes",
    "create_artefact",
    "update_artefact",
    "read_artefact",
    "list_artefacts",
]
```

- [ ] **Step 5: Mount the router in `backend/main.py`**

Find the existing `app.include_router(artefact_router)` line. Add directly below:

```python
from backend.modules.artefact import global_router as artefact_global_router
app.include_router(artefact_global_router)
```

(Move the import to the top of the file with the other artefact import if the existing convention prefers that. Read `main.py` first to match style.)

- [ ] **Step 6: Run the test, expect pass**

Run: `uv run pytest backend/tests/modules/artefact/test_list_user_artefacts.py -v`
Expected: PASS.

If it fails because of the persona model shape, adjust the field accesses in Step 3 and re-run. Do not change the test to match wrong production behaviour.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/artefact/_handlers.py backend/modules/artefact/__init__.py backend/main.py backend/tests/modules/artefact/test_list_user_artefacts.py
git commit -m "Add GET /api/artefacts/ for global artefact list"
```

---

## Task 5 — Frontend types and API

**Files:**
- Modify: `frontend/src/core/types/artefact.ts`
- Modify: `frontend/src/core/api/artefact.ts`

- [ ] **Step 1: Add the type**

Append to `frontend/src/core/types/artefact.ts`:

```ts
export interface ArtefactListItem {
  id: string
  handle: string
  title: string
  type: ArtefactType
  language: string | null
  size_bytes: number
  version: number
  created_at: string
  updated_at: string
  session_id: string
  session_title: string | null
  persona_id: string
  persona_name: string
  persona_monogram: string
  persona_colour_scheme: string
}
```

- [ ] **Step 2: Add the API method**

In `frontend/src/core/api/artefact.ts`, change the import and add the method:

```ts
import { api } from './client'
import type { ArtefactDetail, ArtefactListItem, ArtefactSummary } from '../types/artefact'

const BASE = '/api/chat/sessions'

export const artefactApi = {
  list: (sessionId: string) =>
    api.get<ArtefactSummary[]>(`${BASE}/${sessionId}/artefacts/`),

  listAll: () =>
    api.get<ArtefactListItem[]>(`/api/artefacts/`),

  get: (sessionId: string, artefactId: string) =>
    api.get<ArtefactDetail>(`${BASE}/${sessionId}/artefacts/${artefactId}`),

  patch: (sessionId: string, artefactId: string, body: { title?: string; content?: string }) =>
    api.patch<ArtefactDetail>(`${BASE}/${sessionId}/artefacts/${artefactId}`, body),

  delete: (sessionId: string, artefactId: string) =>
    api.delete<{ status: string }>(`${BASE}/${sessionId}/artefacts/${artefactId}`),

  undo: (sessionId: string, artefactId: string) =>
    api.post<ArtefactDetail>(`${BASE}/${sessionId}/artefacts/${artefactId}/undo`),

  redo: (sessionId: string, artefactId: string) =>
    api.post<ArtefactDetail>(`${BASE}/${sessionId}/artefacts/${artefactId}/redo`),
}
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/core/types/artefact.ts frontend/src/core/api/artefact.ts
git commit -m "Add ArtefactListItem type and listAll() API"
```

---

## Task 6 — Filter/search reducer (pure function + tests)

**Files:**
- Create: `frontend/src/app/components/user-modal/artefactsFilter.ts`
- Create: `frontend/src/app/components/user-modal/__tests__/artefactsFilter.test.ts`

Extracting the reducer keeps the component lean and lets us test it without rendering React.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/app/components/user-modal/__tests__/artefactsFilter.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { applyArtefactFilters } from '../artefactsFilter'
import type { ArtefactListItem } from '../../../../core/types/artefact'

const make = (over: Partial<ArtefactListItem>): ArtefactListItem => ({
  id: 'id', handle: 'h', title: 't', type: 'code', language: null,
  size_bytes: 0, version: 1, created_at: '', updated_at: '',
  session_id: 's', session_title: 'sess', persona_id: 'p1',
  persona_name: 'P1', persona_monogram: 'P', persona_colour_scheme: 'throat',
  ...over,
})

describe('applyArtefactFilters', () => {
  it('hides nsfw persona artefacts when sanitised', () => {
    const items = [make({ id: 'a', persona_id: 'p1' }), make({ id: 'b', persona_id: 'nsfw' })]
    const out = applyArtefactFilters(items, {
      isSanitised: true, nsfwPersonaIds: new Set(['nsfw']),
      personaFilter: 'all', typeFilter: 'all', search: '',
    })
    expect(out.map((x) => x.id)).toEqual(['a'])
  })

  it('AND-combines whitespace tokens, case insensitive', () => {
    const items = [
      make({ id: 'a', title: 'Snake Game Prototype' }),
      make({ id: 'b', title: 'Snake recipe' }),
      make({ id: 'c', title: 'Game design notes' }),
    ]
    const out = applyArtefactFilters(items, {
      isSanitised: false, nsfwPersonaIds: new Set(),
      personaFilter: 'all', typeFilter: 'all', search: 'snake game',
    })
    expect(out.map((x) => x.id)).toEqual(['a'])
  })

  it('persona and type filters compose with search', () => {
    const items = [
      make({ id: 'a', title: 'foo', persona_id: 'p1', type: 'code' }),
      make({ id: 'b', title: 'foo', persona_id: 'p2', type: 'code' }),
      make({ id: 'c', title: 'foo', persona_id: 'p1', type: 'markdown' }),
    ]
    const out = applyArtefactFilters(items, {
      isSanitised: false, nsfwPersonaIds: new Set(),
      personaFilter: 'p1', typeFilter: 'code', search: 'foo',
    })
    expect(out.map((x) => x.id)).toEqual(['a'])
  })

  it('blank search keeps all', () => {
    const items = [make({ id: 'a' }), make({ id: 'b' })]
    const out = applyArtefactFilters(items, {
      isSanitised: false, nsfwPersonaIds: new Set(),
      personaFilter: 'all', typeFilter: 'all', search: '   ',
    })
    expect(out).toHaveLength(2)
  })
})
```

- [ ] **Step 2: Run, expect failure**

Run: `cd frontend && pnpm vitest run src/app/components/user-modal/__tests__/artefactsFilter.test.ts`
Expected: FAIL with module-not-found.

- [ ] **Step 3: Implement the reducer**

Create `frontend/src/app/components/user-modal/artefactsFilter.ts`:

```ts
import type { ArtefactListItem, ArtefactType } from '../../../core/types/artefact'

export interface ArtefactFilterState {
  isSanitised: boolean
  nsfwPersonaIds: Set<string>
  personaFilter: string  // persona id or 'all'
  typeFilter: ArtefactType | 'all'
  search: string
}

export function applyArtefactFilters(
  items: ArtefactListItem[],
  state: ArtefactFilterState,
): ArtefactListItem[] {
  let result = items

  if (state.isSanitised) {
    result = result.filter((a) => !state.nsfwPersonaIds.has(a.persona_id))
  }

  if (state.personaFilter !== 'all') {
    result = result.filter((a) => a.persona_id === state.personaFilter)
  }

  if (state.typeFilter !== 'all') {
    result = result.filter((a) => a.type === state.typeFilter)
  }

  const tokens = state.search.toLowerCase().split(/\s+/).filter(Boolean)
  if (tokens.length > 0) {
    result = result.filter((a) => {
      const title = a.title.toLowerCase()
      return tokens.every((t) => title.includes(t))
    })
  }

  return result
}
```

- [ ] **Step 4: Run, expect pass**

Run: `cd frontend && pnpm vitest run src/app/components/user-modal/__tests__/artefactsFilter.test.ts`
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/user-modal/artefactsFilter.ts frontend/src/app/components/user-modal/__tests__/artefactsFilter.test.ts
git commit -m "Add pure filter/search reducer for artefacts tab"
```

---

## Task 7 — Implement ArtefactsTab

**Files:**
- Modify: `frontend/src/app/components/user-modal/ArtefactsTab.tsx`

Read `HistoryTab.tsx`, `BookmarksTab.tsx`, and `UploadsTab.tsx` once before writing this. Match their visual style, button classes, dropdown styling, and row layout exactly. The only structural difference is row content (artefact title + type badge + session title) and the available actions (REN, DEL, OPEN).

- [ ] **Step 1: Replace the file with the full implementation**

Overwrite `frontend/src/app/components/user-modal/ArtefactsTab.tsx`:

```tsx
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { artefactApi } from '../../../core/api/artefact'
import { useEventBus } from '../../../core/hooks/useEventBus'  // adjust if the project uses a different event hook
import { usePersonas } from '../../../core/hooks/usePersonas'
import { useSanitisedMode } from '../../../core/store/sanitisedModeStore'
import type { ArtefactListItem, ArtefactType } from '../../../core/types/artefact'
import { CHAKRA_PALETTE, type ChakraColour } from '../../../core/types/chakra'
import { applyArtefactFilters } from './artefactsFilter'

const ARTEFACT_TYPES: ArtefactType[] = ['markdown', 'code', 'html', 'svg', 'jsx', 'mermaid']

const BTN = 'px-1.5 py-0.5 rounded text-[10px] font-mono uppercase tracking-wider border transition-colors cursor-pointer'
const BTN_NEUTRAL = `${BTN} border-white/8 text-white/40 hover:text-white/60 hover:border-white/15`
const BTN_RED = `${BTN} border-red-400/30 text-red-400 bg-red-400/10 hover:bg-red-400/15`

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  })
}

interface ArtefactsTabProps {
  onClose: () => void
}

export function ArtefactsTab({ onClose }: ArtefactsTabProps) {
  const [items, setItems] = useState<ArtefactListItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [personaFilter, setPersonaFilter] = useState<string>('all')
  const [typeFilter, setTypeFilter] = useState<ArtefactType | 'all'>('all')
  const { personas } = usePersonas()
  const isSanitised = useSanitisedMode((s) => s.isSanitised)
  const navigate = useNavigate()

  const nsfwPersonaIds = useMemo(
    () => new Set(personas.filter((p) => p.nsfw).map((p) => p.id)),
    [personas],
  )

  // Initial load
  useEffect(() => {
    let cancelled = false
    setIsLoading(true)
    artefactApi.listAll()
      .then((rows) => { if (!cancelled) setItems(rows) })
      .catch(() => { if (!cancelled) setError('Could not load artefacts.') })
      .finally(() => { if (!cancelled) setIsLoading(false) })
    return () => { cancelled = true }
  }, [])

  // Subscribe to artefact lifecycle events so the list stays in sync.
  // Use whichever event-subscription primitive the project uses — verify by reading
  // useArtefactEvents.ts or another consumer such as ArtefactSidebar.
  useEventBus((event) => {
    if (event.type === 'artefact.deleted') {
      setItems((prev) => prev.filter(
        (a) => !(a.session_id === event.payload.session_id && a.handle === event.payload.handle),
      ))
    } else if (event.type === 'artefact.updated') {
      setItems((prev) => prev.map((a) =>
        a.session_id === event.payload.session_id && a.handle === event.payload.handle
          ? { ...a, title: event.payload.title, size_bytes: event.payload.size_bytes, version: event.payload.version, updated_at: new Date().toISOString() }
          : a,
      ))
    }
    // artefact.created arrives without session_title/persona enrichment, so we
    // do a one-shot refetch to keep the row complete.
    else if (event.type === 'artefact.created') {
      artefactApi.listAll().then(setItems).catch(() => {})
    }
  })

  const filtered = useMemo(
    () => applyArtefactFilters(items, {
      isSanitised, nsfwPersonaIds, personaFilter, typeFilter, search,
    }),
    [items, isSanitised, nsfwPersonaIds, personaFilter, typeFilter, search],
  )

  // Personas with at least one *visible* artefact
  const filterPersonas = useMemo(() => {
    const visible = isSanitised ? items.filter((a) => !nsfwPersonaIds.has(a.persona_id)) : items
    const personaIds = new Set(visible.map((a) => a.persona_id))
    return personas
      .filter((p) => personaIds.has(p.id))
      .filter((p) => !isSanitised || !p.nsfw)
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [personas, items, isSanitised, nsfwPersonaIds])

  const handleRename = useCallback(async (row: ArtefactListItem, newTitle: string) => {
    const trimmed = newTitle.trim()
    if (!trimmed || trimmed === row.title) return
    // Optimistic update
    setItems((prev) => prev.map((a) => (a.id === row.id ? { ...a, title: trimmed } : a)))
    try {
      await artefactApi.patch(row.session_id, row.id, { title: trimmed })
    } catch {
      // revert
      setItems((prev) => prev.map((a) => (a.id === row.id ? { ...a, title: row.title } : a)))
    }
  }, [])

  const handleDelete = useCallback(async (row: ArtefactListItem) => {
    setItems((prev) => prev.filter((a) => a.id !== row.id))
    try {
      await artefactApi.delete(row.session_id, row.id)
    } catch {
      // refetch on failure
      artefactApi.listAll().then(setItems).catch(() => {})
    }
  }, [])

  const handleOpen = useCallback((row: ArtefactListItem) => {
    navigate(`/chat/${row.persona_id}/${row.session_id}`, {
      state: { pendingArtefactId: row.id },
    })
    onClose()
  }, [navigate, onClose])

  return (
    <div className="flex flex-col h-full">
      {/* Filters */}
      <div className="px-4 pt-4 pb-2 flex-shrink-0 flex gap-2">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search artefacts..."
          aria-label="Search artefacts"
          className="flex-1 bg-white/[0.04] border border-white/8 rounded-lg px-3 py-2 text-[13px] text-white/75 placeholder:text-white/30 outline-none focus:border-gold/30 transition-colors font-mono"
        />
        <select
          value={personaFilter}
          onChange={(e) => setPersonaFilter(e.target.value)}
          aria-label="Filter by persona"
          className="bg-surface border border-white/8 rounded-lg px-2 py-1 text-[11px] font-mono text-white/60 outline-none focus:border-gold/40 cursor-pointer"
        >
          <option value="all">All Personas</option>
          {filterPersonas.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value as ArtefactType | 'all')}
          aria-label="Filter by type"
          className="bg-surface border border-white/8 rounded-lg px-2 py-1 text-[11px] font-mono text-white/60 outline-none focus:border-gold/40 cursor-pointer"
        >
          <option value="all">All Types</option>
          {ARTEFACT_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto px-2 pb-4 [&::-webkit-scrollbar]:w-[3px] [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10">
        {isLoading && (
          <p className="px-4 py-3 text-[12px] text-white/60 font-mono">Loading...</p>
        )}
        {error && !isLoading && (
          <p className="px-4 py-3 text-[12px] text-red-400 font-mono">{error}</p>
        )}
        {!isLoading && !error && filtered.length === 0 && (
          <p className="px-4 py-3 text-[12px] text-white/60 font-mono">No artefacts found.</p>
        )}
        {filtered.map((row) => (
          <ArtefactRow
            key={row.id}
            row={row}
            onOpen={() => handleOpen(row)}
            onRename={(title) => handleRename(row, title)}
            onDelete={() => handleDelete(row)}
          />
        ))}
      </div>
    </div>
  )
}

interface RowProps {
  row: ArtefactListItem
  onOpen: () => void
  onRename: (newTitle: string) => void
  onDelete: () => void
}

function ArtefactRow({ row, onOpen, onRename, onDelete }: RowProps) {
  const chakra = CHAKRA_PALETTE[row.persona_colour_scheme as ChakraColour] ?? null
  const [editing, setEditing] = useState(false)
  const [editValue, setEditValue] = useState(row.title)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const startEdit = useCallback(() => {
    setEditValue(row.title)
    setEditing(true)
  }, [row.title])

  const commit = useCallback(() => {
    setEditing(false)
    onRename(editValue)
  }, [editValue, onRename])

  const cancel = useCallback(() => {
    setEditing(false)
    setEditValue(row.title)
  }, [row.title])

  return (
    <div className="group rounded-lg transition-colors hover:bg-white/4">
      <div className="flex items-center gap-3 px-3 py-2.5">
        {chakra && (
          <div
            className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full text-[8px] font-serif"
            style={{
              background: `radial-gradient(circle, ${chakra.hex}40 0%, ${chakra.hex}10 80%)`,
              color: `${chakra.hex}CC`,
            }}
          >
            {row.persona_monogram}
          </div>
        )}

        <button type="button" onClick={onOpen} className="flex-1 min-w-0 text-left">
          <div className="flex items-center gap-2">
            {editing ? (
              <input
                autoFocus
                type="text"
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                onClick={(e) => e.stopPropagation()}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commit()
                  if (e.key === 'Escape') cancel()
                }}
                onBlur={commit}
                className="flex-1 bg-white/[0.04] border border-gold/30 rounded px-2 py-0.5 text-[13px] text-white/80 outline-none font-mono"
              />
            ) : (
              <p
                className="text-[13px] text-white/65 group-hover:text-white/80 truncate transition-colors"
                onDoubleClick={(e) => { e.stopPropagation(); startEdit() }}
              >
                {row.title}
              </p>
            )}
            <span className="text-[9px] uppercase tracking-wider text-white/30 font-mono border border-white/10 rounded px-1">
              {row.type}
            </span>
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <p className="text-[10px] text-white/40 font-mono truncate">{row.persona_name}</p>
            <span className="text-[10px] text-white/20">·</span>
            <p className="text-[10px] text-white/30 font-mono truncate">
              {row.session_title ?? 'untitled chat'}
            </p>
            <span className="text-[10px] text-white/20">·</span>
            <p className="text-[10px] text-white/30 font-mono">{formatDate(row.updated_at)}</p>
          </div>
        </button>

        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
          <button type="button" onClick={startEdit} className={BTN_NEUTRAL} title="Rename">REN</button>
          {confirmDelete ? (
            <button type="button" onClick={onDelete} className={BTN_RED} title="Confirm delete">SURE?</button>
          ) : (
            <button type="button" onClick={() => setConfirmDelete(true)} className={BTN_NEUTRAL} title="Delete">DEL</button>
          )}
          <button type="button" onClick={onOpen} className={BTN_NEUTRAL} title="Open in chat">OPEN</button>
        </div>
      </div>
    </div>
  )
}
```

**Two integration points to verify** before assuming the file compiles:

1. The event-bus subscription primitive — `useEventBus` is a guess. Open `frontend/src/features/artefact/useArtefactEvents.ts` and copy whichever pattern it uses (e.g. `useEventBus(Topics.ARTEFACT_DELETED, ...)` or a Topics-keyed subscription, or a `useEffect` + `eventBus.on(...)`). Replace the placeholder block in the new file with the matching pattern. The behaviour stays the same.
2. The user-modal sets `onClose` on its tabs — verify by reading the parent (`UserModal.tsx` or similar) to confirm the prop name and signature, and update the `ArtefactsTab` props if needed. The current `ArtefactsTab` placeholder takes no props, so the parent likely needs a small update (one line) to pass `onClose` — match how `HistoryTab` is wired in.

- [ ] **Step 2: Type-check and build**

Run: `cd frontend && pnpm tsc --noEmit && pnpm run build`
Expected: clean.

Fix any errors reported here — most likely around the two integration points above.

- [ ] **Step 3: Run filter tests again to make sure nothing regressed**

Run: `cd frontend && pnpm vitest run src/app/components/user-modal/__tests__/artefactsFilter.test.ts`
Expected: 4 PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/user-modal/ArtefactsTab.tsx frontend/src/app/components/user-modal/UserModal.tsx
git commit -m "Implement Artefacts tab with filter, search, rename, delete, open-in-chat"
```

(Adjust the second path if the parent file is named differently.)

---

## Task 8 — ChatView consumes pendingArtefactId

**Files:**
- Modify: `frontend/src/features/chat/ChatView.tsx`

Goal: when navigation arrives with `location.state.pendingArtefactId`, fetch the artefact detail after the session’s artefacts have loaded and open the existing overlay. Then clear the state so a reload does not re-open it.

- [ ] **Step 1: Add the effect**

In `frontend/src/features/chat/ChatView.tsx`, near the existing `react-router` imports, ensure `useLocation` is imported:

```ts
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
```

Inside the component, add:

```ts
const location = useLocation() as { state?: { pendingArtefactId?: string } | null }
```

Then add a new effect after the existing artefact-loading effect (after line 297, after the closing `}, [sessionId, ...])` of the load effect):

```ts
// If we navigated here from the global Artefacts tab with a pendingArtefactId,
// fetch the artefact detail and open the overlay once the session is ready.
useEffect(() => {
  const pendingId = location.state?.pendingArtefactId
  if (!pendingId || !sessionId) return

  let cancelled = false
  artefactApi.get(sessionId, pendingId)
    .then((detail) => {
      if (cancelled) return
      useArtefactStore.getState().openOverlay(detail)
    })
    .catch((err) => {
      console.error('Failed to open pending artefact', err)
    })
    .finally(() => {
      // Clear the state so a reload does not re-open the overlay.
      window.history.replaceState({}, '')
    })

  return () => { cancelled = true }
}, [location.state, sessionId])
```

- [ ] **Step 2: Type-check and build**

Run: `cd frontend && pnpm tsc --noEmit && pnpm run build`
Expected: clean.

- [ ] **Step 3: Manual smoke test (notes for the reviewer, not a blocker)**

Spin up the dev server, open the user modal → Artefacts tab → click OPEN on a row → confirm the overlay opens automatically in the target chat. Reload the page → confirm the overlay does NOT re-open.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/chat/ChatView.tsx
git commit -m "ChatView: auto-open artefact overlay when navigated with pendingArtefactId"
```

---

## Task 9 — Final verification and merge

- [ ] **Step 1: Run the full backend test for artefacts**

Run: `uv run pytest backend/tests/modules/artefact/ -v`
Expected: all PASS.

- [ ] **Step 2: Run the frontend tests**

Run: `cd frontend && pnpm vitest run`
Expected: all PASS.

- [ ] **Step 3: Frontend build**

Run: `cd frontend && pnpm run build`
Expected: clean build, no TS errors.

- [ ] **Step 4: Merge to master**

Per project default in `CLAUDE.md` (`Implementation defaults` → "Please always merge to master after implementation"). If working in a worktree/branch, fast-forward or merge into `master` and clean up the worktree. If working directly on `master`, this step is a no-op.

---

## Self-Review Notes

**Spec coverage check:**
- Backend `GET /api/artefacts/` with enriched DTO → Tasks 1–4 ✓
- Cross-module boundary respected (no direct collection access) → Task 2 (chat helper) + Task 4 (uses persona public API) ✓
- ArtefactsTab in user modal with HistoryTab patterns → Task 7 ✓
- Persona filter, type filter, AND-token search → Task 6 (logic) + Task 7 (UI) ✓
- Sanitised mode hides NSFW personas everywhere (filter, search, count, dropdown) → Task 6 + filterPersonas memo in Task 7 ✓
- Inline rename, delete with confirm → Task 7 ✓
- Open in chat with auto-open overlay → Task 7 (navigate) + Task 8 (consume) ✓
- Events-first audit + reuse of `ARTEFACT_UPDATED` / `ARTEFACT_DELETED` / `ARTEFACT_CREATED` → Pre-flight + Task 7 subscription ✓
- Error handling (load failure, rename revert, delete revert) → Task 7 handlers ✓
- Tests: backend list endpoint + frontend filter reducer → Tasks 4 + 6 ✓

**Type/name consistency:** `ArtefactListItemDto` (backend) ↔ `ArtefactListItem` (frontend) match field-for-field. `applyArtefactFilters` signature is the same in test and implementation. `pendingArtefactId` key is the same in `ArtefactsTab` (writer) and `ChatView` (reader).

**Open assumptions flagged in the plan body:**
- Persona public API return shape (dict vs Pydantic) — Task 4 Step 3 tells the implementer to verify and adjust.
- Frontend event-bus primitive — Task 7 Step 1 tells the implementer to copy the existing pattern from `useArtefactEvents.ts`.
- Parent user-modal `onClose` wiring — Task 7 Step 1 tells the implementer to mirror the `HistoryTab` wiring.

These are not placeholders — they are explicit verification steps with a concrete file to read.

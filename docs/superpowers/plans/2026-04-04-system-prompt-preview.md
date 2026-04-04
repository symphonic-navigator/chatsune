# System Prompt Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an inline system prompt preview to the persona Overview tab, backed by a new API endpoint.

**Architecture:** New `GET /api/personas/{id}/system-prompt-preview` endpoint calls the existing `assemble_preview()` from the chat module. The frontend OverviewTab fetches this on mount and renders a collapsed preview with expand/collapse toggle.

**Tech Stack:** Python/FastAPI (backend), React/TSX/Tailwind (frontend), pytest (tests)

**Spec:** `docs/superpowers/specs/2026-04-04-system-prompt-preview-design.md`

---

### Task 1: Export `assemble_preview` from chat module

**Files:**
- Modify: `backend/modules/chat/__init__.py:15` (import line) and `:399-403` (`__all__`)

- [ ] **Step 1: Write the failing test**

Create `tests/test_system_prompt_preview_endpoint.py`:

```python
"""Tests for the system prompt preview endpoint on the persona module."""
import pytest
from unittest.mock import AsyncMock, patch


async def test_assemble_preview_is_importable_from_chat_module():
    """Verify assemble_preview is part of the chat module's public API."""
    from backend.modules.chat import assemble_preview
    assert callable(assemble_preview)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/test_system_prompt_preview_endpoint.py::test_assemble_preview_is_importable_from_chat_module -v`

Expected: FAIL with `ImportError: cannot import name 'assemble_preview'`

- [ ] **Step 3: Add the export**

In `backend/modules/chat/__init__.py`, change line 15 from:

```python
from backend.modules.chat._prompt_assembler import assemble
```

to:

```python
from backend.modules.chat._prompt_assembler import assemble, assemble_preview
```

And update `__all__` at the bottom (lines 399-403) from:

```python
__all__ = [
    "router", "init_indexes",
    "handle_chat_send", "handle_chat_edit", "handle_chat_regenerate",
    "handle_chat_cancel",
]
```

to:

```python
__all__ = [
    "router", "init_indexes",
    "handle_chat_send", "handle_chat_edit", "handle_chat_regenerate",
    "handle_chat_cancel",
    "assemble_preview",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/test_system_prompt_preview_endpoint.py::test_assemble_preview_is_importable_from_chat_module -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/chris/workspace/chatsune && git add backend/modules/chat/__init__.py tests/test_system_prompt_preview_endpoint.py && git commit -m "Export assemble_preview from chat module public API"
```

---

### Task 2: Add the preview endpoint to persona handlers

**Files:**
- Modify: `backend/modules/persona/_handlers.py` (add endpoint after line 113)
- Test: `tests/test_system_prompt_preview_endpoint.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_system_prompt_preview_endpoint.py`:

```python
from httpx import AsyncClient, ASGITransport
from backend.main import app


@pytest.fixture
def auth_headers():
    """Create a valid JWT for testing. Reuses the project's test auth pattern."""
    from backend.modules.user._tokens import create_access_token
    token = create_access_token(user_id="user-1", role="user")
    return {"Authorization": f"Bearer {token}"}


async def test_preview_endpoint_returns_assembled_prompt(auth_headers):
    """GET /api/personas/{id}/system-prompt-preview returns the preview text."""
    with patch("backend.modules.persona._handlers._persona_repo") as mock_repo_fn, \
         patch("backend.modules.persona._handlers.assemble_preview", new_callable=AsyncMock) as mock_preview:

        mock_repo = AsyncMock()
        mock_repo.find_by_id.return_value = {
            "_id": "p-1",
            "user_id": "user-1",
            "model_unique_id": "ollama_cloud:llama3.2",
        }
        mock_repo_fn.return_value = mock_repo

        mock_preview.return_value = "--- Persona ---\nYou are Luna\n\n--- About Me ---\nI am Chris"

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/personas/p-1/system-prompt-preview", headers=auth_headers)

        assert res.status_code == 200
        body = res.json()
        assert body["preview"] == "--- Persona ---\nYou are Luna\n\n--- About Me ---\nI am Chris"
        mock_preview.assert_called_once_with(
            user_id="user-1",
            persona_id="p-1",
            model_unique_id="ollama_cloud:llama3.2",
        )


async def test_preview_endpoint_returns_404_for_unknown_persona(auth_headers):
    """GET /api/personas/{id}/system-prompt-preview returns 404 if persona not found."""
    with patch("backend.modules.persona._handlers._persona_repo") as mock_repo_fn:
        mock_repo = AsyncMock()
        mock_repo.find_by_id.return_value = None
        mock_repo_fn.return_value = mock_repo

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/personas/nonexistent/system-prompt-preview", headers=auth_headers)

        assert res.status_code == 404


async def test_preview_endpoint_returns_empty_string_when_nothing_configured(auth_headers):
    """Preview returns empty string when no prompt parts are configured."""
    with patch("backend.modules.persona._handlers._persona_repo") as mock_repo_fn, \
         patch("backend.modules.persona._handlers.assemble_preview", new_callable=AsyncMock) as mock_preview:

        mock_repo = AsyncMock()
        mock_repo.find_by_id.return_value = {
            "_id": "p-1",
            "user_id": "user-1",
            "model_unique_id": "ollama_cloud:llama3.2",
        }
        mock_repo_fn.return_value = mock_repo

        mock_preview.return_value = ""

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/personas/p-1/system-prompt-preview", headers=auth_headers)

        assert res.status_code == 200
        assert res.json()["preview"] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/test_system_prompt_preview_endpoint.py -v -k "not importable"`

Expected: FAIL — endpoint does not exist yet (404 on all three)

- [ ] **Step 3: Implement the endpoint**

In `backend/modules/persona/_handlers.py`, add the import at the top (after line 6):

```python
from backend.modules.chat import assemble_preview
```

Then add the endpoint after the existing `get_persona` endpoint (after line 113):

```python
@router.get("/{persona_id}/system-prompt-preview")
async def get_system_prompt_preview(
    persona_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _persona_repo()
    doc = await repo.find_by_id(persona_id, user["sub"])
    if not doc:
        raise HTTPException(status_code=404, detail="Persona not found")

    preview = await assemble_preview(
        user_id=user["sub"],
        persona_id=persona_id,
        model_unique_id=doc["model_unique_id"],
    )
    return {"preview": preview}
```

**Important:** This endpoint MUST be placed before the `/{persona_id}` PUT/PATCH/DELETE routes. FastAPI matches routes top-to-bottom, and `system-prompt-preview` could be mistaken for a `persona_id` parameter. Placing it directly after the existing `GET /{persona_id}` (line 104-113) is correct because the more specific path `/{persona_id}/system-prompt-preview` will match before the PUT `/{persona_id}`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/chris/workspace/chatsune && uv run pytest tests/test_system_prompt_preview_endpoint.py -v`

Expected: All 4 tests PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `cd /home/chris/workspace/chatsune && uv run pytest --tb=short`

Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
cd /home/chris/workspace/chatsune && git add backend/modules/persona/_handlers.py tests/test_system_prompt_preview_endpoint.py && git commit -m "Add system prompt preview endpoint to persona API"
```

---

### Task 3: Add API function to frontend personas client

**Files:**
- Modify: `frontend/src/core/api/personas.ts`

- [ ] **Step 1: Add the `getSystemPromptPreview` function**

In `frontend/src/core/api/personas.ts`, add to the `personasApi` object (before the closing `}`):

```typescript
  getSystemPromptPreview: (personaId: string) =>
    api.get<{ preview: string }>(`/api/personas/${personaId}/system-prompt-preview`),
```

The full file should now be:

```typescript
import { api } from "./client"
import type {
  PersonaDto,
  CreatePersonaRequest,
  UpdatePersonaRequest,
} from "../types/persona"

export const personasApi = {
  list: () =>
    api.get<PersonaDto[]>("/api/personas"),

  get: (personaId: string) =>
    api.get<PersonaDto>(`/api/personas/${personaId}`),

  create: (data: CreatePersonaRequest) =>
    api.post<PersonaDto>("/api/personas", data),

  replace: (personaId: string, data: CreatePersonaRequest) =>
    api.put<PersonaDto>(`/api/personas/${personaId}`, data),

  update: (personaId: string, data: UpdatePersonaRequest) =>
    api.patch<PersonaDto>(`/api/personas/${personaId}`, data),

  remove: (personaId: string) =>
    api.delete<{ status: string }>(`/api/personas/${personaId}`),

  reorder: async (orderedIds: string[]): Promise<void> => {
    await api.patch("/api/personas/reorder", { ordered_ids: orderedIds });
  },

  getSystemPromptPreview: (personaId: string) =>
    api.get<{ preview: string }>(`/api/personas/${personaId}/system-prompt-preview`),
}
```

- [ ] **Step 2: Commit**

```bash
cd /home/chris/workspace/chatsune && git add frontend/src/core/api/personas.ts && git commit -m "Add system prompt preview to frontend personas API client"
```

---

### Task 4: Add inline preview to OverviewTab

**Files:**
- Modify: `frontend/src/app/components/persona-overlay/OverviewTab.tsx`

- [ ] **Step 1: Implement the preview section**

Replace the entire content of `frontend/src/app/components/persona-overlay/OverviewTab.tsx` with:

```tsx
import { useEffect, useState } from 'react'
import type { ChakraPaletteEntry } from '../../../core/types/chakra'
import type { PersonaDto } from '../../../core/types/persona'
import { personasApi } from '../../../core/api/personas'

interface OverviewTabProps {
  persona: PersonaDto
  chakra: ChakraPaletteEntry
}

export function OverviewTab({ persona, chakra }: OverviewTabProps) {
  const [preview, setPreview] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)

  const createdDate = new Date(persona.created_at).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })

  useEffect(() => {
    let mounted = true
    personasApi.getSystemPromptPreview(persona.id).then(res => {
      if (mounted) setPreview(res.preview)
    }).catch(() => {
      if (mounted) setPreview(null)
    })
    return () => { mounted = false }
  }, [persona.id])

  const hasPreview = preview !== null && preview.trim().length > 0

  return (
    <div className="flex flex-col items-center px-6 py-8 gap-6">
      {/* Avatar */}
      <div
        className="flex items-center justify-center rounded-full flex-shrink-0"
        style={{
          width: 120,
          height: 120,
          background: persona.profile_image ? undefined : `${chakra.hex}22`,
          border: `2px solid ${chakra.hex}55`,
          boxShadow: `0 0 28px ${chakra.glow}`,
        }}
      >
        {persona.profile_image ? (
          <img
            src={persona.profile_image}
            alt={persona.name}
            className="w-full h-full rounded-full object-cover"
          />
        ) : (
          <span
            className="text-4xl font-bold select-none"
            style={{ color: chakra.hex }}
          >
            {persona.monogram}
          </span>
        )}
      </div>

      {/* Name + tagline */}
      <div className="flex flex-col items-center gap-1 text-center">
        <h2 className="text-[18px] font-semibold text-white/90">{persona.name}</h2>
        {persona.tagline && (
          <p className="text-[13px] text-white/45 max-w-xs">{persona.tagline}</p>
        )}
      </div>

      {/* Stats grid */}
      <div
        className="grid grid-cols-3 w-full max-w-sm rounded-xl overflow-hidden"
        style={{ border: `1px solid ${chakra.hex}22` }}
      >
        {[
          { label: 'Chats', value: '\u2014' },
          { label: 'Memory tokens', value: '\u2014' },
          { label: 'Pending journal', value: '\u2014' },
        ].map((stat, i) => (
          <div
            key={stat.label}
            className="flex flex-col items-center gap-1 py-4 px-2"
            style={{
              background: `${chakra.hex}08`,
              borderRight: i < 2 ? `1px solid ${chakra.hex}22` : undefined,
            }}
          >
            <span className="text-[18px] font-semibold text-white/70">{stat.value}</span>
            <span className="text-[10px] text-white/35 text-center leading-tight">{stat.label}</span>
          </div>
        ))}
      </div>

      {/* System prompt preview */}
      {hasPreview && (
        <div className="w-full max-w-sm">
          <div className="relative">
            <pre
              className="font-mono text-[12px] text-white/50 leading-relaxed whitespace-pre-wrap break-words m-0 overflow-hidden transition-[max-height] duration-300 ease-in-out"
              style={{
                maxHeight: expanded ? '60vh' : '4.5em',
                overflowY: expanded ? 'auto' : 'hidden',
              }}
            >
              {preview.split(/(--- .+? ---)/).map((part, i) =>
                part.match(/^--- .+? ---$/) ? (
                  <span key={i} style={{ color: chakra.hex, fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.15em' }}>
                    {part}
                  </span>
                ) : (
                  <span key={i}>{part}</span>
                )
              )}
            </pre>
            {!expanded && (
              <div
                className="absolute bottom-0 left-0 right-0 h-8 pointer-events-none"
                style={{
                  background: 'linear-gradient(to bottom, transparent, #0f0d16)',
                }}
              />
            )}
          </div>
          <button
            onClick={() => setExpanded(prev => !prev)}
            className="mt-2 font-mono text-[11px] text-white/35 hover:text-white/55 transition-colors cursor-pointer bg-transparent border-none p-0"
          >
            {expanded ? 'Collapse' : 'Show full prompt'}
          </button>
        </div>
      )}

      {/* Created date */}
      <p className="text-[11px] text-white/25 font-mono">
        created {createdDate}
      </p>
    </div>
  )
}
```

Key implementation details:
- `maxHeight: '4.5em'` at `line-height: relaxed` (1.625) gives roughly 2.7 visible lines — enough to tease the content
- The fade gradient uses `rgb(10 8 16)` which matches the dark background of the overlay
- Section headers (`--- X ---`) are detected via regex split and rendered in the persona's chakra colour
- The `transition-[max-height]` provides a smooth expand/collapse animation
- On error or empty preview, the section is simply not rendered

- [ ] **Step 2: Verify the frontend builds**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm build`

Expected: Build succeeds with no TypeScript errors

- [ ] **Step 3: Commit**

```bash
cd /home/chris/workspace/chatsune && git add frontend/src/app/components/persona-overlay/OverviewTab.tsx && git commit -m "Add inline system prompt preview to persona OverviewTab"
```

---

### Task 5: Manual smoke test and final commit

- [ ] **Step 1: Run full backend test suite**

Run: `cd /home/chris/workspace/chatsune && uv run pytest --tb=short`

Expected: All tests PASS

- [ ] **Step 2: Run frontend build**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm build`

Expected: Build succeeds

- [ ] **Step 3: Verify all changes are committed**

Run: `cd /home/chris/workspace/chatsune && git status`

Expected: Clean working tree, nothing uncommitted

- [ ] **Step 4: Merge to master**

```bash
cd /home/chris/workspace/chatsune && git checkout master && git merge feature/system-prompt-preview --no-ff -m "Merge feature/system-prompt-preview: inline system prompt preview on persona overview"
```

# Model Refresh & Persona Clone — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-04-15-model-refresh-and-persona-clone-design.md`

**Goal:** Ship three small features — per-provider model refresh button, auto-refresh after Ollama pull/delete, and persona cloning with optional memory carry-over.

**Architecture:** Feature 1 reuses an existing backend endpoint and adds a small UI control (+ fixes a frontend path bug). Feature 2 wires a callback into `OllamaModelOps` so pull/delete trigger the same refresh endpoint that Feature 1's button uses. Feature 3 introduces a new `_clone.py` in the persona module (mirrors the `_import.py` pattern), a new `AvatarStore.duplicate()` helper, a `POST /api/personas/{id}/clone` endpoint, and a new `PersonaCloneDialog` on the OverviewTab alongside a relocated Export button.

**Tech Stack:** FastAPI, Pydantic v2, Motor (MongoDB), React 19 + TSX + Tailwind, Vitest (frontend), pytest + pytest-asyncio (backend).

---

## Pre-flight Checks

Before any task: make sure the working tree is clean apart from the existing `PersonaOverlay.tsx` modification noted in git status, OR stash/discard as appropriate. Run `pnpm install` (frontend) and `uv sync` (backend) if dependencies look stale.

Commands used throughout:

- Backend typecheck/syntax: `uv run python -m py_compile <file>`
- Backend tests: `uv run pytest <path> -v`
- Frontend typecheck: `cd frontend && pnpm tsc --noEmit`
- Frontend build: `cd frontend && pnpm run build`

---

## Feature 1 — Per-Provider Refresh Button

### Task 1.1: Fix incorrect API path in `llmApi.refreshConnectionModels`

**Context:** The backend route is `POST /api/llm/connections/{id}/refresh` (see `backend/modules/llm/_handlers.py:245`). The frontend client currently calls `/api/llm/connections/${id}/models/refresh`, which 404s. The method is not yet used anywhere, so the bug is latent.

**Files:**
- Modify: `frontend/src/core/api/llm.ts:37-38`

- [ ] **Step 1: Edit the path**

Replace:

```ts
  /** Returns 202 — the refresh is asynchronous; completion flows through events. */
  refreshConnectionModels: (id: string) =>
    api.post<void>(`/api/llm/connections/${id}/models/refresh`),
```

With:

```ts
  /** Returns 200 once the upstream query finishes; emits LLM_CONNECTION_MODELS_REFRESHED. */
  refreshConnectionModels: (id: string) =>
    api.post<void>(`/api/llm/connections/${id}/refresh`),
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/core/api/llm.ts
git commit -m "Fix refreshConnectionModels API path to match backend route"
```

---

### Task 1.2: Add refresh button to ConnectionGroup header in ModelBrowser

**Context:** `ModelBrowser` is rendered both by `ModelSelectionModal` (Picker) and by `UserModal/ModelsTab` (user-facing Models page). The `useEnrichedModels` hook already subscribes to `LLM_CONNECTION_MODELS_REFRESHED` (`frontend/src/core/hooks/useEnrichedModels.ts:89-99`), so we only need to trigger the backend call; the store will refresh itself when the event comes back.

**Files:**
- Modify: `frontend/src/app/components/model-browser/ModelBrowser.tsx` (ConnectionGroup component, around lines 196–238)

- [ ] **Step 1: Extend `ConnectionGroup` with a refresh handler and button**

Replace the `ConnectionGroup` function body (currently lines 196–239) with:

```tsx
function ConnectionGroup({
  connectionId,
  displayName,
  slug,
  models,
  currentModelId,
  onSelect,
  onEdit,
  onToggleFavourite,
}: ConnectionGroupProps) {
  const isCollapsed = useCollapsedGroups((s) => s.collapsed.has(connectionId))
  const toggle = useCollapsedGroups((s) => s.toggle)
  const [refreshing, setRefreshing] = useState(false)
  const [refreshError, setRefreshError] = useState<string | null>(null)

  async function handleRefresh(ev: React.MouseEvent) {
    ev.stopPropagation()
    if (refreshing) return
    setRefreshing(true)
    setRefreshError(null)
    try {
      await llmApi.refreshConnectionModels(connectionId)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Refresh failed'
      setRefreshError(msg)
      window.setTimeout(() => setRefreshError(null), 5000)
    } finally {
      setRefreshing(false)
    }
  }

  return (
    <section className="mb-4">
      <header className="border-b border-white/6 px-3 py-2 flex items-center gap-2">
        <button
          type="button"
          onClick={() => toggle(connectionId)}
          className="flex items-center gap-2 text-left flex-1 min-w-0"
          aria-expanded={!isCollapsed}
        >
          <span className="text-white/50 text-[11px]">{isCollapsed ? '▸' : '▾'}</span>
          <span className="text-[13px] font-semibold text-white/85 truncate">{displayName}</span>
          <span className="text-[11px] font-mono text-white/35 truncate">— {slug}</span>
        </button>
        {refreshError && (
          <span className="text-[11px] text-red-300 truncate" title={refreshError}>
            {refreshError}
          </span>
        )}
        <button
          type="button"
          onClick={handleRefresh}
          disabled={refreshing}
          aria-label="Refresh models from upstream"
          title="Refresh models from upstream"
          className={[
            'shrink-0 rounded border border-white/10 px-2 py-0.5 text-[11px] text-white/70 hover:bg-white/5 disabled:opacity-50 disabled:cursor-not-allowed',
            refreshing ? 'animate-pulse' : '',
          ].join(' ')}
        >
          {refreshing ? '…' : '⟳'}
        </button>
      </header>
      {!isCollapsed && (
        <ul className="divide-y divide-white/5 mt-1">
          {models.map((model) => (
            <ModelRow
              key={model.unique_id}
              model={model}
              isCurrent={model.unique_id === currentModelId}
              onSelect={onSelect}
              onEdit={() => onEdit(model)}
              onToggleFavourite={() => void onToggleFavourite(model)}
            />
          ))}
        </ul>
      )}
    </section>
  )
}
```

- [ ] **Step 2: Verify `useState` import already exists**

Top of the file should already have `import { useMemo, useState } from 'react'`. If not, add `useState`.

- [ ] **Step 3: Typecheck**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Frontend build**

Run: `cd frontend && pnpm run build`
Expected: success.

- [ ] **Step 5: Manual smoke test**

Start dev stack. Open Picker and User-Models page. Verify: each provider header shows `⟳` button; clicking it triggers the backend refresh and the list updates. Trigger an error case (stop upstream) to confirm the inline red error hint appears for ~5s.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/components/model-browser/ModelBrowser.tsx
git commit -m "Add per-provider refresh button to ModelBrowser ConnectionGroup"
```

---

## Feature 2 — Auto-Refresh After Pull / Delete

### Task 2.1: Extend `OllamaModelOps` with an `on_models_changed` callback

**Context:** After a successful pull (`_finalise_success`) or delete (`delete()`), the user's generic Enriched-Models store must learn about the change. The cleanest hook is an optional async callback passed into the constructor. The caller (the adapter sub-router) owns the logic for *how* to refresh, keeping `OllamaModelOps` agnostic of the LLM-module connection abstraction.

**Files:**
- Modify: `backend/modules/llm/_ollama_model_ops.py` (constructor + `_finalise_success` + `delete`)

- [ ] **Step 1: Add the callback parameter to `__init__`**

In `OllamaModelOps.__init__` (around line 75), add a new kwarg and store it. Update imports at the top:

```python
from typing import Any, Awaitable, Callable
```

Extend `__init__`:

```python
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        scope: str,
        event_bus: Any,
        registry: PullTaskRegistry,
        target_user_ids: list[str],
        http_transport: httpx.AsyncBaseTransport | None = None,
        progress_throttle_seconds: float = _DEFAULT_THROTTLE_S,
        on_models_changed: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._scope = scope
        self._bus = event_bus
        self._registry = registry
        self._target_user_ids = target_user_ids
        self._transport = http_transport
        self._throttle = progress_throttle_seconds
        self._on_models_changed = on_models_changed
```

- [ ] **Step 2: Add a helper method that invokes the callback and swallows errors**

Insert after `__init__`:

```python
    async def _notify_models_changed(self) -> None:
        """Best-effort post-operation hook. Logs and swallows failures —
        the underlying pull/delete already succeeded, so a refresh error
        must not be reported as an operational failure to the user."""
        if self._on_models_changed is None:
            return
        try:
            await self._on_models_changed()
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning(
                "on_models_changed hook failed for scope=%s: %s",
                self._scope, exc,
            )
```

- [ ] **Step 3: Call the hook at the end of `_finalise_success`**

At the very end of `_finalise_success` (after `await self._bus.publish(Topics.LLM_MODEL_PULL_COMPLETED, ...)` around line 230), append:

```python
        await self._notify_models_changed()
```

- [ ] **Step 4: Call the hook at the end of `delete`**

At the end of `delete` (after `await self._bus.publish(Topics.LLM_MODEL_DELETED, ...)` around line 267), append:

```python
        await self._notify_models_changed()
```

- [ ] **Step 5: Syntax check**

Run: `uv run python -m py_compile backend/modules/llm/_ollama_model_ops.py`
Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_ollama_model_ops.py
git commit -m "Add on_models_changed hook to OllamaModelOps for post-pull/delete refresh"
```

---

### Task 2.2: Wire the refresh callback at every OllamaModelOps construction site

**Context:** Find every place that constructs `OllamaModelOps` and supply an `on_models_changed` callback that (a) calls `refresh_connection_models(...)`, then (b) publishes `LLM_CONNECTION_MODELS_REFRESHED`. The construction sites live in the Ollama HTTP adapter and possibly admin handlers.

**Files:**
- Modify: `backend/modules/llm/_adapters/_ollama_http.py`
- Modify (if present): any other call-site surfaced by the grep below

- [ ] **Step 1: Find construction sites**

Run: `rg "OllamaModelOps\(" backend/`
Record every hit. Expected sites: inside `_adapters/_ollama_http.py` for pull/cancel/delete handlers.

- [ ] **Step 2: Factor a helper that builds the callback**

At the top of `_adapters/_ollama_http.py` (near other helpers), add:

```python
from datetime import datetime, timezone

from backend.modules.llm._metadata import refresh_connection_models
from shared.events.llm import LlmConnectionModelsRefreshedEvent
from shared.topics import Topics


def _make_on_models_changed(
    connection,  # ResolvedConnection
    adapter_cls,
    redis,
    event_bus,
):
    async def _cb() -> None:
        await refresh_connection_models(connection, adapter_cls, redis)
        await event_bus.publish(
            Topics.LLM_CONNECTION_MODELS_REFRESHED,
            LlmConnectionModelsRefreshedEvent(
                connection_id=connection.id,
                success=True,
                error=None,
                timestamp=datetime.now(timezone.utc),
            ),
            target_user_ids=[connection.user_id],
        )
    return _cb
```

Adjust imports / types to match the file's existing style — if the file already imports `ResolvedConnection`, use that annotation instead of `connection` untyped.

- [ ] **Step 3: Pass the callback into every OllamaModelOps construction**

For each occurrence of `OllamaModelOps(` where the operation will write (pull or delete), add:

```python
    on_models_changed=_make_on_models_changed(c, adapter_cls, redis, event_bus),
```

Read-only uses (diagnostics, test pings) do not need the callback.

- [ ] **Step 4: Syntax check**

Run: `uv run python -m py_compile backend/modules/llm/_adapters/_ollama_http.py`
Expected: no output.

- [ ] **Step 5: Manual smoke test**

Start dev stack. Pull a small model via `OllamaModelsPanel` (e.g. `llama3.2:1b`). Open Picker in another tab. Verify the new model appears in the Picker after `pull.completed` without manual refresh. Then delete it and verify it disappears.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_adapters/_ollama_http.py
git commit -m "Wire on_models_changed callback into OllamaModelOps construction"
```

---

## Feature 3 — Persona Cloning

### Task 3.1: Add `AvatarStore.duplicate()`

**Context:** Cloning a persona with an existing avatar should create a brand-new file on disk — clones must not share a filename with the original (deleting the source would break the clone). A small helper on `AvatarStore` keeps avatar I/O concentrated in the persona module.

**Files:**
- Modify: `backend/modules/persona/_avatar_store.py`
- Test: `backend/tests/modules/persona/test_avatar_store_duplicate.py` (new)

- [ ] **Step 1: Check test directory**

Run: `ls backend/tests/modules/persona/ 2>/dev/null || echo "missing"`
If missing, create: `mkdir -p backend/tests/modules/persona && touch backend/tests/modules/persona/__init__.py`

- [ ] **Step 2: Write the failing test**

Create `backend/tests/modules/persona/test_avatar_store_duplicate.py`:

```python
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.modules.persona._avatar_store import AvatarStore


@pytest.fixture
def avatar_root(tmp_path: Path) -> Path:
    root = tmp_path / "avatars"
    root.mkdir()
    return root


def test_duplicate_creates_new_file_with_same_bytes(avatar_root: Path) -> None:
    with patch("backend.modules.persona._avatar_store.settings") as s:
        s.avatar_root = str(avatar_root)
        store = AvatarStore()
        original = store.save(b"hello-avatar", "png")
        duplicate = store.duplicate(original)

        assert duplicate != original
        assert duplicate.endswith(".png")
        assert (avatar_root / duplicate).read_bytes() == b"hello-avatar"
        # Source must remain intact.
        assert (avatar_root / original).read_bytes() == b"hello-avatar"


def test_duplicate_returns_none_if_source_missing(avatar_root: Path) -> None:
    with patch("backend.modules.persona._avatar_store.settings") as s:
        s.avatar_root = str(avatar_root)
        store = AvatarStore()
        assert store.duplicate("does-not-exist.png") is None
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest backend/tests/modules/persona/test_avatar_store_duplicate.py -v`
Expected: FAIL with `AttributeError: 'AvatarStore' object has no attribute 'duplicate'`.

- [ ] **Step 4: Implement `duplicate`**

In `backend/modules/persona/_avatar_store.py`, append as a new method of `AvatarStore`:

```python
    def duplicate(self, filename: str) -> str | None:
        """Copy an existing avatar file, returning the new filename.

        Returns ``None`` if the source file does not exist.
        """
        source = self._root / filename
        if not source.exists():
            return None
        extension = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
        new_name = f"{uuid4()}.{extension}"
        target = self._root / new_name
        target.write_bytes(source.read_bytes())
        return new_name
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest backend/tests/modules/persona/test_avatar_store_duplicate.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/modules/persona/_avatar_store.py backend/tests/modules/persona/test_avatar_store_duplicate.py
git add backend/tests/modules/persona/__init__.py 2>/dev/null || true
git commit -m "Add AvatarStore.duplicate for persona clone"
```

---

### Task 3.2: Implement `clone_persona` orchestrator

**Context:** Orchestrator that mirrors `_import.py` but operates purely in-process — no tarball, no manifest. It loads the source, creates a new persona document, copies technical config via `repo.update`, duplicates the avatar file, and (optionally) re-imports memory via the memory module's public API. Rolls back via `cascade_delete_persona` on failure.

**Files:**
- Create: `backend/modules/persona/_clone.py`

- [ ] **Step 1: Create the orchestrator**

Write `backend/modules/persona/_clone.py`:

```python
"""Persona cloning — create a new persona that duplicates the source's
personality and technical configuration. History is never cloned.

This orchestrator is the in-process inverse of `_import.py`:
- No archive, no manifest.
- Memory (journal + memory-bodies) is optional and all-or-nothing.
- Avatar files are duplicated via `AvatarStore.duplicate`.
- KB attachments (`knowledge_library_ids`) are copied as references only —
  KB entities themselves are n:m and never duplicated.
- On any post-insert failure, cascade-delete the partial clone and re-raise
  as HTTPException(400).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException

from backend.database import get_db
from backend.modules.persona._avatar_store import AvatarStore
from backend.modules.persona._cascade import cascade_delete_persona
from backend.modules.persona._monogram import generate_monogram
from backend.modules.persona._repository import PersonaRepository
from backend.ws.event_bus import get_event_bus
from shared.dtos.persona import PersonaDto
from shared.events.persona import PersonaCreatedEvent
from shared.topics import Topics

_log = logging.getLogger(__name__)


async def clone_persona(
    user_id: str,
    source_id: str,
    *,
    name: str | None,
    clone_memory: bool,
) -> PersonaDto:
    correlation_id = f"persona-clone-{uuid.uuid4()}"
    repo = PersonaRepository(get_db())

    source = await repo.find_by_id(source_id, user_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Persona not found")

    final_name = (name or "").strip() or f"{source['name']} Clone"

    _log.info(
        "persona_clone.start user_id=%s correlation_id=%s source_id=%s clone_memory=%s",
        user_id, correlation_id, source_id, clone_memory,
    )

    # Generate a collision-free monogram against the user's existing set.
    existing_monograms = await repo.list_monograms_for_user(user_id)
    monogram = generate_monogram(final_name, existing_monograms)

    # Determine display_order for "append at end".
    all_personas = await repo.list_for_user(user_id)
    next_order = max((p.get("display_order", 0) for p in all_personas), default=-1) + 1

    new_id: str | None = None
    try:
        # 1. Insert the new persona with the basic fields supported by `create`.
        #    `knowledge_library_ids`, `mcp_config`, `integrations_config`,
        #    `voice_config`, `profile_crop`, and the regenerated monogram are
        #    applied in a follow-up update — same pattern as `_import.py`.
        new_doc = await repo.create(
            user_id=user_id,
            name=final_name,
            tagline=source.get("tagline", "") or "",
            model_unique_id=source.get("model_unique_id"),  # type: ignore[arg-type]
            system_prompt=source.get("system_prompt", "") or "",
            temperature=source.get("temperature", 1.0),
            reasoning_enabled=source.get("reasoning_enabled", False),
            nsfw=source.get("nsfw", False),
            colour_scheme=source.get("colour_scheme", "solar") or "solar",
            display_order=next_order,
            pinned=False,
            profile_image=None,  # filled after avatar duplication
            soft_cot_enabled=source.get("soft_cot_enabled", False),
            vision_fallback_model=source.get("vision_fallback_model"),
        )
        new_id = new_doc["_id"]

        # 2. Apply extended technical fields that `create` does not accept.
        extended: dict = {
            "monogram": monogram,
            "knowledge_library_ids": list(source.get("knowledge_library_ids") or []),
            "mcp_config": source.get("mcp_config"),
            "integrations_config": source.get("integrations_config"),
            "voice_config": source.get("voice_config"),
            "profile_crop": source.get("profile_crop"),
        }
        await repo.update(new_id, user_id, extended)

        # 3. Duplicate the avatar file (if any).
        src_avatar = source.get("profile_image")
        if src_avatar:
            store = AvatarStore()
            new_filename = store.duplicate(src_avatar)
            if new_filename is not None:
                await repo.update_profile_image(new_id, user_id, new_filename)
            else:
                _log.warning(
                    "persona_clone.avatar_missing correlation_id=%s source_avatar=%s",
                    correlation_id, src_avatar,
                )

        # 4. Memory (optional, all-or-nothing).
        if clone_memory:
            from backend.modules.memory import (
                bulk_export_for_persona,
                bulk_import_for_persona,
            )

            bundle = await bulk_export_for_persona(user_id, source_id)
            await bulk_import_for_persona(user_id, new_id, bundle)

        # 5. Re-fetch + publish PersonaCreatedEvent.
        fresh = await repo.find_by_id(new_id, user_id)
        if fresh is None:
            raise RuntimeError(f"Persona {new_id} vanished after clone")
        dto = PersonaRepository.to_dto(fresh)

        event_bus = get_event_bus()
        await event_bus.publish(
            Topics.PERSONA_CREATED,
            PersonaCreatedEvent(
                persona_id=new_id,
                user_id=user_id,
                persona=dto,
                timestamp=datetime.now(UTC),
            ),
            scope=f"persona:{new_id}",
            target_user_ids=[user_id],
        )

        _log.info(
            "persona_clone.done user_id=%s correlation_id=%s new_id=%s",
            user_id, correlation_id, new_id,
        )
        return dto

    except HTTPException:
        if new_id is not None:
            try:
                await cascade_delete_persona(user_id, new_id)
            except Exception:
                _log.exception(
                    "persona_clone.rollback_failed correlation_id=%s new_id=%s",
                    correlation_id, new_id,
                )
        raise
    except Exception as exc:
        _log.exception(
            "persona_clone.failed correlation_id=%s new_id=%s",
            correlation_id, new_id,
        )
        if new_id is not None:
            try:
                await cascade_delete_persona(user_id, new_id)
            except Exception:
                _log.exception(
                    "persona_clone.rollback_failed correlation_id=%s new_id=%s",
                    correlation_id, new_id,
                )
        raise HTTPException(
            status_code=400, detail=f"Persona clone failed: {exc}",
        ) from exc
```

- [ ] **Step 2: Syntax check**

Run: `uv run python -m py_compile backend/modules/persona/_clone.py`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/persona/_clone.py
git commit -m "Add clone_persona orchestrator in persona module"
```

---

### Task 3.3: Expose `clone_persona` in the persona module's public API

**Files:**
- Modify: `backend/modules/persona/__init__.py`

- [ ] **Step 1: Add import and re-export**

At the top of `backend/modules/persona/__init__.py`, add:

```python
from backend.modules.persona._clone import clone_persona
```

And append `"clone_persona"` to the module's `__all__` list (or equivalent re-export structure). Match the existing style in that file.

- [ ] **Step 2: Syntax check**

Run: `uv run python -m py_compile backend/modules/persona/__init__.py`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/persona/__init__.py
git commit -m "Export clone_persona from persona module"
```

---

### Task 3.4: Add `POST /api/personas/{id}/clone` endpoint

**Context:** Thin handler — input validation + delegation to `clone_persona`.

**Files:**
- Modify: `backend/modules/persona/_handlers.py`

- [ ] **Step 1: Inspect the file**

Run: `rg -n "@router\." backend/modules/persona/_handlers.py`
Identify the existing patterns for request bodies and routes. Pick the closest peer route (e.g. the export or create route) and mirror its style.

- [ ] **Step 2: Add request body and handler**

Near the top of `_handlers.py`, add:

```python
from pydantic import BaseModel


class ClonePersonaRequest(BaseModel):
    name: str | None = None
    clone_memory: bool = False
```

Near the other routes, add:

```python
@router.post("/{persona_id}/clone")
async def clone_persona_endpoint(
    persona_id: str,
    body: ClonePersonaRequest,
    user: dict = Depends(require_active_session),
) -> PersonaDto:
    from backend.modules.persona import clone_persona

    return await clone_persona(
        user_id=user["sub"],
        source_id=persona_id,
        name=body.name,
        clone_memory=body.clone_memory,
    )
```

If `PersonaDto` or `require_active_session` is not yet imported in this file, add the imports. Consult existing routes for the right dependency names.

- [ ] **Step 3: Syntax check**

Run: `uv run python -m py_compile backend/modules/persona/_handlers.py`
Expected: no output.

- [ ] **Step 4: Smoke test via LLM harness or curl**

Start backend. Authenticate. POST to `/api/personas/<existing_persona_id>/clone` with body `{"name": "", "clone_memory": false}`. Expect 200 with a new `PersonaDto` whose name is `"<Original> Clone"`.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/persona/_handlers.py
git commit -m "Add POST /personas/{id}/clone endpoint"
```

---

### Task 3.5: Add `personasApi.clonePersona` client method

**Files:**
- Modify: `frontend/src/core/api/personas.ts`

- [ ] **Step 1: Add method**

Inside the `personasApi` object in `frontend/src/core/api/personas.ts`, add (a natural spot is after `remove`):

```ts
  clonePersona: (
    personaId: string,
    body: { name: string; clone_memory: boolean },
  ) =>
    api.post<PersonaDto>(`/api/personas/${personaId}/clone`, body),
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/core/api/personas.ts
git commit -m "Add personasApi.clonePersona client method"
```

---

### Task 3.6: Build `PersonaCloneDialog` component

**Files:**
- Create: `frontend/src/app/components/persona-overlay/PersonaCloneDialog.tsx`

- [ ] **Step 1: Create the component**

Write `frontend/src/app/components/persona-overlay/PersonaCloneDialog.tsx`:

```tsx
import { useEffect, useRef, useState } from 'react'
import { Sheet } from '../../../core/components/Sheet'
import { personasApi } from '../../../core/api/personas'
import type { PersonaDto } from '../../../core/types/persona'

interface PersonaCloneDialogProps {
  source: PersonaDto
  onClose: () => void
  onCloned: (clone: PersonaDto) => void
}

export function PersonaCloneDialog({ source, onClose, onCloned }: PersonaCloneDialogProps) {
  const [name, setName] = useState(`${source.name} Clone`)
  const [cloneMemory, setCloneMemory] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
    inputRef.current?.select()
  }, [])

  async function handleSubmit(ev: React.FormEvent) {
    ev.preventDefault()
    if (submitting) return
    setSubmitting(true)
    setError(null)
    try {
      const clone = await personasApi.clonePersona(source.id, {
        name: name.trim(),
        clone_memory: cloneMemory,
      })
      onCloned(clone)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Clone failed')
      setSubmitting(false)
    }
  }

  return (
    <Sheet isOpen onClose={onClose} size="sm" ariaLabel="Clone persona">
      <form onSubmit={handleSubmit} className="flex flex-col gap-4 p-5">
        <header className="flex items-center justify-between">
          <h3 className="text-[15px] font-semibold text-white/85">Clone persona</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded px-2 text-white/50 hover:bg-white/5 hover:text-white/80"
          >
            ✕
          </button>
        </header>

        <label className="flex flex-col gap-1">
          <span className="text-[11px] uppercase tracking-wider text-white/60">Name</span>
          <input
            ref={inputRef}
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="rounded border border-white/10 bg-black/20 px-3 py-2 text-[13px] text-white/85 focus:border-white/25 focus:outline-none"
            placeholder={`${source.name} Clone`}
          />
        </label>

        <label className="flex items-start gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={cloneMemory}
            onChange={(e) => setCloneMemory(e.target.checked)}
            className="mt-1"
          />
          <span className="flex flex-col">
            <span className="text-[13px] text-white/85">Memories mitklonen</span>
            <span className="text-[11px] text-white/50">
              Journal und konsolidierte Memories aus der Original-Persona übernehmen. History wird nie geklont.
            </span>
          </span>
        </label>

        {error && (
          <p className="text-[12px] text-red-300">{error}</p>
        )}

        <div className="flex items-center justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded px-3 py-1.5 text-[12px] text-white/70 hover:bg-white/5 disabled:opacity-50"
          >
            Abbrechen
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="rounded border border-gold/40 bg-gold/10 px-4 py-1.5 text-[12px] text-gold transition-colors hover:bg-gold/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? 'Cloning…' : 'Klonen'}
          </button>
        </div>
      </form>
    </Sheet>
  )
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no errors. If `Sheet` size="sm" is not supported, use whatever size token the existing dialogs (e.g. `ExportPersonaModal`) use.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/components/persona-overlay/PersonaCloneDialog.tsx
git commit -m "Add PersonaCloneDialog component"
```

---

### Task 3.7: Add Clone button + wire dialog on `OverviewTab`

**Context:** The dialog opens from a new button on OverviewTab, alongside the existing Delete confirm flow.

**Files:**
- Modify: `frontend/src/app/components/persona-overlay/OverviewTab.tsx`

- [ ] **Step 1: Import the dialog**

At the top of `OverviewTab.tsx`, add:

```tsx
import { PersonaCloneDialog } from './PersonaCloneDialog'
```

- [ ] **Step 2: Add state + handler**

Inside the component, near the other `useState` hooks, add:

```tsx
  const [cloneOpen, setCloneOpen] = useState(false)
```

- [ ] **Step 3: Add Clone button above the Danger zone section**

Find the `{/* Danger zone — delete */}` block (around line 283). Immediately *before* it, insert:

```tsx
      {/* Persona actions — Clone, Export */}
      <div className="w-full max-w-sm flex gap-2">
        <button
          type="button"
          onClick={() => setCloneOpen(true)}
          className="flex-1 rounded-lg py-2 text-[12px] text-white/70 border border-white/10 hover:bg-white/5"
        >
          Clone
        </button>
      </div>
```

(Export button is added in Task 3.8 — for now leave a single-button row; Task 3.8 will add the second.)

- [ ] **Step 4: Render the dialog**

At the end of the component (just before the final closing `</div>` of the top-level wrapper), add:

```tsx
      {cloneOpen && (
        <PersonaCloneDialog
          source={persona}
          onClose={() => setCloneOpen(false)}
          onCloned={() => setCloneOpen(false)}
        />
      )}
```

The new persona will appear in the sidebar automatically via `PersonaCreatedEvent`.

- [ ] **Step 5: Typecheck and build**

Run: `cd frontend && pnpm tsc --noEmit && pnpm run build`
Expected: success.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/components/persona-overlay/OverviewTab.tsx
git commit -m "Add Clone button + dialog wiring to persona OverviewTab"
```

---

### Task 3.8: Move Export button from `EditTab` to `OverviewTab`

**Context:** Thematically the Overview tab is the entry-point surface for persona-level actions. Export stays functionally identical; only its mount point changes.

**Files:**
- Modify: `frontend/src/app/components/persona-overlay/OverviewTab.tsx`
- Modify: `frontend/src/app/components/persona-overlay/EditTab.tsx`

- [ ] **Step 1: Add imports + state + handler to `OverviewTab.tsx`**

Add these imports at the top (some already exist — merge as needed):

```tsx
import { ApiError } from '../../../core/api/client'
import { useNotificationStore } from '../../../core/store/notificationStore'
import { triggerBlobDownload } from '../../../core/utils/download'
import { ExportPersonaModal } from './ExportPersonaModal'
```

Add state inside the component:

```tsx
  const [exportOpen, setExportOpen] = useState(false)
  const [exporting, setExporting] = useState(false)
  const addNotification = useNotificationStore((s) => s.addNotification)
```

Add the handler (1:1 port of `EditTab.tsx:163-190`):

```tsx
  async function handleExport(includeContent: boolean) {
    if (exporting) return
    setExporting(true)
    try {
      const { blob, filename } = await personasApi.exportPersona(persona.id, includeContent)
      triggerBlobDownload({ blob, filename })
      setExportOpen(false)
      addNotification({
        level: 'success',
        title: 'Export started',
        message: `${persona.name} downloaded as ${filename}.`,
      })
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Failed to export persona.'
      addNotification({
        level: 'error',
        title: 'Export failed',
        message,
      })
    } finally {
      setExporting(false)
    }
  }
```

- [ ] **Step 2: Add Export button next to Clone**

Change the actions row added in Task 3.7 from:

```tsx
      <div className="w-full max-w-sm flex gap-2">
        <button
          type="button"
          onClick={() => setCloneOpen(true)}
          className="flex-1 rounded-lg py-2 text-[12px] text-white/70 border border-white/10 hover:bg-white/5"
        >
          Clone
        </button>
      </div>
```

To:

```tsx
      <div className="w-full max-w-sm flex gap-2">
        <button
          type="button"
          onClick={() => setCloneOpen(true)}
          className="flex-1 rounded-lg py-2 text-[12px] text-white/70 border border-white/10 hover:bg-white/5"
        >
          Clone
        </button>
        <button
          type="button"
          onClick={() => setExportOpen(true)}
          disabled={exporting}
          title="Export this persona as a .chatsune-persona.tar.gz archive"
          className="flex-1 rounded-lg py-2 text-[12px] text-white/70 border border-white/10 hover:bg-white/5 disabled:opacity-50"
        >
          {exporting ? 'Exporting…' : 'Export'}
        </button>
      </div>
```

- [ ] **Step 3: Render `ExportPersonaModal` in OverviewTab**

Just below where `PersonaCloneDialog` is rendered (see Task 3.7 Step 4), add:

```tsx
      {exportOpen && (
        <ExportPersonaModal
          personaName={persona.name}
          chakraHex={chakra.hex}
          busy={exporting}
          onCancel={() => setExportOpen(false)}
          onExport={handleExport}
        />
      )}
```

- [ ] **Step 4: Remove Export from `EditTab.tsx`**

Delete:
- The import `import { ExportPersonaModal } from './ExportPersonaModal'` (line 15).
- The state `exportOpen`, `exporting` (lines 54–55).
- The `handleExport` function (lines 163–190 or thereabouts).
- The Export button JSX (lines 513–524).
- The `<ExportPersonaModal>` render (lines 591–596).

Run `rg -n "exportOpen|setExportOpen|handleExport|ExportPersonaModal" frontend/src/app/components/persona-overlay/EditTab.tsx` afterwards to confirm no stale references remain.

- [ ] **Step 5: Typecheck and build**

Run: `cd frontend && pnpm tsc --noEmit && pnpm run build`
Expected: success.

- [ ] **Step 6: Manual smoke test**

Open a persona overlay. Overview tab shows **Clone** and **Export** buttons next to each other; Delete still below in its own Danger-zone section. Edit tab no longer has Export. Both Clone and Export flows succeed end-to-end.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/components/persona-overlay/OverviewTab.tsx \
        frontend/src/app/components/persona-overlay/EditTab.tsx
git commit -m "Move persona Export button from EditTab to OverviewTab"
```

---

## Wrap-up

- [ ] **Step 1: Run the full test suite**

Backend: `uv run pytest backend/tests -x -q`
Frontend: `cd frontend && pnpm test --run` (if vitest is configured) plus `pnpm tsc --noEmit`.

- [ ] **Step 2: Merge to master**

Per project convention (`CLAUDE.md`): after a feature is complete, merge to master. If this plan is running on a feature branch/worktree, fast-forward or squash-merge to master once all tasks are committed and verified.

---

## Out of Scope (for reference)

The following are explicitly **not** part of this plan. If they come up during implementation, open a separate issue or new session:

- Bulk refresh of all connections with one click.
- Cloning across users.
- Cloning of sessions, history, artefacts, storage blobs.
- Duplicating KB entities (only reference arrays are copied).
- UI tests for the new dialog (build verification + manual smoke test is sufficient for this size).

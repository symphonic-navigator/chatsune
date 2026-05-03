# Sidebar Redesign & UX Cleanup (Projects Prep) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Independent pre-delivery before the Projects feature: redesigned sidebar with capped three-zone layout (Personas / [Projects, hidden in v1] / History), LRU-based ordering, gold-stripe pinned indicator, bottom-nav consolidation, and four side cleanups (Personas-tab scroll, Personas-tab "+", History-tab pin, in-chat pin button).

**Architecture:** The sidebar's god-component (`Sidebar.tsx`, ~1170 lines) decomposes into focused sub-components: `ActionBlock`, `ZoneSection` (parameterised over entity type), `FooterBlock`, plus the existing collapsed-rail variant. Allocation of free vertical space among open zones happens via a CSS-grid or flex `flex-basis` strategy (decide in the plan; show the chosen mechanism). Backend gains a single new field `personas.last_used_at` plus one bump entry-point exposed via the persona module's public API.

**Tech Stack:** React + TypeScript + Vite + Tailwind CSS (frontend); FastAPI + Pydantic v2 + Motor/MongoDB (backend); pnpm; uv; Vitest; pytest.

---

## Subagent constraint

> When dispatching a subagent for a task: do NOT merge, do NOT push, do NOT switch branches. Stay on the current branch. Each task ends with one commit on the working branch.

## Zone-allocation choice (locked)

Open entity zones share remaining vertical space via **flexbox**:

- The middle scrollable container becomes `display: flex; flex-direction: column; min-height: 0`.
- Each open zone wrapper carries `flex: 1 1 0; min-height: 0; overflow-y: auto` so they share space evenly and scroll internally.
- Closed zones collapse to their header height with `flex: 0 0 auto`.

Justification: simpler than CSS-grid (no template-rows recalculation when count of open zones changes), works without JS measurement, and Tailwind classes (`flex-1`, `min-h-0`, `overflow-y-auto`) cover it directly.

## Pin indicator (locked)

- `border-left: 3px solid rgba(212, 175, 55, 0.85)`
- `background: rgba(212, 175, 55, 0.03)`
- Item left-padding reduced by 3px so text x-position matches unpinned rows.

## `last_used_at` semantics (locked)

- Sort key for personas in sidebar: `last_used_at ?? created_at`, descending.
- New personas (never chatted) appear at the TOP of the unpinned LRU.
- Bumped on chat-session create AND chat-session resume.

## Persona bump trigger (locked)

- Backend `chat.create_session` (already in `_handlers.py:40`) calls `persona.bump_last_used` directly.
- New endpoint `POST /api/chat/sessions/{session_id}/resume` whose only job is to bump the persona's `last_used_at`.
- Frontend fires this once when the session-load effect runs in `ChatView.tsx` (around line 320–395), idempotent, fire-and-forget.

## Pin button in chat top bar (locked)

- Lives in `frontend/src/features/chat/ChatView.tsx` around line 1183 next to `sessionTitle`.
- Placed RIGHT of the title.
- Reads/writes via `chatApi.updateSessionPinned`.

## Notes for the verifier

- Frontend full build: `cd frontend && pnpm run build` — runs `tsc -b && vite build`.
- Frontend type check (sub-task only): `cd frontend && pnpm tsc --noEmit`.
- Vitest: `cd frontend && pnpm vitest run`.
- Backend pure unit tests on host (no MongoDB): `cd backend && uv run pytest tests/modules/persona tests/modules/chat -k "not requires_db"` — the existing `clean_db` fixture auto-skips when not requested. For the persona-bump unit test added in Phase 1 we deliberately avoid `db`/`client` fixtures so it can run on the host. Backend tests that touch MongoDB (tests requesting `db` or `client` fixtures) must be run inside Docker: `docker compose exec backend pytest tests/test_personas.py tests/modules/chat`.

---

## Phase 1 — Backend foundation

### Task 1.1 — Add `last_used_at` field to `PersonaDocument`

**Purpose:** Add the new optional datetime field with backwards-compatible default, so existing documents deserialise unchanged.

**Files — Modify:**
- `backend/modules/persona/_models.py`

**Steps:**

- [ ] Open `backend/modules/persona/_models.py`. Insert a new field declaration directly after the existing `updated_at` line (currently line 40), before the `model_config` line:

  ```python
      # Most recent chat-session creation or resume. Drives sidebar LRU
      # ordering. None when the persona has never been chatted with — in
      # that case sort falls back to created_at descending.
      last_used_at: datetime | None = None
  ```

- [ ] Run `uv run python -m py_compile backend/modules/persona/_models.py` from the repo root. Expected output: no output, exit code 0.

- [ ] Commit:

  ```bash
  git add backend/modules/persona/_models.py
  git commit -m "$(cat <<'EOF'
  Add personas.last_used_at field with backwards-compatible None default

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 1.2 — Repository method: `bump_last_used`

**Purpose:** Add a single repository method that updates `last_used_at` to "now" for one persona, scoped to its owning user.

**Files — Modify:**
- `backend/modules/persona/_repository.py`

**Steps:**

- [ ] Open `backend/modules/persona/_repository.py`. Find the `delete` method (currently around line 127). Directly above it, add the following method:

  ```python
      async def bump_last_used(self, persona_id: str, user_id: str) -> None:
          """Stamp last_used_at = now on this persona. No-op if not found.

          Called when a chat session is created or resumed for the persona.
          Errors are swallowed by the public API wrapper — sidebar LRU
          ordering is not load-bearing enough to break the chat write path.
          """
          await self._collection.update_one(
              {"_id": persona_id, "user_id": user_id},
              {"$set": {"last_used_at": datetime.now(UTC)}},
          )
  ```

- [ ] Run `uv run python -m py_compile backend/modules/persona/_repository.py`. Expected: no output, exit 0.

- [ ] Commit:

  ```bash
  git add backend/modules/persona/_repository.py
  git commit -m "$(cat <<'EOF'
  Add PersonaRepository.bump_last_used for chat-driven LRU updates

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 1.3 — Public API: expose `bump_last_used` from persona module

**Purpose:** Surface `bump_last_used` via `backend/modules/persona/__init__.py` so the chat module can call it without crossing the `_` import boundary.

**Files — Modify:**
- `backend/modules/persona/__init__.py`

**Steps:**

- [ ] Open `backend/modules/persona/__init__.py`. Directly above the `__all__` list (currently line 78), add a new public function:

  ```python
  async def bump_last_used(persona_id: str, user_id: str) -> None:
      """Stamp the persona's last_used_at to now. Fire-and-forget.

      Called from the chat module when a session is created or resumed.
      Failures are logged and swallowed by the caller — sidebar LRU is
      cosmetic and must never break the chat write path.
      """
      db = get_db()
      repo = PersonaRepository(db)
      await repo.bump_last_used(persona_id, user_id)
  ```

- [ ] In the same file, extend `__all__` to include the new symbol. Replace the existing `__all__` block with:

  ```python
  __all__ = [
      "router",
      "init_indexes",
      "get_persona",
      "bump_last_used",
      "sign_avatar_url",
      "unwire_personas_for_connection",
      "remove_library_from_all_personas",
      "cascade_delete_persona",
      "clone_persona",
      "list_persona_ids_for_user",
  ]
  ```

- [ ] Run `uv run python -m py_compile backend/modules/persona/__init__.py`. Expected: no output, exit 0.

- [ ] Commit:

  ```bash
  git add backend/modules/persona/__init__.py
  git commit -m "$(cat <<'EOF'
  Expose persona.bump_last_used via the module public API

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 1.4 — Unit test for `bump_last_used` (TDD-style, host-runnable)

**Purpose:** Verify the bump method updates exactly one persona's `last_used_at`, scoped to the owning user. Uses a mock collection — no MongoDB required.

**Files — Create:**
- `backend/tests/modules/persona/test_bump_last_used.py`

**Steps:**

- [ ] Create `backend/tests/modules/persona/test_bump_last_used.py` with the following content:

  ```python
  """Unit tests for PersonaRepository.bump_last_used.

  Uses a hand-rolled mock collection so the test runs on the host without
  MongoDB. Exercises the call surface that the public bump_last_used
  wraps.
  """
  from datetime import datetime, UTC

  import pytest

  from backend.modules.persona._repository import PersonaRepository


  class _MockCollection:
      def __init__(self) -> None:
          self.calls: list[tuple[dict, dict]] = []

      async def update_one(self, filter_: dict, update: dict) -> None:
          self.calls.append((filter_, update))

      async def create_index(self, *args, **kwargs) -> None:  # unused here
          pass


  @pytest.mark.asyncio
  async def test_bump_last_used_updates_correct_persona():
      mock = _MockCollection()
      repo = PersonaRepository.__new__(PersonaRepository)
      repo._collection = mock  # type: ignore[attr-defined]

      before = datetime.now(UTC)
      await repo.bump_last_used("persona-id-1", "user-id-1")
      after = datetime.now(UTC)

      assert len(mock.calls) == 1
      filter_, update = mock.calls[0]
      assert filter_ == {"_id": "persona-id-1", "user_id": "user-id-1"}
      assert "$set" in update
      assert "last_used_at" in update["$set"]
      stamp = update["$set"]["last_used_at"]
      assert before <= stamp <= after


  @pytest.mark.asyncio
  async def test_bump_last_used_swallows_no_match():
      """update_one with no matching doc must not raise — Motor returns a
      result with matched_count=0, which we ignore deliberately."""
      mock = _MockCollection()
      repo = PersonaRepository.__new__(PersonaRepository)
      repo._collection = mock  # type: ignore[attr-defined]
      await repo.bump_last_used("missing", "user-id-1")
      assert len(mock.calls) == 1
  ```

- [ ] Run the test from the repo root:

  ```bash
  cd backend && uv run pytest tests/modules/persona/test_bump_last_used.py -v
  ```

  Expected output: both tests pass; PASS lines visible; exit code 0.

- [ ] Commit:

  ```bash
  git add backend/tests/modules/persona/test_bump_last_used.py
  git commit -m "$(cat <<'EOF'
  Test PersonaRepository.bump_last_used update shape and idempotency

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 1.5 — Wire `bump_last_used` into chat.create_session

**Purpose:** The existing `POST /api/chat/sessions` endpoint already validates the persona exists; immediately after that we bump the persona LRU. Failures are logged and swallowed.

**Files — Modify:**
- `backend/modules/chat/_handlers.py`

**Steps:**

- [ ] Open `backend/modules/chat/_handlers.py`. Find the line:

  ```python
  from backend.modules.persona import get_persona as get_persona_fn
  ```

  (currently line 15). Replace it with:

  ```python
  from backend.modules.persona import get_persona as get_persona_fn
  from backend.modules.persona import bump_last_used as bump_persona_last_used
  ```

- [ ] Add a structlog import near the other imports if not already present. Check the top of the file: if no `import structlog` line exists, add one with the other top-of-file `import` statements (matching existing style).

- [ ] In `create_session` (function starting around line 40), after the `dto = ChatRepository.session_to_dto(doc)` line (currently line 62), insert:

  ```python
      try:
          await bump_persona_last_used(persona["_id"], user["sub"])
      except Exception as exc:  # pragma: no cover - logged, never raised
          import structlog
          structlog.get_logger().warning(
              "persona_last_used_bump_failed",
              persona_id=persona["_id"],
              user_id=user["sub"],
              error=str(exc),
          )
  ```

- [ ] Run `uv run python -m py_compile backend/modules/chat/_handlers.py`. Expected: no output, exit 0.

- [ ] Commit:

  ```bash
  git add backend/modules/chat/_handlers.py
  git commit -m "$(cat <<'EOF'
  Bump persona.last_used_at on chat session creation

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 1.6 — New endpoint: `POST /api/chat/sessions/{session_id}/resume`

**Purpose:** A no-content endpoint that the frontend hits when an existing chat is opened. Body-less. Looks up the session's persona and bumps `last_used_at`. Idempotent.

**Files — Modify:**
- `backend/modules/chat/_handlers.py`

**Steps:**

- [ ] Open `backend/modules/chat/_handlers.py`. Locate the `restore_session` endpoint (around line 266). Directly below the closing of `restore_session` (before the next `@router.patch` decorator), add:

  ```python
  @router.post("/sessions/{session_id}/resume", status_code=204)
  async def resume_session(
      session_id: str,
      user: dict = Depends(require_active_session),
  ):
      """Bump the session's persona last_used_at. No-op if session missing.

      Fire-and-forget from the frontend: opening any /chat/{persona}/{session}
      route hits this once. Failures are logged and never returned as 5xx
      so a sidebar-LRU error cannot break chat load.
      """
      repo = _chat_repo()
      session = await repo.get_session(session_id, user["sub"])
      if not session:
          return
      try:
          await bump_persona_last_used(session["persona_id"], user["sub"])
      except Exception as exc:  # pragma: no cover - logged, never raised
          import structlog
          structlog.get_logger().warning(
              "persona_last_used_bump_failed",
              persona_id=session["persona_id"],
              user_id=user["sub"],
              session_id=session_id,
              error=str(exc),
          )
  ```

- [ ] Run `uv run python -m py_compile backend/modules/chat/_handlers.py`. Expected: no output, exit 0.

- [ ] Commit:

  ```bash
  git add backend/modules/chat/_handlers.py
  git commit -m "$(cat <<'EOF'
  Add POST /api/chat/sessions/{id}/resume endpoint that bumps persona LRU

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 1.7 — Defensive read in `PersonaRepository.to_dto`

**Purpose:** `last_used_at` is not yet on `PersonaDto` (we deliberately defer the DTO field add — the frontend computes the sort itself from a derived field on the client; see Phase 2). But defend `to_dto` against documents missing the field by ensuring the model deserialise step still works. Verify by reading the existing `to_dto` and noting no change is needed.

**Files — Read only (no modify):**
- `backend/modules/persona/_repository.py:157` (the `to_dto` static method)

**Steps:**

- [ ] Confirm by inspection that `to_dto` does NOT currently reference `last_used_at`. Since the field has a `None` default in `PersonaDocument` and isn't projected into `PersonaDto`, no change is required here. Document this in the commit by appending the field to `PersonaDto` itself in Phase 2 (Task 2.2). This task is a no-op review checkpoint.

- [ ] No commit (no change made). Move directly to Task 1.8.

---

### Task 1.8 — Backend phase build check

**Purpose:** Verify the backend imports cleanly after the persona-module and chat-handler edits.

**Files — none (verification step).**

**Steps:**

- [ ] From the repo root, run:

  ```bash
  cd backend && uv run python -c "from backend.modules.persona import bump_last_used, PersonaRepository; from backend.modules.chat._handlers import resume_session; print('ok')"
  ```

  Expected output: `ok` on stdout.

- [ ] Run the persona unit test added in Task 1.4 once more to confirm:

  ```bash
  cd backend && uv run pytest tests/modules/persona/test_bump_last_used.py -v
  ```

  Expected: 2 passed.

- [ ] No commit; this is a verification gate. If anything fails, fix in a new task before proceeding.

---

## Phase 2 — Frontend foundation (gates, store, sort util)

### Task 2.1 — Create `featureGates.ts`

**Purpose:** Single boolean source of truth for the (currently hidden) Projects zone.

**Files — Create:**
- `frontend/src/core/config/featureGates.ts`

**Steps:**

- [ ] Create the directory if missing, then create `frontend/src/core/config/featureGates.ts` with content:

  ```ts
  /**
   * Frontend feature gates.
   *
   * Single boolean constants flipped manually when a backend feature is
   * ready to render. Intentionally simple — no env wiring, no runtime
   * fetch — because the gates are reviewed and committed alongside the
   * code that consumes them.
   */

  export const PROJECTS_ENABLED = false
  ```

- [ ] Run `cd frontend && pnpm tsc --noEmit`. Expected: no errors.

- [ ] Commit:

  ```bash
  git add frontend/src/core/config/featureGates.ts
  git commit -m "$(cat <<'EOF'
  Add featureGates module with PROJECTS_ENABLED off by default

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 2.2 — Add `last_used_at` to frontend `PersonaDto`

**Purpose:** Mirror the backend field on the client type so the LRU sort can read it. Optional, defaults to absent.

**Files — Modify:**
- `frontend/src/core/types/persona.ts`
- `shared/dtos/persona.py`

**Steps:**

- [ ] Open `shared/dtos/persona.py`. In `class PersonaDto` (starts at line 54), insert a new field after `updated_at: datetime` (line 87):

  ```python
      # Most recent chat-session creation or resume. None for personas
      # that have never been chatted with — sidebar LRU sort then falls
      # back to created_at descending. Backwards-compatible.
      last_used_at: datetime | None = None
  ```

- [ ] Open `frontend/src/core/types/persona.ts`. In `interface PersonaDto`, after `updated_at: string;` (line 57), insert:

  ```ts
    // Most recent chat-session creation or resume. Optional for backwards
    // compatibility — sidebar LRU sort falls back to created_at when missing.
    last_used_at?: string | null;
  ```

- [ ] Run `cd frontend && pnpm tsc --noEmit`. Expected: no errors.

- [ ] Run `uv run python -m py_compile shared/dtos/persona.py`. Expected: no output.

- [ ] Commit:

  ```bash
  git add shared/dtos/persona.py frontend/src/core/types/persona.ts
  git commit -m "$(cat <<'EOF'
  Surface last_used_at on PersonaDto on both backend and frontend

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 2.3 — Project `last_used_at` through `PersonaRepository.to_dto`

**Purpose:** Now that `PersonaDto` carries the field, populate it in the DTO mapper. Defends against missing-field documents per beta-safety rule.

**Files — Modify:**
- `backend/modules/persona/_repository.py`

**Steps:**

- [ ] Open `backend/modules/persona/_repository.py`. In the `to_dto` static method (starts around line 157), find the `updated_at=doc["updated_at"],` line near the end. Directly after it, add:

  ```python
              last_used_at=doc.get("last_used_at"),
  ```

- [ ] Run `uv run python -m py_compile backend/modules/persona/_repository.py`. Expected: no output.

- [ ] Commit:

  ```bash
  git add backend/modules/persona/_repository.py
  git commit -m "$(cat <<'EOF'
  Project last_used_at into PersonaDto with safe missing-field fallback

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 2.4 — Extend `sidebarStore.ts` with per-zone collapse state

**Purpose:** Add three boolean flags to control per-zone open/closed state, persisted in localStorage. Default open.

**Files — Modify:**
- `frontend/src/core/store/sidebarStore.ts`

**Steps:**

- [ ] Replace the entire content of `frontend/src/core/store/sidebarStore.ts` with:

  ```ts
  import { create } from 'zustand'
  import { safeLocalStorage } from '../utils/safeStorage'

  const COLLAPSED_KEY = 'chatsune_sidebar_collapsed'

  export type SidebarZone = 'personas' | 'projects' | 'history'

  function zoneKey(zone: SidebarZone): string {
    return `chatsune_sidebar_zone_${zone}_open`
  }

  function readZoneOpen(zone: SidebarZone): boolean {
    const raw = safeLocalStorage.getItem(zoneKey(zone))
    if (raw === null) return true
    return raw === 'true'
  }

  interface SidebarState {
    isCollapsed: boolean
    zoneOpen: Record<SidebarZone, boolean>
    toggle: () => void
    toggleZone: (zone: SidebarZone) => void
  }

  export const useSidebarStore = create<SidebarState>((set, get) => ({
    isCollapsed: safeLocalStorage.getItem(COLLAPSED_KEY) === 'true',
    zoneOpen: {
      personas: readZoneOpen('personas'),
      projects: readZoneOpen('projects'),
      history: readZoneOpen('history'),
    },
    toggle: () => {
      const next = !get().isCollapsed
      safeLocalStorage.setItem(COLLAPSED_KEY, String(next))
      set({ isCollapsed: next })
    },
    toggleZone: (zone) => {
      const cur = get().zoneOpen[zone]
      const next = !cur
      safeLocalStorage.setItem(zoneKey(zone), String(next))
      set({ zoneOpen: { ...get().zoneOpen, [zone]: next } })
    },
  }))
  ```

- [ ] Run `cd frontend && pnpm tsc --noEmit`. Expected: no errors. (The Sidebar.tsx still references the old store shape but only `isCollapsed` and `toggle`, which still exist — type-check should pass.)

- [ ] Commit:

  ```bash
  git add frontend/src/core/store/sidebarStore.ts
  git commit -m "$(cat <<'EOF'
  Extend sidebarStore with per-zone collapse state persisted in localStorage

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 2.5 — Rewrite `personaSort.ts` to LRU-first ordering (test-first)

**Purpose:** Change `sortPersonas` from a stable pinned/unpinned partition into LRU-first ordering: pinned-then-unpinned, each subset sorted by `last_used_at ?? created_at` descending.

**Files — Create:**
- `frontend/src/app/components/sidebar/personaSort.test.ts`
**Files — Modify:**
- `frontend/src/app/components/sidebar/personaSort.ts`

**Steps:**

- [ ] Create `frontend/src/app/components/sidebar/personaSort.test.ts` with:

  ```ts
  import { describe, it, expect } from 'vitest'
  import { sortPersonas } from './personaSort'
  import type { PersonaDto } from '../../../core/types/persona'

  function persona(
    id: string,
    overrides: Partial<PersonaDto> = {},
  ): PersonaDto {
    return {
      id,
      user_id: 'u',
      name: id,
      tagline: '',
      model_unique_id: null,
      system_prompt: '',
      temperature: 0.8,
      reasoning_enabled: false,
      soft_cot_enabled: false,
      vision_fallback_model: null,
      nsfw: false,
      use_memory: true,
      colour_scheme: 'solar',
      display_order: 0,
      monogram: id.slice(0, 1).toUpperCase(),
      pinned: false,
      profile_image: null,
      profile_crop: null,
      mcp_config: null,
      integrations_config: null,
      created_at: '2025-01-01T00:00:00Z',
      updated_at: '2025-01-01T00:00:00Z',
      ...overrides,
    }
  }

  describe('sortPersonas', () => {
    it('places pinned personas before unpinned regardless of LRU', () => {
      const list = [
        persona('a', { pinned: false, last_used_at: '2025-12-01T00:00:00Z' }),
        persona('b', { pinned: true, last_used_at: '2025-01-01T00:00:00Z' }),
      ]
      const out = sortPersonas(list)
      expect(out.map((p) => p.id)).toEqual(['b', 'a'])
    })

    it('orders within pinned by last_used_at descending', () => {
      const list = [
        persona('old', { pinned: true, last_used_at: '2025-01-01T00:00:00Z' }),
        persona('new', { pinned: true, last_used_at: '2025-06-01T00:00:00Z' }),
      ]
      const out = sortPersonas(list)
      expect(out.map((p) => p.id)).toEqual(['new', 'old'])
    })

    it('orders within unpinned by last_used_at descending', () => {
      const list = [
        persona('older', { last_used_at: '2025-01-01T00:00:00Z' }),
        persona('newer', { last_used_at: '2025-06-01T00:00:00Z' }),
      ]
      const out = sortPersonas(list)
      expect(out.map((p) => p.id)).toEqual(['newer', 'older'])
    })

    it('falls back to created_at descending when last_used_at missing', () => {
      const list = [
        persona('older', { created_at: '2025-01-01T00:00:00Z' }),
        persona('newer', { created_at: '2025-06-01T00:00:00Z' }),
      ]
      const out = sortPersonas(list)
      expect(out.map((p) => p.id)).toEqual(['newer', 'older'])
    })

    it('places brand-new personas (no last_used_at) above older-used ones', () => {
      const list = [
        persona('used', {
          last_used_at: '2025-01-01T00:00:00Z',
          created_at: '2024-01-01T00:00:00Z',
        }),
        persona('brandnew', {
          last_used_at: null,
          created_at: '2025-12-31T00:00:00Z',
        }),
      ]
      const out = sortPersonas(list)
      expect(out.map((p) => p.id)).toEqual(['brandnew', 'used'])
    })
  })
  ```

- [ ] Run `cd frontend && pnpm vitest run src/app/components/sidebar/personaSort.test.ts`. Expected: tests fail (existing implementation is partition-only). Note the failure output, then proceed to update the implementation.

- [ ] Replace `frontend/src/app/components/sidebar/personaSort.ts` with:

  ```ts
  import type { PersonaDto } from '../../../core/types/persona'

  function sortKey(p: PersonaDto): number {
    // None → fall back to created_at so brand-new personas surface at top.
    const stamp = p.last_used_at ?? p.created_at
    return stamp ? Date.parse(stamp) : 0
  }

  /**
   * Pinned-first, LRU within each group.
   *
   * Sort key per persona is `last_used_at ?? created_at` (descending), so a
   * persona that was just created but never chatted with appears at the top
   * of the unpinned list.
   */
  export function sortPersonas(list: PersonaDto[]): PersonaDto[] {
    const pinned: PersonaDto[] = []
    const unpinned: PersonaDto[] = []
    for (const p of list) {
      if (p.pinned) pinned.push(p)
      else unpinned.push(p)
    }
    pinned.sort((a, b) => sortKey(b) - sortKey(a))
    unpinned.sort((a, b) => sortKey(b) - sortKey(a))
    return [...pinned, ...unpinned]
  }
  ```

- [ ] Run `cd frontend && pnpm vitest run src/app/components/sidebar/personaSort.test.ts`. Expected: 5 passed.

- [ ] Run `cd frontend && pnpm tsc --noEmit`. Expected: no errors.

- [ ] Commit:

  ```bash
  git add frontend/src/app/components/sidebar/personaSort.ts frontend/src/app/components/sidebar/personaSort.test.ts
  git commit -m "$(cat <<'EOF'
  Switch sortPersonas to LRU-first ordering with created_at fallback

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 2.6 — `My data` last-subpage memory util

**Purpose:** Tiny module reading/writing the `chatsune_my_data_last_subpage` localStorage key. Default `'uploads'`.

**Files — Create:**
- `frontend/src/app/components/user-modal/myDataMemory.ts`

**Steps:**

- [ ] Create `frontend/src/app/components/user-modal/myDataMemory.ts`:

  ```ts
  import { safeLocalStorage } from '../../../core/utils/safeStorage'

  const KEY = 'chatsune_my_data_last_subpage'

  export type MyDataSubpage = 'uploads' | 'artefacts' | 'images'

  const VALID: ReadonlyArray<MyDataSubpage> = ['uploads', 'artefacts', 'images']

  export function getLastMyDataSubpage(): MyDataSubpage {
    const raw = safeLocalStorage.getItem(KEY)
    if (raw && (VALID as ReadonlyArray<string>).includes(raw)) {
      return raw as MyDataSubpage
    }
    return 'uploads'
  }

  export function setLastMyDataSubpage(sub: MyDataSubpage): void {
    safeLocalStorage.setItem(KEY, sub)
  }
  ```

- [ ] Run `cd frontend && pnpm tsc --noEmit`. Expected: no errors.

- [ ] Commit:

  ```bash
  git add frontend/src/app/components/user-modal/myDataMemory.ts
  git commit -m "$(cat <<'EOF'
  Add localStorage helper for the My data sub-page memory

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 2.7 — `chatApi.resumeSession` client method + fire on chat load

**Purpose:** Add the client call to `POST /api/chat/sessions/{id}/resume` and invoke it once when the session-load effect runs in `ChatView`.

**Files — Modify:**
- `frontend/src/core/api/chat.ts`
- `frontend/src/features/chat/ChatView.tsx`

**Steps:**

- [ ] Open `frontend/src/core/api/chat.ts`. Find the `restoreSession` line (currently around line 204–205). Directly after it, insert a new method on the `chatApi` object:

  ```ts
    resumeSession: (sessionId: string) =>
      api.post<void>(`/api/chat/sessions/${sessionId}/resume`),
  ```

- [ ] Open `frontend/src/features/chat/ChatView.tsx`. Locate the session-load `useEffect` that begins with `const store = useChatStore.getState()` and `store.reset(effectiveSessionId)` (around line 320). Inside the effect, after the `if (!sessionId) return () => { cancelled = true }` line (around line 333) and before `setIsLoading(true)`, insert:

  ```tsx
      // Bump persona LRU on resume. Fire-and-forget — failures must not
      // block message load. Idempotent on the backend.
      chatApi.resumeSession(sessionId).catch((err) => {
        console.warn('Persona LRU bump on resume failed', err)
      })
  ```

- [ ] Run `cd frontend && pnpm tsc --noEmit`. Expected: no errors.

- [ ] Commit:

  ```bash
  git add frontend/src/core/api/chat.ts frontend/src/features/chat/ChatView.tsx
  git commit -m "$(cat <<'EOF'
  Fire chatApi.resumeSession on chat load to bump persona LRU

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 2.8 — Phase 2 build verification

**Purpose:** Run the full frontend build to catch stricter `tsc -b` errors before moving on.

**Steps:**

- [ ] Run `cd frontend && pnpm run build`. Expected: build completes; no TypeScript errors; vite emits a `dist/` summary.

- [ ] No commit. If the build fails, fix in a follow-up task before proceeding.

---

## Phase 3 — Pinned indicator (gold stripe)

### Task 3.1 — Add `pinnedStripe` Tailwind utility

**Purpose:** Centralise the gold-stripe class so PersonaItem, HistoryItem, and PersonasTab can apply it identically.

**Files — Create:**
- `frontend/src/app/components/sidebar/pinnedStripe.ts`

**Steps:**

- [ ] Create `frontend/src/app/components/sidebar/pinnedStripe.ts`:

  ```ts
  /**
   * Visual treatment for pinned rows across sidebar zones and the
   * Personas-tab grid. A 3-px gold left border plus a barely-perceptible
   * warm tint. Padding compensates for the border so text aligns with
   * unpinned rows (subtract 3px from left padding at the call site).
   *
   * Per spec §2: this stripe replaces the legacy "Pinned" sub-headers and
   * per-row star icons.
   */
  export const PINNED_STRIPE_STYLE: React.CSSProperties = {
    borderLeft: '3px solid rgba(212, 175, 55, 0.85)',
    background: 'rgba(212, 175, 55, 0.03)',
  }
  ```

  Note: the file uses `React.CSSProperties` so add this import at the top:

  ```ts
  import type React from 'react'
  ```

  Final file content:

  ```ts
  import type React from 'react'

  /**
   * Visual treatment for pinned rows across sidebar zones and the
   * Personas-tab grid. A 3-px gold left border plus a barely-perceptible
   * warm tint. Padding compensates for the border so text aligns with
   * unpinned rows (subtract 3px from left padding at the call site).
   *
   * Per spec §2: this stripe replaces the legacy "Pinned" sub-headers and
   * per-row star icons.
   */
  export const PINNED_STRIPE_STYLE: React.CSSProperties = {
    borderLeft: '3px solid rgba(212, 175, 55, 0.85)',
    background: 'rgba(212, 175, 55, 0.03)',
  }
  ```

- [ ] Run `cd frontend && pnpm tsc --noEmit`. Expected: no errors.

- [ ] Commit:

  ```bash
  git add frontend/src/app/components/sidebar/pinnedStripe.ts
  git commit -m "$(cat <<'EOF'
  Add PINNED_STRIPE_STYLE shared style for pinned rows

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 3.2 — Apply gold stripe to `PersonaItem`

**Purpose:** Render the stripe on a pinned persona row in the sidebar; remove the old menu-driven Pin/Unpin context entries are kept (they still work).

**Files — Modify:**
- `frontend/src/app/components/sidebar/PersonaItem.tsx`

**Steps:**

- [ ] Open `frontend/src/app/components/sidebar/PersonaItem.tsx`. At the top, add the import:

  ```ts
  import { PINNED_STRIPE_STYLE } from './pinnedStripe'
  ```

- [ ] Locate the outer `<div ref={dragRef} className={...} ... onClick={...}>` (currently around line 88). Replace it with:

  ```tsx
      <div
        ref={dragRef}
        className={`group relative mx-1.5 flex cursor-pointer items-center gap-2 rounded-lg py-1.5 transition-colors
          ${isActive ? "bg-white/8" : "hover:bg-white/5"}
          ${isDragging ? "opacity-40" : ""}`}
        style={persona.pinned ? { ...PINNED_STRIPE_STYLE, paddingLeft: '5px', paddingRight: '8px' } : { paddingLeft: '8px', paddingRight: '8px' }}
        onClick={() => onSelect(persona)}
      >
  ```

  Rationale: original was `px-2 py-1.5` (8px horizontal). Pinned variant subtracts 3px on the left to compensate for the 3-px border so the monogram x-position is unchanged.

- [ ] Run `cd frontend && pnpm tsc --noEmit`. Expected: no errors.

- [ ] Commit:

  ```bash
  git add frontend/src/app/components/sidebar/PersonaItem.tsx
  git commit -m "$(cat <<'EOF'
  Apply gold-stripe pinned indicator to PersonaItem in the sidebar

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 3.3 — Apply gold stripe to `HistoryItem`

**Purpose:** Same stripe treatment for pinned chat-session rows.

**Files — Modify:**
- `frontend/src/app/components/sidebar/HistoryItem.tsx`

**Steps:**

- [ ] Open `frontend/src/app/components/sidebar/HistoryItem.tsx`. At the top, add:

  ```ts
  import { PINNED_STRIPE_STYLE } from './pinnedStripe'
  ```

- [ ] Find the outer `<div className={...} onClick={...}>` (currently line 58). Replace with:

  ```tsx
      <div
        className={`group relative mx-1.5 flex cursor-pointer items-center gap-2 rounded-lg py-1 text-[12px] transition-colors
          ${isActive ? "bg-white/6 text-white/80" : "text-white/28 hover:bg-white/4 hover:text-white/55"}
          ${isDragging ? "opacity-40" : ""}`}
        style={isPinned ? { ...PINNED_STRIPE_STYLE, paddingLeft: '5px', paddingRight: '8px' } : { paddingLeft: '8px', paddingRight: '8px' }}
        onClick={() => onClick(session)}
      >
  ```

- [ ] Run `cd frontend && pnpm tsc --noEmit`. Expected: no errors.

- [ ] Commit:

  ```bash
  git add frontend/src/app/components/sidebar/HistoryItem.tsx
  git commit -m "$(cat <<'EOF'
  Apply gold-stripe pinned indicator to HistoryItem in the sidebar

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 3.4 — Phase 3 build verification

**Steps:**

- [ ] Run `cd frontend && pnpm run build`. Expected: success.

---

## Phase 4 — Drag-and-drop removal

### Task 4.1 — Remove drag UI from `PersonaItem`

**Purpose:** Drop the `dragRef`, `dragListeners`, `dragAttributes`, `isDragging` props from `PersonaItem` and remove the grip handle.

**Files — Modify:**
- `frontend/src/app/components/sidebar/PersonaItem.tsx`

**Steps:**

- [ ] Open `frontend/src/app/components/sidebar/PersonaItem.tsx`. Remove the import line:

  ```ts
  import type { DraggableAttributes, DraggableSyntheticListeners } from "@dnd-kit/core"
  ```

- [ ] Remove the four drag-related fields from `PersonaItemProps`:

  ```ts
    dragRef?: (node: HTMLElement | null) => void
    dragListeners?: DraggableSyntheticListeners
    dragAttributes?: DraggableAttributes
    isDragging?: boolean
  ```

- [ ] Remove the same names from the destructured function arguments at the top of `PersonaItem`.

- [ ] Replace the outer `<div ref={dragRef} ... className={...} style={...} onClick={...}>` block to remove `ref={dragRef}` and the `${isDragging ? "opacity-40" : ""}` class fragment. The opening `<div>` becomes:

  ```tsx
      <div
        className={`group relative mx-1.5 flex cursor-pointer items-center gap-2 rounded-lg py-1.5 transition-colors
          ${isActive ? "bg-white/8" : "hover:bg-white/5"}`}
        style={persona.pinned ? { ...PINNED_STRIPE_STYLE, paddingLeft: '5px', paddingRight: '8px' } : { paddingLeft: '8px', paddingRight: '8px' }}
        onClick={() => onSelect(persona)}
      >
  ```

- [ ] Delete the entire `<span aria-label="Drag to reorder" ... >⠿</span>` block (the grip handle).

- [ ] Run `cd frontend && pnpm tsc --noEmit`. Expected: errors will appear in `Sidebar.tsx` because `SortablePersonaItem` still passes `dragRef` etc. Those fix in Task 4.4. The current task's compile failure is expected; do NOT try to fix `Sidebar.tsx` here.

- [ ] Commit (compile-fail-but-on-purpose; this is a milestone commit):

  ```bash
  git add frontend/src/app/components/sidebar/PersonaItem.tsx
  git commit -m "$(cat <<'EOF'
  Drop drag props and grip handle from PersonaItem

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 4.2 — Remove drag UI from `HistoryItem`

**Purpose:** Same surgery on `HistoryItem`.

**Files — Modify:**
- `frontend/src/app/components/sidebar/HistoryItem.tsx`

**Steps:**

- [ ] Open `frontend/src/app/components/sidebar/HistoryItem.tsx`. Remove the import:

  ```ts
  import type { DraggableAttributes, DraggableSyntheticListeners } from "@dnd-kit/core"
  ```

- [ ] Remove these three props from `HistoryItemProps` and from the destructured argument list:

  ```ts
    dragListeners?: DraggableSyntheticListeners
    dragAttributes?: DraggableAttributes
    isDragging?: boolean
  ```

- [ ] In the JSX body, delete the entire `{dragListeners && (...)}` block that renders the `⠿` grip span. Remove `${isDragging ? "opacity-40" : ""}` from the outer div's className.

- [ ] Run `cd frontend && pnpm tsc --noEmit`. Expected: errors in `Sidebar.tsx`; this is fine, fixed in Task 4.4.

- [ ] Commit:

  ```bash
  git add frontend/src/app/components/sidebar/HistoryItem.tsx
  git commit -m "$(cat <<'EOF'
  Drop drag props and grip handle from HistoryItem

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 4.3 — Strip drag-and-drop from `PersonasTab`

**Purpose:** Remove `DndContext`, `SortableContext`, `useSortable`, `arrayMove`, the `__personasTabTestHelper` test seam, and the persona reorder handler. Pinning still works via the existing pin button on each row.

**Files — Modify:**
- `frontend/src/app/components/user-modal/PersonasTab.tsx`

**Steps:**

- [ ] Replace the entire content of `frontend/src/app/components/user-modal/PersonasTab.tsx` with:

  ```tsx
  import { useMemo } from 'react'
  import { usePersonas } from '../../../core/hooks/usePersonas'
  import { useSanitisedMode } from '../../../core/store/sanitisedModeStore'
  import { CHAKRA_PALETTE } from '../../../core/types/chakra'
  import { CroppedAvatar } from '../avatar-crop/CroppedAvatar'
  import type { PersonaDto } from '../../../core/types/persona'
  import { sortPersonas } from '../sidebar/personaSort'
  import { PINNED_STRIPE_STYLE } from '../sidebar/pinnedStripe'

  interface PersonasTabProps {
    onOpenPersonaOverlay: (personaId: string) => void
    onCreatePersona: () => void
  }

  export function PersonasTab({ onOpenPersonaOverlay, onCreatePersona }: PersonasTabProps) {
    const { personas, update } = usePersonas()
    const isSanitised = useSanitisedMode((s) => s.isSanitised)

    const visible = useMemo(() => {
      const filtered = isSanitised ? personas.filter((p) => !p.nsfw) : personas
      return sortPersonas(filtered)
    }, [personas, isSanitised])

    return (
      <div className="flex h-full flex-col">
        {/* Top bar with create button */}
        <div className="flex flex-shrink-0 items-center justify-end px-4 pt-4 pb-2">
          <button
            type="button"
            onClick={onCreatePersona}
            className="rounded-md border border-white/10 px-2.5 py-1 text-[12px] font-medium text-white/70 transition-colors hover:bg-white/6 hover:text-white/90"
            aria-label="Create persona"
            title="Create persona"
          >
            + Create persona
          </button>
        </div>

        {/* Scrollable list */}
        <div className="flex-1 overflow-y-auto px-4 pb-4 [&::-webkit-scrollbar]:w-[3px] [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10">
          <div className="flex flex-col gap-2">
            {visible.map((persona) => (
              <PersonaRow
                key={persona.id}
                persona={persona}
                onOpen={() => onOpenPersonaOverlay(persona.id)}
                onTogglePin={() => update(persona.id, { pinned: !persona.pinned })}
              />
            ))}
          </div>
        </div>
      </div>
    )
  }

  interface PersonaRowProps {
    persona: PersonaDto
    onOpen: () => void
    onTogglePin: () => void
  }

  function PersonaRow({ persona, onOpen, onTogglePin }: PersonaRowProps) {
    const chakra = CHAKRA_PALETTE[persona.colour_scheme]
    const modelLabel = persona.model_unique_id ? persona.model_unique_id.split(':').slice(1).join(':') : 'no model'

    const baseStyle: React.CSSProperties = {
      border: `1px solid ${chakra.hex}22`,
    }
    const style: React.CSSProperties = persona.pinned
      ? { ...baseStyle, ...PINNED_STRIPE_STYLE }
      : baseStyle

    return (
      <div
        data-testid="persona-row"
        data-persona-id={persona.id}
        className="relative flex items-center gap-3 rounded-lg px-3 py-2 transition-colors hover:bg-white/5"
        style={style}
      >
        <div
          className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full"
          style={{ background: `${chakra.hex}22`, border: `1px solid ${chakra.hex}55` }}
        >
          {persona.profile_image ? (
            <CroppedAvatar
              personaId={persona.id}
              updatedAt={persona.updated_at}
              crop={persona.profile_crop}
              size={28}
              alt={persona.name}
            />
          ) : (
            <span className="text-[11px] font-semibold" style={{ color: chakra.hex }}>
              {persona.monogram}
            </span>
          )}
        </div>

        <button
          type="button"
          data-testid="persona-row-body"
          onClick={onOpen}
          className="flex min-w-0 flex-1 flex-col items-start bg-transparent border-none p-0 text-left cursor-pointer"
        >
          <span className="truncate text-[13px] font-medium text-white/90">{persona.name}</span>
          {persona.tagline && (
            <span className="truncate text-[11px] text-white/45">{persona.tagline}</span>
          )}
          <span
            className="truncate font-mono text-[10px]"
            style={{ color: chakra.hex + '4d', letterSpacing: '0.5px' }}
          >
            {modelLabel}
          </span>
        </button>

        {persona.nsfw && (
          <span
            data-testid="persona-nsfw-indicator"
            className="absolute top-1 right-1 text-[10px] leading-none"
            aria-label="NSFW"
            title="NSFW"
          >
            💋
          </span>
        )}

        <button
          type="button"
          data-testid="persona-pin-toggle"
          onClick={(e) => {
            e.stopPropagation()
            onTogglePin()
          }}
          className="rounded p-1 transition-colors"
          style={{
            color: persona.pinned ? chakra.hex : 'rgba(255,255,255,0.2)',
            background: persona.pinned ? chakra.hex + '1a' : 'transparent',
          }}
          aria-label={persona.pinned ? 'Unpin' : 'Pin'}
          title={persona.pinned ? 'Unpin' : 'Pin'}
        >
          📌
        </button>
      </div>
    )
  }
  ```

- [ ] Run `cd frontend && pnpm tsc --noEmit`. Expected: errors in `UserModal.tsx` because the new `onCreatePersona` prop is missing at the call site. That is fixed in Phase 6 (Task 6.2). For now: errors in `Sidebar.tsx` and `UserModal.tsx` are expected. (You can confirm by skimming the failure list — the changes are intentional.)

- [ ] Commit:

  ```bash
  git add frontend/src/app/components/user-modal/PersonasTab.tsx
  git commit -m "$(cat <<'EOF'
  Remove drag-and-drop from PersonasTab and add Create-persona top button

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 4.4 — Strip drag-and-drop from `Sidebar.tsx` (interim)

**Purpose:** Replace the dnd-kit imports and the `SortablePersonaItem` / `DraggableHistoryItem` / `DroppableZone` wrappers with plain renders, so the file compiles. Full decomposition happens in Phase 5; this task only cleans up the dnd-kit usage so the build is green at the end of Phase 4.

**Files — Modify:**
- `frontend/src/app/components/sidebar/Sidebar.tsx`

**Steps:**

- [ ] Open `frontend/src/app/components/sidebar/Sidebar.tsx`. Remove the imports at the top:

  ```ts
  import {
    DndContext,
    DragOverlay,
    useDroppable,
    useDraggable,
    type DragEndEvent,
    type DragStartEvent,
    pointerWithin,
  } from "@dnd-kit/core"
  import { SortableContext, verticalListSortingStrategy, useSortable, arrayMove } from "@dnd-kit/sortable"
  import { CSS } from "@dnd-kit/utilities"
  ```

- [ ] Remove the imports of `useDndSensors`, `hapticLongPress`, `zoomModifiers`:

  ```ts
  import { hapticLongPress } from "../../../core/utils/haptics"
  import { useDndSensors } from "../../../core/hooks/useDndSensors"
  import { zoomModifiers } from "../../../core/utils/dndZoomModifier"
  ```

- [ ] Delete the entire `DroppableZone` function definition.
- [ ] Delete the entire `SortablePersonaItem` function definition.
- [ ] Delete the entire `DraggableHistoryItem` function definition.

- [ ] Remove the `onReorder?: (orderedIds: string[]) => void` line from `SidebarProps`.

- [ ] Remove `onReorder` from the destructured `Sidebar` parameter list.

- [ ] Delete the state and handlers used only for drag:
  - `const [dragActiveId, setDragActiveId] = useState<string | null>(null)` and the corresponding history one.
  - `findZone`, `handleDragStart`, `handleDragEnd`, `handleHistoryDragStart`, `handleHistoryDragEnd`, `dragActivePersona`, `historyDragActiveSession`.
  - `const dndSensors = useDndSensors()`.

- [ ] Replace every `<SortablePersonaItem ... />` with `<PersonaItem ... />` (drop the drag-related props that no longer exist on `PersonaItem`).

- [ ] Replace every `<DraggableHistoryItem ... />` with `<HistoryItem ... />`.

- [ ] Remove every `<DndContext>` / `</DndContext>`, `<SortableContext>` / `</SortableContext>`, `<DroppableZone id="..." ...>` / `</DroppableZone>`, and `<DragOverlay>` / `</DragOverlay>` JSX wrapper. Keep their children inline.

- [ ] Find every callsite that passes `onReorder={...}` to `<Sidebar ...>` (in `frontend/src/app/AppLayout.tsx` and possibly other consumers). Run:

  ```bash
  grep -rn "onReorder=" frontend/src
  ```

  For each match in `Sidebar` callers, delete the `onReorder={...}` prop and any helper that only existed to feed it.

- [ ] Run `cd frontend && pnpm tsc --noEmit`. Expected: errors only from the still-pending `PersonasTab` `onCreatePersona` prop. If sidebar-related compile errors persist, address them inline before committing.

- [ ] Commit:

  ```bash
  git add frontend/src/app/components/sidebar/Sidebar.tsx frontend/src/app
  git commit -m "$(cat <<'EOF'
  Strip dnd-kit usage and wrappers from Sidebar.tsx

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 4.5 — Audit other `@dnd-kit` consumers and decide

**Purpose:** Per spec §3.4, `@dnd-kit/*` packages must not ship in the post-redesign build. Confirm what consumers remain and migrate them.

**Files — Read only (audit):**
- `frontend/src/core/utils/dndZoomModifier.ts`
- `frontend/src/core/hooks/useDndSensors.ts`
- `frontend/src/app/components/persona-card/PersonaCard.tsx`
- `frontend/src/app/components/user-modal/BookmarksTab.tsx`
- `frontend/src/features/chat/ChatBookmarkList.tsx`
- `frontend/src/app/pages/PersonasPage.tsx`

**Steps:**

- [ ] Run:

  ```bash
  grep -rn "@dnd-kit" frontend/src
  ```

  Confirm the remaining consumers are the six files listed above.

- [ ] No code changes; this task only sets up the next four tasks. **Important:** the spec is explicit that `@dnd-kit/*` packages must be removed and the spec also explicitly preserves Bookmarks-feature behaviour (Non-Goals). The plan resolves the conflict by replacing Bookmarks drag-reorder with up/down arrow buttons (Tasks 4.7 and 4.8).

- [ ] No commit.

---

### Task 4.6 — Remove drag from `PersonasPage` and `PersonaCard`

**Purpose:** Per spec §3.3 the frontend no longer reads `display_order`, so the manual drag-reorder on the personas page is obsolete.

**Files — Modify:**
- `frontend/src/app/pages/PersonasPage.tsx`
- `frontend/src/app/components/persona-card/PersonaCard.tsx`

**Steps:**

- [ ] Open `frontend/src/app/pages/PersonasPage.tsx`. Remove the imports:

  ```ts
  import {
    closestCenter,
    DndContext,
    DragOverlay,
    type DragEndEvent,
    type DragStartEvent,
  } from "@dnd-kit/core"
  import { zoomModifiers } from "../../core/utils/dndZoomModifier"
  import { hapticLongPress } from "../../core/utils/haptics"
  import { rectSortingStrategy, SortableContext } from "@dnd-kit/sortable"
  import { useDndSensors } from "../../core/hooks/useDndSensors"
  ```

  Keep the other imports.

- [ ] Remove `reorder` from the destructured `usePersonas()` result:

  ```ts
  const { personas, update } = usePersonas()
  ```

- [ ] Delete the `activeId` state, `dndSensors`, `activePersona`, `handleDragStart`, and `handleDragEnd` blocks.

- [ ] Replace the JSX block that begins `<DndContext sensors={dndSensors} ...>` and ends `</DndContext>` with a plain wrapper:

  ```tsx
        <div
          className="flex flex-wrap justify-center gap-4 sm:gap-6"
          style={{ maxWidth: "1200px", margin: "0 auto" }}
        >
          {filtered.map((persona, index) => (
            <PersonaCard
              key={persona.id}
              persona={persona}
              index={index}
              onContinue={handleContinue}
              onNewChat={handleNewChat}
              onOpenOverlay={handleOpenOverlay}
              onTogglePin={handleTogglePin}
            />
          ))}
          <div className="relative">
            <AddPersonaCard onClick={() => setMenuOpen((v) => !v)} index={filtered.length} />
            {menuOpen && (
              <AddPersonaMenu
                onCreateNew={handleCreateNew}
                onImport={handleImportClick}
                onClose={() => setMenuOpen(false)}
              />
            )}
          </div>
        </div>
  ```

- [ ] Open `frontend/src/app/components/persona-card/PersonaCard.tsx`. Remove imports:

  ```ts
  import { useSortable } from "@dnd-kit/sortable";
  import { CSS } from "@dnd-kit/utilities";
  ```

- [ ] Remove the `useSortable` hook block:

  ```ts
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: persona.id });
  ```

- [ ] In `cardStyle`, drop the `transform`, `transition`, and `opacity` lines (and the `CSS.Transform.toString(...)` reference).

- [ ] On the outer card `<div>`, drop `ref={setNodeRef}` and `{...attributes}`.

- [ ] Delete the entire "Drag handle" `<div role="button" aria-label={`Drag to reorder...`} ...>{...}</div>` block including its three dot rows.

- [ ] Run `cd frontend && pnpm tsc --noEmit`. Expected: still failing on `PersonasTab` only (Phase 6 cleanup). No new errors should be introduced.

- [ ] Commit:

  ```bash
  git add frontend/src/app/pages/PersonasPage.tsx frontend/src/app/components/persona-card/PersonaCard.tsx
  git commit -m "$(cat <<'EOF'
  Remove drag-reorder from PersonasPage and PersonaCard

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 4.7 — Convert `BookmarksTab` to natural ordering (no manual sort)

**Purpose:** Drag-reorder is removed everywhere in the app per the spec. Bookmarks switch to natural ordering: sort by `created_at` descending (newest first). No replacement reorder UI — no arrow buttons, no menu actions. Frontend stops calling `bookmarksApi.reorder`. The backend endpoint stays operational but unused (deprecation is a separate follow-up).

**Files — Modify:**
- `frontend/src/app/components/user-modal/BookmarksTab.tsx`

**Steps:**

- [ ] Open `frontend/src/app/components/user-modal/BookmarksTab.tsx`. Remove the imports:

  ```ts
  import {
    DndContext,
    closestCenter,
    type DragEndEvent,
    type DragStartEvent,
  } from '@dnd-kit/core'
  import { SortableContext, verticalListSortingStrategy, useSortable, arrayMove } from '@dnd-kit/sortable'
  import { CSS } from '@dnd-kit/utilities'
  ```

  Also drop any dnd-kit-only sibling imports used solely for this feature: `useDndSensors`, `zoomModifiers`, etc. Re-read the file to confirm.

- [ ] Delete the `handleDragEnd` handler entirely. Delete any local state used only for drag (e.g., `dragActiveId`).

- [ ] Replace the displayed list source with a sort by `created_at` descending. Find the existing line that yields the rows being rendered (likely a `filtered` array or similar from a `useMemo`) and ensure it ends with:

  ```ts
  .slice().sort((a, b) => {
    const aTs = new Date(a.created_at).getTime()
    const bTs = new Date(b.created_at).getTime()
    return bTs - aTs
  })
  ```

  If the field is named differently in the bookmark DTO (e.g., `createdAt`), adapt to the actual name. Verify by reading `frontend/src/core/types/` for the bookmark type.

- [ ] Replace the `<DndContext>...<SortableContext>...</SortableContext></DndContext>` wrapper with a plain `.map(...)` over the sorted list. For each row, render the existing UI **without** the drag handle and **without** any replacement reorder control.

- [ ] Delete the `SortableBookmarkRow` wrapper component and inline its inner `BookmarkRow` rendering directly into the `.map(...)` callback.

- [ ] Remove any call to `bookmarksApi.reorder(...)` from this file. Do NOT remove the function from `bookmarksApi.ts` — leaving it allows the backend endpoint to remain reachable for any future need.

- [ ] Run `cd frontend && pnpm tsc --noEmit`. Expected: no errors from BookmarksTab.

- [ ] Commit:

  ```bash
  git add frontend/src/app/components/user-modal/BookmarksTab.tsx
  git commit -m "$(cat <<'EOF'
  Drop drag-reorder from BookmarksTab; sort by created_at descending

  Drag is removed everywhere in the app per the sidebar redesign spec;
  bookmarks switch to natural ordering with no replacement reorder UI.
  The bookmarksApi.reorder client call is gone; the backend endpoint
  remains for now and will be deprecated separately.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 4.8 — Convert `ChatBookmarkList` to natural ordering (no manual sort)

**Purpose:** Same removal-of-drag for the in-chat bookmark list popover. Bookmarks here sort by their position in the chat — the existing message-timestamp / message-index already provides a meaningful natural order. No replacement reorder UI.

**Files — Modify:**
- `frontend/src/features/chat/ChatBookmarkList.tsx`

**Steps:**

- [ ] Open `frontend/src/features/chat/ChatBookmarkList.tsx`. Remove the dnd-kit imports identical to Task 4.7. Remove `useDndSensors`, `zoomModifiers`, etc. if used only for drag.

- [ ] Delete `handleDragStart`, `handleDragEnd`, and any drag-only local state.

- [ ] Replace the existing source list with a sort by chat-message position. Bookmarks here reference a chat message — the list field exposing message order is likely `message_index`, `message_position`, `created_at`, or similar. Read the bookmark type and pick the field that reflects chronological position in the chat. Add:

  ```ts
  .slice().sort((a, b) => {
    // ascending: oldest at top, newest at bottom — matches reading order
    return a.message_index - b.message_index
  })
  ```

  Adapt the field name to whatever the bookmark DTO actually exposes. If only `created_at` is available on the bookmark object, sort by that ascending.

- [ ] Replace the `<DndContext>`/`<SortableContext>` wrappers with a plain `.map(...)` rendering. Each row renders **without** the drag handle and **without** any replacement reorder control.

- [ ] Delete the `SortableBookmarkRow` wrapper and inline its child component.

- [ ] Remove any call to `bookmarksApi.reorder(...)` from this file.

- [ ] Run `cd frontend && pnpm tsc --noEmit`. Expected: no errors from ChatBookmarkList.

- [ ] Commit:

  ```bash
  git add frontend/src/features/chat/ChatBookmarkList.tsx
  git commit -m "$(cat <<'EOF'
  Drop drag-reorder from ChatBookmarkList; sort chronologically

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 4.9 — Delete `useDndSensors` hook and `dndZoomModifier` util

**Purpose:** With no consumers left, remove the helpers and the dnd-kit packages from `package.json`.

**Files — Delete:**
- `frontend/src/core/hooks/useDndSensors.ts`
- `frontend/src/core/utils/dndZoomModifier.ts`
**Files — Modify:**
- `frontend/package.json`

**Steps:**

- [ ] Confirm zero remaining consumers:

  ```bash
  grep -rn "@dnd-kit\|useDndSensors\|dndZoomModifier\|zoomModifiers" frontend/src
  ```

  Expected output: no matches (apart from possibly the files about to be deleted).

- [ ] Delete `frontend/src/core/hooks/useDndSensors.ts`.

- [ ] Delete `frontend/src/core/utils/dndZoomModifier.ts`.

- [ ] Open `frontend/package.json`. Remove these three lines from the `dependencies` block:

  ```json
      "@dnd-kit/core": "^6.3.1",
      "@dnd-kit/sortable": "^10.0.0",
      "@dnd-kit/utilities": "^3.2.2",
  ```

- [ ] Run `cd frontend && pnpm install`. Expected: lockfile updates; no errors.

- [ ] Run `cd frontend && pnpm run build`. Expected: full build succeeds (PersonasTab still has the missing `onCreatePersona` callsite issue — fix it by passing a stub temporarily if needed, OR delay this build step until after Phase 6 by running `pnpm tsc --noEmit` and accepting the known pending error in `UserModal.tsx`). If the build fails ONLY on the `onCreatePersona` prop, commit anyway and rely on Phase 6 to land the green build.

- [ ] Commit:

  ```bash
  git add frontend/package.json frontend/pnpm-lock.yaml frontend/src/core/hooks/useDndSensors.ts frontend/src/core/utils/dndZoomModifier.ts
  git commit -m "$(cat <<'EOF'
  Remove @dnd-kit packages and unused dnd helpers

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

  Note: the deleted files appear under `git rm` semantically; `git add` of the parent paths after deletion stages the removal correctly. Verify with `git status` before committing.

---

## Phase 5 — Sidebar decomposition and new structure

### Task 5.1 — Create `ZoneSection` component

**Purpose:** A reusable collapsible zone component used by all three entity zones (Personas, Projects, History). Exposes the header (title + optional `+` + collapse caret), an optional empty-state CTA, and slot content.

**Files — Create:**
- `frontend/src/app/components/sidebar/ZoneSection.tsx`

**Steps:**

- [ ] Create `frontend/src/app/components/sidebar/ZoneSection.tsx`:

  ```tsx
  import type { ReactNode } from 'react'
  import { useSidebarStore, type SidebarZone } from '../../../core/store/sidebarStore'

  interface ZoneSectionProps {
    zone: SidebarZone
    title: string
    onAdd?: () => void
    /** Empty CTA configuration. Renders only when `isEmpty` is true. */
    emptyState?: { label: string; onClick: () => void }
    /** Whether the zone has zero items. Drives empty-state rendering. */
    isEmpty: boolean
    children: ReactNode
  }

  /**
   * One of the three sidebar entity zones.
   *
   * Header: title (uppercase, dimmed), optional `+`, collapse caret.
   * Body: scrollable when content overflows the flex-allocated max height.
   * Per-zone open state is persisted via sidebarStore.
   */
  export function ZoneSection({
    zone,
    title,
    onAdd,
    emptyState,
    isEmpty,
    children,
  }: ZoneSectionProps) {
    const open = useSidebarStore((s) => s.zoneOpen[zone])
    const toggleZone = useSidebarStore((s) => s.toggleZone)

    return (
      <section
        className={`flex min-h-0 flex-col ${open ? 'flex-1' : 'flex-none'}`}
        aria-label={title}
      >
        <header className="flex flex-shrink-0 items-center gap-1 px-3 py-1.5">
          <button
            type="button"
            onClick={() => toggleZone(zone)}
            className="flex flex-1 items-center gap-1 text-left"
            aria-expanded={open}
          >
            <span className="text-[11px] font-medium uppercase tracking-wider text-white/55">
              {title}
            </span>
          </button>
          {onAdd && (
            <button
              type="button"
              onClick={onAdd}
              aria-label={`Create ${title.toLowerCase()}`}
              title={`Create ${title.toLowerCase()}`}
              className="flex h-5 w-5 items-center justify-center rounded text-[12px] text-white/55 transition-colors hover:bg-white/8 hover:text-white/85"
            >
              +
            </button>
          )}
          <button
            type="button"
            onClick={() => toggleZone(zone)}
            aria-label={open ? `Collapse ${title}` : `Expand ${title}`}
            title={open ? `Collapse ${title}` : `Expand ${title}`}
            className="flex h-5 w-5 items-center justify-center rounded text-[11px] text-white/55 transition-colors hover:bg-white/8 hover:text-white/85"
          >
            {open ? '∨' : '›'}
          </button>
        </header>

        {open && (
          <div className="min-h-0 flex-1 overflow-y-auto [&::-webkit-scrollbar]:w-[3px] [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10">
            {isEmpty && emptyState ? (
              <button
                type="button"
                onClick={emptyState.onClick}
                className="block w-full px-3 py-2 text-left text-[12px] text-white/45 transition-colors hover:text-white/70"
              >
                {emptyState.label}
              </button>
            ) : (
              children
            )}
          </div>
        )}
      </section>
    )
  }
  ```

- [ ] Run `cd frontend && pnpm tsc --noEmit`. Expected: no new errors from this file.

- [ ] Commit:

  ```bash
  git add frontend/src/app/components/sidebar/ZoneSection.tsx
  git commit -m "$(cat <<'EOF'
  Add ZoneSection component for collapsible flex-shared sidebar zones

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 5.2 — Create `ActionBlock` component

**Purpose:** Encapsulates the New Chat, New Incognito Chat, and conditional Continue rows.

**Files — Create:**
- `frontend/src/app/components/sidebar/ActionBlock.tsx`

**Steps:**

- [ ] Create `frontend/src/app/components/sidebar/ActionBlock.tsx`:

  ```tsx
  import type { PersonaDto } from '../../../core/types/persona'
  import { NewChatRow } from './NewChatRow'

  interface ActionBlockProps {
    personas: PersonaDto[]
    showContinue: boolean
    onCloseModal: () => void
    onNewIncognitoChat: () => void
    onContinue: () => void
  }

  /**
   * Top action block of the sidebar: New Chat (with persona picker),
   * New Incognito Chat, and the conditional Continue row.
   */
  export function ActionBlock({
    personas,
    showContinue,
    onCloseModal,
    onNewIncognitoChat,
    onContinue,
  }: ActionBlockProps) {
    return (
      <div className="flex-shrink-0 border-b border-white/5 pb-1">
        <NewChatRow personas={personas} onCloseModal={onCloseModal} />

        <button
          type="button"
          onClick={onNewIncognitoChat}
          className="group mx-2 mt-1 flex w-[calc(100%-16px)] items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-white/5"
        >
          <span className="text-[14px]">🕶️</span>
          <span className="flex-1 text-[12px] font-medium uppercase tracking-wider text-white/70 group-hover:text-white/90">
            New Incognito Chat
          </span>
          <span className="text-[10px] text-white/40">›</span>
        </button>

        {showContinue && (
          <button
            type="button"
            onClick={onContinue}
            className="group mx-2 mt-1 flex w-[calc(100%-16px)] items-center gap-2 rounded-md px-2 py-1 text-left transition-colors hover:bg-white/5"
          >
            <span className="text-[12px] text-white/60 group-hover:text-white/80">▶️</span>
            <span className="flex-1 text-[12px] text-white/60 group-hover:text-white/85">Continue</span>
            <span className="text-[10px] text-white/40">›</span>
          </button>
        )}
      </div>
    )
  }
  ```

- [ ] Run `cd frontend && pnpm tsc --noEmit`. Expected: no new errors from this file.

- [ ] Commit:

  ```bash
  git add frontend/src/app/components/sidebar/ActionBlock.tsx
  git commit -m "$(cat <<'EOF'
  Add ActionBlock sidebar sub-component for New Chat / Incognito / Continue

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 5.3 — Create `FooterBlock` component

**Purpose:** Bottom-of-sidebar block: Knowledge, Bookmarks, My data ›, Sanitised toggle, User row, Logout.

**Files — Create:**
- `frontend/src/app/components/sidebar/FooterBlock.tsx`

**Steps:**

- [ ] Create `frontend/src/app/components/sidebar/FooterBlock.tsx`:

  ```tsx
  import { NavRow } from './NavRow'

  interface FooterBlockProps {
    avatarTab: string
    avatarHighlight: boolean
    isSanitised: boolean
    displayName: string
    role: string
    initial: string
    hasApiKeyProblem: boolean
    isTabActive: (leaf: string) => boolean
    onOpenModal: (leaf: string) => void
    onOpenMyData: () => void
    onToggleSanitised: () => void
    onOpenUserRow: () => void
    onOpenSettings: () => void
    onLogout: () => void
  }

  /**
   * Sticky bottom of the sidebar: Knowledge / Bookmarks / My data,
   * Sanitised toggle, user identity row, Logout.
   */
  export function FooterBlock({
    avatarHighlight,
    isSanitised,
    displayName,
    role,
    initial,
    hasApiKeyProblem,
    isTabActive,
    onOpenModal,
    onOpenMyData,
    onToggleSanitised,
    onOpenUserRow,
    onOpenSettings,
    onLogout,
  }: FooterBlockProps) {
    return (
      <div className="flex-shrink-0 border-t border-white/5">
        <NavRow
          icon="🎓"
          label="Knowledge"
          isActive={isTabActive('knowledge')}
          onClick={() => onOpenModal('knowledge')}
        />
        <NavRow
          icon="🔖"
          label="Bookmarks"
          isActive={isTabActive('bookmarks')}
          onClick={() => onOpenModal('bookmarks')}
        />
        <NavRow
          icon="📂"
          label="My data ›"
          isActive={isTabActive('uploads') || isTabActive('artefacts') || isTabActive('images')}
          onClick={onOpenMyData}
        />

        <div className="mx-2 my-1.5 h-px bg-white/4" />

        <button
          type="button"
          onClick={onToggleSanitised}
          title={isSanitised ? "Sanitised mode on — NSFW content hidden" : "Sanitised mode off — all content visible"}
          aria-label={isSanitised ? "Turn sanitised mode off" : "Turn sanitised mode on"}
          aria-pressed={isSanitised}
          className="flex w-full items-center gap-2.5 px-3.5 py-1.5 transition-colors hover:bg-white/5"
        >
          <span className={`text-[15px] ${isSanitised ? "opacity-100" : "opacity-60 grayscale"}`}>
            🔒
          </span>
          <span className={`text-[13px] transition-colors ${isSanitised ? "text-gold font-medium" : "text-white/60"}`}>
            Sanitised
          </span>
        </button>

        <div className="mx-2 my-1.5 h-px bg-white/4" />

        <div
          className={[
            "flex items-center gap-2.5 px-3 py-2 transition-colors",
            avatarHighlight ? "bg-gold/7" : "",
          ].join(" ")}
        >
          <button
            type="button"
            onClick={onOpenUserRow}
            className="flex flex-1 items-center gap-2.5 min-w-0 hover:opacity-80 transition-opacity"
            title="Your profile"
          >
            <div className="relative flex h-[30px] w-[30px] flex-shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-purple to-gold text-[12px] font-bold text-white">
              {initial}
              {hasApiKeyProblem && (
                <span className="absolute -top-0.5 -right-0.5 flex h-3 w-3 items-center justify-center rounded-full bg-red-500 text-[7px] font-bold text-white">!</span>
              )}
            </div>
            <div className="text-left min-w-0">
              <p className={[
                "text-[13px] font-medium truncate transition-colors",
                avatarHighlight ? "text-gold" : "text-white/65",
              ].join(" ")}>
                {displayName}
              </p>
              <p className="text-[10px] text-white/60">{role}</p>
            </div>
          </button>

          <button
            type="button"
            onClick={onOpenSettings}
            title="Settings"
            aria-label="Settings"
            className="flex h-[22px] w-[22px] flex-shrink-0 items-center justify-center rounded text-[11px] text-white/60 transition-colors hover:bg-white/8 hover:text-white/85"
          >
            ···
          </button>
        </div>

        <button
          type="button"
          onClick={onLogout}
          aria-label="Log out"
          className="flex w-full items-center gap-2 px-4 py-1.5 text-[11px] text-white/60 hover:text-white/85 transition-colors font-mono"
        >
          <span>↪</span>
          <span>Log out</span>
        </button>
      </div>
    )
  }
  ```

- [ ] Run `cd frontend && pnpm tsc --noEmit`. Expected: no new errors from this file.

- [ ] Commit:

  ```bash
  git add frontend/src/app/components/sidebar/FooterBlock.tsx
  git commit -m "$(cat <<'EOF'
  Add FooterBlock sidebar sub-component (Knowledge/Bookmarks/My data/etc.)

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 5.4 — Rewrite the desktop expanded body of `Sidebar.tsx`

**Purpose:** Replace the current 800-ish lines of desktop JSX (between `// ── Desktop expanded view ──` and the closing `</aside>`) with the new structure that uses `ActionBlock`, two `ZoneSection`s (Personas, History), the conditional Projects `ZoneSection` behind the `PROJECTS_ENABLED` gate, and `FooterBlock`. The collapsed-rail and mobile branches above stay untouched in this task.

**Files — Modify:**
- `frontend/src/app/components/sidebar/Sidebar.tsx`

**Steps:**

- [ ] At the top of `Sidebar.tsx`, add the new imports:

  ```ts
  import { ActionBlock } from './ActionBlock'
  import { ZoneSection } from './ZoneSection'
  import { FooterBlock } from './FooterBlock'
  import { PROJECTS_ENABLED } from '../../../core/config/featureGates'
  import { sortPersonas } from './personaSort'
  import { getLastMyDataSubpage } from '../user-modal/myDataMemory'
  ```

  Remove the now-unused imports of `BookmarksTab` (it's still used in mobile) and any historic state-only imports left over from drag removal.

- [ ] Inside the `Sidebar` function, the `pinnedPersonas` / `unpinnedPersonas` partition is no longer used. Replace with one sorted list:

  ```ts
  const sortedPersonas = useMemo(
    () => sortPersonas(personas),
    [personas],
  )
  ```

  Add `useMemo` to the React import if missing.

- [ ] Compute the same for sessions: pinned-first, then unpinned, sorted by `updated_at` descending:

  ```ts
  const sortedSessions = useMemo(() => {
    const pinned = sessions.filter((s) => s.pinned)
    const unpinned = sessions.filter((s) => !s.pinned)
    const byUpdated = (a: ChatSessionDto, b: ChatSessionDto) => b.updated_at.localeCompare(a.updated_at)
    pinned.sort(byUpdated)
    unpinned.sort(byUpdated)
    return [...pinned, ...unpinned]
  }, [sessions])
  ```

- [ ] Define a stable handler for opening the My data modal:

  ```ts
  function handleOpenMyData() {
    closeDrawerIfMobile()
    onOpenModal(getLastMyDataSubpage())
  }
  ```

- [ ] Locate the JSX block that begins `// ── Desktop expanded view ──────────────────────────────────────────────` and ends with the final `</aside>` before the closing `}` of `Sidebar`. Replace its entire body (between `<aside ...>` open and close) with:

  ```tsx
        {/* Logo */}
        <div className="flex h-[50px] flex-shrink-0 items-center gap-2.5 border-b border-white/5 px-3.5">
          <button
            type="button"
            onClick={() => { onCloseModal(); navigate("/personas") }}
            title="All personas"
            aria-label="Open personas"
            className="flex flex-1 items-center gap-2.5 rounded-md -mx-1 px-1 py-0.5 text-left transition-colors hover:bg-white/5"
          >
            <span className="text-[17px]">🦊</span>
            <span className="flex-1 text-[15px] font-semibold tracking-wide text-white/85">Chatsune</span>
          </button>
          <button
            type="button"
            onClick={() => { if (isDesktop) { toggleCollapsed() } else { useDrawerStore.getState().close() } }}
            title="Collapse sidebar"
            aria-label="Collapse sidebar"
            className="flex h-5 w-5 items-center justify-center rounded text-[13px] text-white/60 transition-colors hover:bg-white/8 hover:text-white/85"
          >
            ⏪
          </button>
        </div>

        {/* Admin banner */}
        {isAdmin && (
          <button
            type="button"
            onClick={() => { closeDrawerIfMobile(); onOpenAdmin() }}
            className={[
              "mx-2 mt-2 flex flex-shrink-0 items-center gap-2 rounded-lg border px-2.5 py-1.5 transition-colors",
              isAdminOpen
                ? "border-gold/30 bg-gold/12"
                : "border-gold/16 bg-gold/7 hover:bg-gold/12",
            ].join(" ")}
          >
            <span className="text-[12px]">🪄</span>
            <span className="flex-1 text-left text-[12px] font-bold uppercase tracking-widest text-gold">Admin</span>
            <span className="text-[11px] text-gold/50">›</span>
          </button>
        )}

        {/* Action block */}
        <ActionBlock
          personas={personas}
          showContinue={!!lastSession && !isInChat}
          onCloseModal={onCloseModal}
          onNewIncognitoChat={() => {
            // Pick the most-recently-used persona; if none, fall through to /personas.
            const pick = sortedPersonas[0]
            if (!pick) { navigate('/personas'); return }
            onCloseModal(); closeDrawerIfMobile()
            navigate(`/chat/${pick.id}?incognito=1`)
          }}
          onContinue={handleContinue}
        />

        {/* Entity zones — flex-shared remaining vertical space */}
        <div className="flex min-h-0 flex-1 flex-col">
          <ZoneSection
            zone="personas"
            title="Personas"
            onAdd={() => { closeDrawerIfMobile(); onOpenModal('personas') }}
            isEmpty={sortedPersonas.length === 0}
            emptyState={{
              label: 'No personas yet · Create one →',
              onClick: () => { closeDrawerIfMobile(); onOpenModal('personas') },
            }}
          >
            {sortedPersonas.map((p) => (
              <PersonaItem
                key={p.id}
                persona={p}
                isActive={p.id === activePersonaId}
                onSelect={handlePersonaSelect}
                onNewChat={handleNewChat}
                onNewIncognitoChat={(persona) => { onCloseModal(); closeDrawerIfMobile(); navigate(`/chat/${persona.id}?incognito=1`) }}
                onEdit={(persona) => openOverlayAndClose(persona.id, 'edit')}
                onPin={p.pinned ? undefined : (persona) => onTogglePin?.(persona.id, true)}
                onUnpin={p.pinned ? (persona) => onTogglePin?.(persona.id, false) : undefined}
                onOpenOverlay={() => openOverlayAndClose(p.id)}
              />
            ))}
            <button
              type="button"
              onClick={() => openModalAndClose('personas')}
              className="mx-3 mt-1 flex w-[calc(100%-24px)] items-center gap-1.5 rounded-md px-2 py-1 text-[11px] text-white/40 transition-colors hover:bg-white/5 hover:text-white/60"
            >
              <span>More… ›</span>
            </button>
          </ZoneSection>

          {PROJECTS_ENABLED && (
            <ZoneSection
              zone="projects"
              title="Projects"
              isEmpty={true}
              emptyState={{
                label: 'No projects yet · Create one →',
                onClick: () => {/* deferred to Projects feature */},
              }}
            >
              {/* Projects rendering deferred to the Projects feature. */}
            </ZoneSection>
          )}

          <ZoneSection
            zone="history"
            title="History"
            isEmpty={sortedSessions.length === 0}
            emptyState={{
              label: 'No conversations yet · Start a new chat →',
              onClick: () => {
                const pick = sortedPersonas[0]
                if (!pick) { navigate('/personas'); return }
                onCloseModal(); closeDrawerIfMobile()
                navigate(`/chat/${pick.id}?new=1`)
              },
            }}
          >
            {sortedSessions.map((s) => {
              const persona = personas.find((p) => p.id === s.persona_id)
              return (
                <HistoryItem
                  key={s.id}
                  session={s}
                  isPinned={s.pinned}
                  isActive={s.id === activeSessionId}
                  monogram={persona?.monogram || persona?.name.charAt(0).toUpperCase()}
                  colourScheme={persona?.colour_scheme}
                  onClick={handleSessionClick}
                  onDelete={handleDeleteSession}
                  onTogglePin={handleToggleSessionPin}
                />
              )
            })}
            <button
              type="button"
              onClick={() => openModalAndClose('history')}
              className="mx-3 mt-1 flex w-[calc(100%-24px)] items-center gap-1.5 rounded-md px-2 py-1 text-[11px] text-white/40 transition-colors hover:bg-white/5 hover:text-white/60"
            >
              <span>More… ›</span>
            </button>
          </ZoneSection>
        </div>

        {/* Footer block */}
        <FooterBlock
          avatarTab={avatarTab}
          avatarHighlight={avatarHighlight}
          isSanitised={isSanitised}
          displayName={displayName}
          role={user?.role || ''}
          initial={initial}
          hasApiKeyProblem={hasApiKeyProblem}
          isTabActive={isTabActive}
          onOpenModal={(leaf) => openModalAndClose(leaf)}
          onOpenMyData={handleOpenMyData}
          onToggleSanitised={toggleSanitised}
          onOpenUserRow={() => openModalAndClose(avatarTab)}
          onOpenSettings={() => openModalAndClose('settings')}
          onLogout={() => logout()}
        />
  ```

- [ ] Delete the old, now-unused `historySearch` / `setHistorySearch` state, the `historyOpen` / `unpinnedOpen` state, the `matchesHistorySearch` helper, the `pinnedSessions` / `unpinnedSessions` arrays, the `pinnedPersonas` / `unpinnedPersonas` arrays, the `flyoutTab` state and all flyout handlers (the desktop expanded view no longer uses a flyout — flyouts only fire from the collapsed rail). If they are still referenced by the collapsed-rail branch above, keep them; otherwise remove.

- [ ] Run `cd frontend && pnpm tsc --noEmit`. Expected: errors only from `UserModal.tsx` (the still-pending `onCreatePersona` prop on PersonasTab) and possibly missing imports. Resolve missing-import errors here. Defer the `UserModal.tsx` error to Phase 6.

- [ ] Commit:

  ```bash
  git add frontend/src/app/components/sidebar/Sidebar.tsx
  git commit -m "$(cat <<'EOF'
  Decompose desktop sidebar body into ActionBlock, ZoneSections, FooterBlock

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 5.5 — Update the collapsed-rail variant: collapse 3 data icons into one `📂 My data`

**Purpose:** Per spec §4, the 50px-rail variant must consolidate the three data icons (Uploads, Artefacts, Images) into a single `📂 My data` icon that navigates via `getLastMyDataSubpage`.

**Files — Modify:**
- `frontend/src/app/components/sidebar/Sidebar.tsx`

**Steps:**

- [ ] In the collapsed-rail return (the `if (renderCollapsed) { return ( ... ) }` block earlier in the file), find the three `<IconBtn>` calls for Uploads (📂), Artefacts (🧪), Images (🖼️). Replace those three with a single one:

  ```tsx
          {/* My data — combined entry point */}
          <IconBtn
            icon="📂"
            onClick={() => onOpenModal(getLastMyDataSubpage())}
            title="My data"
            isActive={isTabActive('uploads') || isTabActive('artefacts') || isTabActive('images')}
          />
  ```

- [ ] Run `cd frontend && pnpm tsc --noEmit`. Expected: no new errors.

- [ ] Commit:

  ```bash
  git add frontend/src/app/components/sidebar/Sidebar.tsx
  git commit -m "$(cat <<'EOF'
  Collapse Uploads/Artefacts/Images into one My data icon on the rail

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 5.6 — Phase 5 build verification

**Steps:**

- [ ] Run `cd frontend && pnpm run build`. Expected: success unless the `PersonasTab onCreatePersona` prop is still missing on the `UserModal` callsite (Phase 6 fix). If only that error blocks the build, proceed to Phase 6 immediately.

---

## Phase 6 — Side cleanups

### Task 6.1 — Personas-tab scroll fix (already covered by Task 4.3 rewrite; verification only)

**Purpose:** Confirm the new `PersonasTab` already has the `flex-1 overflow-y-auto` wrapper.

**Steps:**

- [ ] Open `frontend/src/app/components/user-modal/PersonasTab.tsx` and confirm the structure is `flex h-full flex-col` outer, with the inner list inside `flex-1 overflow-y-auto`. If yes, no change. If no, edit to match Task 4.3 final code.

- [ ] No commit unless a change was needed.

---

### Task 6.2 — Wire `onCreatePersona` from `UserModal` to `PersonasTab`

**Purpose:** Fix the dangling `onCreatePersona` prop. The handler should open the persona-overlay in the `edit` tab with `personaId = null` (the existing creation flow used by `PersonasPage`).

**Files — Modify:**
- `frontend/src/app/components/user-modal/UserModal.tsx`

**Steps:**

- [ ] Open `frontend/src/app/components/user-modal/UserModal.tsx`. Add a new prop on `UserModalProps` named `onCreatePersona: () => void` (immediately after `onOpenPersonaOverlay`).

- [ ] Destructure `onCreatePersona` in the component.

- [ ] Find the line `{contentKey === 'personas' && <PersonasTab onOpenPersonaOverlay={onOpenPersonaOverlay} />}` and replace with:

  ```tsx
            {contentKey === 'personas' && <PersonasTab onOpenPersonaOverlay={onOpenPersonaOverlay} onCreatePersona={onCreatePersona} />}
  ```

- [ ] Find the parent component that renders `<UserModal>` (search):

  ```bash
  grep -rn "<UserModal" frontend/src
  ```

  At each callsite, pass:

  ```tsx
  onCreatePersona={() => openPersonaOverlay(null, 'edit')}
  ```

  using the same `openPersonaOverlay` already used for `onOpenPersonaOverlay`. (If `openPersonaOverlay` does not exist at a callsite, use the same handler that `PersonasPage` uses for `handleCreateNew`.)

- [ ] Run `cd frontend && pnpm run build`. Expected: build succeeds.

- [ ] Commit:

  ```bash
  git add frontend/src/app/components/user-modal/UserModal.tsx frontend/src/app
  git commit -m "$(cat <<'EOF'
  Wire onCreatePersona through UserModal to the PersonasTab + button

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 6.3 — History-tab per-row pin toggle

**Purpose:** Add a pin/unpin button to each `SessionRow` in `HistoryTab`. Visible on hover desktop, always visible on touch.

**Files — Modify:**
- `frontend/src/app/components/user-modal/HistoryTab.tsx`

**Steps:**

- [ ] Open `frontend/src/app/components/user-modal/HistoryTab.tsx`. In `SessionRow`'s prop interface, add:

  ```ts
    isPinned: boolean
    onTogglePin: () => void
  ```

- [ ] In the `HistoryTab` render that maps `groupSessions.map((s) => (`, pass through the new props:

  ```tsx
                  <SessionRow
                    key={s.id}
                    session={s}
                    personaName={persona?.name ?? s.persona_id}
                    monogram={persona?.monogram || persona?.name.charAt(0).toUpperCase()}
                    colourScheme={persona?.colour_scheme}
                    onOpen={() => handleOpen(s)}
                    isPinned={s.pinned}
                    onTogglePin={async () => {
                      try {
                        await chatApi.updateSessionPinned(s.id, !s.pinned)
                      } catch {
                        // pin event arrives via WS; non-critical
                      }
                    }}
                  />
  ```

- [ ] Inside `SessionRow`, in the actions row (the `<div className="flex items-center gap-1 ...">` containing REN/GEN/DEL), add a new pin button as the first action:

  ```tsx
              <button
                type="button"
                onClick={onTogglePin}
                aria-label={isPinned ? 'Unpin session' : 'Pin session'}
                title={isPinned ? 'Unpin' : 'Pin'}
                className={`${BTN_NEUTRAL} ${isPinned ? 'text-gold border-gold/30' : ''}`}
              >
                📌
              </button>
  ```

- [ ] Apply the gold-stripe to pinned rows in `SessionRow`. At the top of `HistoryTab.tsx`, import:

  ```ts
  import { PINNED_STRIPE_STYLE } from '../sidebar/pinnedStripe'
  ```

  In `SessionRow`'s outer `<div className="group rounded-lg transition-colors hover:bg-white/4">`, add a style attribute:

  ```tsx
      <div
        className="group rounded-lg transition-colors hover:bg-white/4"
        style={isPinned ? PINNED_STRIPE_STYLE : undefined}
      >
  ```

- [ ] Run `cd frontend && pnpm tsc --noEmit`. Expected: no errors.

- [ ] Commit:

  ```bash
  git add frontend/src/app/components/user-modal/HistoryTab.tsx
  git commit -m "$(cat <<'EOF'
  Add per-row pin toggle and gold stripe to HistoryTab session rows

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 6.4 — In-chat pin/unpin button next to title

**Purpose:** Add a pin button to the right of `sessionTitle` in `ChatView`. Filled when pinned, outline when not. Calls `chatApi.updateSessionPinned`.

**Files — Modify:**
- `frontend/src/features/chat/ChatView.tsx`

**Steps:**

- [ ] Open `frontend/src/features/chat/ChatView.tsx`. Find the line at ~219:

  ```ts
  const sessionTitle = useChatStore((s) => s.sessionTitle)
  ```

  Below it (or near the other chat-store reads), add a derived `sessionPinned` value. Since the chat store does not currently track pinned, fetch it through the session-load effect: after the existing `useChatStore.getState().setSessionTitle(session.title)` call at ~377, add a local React state setter for pinned.

  Implementation: introduce local `useState<boolean>` for pinned at the top of `ChatView`:

  ```ts
  const [sessionPinned, setSessionPinned] = useState<boolean>(false)
  ```

  In the session-load effect, after the existing `setSessionTitle(session.title)` call at line ~377, add:

  ```ts
          setSessionPinned(session.pinned ?? false)
  ```

- [ ] Listen for `CHAT_SESSION_PINNED_UPDATED` events to keep the local state in sync. Add a new effect near the other event subscriptions:

  ```ts
  useEffect(() => {
    if (!effectiveSessionId) return
    const off = eventBus.on(Topics.CHAT_SESSION_PINNED_UPDATED, (event: BaseEvent) => {
      if (event.payload.session_id !== effectiveSessionId) return
      setSessionPinned(Boolean(event.payload.pinned))
    })
    return off
  }, [effectiveSessionId])
  ```

  Add the imports if missing:

  ```ts
  import { eventBus } from '../../core/websocket/eventBus'
  import { Topics, type BaseEvent } from '../../core/types/events'
  ```

- [ ] Find the chat header line (around 1183) where `sessionTitle ?? 'New chat'` is rendered. Wrap it with an inline-flex row that contains the title and a pin button immediately to its right. Replace:

  ```tsx
          <span className="max-w-[40vw] md:max-w-[400px] truncate text-[13px] text-white/40">
            {isIncognito ? (persona?.name ?? 'Incognito') : (sessionTitle ?? 'New chat')}
          </span>
  ```

  With:

  ```tsx
          <span className="max-w-[40vw] md:max-w-[400px] truncate text-[13px] text-white/40">
            {isIncognito ? (persona?.name ?? 'Incognito') : (sessionTitle ?? 'New chat')}
          </span>
          {!isIncognito && effectiveSessionId && (
            <button
              type="button"
              onClick={async () => {
                const next = !sessionPinned
                setSessionPinned(next)
                try {
                  await chatApi.updateSessionPinned(effectiveSessionId, next)
                } catch {
                  setSessionPinned(!next)
                }
              }}
              aria-label={sessionPinned ? 'Unpin chat' : 'Pin chat'}
              aria-pressed={sessionPinned}
              title={sessionPinned ? 'Unpin chat' : 'Pin chat'}
              className={`ml-1.5 flex h-5 w-5 items-center justify-center rounded text-[12px] transition-colors ${sessionPinned ? 'text-gold' : 'text-white/35 hover:text-white/65'}`}
            >
              {sessionPinned ? '📌' : '📍'}
            </button>
          )}
  ```

  Note: `📌` is "filled" pin; `📍` is "outline-ish" round pin used here as the not-pinned state. If a more glyph-precise pair is preferred, swap to inline SVG matching the existing chat-icon style — the spec only requires "filled = pinned, outline = not pinned".

- [ ] Run `cd frontend && pnpm tsc --noEmit`. Expected: no errors.

- [ ] Commit:

  ```bash
  git add frontend/src/features/chat/ChatView.tsx
  git commit -m "$(cat <<'EOF'
  Add pin/unpin button to the chat top bar next to the session title

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 6.5 — Update `userModalSubtabStore` and `myDataMemory` integration

**Purpose:** When the user switches to Uploads / Artefacts / Images inside the modal, update `chatsune_my_data_last_subpage` so the next sidebar `My data ›` click lands on the same one.

**Files — Modify:**
- `frontend/src/app/components/user-modal/UserModal.tsx`

**Steps:**

- [ ] Open `frontend/src/app/components/user-modal/UserModal.tsx`. Add at the top:

  ```ts
  import { setLastMyDataSubpage, type MyDataSubpage } from './myDataMemory'
  ```

- [ ] Inside the `UserModal` component, add a `useEffect` near the existing effects:

  ```tsx
    useEffect(() => {
      const sub = activeSub ?? activeTop
      if (sub === 'uploads' || sub === 'artefacts' || sub === 'images') {
        setLastMyDataSubpage(sub as MyDataSubpage)
      }
    }, [activeTop, activeSub])
  ```

- [ ] Run `cd frontend && pnpm tsc --noEmit`. Expected: no errors.

- [ ] Commit:

  ```bash
  git add frontend/src/app/components/user-modal/UserModal.tsx
  git commit -m "$(cat <<'EOF'
  Persist last-visited My data sub-page on tab change

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Phase 7 — Verification

### Task 7.1 — Backend test sweep (host-runnable subset)

**Purpose:** Run the backend test suites that do not require MongoDB.

**Steps:**

- [ ] Run from the repo root:

  ```bash
  cd backend && uv run pytest tests/modules/persona tests/modules/chat -v
  ```

  Expected output: all tests in `test_bump_last_used.py`, `test_synthesise_events.py`, `test_inference_events.py`, `test_tool_error_recovery.py`, `test_migration_tts_provider_id.py` pass. No `db`-fixture-dependent tests should appear.

- [ ] If any DB-using tests appear and fail with a connection error, recommend running them via Docker:

  ```bash
  docker compose exec backend pytest tests/modules
  ```

  Document this in the task notes; do NOT modify tests to skip.

- [ ] No commit; verification gate.

---

### Task 7.2 — Frontend test sweep

**Steps:**

- [ ] Run:

  ```bash
  cd frontend && pnpm vitest run
  ```

  Expected: all tests pass, including the new `personaSort.test.ts`. If `PersonasTab.test.tsx` fails because it referenced the now-removed `__personasTabTestHelper` seam or DnD assertions, update or delete the obsolete test cases (drag is gone). Document each removal in a follow-up commit:

  ```bash
  git add frontend/src/app/components/user-modal/__tests__/PersonasTab.test.tsx
  git commit -m "$(cat <<'EOF'
  Remove obsolete drag assertions from PersonasTab tests

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task 7.3 — Final frontend build

**Steps:**

- [ ] Run:

  ```bash
  cd frontend && pnpm run build
  ```

  Expected: full build success, dist/ written, no TypeScript errors, no Vite warnings about unresolved imports.

- [ ] If build fails, fix in a focused new task (do not bundle the fix into an unrelated commit).

- [ ] No commit unless changes were needed.

---

### Task 7.4 — Manual smoke checklist (operator-driven)

**Purpose:** Run the spec §8 manual verification list against a real browser. This is operator work; the subagent leaves a checklist comment in the working branch description and stops.

**Steps:**

- [ ] Reproduce the spec §8 list as a checklist in the next message to the operator. Items:
  - Zone allocation (collapse all / open one / two / three)
  - Pinned indicator (pin/unpin a persona; pin/unpin a session)
  - LRU and drag removal (try to drag in sidebar / Personas-tab / PersonasPage; start a new chat with a bottom-LRU persona and confirm it bubbles up)
  - Action block (Continue row visibility under all three states)
  - My data › (first click → uploads; switch to artefacts → close → reopen → artefacts; same for images)
  - Side cleanups (Personas-tab scrolls; + creates persona; History-tab pin toggle; chat top-bar pin toggle)
  - Empty states (zero personas + zero chats)
  - Sanitised mode toggle behaviour
  - localStorage persistence (collapse zone, reload, remains collapsed)

- [ ] No commit; this is an operator handoff.

---

## Risk register and known scope expansion

The spec mandates `@dnd-kit/*` removal from `package.json`. Audit found four other consumers beyond `Sidebar.tsx` and `PersonasTab.tsx`:

1. `frontend/src/app/components/persona-card/PersonaCard.tsx` — drag handle for PersonasPage. Removed in Task 4.6 (`display_order` is no longer read by frontend per spec §3.3).
2. `frontend/src/app/pages/PersonasPage.tsx` — DndContext for the personas grid. Removed in Task 4.6.
3. `frontend/src/app/components/user-modal/BookmarksTab.tsx` — drag-reorder for bookmarks. Drag removed in Task 4.7; bookmarks switch to natural ordering by `created_at` descending. No replacement reorder UI per spec §3.4.
4. `frontend/src/features/chat/ChatBookmarkList.tsx` — same. Drag removed in Task 4.8; bookmarks sort by chat-message position. No replacement reorder UI.

This is a small expansion of the Bookmarks-feature surface: drag-reorder goes away. Spec Non-Goals language (§Non-Goals) was updated to make this explicit so the change is part of the agreed scope rather than a surprise.

---


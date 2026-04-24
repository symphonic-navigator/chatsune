# Cockpit Toolbar Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the scattered composer toolbar with a single responsive cockpit row (attachments, session toggles, integrations, the magic voice button, live mode) backed by server-persisted session state.

**Architecture:** Frontend: new `features/chat/cockpit/` directory containing a reusable `CockpitButton` primitive, a `cockpitStore` cache, and one adapter component per button; rendered by a new `CockpitBar`. Backend: two new ChatSession fields (`tools_enabled`, `auto_read`) replace the removed `disabled_tool_groups`; defaults are computed from the persona at session-create time; an idempotent one-shot migration promotes existing documents.

**Tech Stack:** Python 3.12 + FastAPI + Pydantic v2 + MongoDB (backend). Vite + React + TypeScript + Zustand + Tailwind (frontend). Tests: pytest (backend), Vitest (frontend where sensible — most UI is verified manually per the spec).

**Spec:** `devdocs/superpowers/specs/2026-04-24-cockpit-toolbar-redesign-design.md`

---

## Task 1: Extend shared ChatSessionDto

**Files:**
- Modify: `shared/dtos/chat.py:19-36`

- [ ] **Step 1: Update the DTO**

Replace the `ChatSessionDto` class body (lines 19-36) with:

```python
class ChatSessionDto(BaseModel):
    id: str
    user_id: str
    persona_id: str
    state: Literal["idle", "streaming", "requires_action"]
    title: str | None = None
    tools_enabled: bool = False
    auto_read: bool = False
    reasoning_override: bool | None = None
    pinned: bool = False
    # Last-known context window utilisation, persisted at stream-end so
    # the UI can show a non-zero indicator when revisiting an existing
    # chat without having to wait for the next inference to complete.
    context_status: Literal["green", "yellow", "orange", "red"] = "green"
    context_fill_percentage: float = 0.0
    context_used_tokens: int = 0
    context_max_tokens: int = 0
    created_at: datetime
    updated_at: datetime
```

`disabled_tool_groups` is removed. Defaults for `tools_enabled` and `auto_read` are `False` so pre-existing documents deserialise cleanly (CLAUDE.md no-wipe rule).

- [ ] **Step 2: Run a syntax check**

Run: `uv run python -m py_compile shared/dtos/chat.py`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add shared/dtos/chat.py
git commit -m "Replace disabled_tool_groups with tools_enabled and auto_read in ChatSessionDto"
```

---

## Task 2: Replace the session-tools-updated event DTO

**Files:**
- Modify: `shared/events/chat.py:184` (and surrounding `ChatSessionToolsUpdatedEvent` class)

- [ ] **Step 1: Inspect the existing event**

Run: `grep -n "ChatSessionToolsUpdatedEvent\|CHAT_SESSION_TOOLS_UPDATED" shared/events/chat.py shared/topics.py`

- [ ] **Step 2: Rename the event and its fields**

In `shared/events/chat.py`, rename the class to `ChatSessionTogglesUpdatedEvent` and replace `disabled_tool_groups: list[str]` with:

```python
tools_enabled: bool
auto_read: bool
reasoning_override: bool | None
```

This single event now carries all three session toggles so a single WebSocket payload keeps the frontend cache in sync after any one of them changes.

- [ ] **Step 3: Rename the topic constant**

In `shared/topics.py`, rename `CHAT_SESSION_TOOLS_UPDATED` → `CHAT_SESSION_TOGGLES_UPDATED` (same string value ok; update the name for readability).

- [ ] **Step 4: Syntax check**

Run: `uv run python -m py_compile shared/events/chat.py shared/topics.py`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add shared/events/chat.py shared/topics.py
git commit -m "Rename session-tools-updated event to toggles-updated and carry all three toggles"
```

---

## Task 3: Update chat repository

**Files:**
- Modify: `backend/modules/chat/_repository.py:182-190, 555-560`

- [ ] **Step 1: Replace the update method**

Replace `update_session_disabled_tool_groups` (lines 182-190) with two new methods and keep them adjacent to `update_session_reasoning_override`:

```python
async def update_session_tools_enabled(
    self, session_id: str, tools_enabled: bool,
) -> dict | None:
    now = datetime.now(UTC)
    await self._sessions.update_one(
        {"_id": session_id},
        {"$set": {"tools_enabled": tools_enabled, "updated_at": now}},
    )
    return await self._sessions.find_one({"_id": session_id})

async def update_session_auto_read(
    self, session_id: str, auto_read: bool,
) -> dict | None:
    now = datetime.now(UTC)
    await self._sessions.update_one(
        {"_id": session_id},
        {"$set": {"auto_read": auto_read, "updated_at": now}},
    )
    return await self._sessions.find_one({"_id": session_id})
```

- [ ] **Step 2: Update `session_to_dto`**

In the `session_to_dto` classmethod (around line 555-560), replace the `disabled_tool_groups=doc.get("disabled_tool_groups", [])` line with:

```python
tools_enabled=doc.get("tools_enabled", False),
auto_read=doc.get("auto_read", False),
```

Keep `reasoning_override=doc.get("reasoning_override")` as-is.

- [ ] **Step 3: Find and update any callers of the old method**

Run: `rg "update_session_disabled_tool_groups" backend/ shared/`
Expected: matches only in `_handlers.py` (which Task 4 updates). No other callers.

- [ ] **Step 4: Syntax check**

Run: `uv run python -m py_compile backend/modules/chat/_repository.py`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/_repository.py
git commit -m "Replace disabled_tool_groups repo method with tools_enabled and auto_read"
```

---

## Task 4: Rewrite the session-toggles handler

**Files:**
- Modify: `backend/modules/chat/_handlers.py:373-409`
- Modify: `backend/modules/chat/__init__.py:45-52` (public API re-exports)

- [ ] **Step 1: Replace the `UpdateSessionToolsRequest` class and endpoint**

In `_handlers.py`, replace the block starting at `class UpdateSessionToolsRequest` (line 373) through the end of the `update_session_tools` function (line ~409) with:

```python
class UpdateSessionTogglesRequest(BaseModel):
    tools_enabled: bool | None = None
    auto_read: bool | None = None


@router.patch("/sessions/{session_id}/toggles")
async def update_session_toggles(
    session_id: str,
    body: UpdateSessionTogglesRequest,
    user: dict = Depends(require_active_session),
):
    repo = _chat_repo()
    session = await repo.get_session(session_id, user["sub"])
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if body.tools_enabled is not None:
        session = await repo.update_session_tools_enabled(session_id, body.tools_enabled)
    if body.auto_read is not None:
        session = await repo.update_session_auto_read(session_id, body.auto_read)

    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.CHAT_SESSION_TOGGLES_UPDATED,
        ChatSessionTogglesUpdatedEvent(
            session_id=session_id,
            tools_enabled=session.get("tools_enabled", False),
            auto_read=session.get("auto_read", False),
            reasoning_override=session.get("reasoning_override"),
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

Imports at the top of `_handlers.py` need to switch from `ChatSessionToolsUpdatedEvent` to `ChatSessionTogglesUpdatedEvent` — adjust the import line.

- [ ] **Step 2: Update `__init__.py` re-exports**

In `backend/modules/chat/__init__.py` around line 45-52 (the list of session-doc fields), replace `"disabled_tool_groups"` with `"tools_enabled"` and `"auto_read"`.

- [ ] **Step 3: Syntax check**

Run: `uv run python -m py_compile backend/modules/chat/_handlers.py backend/modules/chat/__init__.py`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/chat/_handlers.py backend/modules/chat/__init__.py
git commit -m "Replace session /tools endpoint with /toggles accepting tools_enabled and auto_read"
```

---

## Task 5: Compute persona defaults at session create

**Files:**
- Modify: `backend/modules/chat/_repository.py` — the `create_session` method (find via `rg -n "async def create_session" backend/modules/chat/_repository.py`)
- Possibly: `backend/modules/chat/_handlers.py` where sessions are created

- [ ] **Step 1: Locate the session-create code path**

Run: `rg -n "async def create_session\|create_session\(" backend/modules/chat`

- [ ] **Step 2: Add a helper `compute_persona_toggle_defaults` to the chat module**

Create, in `backend/modules/chat/_toggle_defaults.py`:

```python
"""Compute session-toggle defaults from a persona."""
from typing import Any

from backend.modules.tools import get_tool_groups_for_persona


def compute_persona_toggle_defaults(
    persona: dict[str, Any],
) -> dict[str, bool]:
    """Return {"tools_enabled": bool, "auto_read": bool} derived from persona."""
    tool_groups = get_tool_groups_for_persona(persona)
    tools_enabled = any(group.get("tools") for group in tool_groups)

    voice_cfg = persona.get("voice_config") or {}
    has_tts_provider = bool(voice_cfg.get("tts_provider_id"))
    has_voice = bool(voice_cfg.get("dialogue_voice"))
    auto_read = has_tts_provider and has_voice

    return {"tools_enabled": tools_enabled, "auto_read": auto_read}
```

If `backend/modules/tools` does not expose `get_tool_groups_for_persona`, locate the equivalent function with:
`rg -n "tool_groups|get_active_definitions" backend/modules/tools`
and adjust the import and call to match the actual public API. The rule is: a persona has tool-bringing integrations iff any integration configured for it yields at least one tool definition.

- [ ] **Step 3: Call the helper in `create_session`**

In the repository method that inserts a new session document, read the persona (the code already does this, or else the handler does and passes persona in), call `compute_persona_toggle_defaults(persona)`, and include `tools_enabled` and `auto_read` in the initial document alongside `reasoning_override=None`.

- [ ] **Step 4: Syntax check**

Run: `uv run python -m py_compile backend/modules/chat/_toggle_defaults.py backend/modules/chat/_repository.py`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/_toggle_defaults.py backend/modules/chat/_repository.py backend/modules/chat/_handlers.py
git commit -m "Compute tools_enabled and auto_read defaults from persona on session create"
```

---

## Task 6: Feed tools_enabled into the orchestrator

**Files:**
- Modify: `backend/modules/chat/_orchestrator.py:535-565` (around the current `disabled_tool_groups` block)
- Modify: `backend/modules/chat/_handlers_ws.py:578-582`

- [ ] **Step 1: Replace the disabled-groups gate in `_orchestrator.py`**

Find the block (starting around line 539):

```python
disabled_tool_groups = session.get("disabled_tool_groups", [])
...
and "mcp" not in set(disabled_tool_groups)
...
disabled_tool_groups,
```

Replace with a single gate:

```python
tools_enabled = session.get("tools_enabled", False)
if not tools_enabled:
    active_tools = None
else:
    active_tools = get_active_definitions([])  # empty disabled-list == all groups active
```

and thread `active_tools` into the downstream call where `disabled_tool_groups` was previously threaded. If the downstream function still accepts a `disabled_tool_groups` parameter, either pass `[]` or refactor the parameter away — prefer the smaller refactor here to keep the diff local.

- [ ] **Step 2: Same replacement in `_handlers_ws.py`**

At line 580-581:

```python
disabled_tool_groups = session.get("disabled_tool_groups", []) if session else []
active_tools = get_active_definitions(disabled_tool_groups) or None
```

becomes:

```python
tools_enabled = session.get("tools_enabled", False) if session else False
active_tools = get_active_definitions([]) if tools_enabled else None
```

- [ ] **Step 3: Syntax check**

Run: `uv run python -m py_compile backend/modules/chat/_orchestrator.py backend/modules/chat/_handlers_ws.py`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/chat/_orchestrator.py backend/modules/chat/_handlers_ws.py
git commit -m "Gate tool list on session.tools_enabled instead of disabled_tool_groups"
```

---

## Task 7: Feed auto_read into the voice auto-play decision

**Files:**
- Find the file(s) that trigger TTS auto-play today. Run: `rg -n "auto.*read\|auto_play\|autoPlay" backend/` and `rg -n "tts_playback_started\|tts.*auto" backend/`

- [ ] **Step 1: Locate the auto-play trigger**

Typical location: a function that receives the completed assistant message and decides whether to kick off the TTS pipeline. This likely reads persona voice config today.

- [ ] **Step 2: Change the gate to `session.auto_read`**

Where today it reads the persona's voice config to decide auto-play, gate on `session.get("auto_read", False)` instead. Persona voice config still provides the voice, model and other parameters; it no longer decides whether to play.

- [ ] **Step 3: Syntax check**

Run `uv run python -m py_compile` on every touched file.

- [ ] **Step 4: Commit**

```bash
git commit -m "Gate TTS auto-play on session.auto_read"
```

---

## Task 8: Write the one-shot migration

**Files:**
- Create: `backend/migrations/__init__.py` (empty)
- Create: `backend/migrations/2026_04_24_session_toggles.py`

- [ ] **Step 1: Create the migrations directory**

Run: `mkdir -p backend/migrations && touch backend/migrations/__init__.py`

- [ ] **Step 2: Write the migration script**

Create `backend/migrations/2026_04_24_session_toggles.py`:

```python
"""Promote ChatSession documents to the new toggle fields.

Idempotent: safe to re-run. For each session:

- Unsets ``disabled_tool_groups``.
- If ``tools_enabled`` is missing, sets it from the persona (tool-bringing
  integration => True, else False).
- If ``auto_read`` is missing, sets it from the persona (TTS provider and
  dialogue voice configured => True, else False).

Run with:

    uv run python -m backend.migrations.2026_04_24_session_toggles
"""
import asyncio
import logging
from typing import Any

from backend.infra.mongo import get_mongo_client
from backend.modules.chat._toggle_defaults import compute_persona_toggle_defaults

_log = logging.getLogger(__name__)


async def migrate_one(
    session_doc: dict[str, Any], personas: Any,
) -> dict[str, Any]:
    update: dict[str, Any] = {}
    unset: dict[str, Any] = {}

    if "disabled_tool_groups" in session_doc:
        unset["disabled_tool_groups"] = ""

    needs_tools = "tools_enabled" not in session_doc
    needs_auto_read = "auto_read" not in session_doc
    if needs_tools or needs_auto_read:
        persona_id = session_doc.get("persona_id")
        persona = await personas.find_one({"_id": persona_id}) if persona_id else None
        defaults = (
            compute_persona_toggle_defaults(persona) if persona
            else {"tools_enabled": False, "auto_read": False}
        )
        if needs_tools:
            update["tools_enabled"] = defaults["tools_enabled"]
        if needs_auto_read:
            update["auto_read"] = defaults["auto_read"]

    if not update and not unset:
        return {"skipped": True}

    mutation: dict[str, Any] = {}
    if update:
        mutation["$set"] = update
    if unset:
        mutation["$unset"] = unset
    return mutation


async def run() -> None:
    client = get_mongo_client()
    db = client.get_default_database()
    sessions = db["chat_sessions"]
    personas = db["personas"]

    cursor = sessions.find({})
    migrated = 0
    skipped = 0
    async for doc in cursor:
        mutation = await migrate_one(doc, personas)
        if mutation.get("skipped"):
            skipped += 1
            continue
        await sessions.update_one({"_id": doc["_id"]}, mutation)
        migrated += 1
    _log.info("Migration done: migrated=%d skipped=%d", migrated, skipped)
    print(f"Migration done: migrated={migrated} skipped={skipped}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
```

- [ ] **Step 3: Write a test for idempotency**

Create `tests/migrations/test_session_toggles.py`:

```python
"""Integration test: the 2026-04-24 session-toggles migration is idempotent."""
import pytest
from unittest.mock import AsyncMock

from backend.migrations import _2026_04_24_session_toggles as migration_mod  # noqa

pytestmark = pytest.mark.asyncio


async def test_migrate_one_removes_disabled_and_sets_defaults(monkeypatch):
    session = {
        "_id": "s1",
        "persona_id": "p1",
        "disabled_tool_groups": [],
    }
    personas = AsyncMock()
    personas.find_one = AsyncMock(return_value={
        "_id": "p1",
        "voice_config": {"tts_provider_id": "xai", "dialogue_voice": "Ara"},
        "integrations_config": {"enabled_integration_ids": []},
    })
    mutation = await migration_mod.migrate_one(session, personas)

    assert mutation["$unset"] == {"disabled_tool_groups": ""}
    assert mutation["$set"]["auto_read"] is True
    assert mutation["$set"]["tools_enabled"] is False


async def test_migrate_one_is_idempotent_on_already_migrated():
    session = {
        "_id": "s1",
        "persona_id": "p1",
        "tools_enabled": True,
        "auto_read": False,
    }
    personas = AsyncMock()
    result = await migration_mod.migrate_one(session, personas)
    assert result.get("skipped") is True
```

Note the underscore-prefix import name — Python module names can't start with a digit, so the filename `2026_04_24_session_toggles.py` is imported via a private alias at the top of the test. Adjust the actual import to use `importlib` if needed:

```python
import importlib
migration_mod = importlib.import_module(
    "backend.migrations.2026_04_24_session_toggles",
)
```

If that also fails at parse time because of the leading digit, rename the migration file to `m_2026_04_24_session_toggles.py` and update the test import to match.

- [ ] **Step 4: Run the test against a DB-free path**

Run: `uv run pytest tests/migrations/test_session_toggles.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/migrations/ tests/migrations/
git commit -m "Add idempotent migration for session toggle fields"
```

---

## Task 9: Backend smoke test against in-memory fake

**Files:**
- Create: `tests/backend/chat/test_toggle_defaults.py`

- [ ] **Step 1: Write the test**

```python
"""Unit test: compute_persona_toggle_defaults pulls the right bits."""
from backend.modules.chat._toggle_defaults import compute_persona_toggle_defaults


def test_auto_read_true_when_voice_configured(monkeypatch):
    monkeypatch.setattr(
        "backend.modules.chat._toggle_defaults.get_tool_groups_for_persona",
        lambda persona: [],
    )
    persona = {
        "voice_config": {
            "tts_provider_id": "xai",
            "dialogue_voice": "Ara",
        },
    }
    out = compute_persona_toggle_defaults(persona)
    assert out == {"tools_enabled": False, "auto_read": True}


def test_tools_enabled_true_when_integration_publishes_tools(monkeypatch):
    monkeypatch.setattr(
        "backend.modules.chat._toggle_defaults.get_tool_groups_for_persona",
        lambda persona: [{"id": "lovense", "tools": [{"name": "list_toys"}]}],
    )
    out = compute_persona_toggle_defaults({})
    assert out["tools_enabled"] is True


def test_all_false_for_blank_persona(monkeypatch):
    monkeypatch.setattr(
        "backend.modules.chat._toggle_defaults.get_tool_groups_for_persona",
        lambda persona: [],
    )
    out = compute_persona_toggle_defaults({})
    assert out == {"tools_enabled": False, "auto_read": False}
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/backend/chat/test_toggle_defaults.py -v`
Expected: three PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/backend/chat/
git commit -m "Test compute_persona_toggle_defaults"
```

---

## Task 10: Frontend API + session type updates

**Files:**
- Modify: `frontend/src/core/api/chat.ts:8-20, 130-145`

- [ ] **Step 1: Update the session type and API**

In `frontend/src/core/api/chat.ts`:

Replace in the session type (around line 11):

```ts
disabled_tool_groups: string[]
reasoning_override: boolean | null
```

with:

```ts
tools_enabled: boolean
auto_read: boolean
reasoning_override: boolean | null
```

Replace the `updateSessionTools` function (around line 139) with:

```ts
updateSessionToggles: (
  sessionId: string,
  patch: { tools_enabled?: boolean; auto_read?: boolean },
) =>
  api.patch<ChatSession>(`/chat/sessions/${sessionId}/toggles`, patch),
```

Keep `updateSessionReasoning` unchanged.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/core/api/chat.ts
git commit -m "Frontend API: replace updateSessionTools with updateSessionToggles"
```

---

## Task 11: Frontend chat store updates

**Files:**
- Modify: `frontend/src/core/store/chatStore.ts:49-110, 190-200`

- [ ] **Step 1: Replace disabledToolGroups with new fields**

In the store definition around lines 49-55:

Remove:
```ts
disabledToolGroups: string[]
```

Add:
```ts
toolsEnabled: boolean
autoRead: boolean
```

In the initial state (around line 104):

Remove `disabledToolGroups: [] as string[],`. Add:

```ts
toolsEnabled: false,
autoRead: false,
```

Remove the setter (around line 194): `setDisabledToolGroups: ...`. Add:

```ts
setToolsEnabled: (value: boolean) => set({ toolsEnabled: value }),
setAutoRead: (value: boolean) => set({ autoRead: value }),
```

- [ ] **Step 2: Fix all compile errors surfaced**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: a list of errors in files that reference `disabledToolGroups` / `setDisabledToolGroups`. Files touched by later tasks are allowed to stay broken for now. The following files must be updated in this task to keep the repo compiling *apart from the known-broken ToolToggles-related files that get deleted later*:

- `frontend/src/features/chat/ChatView.tsx:206, 381, 1039, 1253, 1329` — replace `disabledToolGroups` reads with `toolsEnabled`/`autoRead` or remove if no longer needed (these lines are touched again in Task 22 for the final replacement)
- `frontend/src/core/hooks/useChatSessions.ts:37` — replace `disabled_tool_groups: []` with `tools_enabled: false, auto_read: false`
- `frontend/src/features/chat/useChatStream.ts:294` — update the WebSocket handler for the renamed toggles event

For useChatStream, replace:
```ts
getStore().setDisabledToolGroups(p.disabled_tool_groups as string[])
```
with handling the new `CHAT_SESSION_TOGGLES_UPDATED` event fields:
```ts
if (typeof p.tools_enabled === 'boolean') getStore().setToolsEnabled(p.tools_enabled)
if (typeof p.auto_read === 'boolean') getStore().setAutoRead(p.auto_read)
if ('reasoning_override' in p) getStore().setReasoningOverride(p.reasoning_override ?? null)
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/core/store/chatStore.ts frontend/src/core/hooks/useChatSessions.ts frontend/src/features/chat/useChatStream.ts frontend/src/features/chat/ChatView.tsx
git commit -m "Replace disabledToolGroups in chatStore with toolsEnabled and autoRead"
```

---

## Task 12: Create the `cockpitStore` cache

**Files:**
- Create: `frontend/src/features/chat/cockpit/cockpitStore.ts`

- [ ] **Step 1: Write the store**

```ts
import { create } from 'zustand'
import { chatApi } from '@/core/api/chat'

type CockpitSessionState = {
  thinking: boolean
  tools: boolean
  autoRead: boolean
}

type CockpitStoreShape = {
  bySession: Record<string, CockpitSessionState>
  hydrateFromServer: (
    sessionId: string,
    state: CockpitSessionState,
  ) => void
  setThinking: (sessionId: string, value: boolean) => Promise<void>
  setTools: (sessionId: string, value: boolean) => Promise<void>
  setAutoRead: (sessionId: string, value: boolean) => Promise<void>
}

export const useCockpitStore = create<CockpitStoreShape>((set, get) => ({
  bySession: {},

  hydrateFromServer: (sessionId, state) =>
    set((s) => ({
      bySession: { ...s.bySession, [sessionId]: state },
    })),

  setThinking: async (sessionId, value) => {
    // Optimistic cache update, then write-through; revert on failure.
    const prev = get().bySession[sessionId]
    if (!prev) return
    set((s) => ({
      bySession: {
        ...s.bySession,
        [sessionId]: { ...prev, thinking: value },
      },
    }))
    try {
      await chatApi.updateSessionReasoning(sessionId, value ? true : null)
    } catch (e) {
      set((s) => ({
        bySession: { ...s.bySession, [sessionId]: prev },
      }))
      throw e
    }
  },

  setTools: async (sessionId, value) => {
    const prev = get().bySession[sessionId]
    if (!prev) return
    set((s) => ({
      bySession: {
        ...s.bySession,
        [sessionId]: { ...prev, tools: value },
      },
    }))
    try {
      await chatApi.updateSessionToggles(sessionId, { tools_enabled: value })
    } catch (e) {
      set((s) => ({
        bySession: { ...s.bySession, [sessionId]: prev },
      }))
      throw e
    }
  },

  setAutoRead: async (sessionId, value) => {
    const prev = get().bySession[sessionId]
    if (!prev) return
    set((s) => ({
      bySession: {
        ...s.bySession,
        [sessionId]: { ...prev, autoRead: value },
      },
    }))
    try {
      await chatApi.updateSessionToggles(sessionId, { auto_read: value })
    } catch (e) {
      set((s) => ({
        bySession: { ...s.bySession, [sessionId]: prev },
      }))
      throw e
    }
  },
}))

export function useCockpitSession(sessionId: string | null): CockpitSessionState | null {
  return useCockpitStore((s) => (sessionId ? s.bySession[sessionId] ?? null : null))
}
```

- [ ] **Step 2: Tsc check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no new errors from the new file.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/cockpit/cockpitStore.ts
git commit -m "Add cockpitStore: session-scoped cache for the three cockpit toggles"
```

---

## Task 13: Create the `CockpitButton` primitive

**Files:**
- Create: `frontend/src/features/chat/cockpit/CockpitButton.tsx`
- Create: `frontend/src/features/chat/cockpit/cockpit.css` (optional, depending on Tailwind-only preference)

- [ ] **Step 1: Write the primitive**

```tsx
import { ReactNode, useState, useRef, useEffect } from 'react'

export type CockpitButtonState =
  | 'active'        // feature is on / running
  | 'idle'          // feature is available and off
  | 'disabled'      // feature is not available in the current context
  | 'playback'      // transient playback / stop state

type Props = {
  icon: ReactNode
  state: CockpitButtonState
  accent?: 'gold' | 'blue' | 'purple' | 'green' | 'neutral'
  label: string                  // native title tooltip (short)
  panel?: ReactNode              // hover / tap panel content
  onClick?: () => void
  ariaLabel?: string
}

const ACCENT_CLASSES: Record<NonNullable<Props['accent']>, string> = {
  gold:   'text-[#d4af37] border-[#d4af37]/35 bg-[#d4af37]/15',
  blue:   'text-[#60a5fa] border-[#3b82f6]/35 bg-[#3b82f6]/15',
  purple: 'text-[#c084fc] border-[#a855f7]/35 bg-[#a855f7]/15',
  green:  'text-[#4ade80] border-[#22c55e]/35 bg-[#22c55e]/15',
  neutral:'text-white/85 border-white/20 bg-white/8',
}

export function CockpitButton({
  icon, state, accent = 'neutral', label, panel, onClick, ariaLabel,
}: Props) {
  const [panelOpen, setPanelOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const closeTimer = useRef<number | null>(null)

  useEffect(() => () => {
    if (closeTimer.current) window.clearTimeout(closeTimer.current)
  }, [])

  const open = () => {
    if (!panel) return
    if (closeTimer.current) window.clearTimeout(closeTimer.current)
    setPanelOpen(true)
  }
  const scheduleClose = () => {
    if (!panel) return
    closeTimer.current = window.setTimeout(() => setPanelOpen(false), 120)
  }

  const base = 'inline-flex items-center justify-center h-9 w-9 rounded-md border transition'
  const disabled = state === 'disabled'
  const classes = disabled
    ? `${base} border-dashed border-white/15 bg-white/2 text-white/30 cursor-not-allowed`
    : state === 'active' || state === 'playback'
      ? `${base} ${ACCENT_CLASSES[accent]}`
      : `${base} border-transparent bg-white/5 text-white/70 hover:bg-white/10`

  return (
    <div
      ref={containerRef}
      className="relative"
      onMouseEnter={open}
      onMouseLeave={scheduleClose}
    >
      <button
        type="button"
        disabled={disabled}
        aria-label={ariaLabel ?? label}
        title={label}
        className={classes}
        onClick={onClick}
      >
        {icon}
      </button>
      {panel && panelOpen && (
        <div
          className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-40 min-w-[260px] max-w-[360px] rounded-lg border border-white/10 bg-[#1a1625] p-3 text-sm shadow-xl"
          onMouseEnter={open}
          onMouseLeave={scheduleClose}
          role="tooltip"
        >
          {panel}
        </div>
      )}
    </div>
  )
}
```

Tailwind classes referenced here should already be available — this project uses Tailwind. If a class like `w-9` is not configured, swap to the configured equivalent; the subagent can check `frontend/tailwind.config.js`.

- [ ] **Step 2: Tsc check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/cockpit/CockpitButton.tsx
git commit -m "Add CockpitButton primitive with sticky hover panel"
```

---

## Task 14: Thinking button adapter

**Files:**
- Create: `frontend/src/features/chat/cockpit/buttons/ThinkingButton.tsx`

- [ ] **Step 1: Write the component**

```tsx
import { CockpitButton } from '../CockpitButton'
import { useCockpitSession, useCockpitStore } from '../cockpitStore'

type Props = {
  sessionId: string
  modelSupportsReasoning: boolean
}

export function ThinkingButton({ sessionId, modelSupportsReasoning }: Props) {
  const cockpit = useCockpitSession(sessionId)
  const setThinking = useCockpitStore((s) => s.setThinking)
  const on = cockpit?.thinking ?? false

  if (!modelSupportsReasoning) {
    return (
      <CockpitButton
        icon="💡"
        state="disabled"
        accent="gold"
        label="Thinking disabled"
        panel={<p className="text-white/70">This model does not support reasoning.</p>}
      />
    )
  }

  return (
    <CockpitButton
      icon="💡"
      state={on ? 'active' : 'idle'}
      accent="gold"
      label={on ? 'Thinking · on' : 'Thinking · off'}
      onClick={() => setThinking(sessionId, !on)}
      panel={
        <div className="text-white/80">
          <div className="font-semibold text-[#d4af37] mb-1">
            Reasoning · {on ? 'on' : 'off'}
          </div>
          <p className="text-xs leading-relaxed">
            The model thinks before it answers. Good for complex questions.
            Some models ignore this when tools are also on.
          </p>
          <div className="mt-2 text-[10px] uppercase tracking-wider text-white/40">
            Session: remembered for this chat.
          </div>
        </div>
      }
    />
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/features/chat/cockpit/buttons/ThinkingButton.tsx
git commit -m "Add cockpit ThinkingButton"
```

---

## Task 15: Tools button adapter

**Files:**
- Create: `frontend/src/features/chat/cockpit/buttons/ToolsButton.tsx`

- [ ] **Step 1: Write the component**

```tsx
import { CockpitButton } from '../CockpitButton'
import { useCockpitSession, useCockpitStore } from '../cockpitStore'

type ToolGroup = { id: string; label: string; kind: 'web' | 'mcp' | 'integration' }

type Props = {
  sessionId: string
  availableGroups: ToolGroup[]      // groups only — never tool names
}

export function ToolsButton({ sessionId, availableGroups }: Props) {
  const cockpit = useCockpitSession(sessionId)
  const setTools = useCockpitStore((s) => s.setTools)
  const on = cockpit?.tools ?? false
  const hasAny = availableGroups.length > 0

  if (!hasAny) {
    return (
      <CockpitButton
        icon="🔧"
        state="disabled"
        accent="neutral"
        label="No tools available"
        panel={
          <p className="text-white/70">
            No tools available. Enable web search or connect an integration in persona settings.
          </p>
        }
      />
    )
  }

  return (
    <CockpitButton
      icon="🔧"
      state={on ? 'active' : 'idle'}
      accent="neutral"
      label={on ? `Tools · on · ${availableGroups.length} available` : 'Tools · off'}
      onClick={() => setTools(sessionId, !on)}
      panel={
        <div className="text-white/80">
          <div className="font-semibold mb-2">
            Tools · {on ? 'on' : 'off'} · {availableGroups.length} available
          </div>
          <ul className="text-xs space-y-1">
            {availableGroups.map((g) => (
              <li key={g.id}>
                <span className="text-white/40 uppercase tracking-wider text-[10px] mr-2">
                  {g.kind}
                </span>
                {g.label}
              </li>
            ))}
          </ul>
        </div>
      }
    />
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/features/chat/cockpit/buttons/ToolsButton.tsx
git commit -m "Add cockpit ToolsButton with groups-only panel"
```

---

## Task 16: Integrations button with popover

**Files:**
- Create: `frontend/src/features/chat/cockpit/buttons/IntegrationsButton.tsx`

- [ ] **Step 1: Locate the existing emergency-stop handler**

Run: `rg -n "emergencyStop" frontend/src/features/integrations/`

- [ ] **Step 2: Write the component**

```tsx
import { CockpitButton } from '../CockpitButton'
import { useIntegrationsStore } from '@/features/integrations/store'
// Adjust import path above to match the actual store location

type Props = {
  activePersonaIntegrationIds: string[]
}

export function IntegrationsButton({ activePersonaIntegrationIds }: Props) {
  const configs = useIntegrationsStore((s) => s.configs)
  const health = useIntegrationsStore((s) => s.healthStatus)
  const emergencyStop = useIntegrationsStore((s) => s.emergencyStop)
  const emergencyStopAll = useIntegrationsStore((s) => s.emergencyStopAll)

  const active = activePersonaIntegrationIds
    .map((id) => configs[id])
    .filter((c): c is NonNullable<typeof c> => Boolean(c))

  if (active.length === 0) {
    return (
      <CockpitButton
        icon="🔌"
        state="disabled"
        accent="purple"
        label="No integrations active"
        panel={
          <p className="text-white/70">
            No integrations active. Connect e.g. Lovense in persona settings.
          </p>
        }
      />
    )
  }

  return (
    <CockpitButton
      icon="🔌"
      state="active"
      accent="purple"
      label={`${active.length} integration${active.length === 1 ? '' : 's'} active`}
      panel={
        <div className="text-white/85">
          <div className="text-[10px] uppercase tracking-wider text-white/40 mb-2">
            Active integrations
          </div>
          {active.map((config) => {
            const status = health[config.id]
            return (
              <div
                key={config.id}
                className="flex items-center justify-between py-2 border-b border-white/5 last:border-b-0"
              >
                <div>
                  <div>{config.displayName}</div>
                  <div className="text-[10px] text-[#4ade80]/80">
                    {status?.healthy ? '● connected · healthy' : '○ check connection'}
                  </div>
                </div>
                <button
                  type="button"
                  className="text-[11px] px-2 py-1 rounded border border-red-500/40 bg-red-500/15 text-red-300"
                  onClick={() => emergencyStop(config)}
                >
                  Stop
                </button>
              </div>
            )
          })}
          <button
            type="button"
            className="w-full text-xs mt-3 px-3 py-2 rounded border border-red-500/45 bg-red-500/20 text-red-200"
            onClick={() => emergencyStopAll()}
          >
            Emergency stop — all
          </button>
        </div>
      }
    />
  )
}
```

Note: the exact property names on `configs` and the signature of `emergencyStopAll` may differ from my sketch. The subagent should run `sed -n` / `grep` on the actual integrations store and adjust. If `emergencyStopAll` does not exist, add it: iterate over active configs and call `emergencyStop` on each, plus cancel in-flight TTS via whatever hook today's standalone emergency-stop button uses.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/cockpit/buttons/IntegrationsButton.tsx
git commit -m "Add cockpit IntegrationsButton with per-integration stop and global emergency stop"
```

---

## Task 17: Voice button — the magic button state machine

**Files:**
- Create: `frontend/src/features/chat/cockpit/buttons/VoiceButton.tsx`

- [ ] **Step 1: Locate voice pipeline and conversation-mode stores**

Run: `rg -n "useVoicePipeline\|useConversationModeStore" frontend/src/features/voice/`

- [ ] **Step 2: Derive the state**

Write a pure helper first — easier to test:

```ts
// frontend/src/features/chat/cockpit/buttons/_voiceState.ts
export type VoiceUIState =
  | { kind: 'normal-off' }       // auto-read off, nothing playing
  | { kind: 'normal-on' }        // auto-read on, nothing playing
  | { kind: 'normal-playing' }   // TTS playing (normal chat)
  | { kind: 'live-mic-on' }
  | { kind: 'live-mic-muted' }
  | { kind: 'live-playing' }
  | { kind: 'disabled' }

export function deriveVoiceUIState({
  personaHasVoice,
  liveMode,
  ttsPlaying,
  autoRead,
  micMuted,
}: {
  personaHasVoice: boolean
  liveMode: boolean
  ttsPlaying: boolean
  autoRead: boolean
  micMuted: boolean
}): VoiceUIState {
  if (!personaHasVoice) return { kind: 'disabled' }
  if (liveMode) {
    if (ttsPlaying) return { kind: 'live-playing' }
    return micMuted ? { kind: 'live-mic-muted' } : { kind: 'live-mic-on' }
  }
  if (ttsPlaying) return { kind: 'normal-playing' }
  return autoRead ? { kind: 'normal-on' } : { kind: 'normal-off' }
}
```

- [ ] **Step 3: Write a unit test for the helper**

Create `frontend/src/features/chat/cockpit/buttons/__tests__/_voiceState.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { deriveVoiceUIState } from '../_voiceState'

describe('deriveVoiceUIState', () => {
  const base = {
    personaHasVoice: true,
    liveMode: false,
    ttsPlaying: false,
    autoRead: false,
    micMuted: false,
  }

  it('disabled when persona has no voice', () => {
    expect(deriveVoiceUIState({ ...base, personaHasVoice: false }))
      .toEqual({ kind: 'disabled' })
  })

  it('normal off', () => {
    expect(deriveVoiceUIState(base)).toEqual({ kind: 'normal-off' })
  })

  it('normal on', () => {
    expect(deriveVoiceUIState({ ...base, autoRead: true }))
      .toEqual({ kind: 'normal-on' })
  })

  it('normal playing', () => {
    expect(deriveVoiceUIState({ ...base, ttsPlaying: true }))
      .toEqual({ kind: 'normal-playing' })
  })

  it('live mic on', () => {
    expect(deriveVoiceUIState({ ...base, liveMode: true }))
      .toEqual({ kind: 'live-mic-on' })
  })

  it('live mic muted', () => {
    expect(deriveVoiceUIState({ ...base, liveMode: true, micMuted: true }))
      .toEqual({ kind: 'live-mic-muted' })
  })

  it('live playing — mic state does not influence', () => {
    expect(deriveVoiceUIState({
      ...base, liveMode: true, ttsPlaying: true, micMuted: true,
    })).toEqual({ kind: 'live-playing' })
  })
})
```

Run: `cd frontend && pnpm vitest run src/features/chat/cockpit/buttons/__tests__/_voiceState.test.ts`
Expected: 7 PASS.

- [ ] **Step 4: Write the component**

```tsx
import { CockpitButton } from '../CockpitButton'
import { useCockpitSession, useCockpitStore } from '../cockpitStore'
import { useVoicePipeline } from '@/features/voice/stores/voicePipelineStore'
import { useConversationModeStore } from '@/features/voice/stores/conversationModeStore'
import { deriveVoiceUIState } from './_voiceState'

type Props = {
  sessionId: string
  personaHasVoice: boolean
  voiceSummary: {
    ttsProvider: string
    voice: string
    mode: string
    sttProvider: string
    sensitivity: string
  } | null
}

export function VoiceButton({ sessionId, personaHasVoice, voiceSummary }: Props) {
  const cockpit = useCockpitSession(sessionId)
  const setAutoRead = useCockpitStore((s) => s.setAutoRead)
  const voice = useVoicePipeline()
  const live = useConversationModeStore()

  const ttsPlaying = voice.state.phase === 'speaking'
  const autoRead = cockpit?.autoRead ?? false
  const micMuted = live.micMuted ?? false

  const ui = deriveVoiceUIState({
    personaHasVoice,
    liveMode: live.active,
    ttsPlaying,
    autoRead,
    micMuted,
  })

  const iconFor: Record<typeof ui.kind, string> = {
    'disabled': '🔈',
    'normal-off': '🔈',
    'normal-on': '🔊',
    'normal-playing': '⏹',
    'live-mic-on': '🎤',
    'live-mic-muted': '🎙',  // swap to a muted-mic SVG when available
    'live-playing': '⏹',
  }

  const onClick = () => {
    switch (ui.kind) {
      case 'normal-off':      return setAutoRead(sessionId, true)
      case 'normal-on':       return setAutoRead(sessionId, false)
      case 'normal-playing':  return voice.stopPlayback()
      case 'live-mic-on':     return live.setMicMuted(true)
      case 'live-mic-muted':  return live.setMicMuted(false)
      case 'live-playing':    return voice.stopPlayback()  // mic state unchanged
      case 'disabled':        return
    }
  }

  if (ui.kind === 'disabled') {
    return (
      <CockpitButton
        icon={iconFor[ui.kind]}
        state="disabled"
        accent="blue"
        label="Voice unavailable"
        panel={
          <p className="text-white/70">
            This persona has no voice. Pick a TTS provider and a voice in persona settings.
          </p>
        }
      />
    )
  }

  const stateClass =
    ui.kind.endsWith('-playing') ? 'playback' :
    (ui.kind === 'normal-off' || ui.kind === 'live-mic-muted') ? 'idle' : 'active'

  return (
    <CockpitButton
      icon={iconFor[ui.kind]}
      state={stateClass as 'playback' | 'idle' | 'active'}
      accent="blue"
      label={labelFor(ui.kind)}
      onClick={onClick}
      panel={
        <div className="text-white/85">
          <div className="font-semibold text-[#60a5fa] mb-2">{statusFor(ui.kind, autoRead)}</div>
          {voiceSummary && (
            <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
              <div className="text-white/50">TTS</div><div>{voiceSummary.ttsProvider}</div>
              <div className="text-white/50">Voice</div><div>{voiceSummary.voice}</div>
              <div className="text-white/50">Mode</div><div>{voiceSummary.mode}</div>
              <div className="text-white/50">STT</div><div>{voiceSummary.sttProvider}</div>
              <div className="text-white/50">Sensitivity</div><div>{voiceSummary.sensitivity}</div>
            </div>
          )}
        </div>
      }
    />
  )
}

function labelFor(kind: Exclude<ReturnType<typeof deriveVoiceUIState>['kind'], 'disabled'>): string {
  switch (kind) {
    case 'normal-off':     return 'Auto-read · off'
    case 'normal-on':      return 'Auto-read · on'
    case 'normal-playing': return 'Stop playback'
    case 'live-mic-on':    return 'Mic is listening'
    case 'live-mic-muted': return 'Mic is muted'
    case 'live-playing':   return 'Interrupt'
  }
}

function statusFor(kind: string, autoRead: boolean): string {
  if (kind === 'normal-off' || kind === 'normal-on') return `Auto-read · ${autoRead ? 'on' : 'off'}`
  if (kind === 'normal-playing') return 'Playing'
  if (kind === 'live-mic-on') return 'Mic is listening'
  if (kind === 'live-mic-muted') return 'Mic is muted'
  if (kind === 'live-playing') return 'Interrupt'
  return ''
}
```

If `voicePipelineStore` does not expose `stopPlayback` or `conversationModeStore` does not expose `micMuted`/`setMicMuted`, the subagent should **add those public setters** in their respective stores rather than reach into internals. This is the right place to formalise those affordances — they're foundational for the magic button.

- [ ] **Step 5: Run the vitest**

Run: `cd frontend && pnpm vitest run src/features/chat/cockpit/buttons/__tests__/_voiceState.test.ts`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/chat/cockpit/buttons/_voiceState.ts \
        frontend/src/features/chat/cockpit/buttons/VoiceButton.tsx \
        frontend/src/features/chat/cockpit/buttons/__tests__/ \
        frontend/src/features/voice/stores/
git commit -m "Add cockpit VoiceButton with 6-state machine"
```

---

## Task 18: Live button adapter

**Files:**
- Create: `frontend/src/features/chat/cockpit/buttons/LiveButton.tsx`

- [ ] **Step 1: Write the component**

```tsx
import { CockpitButton } from '../CockpitButton'
import { useConversationModeStore } from '@/features/voice/stores/conversationModeStore'

type Props = {
  canEnterLive: boolean
  disabledReason: 'no-voice' | 'not-allowed' | null
}

export function LiveButton({ canEnterLive, disabledReason }: Props) {
  const live = useConversationModeStore()
  const active = live.active

  if (!canEnterLive) {
    return (
      <CockpitButton
        icon="🎙"
        state="disabled"
        accent="green"
        label="Live mode unavailable"
        panel={
          <p className="text-white/70">
            {disabledReason === 'no-voice'
              ? 'Live mode needs TTS and STT on the persona.'
              : 'Live mode is not enabled for your account.'}
          </p>
        }
      />
    )
  }

  return (
    <CockpitButton
      icon="🎙"
      state={active ? 'active' : 'idle'}
      accent="green"
      label={active ? 'Live · on' : 'Live · off'}
      onClick={() => (active ? live.leave() : live.enter())}
      panel={
        <div className="text-white/80">
          <div className="font-semibold text-[#4ade80] mb-1">Continuous voice mode</div>
          <p className="text-xs leading-relaxed">
            Hands-free conversation. The mic stays open, the assistant speaks answers
            aloud. You can interrupt by clicking the voice button. Best for long sessions.
          </p>
        </div>
      }
    />
  )
}
```

Method names on `conversationModeStore` (`enter`, `leave`) may differ — match the existing API.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/features/chat/cockpit/buttons/LiveButton.tsx
git commit -m "Add cockpit LiveButton"
```

---

## Task 19: Attach / Camera / Browse adapter buttons

**Files:**
- Create: `frontend/src/features/chat/cockpit/buttons/AttachmentButtons.tsx`

These are thin wrappers around the existing handlers and don't need hover panels.

- [ ] **Step 1: Locate existing handlers**

Run: `rg -n "onAttachFile\|onCamera\|onBrowseUploads\|attachFile\|openCamera" frontend/src/features/chat/`
Expected: handlers used by the current mobile tool tray — these are the ones to reuse.

- [ ] **Step 2: Write the components**

```tsx
import { CockpitButton } from '../CockpitButton'

type Props = {
  onClick: () => void
  disabled?: boolean
  disabledReason?: string
}

export function AttachButton({ onClick, disabled, disabledReason }: Props) {
  return (
    <CockpitButton
      icon="📎"
      state={disabled ? 'disabled' : 'idle'}
      label={disabled ? (disabledReason ?? 'Attachments unavailable') : 'Attach'}
      onClick={disabled ? undefined : onClick}
      panel={disabled && disabledReason ? <p className="text-white/70">{disabledReason}</p> : undefined}
    />
  )
}

export function CameraButton({ onClick, disabled, disabledReason }: Props) {
  return (
    <CockpitButton
      icon="📷"
      state={disabled ? 'disabled' : 'idle'}
      label={disabled ? (disabledReason ?? 'Camera unavailable') : 'Camera'}
      onClick={disabled ? undefined : onClick}
      panel={disabled && disabledReason ? <p className="text-white/70">{disabledReason}</p> : undefined}
    />
  )
}

export function BrowseButton({ onClick }: { onClick: () => void }) {
  return (
    <CockpitButton
      icon="🗂"
      state="idle"
      label="Browse uploads"
      onClick={onClick}
    />
  )
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/cockpit/buttons/AttachmentButtons.tsx
git commit -m "Add cockpit attachment buttons"
```

---

## Task 20: Mobile info modal

**Files:**
- Create: `frontend/src/features/chat/cockpit/MobileInfoModal.tsx`

- [ ] **Step 1: Write the modal**

```tsx
import { ReactNode, useState } from 'react'

type Section = {
  id: 'thinking' | 'tools' | 'integrations' | 'voice' | 'live'
  icon: string
  title: string
  statusLine: string
  active: boolean
  body: ReactNode
}

type Props = {
  open: boolean
  onClose: () => void
  sections: Section[]
}

export function MobileInfoModal({ open, onClose, sections }: Props) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>(
    Object.fromEntries(sections.filter((s) => s.active).map((s) => [s.id, true])),
  )
  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 flex items-end"
      onClick={onClose}
    >
      <div
        className="w-full max-h-[80vh] overflow-y-auto bg-[#0f0d16] rounded-t-xl border-t border-white/10 p-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="text-[11px] uppercase tracking-[0.1em] text-white/50 mb-3">
          Cockpit status
        </div>
        {sections.map((s) => {
          const isOpen = expanded[s.id]
          return (
            <div key={s.id} className="border-b border-white/5 py-2.5">
              <button
                type="button"
                onClick={() => setExpanded((e) => ({ ...e, [s.id]: !isOpen }))}
                className="w-full flex justify-between items-center text-sm"
              >
                <span className={s.active ? 'text-white/90' : 'text-white/70'}>
                  {s.icon} {s.title}
                </span>
                <span className="text-xs text-white/50">
                  {s.statusLine} {isOpen ? '▴' : '▾'}
                </span>
              </button>
              {isOpen && <div className="mt-2 pl-1 text-xs text-white/75">{s.body}</div>}
            </div>
          )
        })}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/features/chat/cockpit/MobileInfoModal.tsx
git commit -m "Add cockpit MobileInfoModal"
```

---

## Task 21: CockpitBar container

**Files:**
- Create: `frontend/src/features/chat/cockpit/CockpitBar.tsx`

- [ ] **Step 1: Write the bar**

```tsx
import { useState } from 'react'
import { useViewport } from '@/core/hooks/useViewport'
import { ThinkingButton } from './buttons/ThinkingButton'
import { ToolsButton } from './buttons/ToolsButton'
import { IntegrationsButton } from './buttons/IntegrationsButton'
import { VoiceButton } from './buttons/VoiceButton'
import { LiveButton } from './buttons/LiveButton'
import { AttachButton, CameraButton, BrowseButton } from './buttons/AttachmentButtons'
import { MobileInfoModal } from './MobileInfoModal'
import { CockpitButton } from './CockpitButton'

type Props = {
  sessionId: string
  // wiring for each button — exact shapes mirror the adapter props
  modelSupportsAttachments: boolean
  modelSupportsReasoning: boolean
  availableToolGroups: { id: string; label: string; kind: 'web' | 'mcp' | 'integration' }[]
  activePersonaIntegrationIds: string[]
  personaHasVoice: boolean
  voiceSummary: Parameters<typeof VoiceButton>[0]['voiceSummary']
  liveAvailability: { canEnterLive: boolean; reason: 'no-voice' | 'not-allowed' | null }
  handlers: {
    attach: () => void
    camera: () => void
    browse: () => void
  }
}

function Sep() {
  return <span className="px-1 text-white/20">│</span>
}

export function CockpitBar(props: Props) {
  const { isMobile } = useViewport()
  const [infoOpen, setInfoOpen] = useState(false)

  return (
    <div className="flex flex-wrap items-center gap-1.5 px-3 py-2 bg-[#0f0d16] rounded-lg">
      <AttachButton onClick={props.handlers.attach} disabled={!props.modelSupportsAttachments} disabledReason="This model does not accept attachments." />
      {isMobile && <CameraButton onClick={props.handlers.camera} disabled={!props.modelSupportsAttachments} disabledReason="This model does not accept attachments." />}
      <BrowseButton onClick={props.handlers.browse} />
      <Sep />
      <ThinkingButton sessionId={props.sessionId} modelSupportsReasoning={props.modelSupportsReasoning} />
      <ToolsButton sessionId={props.sessionId} availableGroups={props.availableToolGroups} />
      <Sep />
      <IntegrationsButton activePersonaIntegrationIds={props.activePersonaIntegrationIds} />
      <Sep />
      <VoiceButton sessionId={props.sessionId} personaHasVoice={props.personaHasVoice} voiceSummary={props.voiceSummary} />
      <Sep />
      <LiveButton canEnterLive={props.liveAvailability.canEnterLive} disabledReason={props.liveAvailability.reason} />
      {isMobile && (
        <>
          <Sep />
          <CockpitButton
            icon="ⓘ"
            state="idle"
            accent="neutral"
            label="Status info"
            onClick={() => setInfoOpen(true)}
          />
        </>
      )}

      {isMobile && (
        <MobileInfoModal
          open={infoOpen}
          onClose={() => setInfoOpen(false)}
          sections={[/* the parent computes this for brevity, or CockpitBar composes from props */]}
        />
      )}
    </div>
  )
}
```

The exact mobile info modal sections are computed from the same props already passed in; the subagent can either (a) build the sections array inside `CockpitBar` by duplicating the panel content from each button, or (b) factor each panel's content into a shared helper. (b) is cleaner and ensures parity with the hover panels.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/features/chat/cockpit/CockpitBar.tsx
git commit -m "Add CockpitBar container with responsive ordering and mobile info modal"
```

---

## Task 22: Wire CockpitBar into ChatView, remove old toolbar code

**Files:**
- Modify: `frontend/src/features/chat/ChatView.tsx:1247-1344` (old toolbar block and mobile wrench tray)
- Modify: `frontend/src/features/chat/ChatView.tsx:206-207, 381-382, 1039` (any remaining `disabledToolGroups` / `reasoningOverride` props passed to `ChatInput`)
- Delete: `frontend/src/features/chat/ToolToggles.tsx`

- [ ] **Step 1: Hydrate cockpitStore on chat open**

Find the block around `ChatView.tsx:381-382` where session state is loaded. Replace or augment the existing `setReasoningOverride(session.reasoning_override ?? null)` etc. with a call to hydrate the cockpit cache:

```ts
import { useCockpitStore } from './cockpit/cockpitStore'
// ...
useCockpitStore.getState().hydrateFromServer(session.id, {
  thinking: session.reasoning_override === true,
  tools: session.tools_enabled,
  autoRead: session.auto_read,
})
```

- [ ] **Step 2: Replace the toolbar JSX**

Find the two blocks at lines 1247-1344:
- Desktop toolbar rendering `ToolToggles`
- Mobile wrench-tray block with `mobileToolsOpen` state

Replace both with one render of `<CockpitBar {...props} />`. Collect the props from existing local values — models, persona data, handlers — the same data today's two toolbars read.

- [ ] **Step 3: Remove `mobileToolsOpen` state**

Any `useState` for `mobileToolsOpen` and its handlers can be deleted.

- [ ] **Step 4: Delete the old ToolToggles file**

```bash
git rm frontend/src/features/chat/ToolToggles.tsx
```

- [ ] **Step 5: Build check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no errors. Then `cd frontend && pnpm run build`
Expected: build success.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/chat/ChatView.tsx
git commit -m "Replace legacy composer toolbar with CockpitBar"
```

---

## Task 23: Remove the standalone integration emergency-stop button

**Files:**
- Modify: `frontend/src/features/chat/ChatView.tsx` — locate the `<ChatIntegrationsPanel />` render (run `rg -n "ChatIntegrationsPanel" frontend/src/features/chat/ChatView.tsx`)

- [ ] **Step 1: Inspect the panel**

Open `frontend/src/features/integrations/ChatIntegrationsPanel.tsx` lines 28-100. The per-integration stop logic is what we've already moved into the cockpit Integrations button.

- [ ] **Step 2: Remove the panel render from `ChatView.tsx`**

If the panel is still referenced elsewhere (e.g. a settings screen), keep the component file. Otherwise, delete it:

```bash
# inspect callers
rg -n "ChatIntegrationsPanel" frontend/src/
```

If no callers remain after the ChatView removal, `git rm` the file.

- [ ] **Step 3: Build check**

Run: `cd frontend && pnpm run build`
Expected: success.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "Remove standalone integration emergency-stop panel from composer"
```

---

## Task 24: Decide on the topbar ConversationModeButton

**Files:**
- Inspect: `frontend/src/features/voice/components/ConversationModeButton.tsx`
- Possibly modify: wherever it is rendered in the top bar (run `rg -n "ConversationModeButton" frontend/src/`)

The spec says: move its function into the cockpit Live button, and revisit whether to keep the topbar placement after first user testing. For this implementation, **keep the topbar button** — both surfaces can co-exist short-term, and the cockpit Live button is additive, not replacing.

- [ ] **Step 1: Verify both surfaces call into the same `conversationModeStore`**

Run: `rg -n "useConversationModeStore" frontend/src/features/voice/components/ConversationModeButton.tsx frontend/src/features/chat/cockpit/buttons/LiveButton.tsx`
Expected: both import the same store. If either has duplicated local state, fix it.

- [ ] **Step 2: No changes needed if both use the store**

Note this decision in the PR description when opening the PR.

- [ ] **Step 3: (No commit if no change.)**

---

## Task 25: Build + type check + manual verification

**Files:** none (verification only)

- [ ] **Step 1: Frontend build**

Run: `cd frontend && pnpm run build`
Expected: build succeeds with no TypeScript errors.

- [ ] **Step 2: Backend compile check**

Run: `uv run python -m py_compile backend/modules/chat/_repository.py backend/modules/chat/_handlers.py backend/modules/chat/_orchestrator.py backend/modules/chat/_handlers_ws.py backend/modules/chat/_toggle_defaults.py shared/dtos/chat.py shared/events/chat.py`
Expected: no output.

- [ ] **Step 3: Backend unit tests**

Run: `uv run pytest tests/backend/chat/test_toggle_defaults.py tests/migrations/test_session_toggles.py -v`
Expected: all PASS.

- [ ] **Step 4: Frontend unit test**

Run: `cd frontend && pnpm vitest run src/features/chat/cockpit/buttons/__tests__/_voiceState.test.ts`
Expected: 7 PASS.

- [ ] **Step 5: Manual verification on real device**

Work through the **Manual verification** section of the spec (`devdocs/superpowers/specs/2026-04-24-cockpit-toolbar-redesign-design.md`) items 1 through 10, ticking each off in the PR description.

- [ ] **Step 6: Run the migration against a staging-like database**

If a staging dump is available, restore it to a local MongoDB and run:

```bash
uv run python -m backend.migrations.2026_04_24_session_toggles
```

Verify:
1. Sessions that had `disabled_tool_groups` no longer have it.
2. Every session has `tools_enabled` and `auto_read` fields.
3. Running the script a second time reports 0 migrated / N skipped.

---

## Self-review checklist

Before declaring this plan done, the author re-checks the spec:

- ✅ Cockpit row layout (desktop and mobile): Tasks 19, 21, 22
- ✅ Always-visible disabled buttons with "activate this first": Every button task
- ✅ `cockpitStore` cache mirroring server state: Task 12
- ✅ Persona defaults computed server-side at session create: Tasks 5, 9
- ✅ Thinking / Tools / Auto-Read session toggles: Tasks 14, 15, 17
- ✅ Magic voice button with six states: Task 17
- ✅ Integrations popover with emergency stop: Task 16
- ✅ Live button: Task 18
- ✅ Attachment buttons (Desktop: attach+browse; Mobile: attach+camera+browse): Tasks 19, 21
- ✅ Mobile info modal: Tasks 20, 21
- ✅ English strings everywhere: enforced throughout
- ✅ Backend fields + migration + orchestrator gate + voice auto-play gate: Tasks 1-9
- ✅ Removal of legacy UI (ToolToggles, mobile wrench tray, standalone emergency stop): Tasks 22, 23
- ✅ Known unknown (thinking+tools conflict) untouched, as specified

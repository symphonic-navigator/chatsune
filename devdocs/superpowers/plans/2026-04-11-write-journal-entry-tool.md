# `write_journal_entry` Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a server-side tool `write_journal_entry` that lets a persona record an uncommitted journal entry about the user mid-conversation, fan out a dedicated event, and surface an info toast in the frontend.

**Architecture:** New tool group `journal` (server-side, toggleable) with a single tool. The executor calls a new public API in the `memory` module that creates the entry via the existing repository and publishes a new event `MemoryEntryAuthoredByPersonaEvent`. The chat orchestrator injects `_session_id`, `_persona_id`, `_persona_name`, `_correlation_id` into tool arguments. The frontend subscribes to the new topic, adds the entry to the journal store, and raises an info toast.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, MongoDB (motor), pytest/pytest-asyncio, React/TSX, zustand.

**Spec:** `docs/superpowers/specs/2026-04-11-write-journal-entry-tool-design.md`

---

## File Structure

**Backend — create:**
- none

**Backend — modify:**
- `shared/topics.py` — add new topic constant
- `shared/events/memory.py` — add new event class
- `backend/ws/event_bus.py` — add fan-out rule for the new topic
- `backend/modules/memory/__init__.py` — add `write_persona_authored_entry` public API
- `backend/modules/tools/_executors.py` — add `JournalToolExecutor` class
- `backend/modules/tools/_registry.py` — register `journal` tool group
- `backend/modules/chat/_orchestrator.py` — inject persona context into tool args

**Backend — tests:**
- `tests/modules/tools/test_journal_tool_executor.py` — unit tests for the executor (validation + happy path)
- `tests/modules/memory/test_persona_authored_entry.py` — integration test against real Mongo

**Frontend — modify:**
- `frontend/src/core/types/events.ts` — add new topic constant
- `frontend/src/features/memory/useMemoryEvents.ts` — handle new event, show info toast

---

## Task 1: Add shared topic constant and event class

**Files:**
- Modify: `shared/topics.py`
- Modify: `shared/events/memory.py`
- Modify: `frontend/src/core/types/events.ts`

- [ ] **Step 1: Add topic constant to backend**

Open `shared/topics.py` and, inside the `class Topics:` block, right after the line:

```python
    MEMORY_ENTRY_AUTO_COMMITTED = "memory.entry.auto_committed"
```

add:

```python
    MEMORY_ENTRY_AUTHORED_BY_PERSONA = "memory.entry.authored_by_persona"
```

- [ ] **Step 2: Add event class to backend**

Open `shared/events/memory.py` and append a new class after `MemoryEntryAutoCommittedEvent`:

```python
class MemoryEntryAuthoredByPersonaEvent(BaseModel):
    type: str = "memory.entry.authored_by_persona"
    entry: JournalEntryDto
    persona_name: str
    correlation_id: str
    timestamp: datetime
```

The `persona_name` is carried in the payload so the frontend can show a toast like `"{persona_name} has added a journal note."` without a follow-up lookup against React state.

- [ ] **Step 3: Add topic constant to frontend**

Open `frontend/src/core/types/events.ts` and, inside the `Topics` object literal, right after the line:

```typescript
  MEMORY_ENTRY_AUTO_COMMITTED: "memory.entry.auto_committed",
```

add:

```typescript
  MEMORY_ENTRY_AUTHORED_BY_PERSONA: "memory.entry.authored_by_persona",
```

- [ ] **Step 4: Syntax-check backend files**

Run:

```bash
uv run python -m py_compile shared/topics.py shared/events/memory.py
```

Expected: no output (clean exit).

- [ ] **Step 5: Commit**

```bash
git add shared/topics.py shared/events/memory.py frontend/src/core/types/events.ts
git commit -m "Add MemoryEntryAuthoredByPersona topic and event

New contract for the persona-authored journal entry flow. The
event carries the full JournalEntryDto and the persona's display
name so the frontend can raise a toast without an extra lookup."
```

---

## Task 2: Register fan-out rule for the new topic

**Files:**
- Modify: `backend/ws/event_bus.py`

The new topic must be added to `_FANOUT`, otherwise `EventBus._fan_out` logs `"no fan-out rule for topic … — event persisted but not delivered"` and the frontend never receives it. It follows the same rule as every other memory entry event: target user only, no role broadcast.

- [ ] **Step 1: Add fan-out entry**

Open `backend/ws/event_bus.py`. Inside the `_FANOUT` dict, locate the memory section that contains:

```python
    Topics.MEMORY_ENTRY_AUTO_COMMITTED: ([], True),
```

and add the following line directly below it:

```python
    Topics.MEMORY_ENTRY_AUTHORED_BY_PERSONA: ([], True),
```

- [ ] **Step 2: Syntax-check**

Run:

```bash
uv run python -m py_compile backend/ws/event_bus.py
```

Expected: clean exit.

- [ ] **Step 3: Commit**

```bash
git add backend/ws/event_bus.py
git commit -m "Register fan-out rule for memory.entry.authored_by_persona

Target-user delivery only, same rule as the other memory entry
lifecycle events."
```

---

## Task 3: Add `write_persona_authored_entry` public API to memory module

**Files:**
- Modify: `backend/modules/memory/__init__.py`
- Test: `tests/modules/memory/test_persona_authored_entry.py`

This function is the single way the `tools` module is allowed to create a persona-authored journal entry — the `memory` module's internals stay private.

- [ ] **Step 1: Write the failing integration test**

Create `tests/modules/memory/test_persona_authored_entry.py`:

```python
import pytest
import pytest_asyncio

from backend.database import connect_db, disconnect_db, get_db, get_redis
from backend.modules.memory import (
    MemoryRepository,
    write_persona_authored_entry,
)
from backend.ws.event_bus import EventBus, set_event_bus
from backend.ws.manager import ConnectionManager, set_manager
from shared.topics import Topics

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def wired_bus(clean_db):
    await connect_db()
    manager = ConnectionManager()
    set_manager(manager)
    bus = EventBus(redis=get_redis(), manager=manager)
    set_event_bus(bus)
    try:
        yield bus
    finally:
        await disconnect_db()


async def test_write_persona_authored_entry_persists_and_publishes(wired_bus):
    captured: list[dict] = []
    wired_bus.subscribe(
        Topics.MEMORY_ENTRY_AUTHORED_BY_PERSONA,
        lambda payload: captured.append(payload),
    )

    dto = await write_persona_authored_entry(
        user_id="user-1",
        persona_id="persona-1",
        persona_name="Aria",
        content="Chris values the principle of least astonishment.",
        category="value",
        source_session_id="session-1",
        correlation_id="corr-1",
    )

    # DTO is correctly shaped
    assert dto.persona_id == "persona-1"
    assert dto.content == "Chris values the principle of least astonishment."
    assert dto.category == "value"
    assert dto.state == "uncommitted"
    assert dto.is_correction is False
    assert dto.auto_committed is False

    # Entry actually exists in Mongo with state "uncommitted"
    repo = MemoryRepository(get_db())
    entries = await repo.list_journal_entries(
        "user-1", "persona-1", state="uncommitted",
    )
    assert len(entries) == 1
    assert entries[0]["content"] == (
        "Chris values the principle of least astonishment."
    )
    assert entries[0]["source_session_id"] == "session-1"

    # Event was published with persona_name and entry DTO
    assert len(captured) == 1
    payload = captured[0]
    assert payload["persona_name"] == "Aria"
    assert payload["correlation_id"] == "corr-1"
    assert payload["entry"]["id"] == dto.id
    assert payload["entry"]["content"] == dto.content
    assert payload["entry"]["state"] == "uncommitted"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/modules/memory/test_persona_authored_entry.py -v
```

Expected: FAIL (ImportError on `write_persona_authored_entry`, which does not yet exist).

- [ ] **Step 3: Implement `write_persona_authored_entry`**

Open `backend/modules/memory/__init__.py` and replace the file body with the following (keeping all existing exports intact):

```python
# Memory module public API
import os
from datetime import UTC, datetime

from backend.modules.memory._handlers import router
from backend.modules.memory._repository import MemoryRepository
from backend.modules.memory._assembly import assemble_memory_context
from shared.dtos.memory import JournalEntryDto
from shared.events.memory import MemoryEntryAuthoredByPersonaEvent
from shared.topics import Topics


async def init_indexes(db) -> None:
    repo = MemoryRepository(db)
    await repo.create_indexes()


async def get_memory_context(user_id: str, persona_id: str) -> str | None:
    """Load memory body + journal entries and assemble the RAG context block."""
    from backend.database import get_db

    repo = MemoryRepository(get_db())
    body_doc = await repo.get_current_memory_body(user_id, persona_id)
    memory_body = body_doc["content"] if body_doc else None
    committed = await repo.list_journal_entries(user_id, persona_id, state="committed")
    uncommitted = await repo.list_journal_entries(user_id, persona_id, state="uncommitted")

    max_tokens = int(os.environ.get("MEMORY_RAG_MAX_TOKENS", "6000"))

    return assemble_memory_context(
        memory_body=memory_body,
        committed_entries=committed,
        uncommitted_entries=uncommitted,
        max_tokens=max_tokens,
    )


async def delete_by_persona(user_id: str, persona_id: str) -> int:
    """Delete all memory data for a persona."""
    from backend.database import get_db

    repo = MemoryRepository(get_db())
    return await repo.delete_by_persona(user_id, persona_id)


async def write_persona_authored_entry(
    *,
    user_id: str,
    persona_id: str,
    persona_name: str,
    content: str,
    category: str,
    source_session_id: str,
    correlation_id: str,
) -> JournalEntryDto:
    """Create an uncommitted journal entry written by the persona itself.

    Used by the ``write_journal_entry`` server-side tool. Creates the
    entry via the repository, loads it back as a ``JournalEntryDto`` and
    publishes ``MemoryEntryAuthoredByPersonaEvent`` so the frontend can
    refresh the journal view and raise an info toast.
    """
    from backend.database import get_db
    from backend.ws.event_bus import get_event_bus

    repo = MemoryRepository(get_db())
    entry_id = await repo.create_journal_entry(
        user_id=user_id,
        persona_id=persona_id,
        content=content,
        category=category,
        source_session_id=source_session_id,
    )
    now = datetime.now(UTC)
    dto = JournalEntryDto(
        id=entry_id,
        persona_id=persona_id,
        content=content,
        category=category,
        state="uncommitted",
        is_correction=False,
        created_at=now,
        committed_at=None,
        auto_committed=False,
    )

    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.MEMORY_ENTRY_AUTHORED_BY_PERSONA,
        MemoryEntryAuthoredByPersonaEvent(
            entry=dto,
            persona_name=persona_name,
            correlation_id=correlation_id,
            timestamp=now,
        ),
        scope=f"persona:{persona_id}",
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )

    return dto


__all__ = [
    "router",
    "init_indexes",
    "get_memory_context",
    "MemoryRepository",
    "delete_by_persona",
    "write_persona_authored_entry",
]
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
uv run pytest tests/modules/memory/test_persona_authored_entry.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/memory/__init__.py tests/modules/memory/test_persona_authored_entry.py
git commit -m "Add memory.write_persona_authored_entry public API

New entry-point for persona-authored journal entries: creates the
entry as uncommitted and publishes MemoryEntryAuthoredByPersona
so the frontend can live-update and toast."
```

---

## Task 4: Add `JournalToolExecutor` with validation tests

**Files:**
- Modify: `backend/modules/tools/_executors.py`
- Test: `tests/modules/tools/test_journal_tool_executor.py`

- [ ] **Step 1: Write the failing unit tests**

Create `tests/modules/tools/test_journal_tool_executor.py`:

```python
import json
from unittest.mock import AsyncMock

import pytest

from backend.modules.tools._executors import JournalToolExecutor
from shared.dtos.memory import JournalEntryDto

pytestmark = pytest.mark.asyncio


def _base_args(**overrides) -> dict:
    args = {
        "content": "Chris values the principle of least astonishment.",
        "category": "value",
        "_session_id": "session-1",
        "_persona_id": "persona-1",
        "_persona_name": "Aria",
        "_correlation_id": "corr-1",
    }
    args.update(overrides)
    return args


async def test_happy_path_calls_memory_api_and_returns_entry_id(monkeypatch):
    from datetime import datetime, timezone

    dto = JournalEntryDto(
        id="entry-123",
        persona_id="persona-1",
        content="Chris values the principle of least astonishment.",
        category="value",
        state="uncommitted",
        is_correction=False,
        created_at=datetime.now(timezone.utc),
    )
    write_mock = AsyncMock(return_value=dto)

    import backend.modules.memory as memory_mod
    monkeypatch.setattr(
        memory_mod, "write_persona_authored_entry", write_mock,
    )

    executor = JournalToolExecutor()
    result_str = await executor.execute(
        user_id="user-1",
        tool_name="write_journal_entry",
        arguments=_base_args(),
    )
    result = json.loads(result_str)

    assert result == {"status": "recorded", "entry_id": "entry-123"}
    write_mock.assert_awaited_once_with(
        user_id="user-1",
        persona_id="persona-1",
        persona_name="Aria",
        content="Chris values the principle of least astonishment.",
        category="value",
        source_session_id="session-1",
        correlation_id="corr-1",
    )


@pytest.mark.parametrize(
    "overrides,expected_error_substring",
    [
        ({"content": ""}, "content"),
        ({"content": None}, "content"),
        ({"category": ""}, "category"),
        ({"category": "nonsense"}, "category"),
        ({"content": "x" * 2001}, "2000"),
    ],
)
async def test_validation_errors_do_not_call_memory(
    monkeypatch, overrides, expected_error_substring,
):
    write_mock = AsyncMock()
    import backend.modules.memory as memory_mod
    monkeypatch.setattr(
        memory_mod, "write_persona_authored_entry", write_mock,
    )

    executor = JournalToolExecutor()
    result_str = await executor.execute(
        user_id="user-1",
        tool_name="write_journal_entry",
        arguments=_base_args(**overrides),
    )
    result = json.loads(result_str)

    assert "error" in result
    assert expected_error_substring in result["error"]
    write_mock.assert_not_awaited()


async def test_missing_session_context_is_internal_error(monkeypatch):
    write_mock = AsyncMock()
    import backend.modules.memory as memory_mod
    monkeypatch.setattr(
        memory_mod, "write_persona_authored_entry", write_mock,
    )

    args = _base_args()
    del args["_persona_id"]

    executor = JournalToolExecutor()
    result_str = await executor.execute(
        user_id="user-1",
        tool_name="write_journal_entry",
        arguments=args,
    )
    result = json.loads(result_str)

    assert "internal" in result["error"]
    write_mock.assert_not_awaited()


async def test_memory_api_exception_returns_error_string(monkeypatch):
    write_mock = AsyncMock(side_effect=RuntimeError("db down"))
    import backend.modules.memory as memory_mod
    monkeypatch.setattr(
        memory_mod, "write_persona_authored_entry", write_mock,
    )

    executor = JournalToolExecutor()
    result_str = await executor.execute(
        user_id="user-1",
        tool_name="write_journal_entry",
        arguments=_base_args(),
    )
    result = json.loads(result_str)

    assert "failed to record entry" in result["error"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
uv run pytest tests/modules/tools/test_journal_tool_executor.py -v
```

Expected: FAIL (ImportError on `JournalToolExecutor`).

- [ ] **Step 3: Implement `JournalToolExecutor`**

Open `backend/modules/tools/_executors.py` and append the following class at the end of the file:

```python
_VALID_JOURNAL_CATEGORIES = {
    "preference", "fact", "relationship", "value",
    "insight", "projects", "creative",
}
_MAX_JOURNAL_CONTENT_LENGTH = 2000


class JournalToolExecutor:
    """Dispatches write_journal_entry tool calls to the memory module."""

    async def execute(self, user_id: str, tool_name: str, arguments: dict) -> str:
        if tool_name != "write_journal_entry":
            return json.dumps({"error": f"Unknown journal tool: {tool_name}"})

        content = arguments.get("content")
        category = arguments.get("category")
        persona_id = arguments.get("_persona_id")
        persona_name = arguments.get("_persona_name", "")
        session_id = arguments.get("_session_id")
        correlation_id = arguments.get("_correlation_id", "")

        # Validation — content
        if not isinstance(content, str) or not content.strip():
            return json.dumps({"error": "content must be a non-empty string"})
        if len(content) > _MAX_JOURNAL_CONTENT_LENGTH:
            return json.dumps({
                "error": (
                    f"content too long (max {_MAX_JOURNAL_CONTENT_LENGTH} "
                    "characters)"
                ),
            })

        # Validation — category
        if not isinstance(category, str) or category not in _VALID_JOURNAL_CATEGORIES:
            return json.dumps({
                "error": (
                    "category must be one of: preference, fact, relationship, "
                    "value, insight, projects, creative"
                ),
            })

        # Dispatch context — must be injected by the chat orchestrator
        if not persona_id or not session_id:
            _log.error(
                "write_journal_entry missing dispatch context: "
                "persona_id=%r session_id=%r correlation_id=%r",
                persona_id, session_id, correlation_id,
            )
            return json.dumps({"error": "internal: missing session context"})

        try:
            from backend.modules.memory import write_persona_authored_entry

            dto = await write_persona_authored_entry(
                user_id=user_id,
                persona_id=persona_id,
                persona_name=persona_name,
                content=content,
                category=category,
                source_session_id=session_id,
                correlation_id=correlation_id,
            )
            return json.dumps({"status": "recorded", "entry_id": dto.id})

        except Exception as exc:
            _log.exception(
                "write_journal_entry failed for user=%s persona=%s correlation_id=%s: %s",
                user_id, persona_id, correlation_id, exc,
            )
            return json.dumps({"error": "failed to record entry"})
```

Note: the file already imports `json` and defines `_log = logging.getLogger(__name__)` at the top, so no new imports are required.

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
uv run pytest tests/modules/tools/test_journal_tool_executor.py -v
```

Expected: all seven cases PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/tools/_executors.py tests/modules/tools/test_journal_tool_executor.py
git commit -m "Add JournalToolExecutor with validation and dispatch tests

Validates content (non-empty, max 2000 chars), category (closed
enum) and dispatch context (_session_id + _persona_id). Returns
JSON error strings for every failure mode so the LLM can react
in-turn."
```

---

## Task 5: Register the `journal` tool group

**Files:**
- Modify: `backend/modules/tools/_registry.py`
- Test: `tests/modules/tools/test_journal_group_registered.py`

- [ ] **Step 1: Write the failing smoke test**

Create `tests/modules/tools/test_journal_group_registered.py`:

```python
from backend.modules.tools import get_active_definitions, get_all_groups
from backend.modules.tools._registry import get_groups


def test_journal_group_is_registered():
    groups = get_groups()
    assert "journal" in groups
    group = groups["journal"]
    assert group.side == "server"
    assert group.toggleable is True
    assert group.tool_names == ["write_journal_entry"]
    assert group.executor is not None
    assert len(group.definitions) == 1
    definition = group.definitions[0]
    assert definition.name == "write_journal_entry"
    params = definition.parameters
    assert params["required"] == ["content", "category"]
    assert set(params["properties"]["category"]["enum"]) == {
        "preference", "fact", "relationship", "value",
        "insight", "projects", "creative",
    }


def test_journal_tool_is_in_active_definitions_by_default():
    active = get_active_definitions()
    names = {d.name for d in active}
    assert "write_journal_entry" in names


def test_journal_group_is_in_group_dtos():
    dtos = get_all_groups()
    ids = {g.id for g in dtos}
    assert "journal" in ids
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/modules/tools/test_journal_group_registered.py -v
```

Expected: FAIL (no `journal` group in the registry).

- [ ] **Step 3: Add the `journal` group to the registry**

Open `backend/modules/tools/_registry.py`.

First, update the lazy-import line inside `_build_groups` to include `JournalToolExecutor`:

```python
    from backend.modules.tools._executors import (
        ArtefactToolExecutor,
        JournalToolExecutor,
        KnowledgeSearchExecutor,
        WebSearchExecutor,
    )
```

Then inside the returned dict (after the `"code_execution"` entry, before the closing `}`), add:

```python
        "journal": ToolGroup(
            id="journal",
            display_name="Journal",
            description=(
                "Allow the persona to record a lasting observation about "
                "you in its private journal when it learns something "
                "genuinely significant. Entries are drafts until you "
                "commit them."
            ),
            side="server",
            toggleable=True,
            tool_names=["write_journal_entry"],
            definitions=[
                ToolDefinition(
                    name="write_journal_entry",
                    description=(
                        "Record a lasting observation about the user in "
                        "your private journal. Use this ONLY when you "
                        "believe you have just learned something genuinely "
                        "significant — something that will meaningfully "
                        "change how you understand or relate to this "
                        "person over the long term. Do NOT use this for "
                        "small talk, transient context, things obvious "
                        "from the conversation itself, or things you "
                        "could easily infer later. The entry is "
                        "uncommitted (a draft) until the user explicitly "
                        "commits it. Be selective: a handful of truly "
                        "impactful entries is worth more than many "
                        "shallow ones."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": (
                                    "The insight about the user, written "
                                    "in natural prose as the persona "
                                    "understands it. Third person, "
                                    "specific and concrete."
                                ),
                            },
                            "category": {
                                "type": "string",
                                "enum": [
                                    "preference", "fact", "relationship",
                                    "value", "insight", "projects",
                                    "creative",
                                ],
                                "description": (
                                    "Which aspect of the user this entry "
                                    "captures."
                                ),
                            },
                        },
                        "required": ["content", "category"],
                    },
                ),
            ],
            executor=JournalToolExecutor(),
        ),
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
uv run pytest tests/modules/tools/test_journal_group_registered.py -v
```

Expected: all three tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/tools/_registry.py tests/modules/tools/test_journal_group_registered.py
git commit -m "Register journal tool group with write_journal_entry

New toggleable server-side group exposing write_journal_entry
to the LLM. Description wording asks the model to be selective
and only use it for lasting, impactful observations."
```

---

## Task 6: Inject persona context into tool arguments

**Files:**
- Modify: `backend/modules/chat/_orchestrator.py`

The executor needs `_session_id`, `_persona_id`, `_persona_name` and `_correlation_id`. The existing `_make_tool_executor` helper injects these context keys per-tool. Extend it with a branch for `write_journal_entry`.

- [ ] **Step 1: Add injection branch**

Open `backend/modules/chat/_orchestrator.py` and locate `_make_tool_executor` (around line 104). Inside the inner `_executor` function, directly after the `artefact_tools` block that ends with `arguments_json = json.dumps(args)`, add:

```python
        if tool_name == "write_journal_entry":
            args = json.loads(arguments_json)
            args["_session_id"] = session.get("_id", "")
            args["_persona_id"] = (persona or {}).get("_id", "")
            args["_persona_name"] = (persona or {}).get("name", "")
            args["_correlation_id"] = correlation_id
            arguments_json = json.dumps(args)
```

- [ ] **Step 2: Syntax-check**

Run:

```bash
uv run python -m py_compile backend/modules/chat/_orchestrator.py
```

Expected: clean exit.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/chat/_orchestrator.py
git commit -m "Inject persona context into write_journal_entry tool args

The JournalToolExecutor needs session id, persona id, persona
name and correlation id to create the entry and publish the
authored-by-persona event. They are injected the same way other
server-side tools receive their dispatch context."
```

---

## Task 7: Frontend — subscribe to the new event and raise a toast

**Files:**
- Modify: `frontend/src/features/memory/useMemoryEvents.ts`

- [ ] **Step 1: Add the new case**

Open `frontend/src/features/memory/useMemoryEvents.ts` and, inside the `switch (event.type)` block, after the `MEMORY_ENTRY_AUTO_COMMITTED` case, add:

```typescript
        case Topics.MEMORY_ENTRY_AUTHORED_BY_PERSONA: {
          const entry = p.entry as JournalEntryDto
          const personaName = (p.persona_name as string | undefined) ?? "Your persona"
          // Cross-persona guard: useMemoryEvents may be mounted twice
          // (ChatView + MemoriesTab), each with a different personaId.
          // Only the hook whose personaId matches the entry should
          // touch the store and raise the toast.
          if (entry.persona_id !== personaId) break
          store().addEntry(personaId, entry)
          if (!_toastedCorrelations.has(event.correlation_id)) {
            _toastedCorrelations.add(event.correlation_id)
            notify().addNotification({
              level: 'info',
              title: 'Journal note added',
              message: `${personaName} has recorded a new observation about you.`,
            })
          }
          break
        }
```

- [ ] **Step 2: Type-check the frontend**

Run:

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: clean exit (no type errors).

- [ ] **Step 3: Build the frontend**

Run:

```bash
cd frontend && pnpm run build
```

Expected: build completes without errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/memory/useMemoryEvents.ts
git commit -m "Show info toast when persona authors a journal entry

Handles memory.entry.authored_by_persona: adds the entry to the
journal store and raises a one-shot info toast named after the
persona. Cross-persona guard keeps dual-mounted hooks from
double-handling the same event."
```

---

## Task 8: End-to-end verification

**Files:** none (manual verification only)

- [ ] **Step 1: Run the full backend test suite for the touched modules**

Run:

```bash
uv run pytest tests/modules/tools/ tests/modules/memory/ -v
```

Expected: all tests pass, including the existing ones.

- [ ] **Step 2: Syntax-check every touched backend file**

Run:

```bash
uv run python -m py_compile \
  shared/topics.py \
  shared/events/memory.py \
  backend/ws/event_bus.py \
  backend/modules/memory/__init__.py \
  backend/modules/tools/_executors.py \
  backend/modules/tools/_registry.py \
  backend/modules/chat/_orchestrator.py
```

Expected: clean exit.

- [ ] **Step 3: Build the frontend once more**

Run:

```bash
cd frontend && pnpm run build
```

Expected: clean build.

- [ ] **Step 4: Manual browser verification**

1. Start the stack (backend + frontend + Mongo + Redis — `docker compose up` or whichever workflow is currently in use).
2. Log in as a normal user, open any persona and start a new chat.
3. In the tool panel, confirm that the new **Journal** group appears and is toggled on.
4. Talk to the persona and deliberately drop a statement like *"I really care about the principle of least astonishment — it's basically my core design value."*
5. Expect: the model calls `write_journal_entry`, the info toast appears (`"<persona> has recorded a new observation about you."`), and the new draft entry is visible in the Memories tab under **Uncommitted**.
6. Toggle the **Journal** group off in the session tool panel and repeat the same prompt. Expect: the model no longer has access to the tool and cannot write an entry.

- [ ] **Step 5: Merge to master**

Per `CLAUDE.md` — implementation defaults include "Please always merge to master after implementation". Confirm the feature branch is up to date with master and merge.

```bash
git checkout master
git merge --no-ff <feature-branch>
```

---

## Self-review checklist (already performed; listed for the executing agent)

- **Spec coverage:** every section of the spec maps to a task. Tool definition → Task 5. Memory public API → Task 3. Executor → Task 4. Event + topic → Task 1. Fan-out → Task 2. Chat injection → Task 6. Frontend → Task 7. Testing plan → covered across Tasks 3, 4, 5, 8.
- **Placeholder scan:** no TBDs, no "TODO", no "similar to Task N", every code step shows the full code to write.
- **Type consistency:** `write_persona_authored_entry` signature in Task 3 matches the call in Task 4 exactly (same kwargs: `user_id`, `persona_id`, `persona_name`, `content`, `category`, `source_session_id`, `correlation_id`). `JournalToolExecutor` name and tool name `write_journal_entry` are consistent across Tasks 4, 5, 6, 7.

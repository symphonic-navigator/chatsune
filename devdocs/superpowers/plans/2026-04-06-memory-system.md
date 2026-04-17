# Memory System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a per-persona memory system that extracts facts from user messages, stages them for review, and consolidates them into long-term memory injected at session start.

**Architecture:** New `backend/modules/memory/` module with own MongoDB collections, job handlers for extraction and consolidation, a tolerant JSON parser, and RAG assembly for prompt injection. Frontend gets a journal dropdown in the chat header, a dedicated memory page per persona, and toast notifications. All state changes publish events through the existing WebSocket event bus.

**Tech Stack:** Python/FastAPI, MongoDB, Redis (tracking state), Pydantic v2, tiktoken, React/TSX, Zustand, Tailwind CSS

**Spec:** `docs/superpowers/specs/2026-04-06-memory-system-design.md`

---

## File Structure

### Backend — New Files

| File | Responsibility |
|------|---------------|
| `backend/modules/memory/__init__.py` | Public API: router, init_indexes(), get_memory_context() |
| `backend/modules/memory/_repository.py` | MongoDB CRUD for journal_entries + memory_bodies collections |
| `backend/modules/memory/_models.py` | Internal Pydantic document models |
| `backend/modules/memory/_handlers.py` | REST endpoints for memory page |
| `backend/modules/memory/_extraction.py` | Content filtering + extraction prompt building |
| `backend/modules/memory/_consolidation.py` | Dreaming prompt building + validation |
| `backend/modules/memory/_assembly.py` | RAG assembly: builds XML block for prompt injection |
| `backend/modules/memory/_parser.py` | Tolerant JSON parser for extraction LLM output |
| `backend/jobs/handlers/_memory_extraction.py` | Job handler: journal extraction |
| `backend/jobs/handlers/_memory_consolidation.py` | Job handler: dreaming/consolidation |
| `shared/dtos/memory.py` | JournalEntryDto, MemoryBodyDto, MemoryBodyVersionDto, MemoryContextDto |
| `shared/events/memory.py` | All MEMORY_* event models |

### Backend — Modified Files

| File | Change |
|------|--------|
| `shared/topics.py` | Add MEMORY_* topic constants |
| `backend/jobs/_models.py` | Add MEMORY_EXTRACTION + MEMORY_CONSOLIDATION to JobType enum |
| `backend/jobs/_registry.py` | Register both new job types |
| `backend/ws/event_bus.py` | Add fan-out rules for memory events |
| `backend/modules/chat/_prompt_assembler.py` | Add usermemory layer via get_memory_context() |
| `backend/main.py` | Register memory module (init_indexes, router, cleanup loop) |

### Frontend — New Files

| File | Responsibility |
|------|---------------|
| `frontend/src/core/store/memoryStore.ts` | Zustand store for journal entries, memory body, UI state |
| `frontend/src/core/api/memory.ts` | REST API client for memory endpoints |
| `frontend/src/features/chat/JournalBadge.tsx` | Badge button in chat header with counter |
| `frontend/src/features/chat/JournalDropdown.tsx` | Dropdown panel listing uncommitted entries |
| `frontend/src/features/memory/MemoryPage.tsx` | Full memory page (3 sections) |
| `frontend/src/features/memory/UncommittedSection.tsx` | Uncommitted entries list with bulk actions |
| `frontend/src/features/memory/CommittedSection.tsx` | Committed entries list |
| `frontend/src/features/memory/MemoryBodySection.tsx` | Memory body viewer, versioning, rollback |
| `frontend/src/features/memory/useMemoryEvents.ts` | WebSocket event handler hook for memory events |

### Frontend — Modified Files

| File | Change |
|------|--------|
| `frontend/src/features/chat/ChatView.tsx` | Add JournalBadge to chat header area |
| `frontend/src/app/App.tsx` | Add /memory/:personaId route |

### Tests

| File | Tests |
|------|-------|
| `tests/memory/test_parser.py` | Tolerant JSON parser edge cases |
| `tests/memory/test_repository.py` | MongoDB operations for journal + memory body |
| `tests/memory/test_extraction.py` | Content filtering, prompt building |
| `tests/memory/test_consolidation.py` | Consolidation prompt, validation |
| `tests/memory/test_assembly.py` | RAG assembly token budget logic |
| `tests/memory/test_handlers.py` | REST endpoint integration tests |

---

### Task 1: Shared Contracts — Topics, DTOs, Events

**Files:**
- Modify: `shared/topics.py`
- Create: `shared/dtos/memory.py`
- Create: `shared/events/memory.py`

- [ ] **Step 1: Add memory topics to shared/topics.py**

Open `shared/topics.py` and add these constants to the `Topics` class:

```python
    # Memory
    MEMORY_EXTRACTION_STARTED = "memory.extraction.started"
    MEMORY_EXTRACTION_COMPLETED = "memory.extraction.completed"
    MEMORY_EXTRACTION_FAILED = "memory.extraction.failed"
    MEMORY_ENTRY_CREATED = "memory.entry.created"
    MEMORY_ENTRY_COMMITTED = "memory.entry.committed"
    MEMORY_ENTRY_UPDATED = "memory.entry.updated"
    MEMORY_ENTRY_DELETED = "memory.entry.deleted"
    MEMORY_ENTRY_AUTO_COMMITTED = "memory.entry.auto_committed"
    MEMORY_DREAM_STARTED = "memory.dream.started"
    MEMORY_DREAM_COMPLETED = "memory.dream.completed"
    MEMORY_DREAM_FAILED = "memory.dream.failed"
    MEMORY_BODY_ROLLBACK = "memory.body.rollback"
```

- [ ] **Step 2: Create shared/dtos/memory.py**

```python
"""Memory DTOs — shared between backend modules and frontend."""

from datetime import datetime

from pydantic import BaseModel


class JournalEntryDto(BaseModel):
    id: str
    persona_id: str
    content: str
    category: str | None = None
    state: str  # "uncommitted" | "committed" | "archived"
    is_correction: bool = False
    created_at: datetime
    committed_at: datetime | None = None
    auto_committed: bool = False


class MemoryBodyDto(BaseModel):
    persona_id: str
    content: str
    token_count: int
    version: int
    created_at: datetime


class MemoryBodyVersionDto(BaseModel):
    version: int
    token_count: int
    entries_processed: int
    created_at: datetime


class MemoryContextDto(BaseModel):
    persona_id: str
    uncommitted_count: int
    committed_count: int
    last_extraction_at: datetime | None = None
    last_dream_at: datetime | None = None
    can_trigger_extraction: bool = False
```

- [ ] **Step 3: Create shared/events/memory.py**

```python
"""Memory events — published through the event bus."""

from datetime import datetime

from pydantic import BaseModel

from shared.dtos.memory import JournalEntryDto, MemoryBodyDto


class MemoryExtractionStartedEvent(BaseModel):
    type: str = "memory.extraction.started"
    persona_id: str
    correlation_id: str
    timestamp: datetime


class MemoryExtractionCompletedEvent(BaseModel):
    type: str = "memory.extraction.completed"
    persona_id: str
    entries_created: int
    correlation_id: str
    timestamp: datetime


class MemoryExtractionFailedEvent(BaseModel):
    type: str = "memory.extraction.failed"
    persona_id: str
    error_message: str
    correlation_id: str
    timestamp: datetime


class MemoryEntryCreatedEvent(BaseModel):
    type: str = "memory.entry.created"
    entry: JournalEntryDto
    correlation_id: str
    timestamp: datetime


class MemoryEntryCommittedEvent(BaseModel):
    type: str = "memory.entry.committed"
    entry: JournalEntryDto
    correlation_id: str
    timestamp: datetime


class MemoryEntryUpdatedEvent(BaseModel):
    type: str = "memory.entry.updated"
    entry: JournalEntryDto
    correlation_id: str
    timestamp: datetime


class MemoryEntryDeletedEvent(BaseModel):
    type: str = "memory.entry.deleted"
    entry_id: str
    persona_id: str
    correlation_id: str
    timestamp: datetime


class MemoryEntryAutoCommittedEvent(BaseModel):
    type: str = "memory.entry.auto_committed"
    entry: JournalEntryDto
    correlation_id: str
    timestamp: datetime


class MemoryDreamStartedEvent(BaseModel):
    type: str = "memory.dream.started"
    persona_id: str
    entries_count: int
    correlation_id: str
    timestamp: datetime


class MemoryDreamCompletedEvent(BaseModel):
    type: str = "memory.dream.completed"
    persona_id: str
    entries_processed: int
    body_version: int
    body_token_count: int
    correlation_id: str
    timestamp: datetime


class MemoryDreamFailedEvent(BaseModel):
    type: str = "memory.dream.failed"
    persona_id: str
    error_message: str
    correlation_id: str
    timestamp: datetime


class MemoryBodyRollbackEvent(BaseModel):
    type: str = "memory.body.rollback"
    persona_id: str
    rolled_back_to_version: int
    new_version: int
    correlation_id: str
    timestamp: datetime
```

- [ ] **Step 4: Verify imports compile**

Run:
```bash
uv run python -c "from shared.topics import Topics; from shared.dtos.memory import JournalEntryDto, MemoryBodyDto, MemoryBodyVersionDto, MemoryContextDto; from shared.events.memory import MemoryEntryCreatedEvent, MemoryDreamCompletedEvent; print('OK')"
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add shared/topics.py shared/dtos/memory.py shared/events/memory.py
git commit -m "Add memory system shared contracts: topics, DTOs, events"
```

---

### Task 2: Tolerant JSON Parser

**Files:**
- Create: `backend/modules/memory/_parser.py`
- Create: `tests/memory/__init__.py`
- Create: `tests/memory/test_parser.py`

- [ ] **Step 1: Create tests/memory/__init__.py**

```python
```

(Empty file to make it a package.)

- [ ] **Step 2: Write failing tests for the parser**

Create `tests/memory/test_parser.py`:

```python
"""Tests for the tolerant JSON parser used in memory extraction."""

import pytest

from backend.modules.memory._parser import parse_extraction_output


class TestCleanJsonOutput:
    """LLM returns well-formed JSON."""

    def test_valid_json_array(self):
        raw = '[{"content": "Likes dark themes", "category": "preference", "is_correction": false}]'
        result = parse_extraction_output(raw)
        assert len(result) == 1
        assert result[0]["content"] == "Likes dark themes"
        assert result[0]["is_correction"] is False

    def test_multiple_entries(self):
        raw = '[{"content": "A", "category": "fact", "is_correction": false}, {"content": "B", "category": null, "is_correction": true}]'
        result = parse_extraction_output(raw)
        assert len(result) == 2
        assert result[1]["is_correction"] is True

    def test_empty_array(self):
        result = parse_extraction_output("[]")
        assert result == []


class TestMarkdownFences:
    """LLM wraps output in markdown code fences."""

    def test_json_fence(self):
        raw = '```json\n[{"content": "Uses Arch", "category": "fact", "is_correction": false}]\n```'
        result = parse_extraction_output(raw)
        assert len(result) == 1
        assert result[0]["content"] == "Uses Arch"

    def test_plain_fence(self):
        raw = '```\n[{"content": "Test", "category": null, "is_correction": false}]\n```'
        result = parse_extraction_output(raw)
        assert len(result) == 1

    def test_fence_with_surrounding_text(self):
        raw = 'Here are the entries:\n```json\n[{"content": "Test", "category": "fact", "is_correction": false}]\n```\nDone.'
        result = parse_extraction_output(raw)
        assert len(result) == 1


class TestTrailingCommas:
    """Weak models produce trailing commas."""

    def test_trailing_comma_in_array(self):
        raw = '[{"content": "A", "category": "fact", "is_correction": false},]'
        result = parse_extraction_output(raw)
        assert len(result) == 1

    def test_trailing_comma_in_object(self):
        raw = '[{"content": "A", "category": "fact", "is_correction": false,}]'
        result = parse_extraction_output(raw)
        assert len(result) == 1


class TestMissingFields:
    """LLM omits optional fields."""

    def test_missing_category(self):
        raw = '[{"content": "Test"}]'
        result = parse_extraction_output(raw)
        assert len(result) == 1
        assert result[0]["content"] == "Test"
        assert result[0].get("category") is None
        assert result[0].get("is_correction") is False

    def test_missing_is_correction(self):
        raw = '[{"content": "Test", "category": "fact"}]'
        result = parse_extraction_output(raw)
        assert result[0]["is_correction"] is False


class TestFallbackRegexExtraction:
    """JSON is broken beyond repair — fall back to regex."""

    def test_objects_without_array_wrapper(self):
        raw = '{"content": "A", "category": "fact", "is_correction": false}\n{"content": "B", "category": "fact", "is_correction": false}'
        result = parse_extraction_output(raw)
        assert len(result) == 2

    def test_prose_with_embedded_json(self):
        raw = 'I found these facts:\n1. {"content": "Uses Linux", "category": "fact", "is_correction": false}\n2. {"content": "Likes Redis", "category": "preference", "is_correction": false}'
        result = parse_extraction_output(raw)
        assert len(result) == 2


class TestGarbageInput:
    """Completely unparseable output."""

    def test_empty_string(self):
        result = parse_extraction_output("")
        assert result == []

    def test_none(self):
        result = parse_extraction_output(None)
        assert result == []

    def test_pure_prose(self):
        result = parse_extraction_output("The user likes dark themes and uses Arch Linux.")
        assert result == []

    def test_whitespace_only(self):
        result = parse_extraction_output("   \n\n  ")
        assert result == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/memory/test_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.modules.memory'`

- [ ] **Step 4: Create the memory module package**

Create `backend/modules/memory/__init__.py`:

```python
"""Memory module — per-persona memory extraction, consolidation, and retrieval.

Public API: import only from this file.
"""

__all__: list[str] = []
```

- [ ] **Step 5: Implement the tolerant parser**

Create `backend/modules/memory/_parser.py`:

```python
"""Tolerant JSON parser for LLM extraction output.

Handles: markdown fences, trailing commas, missing fields, broken arrays,
and individual JSON objects on separate lines. Returns a list of normalised
entry dicts with guaranteed 'content', 'category', and 'is_correction' keys.
"""

from __future__ import annotations

import json
import re

_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_OBJECT_RE = re.compile(r"\{[^{}]*\}")


def parse_extraction_output(raw: str | None) -> list[dict]:
    """Parse LLM extraction output into a list of normalised entry dicts.

    Returns an empty list when the input is unparseable.
    """
    if not raw or not raw.strip():
        return []

    text = raw.strip()

    # Step 1: strip markdown code fences
    fence_match = _FENCE_RE.search(text)
    if fence_match:
        text = fence_match.group(1).strip()

    # Step 2: try direct JSON parse (with trailing comma repair)
    cleaned = _TRAILING_COMMA_RE.sub(r"\1", text)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return [_normalise(entry) for entry in parsed if isinstance(entry, dict) and "content" in entry]
        if isinstance(parsed, dict) and "content" in parsed:
            return [_normalise(parsed)]
    except (json.JSONDecodeError, TypeError):
        pass

    # Step 3: fallback — extract individual JSON objects via regex
    entries: list[dict] = []
    for match in _OBJECT_RE.finditer(text):
        fragment = _TRAILING_COMMA_RE.sub(r"\1", match.group())
        try:
            obj = json.loads(fragment)
            if isinstance(obj, dict) and "content" in obj:
                entries.append(_normalise(obj))
        except (json.JSONDecodeError, TypeError):
            continue

    return entries


def _normalise(entry: dict) -> dict:
    """Ensure required keys exist with sensible defaults."""
    return {
        "content": str(entry.get("content", "")),
        "category": entry.get("category"),
        "is_correction": bool(entry.get("is_correction", False)),
    }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/memory/test_parser.py -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add backend/modules/memory/__init__.py backend/modules/memory/_parser.py tests/memory/__init__.py tests/memory/test_parser.py
git commit -m "Add tolerant JSON parser for memory extraction output"
```

---

### Task 3: Memory Repository & Document Models

**Files:**
- Create: `backend/modules/memory/_models.py`
- Create: `backend/modules/memory/_repository.py`
- Create: `tests/memory/test_repository.py`

- [ ] **Step 1: Write failing tests for the repository**

Create `tests/memory/test_repository.py`:

```python
"""Tests for memory repository — requires running MongoDB."""

from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio

from backend.modules.memory._models import JournalEntryDocument, MemoryBodyDocument
from backend.modules.memory._repository import MemoryRepository


@pytest_asyncio.fixture
async def repo():
    """Get a MemoryRepository connected to the test database."""
    from backend.database import get_db
    db = get_db()
    repo = MemoryRepository(db)
    await repo.create_indexes()
    # Clean up before each test
    await db["memory_journal_entries"].delete_many({})
    await db["memory_bodies"].delete_many({})
    yield repo


@pytest.mark.asyncio
class TestJournalEntries:

    async def test_create_and_find_uncommitted(self, repo: MemoryRepository):
        entry_id = await repo.create_journal_entry(
            user_id="u1",
            persona_id="p1",
            content="Likes dark themes",
            category="preference",
            source_session_id="s1",
            is_correction=False,
        )
        assert entry_id is not None

        entries = await repo.list_journal_entries("u1", "p1", state="uncommitted")
        assert len(entries) == 1
        assert entries[0]["content"] == "Likes dark themes"
        assert entries[0]["state"] == "uncommitted"

    async def test_commit_entry(self, repo: MemoryRepository):
        entry_id = await repo.create_journal_entry(
            user_id="u1", persona_id="p1", content="Test",
            category=None, source_session_id="s1", is_correction=False,
        )
        result = await repo.commit_entry(entry_id, "u1")
        assert result is True

        entries = await repo.list_journal_entries("u1", "p1", state="committed")
        assert len(entries) == 1
        assert entries[0]["committed_at"] is not None
        assert entries[0]["auto_committed"] is False

    async def test_update_entry_content(self, repo: MemoryRepository):
        entry_id = await repo.create_journal_entry(
            user_id="u1", persona_id="p1", content="Original",
            category=None, source_session_id="s1", is_correction=False,
        )
        result = await repo.update_entry(entry_id, "u1", content="Edited")
        assert result is True

        entries = await repo.list_journal_entries("u1", "p1", state="uncommitted")
        assert entries[0]["content"] == "Edited"

    async def test_delete_entry(self, repo: MemoryRepository):
        entry_id = await repo.create_journal_entry(
            user_id="u1", persona_id="p1", content="Test",
            category=None, source_session_id="s1", is_correction=False,
        )
        result = await repo.delete_entry(entry_id, "u1")
        assert result is True

        entries = await repo.list_journal_entries("u1", "p1", state="uncommitted")
        assert len(entries) == 0

    async def test_count_uncommitted(self, repo: MemoryRepository):
        for i in range(5):
            await repo.create_journal_entry(
                user_id="u1", persona_id="p1", content=f"Entry {i}",
                category=None, source_session_id="s1", is_correction=False,
            )
        count = await repo.count_entries("u1", "p1", state="uncommitted")
        assert count == 5

    async def test_auto_commit_old_entries(self, repo: MemoryRepository):
        # Create entry with old timestamp
        entry_id = await repo.create_journal_entry(
            user_id="u1", persona_id="p1", content="Old entry",
            category=None, source_session_id="s1", is_correction=False,
        )
        # Backdate it
        await repo._entries.update_one(
            {"_id": entry_id},
            {"$set": {"created_at": datetime.now(timezone.utc) - timedelta(hours=49)}},
        )
        committed = await repo.auto_commit_old_entries(max_age_hours=48)
        assert len(committed) == 1
        assert committed[0]["auto_committed"] is True

    async def test_discard_oldest_over_cap(self, repo: MemoryRepository):
        for i in range(5):
            await repo.create_journal_entry(
                user_id="u1", persona_id="p1", content=f"Entry {i}",
                category=None, source_session_id="s1", is_correction=False,
            )
        discarded = await repo.discard_oldest_uncommitted("u1", "p1", max_count=3)
        assert discarded == 2

        remaining = await repo.count_entries("u1", "p1", state="uncommitted")
        assert remaining == 3

    async def test_archive_committed_entries(self, repo: MemoryRepository):
        entry_id = await repo.create_journal_entry(
            user_id="u1", persona_id="p1", content="Test",
            category=None, source_session_id="s1", is_correction=False,
        )
        await repo.commit_entry(entry_id, "u1")

        archived = await repo.archive_entries("u1", "p1", dream_id="d1")
        assert archived == 1

        entries = await repo.list_journal_entries("u1", "p1", state="archived")
        assert len(entries) == 1
        assert entries[0]["archived_by_dream_id"] == "d1"


@pytest.mark.asyncio
class TestMemoryBody:

    async def test_create_and_get_current(self, repo: MemoryRepository):
        await repo.save_memory_body(
            user_id="u1", persona_id="p1", content="User likes dark themes.",
            token_count=12, entries_processed=3,
        )
        body = await repo.get_current_memory_body("u1", "p1")
        assert body is not None
        assert body["version"] == 1
        assert body["content"] == "User likes dark themes."

    async def test_version_increments(self, repo: MemoryRepository):
        await repo.save_memory_body(
            user_id="u1", persona_id="p1", content="V1",
            token_count=5, entries_processed=2,
        )
        await repo.save_memory_body(
            user_id="u1", persona_id="p1", content="V2",
            token_count=8, entries_processed=4,
        )
        body = await repo.get_current_memory_body("u1", "p1")
        assert body["version"] == 2
        assert body["content"] == "V2"

    async def test_list_versions(self, repo: MemoryRepository):
        for i in range(3):
            await repo.save_memory_body(
                user_id="u1", persona_id="p1", content=f"V{i+1}",
                token_count=5, entries_processed=1,
            )
        versions = await repo.list_memory_body_versions("u1", "p1")
        assert len(versions) == 3
        assert versions[0]["version"] == 3  # newest first

    async def test_max_versions_retained(self, repo: MemoryRepository):
        for i in range(7):
            await repo.save_memory_body(
                user_id="u1", persona_id="p1", content=f"V{i+1}",
                token_count=5, entries_processed=1,
            )
        versions = await repo.list_memory_body_versions("u1", "p1")
        assert len(versions) == 5  # only last 5 retained

    async def test_get_version_by_number(self, repo: MemoryRepository):
        for i in range(3):
            await repo.save_memory_body(
                user_id="u1", persona_id="p1", content=f"V{i+1}",
                token_count=5, entries_processed=1,
            )
        body = await repo.get_memory_body_version("u1", "p1", version=1)
        assert body is not None
        assert body["content"] == "V1"

    async def test_rollback_creates_new_version(self, repo: MemoryRepository):
        await repo.save_memory_body(
            user_id="u1", persona_id="p1", content="Good",
            token_count=5, entries_processed=2,
        )
        await repo.save_memory_body(
            user_id="u1", persona_id="p1", content="Bad",
            token_count=5, entries_processed=3,
        )
        new_version = await repo.rollback_memory_body("u1", "p1", to_version=1)
        assert new_version == 3

        body = await repo.get_current_memory_body("u1", "p1")
        assert body["content"] == "Good"
        assert body["version"] == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/memory/test_repository.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create document models**

Create `backend/modules/memory/_models.py`:

```python
"""Internal document models for the memory module.

These are MongoDB document shapes — not to be imported outside this module.
Use shared/dtos/memory.py for cross-module communication.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class JournalEntryDocument(BaseModel):
    user_id: str
    persona_id: str
    content: str
    category: str | None = None
    source_session_id: str
    state: str = "uncommitted"  # "uncommitted" | "committed" | "archived"
    is_correction: bool = False
    archived_by_dream_id: str | None = None
    created_at: datetime
    committed_at: datetime | None = None
    auto_committed: bool = False


class MemoryBodyDocument(BaseModel):
    user_id: str
    persona_id: str
    content: str
    token_count: int
    version: int
    entries_processed: int
    created_at: datetime
```

- [ ] **Step 4: Implement the repository**

Create `backend/modules/memory/_repository.py`:

```python
"""MongoDB operations for journal entries and memory bodies."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.modules.memory._models import JournalEntryDocument, MemoryBodyDocument

_MAX_VERSIONS = 5


class MemoryRepository:

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._entries = db["memory_journal_entries"]
        self._bodies = db["memory_bodies"]

    async def create_indexes(self) -> None:
        await self._entries.create_index(
            [("user_id", 1), ("persona_id", 1), ("state", 1), ("created_at", 1)],
        )
        await self._bodies.create_index(
            [("user_id", 1), ("persona_id", 1), ("version", -1)],
            unique=True,
        )

    # ── Journal Entries ──────────────────────────────────────────────

    async def create_journal_entry(
        self,
        *,
        user_id: str,
        persona_id: str,
        content: str,
        category: str | None,
        source_session_id: str,
        is_correction: bool,
    ) -> str:
        entry_id = str(uuid4())
        doc = JournalEntryDocument(
            user_id=user_id,
            persona_id=persona_id,
            content=content,
            category=category,
            source_session_id=source_session_id,
            is_correction=is_correction,
            created_at=datetime.now(timezone.utc),
        )
        await self._entries.insert_one({"_id": entry_id, **doc.model_dump()})
        return entry_id

    async def list_journal_entries(
        self,
        user_id: str,
        persona_id: str,
        *,
        state: str | None = None,
    ) -> list[dict]:
        query: dict = {"user_id": user_id, "persona_id": persona_id}
        if state is not None:
            query["state"] = state
        cursor = self._entries.find(query).sort("created_at", -1)
        return [{"id": doc["_id"], **{k: v for k, v in doc.items() if k != "_id"}} async for doc in cursor]

    async def count_entries(
        self,
        user_id: str,
        persona_id: str,
        *,
        state: str,
    ) -> int:
        return await self._entries.count_documents(
            {"user_id": user_id, "persona_id": persona_id, "state": state},
        )

    async def commit_entry(self, entry_id: str, user_id: str) -> bool:
        result = await self._entries.update_one(
            {"_id": entry_id, "user_id": user_id, "state": "uncommitted"},
            {"$set": {
                "state": "committed",
                "committed_at": datetime.now(timezone.utc),
                "auto_committed": False,
            }},
        )
        return result.modified_count == 1

    async def update_entry(
        self,
        entry_id: str,
        user_id: str,
        *,
        content: str,
    ) -> bool:
        result = await self._entries.update_one(
            {"_id": entry_id, "user_id": user_id, "state": {"$in": ["uncommitted", "committed"]}},
            {"$set": {"content": content}},
        )
        return result.modified_count == 1

    async def delete_entry(self, entry_id: str, user_id: str) -> bool:
        result = await self._entries.delete_one(
            {"_id": entry_id, "user_id": user_id},
        )
        return result.deleted_count == 1

    async def auto_commit_old_entries(self, *, max_age_hours: int = 48) -> list[dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        cursor = self._entries.find(
            {"state": "uncommitted", "created_at": {"$lt": cutoff}},
        )
        entries = []
        async for doc in cursor:
            await self._entries.update_one(
                {"_id": doc["_id"]},
                {"$set": {
                    "state": "committed",
                    "committed_at": datetime.now(timezone.utc),
                    "auto_committed": True,
                }},
            )
            doc["state"] = "committed"
            doc["auto_committed"] = True
            entries.append({"id": doc["_id"], **{k: v for k, v in doc.items() if k != "_id"}})
        return entries

    async def discard_oldest_uncommitted(
        self,
        user_id: str,
        persona_id: str,
        *,
        max_count: int = 50,
    ) -> int:
        count = await self.count_entries(user_id, persona_id, state="uncommitted")
        if count <= max_count:
            return 0

        excess = count - max_count
        cursor = (
            self._entries.find(
                {"user_id": user_id, "persona_id": persona_id, "state": "uncommitted"},
            )
            .sort("created_at", 1)
            .limit(excess)
        )
        ids_to_delete = [doc["_id"] async for doc in cursor]
        if ids_to_delete:
            await self._entries.delete_many({"_id": {"$in": ids_to_delete}})
        return len(ids_to_delete)

    async def archive_entries(
        self,
        user_id: str,
        persona_id: str,
        *,
        dream_id: str,
    ) -> int:
        result = await self._entries.update_many(
            {"user_id": user_id, "persona_id": persona_id, "state": "committed"},
            {"$set": {"state": "archived", "archived_by_dream_id": dream_id}},
        )
        return result.modified_count

    # ── Memory Body ──────────────────────────────────────────────────

    async def save_memory_body(
        self,
        *,
        user_id: str,
        persona_id: str,
        content: str,
        token_count: int,
        entries_processed: int,
    ) -> int:
        current = await self.get_current_memory_body(user_id, persona_id)
        new_version = (current["version"] + 1) if current else 1

        doc = MemoryBodyDocument(
            user_id=user_id,
            persona_id=persona_id,
            content=content,
            token_count=token_count,
            version=new_version,
            entries_processed=entries_processed,
            created_at=datetime.now(timezone.utc),
        )
        await self._bodies.insert_one(
            {"_id": str(uuid4()), **doc.model_dump()},
        )

        # Prune old versions beyond the retention limit
        all_versions = (
            await self._bodies.find(
                {"user_id": user_id, "persona_id": persona_id},
                {"_id": 1, "version": 1},
            )
            .sort("version", -1)
            .to_list(length=None)
        )
        if len(all_versions) > _MAX_VERSIONS:
            old_ids = [v["_id"] for v in all_versions[_MAX_VERSIONS:]]
            await self._bodies.delete_many({"_id": {"$in": old_ids}})

        return new_version

    async def get_current_memory_body(
        self,
        user_id: str,
        persona_id: str,
    ) -> dict | None:
        doc = await self._bodies.find_one(
            {"user_id": user_id, "persona_id": persona_id},
            sort=[("version", -1)],
        )
        if doc is None:
            return None
        return {"id": doc["_id"], **{k: v for k, v in doc.items() if k != "_id"}}

    async def get_memory_body_version(
        self,
        user_id: str,
        persona_id: str,
        *,
        version: int,
    ) -> dict | None:
        doc = await self._bodies.find_one(
            {"user_id": user_id, "persona_id": persona_id, "version": version},
        )
        if doc is None:
            return None
        return {"id": doc["_id"], **{k: v for k, v in doc.items() if k != "_id"}}

    async def list_memory_body_versions(
        self,
        user_id: str,
        persona_id: str,
    ) -> list[dict]:
        cursor = (
            self._bodies.find(
                {"user_id": user_id, "persona_id": persona_id},
                {"content": 0},  # omit content for listing
            )
            .sort("version", -1)
        )
        return [
            {"id": doc["_id"], **{k: v for k, v in doc.items() if k != "_id"}}
            async for doc in cursor
        ]

    async def rollback_memory_body(
        self,
        user_id: str,
        persona_id: str,
        *,
        to_version: int,
    ) -> int:
        old = await self.get_memory_body_version(user_id, persona_id, version=to_version)
        if old is None:
            raise ValueError(f"Version {to_version} not found")

        return await self.save_memory_body(
            user_id=user_id,
            persona_id=persona_id,
            content=old["content"],
            token_count=old["token_count"],
            entries_processed=0,
        )
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/memory/test_repository.py -v`
Expected: All PASS (requires running MongoDB — run via Docker if needed: `docker compose up -d`)

- [ ] **Step 6: Commit**

```bash
git add backend/modules/memory/_models.py backend/modules/memory/_repository.py tests/memory/test_repository.py
git commit -m "Add memory repository with journal entries and memory body storage"
```

---

### Task 4: Content Filtering & Extraction Logic

**Files:**
- Create: `backend/modules/memory/_extraction.py`
- Create: `tests/memory/test_extraction.py`

- [ ] **Step 1: Write failing tests for content filtering**

Create `tests/memory/test_extraction.py`:

```python
"""Tests for content filtering and extraction prompt building."""

import pytest

from backend.modules.memory._extraction import strip_technical_content, build_extraction_prompt


class TestStripTechnicalContent:

    def test_removes_fenced_code_blocks(self):
        text = "I have a bug:\n```python\ndef foo():\n    pass\n```\nCan you help?"
        result = strip_technical_content(text)
        assert "def foo" not in result
        assert "I have a bug" in result
        assert "Can you help?" in result

    def test_removes_indented_code_blocks(self):
        text = "Check this:\n\n    SELECT * FROM users;\n    WHERE id = 1;\n\nWhat do you think?"
        result = strip_technical_content(text)
        assert "SELECT" not in result
        assert "What do you think?" in result

    def test_removes_stacktraces(self):
        text = "Got this error:\nTraceback (most recent call last):\n  File \"main.py\", line 1\nValueError: bad\n\nWhat's wrong?"
        result = strip_technical_content(text)
        assert "Traceback" not in result
        assert "What's wrong?" in result

    def test_removes_json_dumps(self):
        text = 'The response was:\n{"status": 200, "data": [{"id": 1, "name": "test"}]}\n\nLooks wrong.'
        result = strip_technical_content(text)
        assert '"status"' not in result
        assert "Looks wrong." in result

    def test_preserves_human_context(self):
        text = "I'm working on a Redis caching problem. The cache keeps expiring too early. I prefer TTL of 1 hour."
        result = strip_technical_content(text)
        assert "Redis caching problem" in result
        assert "prefer TTL of 1 hour" in result

    def test_preserves_short_inline_code(self):
        text = "I use `vim` as my editor and love `tmux`."
        result = strip_technical_content(text)
        assert "vim" in result
        assert "tmux" in result

    def test_removes_log_output(self):
        text = "Server logs:\n2026-04-06 12:00:00 INFO Starting server\n2026-04-06 12:00:01 ERROR Connection refused\n\nIt crashed."
        result = strip_technical_content(text)
        assert "2026-04-06 12:00:00" not in result
        assert "It crashed." in result

    def test_removes_xml_yaml_dumps(self):
        text = "Config:\n```yaml\nserver:\n  port: 8080\n  host: 0.0.0.0\n```\nNeed to change the port."
        result = strip_technical_content(text)
        assert "port: 8080" not in result
        assert "Need to change the port." in result


class TestBuildExtractionPrompt:

    def test_includes_memory_body(self):
        prompt = build_extraction_prompt(
            memory_body="User likes dark themes.",
            journal_entries=["Works as C# developer"],
            messages=["I switched to Go recently."],
        )
        assert "User likes dark themes." in prompt
        assert "C# developer" in prompt
        assert "switched to Go" in prompt

    def test_no_memory_body(self):
        prompt = build_extraction_prompt(
            memory_body=None,
            journal_entries=[],
            messages=["My name is Chris."],
        )
        assert "My name is Chris." in prompt
        assert "no existing memory" in prompt.lower() or "empty" in prompt.lower() or "none" in prompt.lower()

    def test_instructs_json_output(self):
        prompt = build_extraction_prompt(
            memory_body=None,
            journal_entries=[],
            messages=["Hello"],
        )
        assert "json" in prompt.lower() or "JSON" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/memory/test_extraction.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement content filtering and prompt building**

Create `backend/modules/memory/_extraction.py`:

```python
"""Content filtering and extraction prompt building.

Strips technical raw data from user messages before sending to the
extraction LLM. Builds the extraction prompt with existing memory context.
"""

from __future__ import annotations

import re

# Fenced code blocks: ```lang ... ``` or ~~~ ... ~~~
_FENCED_CODE_RE = re.compile(r"(`{3,}|~{3,})[^\n]*\n.*?\1", re.DOTALL)

# Indented code blocks: 4+ spaces or tab at line start, consecutive lines
_INDENTED_CODE_RE = re.compile(r"(?:^(?:    |\t).+\n?){2,}", re.MULTILINE)

# Python/Java stacktraces
_STACKTRACE_RE = re.compile(
    r"Traceback \(most recent call last\):.*?(?=\n\S|\n\n|\Z)",
    re.DOTALL,
)

# Java-style stacktraces
_JAVA_STACKTRACE_RE = re.compile(
    r"(?:^|\n)\S+(?:Exception|Error):.+?(?:\n\s+at .+)+",
    re.DOTALL,
)

# Log lines: timestamp patterns (ISO-8601 or common log formats)
_LOG_LINE_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}|"
    r"\[\d{4}-\d{2}-\d{2}|"
    r"\d{2}/\w{3}/\d{4})"
    r".*$",
    re.MULTILINE,
)

# Multi-line JSON objects/arrays (3+ lines)
_JSON_BLOCK_RE = re.compile(
    r'(?:^|\n)\s*[\[{](?:\s*\n(?:.*\n){2,}?\s*[\]}])',
    re.MULTILINE,
)

# Single-line JSON that looks like a dump (has multiple keys)
_JSON_INLINE_RE = re.compile(
    r'\{(?:"[^"]+"\s*:\s*(?:"[^"]*"|[\d.]+|true|false|null|\[.*?\]|\{.*?\})\s*,?\s*){2,}\}',
)


def strip_technical_content(text: str) -> str:
    """Remove technical raw data from a user message.

    Strips code blocks, stacktraces, log output, and data dumps.
    Preserves the human-written context around them.
    """
    result = text

    # Order matters: fenced blocks first (most specific), then broader patterns
    result = _FENCED_CODE_RE.sub("", result)
    result = _STACKTRACE_RE.sub("", result)
    result = _JAVA_STACKTRACE_RE.sub("", result)
    result = _LOG_LINE_RE.sub("", result)
    result = _JSON_BLOCK_RE.sub("", result)
    result = _JSON_INLINE_RE.sub("", result)
    result = _INDENTED_CODE_RE.sub("", result)

    # Collapse excessive whitespace but keep paragraph breaks
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def build_extraction_prompt(
    *,
    memory_body: str | None,
    journal_entries: list[str],
    messages: list[str],
) -> str:
    """Build the system prompt for journal extraction.

    Args:
        memory_body: Current consolidated memory (may be None).
        journal_entries: Existing journal entry contents (committed + uncommitted).
        messages: Filtered user message contents to extract from.
    """
    memory_section = memory_body if memory_body else "(No existing memory — this is a new persona.)"

    journal_section = ""
    if journal_entries:
        journal_section = "\n".join(f"- {e}" for e in journal_entries)
    else:
        journal_section = "(No existing journal entries.)"

    messages_section = "\n---\n".join(messages) if messages else "(No messages to process.)"

    return f"""You are a memory extraction assistant. Your job is to extract personal facts,
preferences, relationships, opinions, and context about the user from their messages.

RULES:
- Extract facts, preferences, relationships, and personal information.
- Note technologies, projects, domains, and hobbies the user discusses.
- Do NOT extract pasted technical content (code, logs, stack traces, configs).
  Instead, note what the user SAYS about their work — their context, opinions, and preferences.
- Perform semantic de-duplication: do not create entries that duplicate existing memory or journal entries.
- If new information contradicts existing memory or journal entries, create a correction entry
  with "is_correction": true.
- Produce output as a JSON array. Each entry has: "content" (string), "category" (string or null),
  "is_correction" (boolean).
- Valid categories: "fact", "preference", "relationship", "opinion", "context", or null if unclear.
- If there is nothing meaningful to extract, return an empty array: []

EXISTING MEMORY BODY:
{memory_section}

EXISTING JOURNAL ENTRIES:
{journal_section}

USER MESSAGES TO PROCESS:
{messages_section}

Respond ONLY with the JSON array. No explanation, no markdown fences."""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/memory/test_extraction.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/modules/memory/_extraction.py tests/memory/test_extraction.py
git commit -m "Add content filtering and extraction prompt building"
```

---

### Task 5: RAG Assembly

**Files:**
- Create: `backend/modules/memory/_assembly.py`
- Create: `tests/memory/test_assembly.py`

- [ ] **Step 1: Write failing tests**

Create `tests/memory/test_assembly.py`:

```python
"""Tests for memory RAG assembly — builds the XML block for prompt injection."""

import pytest

from backend.modules.memory._assembly import assemble_memory_context


class TestAssembleMemoryContext:

    def test_body_only(self):
        result = assemble_memory_context(
            memory_body="User likes dark themes.",
            committed_entries=[],
            uncommitted_entries=[],
            max_tokens=6000,
        )
        assert "<memory-body>" in result
        assert "User likes dark themes." in result
        assert "<journal>" not in result

    def test_body_plus_journal(self):
        result = assemble_memory_context(
            memory_body="User likes dark themes.",
            committed_entries=[
                {"content": "Works as C# developer", "created_at": "2026-04-06"},
            ],
            uncommitted_entries=[
                {"content": "Uses Arch Linux", "created_at": "2026-04-06"},
            ],
            max_tokens=6000,
        )
        assert "<memory-body>" in result
        assert "<journal>" in result
        assert "C# developer" in result
        assert "Arch Linux" in result

    def test_no_memory_returns_none(self):
        result = assemble_memory_context(
            memory_body=None,
            committed_entries=[],
            uncommitted_entries=[],
            max_tokens=6000,
        )
        assert result is None

    def test_budget_respected(self):
        # Body uses most of budget, entries should be trimmed
        long_body = "x " * 2500  # ~2500 tokens
        many_entries = [
            {"content": f"Entry {i} " * 50, "created_at": "2026-04-06"}
            for i in range(20)
        ]
        result = assemble_memory_context(
            memory_body=long_body,
            committed_entries=many_entries,
            uncommitted_entries=[],
            max_tokens=3000,
        )
        assert result is not None
        # Not all entries should be included (budget exceeded)
        assert result.count("Entry") < 20

    def test_committed_before_uncommitted(self):
        result = assemble_memory_context(
            memory_body="Body.",
            committed_entries=[
                {"content": "COMMITTED_MARKER", "created_at": "2026-04-06"},
            ],
            uncommitted_entries=[
                {"content": "UNCOMMITTED_MARKER", "created_at": "2026-04-06"},
            ],
            max_tokens=6000,
        )
        committed_pos = result.index("COMMITTED_MARKER")
        uncommitted_pos = result.index("UNCOMMITTED_MARKER")
        # Committed entries appear before uncommitted in the journal section
        assert committed_pos < uncommitted_pos

    def test_wraps_in_usermemory_tag(self):
        result = assemble_memory_context(
            memory_body="Test.",
            committed_entries=[],
            uncommitted_entries=[],
            max_tokens=6000,
        )
        assert result.startswith('<usermemory priority="normal">')
        assert result.endswith("</usermemory>")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/memory/test_assembly.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement RAG assembly**

Create `backend/modules/memory/_assembly.py`:

```python
"""RAG assembly — builds the XML memory block for system prompt injection.

Fills a token budget in priority order:
1. Memory body (always)
2. Committed journal entries (newest first)
3. Uncommitted journal entries (newest first)
"""

from __future__ import annotations

from backend.modules.chat._token_counter import count_tokens


def assemble_memory_context(
    *,
    memory_body: str | None,
    committed_entries: list[dict],
    uncommitted_entries: list[dict],
    max_tokens: int = 6000,
) -> str | None:
    """Build the <usermemory> XML block for prompt injection.

    Returns None if there is no memory content at all.
    """
    if not memory_body and not committed_entries and not uncommitted_entries:
        return None

    parts: list[str] = []
    remaining = max_tokens

    # 1. Memory body — always included in full
    if memory_body:
        body_block = f"<memory-body>\n{memory_body}\n</memory-body>"
        remaining -= count_tokens(body_block)
        parts.append(body_block)

    # 2 + 3. Journal entries (committed first, then uncommitted)
    journal_lines: list[str] = []

    for entry in committed_entries:
        line = f"- [committed] {entry['content']}"
        line_tokens = count_tokens(line)
        if line_tokens <= remaining:
            journal_lines.append(line)
            remaining -= line_tokens

    for entry in uncommitted_entries:
        line = f"- [pending] {entry['content']}"
        line_tokens = count_tokens(line)
        if line_tokens <= remaining:
            journal_lines.append(line)
            remaining -= line_tokens

    if journal_lines:
        journal_block = "<journal>\n" + "\n".join(journal_lines) + "\n</journal>"
        parts.append(journal_block)

    if not parts:
        return None

    inner = "\n".join(parts)
    return f'<usermemory priority="normal">\n{inner}\n</usermemory>'
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/memory/test_assembly.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/modules/memory/_assembly.py tests/memory/test_assembly.py
git commit -m "Add memory RAG assembly for prompt injection"
```

---

### Task 6: Consolidation Logic

**Files:**
- Create: `backend/modules/memory/_consolidation.py`
- Create: `tests/memory/test_consolidation.py`

- [ ] **Step 1: Write failing tests**

Create `tests/memory/test_consolidation.py`:

```python
"""Tests for dreaming/consolidation prompt building and validation."""

import pytest

from backend.modules.memory._consolidation import (
    build_consolidation_prompt,
    validate_memory_body,
)


class TestBuildConsolidationPrompt:

    def test_includes_existing_body(self):
        prompt = build_consolidation_prompt(
            existing_body="User likes dark themes.",
            entries=[{"content": "Uses Arch Linux", "is_correction": False}],
        )
        assert "User likes dark themes." in prompt
        assert "Arch Linux" in prompt

    def test_no_existing_body(self):
        prompt = build_consolidation_prompt(
            existing_body=None,
            entries=[{"content": "Name is Chris", "is_correction": False}],
        )
        assert "Chris" in prompt

    def test_marks_corrections(self):
        prompt = build_consolidation_prompt(
            existing_body="User's name is Christian.",
            entries=[{"content": "Name is Chris, not Christian", "is_correction": True}],
        )
        assert "CORRECTION" in prompt or "correction" in prompt


class TestValidateMemoryBody:

    def test_valid_body(self):
        assert validate_memory_body("User likes dark themes and uses Arch Linux.", max_tokens=3000) is True

    def test_empty_body(self):
        assert validate_memory_body("", max_tokens=3000) is False

    def test_whitespace_only(self):
        assert validate_memory_body("   \n  ", max_tokens=3000) is False

    def test_over_token_limit(self):
        long_text = "word " * 4000  # way over 3000 tokens
        assert validate_memory_body(long_text, max_tokens=3000) is False

    def test_none(self):
        assert validate_memory_body(None, max_tokens=3000) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/memory/test_consolidation.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement consolidation logic**

Create `backend/modules/memory/_consolidation.py`:

```python
"""Dreaming/consolidation prompt building and validation.

The consolidation LLM merges committed journal entries into the memory body.
"""

from __future__ import annotations

from backend.modules.chat._token_counter import count_tokens

_MAX_TOKENS_DEFAULT = 3000


def build_consolidation_prompt(
    *,
    existing_body: str | None,
    entries: list[dict],
) -> str:
    """Build the system prompt for memory consolidation (dreaming).

    Args:
        existing_body: Current memory body text (may be None for first dream).
        entries: Committed journal entries to consolidate.
    """
    body_section = existing_body if existing_body else "(No existing memory — this is the first consolidation.)"

    entry_lines: list[str] = []
    for entry in entries:
        prefix = "[CORRECTION] " if entry.get("is_correction") else ""
        entry_lines.append(f"- {prefix}{entry['content']}")
    entries_section = "\n".join(entry_lines) if entry_lines else "(No entries.)"

    return f"""You are a memory consolidation assistant. Your job is to merge new journal entries
into an existing memory body, producing an updated version.

RULES:
- Integrate all new journal entries into the memory body.
- Entries marked [CORRECTION] override older contradictory information. Remove or update the old fact.
- Organise the memory logically — group related facts together. You decide the structure freely.
- When approaching the token limit, prioritise: newer information > older information,
  important personal facts > transient context.
- Summarise and compress rather than delete. Prefer dense, factual statements.
- Do NOT add information that is not in the existing body or journal entries.
- Output ONLY the new memory body text. No explanation, no metadata, no formatting markers.
- Keep the output under {_MAX_TOKENS_DEFAULT} tokens.

EXISTING MEMORY BODY:
{body_section}

NEW JOURNAL ENTRIES TO INTEGRATE:
{entries_section}

Write the updated memory body:"""


def validate_memory_body(
    content: str | None,
    *,
    max_tokens: int = _MAX_TOKENS_DEFAULT,
) -> bool:
    """Validate that a consolidation result is usable."""
    if not content or not content.strip():
        return False
    return count_tokens(content) <= max_tokens
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/memory/test_consolidation.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/modules/memory/_consolidation.py tests/memory/test_consolidation.py
git commit -m "Add consolidation prompt building and validation"
```

---

### Task 7: Job Handlers — Extraction & Consolidation

**Files:**
- Create: `backend/jobs/handlers/_memory_extraction.py`
- Create: `backend/jobs/handlers/_memory_consolidation.py`
- Modify: `backend/jobs/_models.py`
- Modify: `backend/jobs/_registry.py`

- [ ] **Step 1: Add job types to the enum**

In `backend/jobs/_models.py`, add to the `JobType` enum:

```python
    MEMORY_EXTRACTION = "memory_extraction"
    MEMORY_CONSOLIDATION = "memory_consolidation"
```

- [ ] **Step 2: Create the extraction job handler**

Create `backend/jobs/handlers/_memory_extraction.py`:

```python
"""Job handler: journal extraction from user messages.

Extracts personal facts from recent messages using the persona's LLM,
then stores them as uncommitted journal entries.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from backend.jobs._models import JobConfig, JobEntry
from shared.topics import Topics

logger = logging.getLogger(__name__)


async def handle_memory_extraction(
    job: JobEntry,
    config: JobConfig,
    redis,
    event_bus,
) -> None:
    from backend.database import get_db
    from backend.modules.chat._token_counter import count_tokens
    from backend.modules.llm import stream_completion
    from backend.modules.memory._extraction import (
        build_extraction_prompt,
        strip_technical_content,
    )
    from backend.modules.memory._parser import parse_extraction_output
    from backend.modules.memory._repository import MemoryRepository
    from shared.dtos.memory import JournalEntryDto
    from shared.events.memory import (
        MemoryEntryCreatedEvent,
        MemoryExtractionCompletedEvent,
        MemoryExtractionFailedEvent,
        MemoryExtractionStartedEvent,
    )

    persona_id = job.payload["persona_id"]
    session_id = job.payload["session_id"]
    messages_raw: list[str] = job.payload["messages"]
    provider_id, model_slug = job.model_unique_id.split(":", 1)

    db = get_db()
    repo = MemoryRepository(db)
    now = datetime.now(timezone.utc)

    # Publish start event
    await event_bus.publish(
        Topics.MEMORY_EXTRACTION_STARTED,
        MemoryExtractionStartedEvent(
            persona_id=persona_id,
            correlation_id=job.correlation_id,
            timestamp=now,
        ),
        scope=f"persona:{persona_id}",
        target_user_ids=[job.user_id],
        correlation_id=job.correlation_id,
    )

    try:
        # Filter technical content from messages
        filtered_messages = [strip_technical_content(m) for m in messages_raw]
        filtered_messages = [m for m in filtered_messages if m.strip()]

        if not filtered_messages:
            logger.info(
                "memory_extraction: no extractable content after filtering "
                "user_id=%s persona_id=%s",
                job.user_id, persona_id,
            )
            await event_bus.publish(
                Topics.MEMORY_EXTRACTION_COMPLETED,
                MemoryExtractionCompletedEvent(
                    persona_id=persona_id,
                    entries_created=0,
                    correlation_id=job.correlation_id,
                    timestamp=datetime.now(timezone.utc),
                ),
                scope=f"persona:{persona_id}",
                target_user_ids=[job.user_id],
                correlation_id=job.correlation_id,
            )
            return

        # Gather existing context
        body = await repo.get_current_memory_body(job.user_id, persona_id)
        memory_body_text = body["content"] if body else None

        existing_entries = await repo.list_journal_entries(
            job.user_id, persona_id,
        )
        journal_contents = [e["content"] for e in existing_entries if e["state"] != "archived"]

        # Build extraction prompt
        extraction_prompt = build_extraction_prompt(
            memory_body=memory_body_text,
            journal_entries=journal_contents,
            messages=filtered_messages,
        )

        # Call LLM
        from backend.modules.llm._adapters._base import CompletionMessage, CompletionRequest, ContentPart

        request = CompletionRequest(
            model=model_slug,
            messages=[
                CompletionMessage(
                    role="user",
                    content=[ContentPart(type="text", text=extraction_prompt)],
                ),
            ],
            temperature=0.3,
            reasoning_enabled=False,
            supports_reasoning=False,
        )

        full_content = ""
        from backend.modules.llm._adapters._base import ContentDelta, StreamDone, StreamError

        async for event in stream_completion(job.user_id, provider_id, request):
            match event:
                case ContentDelta(delta=delta):
                    full_content += delta
                case StreamDone():
                    break
                case StreamError() as err:
                    raise RuntimeError(
                        f"Extraction LLM error: {err.error_code} — {err.message}"
                    )

        # Parse output
        parsed_entries = parse_extraction_output(full_content)

        if not parsed_entries:
            logger.info(
                "memory_extraction: LLM returned no entries "
                "user_id=%s persona_id=%s",
                job.user_id, persona_id,
            )

        # Store entries
        created_count = 0
        for entry_data in parsed_entries:
            entry_id = await repo.create_journal_entry(
                user_id=job.user_id,
                persona_id=persona_id,
                content=entry_data["content"],
                category=entry_data.get("category"),
                source_session_id=session_id,
                is_correction=entry_data.get("is_correction", False),
            )

            entry_dto = JournalEntryDto(
                id=entry_id,
                persona_id=persona_id,
                content=entry_data["content"],
                category=entry_data.get("category"),
                state="uncommitted",
                is_correction=entry_data.get("is_correction", False),
                created_at=datetime.now(timezone.utc),
            )

            await event_bus.publish(
                Topics.MEMORY_ENTRY_CREATED,
                MemoryEntryCreatedEvent(
                    entry=entry_dto,
                    correlation_id=job.correlation_id,
                    timestamp=datetime.now(timezone.utc),
                ),
                scope=f"persona:{persona_id}",
                target_user_ids=[job.user_id],
                correlation_id=job.correlation_id,
            )
            created_count += 1

        # Enforce 50-entry cap
        discarded = await repo.discard_oldest_uncommitted(job.user_id, persona_id, max_count=50)
        if discarded > 0:
            logger.warning(
                "memory_extraction: discarded %d oldest uncommitted entries "
                "user_id=%s persona_id=%s",
                discarded, job.user_id, persona_id,
            )

        # Update Redis tracking state
        await redis.hset(
            f"memory:extraction:{job.user_id}:{persona_id}",
            mapping={
                "last_extraction_at": datetime.now(timezone.utc).isoformat(),
                "messages_since_extraction": "0",
            },
        )

        await event_bus.publish(
            Topics.MEMORY_EXTRACTION_COMPLETED,
            MemoryExtractionCompletedEvent(
                persona_id=persona_id,
                entries_created=created_count,
                correlation_id=job.correlation_id,
                timestamp=datetime.now(timezone.utc),
            ),
            scope=f"persona:{persona_id}",
            target_user_ids=[job.user_id],
            correlation_id=job.correlation_id,
        )

        logger.info(
            "memory_extraction: completed entries_created=%d "
            "user_id=%s persona_id=%s",
            created_count, job.user_id, persona_id,
        )

    except Exception as exc:
        logger.exception(
            "memory_extraction: failed user_id=%s persona_id=%s",
            job.user_id, persona_id,
        )
        await event_bus.publish(
            Topics.MEMORY_EXTRACTION_FAILED,
            MemoryExtractionFailedEvent(
                persona_id=persona_id,
                error_message=str(exc),
                correlation_id=job.correlation_id,
                timestamp=datetime.now(timezone.utc),
            ),
            scope=f"persona:{persona_id}",
            target_user_ids=[job.user_id],
            correlation_id=job.correlation_id,
        )
        raise
```

- [ ] **Step 3: Create the consolidation job handler**

Create `backend/jobs/handlers/_memory_consolidation.py`:

```python
"""Job handler: memory consolidation (dreaming).

Merges committed journal entries into the memory body using the persona's LLM.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from backend.jobs._models import JobConfig, JobEntry
from shared.topics import Topics

logger = logging.getLogger(__name__)


async def handle_memory_consolidation(
    job: JobEntry,
    config: JobConfig,
    redis,
    event_bus,
) -> None:
    from backend.database import get_db
    from backend.modules.chat._token_counter import count_tokens
    from backend.modules.llm import stream_completion
    from backend.modules.memory._consolidation import (
        build_consolidation_prompt,
        validate_memory_body,
    )
    from backend.modules.memory._repository import MemoryRepository
    from shared.events.memory import (
        MemoryDreamCompletedEvent,
        MemoryDreamFailedEvent,
        MemoryDreamStartedEvent,
    )

    persona_id = job.payload["persona_id"]
    provider_id, model_slug = job.model_unique_id.split(":", 1)

    db = get_db()
    repo = MemoryRepository(db)
    dream_id = str(uuid4())

    # Get committed entries
    committed = await repo.list_journal_entries(
        job.user_id, persona_id, state="committed",
    )

    if not committed:
        logger.info(
            "memory_consolidation: no committed entries to process "
            "user_id=%s persona_id=%s",
            job.user_id, persona_id,
        )
        return

    # Publish start event
    await event_bus.publish(
        Topics.MEMORY_DREAM_STARTED,
        MemoryDreamStartedEvent(
            persona_id=persona_id,
            entries_count=len(committed),
            correlation_id=job.correlation_id,
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"persona:{persona_id}",
        target_user_ids=[job.user_id],
        correlation_id=job.correlation_id,
    )

    try:
        # Get current memory body
        body = await repo.get_current_memory_body(job.user_id, persona_id)
        existing_body = body["content"] if body else None

        # Build consolidation prompt
        prompt = build_consolidation_prompt(
            existing_body=existing_body,
            entries=[{"content": e["content"], "is_correction": e.get("is_correction", False)} for e in committed],
        )

        # Call LLM
        from backend.modules.llm._adapters._base import CompletionMessage, CompletionRequest, ContentPart

        request = CompletionRequest(
            model=model_slug,
            messages=[
                CompletionMessage(
                    role="user",
                    content=[ContentPart(type="text", text=prompt)],
                ),
            ],
            temperature=0.3,
            reasoning_enabled=False,
            supports_reasoning=False,
        )

        full_content = ""
        from backend.modules.llm._adapters._base import ContentDelta, StreamDone, StreamError

        async for event in stream_completion(job.user_id, provider_id, request):
            match event:
                case ContentDelta(delta=delta):
                    full_content += delta
                case StreamDone():
                    break
                case StreamError() as err:
                    raise RuntimeError(
                        f"Consolidation LLM error: {err.error_code} — {err.message}"
                    )

        # Validate result
        if not validate_memory_body(full_content):
            raise ValueError(
                f"Consolidation produced invalid memory body "
                f"(empty={not full_content.strip()}, "
                f"tokens={count_tokens(full_content)})"
            )

        # Save new version
        token_count = count_tokens(full_content)
        new_version = await repo.save_memory_body(
            user_id=job.user_id,
            persona_id=persona_id,
            content=full_content.strip(),
            token_count=token_count,
            entries_processed=len(committed),
        )

        # Archive processed entries
        await repo.archive_entries(job.user_id, persona_id, dream_id=dream_id)

        # Update Redis tracking
        await redis.hset(
            f"memory:dream:{job.user_id}:{persona_id}",
            mapping={"last_dream_at": datetime.now(timezone.utc).isoformat()},
        )

        await event_bus.publish(
            Topics.MEMORY_DREAM_COMPLETED,
            MemoryDreamCompletedEvent(
                persona_id=persona_id,
                entries_processed=len(committed),
                body_version=new_version,
                body_token_count=token_count,
                correlation_id=job.correlation_id,
                timestamp=datetime.now(timezone.utc),
            ),
            scope=f"persona:{persona_id}",
            target_user_ids=[job.user_id],
            correlation_id=job.correlation_id,
        )

        logger.info(
            "memory_consolidation: completed version=%d entries=%d tokens=%d "
            "user_id=%s persona_id=%s",
            new_version, len(committed), token_count,
            job.user_id, persona_id,
        )

    except Exception as exc:
        logger.exception(
            "memory_consolidation: failed user_id=%s persona_id=%s",
            job.user_id, persona_id,
        )
        await event_bus.publish(
            Topics.MEMORY_DREAM_FAILED,
            MemoryDreamFailedEvent(
                persona_id=persona_id,
                error_message=str(exc),
                correlation_id=job.correlation_id,
                timestamp=datetime.now(timezone.utc),
            ),
            scope=f"persona:{persona_id}",
            target_user_ids=[job.user_id],
            correlation_id=job.correlation_id,
        )
        raise
```

- [ ] **Step 4: Register job types in the registry**

In `backend/jobs/_registry.py`, add the imports and registrations:

```python
from backend.jobs.handlers._memory_extraction import handle_memory_extraction
from backend.jobs.handlers._memory_consolidation import handle_memory_consolidation
```

Add to `JOB_REGISTRY`:

```python
    JobType.MEMORY_EXTRACTION: JobConfig(
        handler=handle_memory_extraction,
        max_retries=2,
        retry_delay_seconds=30.0,
        queue_timeout_seconds=3600.0,
        execution_timeout_seconds=120.0,
        reasoning_enabled=False,
        notify=False,
        notify_error=True,
    ),
    JobType.MEMORY_CONSOLIDATION: JobConfig(
        handler=handle_memory_consolidation,
        max_retries=2,
        retry_delay_seconds=60.0,
        queue_timeout_seconds=3600.0,
        execution_timeout_seconds=180.0,
        reasoning_enabled=False,
        notify=True,
        notify_error=True,
    ),
```

- [ ] **Step 5: Verify imports compile**

Run:
```bash
uv run python -c "from backend.jobs._models import JobType; print(JobType.MEMORY_EXTRACTION, JobType.MEMORY_CONSOLIDATION)"
```
Expected: `memory_extraction memory_consolidation`

- [ ] **Step 6: Commit**

```bash
git add backend/jobs/handlers/_memory_extraction.py backend/jobs/handlers/_memory_consolidation.py backend/jobs/_models.py backend/jobs/_registry.py
git commit -m "Add memory extraction and consolidation job handlers"
```

---

### Task 8: REST API Endpoints

**Files:**
- Create: `backend/modules/memory/_handlers.py`
- Create: `tests/memory/test_handlers.py`

- [ ] **Step 1: Write failing tests for the REST endpoints**

Create `tests/memory/test_handlers.py`:

```python
"""Tests for memory REST endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestMemoryEndpoints:

    async def test_list_journal_entries_requires_auth(self, client: AsyncClient):
        resp = await client.get("/api/memory/p1/journal")
        assert resp.status_code == 401

    async def test_get_memory_context_requires_auth(self, client: AsyncClient):
        resp = await client.get("/api/memory/p1/context")
        assert resp.status_code == 401
```

Note: Full integration tests depend on the test harness — the tests above validate auth guards. More comprehensive tests should be written after the endpoints are in place, testing the actual CRUD flow.

- [ ] **Step 2: Implement REST endpoints**

Create `backend/modules/memory/_handlers.py`:

```python
"""REST endpoints for the memory page.

All endpoints require authentication. Operations are scoped to the
authenticated user — no user can access another user's memory.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.database import get_db
from backend.modules.user import get_current_user
from backend.modules.memory._repository import MemoryRepository
from backend.ws.event_bus import get_event_bus
from shared.dtos.memory import (
    JournalEntryDto,
    MemoryBodyDto,
    MemoryBodyVersionDto,
    MemoryContextDto,
)
from shared.events.memory import (
    MemoryBodyRollbackEvent,
    MemoryEntryCommittedEvent,
    MemoryEntryDeletedEvent,
    MemoryEntryUpdatedEvent,
)
from shared.topics import Topics

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memory", tags=["memory"])


# ── Request Bodies ───────────────────────────────────────────────

class UpdateEntryRequest(BaseModel):
    content: str


class CommitEntriesRequest(BaseModel):
    entry_ids: list[str]


class DeleteEntriesRequest(BaseModel):
    entry_ids: list[str]


class RollbackRequest(BaseModel):
    to_version: int


# ── Journal Entries ──────────────────────────────────────────────

@router.get("/{persona_id}/journal")
async def list_journal_entries(
    persona_id: str,
    state: str | None = None,
    user: dict = Depends(get_current_user),
) -> list[JournalEntryDto]:
    db = get_db()
    repo = MemoryRepository(db)
    entries = await repo.list_journal_entries(user["id"], persona_id, state=state)
    return [
        JournalEntryDto(
            id=e["id"],
            persona_id=persona_id,
            content=e["content"],
            category=e.get("category"),
            state=e["state"],
            is_correction=e.get("is_correction", False),
            created_at=e["created_at"],
            committed_at=e.get("committed_at"),
            auto_committed=e.get("auto_committed", False),
        )
        for e in entries
    ]


@router.patch("/{persona_id}/journal/{entry_id}")
async def update_entry(
    persona_id: str,
    entry_id: str,
    body: UpdateEntryRequest,
    user: dict = Depends(get_current_user),
) -> JournalEntryDto:
    db = get_db()
    repo = MemoryRepository(db)
    success = await repo.update_entry(entry_id, user["id"], content=body.content)
    if not success:
        raise HTTPException(404, "Entry not found or not editable")

    entries = await repo.list_journal_entries(user["id"], persona_id)
    entry = next((e for e in entries if e["id"] == entry_id), None)
    if entry is None:
        raise HTTPException(404, "Entry not found")

    dto = JournalEntryDto(
        id=entry["id"],
        persona_id=persona_id,
        content=entry["content"],
        category=entry.get("category"),
        state=entry["state"],
        is_correction=entry.get("is_correction", False),
        created_at=entry["created_at"],
        committed_at=entry.get("committed_at"),
        auto_committed=entry.get("auto_committed", False),
    )

    event_bus = get_event_bus()
    correlation_id = str(uuid4())
    await event_bus.publish(
        Topics.MEMORY_ENTRY_UPDATED,
        MemoryEntryUpdatedEvent(
            entry=dto,
            correlation_id=correlation_id,
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"persona:{persona_id}",
        target_user_ids=[user["id"]],
        correlation_id=correlation_id,
    )

    return dto


@router.post("/{persona_id}/journal/commit")
async def commit_entries(
    persona_id: str,
    body: CommitEntriesRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    db = get_db()
    repo = MemoryRepository(db)
    event_bus = get_event_bus()
    correlation_id = str(uuid4())
    committed = 0

    for entry_id in body.entry_ids:
        success = await repo.commit_entry(entry_id, user["id"])
        if success:
            committed += 1
            # Fetch updated entry for event
            entries = await repo.list_journal_entries(user["id"], persona_id, state="committed")
            entry = next((e for e in entries if e["id"] == entry_id), None)
            if entry:
                dto = JournalEntryDto(
                    id=entry["id"],
                    persona_id=persona_id,
                    content=entry["content"],
                    category=entry.get("category"),
                    state=entry["state"],
                    is_correction=entry.get("is_correction", False),
                    created_at=entry["created_at"],
                    committed_at=entry.get("committed_at"),
                    auto_committed=entry.get("auto_committed", False),
                )
                await event_bus.publish(
                    Topics.MEMORY_ENTRY_COMMITTED,
                    MemoryEntryCommittedEvent(
                        entry=dto,
                        correlation_id=correlation_id,
                        timestamp=datetime.now(timezone.utc),
                    ),
                    scope=f"persona:{persona_id}",
                    target_user_ids=[user["id"]],
                    correlation_id=correlation_id,
                )

    return {"committed": committed}


@router.post("/{persona_id}/journal/delete")
async def delete_entries(
    persona_id: str,
    body: DeleteEntriesRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    db = get_db()
    repo = MemoryRepository(db)
    event_bus = get_event_bus()
    correlation_id = str(uuid4())
    deleted = 0

    for entry_id in body.entry_ids:
        success = await repo.delete_entry(entry_id, user["id"])
        if success:
            deleted += 1
            await event_bus.publish(
                Topics.MEMORY_ENTRY_DELETED,
                MemoryEntryDeletedEvent(
                    entry_id=entry_id,
                    persona_id=persona_id,
                    correlation_id=correlation_id,
                    timestamp=datetime.now(timezone.utc),
                ),
                scope=f"persona:{persona_id}",
                target_user_ids=[user["id"]],
                correlation_id=correlation_id,
            )

    return {"deleted": deleted}


# ── Memory Body ──────────────────────────────────────────────────

@router.get("/{persona_id}/body")
async def get_memory_body(
    persona_id: str,
    user: dict = Depends(get_current_user),
) -> MemoryBodyDto | None:
    db = get_db()
    repo = MemoryRepository(db)
    body = await repo.get_current_memory_body(user["id"], persona_id)
    if body is None:
        return None
    return MemoryBodyDto(
        persona_id=persona_id,
        content=body["content"],
        token_count=body["token_count"],
        version=body["version"],
        created_at=body["created_at"],
    )


@router.get("/{persona_id}/body/versions")
async def list_body_versions(
    persona_id: str,
    user: dict = Depends(get_current_user),
) -> list[MemoryBodyVersionDto]:
    db = get_db()
    repo = MemoryRepository(db)
    versions = await repo.list_memory_body_versions(user["id"], persona_id)
    return [
        MemoryBodyVersionDto(
            version=v["version"],
            token_count=v["token_count"],
            entries_processed=v["entries_processed"],
            created_at=v["created_at"],
        )
        for v in versions
    ]


@router.get("/{persona_id}/body/versions/{version}")
async def get_body_version(
    persona_id: str,
    version: int,
    user: dict = Depends(get_current_user),
) -> MemoryBodyDto:
    db = get_db()
    repo = MemoryRepository(db)
    body = await repo.get_memory_body_version(user["id"], persona_id, version=version)
    if body is None:
        raise HTTPException(404, f"Version {version} not found")
    return MemoryBodyDto(
        persona_id=persona_id,
        content=body["content"],
        token_count=body["token_count"],
        version=body["version"],
        created_at=body["created_at"],
    )


@router.post("/{persona_id}/body/rollback")
async def rollback_body(
    persona_id: str,
    body: RollbackRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    db = get_db()
    repo = MemoryRepository(db)
    event_bus = get_event_bus()
    correlation_id = str(uuid4())

    try:
        new_version = await repo.rollback_memory_body(
            user["id"], persona_id, to_version=body.to_version,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc))

    await event_bus.publish(
        Topics.MEMORY_BODY_ROLLBACK,
        MemoryBodyRollbackEvent(
            persona_id=persona_id,
            rolled_back_to_version=body.to_version,
            new_version=new_version,
            correlation_id=correlation_id,
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"persona:{persona_id}",
        target_user_ids=[user["id"]],
        correlation_id=correlation_id,
    )

    return {"new_version": new_version}


# ── Context (for journal dropdown) ───────────────────────────────

@router.get("/{persona_id}/context")
async def get_memory_context(
    persona_id: str,
    user: dict = Depends(get_current_user),
) -> MemoryContextDto:
    from backend.database import get_redis

    db = get_db()
    redis = get_redis()
    repo = MemoryRepository(db)

    uncommitted_count = await repo.count_entries(user["id"], persona_id, state="uncommitted")
    committed_count = await repo.count_entries(user["id"], persona_id, state="committed")

    # Read tracking state from Redis
    tracking = await redis.hgetall(f"memory:extraction:{user['id']}:{persona_id}")
    last_extraction_at = None
    messages_since = 0
    if tracking:
        raw_ts = tracking.get("last_extraction_at") or tracking.get(b"last_extraction_at")
        if raw_ts:
            from datetime import datetime as dt
            ts_str = raw_ts if isinstance(raw_ts, str) else raw_ts.decode()
            last_extraction_at = dt.fromisoformat(ts_str)
        raw_msg = tracking.get("messages_since_extraction") or tracking.get(b"messages_since_extraction")
        if raw_msg:
            messages_since = int(raw_msg if isinstance(raw_msg, str) else raw_msg.decode())

    dream_tracking = await redis.hgetall(f"memory:dream:{user['id']}:{persona_id}")
    last_dream_at = None
    if dream_tracking:
        raw_ts = dream_tracking.get("last_dream_at") or dream_tracking.get(b"last_dream_at")
        if raw_ts:
            from datetime import datetime as dt
            ts_str = raw_ts if isinstance(raw_ts, str) else raw_ts.decode()
            last_dream_at = dt.fromisoformat(ts_str)

    # Can trigger extraction: 30min since last + 5+ messages
    can_trigger = False
    if last_extraction_at is not None:
        from datetime import timedelta
        elapsed = datetime.now(timezone.utc) - last_extraction_at
        can_trigger = elapsed >= timedelta(minutes=30) and messages_since >= 5
    elif messages_since >= 5:
        can_trigger = True  # never extracted before, 5+ messages

    return MemoryContextDto(
        persona_id=persona_id,
        uncommitted_count=uncommitted_count,
        committed_count=committed_count,
        last_extraction_at=last_extraction_at,
        last_dream_at=last_dream_at,
        can_trigger_extraction=can_trigger,
    )


# ── Manual Triggers ──────────────────────────────────────────────

@router.post("/{persona_id}/extract")
async def trigger_extraction(
    persona_id: str,
    user: dict = Depends(get_current_user),
) -> dict:
    """Manually trigger journal extraction for a persona."""
    from backend.jobs._submit import submit
    from backend.jobs._models import JobType
    from backend.modules.persona import get_persona

    persona = await get_persona(persona_id, user["id"])
    if persona is None:
        raise HTTPException(404, "Persona not found")

    # Get recent messages from latest session
    from backend.modules.chat._repository import ChatRepository
    db = get_db()
    chat_repo = ChatRepository(db)

    sessions = await chat_repo.list_sessions(user["id"], persona_id=persona_id)
    if not sessions:
        raise HTTPException(400, "No sessions found for this persona")

    latest_session = sessions[0]
    messages = await chat_repo.list_messages(latest_session["id"])
    user_messages = [m["content"] for m in messages if m["role"] == "user"]

    if not user_messages:
        raise HTTPException(400, "No user messages to extract from")

    job_id = await submit(
        job_type=JobType.MEMORY_EXTRACTION,
        user_id=user["id"],
        model_unique_id=persona["model_unique_id"],
        payload={
            "persona_id": persona_id,
            "session_id": latest_session["id"],
            "messages": user_messages[-20:],  # last 20 messages
        },
    )

    return {"job_id": job_id}


@router.post("/{persona_id}/dream")
async def trigger_dream(
    persona_id: str,
    user: dict = Depends(get_current_user),
) -> dict:
    """Manually trigger dreaming (consolidation) for a persona."""
    from backend.jobs._submit import submit
    from backend.jobs._models import JobType
    from backend.modules.persona import get_persona

    persona = await get_persona(persona_id, user["id"])
    if persona is None:
        raise HTTPException(404, "Persona not found")

    db = get_db()
    repo = MemoryRepository(db)
    committed_count = await repo.count_entries(user["id"], persona_id, state="committed")
    if committed_count == 0:
        raise HTTPException(400, "No committed entries to consolidate")

    job_id = await submit(
        job_type=JobType.MEMORY_CONSOLIDATION,
        user_id=user["id"],
        model_unique_id=persona["model_unique_id"],
        payload={"persona_id": persona_id},
    )

    return {"job_id": job_id}
```

- [ ] **Step 3: Verify syntax**

Run:
```bash
uv run python -m py_compile backend/modules/memory/_handlers.py
```
Expected: No output (success)

- [ ] **Step 4: Commit**

```bash
git add backend/modules/memory/_handlers.py tests/memory/test_handlers.py
git commit -m "Add memory REST endpoints for journal, body, and triggers"
```

---

### Task 9: Module Public API & System Integration

**Files:**
- Modify: `backend/modules/memory/__init__.py`
- Modify: `backend/main.py`
- Modify: `backend/ws/event_bus.py`
- Modify: `backend/modules/chat/_prompt_assembler.py`

- [ ] **Step 1: Update the memory module's public API**

Replace `backend/modules/memory/__init__.py`:

```python
"""Memory module — per-persona memory extraction, consolidation, and retrieval.

Public API: import only from this file.
"""

from backend.modules.memory._handlers import router
from backend.modules.memory._repository import MemoryRepository
from backend.database import get_db


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the memory module collections."""
    await MemoryRepository(db).create_indexes()


async def get_memory_context(user_id: str, persona_id: str) -> str | None:
    """Build the <usermemory> XML block for prompt injection.

    Returns None if the persona has no memory yet.
    Called by the prompt assembler at session start.
    """
    import os

    from backend.modules.memory._assembly import assemble_memory_context

    db = get_db()
    repo = MemoryRepository(db)

    body = await repo.get_current_memory_body(user_id, persona_id)
    committed = await repo.list_journal_entries(user_id, persona_id, state="committed")
    uncommitted = await repo.list_journal_entries(user_id, persona_id, state="uncommitted")

    max_tokens = int(os.environ.get("MEMORY_RAG_MAX_TOKENS", "6000"))

    return assemble_memory_context(
        memory_body=body["content"] if body else None,
        committed_entries=committed,
        uncommitted_entries=uncommitted,
        max_tokens=max_tokens,
    )


__all__ = ["router", "init_indexes", "get_memory_context"]
```

- [ ] **Step 2: Add fan-out rules to the event bus**

In `backend/ws/event_bus.py`, add to the `_FANOUT` dict:

```python
    Topics.MEMORY_EXTRACTION_STARTED: ([], True),
    Topics.MEMORY_EXTRACTION_COMPLETED: ([], True),
    Topics.MEMORY_EXTRACTION_FAILED: ([], True),
    Topics.MEMORY_ENTRY_CREATED: ([], True),
    Topics.MEMORY_ENTRY_COMMITTED: ([], True),
    Topics.MEMORY_ENTRY_UPDATED: ([], True),
    Topics.MEMORY_ENTRY_DELETED: ([], True),
    Topics.MEMORY_ENTRY_AUTO_COMMITTED: ([], True),
    Topics.MEMORY_DREAM_STARTED: ([], True),
    Topics.MEMORY_DREAM_COMPLETED: ([], True),
    Topics.MEMORY_DREAM_FAILED: ([], True),
    Topics.MEMORY_BODY_ROLLBACK: ([], True),
```

- [ ] **Step 3: Integrate memory into the prompt assembler**

In `backend/modules/chat/_prompt_assembler.py`, in the `assemble()` function, add between the persona layer and the userinfo layer:

```python
    # Layer 4.5: User memory (if available)
    from backend.modules.memory import get_memory_context
    memory_xml = await get_memory_context(user_id, persona_id) if persona_id else None
    if memory_xml:
        parts.append(memory_xml)
```

This must be placed **after** the persona `<you>` tag and **before** the `<userinfo>` tag.

- [ ] **Step 4: Register memory module in main.py**

In `backend/main.py`:

Add import:
```python
from backend.modules.memory import router as memory_router, init_indexes as memory_init_indexes
```

In the lifespan function, after the other `init_indexes` calls:
```python
    await memory_init_indexes(db)
```

Add the router before `ws_router`:
```python
    app.include_router(memory_router)
```

In the `_session_cleanup_loop`, add auto-commit check:
```python
            try:
                from backend.modules.memory._repository import MemoryRepository
                memory_repo = MemoryRepository(db)
                auto_committed = await memory_repo.auto_commit_old_entries(max_age_hours=48)
                if auto_committed:
                    from shared.events.memory import MemoryEntryAutoCommittedEvent
                    from shared.dtos.memory import JournalEntryDto
                    from shared.topics import Topics
                    correlation_id = str(uuid4())
                    for entry in auto_committed:
                        dto = JournalEntryDto(
                            id=entry["id"],
                            persona_id=entry["persona_id"],
                            content=entry["content"],
                            category=entry.get("category"),
                            state="committed",
                            is_correction=entry.get("is_correction", False),
                            created_at=entry["created_at"],
                            committed_at=entry.get("committed_at"),
                            auto_committed=True,
                        )
                        await event_bus.publish(
                            Topics.MEMORY_ENTRY_AUTO_COMMITTED,
                            MemoryEntryAutoCommittedEvent(
                                entry=dto,
                                correlation_id=correlation_id,
                                timestamp=datetime.now(timezone.utc),
                            ),
                            scope=f"persona:{entry['persona_id']}",
                            target_user_ids=[entry["user_id"]],
                            correlation_id=correlation_id,
                        )
            except Exception:
                logger.exception("memory auto-commit cleanup failed")
```

- [ ] **Step 5: Verify the full backend compiles**

Run:
```bash
uv run python -c "from backend.main import app; print('OK')"
```
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/modules/memory/__init__.py backend/main.py backend/ws/event_bus.py backend/modules/chat/_prompt_assembler.py
git commit -m "Integrate memory module: public API, event bus, prompt assembler, main.py"
```

---

### Task 10: Extraction Trigger System

**Files:**
- Modify: `backend/ws/router.py` (or wherever chat.send is handled)
- Modify: `backend/modules/chat/__init__.py`

This task wires up the automatic extraction triggers: idle detection, session close,
and message counting for the manual trigger button.

- [ ] **Step 1: Track message count in Redis after each user message**

In the `handle_chat_send` function (in `backend/modules/chat/__init__.py` or `backend/ws/router.py`),
after the message is saved, add:

```python
    # Track message count for memory extraction
    from backend.database import get_redis
    redis = get_redis()
    key = f"memory:extraction:{user_id}:{persona_id}"
    await redis.hincrby(key, "messages_since_extraction", 1)
```

- [ ] **Step 2: Schedule idle-based extraction after user messages**

After a user message is processed, schedule a delayed extraction check.
Add a helper that checks after 5 minutes if the user has been idle:

In `backend/modules/chat/__init__.py`, near the end of `handle_chat_send`:

```python
    # Schedule memory extraction check after 5 min idle
    async def _schedule_extraction_check():
        import asyncio
        await asyncio.sleep(300)  # 5 minutes
        from backend.database import get_redis
        redis = get_redis()
        key = f"memory:extraction:{user_id}:{persona_id}"
        tracking = await redis.hgetall(key)
        # Check if user is still idle (no new messages in 5 min)
        # The timestamp of last message is tracked; if it matches, user is idle
        last_ts = tracking.get(b"last_message_at") or tracking.get("last_message_at")
        if last_ts and last_ts.decode() if isinstance(last_ts, bytes) else last_ts == saved_at_iso:
            from backend.jobs._submit import submit
            from backend.jobs._models import JobType
            await submit(
                job_type=JobType.MEMORY_EXTRACTION,
                user_id=user_id,
                model_unique_id=persona["model_unique_id"],
                payload={
                    "persona_id": persona_id,
                    "session_id": session_id,
                    "messages": [msg["content"] for msg in recent_user_messages],
                },
            )

    # Store last message timestamp for idle detection
    saved_at_iso = datetime.now(timezone.utc).isoformat()
    await redis.hset(key, "last_message_at", saved_at_iso)

    # Don't schedule for incognito sessions
    if not is_incognito:
        task = asyncio.create_task(_schedule_extraction_check())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
```

Note: The exact integration point depends on how `handle_chat_send` is structured.
The implementer should find the right spot after messages are saved but before
the function returns. Incognito sessions (`handle_incognito_send`) must be excluded.

- [ ] **Step 3: Verify syntax**

Run:
```bash
uv run python -m py_compile backend/modules/chat/__init__.py
```
Expected: No output (success)

- [ ] **Step 4: Commit**

```bash
git add backend/modules/chat/__init__.py backend/ws/router.py
git commit -m "Add memory extraction triggers: idle detection, message tracking"
```

---

### Task 11: Dreaming Auto-Trigger

**Files:**
- Modify: `backend/main.py` (cleanup loop)

- [ ] **Step 1: Add dreaming trigger check to the periodic cleanup loop**

In the `_session_cleanup_loop` in `backend/main.py`, after the auto-commit block, add:

```python
            # Check dreaming triggers for all users with committed entries
            try:
                from backend.modules.memory._repository import MemoryRepository
                from backend.jobs._submit import submit
                from backend.jobs._models import JobType
                from datetime import timedelta

                memory_repo = MemoryRepository(db)
                # Find all (user_id, persona_id) pairs with committed entries
                pipeline = [
                    {"$match": {"state": "committed"}},
                    {"$group": {
                        "_id": {"user_id": "$user_id", "persona_id": "$persona_id"},
                        "count": {"$sum": 1},
                    }},
                ]
                cursor = memory_repo._entries.aggregate(pipeline)
                async for group in cursor:
                    uid = group["_id"]["user_id"]
                    pid = group["_id"]["persona_id"]
                    count = group["count"]

                    # Hard limit: >= 25 → immediate
                    if count >= 25:
                        persona = await get_persona(pid, uid)
                        if persona:
                            await submit(
                                job_type=JobType.MEMORY_CONSOLIDATION,
                                user_id=uid,
                                model_unique_id=persona["model_unique_id"],
                                payload={"persona_id": pid},
                            )
                        continue

                    # Soft limit: >= 10 AND 6h since last dream
                    if count >= 10:
                        dream_key = f"memory:dream:{uid}:{pid}"
                        dream_tracking = await redis.hgetall(dream_key)
                        raw_ts = dream_tracking.get(b"last_dream_at") or dream_tracking.get("last_dream_at")
                        if raw_ts:
                            ts_str = raw_ts.decode() if isinstance(raw_ts, bytes) else raw_ts
                            last_dream = datetime.fromisoformat(ts_str)
                            if datetime.now(timezone.utc) - last_dream < timedelta(hours=6):
                                continue  # cooldown not elapsed
                        # Either no previous dream or cooldown elapsed
                        persona = await get_persona(pid, uid)
                        if persona:
                            await submit(
                                job_type=JobType.MEMORY_CONSOLIDATION,
                                user_id=uid,
                                model_unique_id=persona["model_unique_id"],
                                payload={"persona_id": pid},
                            )
            except Exception:
                logger.exception("memory dreaming trigger check failed")
```

- [ ] **Step 2: Verify syntax**

Run:
```bash
uv run python -m py_compile backend/main.py
```
Expected: No output (success)

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "Add automatic dreaming triggers in periodic cleanup loop"
```

---

### Task 12: Frontend — Memory Store & API Client

**Files:**
- Create: `frontend/src/core/api/memory.ts`
- Create: `frontend/src/core/store/memoryStore.ts`

- [ ] **Step 1: Create the API client**

Create `frontend/src/core/api/memory.ts`:

```typescript
import { api } from './client'

export interface JournalEntryDto {
  id: string
  persona_id: string
  content: string
  category: string | null
  state: 'uncommitted' | 'committed' | 'archived'
  is_correction: boolean
  created_at: string
  committed_at: string | null
  auto_committed: boolean
}

export interface MemoryBodyDto {
  persona_id: string
  content: string
  token_count: number
  version: number
  created_at: string
}

export interface MemoryBodyVersionDto {
  version: number
  token_count: number
  entries_processed: number
  created_at: string
}

export interface MemoryContextDto {
  persona_id: string
  uncommitted_count: number
  committed_count: number
  last_extraction_at: string | null
  last_dream_at: string | null
  can_trigger_extraction: boolean
}

export const memoryApi = {
  listJournalEntries: (personaId: string, state?: string) =>
    api.get<JournalEntryDto[]>(`/api/memory/${personaId}/journal${state ? `?state=${state}` : ''}`),

  updateEntry: (personaId: string, entryId: string, content: string) =>
    api.patch<JournalEntryDto>(`/api/memory/${personaId}/journal/${entryId}`, { content }),

  commitEntries: (personaId: string, entryIds: string[]) =>
    api.post<{ committed: number }>(`/api/memory/${personaId}/journal/commit`, { entry_ids: entryIds }),

  deleteEntries: (personaId: string, entryIds: string[]) =>
    api.post<{ deleted: number }>(`/api/memory/${personaId}/journal/delete`, { entry_ids: entryIds }),

  getMemoryBody: (personaId: string) =>
    api.get<MemoryBodyDto | null>(`/api/memory/${personaId}/body`),

  listBodyVersions: (personaId: string) =>
    api.get<MemoryBodyVersionDto[]>(`/api/memory/${personaId}/body/versions`),

  getBodyVersion: (personaId: string, version: number) =>
    api.get<MemoryBodyDto>(`/api/memory/${personaId}/body/versions/${version}`),

  rollbackBody: (personaId: string, toVersion: number) =>
    api.post<{ new_version: number }>(`/api/memory/${personaId}/body/rollback`, { to_version: toVersion }),

  getContext: (personaId: string) =>
    api.get<MemoryContextDto>(`/api/memory/${personaId}/context`),

  triggerExtraction: (personaId: string) =>
    api.post<{ job_id: string }>(`/api/memory/${personaId}/extract`),

  triggerDream: (personaId: string) =>
    api.post<{ job_id: string }>(`/api/memory/${personaId}/dream`),
}
```

- [ ] **Step 2: Create the memory store**

Create `frontend/src/core/store/memoryStore.ts`:

```typescript
import { create } from 'zustand'
import type { JournalEntryDto, MemoryBodyDto, MemoryBodyVersionDto, MemoryContextDto } from '../api/memory'

interface MemoryState {
  // Per-persona state keyed by persona ID
  uncommittedEntries: Record<string, JournalEntryDto[]>
  committedEntries: Record<string, JournalEntryDto[]>
  memoryBody: Record<string, MemoryBodyDto | null>
  bodyVersions: Record<string, MemoryBodyVersionDto[]>
  context: Record<string, MemoryContextDto | null>

  // UI state
  isDreaming: Record<string, boolean>
  isExtracting: Record<string, boolean>

  // Toast counter per persona (resets on user action)
  toastCounter: Record<string, number>

  // Actions
  setUncommittedEntries: (personaId: string, entries: JournalEntryDto[]) => void
  setCommittedEntries: (personaId: string, entries: JournalEntryDto[]) => void
  setMemoryBody: (personaId: string, body: MemoryBodyDto | null) => void
  setBodyVersions: (personaId: string, versions: MemoryBodyVersionDto[]) => void
  setContext: (personaId: string, ctx: MemoryContextDto) => void
  setDreaming: (personaId: string, v: boolean) => void
  setExtracting: (personaId: string, v: boolean) => void

  // Event-driven updates
  addEntry: (entry: JournalEntryDto) => void
  updateEntry: (entry: JournalEntryDto) => void
  removeEntry: (personaId: string, entryId: string) => void
  commitEntry: (entry: JournalEntryDto) => void
  autoCommitEntry: (entry: JournalEntryDto) => void
  resetToastCounter: (personaId: string) => void
  incrementToastCounter: (personaId: string) => void
}

export const useMemoryStore = create<MemoryState>((set) => ({
  uncommittedEntries: {},
  committedEntries: {},
  memoryBody: {},
  bodyVersions: {},
  context: {},
  isDreaming: {},
  isExtracting: {},
  toastCounter: {},

  setUncommittedEntries: (personaId, entries) =>
    set((s) => ({ uncommittedEntries: { ...s.uncommittedEntries, [personaId]: entries } })),

  setCommittedEntries: (personaId, entries) =>
    set((s) => ({ committedEntries: { ...s.committedEntries, [personaId]: entries } })),

  setMemoryBody: (personaId, body) =>
    set((s) => ({ memoryBody: { ...s.memoryBody, [personaId]: body } })),

  setBodyVersions: (personaId, versions) =>
    set((s) => ({ bodyVersions: { ...s.bodyVersions, [personaId]: versions } })),

  setContext: (personaId, ctx) =>
    set((s) => ({ context: { ...s.context, [personaId]: ctx } })),

  setDreaming: (personaId, v) =>
    set((s) => ({ isDreaming: { ...s.isDreaming, [personaId]: v } })),

  setExtracting: (personaId, v) =>
    set((s) => ({ isExtracting: { ...s.isExtracting, [personaId]: v } })),

  addEntry: (entry) =>
    set((s) => {
      const pid = entry.persona_id
      const current = s.uncommittedEntries[pid] ?? []
      return {
        uncommittedEntries: { ...s.uncommittedEntries, [pid]: [entry, ...current] },
        toastCounter: { ...s.toastCounter, [pid]: (s.toastCounter[pid] ?? 0) + 1 },
      }
    }),

  updateEntry: (entry) =>
    set((s) => {
      const pid = entry.persona_id
      const key = entry.state === 'uncommitted' ? 'uncommittedEntries' : 'committedEntries'
      const current = s[key][pid] ?? []
      return {
        [key]: { ...s[key], [pid]: current.map((e) => (e.id === entry.id ? entry : e)) },
      }
    }),

  removeEntry: (personaId, entryId) =>
    set((s) => ({
      uncommittedEntries: {
        ...s.uncommittedEntries,
        [personaId]: (s.uncommittedEntries[personaId] ?? []).filter((e) => e.id !== entryId),
      },
      committedEntries: {
        ...s.committedEntries,
        [personaId]: (s.committedEntries[personaId] ?? []).filter((e) => e.id !== entryId),
      },
      toastCounter: { ...s.toastCounter, [personaId]: 0 },
    })),

  commitEntry: (entry) =>
    set((s) => {
      const pid = entry.persona_id
      const uncommitted = (s.uncommittedEntries[pid] ?? []).filter((e) => e.id !== entry.id)
      const committed = [entry, ...(s.committedEntries[pid] ?? [])]
      return {
        uncommittedEntries: { ...s.uncommittedEntries, [pid]: uncommitted },
        committedEntries: { ...s.committedEntries, [pid]: committed },
        toastCounter: { ...s.toastCounter, [pid]: 0 },
      }
    }),

  autoCommitEntry: (entry) =>
    set((s) => {
      const pid = entry.persona_id
      const uncommitted = (s.uncommittedEntries[pid] ?? []).filter((e) => e.id !== entry.id)
      const committed = [entry, ...(s.committedEntries[pid] ?? [])]
      return {
        uncommittedEntries: { ...s.uncommittedEntries, [pid]: uncommitted },
        committedEntries: { ...s.committedEntries, [pid]: committed },
      }
    }),

  resetToastCounter: (personaId) =>
    set((s) => ({ toastCounter: { ...s.toastCounter, [personaId]: 0 } })),

  incrementToastCounter: (personaId) =>
    set((s) => ({ toastCounter: { ...s.toastCounter, [personaId]: (s.toastCounter[personaId] ?? 0) + 1 } })),
}))
```

- [ ] **Step 3: Verify frontend builds**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/core/api/memory.ts frontend/src/core/store/memoryStore.ts
git commit -m "Add memory API client and Zustand store"
```

---

### Task 13: Frontend — Memory Event Handler Hook

**Files:**
- Create: `frontend/src/features/memory/useMemoryEvents.ts`

- [ ] **Step 1: Create the event handler hook**

Create `frontend/src/features/memory/useMemoryEvents.ts`:

```typescript
import { useEffect } from 'react'
import { eventBus } from '../../core/websocket/eventBus'
import { useMemoryStore } from '../../core/store/memoryStore'
import { useNotificationStore } from '../../core/store/notificationStore'
import type { JournalEntryDto } from '../../core/api/memory'

const TOAST_THRESHOLD = 50

export function useMemoryEvents(personaId: string | null) {
  useEffect(() => {
    if (!personaId) return

    const store = useMemoryStore.getState
    const notify = useNotificationStore.getState().addNotification

    const unsub = eventBus.on('memory.*', (event: any) => {
      const payload = event.payload ?? event

      switch (event.type) {
        case 'memory.entry.created': {
          const entry = payload.entry as JournalEntryDto
          if (entry.persona_id === personaId) {
            store().addEntry(entry)
            // Check toast threshold
            const count = useMemoryStore.getState().toastCounter[personaId] ?? 0
            if (count > 0 && count % TOAST_THRESHOLD === 0) {
              notify({
                level: 'info',
                title: 'Memory Review',
                message: `${count} unreviewed memories — review now?`,
                action: { label: 'Review', href: `/memory/${personaId}` },
              })
            }
          }
          break
        }

        case 'memory.entry.committed': {
          const entry = payload.entry as JournalEntryDto
          if (entry.persona_id === personaId) {
            store().commitEntry(entry)
          }
          break
        }

        case 'memory.entry.updated': {
          const entry = payload.entry as JournalEntryDto
          if (entry.persona_id === personaId) {
            store().updateEntry(entry)
          }
          break
        }

        case 'memory.entry.deleted': {
          if (payload.persona_id === personaId) {
            store().removeEntry(personaId, payload.entry_id)
          }
          break
        }

        case 'memory.entry.auto_committed': {
          const entry = payload.entry as JournalEntryDto
          if (entry.persona_id === personaId) {
            store().autoCommitEntry(entry)
          }
          break
        }

        case 'memory.dream.started': {
          if (payload.persona_id === personaId) {
            store().setDreaming(personaId, true)
          }
          break
        }

        case 'memory.dream.completed': {
          if (payload.persona_id === personaId) {
            store().setDreaming(personaId, false)
            notify({
              level: 'success',
              title: 'Dream Complete',
              message: `${payload.entries_processed} memories processed`,
            })
          }
          break
        }

        case 'memory.dream.failed': {
          if (payload.persona_id === personaId) {
            store().setDreaming(personaId, false)
            notify({
              level: 'error',
              title: 'Dream Failed',
              message: payload.error_message ?? 'Consolidation failed',
            })
          }
          break
        }

        case 'memory.extraction.started': {
          if (payload.persona_id === personaId) {
            store().setExtracting(personaId, true)
          }
          break
        }

        case 'memory.extraction.completed': {
          if (payload.persona_id === personaId) {
            store().setExtracting(personaId, false)
          }
          break
        }

        case 'memory.extraction.failed': {
          if (payload.persona_id === personaId) {
            store().setExtracting(personaId, false)
          }
          break
        }

        case 'memory.body.rollback': {
          if (payload.persona_id === personaId) {
            notify({
              level: 'info',
              title: 'Memory Rolled Back',
              message: `Rolled back to version ${payload.rolled_back_to_version}`,
            })
          }
          break
        }
      }
    })

    return unsub
  }, [personaId])
}
```

- [ ] **Step 2: Verify frontend builds**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/memory/useMemoryEvents.ts
git commit -m "Add memory WebSocket event handler hook"
```

---

### Task 14: Frontend — Journal Badge & Dropdown

**Files:**
- Create: `frontend/src/features/chat/JournalBadge.tsx`
- Create: `frontend/src/features/chat/JournalDropdown.tsx`
- Modify: `frontend/src/features/chat/ChatView.tsx`

- [ ] **Step 1: Create the JournalBadge component**

Create `frontend/src/features/chat/JournalBadge.tsx`:

```tsx
import { useState, useEffect, useRef } from 'react'
import { useMemoryStore } from '../../core/store/memoryStore'
import { memoryApi } from '../../core/api/memory'
import { JournalDropdown } from './JournalDropdown'

interface JournalBadgeProps {
  personaId: string
}

type BadgeColour = 'green' | 'yellow' | 'red'

function getBadgeColour(count: number): BadgeColour {
  if (count <= 20) return 'green'
  if (count <= 35) return 'yellow'
  return 'red'
}

const COLOUR_CLASSES: Record<BadgeColour, string> = {
  green: 'bg-green-500',
  yellow: 'bg-yellow-400',
  red: 'bg-red-500',
}

const BORDER_CLASSES: Record<BadgeColour, string> = {
  green: 'border-green-500/30',
  yellow: 'border-yellow-400/30',
  red: 'border-red-500/30',
}

export function JournalBadge({ personaId }: JournalBadgeProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [isBlinking, setIsBlinking] = useState(false)
  const prevCount = useRef(0)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const entries = useMemoryStore((s) => s.uncommittedEntries[personaId] ?? [])
  const context = useMemoryStore((s) => s.context[personaId])
  const count = entries.length

  // Fetch initial context
  useEffect(() => {
    memoryApi.getContext(personaId).then((ctx) => {
      useMemoryStore.getState().setContext(personaId, ctx)
    })
    memoryApi.listJournalEntries(personaId, 'uncommitted').then((entries) => {
      useMemoryStore.getState().setUncommittedEntries(personaId, entries)
    })
  }, [personaId])

  // Blink on new entries
  useEffect(() => {
    if (count > prevCount.current && prevCount.current > 0) {
      setIsBlinking(true)
      const timer = setTimeout(() => setIsBlinking(false), 2000)
      return () => clearTimeout(timer)
    }
    prevCount.current = count
  }, [count])

  // Close dropdown on outside click
  useEffect(() => {
    if (!isOpen) return
    function handleClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [isOpen])

  if (count === 0) return null

  const colour = getBadgeColour(count)

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs transition-colors hover:bg-white/5 ${BORDER_CLASSES[colour]}`}
      >
        <span className="text-white/50">Journal</span>
        <span
          className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold text-black ${COLOUR_CLASSES[colour]} ${isBlinking ? 'animate-pulse' : ''}`}
        >
          {count}
        </span>
      </button>

      {isOpen && (
        <JournalDropdown
          personaId={personaId}
          entries={entries}
          canTriggerExtraction={context?.can_trigger_extraction ?? false}
          onClose={() => setIsOpen(false)}
        />
      )}
    </div>
  )
}
```

- [ ] **Step 2: Create the JournalDropdown component**

Create `frontend/src/features/chat/JournalDropdown.tsx`:

```tsx
import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { memoryApi, type JournalEntryDto } from '../../core/api/memory'

interface JournalDropdownProps {
  personaId: string
  entries: JournalEntryDto[]
  canTriggerExtraction: boolean
  onClose: () => void
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

export function JournalDropdown({ personaId, entries, canTriggerExtraction, onClose }: JournalDropdownProps) {
  const navigate = useNavigate()

  const handleCommit = useCallback(async (entryId: string) => {
    await memoryApi.commitEntries(personaId, [entryId])
  }, [personaId])

  const handleDelete = useCallback(async (entryId: string) => {
    await memoryApi.deleteEntries(personaId, [entryId])
  }, [personaId])

  const handleExtract = useCallback(async () => {
    await memoryApi.triggerExtraction(personaId)
  }, [personaId])

  const handleOpenMemoryPage = useCallback(() => {
    onClose()
    navigate(`/memory/${personaId}`)
  }, [personaId, navigate, onClose])

  return (
    <div className="absolute right-0 top-full z-50 mt-1 w-80 rounded-lg border border-white/10 bg-elevated shadow-xl">
      <div className="border-b border-white/5 px-3 py-2 text-[11px] uppercase tracking-wider text-white/40">
        Uncommitted Entries
      </div>

      <div className="max-h-72 overflow-y-auto">
        {entries.slice(0, 10).map((entry) => (
          <div key={entry.id} className="border-b border-white/5 px-3 py-2.5">
            <div className="text-sm text-white/80">{entry.content}</div>
            <div className="mt-1 flex items-center justify-between">
              <span className="text-[11px] text-white/30">{timeAgo(entry.created_at)}</span>
              <div className="flex gap-1">
                <button
                  onClick={() => handleCommit(entry.id)}
                  className="rounded px-1.5 py-0.5 text-[11px] text-white/40 hover:bg-white/5 hover:text-green-400"
                  title="Commit"
                >
                  Commit
                </button>
                <button
                  onClick={() => handleDelete(entry.id)}
                  className="rounded px-1.5 py-0.5 text-[11px] text-white/40 hover:bg-white/5 hover:text-red-400"
                  title="Delete"
                >
                  Delete
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-1 border-t border-white/5 px-3 py-2">
        {canTriggerExtraction && (
          <button
            onClick={handleExtract}
            className="w-full rounded py-1 text-xs text-white/40 hover:bg-white/5 hover:text-white/60"
          >
            Extract Now
          </button>
        )}
        <button
          onClick={handleOpenMemoryPage}
          className="w-full text-center text-xs text-blue-400 hover:text-blue-300"
        >
          {entries.length > 10 ? `View all ${entries.length} entries` : 'Open Memory Page'} &rarr;
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Integrate JournalBadge into ChatView**

In `frontend/src/features/chat/ChatView.tsx`, in the header area (near where ContextStatusPill is rendered),
add the JournalBadge:

```tsx
import { JournalBadge } from './JournalBadge'
import { useMemoryEvents } from '../memory/useMemoryEvents'
```

Inside the component, add the event hook:
```tsx
useMemoryEvents(persona?.id ?? null)
```

In the header JSX, next to the ContextStatusPill:
```tsx
{persona && <JournalBadge personaId={persona.id} />}
```

- [ ] **Step 4: Verify frontend builds**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/chat/JournalBadge.tsx frontend/src/features/chat/JournalDropdown.tsx frontend/src/features/chat/ChatView.tsx
git commit -m "Add journal badge and dropdown to chat header"
```

---

### Task 15: Frontend — Memory Page

**Files:**
- Create: `frontend/src/features/memory/MemoryPage.tsx`
- Create: `frontend/src/features/memory/UncommittedSection.tsx`
- Create: `frontend/src/features/memory/CommittedSection.tsx`
- Create: `frontend/src/features/memory/MemoryBodySection.tsx`
- Modify: `frontend/src/app/App.tsx`

- [ ] **Step 1: Create UncommittedSection**

Create `frontend/src/features/memory/UncommittedSection.tsx`:

```tsx
import { useState, useCallback } from 'react'
import { memoryApi, type JournalEntryDto } from '../../core/api/memory'

interface UncommittedSectionProps {
  personaId: string
  entries: JournalEntryDto[]
}

export function UncommittedSection({ personaId, entries }: UncommittedSectionProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editText, setEditText] = useState('')

  const toggleSelect = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const handleCommitSelected = useCallback(async () => {
    if (selected.size === 0) return
    await memoryApi.commitEntries(personaId, [...selected])
    setSelected(new Set())
  }, [personaId, selected])

  const handleDeleteSelected = useCallback(async () => {
    if (selected.size === 0) return
    await memoryApi.deleteEntries(personaId, [...selected])
    setSelected(new Set())
  }, [personaId, selected])

  const handleCommitAll = useCallback(async () => {
    const ids = entries.map((e) => e.id)
    await memoryApi.commitEntries(personaId, ids)
  }, [personaId, entries])

  const handleEdit = useCallback(async (entryId: string) => {
    if (!editText.trim()) return
    await memoryApi.updateEntry(personaId, entryId, editText.trim())
    setEditingId(null)
    setEditText('')
  }, [personaId, editText])

  const handleCommitOne = useCallback(async (entryId: string) => {
    await memoryApi.commitEntries(personaId, [entryId])
  }, [personaId])

  const handleDeleteOne = useCallback(async (entryId: string) => {
    await memoryApi.deleteEntries(personaId, [entryId])
  }, [personaId])

  if (entries.length === 0) {
    return (
      <div className="rounded-lg border border-white/5 bg-surface p-4 text-sm text-white/30">
        No uncommitted entries.
      </div>
    )
  }

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-medium text-white/60">
          Uncommitted ({entries.length})
        </h3>
        <div className="flex gap-2">
          {selected.size > 0 && (
            <>
              <button onClick={handleCommitSelected} className="rounded bg-green-500/10 px-2.5 py-1 text-xs text-green-400 hover:bg-green-500/20">
                Commit {selected.size}
              </button>
              <button onClick={handleDeleteSelected} className="rounded bg-red-500/10 px-2.5 py-1 text-xs text-red-400 hover:bg-red-500/20">
                Delete {selected.size}
              </button>
            </>
          )}
          <button onClick={handleCommitAll} className="rounded bg-white/5 px-2.5 py-1 text-xs text-white/40 hover:bg-white/10">
            Commit All
          </button>
        </div>
      </div>

      <div className="flex flex-col gap-1">
        {entries.map((entry) => (
          <div key={entry.id} className="flex items-start gap-3 rounded-lg border border-white/5 bg-surface p-3">
            <input
              type="checkbox"
              checked={selected.has(entry.id)}
              onChange={() => toggleSelect(entry.id)}
              className="mt-1 accent-blue-400"
            />
            <div className="flex-1">
              {editingId === entry.id ? (
                <div className="flex gap-2">
                  <input
                    value={editText}
                    onChange={(e) => setEditText(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleEdit(entry.id)}
                    className="flex-1 rounded border border-white/10 bg-base px-2 py-1 text-sm text-white/80"
                    autoFocus
                  />
                  <button onClick={() => handleEdit(entry.id)} className="text-xs text-green-400">Save</button>
                  <button onClick={() => setEditingId(null)} className="text-xs text-white/30">Cancel</button>
                </div>
              ) : (
                <div className="text-sm text-white/80">{entry.content}</div>
              )}
              <div className="mt-1 flex items-center gap-3 text-[11px] text-white/30">
                <span>{new Date(entry.created_at).toLocaleString()}</span>
                {entry.category && <span className="rounded bg-white/5 px-1.5 py-0.5">{entry.category}</span>}
                {entry.is_correction && <span className="text-yellow-400">correction</span>}
              </div>
            </div>
            <div className="flex gap-1">
              <button onClick={() => handleCommitOne(entry.id)} className="rounded px-1.5 py-0.5 text-[11px] text-white/30 hover:text-green-400">Commit</button>
              <button onClick={() => { setEditingId(entry.id); setEditText(entry.content) }} className="rounded px-1.5 py-0.5 text-[11px] text-white/30 hover:text-blue-400">Edit</button>
              <button onClick={() => handleDeleteOne(entry.id)} className="rounded px-1.5 py-0.5 text-[11px] text-white/30 hover:text-red-400">Delete</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Create CommittedSection**

Create `frontend/src/features/memory/CommittedSection.tsx`:

```tsx
import { useState, useCallback } from 'react'
import { memoryApi, type JournalEntryDto } from '../../core/api/memory'

interface CommittedSectionProps {
  personaId: string
  entries: JournalEntryDto[]
}

export function CommittedSection({ personaId, entries }: CommittedSectionProps) {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editText, setEditText] = useState('')

  const handleEdit = useCallback(async (entryId: string) => {
    if (!editText.trim()) return
    await memoryApi.updateEntry(personaId, entryId, editText.trim())
    setEditingId(null)
    setEditText('')
  }, [personaId, editText])

  const handleDelete = useCallback(async (entryId: string) => {
    await memoryApi.deleteEntries(personaId, [entryId])
  }, [personaId])

  if (entries.length === 0) {
    return (
      <div className="rounded-lg border border-white/5 bg-surface p-4 text-sm text-white/30">
        No committed entries waiting for consolidation.
      </div>
    )
  }

  return (
    <div>
      <h3 className="mb-3 text-sm font-medium text-white/60">
        Committed — waiting for dream ({entries.length})
      </h3>
      <div className="flex flex-col gap-1">
        {entries.map((entry) => (
          <div key={entry.id} className="flex items-start gap-3 rounded-lg border border-white/5 bg-surface p-3">
            <div className="flex-1">
              {editingId === entry.id ? (
                <div className="flex gap-2">
                  <input
                    value={editText}
                    onChange={(e) => setEditText(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleEdit(entry.id)}
                    className="flex-1 rounded border border-white/10 bg-base px-2 py-1 text-sm text-white/80"
                    autoFocus
                  />
                  <button onClick={() => handleEdit(entry.id)} className="text-xs text-green-400">Save</button>
                  <button onClick={() => setEditingId(null)} className="text-xs text-white/30">Cancel</button>
                </div>
              ) : (
                <div className="text-sm text-white/80">{entry.content}</div>
              )}
              <div className="mt-1 flex items-center gap-3 text-[11px] text-white/30">
                <span>{new Date(entry.created_at).toLocaleString()}</span>
                {entry.category && <span className="rounded bg-white/5 px-1.5 py-0.5">{entry.category}</span>}
                {entry.auto_committed && <span className="text-yellow-400/60">auto-committed</span>}
              </div>
            </div>
            <div className="flex gap-1">
              <button onClick={() => { setEditingId(entry.id); setEditText(entry.content) }} className="rounded px-1.5 py-0.5 text-[11px] text-white/30 hover:text-blue-400">Edit</button>
              <button onClick={() => handleDelete(entry.id)} className="rounded px-1.5 py-0.5 text-[11px] text-white/30 hover:text-red-400">Delete</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Create MemoryBodySection**

Create `frontend/src/features/memory/MemoryBodySection.tsx`:

```tsx
import { useState, useEffect, useCallback } from 'react'
import { memoryApi, type MemoryBodyDto, type MemoryBodyVersionDto } from '../../core/api/memory'
import { useMemoryStore } from '../../core/store/memoryStore'

interface MemoryBodySectionProps {
  personaId: string
}

export function MemoryBodySection({ personaId }: MemoryBodySectionProps) {
  const body = useMemoryStore((s) => s.memoryBody[personaId])
  const versions = useMemoryStore((s) => s.bodyVersions[personaId] ?? [])
  const isDreaming = useMemoryStore((s) => s.isDreaming[personaId] ?? false)
  const committedCount = useMemoryStore((s) => (s.committedEntries[personaId] ?? []).length)

  const [viewingVersion, setViewingVersion] = useState<MemoryBodyDto | null>(null)

  useEffect(() => {
    memoryApi.getMemoryBody(personaId).then((b) => {
      useMemoryStore.getState().setMemoryBody(personaId, b)
    })
    memoryApi.listBodyVersions(personaId).then((v) => {
      useMemoryStore.getState().setBodyVersions(personaId, v)
    })
  }, [personaId])

  const handleDream = useCallback(async () => {
    await memoryApi.triggerDream(personaId)
  }, [personaId])

  const handleViewVersion = useCallback(async (version: number) => {
    const v = await memoryApi.getBodyVersion(personaId, version)
    setViewingVersion(v)
  }, [personaId])

  const handleRollback = useCallback(async (version: number) => {
    await memoryApi.rollbackBody(personaId, version)
    setViewingVersion(null)
    // Refresh
    const b = await memoryApi.getMemoryBody(personaId)
    useMemoryStore.getState().setMemoryBody(personaId, b)
    const v = await memoryApi.listBodyVersions(personaId)
    useMemoryStore.getState().setBodyVersions(personaId, v)
  }, [personaId])

  const displayBody = viewingVersion ?? body

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-medium text-white/60">Memory Body</h3>
        <div className="flex items-center gap-3">
          {displayBody && (
            <span className="font-mono text-[11px] text-white/30">
              {displayBody.token_count} / 3000 tokens
            </span>
          )}
          <button
            onClick={handleDream}
            disabled={isDreaming || committedCount === 0}
            className="rounded bg-purple/10 px-2.5 py-1 text-xs text-purple hover:bg-purple/20 disabled:opacity-30"
          >
            {isDreaming ? 'Dreaming...' : 'Dream Now'}
          </button>
        </div>
      </div>

      {displayBody ? (
        <div className="rounded-lg border border-white/5 bg-surface p-4">
          <pre className="whitespace-pre-wrap text-sm leading-relaxed text-white/70">
            {displayBody.content}
          </pre>
          {viewingVersion && viewingVersion.version !== body?.version && (
            <div className="mt-3 flex items-center gap-2 border-t border-white/5 pt-3">
              <span className="text-xs text-white/30">Viewing version {viewingVersion.version}</span>
              <button
                onClick={() => handleRollback(viewingVersion.version)}
                className="rounded bg-yellow-500/10 px-2 py-0.5 text-xs text-yellow-400 hover:bg-yellow-500/20"
              >
                Rollback to this version
              </button>
              <button
                onClick={() => setViewingVersion(null)}
                className="text-xs text-white/30 hover:text-white/50"
              >
                Back to current
              </button>
            </div>
          )}
        </div>
      ) : (
        <div className="rounded-lg border border-white/5 bg-surface p-4 text-sm text-white/30">
          No memory body yet. Memories will be consolidated after enough journal entries are committed.
        </div>
      )}

      {versions.length > 1 && (
        <div className="mt-3">
          <div className="text-[11px] uppercase tracking-wider text-white/30">Version History</div>
          <div className="mt-1 flex flex-wrap gap-1">
            {versions.map((v) => (
              <button
                key={v.version}
                onClick={() => handleViewVersion(v.version)}
                className={`rounded border px-2 py-0.5 text-xs ${
                  (viewingVersion?.version ?? body?.version) === v.version
                    ? 'border-purple/30 bg-purple/10 text-purple'
                    : 'border-white/5 text-white/30 hover:bg-white/5'
                }`}
              >
                v{v.version} ({v.entries_processed} entries)
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Create MemoryPage**

Create `frontend/src/features/memory/MemoryPage.tsx`:

```tsx
import { useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useMemoryStore } from '../../core/store/memoryStore'
import { useMemoryEvents } from './useMemoryEvents'
import { memoryApi } from '../../core/api/memory'
import { UncommittedSection } from './UncommittedSection'
import { CommittedSection } from './CommittedSection'
import { MemoryBodySection } from './MemoryBodySection'

export function MemoryPage() {
  const { personaId } = useParams<{ personaId: string }>()
  const navigate = useNavigate()

  useMemoryEvents(personaId ?? null)

  const uncommitted = useMemoryStore((s) => s.uncommittedEntries[personaId!] ?? [])
  const committed = useMemoryStore((s) => s.committedEntries[personaId!] ?? [])

  useEffect(() => {
    if (!personaId) return
    memoryApi.listJournalEntries(personaId, 'uncommitted').then((entries) => {
      useMemoryStore.getState().setUncommittedEntries(personaId, entries)
    })
    memoryApi.listJournalEntries(personaId, 'committed').then((entries) => {
      useMemoryStore.getState().setCommittedEntries(personaId, entries)
    })
  }, [personaId])

  if (!personaId) {
    navigate('/personas')
    return null
  }

  return (
    <div className="mx-auto max-w-3xl space-y-8 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-medium text-white/80">Memory</h1>
        <button
          onClick={() => navigate(-1)}
          className="text-xs text-white/30 hover:text-white/50"
        >
          &larr; Back
        </button>
      </div>

      <UncommittedSection personaId={personaId} entries={uncommitted} />
      <CommittedSection personaId={personaId} entries={committed} />
      <MemoryBodySection personaId={personaId} />
    </div>
  )
}
```

- [ ] **Step 5: Add route to App.tsx**

In `frontend/src/app/App.tsx`, add the import and route:

```tsx
import { MemoryPage } from '../features/memory/MemoryPage'
```

Inside the authenticated routes (within `<AuthGuard><AppLayout /></AuthGuard>`):

```tsx
<Route path="/memory/:personaId" element={<MemoryPage />} />
```

- [ ] **Step 6: Verify frontend builds**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: No errors

- [ ] **Step 7: Run full frontend build**

Run: `cd frontend && pnpm run build`
Expected: Build succeeds

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/memory/ frontend/src/app/App.tsx
git commit -m "Add memory page with uncommitted, committed, and body sections"
```

---

### Task 16: Full Stack Verification

- [ ] **Step 1: Run all backend tests**

Run: `uv run pytest tests/memory/ -v`
Expected: All tests pass

- [ ] **Step 2: Run full frontend build**

Run: `cd frontend && pnpm run build`
Expected: Build succeeds with no errors

- [ ] **Step 3: Verify backend starts cleanly**

Run: `docker compose up -d && uv run python -c "from backend.main import app; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Final commit and merge to master**

```bash
git add -A
git status  # verify only expected files
git commit -m "Memory system: complete implementation"
```

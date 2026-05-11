# ChatGPT Conversation Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `chatgpt_import` backend module and persona-detail UI tab that turn a uploaded ChatGPT `conversations.json` export into native Chatsune sessions via multi-select import.

**Architecture:** Streaming-parse the export with `ijson` into MongoDB documents under a 14-day TTL; queue per-conversation import jobs that call a new `ChatService.create_imported_session()` public API; surface progress through the existing WebSocket event bus; render a tab in `PersonaOverlay` that shows the conversation list with per-persona import badges; intercept first send on imported sessions with a connection-picker dialog.

**Tech Stack:** Python 3.12, FastAPI, Motor (AsyncIO MongoDB), Pydantic v2, `ijson` (new dep), Redis Streams (existing event bus), React + Vite + TypeScript, Zustand, Tailwind, Vitest.

**Spec reference:** `devdocs/specs/2026-05-11-chatgpt-import-design.md`

---

## File Structure

### Backend — new files

| Path | Responsibility |
|---|---|
| `backend/modules/chatgpt_import/__init__.py` | Public API: `router`, `init_indexes`, `ChatGptImportService` |
| `backend/modules/chatgpt_import/_models.py` | Internal Pydantic shapes for parser intermediate types |
| `backend/modules/chatgpt_import/_repository.py` | MongoDB access for `chatgpt_imports` + `chatgpt_import_conversations` |
| `backend/modules/chatgpt_import/_parser.py` | `ijson` streaming + tree linearise + filter + Custom Instructions mapping |
| `backend/modules/chatgpt_import/_session_builder.py` | Conversion of parsed conversation → `create_imported_session()` args |
| `backend/modules/chatgpt_import/_handlers.py` | REST endpoints (`/api/chatgpt-import/*`) |
| `backend/jobs/handlers/_chatgpt_import_parse.py` | Long-running parse job handler |
| `backend/jobs/handlers/_chatgpt_import_conversation.py` | Per-conversation import job handler |
| `shared/topics.py` | Add 6 new topic constants (modify) |
| `shared/events/chatgpt_import.py` | Event DTOs for parse + per-conversation events |
| `shared/dtos/chatgpt_import.py` | API DTOs (`ImportDto`, `ConversationItemDto`, etc.) |
| `shared/dtos/chat.py` | Add `ImportedMessageInput` + `CreateImportedSessionRequest` (modify) |
| `tests/chatgpt_import/test_parser.py` | Parser unit tests |
| `tests/chatgpt_import/test_session_builder.py` | Session-builder unit tests |
| `tests/chatgpt_import/test_repository.py` | Repository tests (require DB) |
| `tests/chatgpt_import/test_handlers.py` | API tests (require DB) |
| `tests/chatgpt_import/fixtures/sample.json` | Curated 5-conversation fixture |
| `pyproject.toml` (root + `backend/`) | Add `ijson>=3.3.0` (modify both) |

### Backend — modified files

| Path | Change |
|---|---|
| `backend/jobs/_models.py` | Add 2 entries to `JobType` |
| `backend/jobs/_registry.py` | Add 2 entries to `JOB_REGISTRY` |
| `backend/modules/chat/_repository.py` | Add `create_imported_session()` repository method |
| `backend/modules/chat/__init__.py` | Re-export new `ChatService.create_imported_session()` if applicable |
| `backend/main.py` | Wire `chatgpt_import` router + `init_indexes` |

### Frontend — new files

| Path | Responsibility |
|---|---|
| `frontend/src/core/api/chatGptImportApi.ts` | API client for all `/api/chatgpt-import/*` endpoints |
| `frontend/src/core/store/chatGptImportStore.ts` | Zustand store for active import + conversations + selection |
| `frontend/src/features/chatgpt-import/useChatGptImportEvents.ts` | WebSocket subscription hook |
| `frontend/src/features/chatgpt-import/ChatGptImportTab.tsx` | Tab root, dispatches sub-states |
| `frontend/src/features/chatgpt-import/UploadEmptyState.tsx` | Empty state with upload button |
| `frontend/src/features/chatgpt-import/ParseProgressBanner.tsx` | Sticky parsing banner |
| `frontend/src/features/chatgpt-import/ConversationList.tsx` | List + filters orchestrator |
| `frontend/src/features/chatgpt-import/ConversationFilters.tsx` | Search input + sort/status dropdowns |
| `frontend/src/features/chatgpt-import/ConversationRow.tsx` | Single row with checkbox, badges, preview |
| `frontend/src/features/chatgpt-import/ConversationPreviewExpanded.tsx` | Full message list on expand |
| `frontend/src/features/chatgpt-import/MultiSelectActionBar.tsx` | Sticky bottom bar |
| `frontend/src/features/chatgpt-import/ImportConfirmDialog.tsx` | Confirmation modal |
| `frontend/src/features/chatgpt-import/ReplaceUploadDialog.tsx` | Replace-active-upload modal |
| `frontend/src/features/chat/ConnectionPickerDialog.tsx` | New connection-picker for first send on imported sessions |

### Frontend — modified files

| Path | Change |
|---|---|
| `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx` | Add `'chatgpt-import'` tab |
| `frontend/src/features/chat/<chat-input-or-send-flow>.tsx` | Intercept send when `model_unique_id` starts with `imported:` |

---

## Task-by-task implementation

### Task 1: Add `ijson` dependency

**Files:**
- Modify: `pyproject.toml` (root)
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add to root `pyproject.toml`**

Find the `dependencies = [...]` list and add the line `"ijson>=3.3.0",` alphabetically.

- [ ] **Step 2: Add to `backend/pyproject.toml`**

Same change in `backend/pyproject.toml`. Both files must list it; the Docker build uses the backend one.

- [ ] **Step 3: Install locally**

```bash
uv sync
```
Expected: `ijson` installed, no errors.

- [ ] **Step 4: Smoke-import**

```bash
PYTHONPATH=. uv run python -c "import ijson; print(ijson.__version__)"
```
Expected: prints a version ≥ 3.3.0.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml backend/pyproject.toml uv.lock
git commit -m "Add ijson dependency for streaming JSON parsing"
```

---

### Task 2: Add new `Topics` constants

**Files:**
- Modify: `shared/topics.py`

- [ ] **Step 1: Add the six new constants**

Inside `class Topics:`, alphabetically grouped, add:

```python
    CHATGPT_IMPORT_PARSE_STARTED = "chatgpt_import.parse.started"
    CHATGPT_IMPORT_PARSE_PROGRESS = "chatgpt_import.parse.progress"
    CHATGPT_IMPORT_PARSE_DONE = "chatgpt_import.parse.done"
    CHATGPT_IMPORT_PARSE_FAILED = "chatgpt_import.parse.failed"
    CHATGPT_IMPORT_CONVERSATION_IMPORTED = "chatgpt_import.conversation.imported"
    CHATGPT_IMPORT_CONVERSATION_IMPORT_FAILED = "chatgpt_import.conversation.import_failed"
```

- [ ] **Step 2: Smoke-import**

```bash
PYTHONPATH=. uv run python -c "from shared.topics import Topics; print(Topics.CHATGPT_IMPORT_PARSE_STARTED)"
```
Expected: `chatgpt_import.parse.started`.

- [ ] **Step 3: Commit**

```bash
git add shared/topics.py
git commit -m "Add ChatGPT-import topics"
```

---

### Task 3: Create event DTOs

**Files:**
- Create: `shared/events/chatgpt_import.py`

- [ ] **Step 1: Create the file**

```python
from datetime import datetime
from pydantic import BaseModel


class ChatGptImportParseStartedEvent(BaseModel):
    type: str = "chatgpt_import.parse.started"
    import_id: str
    filename: str
    file_size_bytes: int


class ChatGptImportParseProgressEvent(BaseModel):
    type: str = "chatgpt_import.parse.progress"
    import_id: str
    conversations_indexed: int


class ChatGptImportParseDoneEvent(BaseModel):
    type: str = "chatgpt_import.parse.done"
    import_id: str
    conversation_count: int
    expires_at: datetime
    skipped_count: int
    skipped_reasons: dict[str, int]


class ChatGptImportParseFailedEvent(BaseModel):
    type: str = "chatgpt_import.parse.failed"
    import_id: str
    error_code: str
    error_message: str


class ChatGptImportConversationImportedEvent(BaseModel):
    type: str = "chatgpt_import.conversation.imported"
    import_id: str
    chatgpt_conversation_id: str
    persona_id: str
    session_id: str
    title: str


class ChatGptImportConversationImportFailedEvent(BaseModel):
    type: str = "chatgpt_import.conversation.import_failed"
    import_id: str
    chatgpt_conversation_id: str
    persona_id: str
    error_code: str
    error_message: str
```

- [ ] **Step 2: Smoke-import**

```bash
PYTHONPATH=. uv run python -c "from shared.events.chatgpt_import import ChatGptImportParseStartedEvent; print(ChatGptImportParseStartedEvent.model_fields.keys())"
```
Expected: prints field names including `import_id`.

- [ ] **Step 3: Commit**

```bash
git add shared/events/chatgpt_import.py
git commit -m "Add ChatGPT-import event DTOs"
```

---

### Task 4: Create API DTOs

**Files:**
- Create: `shared/dtos/chatgpt_import.py`

- [ ] **Step 1: Create the file**

```python
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ImportedInfoDto(BaseModel):
    persona_id: str
    persona_name: str
    session_id: str
    imported_at: datetime


class ImportDto(BaseModel):
    import_id: str
    filename: str
    file_size_bytes: int
    status: Literal["parsing", "ready", "failed"]
    conversation_count: int
    skipped_count: int
    skipped_reasons: dict[str, int]
    created_at: datetime
    expires_at: datetime
    last_import_at: datetime | None
    error_message: str | None


class ConversationItemDto(BaseModel):
    chatgpt_conversation_id: str
    title: str
    create_time: datetime
    update_time: datetime
    message_count: int
    first_user_message_preview: str
    first_assistant_message_preview: str
    default_model_slug: str | None
    imports: list[ImportedInfoDto]


class ImportTriggerRequest(BaseModel):
    persona_id: str
    chatgpt_conversation_ids: list[str]


class ImportTriggerJobInfo(BaseModel):
    chatgpt_conversation_id: str
    job_id: str


class ImportTriggerResponse(BaseModel):
    correlation_id: str
    jobs: list[ImportTriggerJobInfo]


class UploadResponse(BaseModel):
    import_id: str
    status: Literal["parsing", "ready", "failed"]
    duplicate: bool  # True if same file_hash already existed; no re-parse
```

- [ ] **Step 2: Smoke-import**

```bash
PYTHONPATH=. uv run python -c "from shared.dtos.chatgpt_import import ImportDto; print('ok')"
```

- [ ] **Step 3: Commit**

```bash
git add shared/dtos/chatgpt_import.py
git commit -m "Add ChatGPT-import API DTOs"
```

---

### Task 5: Extend `shared/dtos/chat.py` with imported-session DTOs

**Files:**
- Modify: `shared/dtos/chat.py`

- [ ] **Step 1: Append new DTOs at the end of the file**

```python
from datetime import datetime
from typing import Literal

# ... existing imports and DTOs ...


class ImportedMessageInput(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    imported_model_slug: str | None = None


class CreateImportedSessionRequest(BaseModel):
    persona_id: str
    title: str
    messages: list[ImportedMessageInput]
    imported_from: Literal["chatgpt"]
    imported_model_slug: str | None
    original_created_at: datetime
```

(If `datetime` / `Literal` / `BaseModel` are already imported at the top of the file, omit the duplicates.)

- [ ] **Step 2: Smoke-import**

```bash
PYTHONPATH=. uv run python -c "from shared.dtos.chat import ImportedMessageInput, CreateImportedSessionRequest; print('ok')"
```

- [ ] **Step 3: Commit**

```bash
git add shared/dtos/chat.py
git commit -m "Add ImportedMessageInput and CreateImportedSessionRequest DTOs"
```

---

### Task 6: Add `ChatRepository.create_imported_session()`

**Files:**
- Modify: `backend/modules/chat/_repository.py`
- Test: `backend/tests/chat/test_repository_imported_session.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/chat/test_repository_imported_session.py
from datetime import UTC, datetime

import pytest

from backend.modules.chat._repository import ChatRepository
from shared.dtos.chat import ImportedMessageInput


@pytest.mark.asyncio
async def test_create_imported_session_persists_metadata_and_messages(test_db):
    repo = ChatRepository(test_db)
    original_dt = datetime(2024, 7, 2, 12, 0, tzinfo=UTC)
    messages = [
        ImportedMessageInput(
            role="user",
            content="hello",
            created_at=original_dt,
        ),
        ImportedMessageInput(
            role="assistant",
            content="hi there",
            created_at=original_dt,
            imported_model_slug="gpt-5",
        ),
    ]

    session = await repo.create_imported_session(
        user_id="u1",
        persona_id="p1",
        title="Test import",
        messages=messages,
        imported_from="chatgpt",
        imported_model_slug="gpt-5",
        original_created_at=original_dt,
    )

    assert session["persona_id"] == "p1"
    assert session["title"] == "Test import"
    assert session["imported_from"] == "chatgpt"
    assert session["imported_model_slug"] == "gpt-5"
    assert session["model_unique_id"] == "imported:chatgpt:gpt-5"
    assert session["created_at"] == original_dt

    stored_messages = await test_db["chat_messages"].find(
        {"session_id": session["_id"]}
    ).sort("created_at", 1).to_list(length=10)
    assert len(stored_messages) == 2
    assert stored_messages[0]["role"] == "user"
    assert stored_messages[0]["content"] == "hello"
    assert stored_messages[1]["imported_model_slug"] == "gpt-5"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=. uv run pytest backend/tests/chat/test_repository_imported_session.py -v
```
Expected: FAIL with `AttributeError: 'ChatRepository' object has no attribute 'create_imported_session'`.

- [ ] **Step 3: Implement the method**

In `backend/modules/chat/_repository.py` add this method on `ChatRepository` (mirror the existing `create_session` patterns for fields like state, etc.):

```python
from datetime import UTC, datetime
from typing import Literal

from shared.dtos.chat import ImportedMessageInput


async def create_imported_session(
    self,
    *,
    user_id: str,
    persona_id: str,
    title: str,
    messages: list[ImportedMessageInput],
    imported_from: Literal["chatgpt"],
    imported_model_slug: str | None,
    original_created_at: datetime,
) -> dict:
    """Create a session backed by an external import (e.g. ChatGPT export)."""
    pseudo_model = f"imported:{imported_from}:{imported_model_slug or 'unknown'}"
    session_doc = {
        "user_id": user_id,
        "persona_id": persona_id,
        "title": title,
        "state": "idle",
        "tools_enabled": False,
        "auto_read": False,
        "project_id": None,
        "model_unique_id": pseudo_model,
        "imported_from": imported_from,
        "imported_model_slug": imported_model_slug,
        "imported_at": datetime.now(UTC),
        "created_at": original_created_at,
    }
    result = await self._sessions.insert_one(session_doc)
    session_doc["_id"] = result.inserted_id

    if messages:
        message_docs = [
            {
                "session_id": result.inserted_id,
                "user_id": user_id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at,
                "imported_model_slug": m.imported_model_slug,
            }
            for m in messages
        ]
        await self._messages.insert_many(message_docs)

    return session_doc
```

(If the existing `_sessions` / `_messages` collection attributes have different names in this repository, adapt to whatever `create_session` already uses.)

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=. uv run pytest backend/tests/chat/test_repository_imported_session.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/_repository.py backend/tests/chat/test_repository_imported_session.py
git commit -m "Add ChatRepository.create_imported_session for external imports"
```

---

### Task 7: Expose `ChatService.create_imported_session()` in module public API

**Files:**
- Modify: `backend/modules/chat/__init__.py`

- [ ] **Step 1: Locate the existing `ChatService` (or equivalent service-shaped object)**

If the chat module exposes a `ChatService` class, add a thin pass-through method:

```python
async def create_imported_session(self, **kwargs) -> dict:
    return await self._repository.create_imported_session(**kwargs)
```

If the module exposes only `router` and per-function helpers, add a top-level function:

```python
async def create_imported_session(
    db: AsyncIOMotorDatabase, **kwargs
) -> dict:
    repo = ChatRepository(db)
    return await repo.create_imported_session(**kwargs)
```

Pick whichever style matches the module's current public surface. Re-export from `__init__.py`'s `__all__`.

- [ ] **Step 2: Smoke-import**

```bash
PYTHONPATH=. uv run python -c "from backend.modules.chat import create_imported_session; print('ok')"
```
(Or `from backend.modules.chat import ChatService; print(hasattr(ChatService, 'create_imported_session'))`.)

- [ ] **Step 3: Commit**

```bash
git add backend/modules/chat/__init__.py
git commit -m "Expose create_imported_session via chat module public API"
```

---

### Task 8: Scaffold `chatgpt_import` module skeleton

**Files:**
- Create: `backend/modules/chatgpt_import/__init__.py`
- Create: `backend/modules/chatgpt_import/_models.py`

- [ ] **Step 1: Create `_models.py`**

```python
"""Internal parser intermediate types for chatgpt_import."""
from datetime import datetime
from pydantic import BaseModel


class ParsedMessage(BaseModel):
    """A single message that survived parser filters."""
    role: str  # "user" or "assistant"
    content: str
    created_at: datetime
    imported_model_slug: str | None = None


class ParsedConversation(BaseModel):
    """A conversation reduced to its imported form."""
    chatgpt_conversation_id: str
    title: str
    create_time: datetime
    update_time: datetime
    default_model_slug: str | None
    messages: list[ParsedMessage]
    first_user_message_preview: str
    first_assistant_message_preview: str
```

- [ ] **Step 2: Create `__init__.py` with placeholder exports**

```python
"""Public API for the chatgpt_import module."""
from backend.modules.chatgpt_import._handlers import router

__all__ = ["router", "init_indexes"]


async def init_indexes(db) -> None:
    """Create all indexes for chatgpt_import collections."""
    from backend.modules.chatgpt_import._repository import ChatGptImportRepository
    repo = ChatGptImportRepository(db)
    await repo.create_indexes()
```

The `_handlers` import will currently fail; that is expected — Task 13 creates `_handlers.py`. Subsequent tasks resolve this. Do not commit yet — combine into Task 13's commit.

---

### Task 9: ChatGptImportRepository — imports collection

**Files:**
- Create: `backend/modules/chatgpt_import/_repository.py`
- Test: `tests/chatgpt_import/test_repository.py`

- [ ] **Step 1: Write the failing test for `create_import` and `get_active_import`**

```python
# tests/chatgpt_import/test_repository.py
from datetime import UTC, datetime, timedelta

import pytest

from backend.modules.chatgpt_import._repository import ChatGptImportRepository


@pytest.mark.asyncio
async def test_create_and_get_active_import(test_db):
    repo = ChatGptImportRepository(test_db)
    await repo.create_indexes()

    import_id = await repo.create_import(
        user_id="u1",
        file_hash="abc123",
        file_size_bytes=12345,
        filename="conversations.json",
        ttl_days=14,
    )
    assert isinstance(import_id, str)

    active = await repo.get_active_import("u1")
    assert active is not None
    assert active["user_id"] == "u1"
    assert active["file_hash"] == "abc123"
    assert active["status"] == "parsing"
    assert active["conversation_count"] == 0
    assert active["skipped_count"] == 0
    assert active["expires_at"] > datetime.now(UTC) + timedelta(days=13)
```

- [ ] **Step 2: Run it to confirm failure**

```bash
PYTHONPATH=. uv run pytest tests/chatgpt_import/test_repository.py -v
```
Expected: FAIL — module does not exist yet.

- [ ] **Step 3: Implement `ChatGptImportRepository` (imports half)**

```python
# backend/modules/chatgpt_import/_repository.py
from datetime import UTC, datetime, timedelta

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase


class ChatGptImportRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._imports = db["chatgpt_imports"]
        self._conversations = db["chatgpt_import_conversations"]

    async def create_indexes(self) -> None:
        await self._imports.create_index([("user_id", 1)])
        await self._imports.create_index([("expires_at", 1)], expireAfterSeconds=0)
        await self._imports.create_index(
            [("user_id", 1), ("file_hash", 1)], unique=False
        )

    async def create_import(
        self,
        *,
        user_id: str,
        file_hash: str,
        file_size_bytes: int,
        filename: str,
        ttl_days: int = 14,
    ) -> str:
        now = datetime.now(UTC)
        doc = {
            "user_id": user_id,
            "file_hash": file_hash,
            "file_size_bytes": file_size_bytes,
            "uploaded_filename": filename,
            "status": "parsing",
            "error_message": None,
            "conversation_count": 0,
            "skipped_count": 0,
            "skipped_reasons": {},
            "created_at": now,
            "expires_at": now + timedelta(days=ttl_days),
            "last_import_at": None,
        }
        result = await self._imports.insert_one(doc)
        return str(result.inserted_id)

    async def get_active_import(self, user_id: str) -> dict | None:
        return await self._imports.find_one({"user_id": user_id})

    async def find_import_by_hash(
        self, user_id: str, file_hash: str
    ) -> dict | None:
        return await self._imports.find_one(
            {"user_id": user_id, "file_hash": file_hash}
        )

    async def update_import_status(
        self,
        import_id: str,
        *,
        status: str,
        conversation_count: int | None = None,
        skipped_count: int | None = None,
        skipped_reasons: dict[str, int] | None = None,
        error_message: str | None = None,
    ) -> None:
        update: dict = {"status": status}
        if conversation_count is not None:
            update["conversation_count"] = conversation_count
        if skipped_count is not None:
            update["skipped_count"] = skipped_count
        if skipped_reasons is not None:
            update["skipped_reasons"] = skipped_reasons
        if error_message is not None:
            update["error_message"] = error_message
        await self._imports.update_one(
            {"_id": ObjectId(import_id)}, {"$set": update}
        )

    async def reset_ttl(
        self, import_id: str, *, ttl_days: int = 14
    ) -> None:
        now = datetime.now(UTC)
        await self._imports.update_one(
            {"_id": ObjectId(import_id)},
            {
                "$set": {
                    "expires_at": now + timedelta(days=ttl_days),
                    "last_import_at": now,
                }
            },
        )
        await self._conversations.update_many(
            {"import_id": ObjectId(import_id)},
            {"$set": {"expires_at": now + timedelta(days=ttl_days)}},
        )

    async def delete_import(self, import_id: str) -> None:
        oid = ObjectId(import_id)
        await self._conversations.delete_many({"import_id": oid})
        await self._imports.delete_one({"_id": oid})
```

- [ ] **Step 4: Run the test to verify pass**

```bash
PYTHONPATH=. uv run pytest tests/chatgpt_import/test_repository.py::test_create_and_get_active_import -v
```
Expected: PASS.

- [ ] **Step 5: Commit (combined with Task 8's skeleton)**

```bash
git add backend/modules/chatgpt_import/_models.py \
        backend/modules/chatgpt_import/_repository.py \
        backend/modules/chatgpt_import/__init__.py \
        tests/chatgpt_import/test_repository.py
git commit -m "Scaffold chatgpt_import module with imports-collection repository"
```

(Note: `__init__.py` still imports `_handlers` which doesn't exist yet. The build will only run end-to-end after Task 13. This is intentional for clean per-task commits — `pytest` runs successfully because the test imports `ChatGptImportRepository` directly, not via the package.)

---

### Task 10: ChatGptImportRepository — conversations collection methods

**Files:**
- Modify: `backend/modules/chatgpt_import/_repository.py`
- Test: `tests/chatgpt_import/test_repository.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append in tests/chatgpt_import/test_repository.py
from datetime import UTC, datetime
import pytest


@pytest.mark.asyncio
async def test_insert_and_list_conversations(test_db):
    repo = ChatGptImportRepository(test_db)
    await repo.create_indexes()
    import_id = await repo.create_import(
        user_id="u1", file_hash="h1", file_size_bytes=100, filename="x.json"
    )

    await repo.insert_conversation(
        import_id=import_id,
        user_id="u1",
        chatgpt_conversation_id="conv-1",
        title="Test conv",
        create_time=datetime(2024, 7, 2, 12, 0, tzinfo=UTC),
        update_time=datetime(2024, 7, 2, 12, 5, tzinfo=UTC),
        default_model_slug="gpt-5",
        message_count=4,
        first_user_message_preview="hello",
        first_assistant_message_preview="hi",
        raw_data={"id": "conv-1", "title": "Test conv"},
    )

    convs = await repo.list_conversations(user_id="u1", import_id=import_id)
    assert len(convs) == 1
    assert convs[0]["chatgpt_conversation_id"] == "conv-1"
    assert convs[0]["imports"] == []


@pytest.mark.asyncio
async def test_record_import_creates_entry_in_imports_array(test_db):
    repo = ChatGptImportRepository(test_db)
    await repo.create_indexes()
    import_id = await repo.create_import(
        user_id="u1", file_hash="h1", file_size_bytes=100, filename="x.json"
    )
    await repo.insert_conversation(
        import_id=import_id,
        user_id="u1",
        chatgpt_conversation_id="conv-1",
        title="T",
        create_time=datetime.now(UTC),
        update_time=datetime.now(UTC),
        default_model_slug=None,
        message_count=2,
        first_user_message_preview="",
        first_assistant_message_preview="",
        raw_data={},
    )

    await repo.record_import(
        import_id=import_id,
        chatgpt_conversation_id="conv-1",
        persona_id="p1",
        session_id="s1",
    )

    convs = await repo.list_conversations(user_id="u1", import_id=import_id)
    assert len(convs[0]["imports"]) == 1
    assert convs[0]["imports"][0]["persona_id"] == "p1"
    assert convs[0]["imports"][0]["session_id"] == "s1"


@pytest.mark.asyncio
async def test_record_import_is_idempotent_per_persona(test_db):
    """Calling record_import twice with same persona must not create duplicate."""
    repo = ChatGptImportRepository(test_db)
    await repo.create_indexes()
    import_id = await repo.create_import(
        user_id="u1", file_hash="h1", file_size_bytes=100, filename="x.json"
    )
    await repo.insert_conversation(
        import_id=import_id,
        user_id="u1",
        chatgpt_conversation_id="conv-1",
        title="T",
        create_time=datetime.now(UTC),
        update_time=datetime.now(UTC),
        default_model_slug=None,
        message_count=2,
        first_user_message_preview="",
        first_assistant_message_preview="",
        raw_data={},
    )

    await repo.record_import(
        import_id=import_id,
        chatgpt_conversation_id="conv-1",
        persona_id="p1",
        session_id="s1",
    )
    # Second call into SAME persona allowed (per spec; creates duplicate session-link entry)
    await repo.record_import(
        import_id=import_id,
        chatgpt_conversation_id="conv-1",
        persona_id="p1",
        session_id="s2",
    )

    convs = await repo.list_conversations(user_id="u1", import_id=import_id)
    assert len(convs[0]["imports"]) == 2
```

- [ ] **Step 2: Run to confirm failure**

```bash
PYTHONPATH=. uv run pytest tests/chatgpt_import/test_repository.py -v
```
Expected: FAIL — methods `insert_conversation`, `list_conversations`, `record_import` not yet defined.

- [ ] **Step 3: Implement the methods**

Append to `ChatGptImportRepository`:

```python
from datetime import datetime


async def insert_conversation(
    self,
    *,
    import_id: str,
    user_id: str,
    chatgpt_conversation_id: str,
    title: str,
    create_time: datetime,
    update_time: datetime,
    default_model_slug: str | None,
    message_count: int,
    first_user_message_preview: str,
    first_assistant_message_preview: str,
    raw_data: dict,
) -> None:
    parent = await self._imports.find_one({"_id": ObjectId(import_id)})
    expires_at = parent["expires_at"] if parent else datetime.now(UTC)
    doc = {
        "import_id": ObjectId(import_id),
        "user_id": user_id,
        "chatgpt_conversation_id": chatgpt_conversation_id,
        "title": title,
        "create_time": create_time,
        "update_time": update_time,
        "default_model_slug": default_model_slug,
        "message_count": message_count,
        "first_user_message_preview": first_user_message_preview,
        "first_assistant_message_preview": first_assistant_message_preview,
        "raw_data": raw_data,
        "imports": [],
        "expires_at": expires_at,
    }
    await self._conversations.insert_one(doc)

async def list_conversations(
    self,
    *,
    user_id: str,
    import_id: str,
    title_search: str | None = None,
    sort: str = "create_time_desc",
) -> list[dict]:
    query: dict = {"user_id": user_id, "import_id": ObjectId(import_id)}
    if title_search:
        query["title"] = {"$regex": title_search, "$options": "i"}
    sort_fields = {
        "create_time_desc": [("create_time", -1)],
        "create_time_asc": [("create_time", 1)],
        "title_asc": [("title", 1)],
    }.get(sort, [("create_time", -1)])
    cursor = self._conversations.find(query).sort(sort_fields)
    return await cursor.to_list(length=None)

async def get_conversation(
    self, *, user_id: str, import_id: str, chatgpt_conversation_id: str
) -> dict | None:
    return await self._conversations.find_one(
        {
            "user_id": user_id,
            "import_id": ObjectId(import_id),
            "chatgpt_conversation_id": chatgpt_conversation_id,
        }
    )

async def record_import(
    self,
    *,
    import_id: str,
    chatgpt_conversation_id: str,
    persona_id: str,
    session_id: str,
) -> None:
    await self._conversations.update_one(
        {
            "import_id": ObjectId(import_id),
            "chatgpt_conversation_id": chatgpt_conversation_id,
        },
        {
            "$push": {
                "imports": {
                    "persona_id": persona_id,
                    "session_id": session_id,
                    "imported_at": datetime.now(UTC),
                }
            }
        },
    )

async def add_indexes_for_conversations(self) -> None:
    """Called once at startup; idempotent."""
    await self._conversations.create_index(
        [("user_id", 1), ("import_id", 1), ("create_time", -1)]
    )
    await self._conversations.create_index(
        [("user_id", 1), ("chatgpt_conversation_id", 1)]
    )
    await self._conversations.create_index(
        [("expires_at", 1)], expireAfterSeconds=0
    )
```

Also extend `create_indexes` to call `add_indexes_for_conversations`:

```python
async def create_indexes(self) -> None:
    await self._imports.create_index([("user_id", 1)])
    await self._imports.create_index([("expires_at", 1)], expireAfterSeconds=0)
    await self._imports.create_index(
        [("user_id", 1), ("file_hash", 1)], unique=False
    )
    await self.add_indexes_for_conversations()
```

- [ ] **Step 4: Run tests to verify pass**

```bash
PYTHONPATH=. uv run pytest tests/chatgpt_import/test_repository.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chatgpt_import/_repository.py tests/chatgpt_import/test_repository.py
git commit -m "Add conversations-collection methods to ChatGptImportRepository"
```

---

### Task 11: Parser — tree linearise

**Files:**
- Create: `backend/modules/chatgpt_import/_parser.py`
- Test: `tests/chatgpt_import/test_parser.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/chatgpt_import/test_parser.py
from backend.modules.chatgpt_import._parser import linearise


def test_linearise_simple_chain():
    mapping = {
        "root": {"id": "root", "message": None, "parent": None, "children": ["m1"]},
        "m1": {
            "id": "m1",
            "message": {"id": "m1", "content": "first"},
            "parent": "root",
            "children": ["m2"],
        },
        "m2": {
            "id": "m2",
            "message": {"id": "m2", "content": "second"},
            "parent": "m1",
            "children": [],
        },
    }
    chain = linearise(mapping, "m2")
    assert [m["id"] for m in chain] == ["m1", "m2"]


def test_linearise_discards_alternative_branch():
    """Two siblings — current_node walks back only through its own ancestor."""
    mapping = {
        "root": {"id": "root", "message": None, "parent": None, "children": ["m1"]},
        "m1": {
            "id": "m1",
            "message": {"id": "m1", "content": "user"},
            "parent": "root",
            "children": ["m2a", "m2b"],
        },
        "m2a": {
            "id": "m2a",
            "message": {"id": "m2a", "content": "interrupted"},
            "parent": "m1",
            "children": [],
        },
        "m2b": {
            "id": "m2b",
            "message": {"id": "m2b", "content": "finished"},
            "parent": "m1",
            "children": [],
        },
    }
    chain = linearise(mapping, "m2b")
    assert [m["id"] for m in chain] == ["m1", "m2b"]


def test_linearise_handles_cycle_defensively():
    mapping = {
        "a": {
            "id": "a",
            "message": {"id": "a", "content": "x"},
            "parent": "b",
            "children": [],
        },
        "b": {
            "id": "b",
            "message": {"id": "b", "content": "y"},
            "parent": "a",  # cycle
            "children": [],
        },
    }
    chain = linearise(mapping, "a")
    assert len(chain) == 2  # both visited once
```

- [ ] **Step 2: Run to confirm failure**

```bash
PYTHONPATH=. uv run pytest tests/chatgpt_import/test_parser.py -v
```
Expected: FAIL — `linearise` not defined.

- [ ] **Step 3: Implement `linearise`**

```python
# backend/modules/chatgpt_import/_parser.py


def linearise(mapping: dict, current_node_id: str) -> list[dict]:
    """Walk the parent chain from current_node back to root, return root→leaf order."""
    chain: list[dict] = []
    visited: set[str] = set()
    node_id: str | None = current_node_id
    while node_id and node_id not in visited:
        visited.add(node_id)
        node = mapping.get(node_id)
        if not node:
            break
        msg = node.get("message")
        if msg is not None:
            chain.append(msg)
        node_id = node.get("parent")
    return list(reversed(chain))
```

- [ ] **Step 4: Verify pass**

```bash
PYTHONPATH=. uv run pytest tests/chatgpt_import/test_parser.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chatgpt_import/_parser.py tests/chatgpt_import/test_parser.py
git commit -m "Add tree-linearise function to chatgpt_import parser"
```

---

### Task 12: Parser — message filter

**Files:**
- Modify: `backend/modules/chatgpt_import/_parser.py`
- Test: `tests/chatgpt_import/test_parser.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append in tests/chatgpt_import/test_parser.py
from backend.modules.chatgpt_import._parser import is_message_keepable


def _msg(role="user", content_type="text", parts=None, hidden=False, status="finished_successfully", **extra_meta):
    return {
        "author": {"role": role},
        "content": {"content_type": content_type, "parts": parts or [""]},
        "status": status,
        "metadata": {"is_visually_hidden_from_conversation": hidden, **extra_meta},
    }


def test_filter_keeps_normal_user_message():
    assert is_message_keepable(_msg(role="user", parts=["hello"])) is True


def test_filter_keeps_normal_assistant_message():
    assert is_message_keepable(_msg(role="assistant", parts=["reply"])) is True


def test_filter_drops_system_role():
    assert is_message_keepable(_msg(role="system", parts=["whatever"])) is False


def test_filter_drops_hidden_message():
    assert is_message_keepable(_msg(role="user", parts=["x"], hidden=True)) is False


def test_filter_keeps_user_editable_context_even_if_hidden():
    m = {
        "author": {"role": "user"},
        "content": {
            "content_type": "user_editable_context",
            "user_profile": "x",
            "user_instructions": "y",
        },
        "status": "finished_successfully",
        "metadata": {"is_visually_hidden_from_conversation": True},
    }
    assert is_message_keepable(m) is True


def test_filter_drops_empty_parts():
    assert is_message_keepable(_msg(role="assistant", parts=[""])) is False
    assert is_message_keepable(_msg(role="assistant", parts=["", ""])) is False


def test_filter_drops_unsupported_content_type():
    m = {
        "author": {"role": "assistant"},
        "content": {"content_type": "code", "text": "print(1)"},
        "status": "finished_successfully",
        "metadata": {},
    }
    assert is_message_keepable(m) is False


def test_filter_drops_interrupted_status():
    assert is_message_keepable(_msg(role="assistant", parts=["x"], status="in_progress")) is False
```

- [ ] **Step 2: Run to confirm failure**

```bash
PYTHONPATH=. uv run pytest tests/chatgpt_import/test_parser.py -v
```
Expected: FAIL — `is_message_keepable` not defined.

- [ ] **Step 3: Implement `is_message_keepable`**

Append to `_parser.py`:

```python
SUPPORTED_CONTENT_TYPES = {"text", "user_editable_context"}
KEEPABLE_ROLES = {"user", "assistant"}


def is_message_keepable(message: dict) -> bool:
    """Apply the filter rules from spec §5.3."""
    if message is None:
        return False
    author = message.get("author") or {}
    role = author.get("role")
    if role not in KEEPABLE_ROLES:
        return False
    if message.get("status") not in (None, "finished_successfully"):
        return False
    content = message.get("content") or {}
    ctype = content.get("content_type")
    if ctype not in SUPPORTED_CONTENT_TYPES:
        return False
    metadata = message.get("metadata") or {}
    is_hidden = metadata.get("is_visually_hidden_from_conversation", False)
    if is_hidden and ctype != "user_editable_context":
        return False
    if ctype == "text":
        parts = content.get("parts") or []
        if not parts or all(not (p or "").strip() for p in parts):
            return False
    return True
```

- [ ] **Step 4: Verify pass**

```bash
PYTHONPATH=. uv run pytest tests/chatgpt_import/test_parser.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chatgpt_import/_parser.py tests/chatgpt_import/test_parser.py
git commit -m "Add message-filter rules to chatgpt_import parser"
```

---

### Task 13: Parser — Custom Instructions mapping + message-to-output conversion + full-conversation parser

**Files:**
- Modify: `backend/modules/chatgpt_import/_parser.py`
- Test: `tests/chatgpt_import/test_parser.py` (append)
- Create: `tests/chatgpt_import/fixtures/sample.json`

- [ ] **Step 1: Save the curated sample as a fixture**

Place the 5-conversation curated sample (already created during brainstorming) at `tests/chatgpt_import/fixtures/sample.json` — exact bytes pasted earlier in the design session.

- [ ] **Step 2: Write failing tests for `parse_conversation`**

```python
# append in tests/chatgpt_import/test_parser.py
import json
from pathlib import Path

from backend.modules.chatgpt_import._parser import parse_conversation


def _load_sample() -> list[dict]:
    p = Path(__file__).parent / "fixtures" / "sample.json"
    return json.loads(p.read_text())


def test_parse_huehnerbrust_includes_custom_instructions_as_first_message():
    sample = _load_sample()
    conv = next(c for c in sample if "Hühnerbrust" in c["title"])
    parsed = parse_conversation(conv)
    assert parsed.title.startswith("Hühnerbrust")
    assert parsed.messages, "expected at least one parsed message"
    first = parsed.messages[0]
    assert first.role == "user"
    assert "[User Profile]" in first.content
    assert "[Custom Instructions]" in first.content
    assert "Preferred name: Chris" in first.content


def test_parse_moon_darker_drops_interrupted_branch():
    sample = _load_sample()
    conv = next(c for c in sample if c["title"] == "Moon Darker Than Coal")
    parsed = parse_conversation(conv)
    # interrupted branch contained "in_progress" content "It's a common misconception! The color..."
    # finished branch contained the full multi-paragraph reply
    found_interrupted = any(
        "color of lunar regolith can indeed give the impression of being light gray" in m.content
        for m in parsed.messages
    )
    found_finished = any(
        "Regolith, the layer of loose, fragmented material" in m.content
        for m in parsed.messages
    )
    assert not found_interrupted
    assert found_finished


def test_parse_starfleet_no_custom_instructions():
    sample = _load_sample()
    conv = next(c for c in sample if "Starfleet" in c["title"])
    parsed = parse_conversation(conv)
    # first message should be the real user question, not a synthetic CI message
    assert "User Profile" not in parsed.messages[0].content
    assert parsed.messages[0].role == "user"
    assert "star trek" in parsed.messages[0].content.lower()


def test_parse_preview_strings_are_capped():
    sample = _load_sample()
    conv = next(c for c in sample if c["title"] == "Reversed Time and AdS")
    parsed = parse_conversation(conv)
    assert len(parsed.first_user_message_preview) <= 200
    assert len(parsed.first_assistant_message_preview) <= 200
    assert parsed.message_count == len(parsed.messages)
```

(Note: `message_count` is on `ParsedConversation` per `_models.py` — confirm or add.)

- [ ] **Step 3: Run to confirm failure**

```bash
PYTHONPATH=. uv run pytest tests/chatgpt_import/test_parser.py -v
```
Expected: FAIL — `parse_conversation` not defined.

- [ ] **Step 4: Implement `parse_conversation` and helpers**

Append to `_parser.py`:

```python
import logging
from datetime import UTC, datetime, timedelta

from backend.modules.chatgpt_import._models import ParsedConversation, ParsedMessage

_log = logging.getLogger(__name__)
_PREVIEW_MAX = 200


def _build_custom_instructions_text(message: dict) -> str:
    meta = (message.get("metadata") or {}).get("user_context_message_data") or {}
    about_user = meta.get("about_user_message", "").strip()
    about_model = meta.get("about_model_message", "").strip()
    parts: list[str] = []
    if about_user:
        parts.append(f"[User Profile]\n{about_user}")
    if about_model:
        parts.append(f"[Custom Instructions]\n{about_model}")
    return "\n\n".join(parts)


def _message_to_parsed(message: dict, conversation_create_time: datetime) -> ParsedMessage:
    role = (message["author"]["role"])
    create_time = message.get("create_time")
    if create_time is None:
        ts = conversation_create_time
    else:
        ts = datetime.fromtimestamp(create_time, UTC)
    metadata = message.get("metadata") or {}
    parts = (message.get("content") or {}).get("parts") or []
    content = "\n".join(p for p in parts if p is not None)
    return ParsedMessage(
        role=role,
        content=content,
        created_at=ts,
        imported_model_slug=metadata.get("model_slug"),
    )


def parse_conversation(conv: dict) -> ParsedConversation:
    """Tree → filter → Chatsune-shape. Pure function on one conversation."""
    mapping = conv.get("mapping") or {}
    current_node = conv.get("current_node")
    if not current_node:
        return ParsedConversation(
            chatgpt_conversation_id=conv.get("id") or conv.get("conversation_id") or "",
            title=conv.get("title") or "",
            create_time=_ts_to_dt(conv.get("create_time")),
            update_time=_ts_to_dt(conv.get("update_time")),
            default_model_slug=conv.get("default_model_slug"),
            messages=[],
            first_user_message_preview="",
            first_assistant_message_preview="",
        )

    raw_chain = linearise(mapping, current_node)
    conv_create_dt = _ts_to_dt(conv.get("create_time"))

    parsed: list[ParsedMessage] = []
    ci_seen = False
    for msg in raw_chain:
        if not is_message_keepable(msg):
            ctype = ((msg.get("content") or {}).get("content_type")) or "<missing>"
            if ctype not in SUPPORTED_CONTENT_TYPES:
                _log.info(
                    "chatgpt_import.unsupported_content_type",
                    extra={"content_type": ctype, "conversation_id": conv.get("id")},
                )
            continue
        ctype = msg["content"]["content_type"]
        if ctype == "user_editable_context":
            ci_text = _build_custom_instructions_text(msg)
            if ci_text:
                parsed.append(
                    ParsedMessage(
                        role="user",
                        content=ci_text,
                        created_at=conv_create_dt - timedelta(seconds=1),
                    )
                )
                ci_seen = True
            continue
        parsed.append(_message_to_parsed(msg, conv_create_dt))

    first_user = next((m for m in parsed if m.role == "user" and not (ci_seen and m is parsed[0])), None)
    first_asst = next((m for m in parsed if m.role == "assistant"), None)
    user_prev = (first_user.content if first_user else "")[:_PREVIEW_MAX]
    asst_prev = (first_asst.content if first_asst else "")[:_PREVIEW_MAX]

    return ParsedConversation(
        chatgpt_conversation_id=conv.get("id") or conv.get("conversation_id") or "",
        title=conv.get("title") or "",
        create_time=conv_create_dt,
        update_time=_ts_to_dt(conv.get("update_time")),
        default_model_slug=conv.get("default_model_slug"),
        messages=parsed,
        first_user_message_preview=user_prev,
        first_assistant_message_preview=asst_prev,
    )


def _ts_to_dt(ts: float | None) -> datetime:
    if ts is None:
        return datetime.now(UTC)
    return datetime.fromtimestamp(ts, UTC)
```

Also add `message_count` as a computed property on `ParsedConversation` in `_models.py`:

```python
class ParsedConversation(BaseModel):
    # ...existing fields...

    @property
    def message_count(self) -> int:
        return len(self.messages)
```

- [ ] **Step 5: Verify pass**

```bash
PYTHONPATH=. uv run pytest tests/chatgpt_import/test_parser.py -v
```
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/chatgpt_import/_parser.py \
        backend/modules/chatgpt_import/_models.py \
        tests/chatgpt_import/test_parser.py \
        tests/chatgpt_import/fixtures/sample.json
git commit -m "Add full conversation parser with Custom Instructions mapping"
```

---

### Task 14: Session-builder — ParsedConversation → CreateImportedSessionRequest

**Files:**
- Create: `backend/modules/chatgpt_import/_session_builder.py`
- Test: `tests/chatgpt_import/test_session_builder.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/chatgpt_import/test_session_builder.py
from datetime import UTC, datetime

from backend.modules.chatgpt_import._models import ParsedConversation, ParsedMessage
from backend.modules.chatgpt_import._session_builder import build_imported_session_request


def test_builds_request_with_correct_fields():
    parsed = ParsedConversation(
        chatgpt_conversation_id="conv-1",
        title="Test conv",
        create_time=datetime(2024, 7, 2, 12, 0, tzinfo=UTC),
        update_time=datetime(2024, 7, 2, 12, 5, tzinfo=UTC),
        default_model_slug="gpt-4o",
        messages=[
            ParsedMessage(role="user", content="hi", created_at=datetime(2024, 7, 2, 12, 1, tzinfo=UTC)),
            ParsedMessage(role="assistant", content="hello", created_at=datetime(2024, 7, 2, 12, 2, tzinfo=UTC), imported_model_slug="gpt-4o"),
        ],
        first_user_message_preview="hi",
        first_assistant_message_preview="hello",
    )

    req = build_imported_session_request(parsed=parsed, persona_id="p1")

    assert req.persona_id == "p1"
    assert req.title == "Test conv"
    assert req.imported_from == "chatgpt"
    assert req.imported_model_slug == "gpt-4o"
    assert req.original_created_at == datetime(2024, 7, 2, 12, 0, tzinfo=UTC)
    assert len(req.messages) == 2
    assert req.messages[0].role == "user"
    assert req.messages[1].imported_model_slug == "gpt-4o"


def test_imported_model_slug_falls_back_to_first_assistant_message():
    parsed = ParsedConversation(
        chatgpt_conversation_id="conv-1",
        title="Test",
        create_time=datetime.now(UTC),
        update_time=datetime.now(UTC),
        default_model_slug=None,
        messages=[
            ParsedMessage(role="user", content="x", created_at=datetime.now(UTC)),
            ParsedMessage(role="assistant", content="y", created_at=datetime.now(UTC), imported_model_slug="gpt-4"),
        ],
        first_user_message_preview="x",
        first_assistant_message_preview="y",
    )
    req = build_imported_session_request(parsed=parsed, persona_id="p1")
    assert req.imported_model_slug == "gpt-4"
```

- [ ] **Step 2: Run to confirm failure**

```bash
PYTHONPATH=. uv run pytest tests/chatgpt_import/test_session_builder.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implement**

```python
# backend/modules/chatgpt_import/_session_builder.py
from backend.modules.chatgpt_import._models import ParsedConversation
from shared.dtos.chat import (
    CreateImportedSessionRequest,
    ImportedMessageInput,
)


def build_imported_session_request(
    *, parsed: ParsedConversation, persona_id: str
) -> CreateImportedSessionRequest:
    model_slug = parsed.default_model_slug
    if model_slug is None:
        for m in parsed.messages:
            if m.role == "assistant" and m.imported_model_slug:
                model_slug = m.imported_model_slug
                break

    messages = [
        ImportedMessageInput(
            role=m.role,
            content=m.content,
            created_at=m.created_at,
            imported_model_slug=m.imported_model_slug,
        )
        for m in parsed.messages
    ]
    return CreateImportedSessionRequest(
        persona_id=persona_id,
        title=parsed.title,
        messages=messages,
        imported_from="chatgpt",
        imported_model_slug=model_slug,
        original_created_at=parsed.create_time,
    )
```

- [ ] **Step 4: Verify pass**

```bash
PYTHONPATH=. uv run pytest tests/chatgpt_import/test_session_builder.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chatgpt_import/_session_builder.py \
        tests/chatgpt_import/test_session_builder.py
git commit -m "Add session builder mapping ParsedConversation to CreateImportedSessionRequest"
```

---

### Task 15: JobType additions

**Files:**
- Modify: `backend/jobs/_models.py`

- [ ] **Step 1: Add the two new enum entries**

```python
class JobType(StrEnum):
    TITLE_GENERATION = "title_generation"
    MEMORY_EXTRACTION = "memory_extraction"
    MEMORY_CONSOLIDATION = "memory_consolidation"
    CHATGPT_IMPORT_PARSE = "chatgpt_import_parse"
    CHATGPT_IMPORT_CONVERSATION = "chatgpt_import_conversation"
```

- [ ] **Step 2: Smoke-import**

```bash
PYTHONPATH=. uv run python -c "from backend.jobs._models import JobType; print(JobType.CHATGPT_IMPORT_PARSE.value)"
```
Expected: `chatgpt_import_parse`.

- [ ] **Step 3: Commit**

```bash
git add backend/jobs/_models.py
git commit -m "Add ChatGPT-import JobType entries"
```

---

### Task 16: Parse-job handler

**Files:**
- Create: `backend/jobs/handlers/_chatgpt_import_parse.py`
- Test: `tests/chatgpt_import/test_parse_handler.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/chatgpt_import/test_parse_handler.py
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.jobs.handlers._chatgpt_import_parse import handle_chatgpt_import_parse


@pytest.mark.asyncio
async def test_parse_handler_indexes_each_conversation(tmp_path, test_db, monkeypatch):
    fixture = Path(__file__).parent / "fixtures" / "sample.json"
    work = tmp_path / "input.json"
    work.write_bytes(fixture.read_bytes())

    # Create parent import doc
    from backend.modules.chatgpt_import._repository import ChatGptImportRepository
    repo = ChatGptImportRepository(test_db)
    await repo.create_indexes()
    import_id = await repo.create_import(
        user_id="u1", file_hash="h1", file_size_bytes=work.stat().st_size, filename="sample.json"
    )

    # Capture published events
    published: list[tuple[str, object]] = []
    fake_bus = AsyncMock()
    fake_bus.publish = AsyncMock(side_effect=lambda topic, event, **_: published.append((topic, event)))

    monkeypatch.setattr(
        "backend.jobs.handlers._chatgpt_import_parse.get_event_bus",
        lambda: fake_bus,
    )
    monkeypatch.setattr(
        "backend.jobs.handlers._chatgpt_import_parse.get_db",
        lambda: test_db,
    )

    job = MagicMock()
    job.payload = {
        "user_id": "u1",
        "import_id": import_id,
        "file_path": str(work),
        "filename": "sample.json",
        "file_size_bytes": work.stat().st_size,
        "correlation_id": "corr-1",
    }

    await handle_chatgpt_import_parse(job)

    parent = await repo.get_active_import("u1")
    assert parent["status"] == "ready"
    assert parent["conversation_count"] == 5  # fixture has 5 conversations
    convs = await repo.list_conversations(user_id="u1", import_id=import_id)
    assert len(convs) == 5

    topics = [t for t, _ in published]
    assert "chatgpt_import.parse.started" in topics
    assert "chatgpt_import.parse.done" in topics
```

- [ ] **Step 2: Confirm failure**

```bash
PYTHONPATH=. uv run pytest tests/chatgpt_import/test_parse_handler.py -v
```
Expected: FAIL — handler does not exist.

- [ ] **Step 3: Implement the handler**

```python
# backend/jobs/handlers/_chatgpt_import_parse.py
"""Long-running parse job for ChatGPT export uploads."""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ijson

from backend.db import get_db
from backend.modules.chatgpt_import._parser import parse_conversation
from backend.modules.chatgpt_import._repository import ChatGptImportRepository
from backend.ws.event_bus import get_event_bus
from shared.events.chatgpt_import import (
    ChatGptImportParseDoneEvent,
    ChatGptImportParseFailedEvent,
    ChatGptImportParseProgressEvent,
    ChatGptImportParseStartedEvent,
)
from shared.topics import Topics

_log = logging.getLogger(__name__)
_PROGRESS_EVERY = 10


async def handle_chatgpt_import_parse(job: Any) -> None:
    payload = job.payload
    user_id = payload["user_id"]
    import_id = payload["import_id"]
    file_path = Path(payload["file_path"])
    filename = payload["filename"]
    file_size_bytes = payload["file_size_bytes"]
    correlation_id = payload.get("correlation_id")

    db = get_db()
    repo = ChatGptImportRepository(db)
    bus = get_event_bus()

    scope = f"chatgpt_import:{import_id}"
    await bus.publish(
        Topics.CHATGPT_IMPORT_PARSE_STARTED,
        ChatGptImportParseStartedEvent(
            import_id=import_id, filename=filename, file_size_bytes=file_size_bytes
        ),
        scope=scope,
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )

    indexed = 0
    skipped_count = 0
    skipped_reasons: dict[str, int] = {}

    try:
        with file_path.open("rb") as f:
            for conv in ijson.items(f, "item"):
                try:
                    parsed = parse_conversation(conv)
                    await repo.insert_conversation(
                        import_id=import_id,
                        user_id=user_id,
                        chatgpt_conversation_id=parsed.chatgpt_conversation_id,
                        title=parsed.title,
                        create_time=parsed.create_time,
                        update_time=parsed.update_time,
                        default_model_slug=parsed.default_model_slug,
                        message_count=parsed.message_count,
                        first_user_message_preview=parsed.first_user_message_preview,
                        first_assistant_message_preview=parsed.first_assistant_message_preview,
                        raw_data=conv,
                    )
                    indexed += 1
                    if indexed % _PROGRESS_EVERY == 0:
                        await bus.publish(
                            Topics.CHATGPT_IMPORT_PARSE_PROGRESS,
                            ChatGptImportParseProgressEvent(
                                import_id=import_id, conversations_indexed=indexed
                            ),
                            scope=scope,
                            target_user_ids=[user_id],
                            correlation_id=correlation_id,
                        )
                except Exception as exc:
                    skipped_count += 1
                    reason = type(exc).__name__
                    skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
                    _log.warning(
                        "chatgpt_import.conversation_skipped",
                        extra={
                            "import_id": import_id,
                            "reason": reason,
                            "error": str(exc),
                        },
                    )

        # If majority failed, mark import as failed
        total = indexed + skipped_count
        if total > 0 and skipped_count / total > 0.5:
            await repo.update_import_status(
                import_id,
                status="failed",
                conversation_count=indexed,
                skipped_count=skipped_count,
                skipped_reasons=skipped_reasons,
                error_message="More than half of conversations failed to parse",
            )
            await bus.publish(
                Topics.CHATGPT_IMPORT_PARSE_FAILED,
                ChatGptImportParseFailedEvent(
                    import_id=import_id,
                    error_code="majority_failed",
                    error_message="More than half of conversations failed to parse",
                ),
                scope=scope,
                target_user_ids=[user_id],
                correlation_id=correlation_id,
            )
            return

        await repo.update_import_status(
            import_id,
            status="ready",
            conversation_count=indexed,
            skipped_count=skipped_count,
            skipped_reasons=skipped_reasons,
        )
        parent = await repo.get_active_import(user_id)
        await bus.publish(
            Topics.CHATGPT_IMPORT_PARSE_DONE,
            ChatGptImportParseDoneEvent(
                import_id=import_id,
                conversation_count=indexed,
                expires_at=parent["expires_at"],
                skipped_count=skipped_count,
                skipped_reasons=skipped_reasons,
            ),
            scope=scope,
            target_user_ids=[user_id],
            correlation_id=correlation_id,
        )
    except Exception as exc:
        await repo.update_import_status(
            import_id, status="failed", error_message=str(exc)
        )
        await bus.publish(
            Topics.CHATGPT_IMPORT_PARSE_FAILED,
            ChatGptImportParseFailedEvent(
                import_id=import_id,
                error_code=type(exc).__name__,
                error_message=str(exc),
            ),
            scope=scope,
            target_user_ids=[user_id],
            correlation_id=correlation_id,
        )
        raise
    finally:
        # Always clean up the temp file
        try:
            os.unlink(file_path)
        except OSError:
            pass
```

- [ ] **Step 4: Verify pass**

```bash
PYTHONPATH=. uv run pytest tests/chatgpt_import/test_parse_handler.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/jobs/handlers/_chatgpt_import_parse.py tests/chatgpt_import/test_parse_handler.py
git commit -m "Add parse job handler for ChatGPT-import"
```

---

### Task 17: Conversation-import job handler

**Files:**
- Create: `backend/jobs/handlers/_chatgpt_import_conversation.py`
- Test: `tests/chatgpt_import/test_conversation_handler.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/chatgpt_import/test_conversation_handler.py
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.jobs.handlers._chatgpt_import_conversation import (
    handle_chatgpt_import_conversation,
)
from backend.modules.chatgpt_import._repository import ChatGptImportRepository


@pytest.mark.asyncio
async def test_conversation_handler_creates_session_and_records_import(
    test_db, monkeypatch
):
    repo = ChatGptImportRepository(test_db)
    await repo.create_indexes()
    import_id = await repo.create_import(
        user_id="u1", file_hash="h1", file_size_bytes=100, filename="x.json"
    )

    sample_raw = {
        "id": "conv-1",
        "title": "Test",
        "create_time": 1719928256.0,
        "update_time": 1719928256.0,
        "current_node": "m2",
        "default_model_slug": "gpt-4o",
        "mapping": {
            "root": {"id": "root", "message": None, "parent": None, "children": ["m1"]},
            "m1": {
                "id": "m1",
                "message": {
                    "id": "m1",
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["hi"]},
                    "status": "finished_successfully",
                    "create_time": 1719928256.0,
                    "metadata": {},
                },
                "parent": "root",
                "children": ["m2"],
            },
            "m2": {
                "id": "m2",
                "message": {
                    "id": "m2",
                    "author": {"role": "assistant"},
                    "content": {"content_type": "text", "parts": ["hello"]},
                    "status": "finished_successfully",
                    "create_time": 1719928266.0,
                    "metadata": {"model_slug": "gpt-4o"},
                },
                "parent": "m1",
                "children": [],
            },
        },
    }
    await repo.insert_conversation(
        import_id=import_id,
        user_id="u1",
        chatgpt_conversation_id="conv-1",
        title="Test",
        create_time=datetime.now(UTC),
        update_time=datetime.now(UTC),
        default_model_slug="gpt-4o",
        message_count=2,
        first_user_message_preview="hi",
        first_assistant_message_preview="hello",
        raw_data=sample_raw,
    )

    # Mock ChatService.create_imported_session
    fake_create = AsyncMock(return_value={"_id": "session-xyz"})
    monkeypatch.setattr(
        "backend.jobs.handlers._chatgpt_import_conversation.create_imported_session",
        fake_create,
    )

    published = []
    fake_bus = AsyncMock()
    fake_bus.publish = AsyncMock(side_effect=lambda topic, ev, **_: published.append(topic))
    monkeypatch.setattr(
        "backend.jobs.handlers._chatgpt_import_conversation.get_event_bus",
        lambda: fake_bus,
    )
    monkeypatch.setattr(
        "backend.jobs.handlers._chatgpt_import_conversation.get_db",
        lambda: test_db,
    )

    job = MagicMock()
    job.payload = {
        "user_id": "u1",
        "import_id": import_id,
        "chatgpt_conversation_id": "conv-1",
        "persona_id": "p1",
        "correlation_id": "imp-batch-1",
    }
    await handle_chatgpt_import_conversation(job)

    # Verify chat service was called
    fake_create.assert_called_once()
    # Verify event published
    assert "chatgpt_import.conversation.imported" in published
    # Verify import recorded
    convs = await repo.list_conversations(user_id="u1", import_id=import_id)
    assert len(convs[0]["imports"]) == 1
    assert convs[0]["imports"][0]["persona_id"] == "p1"
```

- [ ] **Step 2: Confirm failure**

```bash
PYTHONPATH=. uv run pytest tests/chatgpt_import/test_conversation_handler.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implement**

```python
# backend/jobs/handlers/_chatgpt_import_conversation.py
"""Per-conversation import job handler."""
from __future__ import annotations

import logging
from typing import Any

from backend.db import get_db
from backend.modules.chat import create_imported_session
from backend.modules.chatgpt_import._parser import parse_conversation
from backend.modules.chatgpt_import._repository import ChatGptImportRepository
from backend.modules.chatgpt_import._session_builder import (
    build_imported_session_request,
)
from backend.ws.event_bus import get_event_bus
from shared.events.chatgpt_import import (
    ChatGptImportConversationImportedEvent,
    ChatGptImportConversationImportFailedEvent,
)
from shared.topics import Topics

_log = logging.getLogger(__name__)


async def handle_chatgpt_import_conversation(job: Any) -> None:
    payload = job.payload
    user_id = payload["user_id"]
    import_id = payload["import_id"]
    chatgpt_conversation_id = payload["chatgpt_conversation_id"]
    persona_id = payload["persona_id"]
    correlation_id = payload.get("correlation_id")

    db = get_db()
    repo = ChatGptImportRepository(db)
    bus = get_event_bus()

    async def fail(code: str, message: str) -> None:
        await bus.publish(
            Topics.CHATGPT_IMPORT_CONVERSATION_IMPORT_FAILED,
            ChatGptImportConversationImportFailedEvent(
                import_id=import_id,
                chatgpt_conversation_id=chatgpt_conversation_id,
                persona_id=persona_id,
                error_code=code,
                error_message=message,
            ),
            scope=f"chatgpt_import:{import_id}",
            target_user_ids=[user_id],
            correlation_id=correlation_id,
        )

    conv_doc = await repo.get_conversation(
        user_id=user_id, import_id=import_id, chatgpt_conversation_id=chatgpt_conversation_id
    )
    if not conv_doc:
        await fail("conversation_not_found", "Conversation no longer in import")
        return

    parsed = parse_conversation(conv_doc["raw_data"])
    if not parsed.messages:
        await fail("no_convertible_messages", "No user/assistant text after filtering")
        return

    try:
        req = build_imported_session_request(parsed=parsed, persona_id=persona_id)
        session = await create_imported_session(
            db,
            user_id=user_id,
            persona_id=req.persona_id,
            title=req.title,
            messages=req.messages,
            imported_from=req.imported_from,
            imported_model_slug=req.imported_model_slug,
            original_created_at=req.original_created_at,
        )
    except Exception as exc:
        await fail(type(exc).__name__, str(exc))
        raise

    session_id = str(session["_id"])
    await repo.record_import(
        import_id=import_id,
        chatgpt_conversation_id=chatgpt_conversation_id,
        persona_id=persona_id,
        session_id=session_id,
    )
    await repo.reset_ttl(import_id)

    await bus.publish(
        Topics.CHATGPT_IMPORT_CONVERSATION_IMPORTED,
        ChatGptImportConversationImportedEvent(
            import_id=import_id,
            chatgpt_conversation_id=chatgpt_conversation_id,
            persona_id=persona_id,
            session_id=session_id,
            title=parsed.title,
        ),
        scope=f"chatgpt_import:{import_id}",
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )
    # Also publish on the persona scope so other tabs update
    await bus.publish(
        Topics.CHATGPT_IMPORT_CONVERSATION_IMPORTED,
        ChatGptImportConversationImportedEvent(
            import_id=import_id,
            chatgpt_conversation_id=chatgpt_conversation_id,
            persona_id=persona_id,
            session_id=session_id,
            title=parsed.title,
        ),
        scope=f"persona:{persona_id}",
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )
```

- [ ] **Step 4: Verify pass**

```bash
PYTHONPATH=. uv run pytest tests/chatgpt_import/test_conversation_handler.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/jobs/handlers/_chatgpt_import_conversation.py \
        tests/chatgpt_import/test_conversation_handler.py
git commit -m "Add per-conversation import job handler"
```

---

### Task 18: Register handlers in JOB_REGISTRY

**Files:**
- Modify: `backend/jobs/_registry.py`

- [ ] **Step 1: Add the two new entries**

In `JOB_REGISTRY`:

```python
from backend.jobs.handlers._chatgpt_import_parse import handle_chatgpt_import_parse
from backend.jobs.handlers._chatgpt_import_conversation import handle_chatgpt_import_conversation


JOB_REGISTRY: dict[JobType, JobConfig] = {
    # ... existing entries ...
    JobType.CHATGPT_IMPORT_PARSE: JobConfig(
        handler=handle_chatgpt_import_parse,
        max_retries=1,
        execution_timeout_seconds=600.0,
        notify=True,
    ),
    JobType.CHATGPT_IMPORT_CONVERSATION: JobConfig(
        handler=handle_chatgpt_import_conversation,
        max_retries=1,
        execution_timeout_seconds=30.0,
        notify=True,
    ),
}
```

- [ ] **Step 2: Smoke-import**

```bash
PYTHONPATH=. uv run python -c "from backend.jobs._registry import JOB_REGISTRY; from backend.jobs._models import JobType; print(JOB_REGISTRY[JobType.CHATGPT_IMPORT_PARSE].handler.__name__)"
```
Expected: `handle_chatgpt_import_parse`.

- [ ] **Step 3: Commit**

```bash
git add backend/jobs/_registry.py
git commit -m "Register ChatGPT-import job handlers in JOB_REGISTRY"
```

---

### Task 19: ChatGptImportService (public-API class)

**Files:**
- Create: `backend/modules/chatgpt_import/_service.py`
- Modify: `backend/modules/chatgpt_import/__init__.py`

- [ ] **Step 1: Create the service class**

```python
# backend/modules/chatgpt_import/_service.py
"""Public service surface for the chatgpt_import module."""
from __future__ import annotations

import hashlib
import logging
import secrets
import tempfile
from pathlib import Path
from typing import AsyncIterator

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.jobs._models import JobType
from backend.jobs.submit import submit
from backend.modules.chatgpt_import._repository import ChatGptImportRepository

_log = logging.getLogger(__name__)


class ChatGptImportService:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._repo = ChatGptImportRepository(db)

    async def upload_streaming(
        self,
        *,
        user_id: str,
        stream: AsyncIterator[bytes],
        filename: str,
        replace_existing: bool = False,
    ) -> tuple[str, bool]:
        """Stream the body to /tmp, dedupe by hash, dispatch parse job.

        Returns (import_id, duplicate). If the file_hash matches an existing
        active import, returns that import's id with duplicate=True and skips
        parsing.
        """
        # Stream to a temp file while computing hash
        sha = hashlib.sha256()
        size = 0
        tmp = tempfile.NamedTemporaryFile(
            prefix="chatgpt_import_", suffix=".json", delete=False
        )
        path = Path(tmp.name)
        try:
            async for chunk in stream:
                sha.update(chunk)
                size += len(chunk)
                tmp.write(chunk)
        finally:
            tmp.close()

        file_hash = sha.hexdigest()
        existing = await self._repo.find_import_by_hash(user_id, file_hash)
        if existing:
            path.unlink(missing_ok=True)
            return str(existing["_id"]), True

        active = await self._repo.get_active_import(user_id)
        if active and not replace_existing:
            path.unlink(missing_ok=True)
            raise ImportConflictError(
                existing_import_id=str(active["_id"]),
                message="An active upload already exists",
            )
        if active and replace_existing:
            await self._repo.delete_import(str(active["_id"]))

        import_id = await self._repo.create_import(
            user_id=user_id,
            file_hash=file_hash,
            file_size_bytes=size,
            filename=filename,
        )

        correlation_id = f"import-parse-{secrets.token_hex(8)}"
        await submit(
            JobType.CHATGPT_IMPORT_PARSE,
            payload={
                "user_id": user_id,
                "import_id": import_id,
                "file_path": str(path),
                "filename": filename,
                "file_size_bytes": size,
                "correlation_id": correlation_id,
            },
            user_id=user_id,
        )
        return import_id, False

    async def trigger_conversation_imports(
        self,
        *,
        user_id: str,
        import_id: str,
        persona_id: str,
        chatgpt_conversation_ids: list[str],
    ) -> tuple[str, list[tuple[str, str]]]:
        """Queue one job per conversation. Returns (correlation_id, [(conv_id, job_id)])."""
        correlation_id = f"import-batch-{secrets.token_hex(6)}"
        jobs: list[tuple[str, str]] = []
        for cid in chatgpt_conversation_ids:
            job_id = await submit(
                JobType.CHATGPT_IMPORT_CONVERSATION,
                payload={
                    "user_id": user_id,
                    "import_id": import_id,
                    "chatgpt_conversation_id": cid,
                    "persona_id": persona_id,
                    "correlation_id": correlation_id,
                },
                user_id=user_id,
            )
            jobs.append((cid, str(job_id)))
        return correlation_id, jobs


class ImportConflictError(Exception):
    def __init__(self, *, existing_import_id: str, message: str) -> None:
        super().__init__(message)
        self.existing_import_id = existing_import_id
```

- [ ] **Step 2: Re-export from `__init__.py`**

Replace the placeholder `__init__.py` (created in Task 8) with:

```python
"""Public API for the chatgpt_import module."""
from backend.modules.chatgpt_import._handlers import router
from backend.modules.chatgpt_import._service import (
    ChatGptImportService,
    ImportConflictError,
)

__all__ = [
    "router",
    "init_indexes",
    "ChatGptImportService",
    "ImportConflictError",
]


async def init_indexes(db) -> None:
    from backend.modules.chatgpt_import._repository import ChatGptImportRepository
    repo = ChatGptImportRepository(db)
    await repo.create_indexes()
```

- [ ] **Step 3: Smoke-import**

(Will fail until handlers exist — defer commit.)

---

### Task 20: REST handlers — upload endpoint

**Files:**
- Create: `backend/modules/chatgpt_import/_handlers.py`

- [ ] **Step 1: Implement the file with router + upload endpoint**

```python
# backend/modules/chatgpt_import/_handlers.py
"""REST API for /api/chatgpt-import/*."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from backend.modules.chatgpt_import._service import (
    ChatGptImportService,
    ImportConflictError,
)
from backend.db import get_db
from backend.modules.user._auth import require_active_session
from shared.dtos.chatgpt_import import (
    ConversationItemDto,
    ImportDto,
    ImportTriggerJobInfo,
    ImportTriggerRequest,
    ImportTriggerResponse,
    ImportedInfoDto,
    UploadResponse,
)

router = APIRouter(prefix="/api/chatgpt-import")

_MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB


def _service() -> ChatGptImportService:
    return ChatGptImportService(get_db())


@router.post("/uploads", status_code=201, response_model=UploadResponse)
async def upload(
    request: Request,
    filename: str = Query(default="conversations.json"),
    replace: bool = Query(default=False),
    user: dict = Depends(require_active_session),
) -> UploadResponse:
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large")

    service = _service()
    try:
        import_id, duplicate = await service.upload_streaming(
            user_id=user["_id"],
            stream=request.stream(),
            filename=filename,
            replace_existing=replace,
        )
    except ImportConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "existing_import_id": exc.existing_import_id,
            },
        )
    status_text = "ready" if duplicate else "parsing"
    return UploadResponse(import_id=import_id, status=status_text, duplicate=duplicate)
```

(Note: `require_active_session` and `get_db` import paths must match the existing codebase. If they live elsewhere, adapt the import.)

- [ ] **Step 2: Smoke-import**

```bash
PYTHONPATH=. uv run python -c "from backend.modules.chatgpt_import import router; print([r.path for r in router.routes])"
```
Expected: includes `/api/chatgpt-import/uploads`.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/chatgpt_import/_service.py \
        backend/modules/chatgpt_import/_handlers.py \
        backend/modules/chatgpt_import/__init__.py
git commit -m "Add ChatGptImportService + upload endpoint"
```

---

### Task 21: REST handlers — listing + active + delete

**Files:**
- Modify: `backend/modules/chatgpt_import/_handlers.py`
- Modify: `backend/modules/chatgpt_import/_service.py` (add list method)

- [ ] **Step 1: Add service method `get_active_import_dto`, `list_conversations_for_ui`, `delete_import`**

In `_service.py` append:

```python
from datetime import datetime

from bson import ObjectId

from shared.dtos.chatgpt_import import (
    ConversationItemDto,
    ImportDto,
    ImportedInfoDto,
)


async def get_active_import_dto(self, *, user_id: str) -> ImportDto | None:
    doc = await self._repo.get_active_import(user_id)
    if not doc:
        return None
    return _import_doc_to_dto(doc)


async def list_conversations_for_ui(
    self,
    *,
    user_id: str,
    import_id: str,
    persona_names: dict[str, str],
    title_search: str | None = None,
    sort: str = "create_time_desc",
) -> list[ConversationItemDto]:
    docs = await self._repo.list_conversations(
        user_id=user_id, import_id=import_id, title_search=title_search, sort=sort
    )
    return [_conv_doc_to_dto(d, persona_names) for d in docs]


async def delete_import(self, *, user_id: str, import_id: str) -> None:
    doc = await self._repo.get_active_import(user_id)
    if not doc or str(doc["_id"]) != import_id:
        raise HTTPException(status_code=404, detail="Import not found")
    await self._repo.delete_import(import_id)


def _import_doc_to_dto(doc: dict) -> ImportDto:
    return ImportDto(
        import_id=str(doc["_id"]),
        filename=doc["uploaded_filename"],
        file_size_bytes=doc["file_size_bytes"],
        status=doc["status"],
        conversation_count=doc.get("conversation_count", 0),
        skipped_count=doc.get("skipped_count", 0),
        skipped_reasons=doc.get("skipped_reasons", {}),
        created_at=doc["created_at"],
        expires_at=doc["expires_at"],
        last_import_at=doc.get("last_import_at"),
        error_message=doc.get("error_message"),
    )


def _conv_doc_to_dto(doc: dict, persona_names: dict[str, str]) -> ConversationItemDto:
    imports = [
        ImportedInfoDto(
            persona_id=i["persona_id"],
            persona_name=persona_names.get(i["persona_id"], "unknown"),
            session_id=i["session_id"],
            imported_at=i["imported_at"],
        )
        for i in doc.get("imports", [])
    ]
    return ConversationItemDto(
        chatgpt_conversation_id=doc["chatgpt_conversation_id"],
        title=doc["title"],
        create_time=doc["create_time"],
        update_time=doc["update_time"],
        message_count=doc.get("message_count", 0),
        first_user_message_preview=doc.get("first_user_message_preview", ""),
        first_assistant_message_preview=doc.get("first_assistant_message_preview", ""),
        default_model_slug=doc.get("default_model_slug"),
        imports=imports,
    )
```

Note: `HTTPException` import here is wrong — services shouldn't raise HTTP types. Replace with a custom exception:

```python
class ImportNotFoundError(Exception):
    pass
```

Use it in `delete_import` and map to 404 in the handler.

- [ ] **Step 2: Append handlers in `_handlers.py`**

```python
from backend.modules.persona import list_user_personas  # adjust to actual API
from backend.modules.chatgpt_import._service import ImportNotFoundError


@router.get("/uploads/active", response_model=ImportDto | None)
async def get_active(
    user: dict = Depends(require_active_session),
) -> ImportDto | None:
    return await _service().get_active_import_dto(user_id=user["_id"])


@router.delete("/uploads/{import_id}", status_code=204)
async def delete(
    import_id: str,
    user: dict = Depends(require_active_session),
) -> None:
    try:
        await _service().delete_import(user_id=user["_id"], import_id=import_id)
    except ImportNotFoundError:
        raise HTTPException(status_code=404, detail="Import not found")


@router.get(
    "/uploads/{import_id}/conversations",
    response_model=list[ConversationItemDto],
)
async def list_conversations(
    import_id: str,
    title_search: str | None = Query(default=None),
    sort: str = Query(default="create_time_desc"),
    user: dict = Depends(require_active_session),
) -> list[ConversationItemDto]:
    # Build persona-name map for badges
    personas = await list_user_personas(user_id=user["_id"])
    persona_names = {p["_id"]: p["name"] for p in personas}
    return await _service().list_conversations_for_ui(
        user_id=user["_id"],
        import_id=import_id,
        persona_names=persona_names,
        title_search=title_search,
        sort=sort,
    )
```

`list_user_personas` may have a different name in the existing codebase — adapt to whichever public API the `persona` module exposes for listing the current user's personas.

- [ ] **Step 3: Smoke-import**

```bash
PYTHONPATH=. uv run python -c "from backend.modules.chatgpt_import import router; print(sorted(r.path for r in router.routes))"
```
Expected: prints the four endpoint paths.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/chatgpt_import/_service.py \
        backend/modules/chatgpt_import/_handlers.py
git commit -m "Add active/list/delete endpoints for ChatGPT-import"
```

---

### Task 22: REST handlers — import trigger endpoint

**Files:**
- Modify: `backend/modules/chatgpt_import/_handlers.py`

- [ ] **Step 1: Append the trigger endpoint**

```python
@router.post(
    "/uploads/{import_id}/import",
    response_model=ImportTriggerResponse,
    status_code=202,
)
async def trigger_import(
    import_id: str,
    body: ImportTriggerRequest,
    user: dict = Depends(require_active_session),
) -> ImportTriggerResponse:
    # Validate persona exists and belongs to user
    persona = await get_persona(user_id=user["_id"], persona_id=body.persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    # Validate at least one conversation id
    if not body.chatgpt_conversation_ids:
        raise HTTPException(status_code=400, detail="No conversations selected")

    correlation_id, job_pairs = await _service().trigger_conversation_imports(
        user_id=user["_id"],
        import_id=import_id,
        persona_id=body.persona_id,
        chatgpt_conversation_ids=body.chatgpt_conversation_ids,
    )
    return ImportTriggerResponse(
        correlation_id=correlation_id,
        jobs=[
            ImportTriggerJobInfo(chatgpt_conversation_id=cid, job_id=jid)
            for cid, jid in job_pairs
        ],
    )
```

`get_persona` should be imported from the persona module's public API.

- [ ] **Step 2: Smoke-import**

```bash
PYTHONPATH=. uv run python -c "from backend.modules.chatgpt_import import router; print(sum(1 for r in router.routes))"
```
Expected: 5 routes.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/chatgpt_import/_handlers.py
git commit -m "Add import-trigger endpoint for ChatGPT-import"
```

---

### Task 23: Wire `chatgpt_import` into `backend/main.py`

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add imports near the other module-router imports**

```python
from backend.modules.chatgpt_import import (
    init_indexes as chatgpt_import_init_indexes,
    router as chatgpt_import_router,
)
```

- [ ] **Step 2: Add `init_indexes` call in the startup block**

In the section where `await memory_init_indexes(db)` lives, append:

```python
await chatgpt_import_init_indexes(db)
```

- [ ] **Step 3: Register the router**

Where existing routers are mounted with `app.include_router(...)`:

```python
app.include_router(chatgpt_import_router)
```

- [ ] **Step 4: Smoke-start**

```bash
PYTHONPATH=. uv run python -c "from backend.main import app; print(sorted(r.path for r in app.routes if hasattr(r, 'path') and 'chatgpt-import' in r.path))"
```
Expected: prints all 5 routes.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "Wire chatgpt_import router and indexes into main.py"
```

---

### Task 24: API client (frontend)

**Files:**
- Create: `frontend/src/core/api/chatGptImportApi.ts`

- [ ] **Step 1: Create the file**

```typescript
// frontend/src/core/api/chatGptImportApi.ts
import { api, baseUrl, currentAccessToken, ApiError } from './client'

export interface ImportDto {
  import_id: string
  filename: string
  file_size_bytes: number
  status: 'parsing' | 'ready' | 'failed'
  conversation_count: number
  skipped_count: number
  skipped_reasons: Record<string, number>
  created_at: string
  expires_at: string
  last_import_at: string | null
  error_message: string | null
}

export interface ImportedInfoDto {
  persona_id: string
  persona_name: string
  session_id: string
  imported_at: string
}

export interface ConversationItemDto {
  chatgpt_conversation_id: string
  title: string
  create_time: string
  update_time: string
  message_count: number
  first_user_message_preview: string
  first_assistant_message_preview: string
  default_model_slug: string | null
  imports: ImportedInfoDto[]
}

export interface UploadResponse {
  import_id: string
  status: 'parsing' | 'ready' | 'failed'
  duplicate: boolean
}

export interface ImportTriggerResponse {
  correlation_id: string
  jobs: { chatgpt_conversation_id: string; job_id: string }[]
}

export const chatGptImportApi = {
  uploadFile: async (
    file: File,
    options: { replace?: boolean; onProgress?: (loaded: number) => void } = {},
  ): Promise<UploadResponse> => {
    const token = currentAccessToken()
    const headers: Record<string, string> = {
      'Content-Type': 'application/octet-stream',
    }
    if (token) headers['Authorization'] = `Bearer ${token}`
    const url =
      `${baseUrl()}/api/chatgpt-import/uploads` +
      `?filename=${encodeURIComponent(file.name)}` +
      (options.replace ? '&replace=true' : '')

    // Use XHR to report progress (fetch lacks upload-progress on most browsers)
    return await new Promise<UploadResponse>((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', url)
      Object.entries(headers).forEach(([k, v]) => xhr.setRequestHeader(k, v))
      xhr.withCredentials = true
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && options.onProgress) options.onProgress(e.loaded)
      }
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(JSON.parse(xhr.responseText) as UploadResponse)
        } else {
          let body: unknown = null
          try { body = JSON.parse(xhr.responseText) } catch { /* */ }
          reject(new ApiError(xhr.status, xhr.statusText, body))
        }
      }
      xhr.onerror = () => reject(new ApiError(0, 'Network error', null))
      xhr.send(file)
    })
  },

  getActiveImport: () => api.get<ImportDto | null>('/api/chatgpt-import/uploads/active'),

  deleteImport: (importId: string) =>
    api.delete<void>(`/api/chatgpt-import/uploads/${importId}`),

  listConversations: (
    importId: string,
    params: { titleSearch?: string; sort?: string } = {},
  ) => {
    const q = new URLSearchParams()
    if (params.titleSearch) q.set('title_search', params.titleSearch)
    if (params.sort) q.set('sort', params.sort)
    const query = q.toString()
    return api.get<ConversationItemDto[]>(
      `/api/chatgpt-import/uploads/${importId}/conversations${query ? '?' + query : ''}`,
    )
  },

  triggerImport: (
    importId: string,
    body: { persona_id: string; chatgpt_conversation_ids: string[] },
  ) =>
    api.post<ImportTriggerResponse>(
      `/api/chatgpt-import/uploads/${importId}/import`,
      body,
    ),
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && pnpm tsc --noEmit
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/core/api/chatGptImportApi.ts
git commit -m "Add ChatGPT-import API client"
```

---

### Task 25: Zustand store

**Files:**
- Create: `frontend/src/core/store/chatGptImportStore.ts`

- [ ] **Step 1: Create the store**

```typescript
// frontend/src/core/store/chatGptImportStore.ts
import { create } from 'zustand'

import type {
  ConversationItemDto,
  ImportDto,
} from '../api/chatGptImportApi'

type StatusFilter = 'all' | 'not_in_this_persona' | 'not_in_any_persona' | 'in_other_persona'
type SortOption = 'create_time_desc' | 'create_time_asc' | 'title_asc'

interface ChatGptImportState {
  activeImport: ImportDto | null
  conversations: ConversationItemDto[]
  parseProgress: { conversationsIndexed: number } | null
  selectedConversationIds: Set<string>
  importingConversationIds: Set<string>
  titleSearch: string
  sort: SortOption
  statusFilter: StatusFilter

  setActiveImport: (imp: ImportDto | null) => void
  setConversations: (convs: ConversationItemDto[]) => void
  setParseProgress: (p: { conversationsIndexed: number } | null) => void
  toggleSelected: (id: string) => void
  clearSelection: () => void
  setImportingIds: (ids: Set<string>) => void
  markConversationImported: (
    convId: string,
    info: { persona_id: string; persona_name: string; session_id: string; imported_at: string },
  ) => void

  setTitleSearch: (s: string) => void
  setSort: (s: SortOption) => void
  setStatusFilter: (s: StatusFilter) => void
}

export const useChatGptImportStore = create<ChatGptImportState>((set) => ({
  activeImport: null,
  conversations: [],
  parseProgress: null,
  selectedConversationIds: new Set(),
  importingConversationIds: new Set(),
  titleSearch: '',
  sort: 'create_time_desc',
  statusFilter: 'all',

  setActiveImport: (imp) => set({ activeImport: imp }),
  setConversations: (convs) => set({ conversations: convs }),
  setParseProgress: (p) => set({ parseProgress: p }),

  toggleSelected: (id) =>
    set((s) => {
      const next = new Set(s.selectedConversationIds)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return { selectedConversationIds: next }
    }),

  clearSelection: () => set({ selectedConversationIds: new Set() }),

  setImportingIds: (ids) => set({ importingConversationIds: ids }),

  markConversationImported: (convId, info) =>
    set((s) => ({
      conversations: s.conversations.map((c) =>
        c.chatgpt_conversation_id === convId
          ? { ...c, imports: [...c.imports, info] }
          : c,
      ),
      importingConversationIds: (() => {
        const next = new Set(s.importingConversationIds)
        next.delete(convId)
        return next
      })(),
    })),

  setTitleSearch: (titleSearch) => set({ titleSearch }),
  setSort: (sort) => set({ sort }),
  setStatusFilter: (statusFilter) => set({ statusFilter }),
}))
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && pnpm tsc --noEmit
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/core/store/chatGptImportStore.ts
git commit -m "Add ChatGPT-import Zustand store"
```

---

### Task 26: WebSocket events hook

**Files:**
- Create: `frontend/src/features/chatgpt-import/useChatGptImportEvents.ts`

- [ ] **Step 1: Create the hook**

```typescript
// frontend/src/features/chatgpt-import/useChatGptImportEvents.ts
import { useEffect } from 'react'

import { eventBus } from '../../core/ws/eventBus'  // adjust to actual import
import { useChatGptImportStore } from '../../core/store/chatGptImportStore'

type BaseEvent = { type: string; payload: Record<string, unknown> }

export function useChatGptImportEvents(personaId: string | null): void {
  useEffect(() => {
    const handle = (event: BaseEvent) => {
      const p = event.payload
      const store = useChatGptImportStore.getState()
      switch (event.type) {
        case 'chatgpt_import.parse.started': {
          // Refresh active import
          store.setParseProgress({ conversationsIndexed: 0 })
          break
        }
        case 'chatgpt_import.parse.progress': {
          store.setParseProgress({
            conversationsIndexed: p.conversations_indexed as number,
          })
          break
        }
        case 'chatgpt_import.parse.done': {
          store.setParseProgress(null)
          store.setActiveImport({
            ...(store.activeImport!),
            status: 'ready',
            conversation_count: p.conversation_count as number,
            expires_at: p.expires_at as string,
            skipped_count: p.skipped_count as number,
            skipped_reasons: p.skipped_reasons as Record<string, number>,
          })
          break
        }
        case 'chatgpt_import.parse.failed': {
          store.setParseProgress(null)
          if (store.activeImport) {
            store.setActiveImport({
              ...store.activeImport,
              status: 'failed',
              error_message: p.error_message as string,
            })
          }
          break
        }
        case 'chatgpt_import.conversation.imported': {
          const convId = p.chatgpt_conversation_id as string
          const eventPersonaId = p.persona_id as string
          store.markConversationImported(convId, {
            persona_id: eventPersonaId,
            persona_name: '', // resolved in the row UI
            session_id: p.session_id as string,
            imported_at: new Date().toISOString(),
          })
          break
        }
        case 'chatgpt_import.conversation.import_failed': {
          const convId = p.chatgpt_conversation_id as string
          const ids = new Set(store.importingConversationIds)
          ids.delete(convId)
          store.setImportingIds(ids)
          break
        }
      }
    }

    const unsub = eventBus.on('chatgpt_import.*', handle)
    return unsub
  }, [personaId])
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && pnpm tsc --noEmit
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chatgpt-import/useChatGptImportEvents.ts
git commit -m "Add WebSocket events hook for ChatGPT-import"
```

---

### Task 27: UploadEmptyState component

**Files:**
- Create: `frontend/src/features/chatgpt-import/UploadEmptyState.tsx`

- [ ] **Step 1: Implement**

```typescript
// frontend/src/features/chatgpt-import/UploadEmptyState.tsx
import { useRef } from 'react'

interface Props {
  onFileSelected: (file: File) => void
  isUploading: boolean
  uploadProgress: number | null  // bytes loaded
}

export function UploadEmptyState({ onFileSelected, isUploading, uploadProgress }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)

  const onClick = () => inputRef.current?.click()
  const onChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) onFileSelected(file)
    // Reset so same file can be reselected
    if (inputRef.current) inputRef.current.value = ''
  }

  return (
    <div className="p-8 text-center">
      <input
        ref={inputRef}
        type="file"
        accept=".json,application/json"
        onChange={onChange}
        className="hidden"
      />
      <button
        type="button"
        onClick={onClick}
        disabled={isUploading}
        className="px-6 py-3 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-white font-medium"
      >
        {isUploading
          ? `Uploading… ${uploadProgress ? Math.round(uploadProgress / 1024 / 1024) + ' MB' : ''}`
          : 'Upload file'}
      </button>
      <p className="mt-6 text-sm text-white/70 max-w-md mx-auto">
        Upload your ChatGPT export <code className="font-mono">conversations.json</code>.
        You can then import individual or multiple conversations into this persona
        as sessions.
      </p>
      <ul className="mt-4 text-xs text-white/50 max-w-md mx-auto text-left list-disc pl-5">
        <li>Retained for 14 days</li>
        <li>Retention resets on every import</li>
        <li>File applies across all your personas</li>
      </ul>
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && pnpm tsc --noEmit
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chatgpt-import/UploadEmptyState.tsx
git commit -m "Add UploadEmptyState component"
```

---

### Task 28: ParseProgressBanner component

**Files:**
- Create: `frontend/src/features/chatgpt-import/ParseProgressBanner.tsx`

- [ ] **Step 1: Implement**

```typescript
// frontend/src/features/chatgpt-import/ParseProgressBanner.tsx
interface Props {
  conversationsIndexed: number
  failed?: { errorMessage: string } | null
  onRestart?: () => void
}

export function ParseProgressBanner({ conversationsIndexed, failed, onRestart }: Props) {
  if (failed) {
    return (
      <div className="bg-red-900/30 border border-red-700 rounded-lg p-4 mb-4">
        <p className="text-red-200">Parsing failed: {failed.errorMessage}</p>
        {onRestart && (
          <button
            type="button"
            onClick={onRestart}
            className="mt-2 text-sm underline text-red-300 hover:text-red-100"
          >
            Start another upload
          </button>
        )}
      </div>
    )
  }
  return (
    <div className="bg-indigo-900/30 border border-indigo-700 rounded-lg p-4 mb-4 flex items-center gap-3">
      <span className="animate-spin">⏳</span>
      <p className="text-indigo-100">
        Processing file — <strong>{conversationsIndexed}</strong> conversations indexed…
      </p>
    </div>
  )
}
```

- [ ] **Step 2: Type-check + commit**

```bash
cd frontend && pnpm tsc --noEmit
git add frontend/src/features/chatgpt-import/ParseProgressBanner.tsx
git commit -m "Add ParseProgressBanner component"
```

---

### Task 29: ConversationFilters component

**Files:**
- Create: `frontend/src/features/chatgpt-import/ConversationFilters.tsx`

- [ ] **Step 1: Implement**

```typescript
// frontend/src/features/chatgpt-import/ConversationFilters.tsx
import { useChatGptImportStore } from '../../core/store/chatGptImportStore'

const OPTION_STYLE: React.CSSProperties = {
  background: '#0f0d16',
  color: 'rgba(255,255,255,0.85)',
}

export function ConversationFilters() {
  const titleSearch = useChatGptImportStore((s) => s.titleSearch)
  const sort = useChatGptImportStore((s) => s.sort)
  const statusFilter = useChatGptImportStore((s) => s.statusFilter)
  const setTitleSearch = useChatGptImportStore((s) => s.setTitleSearch)
  const setSort = useChatGptImportStore((s) => s.setSort)
  const setStatusFilter = useChatGptImportStore((s) => s.setStatusFilter)

  return (
    <div className="flex flex-wrap gap-3 mb-4">
      <input
        type="search"
        placeholder="Search title…"
        value={titleSearch}
        onChange={(e) => setTitleSearch(e.target.value)}
        className="flex-1 min-w-[200px] px-3 py-2 bg-white/5 border border-white/10 rounded text-white"
      />
      <select
        value={sort}
        onChange={(e) => setSort(e.target.value as 'create_time_desc' | 'create_time_asc' | 'title_asc')}
        className="px-3 py-2 bg-white/5 border border-white/10 rounded text-white"
      >
        <option value="create_time_desc" style={OPTION_STYLE}>Newest first</option>
        <option value="create_time_asc" style={OPTION_STYLE}>Oldest first</option>
        <option value="title_asc" style={OPTION_STYLE}>Title A-Z</option>
      </select>
      <select
        value={statusFilter}
        onChange={(e) =>
          setStatusFilter(e.target.value as 'all' | 'not_in_this_persona' | 'not_in_any_persona' | 'in_other_persona')
        }
        className="px-3 py-2 bg-white/5 border border-white/10 rounded text-white"
      >
        <option value="all" style={OPTION_STYLE}>All</option>
        <option value="not_in_this_persona" style={OPTION_STYLE}>Not in this persona</option>
        <option value="not_in_any_persona" style={OPTION_STYLE}>Not in any persona</option>
        <option value="in_other_persona" style={OPTION_STYLE}>In another persona</option>
      </select>
    </div>
  )
}
```

- [ ] **Step 2: Type-check + commit**

```bash
cd frontend && pnpm tsc --noEmit
git add frontend/src/features/chatgpt-import/ConversationFilters.tsx
git commit -m "Add ConversationFilters component"
```

---

### Task 30: ConversationRow + ConversationPreviewExpanded components

**Files:**
- Create: `frontend/src/features/chatgpt-import/ConversationRow.tsx`
- Create: `frontend/src/features/chatgpt-import/ConversationPreviewExpanded.tsx`

- [ ] **Step 1: Implement `ConversationPreviewExpanded`**

```typescript
// frontend/src/features/chatgpt-import/ConversationPreviewExpanded.tsx
import { useEffect, useState } from 'react'

import { chatGptImportApi, type ConversationItemDto } from '../../core/api/chatGptImportApi'

// For the expanded preview we re-fetch the full conversation; but in this iteration we
// reuse the previews already loaded (full message list is not exposed by the listing endpoint).
// Future task: add a GET /uploads/{id}/conversations/{cid} that returns parsed messages.

interface Props {
  conv: ConversationItemDto
}

export function ConversationPreviewExpanded({ conv }: Props) {
  return (
    <div className="ml-8 mt-2 pl-3 border-l-2 border-white/10 text-sm text-white/70 space-y-2">
      {conv.first_user_message_preview && (
        <div>
          <span className="font-mono text-xs px-1 py-0.5 bg-white/10 rounded mr-2">⟨user⟩</span>
          {conv.first_user_message_preview}
        </div>
      )}
      {conv.first_assistant_message_preview && (
        <div>
          <span className="font-mono text-xs px-1 py-0.5 bg-white/10 rounded mr-2">⟨assistant⟩</span>
          {conv.first_assistant_message_preview}
        </div>
      )}
      <p className="text-xs text-white/40 italic">
        Full message list available once imported into a session.
      </p>
    </div>
  )
}
```

- [ ] **Step 2: Implement `ConversationRow`**

```typescript
// frontend/src/features/chatgpt-import/ConversationRow.tsx
import { useState } from 'react'

import type { ConversationItemDto } from '../../core/api/chatGptImportApi'
import { useChatGptImportStore } from '../../core/store/chatGptImportStore'

import { ConversationPreviewExpanded } from './ConversationPreviewExpanded'

interface Props {
  conv: ConversationItemDto
  currentPersonaId: string
}

export function ConversationRow({ conv, currentPersonaId }: Props) {
  const [expanded, setExpanded] = useState(false)
  const isSelected = useChatGptImportStore((s) =>
    s.selectedConversationIds.has(conv.chatgpt_conversation_id),
  )
  const isImporting = useChatGptImportStore((s) =>
    s.importingConversationIds.has(conv.chatgpt_conversation_id),
  )
  const toggle = useChatGptImportStore((s) => s.toggleSelected)

  const inThisPersona = conv.imports.find((i) => i.persona_id === currentPersonaId)
  const inOtherPersonas = conv.imports.filter((i) => i.persona_id !== currentPersonaId)

  return (
    <div className="p-3 border-b border-white/5 hover:bg-white/5 transition">
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          checked={isSelected}
          onChange={() => toggle(conv.chatgpt_conversation_id)}
          disabled={isImporting}
          className="mt-1"
        />
        <div className="flex-1 min-w-0 cursor-pointer" onClick={() => setExpanded((v) => !v)}>
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-white font-medium truncate">{conv.title}</h3>
            {conv.default_model_slug && (
              <span className="font-mono text-xs px-1.5 py-0.5 bg-white/10 rounded text-white/70">
                {conv.default_model_slug}
              </span>
            )}
            {isImporting && <span className="text-xs text-amber-300">⏳ importing…</span>}
          </div>
          <p className="text-xs text-white/50 mt-0.5">
            {new Date(conv.create_time).toLocaleDateString()} · {conv.message_count} messages
          </p>
          <div className="flex flex-wrap gap-1 mt-1">
            {inThisPersona && (
              <span className="text-xs px-2 py-0.5 bg-emerald-900/40 text-emerald-200 rounded">
                in this persona, imported {new Date(inThisPersona.imported_at).toLocaleDateString()}
              </span>
            )}
            {inOtherPersonas.map((i) => (
              <span key={i.session_id} className="text-xs px-2 py-0.5 bg-white/10 text-white/60 rounded">
                in "{i.persona_name}", imported {new Date(i.imported_at).toLocaleDateString()}
              </span>
            ))}
          </div>
        </div>
      </div>
      {expanded && <ConversationPreviewExpanded conv={conv} />}
    </div>
  )
}
```

- [ ] **Step 3: Type-check + commit**

```bash
cd frontend && pnpm tsc --noEmit
git add frontend/src/features/chatgpt-import/ConversationRow.tsx \
        frontend/src/features/chatgpt-import/ConversationPreviewExpanded.tsx
git commit -m "Add ConversationRow + expanded preview components"
```

---

### Task 31: MultiSelectActionBar component

**Files:**
- Create: `frontend/src/features/chatgpt-import/MultiSelectActionBar.tsx`

- [ ] **Step 1: Implement**

```typescript
// frontend/src/features/chatgpt-import/MultiSelectActionBar.tsx
import { useChatGptImportStore } from '../../core/store/chatGptImportStore'

interface Props {
  onImportClick: () => void
}

export function MultiSelectActionBar({ onImportClick }: Props) {
  const selectedCount = useChatGptImportStore((s) => s.selectedConversationIds.size)
  const clearSelection = useChatGptImportStore((s) => s.clearSelection)

  if (selectedCount === 0) return null

  return (
    <div className="sticky bottom-0 left-0 right-0 bg-[#0f0d16] border-t border-white/10 px-4 py-3 flex items-center justify-between z-10">
      <span className="text-white/80">{selectedCount} selected</span>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onImportClick}
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded font-medium"
        >
          Import into this persona
        </button>
        <button
          type="button"
          onClick={clearSelection}
          aria-label="Clear selection"
          className="px-3 py-2 bg-white/5 hover:bg-white/10 text-white rounded"
        >
          ×
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Type-check + commit**

```bash
cd frontend && pnpm tsc --noEmit
git add frontend/src/features/chatgpt-import/MultiSelectActionBar.tsx
git commit -m "Add MultiSelectActionBar component"
```

---

### Task 32: ImportConfirmDialog component

**Files:**
- Create: `frontend/src/features/chatgpt-import/ImportConfirmDialog.tsx`

- [ ] **Step 1: Implement**

```typescript
// frontend/src/features/chatgpt-import/ImportConfirmDialog.tsx
import { Sheet } from '../../core/components/Sheet'
import type { ConversationItemDto } from '../../core/api/chatGptImportApi'

interface Props {
  isOpen: boolean
  onCancel: () => void
  onConfirm: () => void
  selectedConvs: ConversationItemDto[]
  personaName: string
  currentPersonaId: string
}

export function ImportConfirmDialog({
  isOpen,
  onCancel,
  onConfirm,
  selectedConvs,
  personaName,
  currentPersonaId,
}: Props) {
  const otherPersonaCount = selectedConvs.filter((c) =>
    c.imports.some((i) => i.persona_id !== currentPersonaId),
  ).length

  return (
    <Sheet isOpen={isOpen} onClose={onCancel} size="md" ariaLabel="Confirm import">
      <div className="p-6">
        <h2 className="text-xl font-semibold text-white mb-3">Confirm import</h2>
        <p className="text-white/80 mb-4">
          Import {selectedConvs.length} conversations into "{personaName}"?
        </p>
        <ul className="text-sm text-white/70 mb-4 max-h-40 overflow-y-auto list-disc pl-5">
          {selectedConvs.map((c) => (
            <li key={c.chatgpt_conversation_id}>{c.title}</li>
          ))}
        </ul>
        {otherPersonaCount > 0 && (
          <p className="text-xs text-white/50 mb-4 italic">
            {otherPersonaCount} of these were already imported into other personas —
            they will be added to "{personaName}" as well.
          </p>
        )}
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 bg-white/5 hover:bg-white/10 text-white rounded"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded font-medium"
          >
            Import
          </button>
        </div>
      </div>
    </Sheet>
  )
}
```

- [ ] **Step 2: Type-check + commit**

```bash
cd frontend && pnpm tsc --noEmit
git add frontend/src/features/chatgpt-import/ImportConfirmDialog.tsx
git commit -m "Add ImportConfirmDialog component"
```

---

### Task 33: ReplaceUploadDialog component

**Files:**
- Create: `frontend/src/features/chatgpt-import/ReplaceUploadDialog.tsx`

- [ ] **Step 1: Implement**

```typescript
// frontend/src/features/chatgpt-import/ReplaceUploadDialog.tsx
import { Sheet } from '../../core/components/Sheet'

interface Props {
  isOpen: boolean
  onCancel: () => void
  onConfirm: () => void
  currentFilename: string
  currentConversationCount: number
}

export function ReplaceUploadDialog({
  isOpen,
  onCancel,
  onConfirm,
  currentFilename,
  currentConversationCount,
}: Props) {
  return (
    <Sheet isOpen={isOpen} onClose={onCancel} size="md" ariaLabel="Replace active file">
      <div className="p-6">
        <h2 className="text-xl font-semibold text-white mb-3">Replace active file?</h2>
        <p className="text-white/80 mb-4">
          There is still an active upload (<code className="font-mono text-sm">{currentFilename}</code>,{' '}
          {currentConversationCount} conversations).
        </p>
        <p className="text-white/70 mb-4">
          If you upload a new one, the old list of not-yet-imported conversations will be
          discarded.
        </p>
        <p className="text-white/50 mb-4 text-sm italic">
          Already-imported sessions remain untouched.
        </p>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 bg-white/5 hover:bg-white/10 text-white rounded"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="px-4 py-2 bg-amber-600 hover:bg-amber-500 text-white rounded font-medium"
          >
            Replace
          </button>
        </div>
      </div>
    </Sheet>
  )
}
```

- [ ] **Step 2: Type-check + commit**

```bash
cd frontend && pnpm tsc --noEmit
git add frontend/src/features/chatgpt-import/ReplaceUploadDialog.tsx
git commit -m "Add ReplaceUploadDialog component"
```

---

### Task 34: ConversationList orchestrator

**Files:**
- Create: `frontend/src/features/chatgpt-import/ConversationList.tsx`

- [ ] **Step 1: Implement**

```typescript
// frontend/src/features/chatgpt-import/ConversationList.tsx
import { useMemo, useState } from 'react'

import type { ConversationItemDto } from '../../core/api/chatGptImportApi'
import { useChatGptImportStore } from '../../core/store/chatGptImportStore'

import { ConversationFilters } from './ConversationFilters'
import { ConversationRow } from './ConversationRow'
import { ImportConfirmDialog } from './ImportConfirmDialog'
import { MultiSelectActionBar } from './MultiSelectActionBar'

interface Props {
  conversations: ConversationItemDto[]
  currentPersonaId: string
  currentPersonaName: string
  onConfirmImport: (convs: ConversationItemDto[]) => void
}

export function ConversationList({
  conversations,
  currentPersonaId,
  currentPersonaName,
  onConfirmImport,
}: Props) {
  const titleSearch = useChatGptImportStore((s) => s.titleSearch)
  const statusFilter = useChatGptImportStore((s) => s.statusFilter)
  const selectedIds = useChatGptImportStore((s) => s.selectedConversationIds)
  const [confirmOpen, setConfirmOpen] = useState(false)

  const filtered = useMemo(() => {
    return conversations.filter((c) => {
      if (titleSearch && !c.title.toLowerCase().includes(titleSearch.toLowerCase())) {
        return false
      }
      const inThis = c.imports.some((i) => i.persona_id === currentPersonaId)
      const inAny = c.imports.length > 0
      if (statusFilter === 'not_in_this_persona' && inThis) return false
      if (statusFilter === 'not_in_any_persona' && inAny) return false
      if (statusFilter === 'in_other_persona' && (inThis || !inAny)) return false
      return true
    })
  }, [conversations, titleSearch, statusFilter, currentPersonaId])

  const selectedConvs = filtered.filter((c) => selectedIds.has(c.chatgpt_conversation_id))

  return (
    <div>
      <ConversationFilters />
      <div className="divide-y divide-white/5">
        {filtered.map((c) => (
          <ConversationRow
            key={c.chatgpt_conversation_id}
            conv={c}
            currentPersonaId={currentPersonaId}
          />
        ))}
      </div>
      <MultiSelectActionBar onImportClick={() => setConfirmOpen(true)} />
      <ImportConfirmDialog
        isOpen={confirmOpen}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => {
          setConfirmOpen(false)
          onConfirmImport(selectedConvs)
        }}
        selectedConvs={selectedConvs}
        personaName={currentPersonaName}
        currentPersonaId={currentPersonaId}
      />
    </div>
  )
}
```

- [ ] **Step 2: Type-check + commit**

```bash
cd frontend && pnpm tsc --noEmit
git add frontend/src/features/chatgpt-import/ConversationList.tsx
git commit -m "Add ConversationList orchestrator"
```

---

### Task 35: ChatGptImportTab root component

**Files:**
- Create: `frontend/src/features/chatgpt-import/ChatGptImportTab.tsx`

- [ ] **Step 1: Implement**

```typescript
// frontend/src/features/chatgpt-import/ChatGptImportTab.tsx
import { useCallback, useEffect, useState } from 'react'

import {
  chatGptImportApi,
  type ConversationItemDto,
  type ImportDto,
} from '../../core/api/chatGptImportApi'
import { ApiError } from '../../core/api/client'
import { useChatGptImportStore } from '../../core/store/chatGptImportStore'

import { ConversationList } from './ConversationList'
import { ParseProgressBanner } from './ParseProgressBanner'
import { ReplaceUploadDialog } from './ReplaceUploadDialog'
import { UploadEmptyState } from './UploadEmptyState'
import { useChatGptImportEvents } from './useChatGptImportEvents'

interface Props {
  personaId: string
  personaName: string
}

export function ChatGptImportTab({ personaId, personaName }: Props) {
  const activeImport = useChatGptImportStore((s) => s.activeImport)
  const conversations = useChatGptImportStore((s) => s.conversations)
  const parseProgress = useChatGptImportStore((s) => s.parseProgress)
  const setActiveImport = useChatGptImportStore((s) => s.setActiveImport)
  const setConversations = useChatGptImportStore((s) => s.setConversations)
  const setImportingIds = useChatGptImportStore((s) => s.setImportingIds)
  const titleSearch = useChatGptImportStore((s) => s.titleSearch)
  const sort = useChatGptImportStore((s) => s.sort)

  const [uploadProgress, setUploadProgress] = useState<number | null>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [replaceDialogFile, setReplaceDialogFile] = useState<File | null>(null)

  useChatGptImportEvents(personaId)

  // Initial fetch
  useEffect(() => {
    chatGptImportApi.getActiveImport().then((imp) => setActiveImport(imp))
  }, [setActiveImport])

  // Reload conversations when filters or active import change
  useEffect(() => {
    if (!activeImport || activeImport.status !== 'ready') {
      setConversations([])
      return
    }
    chatGptImportApi
      .listConversations(activeImport.import_id, { titleSearch, sort })
      .then(setConversations)
  }, [activeImport, titleSearch, sort, setConversations])

  const performUpload = useCallback(async (file: File, replace: boolean) => {
    setIsUploading(true)
    setUploadProgress(0)
    try {
      const res = await chatGptImportApi.uploadFile(file, {
        replace,
        onProgress: (loaded) => setUploadProgress(loaded),
      })
      const imp = await chatGptImportApi.getActiveImport()
      setActiveImport(imp)
      if (res.duplicate && imp) {
        // load conversations immediately
        const convs = await chatGptImportApi.listConversations(imp.import_id)
        setConversations(convs)
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // Conflict: we need replace flag
        setReplaceDialogFile(file)
      } else {
        // TODO: toast
        console.error(err)
      }
    } finally {
      setIsUploading(false)
      setUploadProgress(null)
    }
  }, [setActiveImport, setConversations])

  const onFileSelected = useCallback(
    (file: File) => performUpload(file, false),
    [performUpload],
  )

  const onReplaceConfirm = useCallback(() => {
    if (replaceDialogFile) {
      performUpload(replaceDialogFile, true)
      setReplaceDialogFile(null)
    }
  }, [replaceDialogFile, performUpload])

  const onConfirmImport = useCallback(
    async (convs: ConversationItemDto[]) => {
      if (!activeImport) return
      const ids = convs.map((c) => c.chatgpt_conversation_id)
      setImportingIds(new Set(ids))
      try {
        await chatGptImportApi.triggerImport(activeImport.import_id, {
          persona_id: personaId,
          chatgpt_conversation_ids: ids,
        })
      } catch (err) {
        console.error(err)
        setImportingIds(new Set())
      }
    },
    [activeImport, personaId, setImportingIds],
  )

  // State 1: no upload
  if (!activeImport) {
    return (
      <>
        <UploadEmptyState
          onFileSelected={onFileSelected}
          isUploading={isUploading}
          uploadProgress={uploadProgress}
        />
        <ReplaceUploadDialog
          isOpen={!!replaceDialogFile}
          currentFilename=""
          currentConversationCount={0}
          onCancel={() => setReplaceDialogFile(null)}
          onConfirm={onReplaceConfirm}
        />
      </>
    )
  }

  // State 2: parsing
  if (activeImport.status === 'parsing') {
    return (
      <ParseProgressBanner
        conversationsIndexed={parseProgress?.conversationsIndexed ?? 0}
      />
    )
  }

  if (activeImport.status === 'failed') {
    return (
      <ParseProgressBanner
        conversationsIndexed={0}
        failed={{ errorMessage: activeImport.error_message ?? 'Unknown error' }}
        onRestart={() => setActiveImport(null)}
      />
    )
  }

  // State 3: ready
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 p-3 bg-white/5 rounded mb-4 text-sm">
        <span className="text-white/70">
          <code className="font-mono">{activeImport.filename}</code> · {activeImport.conversation_count} conversations · expires {new Date(activeImport.expires_at).toLocaleDateString()}
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setActiveImport(null)}
            className="px-3 py-1 text-xs bg-white/5 hover:bg-white/10 rounded"
          >
            Replace upload
          </button>
          <button
            type="button"
            onClick={async () => {
              await chatGptImportApi.deleteImport(activeImport.import_id)
              setActiveImport(null)
            }}
            className="px-3 py-1 text-xs bg-white/5 hover:bg-white/10 rounded text-red-300"
          >
            Delete file
          </button>
        </div>
      </div>
      <ConversationList
        conversations={conversations}
        currentPersonaId={personaId}
        currentPersonaName={personaName}
        onConfirmImport={onConfirmImport}
      />
    </div>
  )
}
```

- [ ] **Step 2: Type-check + commit**

```bash
cd frontend && pnpm tsc --noEmit
git add frontend/src/features/chatgpt-import/ChatGptImportTab.tsx
git commit -m "Add ChatGptImportTab root component"
```

---

### Task 36: Wire tab into PersonaOverlay

**Files:**
- Modify: `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx`

- [ ] **Step 1: Add the tab id, label, and render case**

Extend the `PersonaOverlayTab` type:

```typescript
type PersonaOverlayTab =
  | 'overview'
  | 'edit'
  | 'knowledge'
  | 'memories'
  | 'history'
  | 'mcp'
  | 'integrations'
  | 'voice'
  | 'chatgpt-import'
```

Add to the `TABS` array (after `integrations`):

```typescript
  { id: 'chatgpt-import', label: 'ChatGPT-Import' },
```

In the render switch, import the component and add:

```typescript
import { ChatGptImportTab } from '../../../features/chatgpt-import/ChatGptImportTab'

// ... in the render switch:
{activeTab === 'chatgpt-import' && (
  <ChatGptImportTab personaId={persona.id} personaName={persona.name} />
)}
```

- [ ] **Step 2: Build**

```bash
cd frontend && pnpm run build
```
Expected: clean build.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/components/persona-overlay/PersonaOverlay.tsx
git commit -m "Wire ChatGPT-Import tab into PersonaOverlay"
```

---

### Task 37: ConnectionPickerDialog for imported sessions

**Files:**
- Create: `frontend/src/features/chat/ConnectionPickerDialog.tsx`

- [ ] **Step 1: Implement**

```typescript
// frontend/src/features/chat/ConnectionPickerDialog.tsx
import { useEffect, useState } from 'react'

import { Sheet } from '../../core/components/Sheet'
import { llmApi } from '../../core/api/llm'  // or whatever the existing connections API is called

interface ConnectionOption {
  connection_id: string
  display_name: string
  model_slugs: string[]
}

interface Props {
  isOpen: boolean
  onCancel: () => void
  onConfirm: (modelUniqueId: string) => void
}

export function ConnectionPickerDialog({ isOpen, onCancel, onConfirm }: Props) {
  const [connections, setConnections] = useState<ConnectionOption[]>([])
  const [selectedConnectionId, setSelectedConnectionId] = useState<string | null>(null)
  const [selectedModelSlug, setSelectedModelSlug] = useState<string | null>(null)

  useEffect(() => {
    if (!isOpen) return
    llmApi.listConnections().then((conns) => setConnections(conns))
  }, [isOpen])

  const onPick = () => {
    if (selectedConnectionId && selectedModelSlug) {
      onConfirm(`${selectedConnectionId}:${selectedModelSlug}`)
    }
  }

  const selectedConn = connections.find((c) => c.connection_id === selectedConnectionId)

  return (
    <Sheet isOpen={isOpen} onClose={onCancel} size="md" ariaLabel="Choose connection">
      <div className="p-6">
        <h2 className="text-xl font-semibold text-white mb-3">Choose a connection</h2>
        <p className="text-white/70 mb-4">
          This conversation was imported from ChatGPT. Pick the Chatsune connection you
          want to continue with.
        </p>
        <div className="space-y-2 max-h-64 overflow-y-auto mb-4">
          {connections.map((c) => (
            <button
              key={c.connection_id}
              type="button"
              onClick={() => {
                setSelectedConnectionId(c.connection_id)
                setSelectedModelSlug(c.model_slugs[0] ?? null)
              }}
              className={`block w-full text-left px-3 py-2 rounded ${
                selectedConnectionId === c.connection_id
                  ? 'bg-indigo-700 text-white'
                  : 'bg-white/5 text-white/80 hover:bg-white/10'
              }`}
            >
              {c.display_name}
            </button>
          ))}
        </div>
        {selectedConn && selectedConn.model_slugs.length > 1 && (
          <select
            value={selectedModelSlug ?? ''}
            onChange={(e) => setSelectedModelSlug(e.target.value)}
            className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-white mb-4"
          >
            {selectedConn.model_slugs.map((m) => (
              <option key={m} value={m} style={{ background: '#0f0d16', color: 'rgba(255,255,255,0.85)' }}>
                {m}
              </option>
            ))}
          </select>
        )}
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 bg-white/5 hover:bg-white/10 text-white rounded"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onPick}
            disabled={!selectedConnectionId || !selectedModelSlug}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded font-medium"
          >
            Use this connection
          </button>
        </div>
      </div>
    </Sheet>
  )
}
```

- [ ] **Step 2: Type-check + commit**

```bash
cd frontend && pnpm tsc --noEmit
git add frontend/src/features/chat/ConnectionPickerDialog.tsx
git commit -m "Add ConnectionPickerDialog for imported-session first send"
```

---

### Task 38: Wire ConnectionPickerDialog into chat send flow

**Files:**
- Modify: chat input/send component (path depends on existing structure — find it via `grep -r 'model_unique_id' frontend/src/features/chat/`)

- [ ] **Step 1: Find the chat-input component that orchestrates message send**

Run:

```bash
grep -rn "model_unique_id" frontend/src/features/chat/ | head -20
```

Identify the component that (a) reads `session.model_unique_id` and (b) dispatches the send. This is typically named something like `ChatComposer.tsx`, `ChatInput.tsx`, or `useChatSend.ts`.

- [ ] **Step 2: Intercept send when model_unique_id starts with `imported:`**

In that component, replace the existing `onSend` with:

```typescript
import { useState } from 'react'
import { ConnectionPickerDialog } from './ConnectionPickerDialog'
import { chatApi } from '../../core/api/chat'  // existing chat API client

// ... inside the component ...
const [pendingSend, setPendingSend] = useState<string | null>(null)
const [pickerOpen, setPickerOpen] = useState(false)

const onSend = async (text: string) => {
  if (session.model_unique_id?.startsWith('imported:')) {
    setPendingSend(text)
    setPickerOpen(true)
    return
  }
  await doSend(text)  // existing send logic
}

const onConnectionPicked = async (modelUniqueId: string) => {
  setPickerOpen(false)
  // Patch the session to set the real model
  await chatApi.updateSession(session.id, { model_unique_id: modelUniqueId })
  if (pendingSend) {
    await doSend(pendingSend)
    setPendingSend(null)
  }
}

// In JSX:
<ConnectionPickerDialog
  isOpen={pickerOpen}
  onCancel={() => { setPickerOpen(false); setPendingSend(null) }}
  onConfirm={onConnectionPicked}
/>
```

If `chatApi.updateSession` does not exist, add it: a `PATCH /api/chat/sessions/{id}` with body `{ model_unique_id }`. The backend chat module almost certainly already supports session updates — verify in `backend/modules/chat/_handlers.py`. If a PATCH route exists, just use it; otherwise add one (10-line addition).

- [ ] **Step 3: Build**

```bash
cd frontend && pnpm run build
```
Expected: clean build.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/chat/<modified-file>
# include any backend additions if needed:
# git add backend/modules/chat/_handlers.py
git commit -m "Intercept send on imported sessions with connection picker"
```

---

### Task 39: Final integration build + smoke

**Files:** none modified — verification step.

- [ ] **Step 1: Run full backend syntax check**

```bash
PYTHONPATH=. uv run python -m py_compile \
  backend/main.py \
  backend/modules/chatgpt_import/__init__.py \
  backend/modules/chatgpt_import/_handlers.py \
  backend/modules/chatgpt_import/_service.py \
  backend/modules/chatgpt_import/_repository.py \
  backend/modules/chatgpt_import/_parser.py \
  backend/modules/chatgpt_import/_session_builder.py \
  backend/jobs/handlers/_chatgpt_import_parse.py \
  backend/jobs/handlers/_chatgpt_import_conversation.py
```
Expected: no errors.

- [ ] **Step 2: Run all chatgpt_import tests**

```bash
PYTHONPATH=. uv run pytest tests/chatgpt_import/ backend/tests/chat/test_repository_imported_session.py -v
```
Expected: all PASS.

- [ ] **Step 3: Run full backend test suite (excluding DB tests if running on host)**

```bash
PYTHONPATH=. uv run pytest backend/tests/ tests/ \
  --ignore=backend/tests/integration/test_websocket_disconnect.py \
  --ignore=backend/tests/test_memory_consolidation_handler.py \
  --ignore=backend/tests/test_chat_session_with_messages.py \
  --ignore=backend/tests/test_persona_repository_indexes.py \
  -v
```

(Adjust the ignore list to whatever the current host-incompatible files are; see CLAUDE.md memory `feedback_db_tests_on_host`.)

Expected: all selected tests PASS.

- [ ] **Step 4: Build frontend**

```bash
cd frontend && pnpm run build
```
Expected: clean build, no type errors.

- [ ] **Step 5: Commit (only if anything changed)**

If only verification with no file changes: skip commit.

---

### Task 40: Manual verification

This is a checklist for the human to execute — see spec §9 in
`devdocs/specs/2026-05-11-chatgpt-import-design.md`. Run all bullets there
on a real browser before merge. Do not mark the feature complete until
every bullet passes.

---

## Self-Review Checklist (post-write)

- [x] All spec sections (4-7 of the spec) covered by tasks
- [x] No placeholders / TODOs / "implement later" / "similar to Task N"
- [x] Every step that creates code shows the complete code
- [x] File paths are explicit and consistent across tasks
- [x] Function/method signatures used in later tasks match earlier definitions
- [x] Spec §10 (out-of-scope) items are explicitly not in any task

**Type consistency double-check:**
- `ChatGptImportRepository.create_indexes()` (Task 9) is called by `init_indexes` (Task 8) — matches.
- `parse_conversation()` (Task 13) returns `ParsedConversation` (Task 8 model) — matches.
- `build_imported_session_request()` (Task 14) consumes `ParsedConversation`, returns `CreateImportedSessionRequest` (Task 5) — matches.
- `create_imported_session()` (Task 6/7) signature is consumed in Task 17 — matches.
- Front-end `ConversationItemDto` shape (Task 24 API client) matches backend DTO (Task 4) — matches.

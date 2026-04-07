# Artefact System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a session-scoped artefact system where LLMs create/update artefacts via tool calls, and users view/edit them through a right-side rail/sidebar with an overlay viewer.

**Architecture:** New backend module `backend/modules/artefact/` with MongoDB storage, four LLM tools registered in the existing tool system, events via the event bus. Frontend adds a rail/sidebar to ChatView, an overlay for viewing/editing, and inline cards in the message stream.

**Tech Stack:** Python/FastAPI, MongoDB, Pydantic v2, React/TSX, Zustand, Shiki, ReactMarkdown, Mermaid, Babel (for JSX preview)

**Spec:** `docs/superpowers/specs/2026-04-06-artefact-system-design.md`

**Security note:** Shiki's `codeToHtml` produces syntax-highlighted HTML from code the user/LLM authored within the app. The HTML/JSX/SVG preview renderers use sandboxed iframes which isolate untrusted content from the parent page. `dangerouslySetInnerHTML` is used only for Shiki output (trusted syntax-highlight markup) and Mermaid SVG output (library-generated). User-authored HTML/JSX content is always rendered inside sandboxed iframes, never injected into the parent DOM.

---

## File Structure

### Backend — New Files

| File | Responsibility |
|------|----------------|
| `backend/modules/artefact/__init__.py` | Public API: router, init_indexes, service functions |
| `backend/modules/artefact/_repository.py` | MongoDB CRUD for `artefacts` and `artefact_versions` collections |
| `backend/modules/artefact/_models.py` | Internal Pydantic models for DB documents |
| `backend/modules/artefact/_handlers.py` | FastAPI REST endpoints for user actions |
| `shared/dtos/artefact.py` | ArtefactSummaryDto, ArtefactDetailDto |
| `shared/events/artefact.py` | All artefact event models |

### Backend — Modified Files

| File | Change |
|------|--------|
| `shared/topics.py` | Add ARTEFACT_* topic constants |
| `backend/modules/tools/_registry.py` | Register artefact tool group |
| `backend/modules/tools/_executors.py` | Add ArtefactToolExecutor class |
| `backend/modules/chat/__init__.py` | Inject session_id into artefact tool args |
| `backend/main.py` | Mount artefact router, call init_indexes |

### Frontend — New Files

| File | Responsibility |
|------|----------------|
| `frontend/src/core/types/artefact.ts` | TypeScript types for artefacts |
| `frontend/src/core/api/artefact.ts` | REST API client for artefact endpoints |
| `frontend/src/core/store/artefactStore.ts` | Zustand store for artefact state |
| `frontend/src/features/artefact/useArtefactEvents.ts` | Event bus subscription hook |
| `frontend/src/features/artefact/ArtefactRail.tsx` | Collapsed rail (40px) with count badge |
| `frontend/src/features/artefact/ArtefactSidebar.tsx` | Expanded sidebar (~280px) with artefact list |
| `frontend/src/features/artefact/ArtefactOverlay.tsx` | Full artefact viewer/editor overlay |
| `frontend/src/features/artefact/ArtefactCard.tsx` | Inline card for chat stream |
| `frontend/src/features/artefact/ArtefactPreview.tsx` | Per-type preview renderers |

### Frontend — Modified Files

| File | Change |
|------|--------|
| `frontend/src/core/types/events.ts` | Add ARTEFACT_* topic constants |
| `frontend/src/features/chat/ChatView.tsx` | Integrate rail/sidebar to right of chat |
| `frontend/src/features/chat/MessageList.tsx` | Render ArtefactCard for artefact tool calls |
| `frontend/src/features/chat/ToolCallActivity.tsx` | Add artefact tool labels |
| `frontend/package.json` | Add mermaid dependency |

---

## Task 1: Shared Contracts (DTOs, Events, Topics)

**Files:**
- Create: `shared/dtos/artefact.py`
- Create: `shared/events/artefact.py`
- Modify: `shared/topics.py`

- [ ] **Step 1: Create artefact DTOs**

```python
# shared/dtos/artefact.py
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

ArtefactType = Literal["markdown", "code", "html", "svg", "jsx", "mermaid"]


class ArtefactSummaryDto(BaseModel):
    id: str
    session_id: str
    handle: str
    title: str
    type: ArtefactType
    language: str | None = None
    size_bytes: int
    version: int
    created_at: datetime
    updated_at: datetime


class ArtefactDetailDto(ArtefactSummaryDto):
    content: str
```

- [ ] **Step 2: Create artefact events**

```python
# shared/events/artefact.py
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ArtefactCreatedEvent(BaseModel):
    type: str = "artefact.created"
    session_id: str
    handle: str
    title: str
    artefact_type: str
    language: str | None = None
    size_bytes: int
    correlation_id: str
    timestamp: datetime


class ArtefactUpdatedEvent(BaseModel):
    type: str = "artefact.updated"
    session_id: str
    handle: str
    title: str
    artefact_type: str
    size_bytes: int
    version: int
    correlation_id: str
    timestamp: datetime


class ArtefactDeletedEvent(BaseModel):
    type: str = "artefact.deleted"
    session_id: str
    handle: str
    correlation_id: str
    timestamp: datetime


class ArtefactUndoEvent(BaseModel):
    type: str = "artefact.undo"
    session_id: str
    handle: str
    version: int
    correlation_id: str
    timestamp: datetime


class ArtefactRedoEvent(BaseModel):
    type: str = "artefact.redo"
    session_id: str
    handle: str
    version: int
    correlation_id: str
    timestamp: datetime
```

- [ ] **Step 3: Add topic constants to `shared/topics.py`**

Add after the `KNOWLEDGE_SEARCH_COMPLETED` line (line 88):

```python
    # Artefacts
    ARTEFACT_CREATED = "artefact.created"
    ARTEFACT_UPDATED = "artefact.updated"
    ARTEFACT_DELETED = "artefact.deleted"
    ARTEFACT_UNDO = "artefact.undo"
    ARTEFACT_REDO = "artefact.redo"
```

- [ ] **Step 4: Verify syntax**

Run: `uv run python -m py_compile shared/dtos/artefact.py && uv run python -m py_compile shared/events/artefact.py && uv run python -m py_compile shared/topics.py`
Expected: no output (success)

- [ ] **Step 5: Commit**

```bash
git add shared/dtos/artefact.py shared/events/artefact.py shared/topics.py
git commit -m "Add shared contracts for artefact system (DTOs, events, topics)"
```

---

## Task 2: Backend Artefact Module — Repository & Models

**Files:**
- Create: `backend/modules/artefact/_models.py`
- Create: `backend/modules/artefact/_repository.py`

- [ ] **Step 1: Create internal models**

```python
# backend/modules/artefact/_models.py
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ArtefactType = Literal["markdown", "code", "html", "svg", "jsx", "mermaid"]


class ArtefactDocument(BaseModel):
    """MongoDB document for an artefact."""
    session_id: str
    user_id: str
    handle: str
    title: str
    type: ArtefactType
    language: str | None = None
    content: str
    size_bytes: int
    version: int = 1
    max_version: int = 1  # highest version ever stored (for redo boundary)
    created_at: datetime = Field(default_factory=lambda: datetime.now())
    updated_at: datetime = Field(default_factory=lambda: datetime.now())


class ArtefactVersionDocument(BaseModel):
    """MongoDB document for an artefact version (undo/redo stack)."""
    artefact_id: str
    version: int
    content: str
    title: str
    created_at: datetime = Field(default_factory=lambda: datetime.now())
```

- [ ] **Step 2: Create repository**

```python
# backend/modules/artefact/_repository.py
"""MongoDB repository for artefacts and artefact versions."""

import logging
from datetime import datetime, timezone

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

_log = logging.getLogger(__name__)

_MAX_VERSIONS = 20


class ArtefactRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self._artefacts = db["artefacts"]
        self._versions = db["artefact_versions"]

    async def create_indexes(self) -> None:
        await self._artefacts.create_index(
            [("session_id", 1), ("handle", 1)], unique=True,
        )
        await self._artefacts.create_index("session_id")
        await self._versions.create_index("artefact_id")

    # --- CRUD ---

    async def create(self, doc: dict) -> dict:
        result = await self._artefacts.insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc

    async def get_by_handle(self, session_id: str, handle: str) -> dict | None:
        return await self._artefacts.find_one(
            {"session_id": session_id, "handle": handle},
        )

    async def get_by_id(self, artefact_id: str) -> dict | None:
        return await self._artefacts.find_one({"_id": ObjectId(artefact_id)})

    async def list_by_session(self, session_id: str) -> list[dict]:
        cursor = self._artefacts.find(
            {"session_id": session_id},
        ).sort("created_at", 1)
        return await cursor.to_list(length=200)

    async def update_content(
        self,
        artefact_id: str,
        content: str,
        title: str | None,
        new_version: int,
        max_version: int,
    ) -> dict | None:
        update: dict = {
            "$set": {
                "content": content,
                "size_bytes": len(content.encode("utf-8")),
                "version": new_version,
                "max_version": max_version,
                "updated_at": datetime.now(timezone.utc),
            },
        }
        if title is not None:
            update["$set"]["title"] = title
        return await self._artefacts.find_one_and_update(
            {"_id": ObjectId(artefact_id)},
            update,
            return_document=True,
        )

    async def rename(self, artefact_id: str, title: str) -> dict | None:
        return await self._artefacts.find_one_and_update(
            {"_id": ObjectId(artefact_id)},
            {"$set": {"title": title, "updated_at": datetime.now(timezone.utc)}},
            return_document=True,
        )

    async def delete(self, artefact_id: str) -> bool:
        result = await self._artefacts.delete_one({"_id": ObjectId(artefact_id)})
        if result.deleted_count:
            await self._versions.delete_many({"artefact_id": artefact_id})
        return result.deleted_count > 0

    # --- Version stack ---

    async def save_version(self, artefact_id: str, version: int, content: str, title: str) -> None:
        await self._versions.insert_one({
            "artefact_id": artefact_id,
            "version": version,
            "content": content,
            "title": title,
            "created_at": datetime.now(timezone.utc),
        })
        # Prune old versions beyond the limit
        count = await self._versions.count_documents({"artefact_id": artefact_id})
        if count > _MAX_VERSIONS:
            oldest = await self._versions.find(
                {"artefact_id": artefact_id},
            ).sort("version", 1).limit(count - _MAX_VERSIONS).to_list(length=count)
            if oldest:
                ids = [d["_id"] for d in oldest]
                await self._versions.delete_many({"_id": {"$in": ids}})

    async def get_version(self, artefact_id: str, version: int) -> dict | None:
        return await self._versions.find_one(
            {"artefact_id": artefact_id, "version": version},
        )

    async def delete_versions_above(self, artefact_id: str, version: int) -> None:
        await self._versions.delete_many(
            {"artefact_id": artefact_id, "version": {"$gt": version}},
        )

    async def set_version_pointer(self, artefact_id: str, version: int, max_version: int) -> dict | None:
        """Restore artefact to a specific version from the version stack."""
        ver_doc = await self.get_version(artefact_id, version)
        if not ver_doc:
            return None
        return await self._artefacts.find_one_and_update(
            {"_id": ObjectId(artefact_id)},
            {"$set": {
                "content": ver_doc["content"],
                "title": ver_doc.get("title", ""),
                "size_bytes": len(ver_doc["content"].encode("utf-8")),
                "version": version,
                "max_version": max_version,
                "updated_at": datetime.now(timezone.utc),
            }},
            return_document=True,
        )
```

- [ ] **Step 3: Verify syntax**

Run: `uv run python -m py_compile backend/modules/artefact/_models.py && uv run python -m py_compile backend/modules/artefact/_repository.py`
Expected: no output (success)

Note: Create an empty `backend/modules/artefact/__init__.py` first so the package is importable.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/artefact/
git commit -m "Add artefact module repository and models"
```

---

## Task 3: Backend Artefact Module — Public API & REST Handlers

**Files:**
- Create: `backend/modules/artefact/_handlers.py`
- Create: `backend/modules/artefact/__init__.py` (full version)

- [ ] **Step 1: Create REST handlers**

```python
# backend/modules/artefact/_handlers.py
"""REST endpoints for user artefact actions (not LLM tool calls)."""

import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.database import get_db
from backend.modules.artefact._repository import ArtefactRepository
from backend.modules.user import require_user
from backend.ws.event_bus import get_event_bus
from shared.dtos.artefact import ArtefactDetailDto, ArtefactSummaryDto
from shared.events.artefact import (
    ArtefactDeletedEvent,
    ArtefactRedoEvent,
    ArtefactUndoEvent,
    ArtefactUpdatedEvent,
)
from shared.topics import Topics

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat/sessions/{session_id}/artefacts", tags=["artefacts"])


def _repo() -> ArtefactRepository:
    return ArtefactRepository(get_db())


def _to_summary(doc: dict) -> ArtefactSummaryDto:
    return ArtefactSummaryDto(
        id=str(doc["_id"]),
        session_id=doc["session_id"],
        handle=doc["handle"],
        title=doc["title"],
        type=doc["type"],
        language=doc.get("language"),
        size_bytes=doc["size_bytes"],
        version=doc["version"],
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


def _to_detail(doc: dict) -> ArtefactDetailDto:
    return ArtefactDetailDto(
        id=str(doc["_id"]),
        session_id=doc["session_id"],
        handle=doc["handle"],
        title=doc["title"],
        type=doc["type"],
        language=doc.get("language"),
        size_bytes=doc["size_bytes"],
        version=doc["version"],
        content=doc["content"],
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


@router.get("/")
async def list_artefacts(session_id: str, user=require_user) -> list[ArtefactSummaryDto]:
    docs = await _repo().list_by_session(session_id)
    return [_to_summary(d) for d in docs if d["user_id"] == user["_id"]]


@router.get("/{artefact_id}")
async def get_artefact(session_id: str, artefact_id: str, user=require_user) -> ArtefactDetailDto:
    doc = await _repo().get_by_id(artefact_id)
    if not doc or doc["session_id"] != session_id or doc["user_id"] != user["_id"]:
        raise HTTPException(404, "Artefact not found")
    return _to_detail(doc)


class PatchArtefactRequest(BaseModel):
    title: str | None = None
    content: str | None = None


@router.patch("/{artefact_id}")
async def patch_artefact(
    session_id: str, artefact_id: str, body: PatchArtefactRequest, user=require_user,
) -> ArtefactDetailDto:
    repo = _repo()
    doc = await repo.get_by_id(artefact_id)
    if not doc or doc["session_id"] != session_id or doc["user_id"] != user["_id"]:
        raise HTTPException(404, "Artefact not found")

    if body.content is not None:
        # Save current state as version for undo
        await repo.save_version(
            artefact_id, doc["version"], doc["content"], doc["title"],
        )
        # Clear redo history
        new_version = doc["version"] + 1
        await repo.delete_versions_above(artefact_id, doc["version"])
        updated = await repo.update_content(
            artefact_id, body.content, body.title, new_version, new_version,
        )
    elif body.title is not None:
        updated = await repo.rename(artefact_id, body.title)
    else:
        raise HTTPException(400, "Nothing to update")

    if not updated:
        raise HTTPException(500, "Update failed")

    # Publish event
    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.ARTEFACT_UPDATED,
        ArtefactUpdatedEvent(
            session_id=session_id,
            handle=updated["handle"],
            title=updated["title"],
            artefact_type=updated["type"],
            size_bytes=updated["size_bytes"],
            version=updated["version"],
            correlation_id=str(uuid4()),
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user["_id"]],
    )
    return _to_detail(updated)


@router.delete("/{artefact_id}", status_code=204)
async def delete_artefact(session_id: str, artefact_id: str, user=require_user) -> None:
    repo = _repo()
    doc = await repo.get_by_id(artefact_id)
    if not doc or doc["session_id"] != session_id or doc["user_id"] != user["_id"]:
        raise HTTPException(404, "Artefact not found")
    await repo.delete(artefact_id)

    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.ARTEFACT_DELETED,
        ArtefactDeletedEvent(
            session_id=session_id,
            handle=doc["handle"],
            correlation_id=str(uuid4()),
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user["_id"]],
    )


@router.post("/{artefact_id}/undo")
async def undo_artefact(session_id: str, artefact_id: str, user=require_user) -> ArtefactDetailDto:
    repo = _repo()
    doc = await repo.get_by_id(artefact_id)
    if not doc or doc["session_id"] != session_id or doc["user_id"] != user["_id"]:
        raise HTTPException(404, "Artefact not found")
    if doc["version"] <= 1:
        raise HTTPException(400, "Nothing to undo")

    # Save current state so redo can restore it
    await repo.save_version(
        artefact_id, doc["version"], doc["content"], doc["title"],
    )
    target_version = doc["version"] - 1
    updated = await repo.set_version_pointer(artefact_id, target_version, doc["max_version"])
    if not updated:
        raise HTTPException(400, "Version not found")

    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.ARTEFACT_UNDO,
        ArtefactUndoEvent(
            session_id=session_id,
            handle=updated["handle"],
            version=updated["version"],
            correlation_id=str(uuid4()),
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user["_id"]],
    )
    return _to_detail(updated)


@router.post("/{artefact_id}/redo")
async def redo_artefact(session_id: str, artefact_id: str, user=require_user) -> ArtefactDetailDto:
    repo = _repo()
    doc = await repo.get_by_id(artefact_id)
    if not doc or doc["session_id"] != session_id or doc["user_id"] != user["_id"]:
        raise HTTPException(404, "Artefact not found")
    if doc["version"] >= doc["max_version"]:
        raise HTTPException(400, "Nothing to redo")

    # Save current state
    await repo.save_version(
        artefact_id, doc["version"], doc["content"], doc["title"],
    )
    target_version = doc["version"] + 1
    updated = await repo.set_version_pointer(artefact_id, target_version, doc["max_version"])
    if not updated:
        raise HTTPException(400, "Version not found")

    event_bus = get_event_bus()
    await event_bus.publish(
        Topics.ARTEFACT_REDO,
        ArtefactRedoEvent(
            session_id=session_id,
            handle=updated["handle"],
            version=updated["version"],
            correlation_id=str(uuid4()),
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user["_id"]],
    )
    return _to_detail(updated)
```

- [ ] **Step 2: Create module public API**

```python
# backend/modules/artefact/__init__.py
"""Artefact module — session-scoped artefact storage with undo/redo.

Public API: import only from this file.
"""

from backend.modules.artefact._handlers import router
from backend.modules.artefact._repository import ArtefactRepository


async def init_indexes(db) -> None:
    await ArtefactRepository(db).create_indexes()


__all__ = ["router", "init_indexes"]
```

- [ ] **Step 3: Mount in main.py**

Modify `backend/main.py`:

Add import after the knowledge import (around line 20-23):
```python
from backend.modules.artefact import router as artefact_router, init_indexes as artefact_init_indexes
```

Add `await artefact_init_indexes(db)` after `await knowledge_init_indexes(db)` (after line 45).

Add `app.include_router(artefact_router)` after `app.include_router(knowledge_router)` (after line 330).

- [ ] **Step 4: Verify syntax**

Run: `uv run python -m py_compile backend/modules/artefact/_handlers.py && uv run python -m py_compile backend/modules/artefact/__init__.py && uv run python -m py_compile backend/main.py`
Expected: no output (success)

- [ ] **Step 5: Commit**

```bash
git add backend/modules/artefact/ backend/main.py
git commit -m "Add artefact REST handlers and mount in main app"
```

---

## Task 4: Backend — Tool Executor & Registration

**Files:**
- Modify: `backend/modules/tools/_executors.py`
- Modify: `backend/modules/tools/_registry.py`
- Modify: `backend/modules/chat/__init__.py`

- [ ] **Step 1: Add ArtefactToolExecutor to `_executors.py`**

Append after the `KnowledgeSearchExecutor` class (after line 115):

```python
class ArtefactToolExecutor:
    """Dispatches artefact tool calls to the artefact module."""

    async def execute(self, user_id: str, tool_name: str, arguments: dict) -> str:
        import re
        from datetime import datetime, timezone
        from uuid import uuid4

        from backend.database import get_db
        from backend.modules.artefact._repository import ArtefactRepository
        from backend.ws.event_bus import get_event_bus
        from shared.events.artefact import ArtefactCreatedEvent, ArtefactUpdatedEvent
        from shared.topics import Topics

        repo = ArtefactRepository(get_db())
        event_bus = get_event_bus()

        # session_id and correlation_id are injected by _make_tool_executor in chat module
        session_id = arguments.pop("_session_id", "")
        correlation_id = arguments.pop("_correlation_id", str(uuid4()))

        if tool_name == "create_artefact":
            handle = arguments.get("handle", "")
            title = arguments.get("title", "")
            artefact_type = arguments.get("type", "code")
            content = arguments.get("content", "")
            language = arguments.get("language")

            # Validate handle
            if not handle or not re.match(r"^[a-z0-9][a-z0-9-]*$", handle) or len(handle) > 64:
                return json.dumps({"error": "Invalid handle. Use lowercase alphanumeric + hyphens, max 64 chars."})

            # Check for duplicate
            existing = await repo.get_by_handle(session_id, handle)
            if existing:
                return json.dumps({"error": f"Handle '{handle}' already exists in this session. Choose a different handle."})

            doc = await repo.create({
                "session_id": session_id,
                "user_id": user_id,
                "handle": handle,
                "title": title,
                "type": artefact_type,
                "language": language,
                "content": content,
                "size_bytes": len(content.encode("utf-8")),
                "version": 1,
                "max_version": 1,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            })

            await event_bus.publish(
                Topics.ARTEFACT_CREATED,
                ArtefactCreatedEvent(
                    session_id=session_id,
                    handle=handle,
                    title=title,
                    artefact_type=artefact_type,
                    language=language,
                    size_bytes=len(content.encode("utf-8")),
                    correlation_id=correlation_id,
                    timestamp=datetime.now(timezone.utc),
                ),
                scope=f"session:{session_id}",
                target_user_ids=[user_id],
                correlation_id=correlation_id,
            )

            return json.dumps({"status": "created", "handle": handle})

        if tool_name == "update_artefact":
            handle = arguments.get("handle", "")
            content = arguments.get("content", "")
            title = arguments.get("title")

            doc = await repo.get_by_handle(session_id, handle)
            if not doc:
                return json.dumps({"error": f"No artefact with handle '{handle}' found."})

            artefact_id = str(doc["_id"])

            # Save current as version
            await repo.save_version(artefact_id, doc["version"], doc["content"], doc["title"])
            # Clear redo history
            await repo.delete_versions_above(artefact_id, doc["version"])

            new_version = doc["version"] + 1
            updated = await repo.update_content(artefact_id, content, title, new_version, new_version)

            await event_bus.publish(
                Topics.ARTEFACT_UPDATED,
                ArtefactUpdatedEvent(
                    session_id=session_id,
                    handle=handle,
                    title=updated["title"],
                    artefact_type=updated["type"],
                    size_bytes=updated["size_bytes"],
                    version=new_version,
                    correlation_id=correlation_id,
                    timestamp=datetime.now(timezone.utc),
                ),
                scope=f"session:{session_id}",
                target_user_ids=[user_id],
                correlation_id=correlation_id,
            )

            return json.dumps({"status": "updated", "handle": handle, "version": new_version})

        if tool_name == "read_artefact":
            handle = arguments.get("handle", "")
            doc = await repo.get_by_handle(session_id, handle)
            if not doc:
                return json.dumps({"error": f"No artefact with handle '{handle}' found."})
            return json.dumps({
                "handle": handle,
                "title": doc["title"],
                "type": doc["type"],
                "language": doc.get("language"),
                "version": doc["version"],
                "size_bytes": doc["size_bytes"],
                "content": doc["content"],
            }, ensure_ascii=False)

        if tool_name == "list_artefacts":
            docs = await repo.list_by_session(session_id)
            items = [
                {
                    "handle": d["handle"],
                    "title": d["title"],
                    "type": d["type"],
                    "language": d.get("language"),
                    "size_bytes": d["size_bytes"],
                    "version": d["version"],
                }
                for d in docs
                if d["user_id"] == user_id
            ]
            return json.dumps({"artefacts": items}, ensure_ascii=False)

        return json.dumps({"error": f"Unknown artefact tool: {tool_name}"})
```

- [ ] **Step 2: Register artefact tool group in `_registry.py`**

In the `_build_groups()` function, update the import on line 34 to:
```python
    from backend.modules.tools._executors import ArtefactToolExecutor, KnowledgeSearchExecutor, WebSearchExecutor
```

After the `knowledge_search` group definition (before the closing `}` of the return dict, after line 77), add the `"artefacts"` group with four `ToolDefinition` entries:

- `create_artefact`: params `handle` (string, required), `title` (string, required), `type` (string enum, required), `content` (string, required), `language` (string, optional)
- `update_artefact`: params `handle` (string, required), `content` (string, required), `title` (string, optional)
- `read_artefact`: params `handle` (string, required)
- `list_artefacts`: no required params

The group should be `toggleable=True`, `side="server"`, executor `ArtefactToolExecutor()`.

Tool descriptions should guide the LLM:
- `create_artefact`: "Create a new artefact. Use this to produce code files, documents, diagrams, or web pages that the user can view, edit, and download."
- `update_artefact`: "Update an existing artefact's content. The user can undo this change."
- `read_artefact`: "Read the full content of an artefact. Use this to review an artefact before updating it."
- `list_artefacts`: "List all artefacts in the current session. Returns handles, titles, types, and sizes."

- [ ] **Step 3: Inject session_id and correlation_id into artefact tool args**

In `backend/modules/chat/__init__.py`, modify `_make_tool_executor` (around line 66-85).

Change the signature to accept `correlation_id`:
```python
def _make_tool_executor(session: dict, persona: dict | None, correlation_id: str):
```

Inside the inner `_executor`, after the `knowledge_search` block (after line 81), add:

```python
        artefact_tools = {"create_artefact", "update_artefact", "read_artefact", "list_artefacts"}
        if tool_name in artefact_tools:
            args = _json.loads(arguments_json)
            args["_session_id"] = session.get("_id", "")
            args["_correlation_id"] = correlation_id
            arguments_json = _json.dumps(args)
```

Then find where `_make_tool_executor(session, persona)` is called in `_run_inference` and add the `correlation_id` argument: `_make_tool_executor(session, persona, correlation_id)`.

- [ ] **Step 4: Verify syntax**

Run: `uv run python -m py_compile backend/modules/tools/_executors.py && uv run python -m py_compile backend/modules/tools/_registry.py && uv run python -m py_compile backend/modules/chat/__init__.py`
Expected: no output (success)

- [ ] **Step 5: Commit**

```bash
git add backend/modules/tools/_executors.py backend/modules/tools/_registry.py backend/modules/chat/__init__.py
git commit -m "Register artefact tools and executor in tool system"
```

---

## Task 5: Frontend — Types, API Client, Store

**Files:**
- Create: `frontend/src/core/types/artefact.ts`
- Create: `frontend/src/core/api/artefact.ts`
- Create: `frontend/src/core/store/artefactStore.ts`
- Modify: `frontend/src/core/types/events.ts`

- [ ] **Step 1: Create TypeScript types**

```typescript
// frontend/src/core/types/artefact.ts
export type ArtefactType = 'markdown' | 'code' | 'html' | 'svg' | 'jsx' | 'mermaid'

export interface ArtefactSummary {
  id: string
  session_id: string
  handle: string
  title: string
  type: ArtefactType
  language: string | null
  size_bytes: number
  version: number
  created_at: string
  updated_at: string
}

export interface ArtefactDetail extends ArtefactSummary {
  content: string
}
```

- [ ] **Step 2: Create API client**

```typescript
// frontend/src/core/api/artefact.ts
import type { ArtefactDetail, ArtefactSummary } from '../types/artefact'

const BASE = '/api/chat/sessions'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  if (res.status === 204) return undefined as T
  return res.json()
}

export const artefactApi = {
  list: (sessionId: string) =>
    request<ArtefactSummary[]>(`${BASE}/${sessionId}/artefacts/`),

  get: (sessionId: string, artefactId: string) =>
    request<ArtefactDetail>(`${BASE}/${sessionId}/artefacts/${artefactId}`),

  patch: (sessionId: string, artefactId: string, body: { title?: string; content?: string }) =>
    request<ArtefactDetail>(`${BASE}/${sessionId}/artefacts/${artefactId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  delete: (sessionId: string, artefactId: string) =>
    request<void>(`${BASE}/${sessionId}/artefacts/${artefactId}`, { method: 'DELETE' }),

  undo: (sessionId: string, artefactId: string) =>
    request<ArtefactDetail>(`${BASE}/${sessionId}/artefacts/${artefactId}/undo`, { method: 'POST' }),

  redo: (sessionId: string, artefactId: string) =>
    request<ArtefactDetail>(`${BASE}/${sessionId}/artefacts/${artefactId}/redo`, { method: 'POST' }),
}
```

- [ ] **Step 3: Create Zustand store**

```typescript
// frontend/src/core/store/artefactStore.ts
import { create } from 'zustand'
import type { ArtefactSummary, ArtefactDetail } from '../types/artefact'

interface ArtefactState {
  artefacts: ArtefactSummary[]
  sidebarOpen: boolean
  activeArtefact: ArtefactDetail | null
  activeArtefactLoading: boolean

  setArtefacts: (artefacts: ArtefactSummary[]) => void
  addArtefact: (artefact: ArtefactSummary) => void
  updateArtefact: (handle: string, updates: Partial<ArtefactSummary>) => void
  removeArtefact: (handle: string) => void
  toggleSidebar: () => void
  setSidebarOpen: (open: boolean) => void
  openOverlay: (detail: ArtefactDetail) => void
  closeOverlay: () => void
  setActiveArtefact: (detail: ArtefactDetail | null) => void
  setActiveArtefactLoading: (loading: boolean) => void
  reset: () => void
}

export const useArtefactStore = create<ArtefactState>((set) => ({
  artefacts: [],
  sidebarOpen: false,
  activeArtefact: null,
  activeArtefactLoading: false,

  setArtefacts: (artefacts) => set({ artefacts }),
  addArtefact: (artefact) =>
    set((s) => ({ artefacts: [...s.artefacts, artefact] })),
  updateArtefact: (handle, updates) =>
    set((s) => ({
      artefacts: s.artefacts.map((a) =>
        a.handle === handle ? { ...a, ...updates } : a,
      ),
    })),
  removeArtefact: (handle) =>
    set((s) => ({
      artefacts: s.artefacts.filter((a) => a.handle !== handle),
      activeArtefact:
        s.activeArtefact?.handle === handle ? null : s.activeArtefact,
    })),
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  openOverlay: (detail) => set({ activeArtefact: detail, activeArtefactLoading: false }),
  closeOverlay: () => set({ activeArtefact: null }),
  setActiveArtefact: (detail) => set({ activeArtefact: detail }),
  setActiveArtefactLoading: (loading) => set({ activeArtefactLoading: loading }),
  reset: () =>
    set({
      artefacts: [],
      sidebarOpen: false,
      activeArtefact: null,
      activeArtefactLoading: false,
    }),
}))
```

- [ ] **Step 4: Add topic constants to `frontend/src/core/types/events.ts`**

Add after `KNOWLEDGE_SEARCH_COMPLETED` (line 83):

```typescript
  ARTEFACT_CREATED: "artefact.created",
  ARTEFACT_UPDATED: "artefact.updated",
  ARTEFACT_DELETED: "artefact.deleted",
  ARTEFACT_UNDO: "artefact.undo",
  ARTEFACT_REDO: "artefact.redo",
```

- [ ] **Step 5: Verify build**

Run: `cd frontend && pnpm tsc --noEmit 2>&1 | grep -E "artefact|Artefact" | head -10`
Expected: no errors related to artefact files

- [ ] **Step 6: Commit**

```bash
git add frontend/src/core/types/artefact.ts frontend/src/core/api/artefact.ts frontend/src/core/store/artefactStore.ts frontend/src/core/types/events.ts
git commit -m "Add frontend artefact types, API client, and Zustand store"
```

---

## Task 6: Frontend — Event Hook

**Files:**
- Create: `frontend/src/features/artefact/useArtefactEvents.ts`

- [ ] **Step 1: Create event subscription hook**

```typescript
// frontend/src/features/artefact/useArtefactEvents.ts
import { useEffect } from 'react'
import { eventBus } from '../../core/websocket/eventBus'
import { useArtefactStore } from '../../core/store/artefactStore'
import { Topics } from '../../core/types/events'
import type { BaseEvent } from '../../core/types/events'
import type { ArtefactType } from '../../core/types/artefact'

export function useArtefactEvents(sessionId: string | null) {
  useEffect(() => {
    if (!sessionId) return

    const store = useArtefactStore.getState

    const handleEvent = (event: BaseEvent) => {
      const p = event.payload as Record<string, unknown>
      if (p.session_id !== sessionId) return

      switch (event.type) {
        case Topics.ARTEFACT_CREATED: {
          store().addArtefact({
            id: '',
            session_id: sessionId,
            handle: p.handle as string,
            title: p.title as string,
            type: p.artefact_type as ArtefactType,
            language: (p.language as string) ?? null,
            size_bytes: p.size_bytes as number,
            version: 1,
            created_at: event.timestamp,
            updated_at: event.timestamp,
          })
          // Auto-open sidebar when first artefact arrives
          if (store().artefacts.length <= 1) {
            store().setSidebarOpen(true)
          }
          break
        }
        case Topics.ARTEFACT_UPDATED: {
          store().updateArtefact(p.handle as string, {
            title: p.title as string,
            size_bytes: p.size_bytes as number,
            version: p.version as number,
            updated_at: event.timestamp,
          })
          const active = store().activeArtefact
          if (active && active.handle === p.handle) {
            store().setActiveArtefact(null)
            store().setActiveArtefactLoading(true)
          }
          break
        }
        case Topics.ARTEFACT_DELETED: {
          store().removeArtefact(p.handle as string)
          break
        }
        case Topics.ARTEFACT_UNDO:
        case Topics.ARTEFACT_REDO: {
          store().updateArtefact(p.handle as string, {
            version: p.version as number,
            updated_at: event.timestamp,
          })
          const active = store().activeArtefact
          if (active && active.handle === p.handle) {
            store().setActiveArtefact(null)
            store().setActiveArtefactLoading(true)
          }
          break
        }
      }
    }

    const unsub = eventBus.on('artefact.*', handleEvent)
    return unsub
  }, [sessionId])
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/features/artefact/useArtefactEvents.ts
git commit -m "Add artefact event subscription hook"
```

---

## Task 7: Frontend — ArtefactRail & ArtefactSidebar

**Files:**
- Create: `frontend/src/features/artefact/ArtefactRail.tsx`
- Create: `frontend/src/features/artefact/ArtefactSidebar.tsx`

- [ ] **Step 1: Create ArtefactRail component**

A 40px-wide vertical strip with an expand arrow and artefact count badge. Only renders when artefact count > 0. Entire rail is clickable and calls `toggleSidebar()`. Uses gold accent colour for the badge. See detailed code in spec context above.

- [ ] **Step 2: Create ArtefactSidebar component**

A 280px-wide panel with:
- Header: "Artefacts" label + collapse arrow
- Artefact list: each item shows title, type badge (colour-coded), size
- Per-item context menu (three-dot button, visible on hover): Rename, Copy, Download, Delete
- Inline rename editing (input replaces title on rename action)
- Click on artefact row opens overlay via `artefactApi.get()` then `openOverlay()`

Colour map for type badges: markdown=`180,180,220`, code=`137,180,250`, html=`250,170,130`, svg=`170,220,170`, jsx=`140,180,250`, mermaid=`200,170,250`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/artefact/ArtefactRail.tsx frontend/src/features/artefact/ArtefactSidebar.tsx
git commit -m "Add ArtefactRail and ArtefactSidebar components"
```

---

## Task 8: Frontend — ArtefactPreview (Per-Type Renderers)

**Files:**
- Create: `frontend/src/features/artefact/ArtefactPreview.tsx`
- Modify: `frontend/package.json` (add mermaid)

- [ ] **Step 1: Install mermaid**

Run: `cd frontend && pnpm add mermaid`

- [ ] **Step 2: Create ArtefactPreview component**

A switcher component that renders the correct preview based on `type`:

- **`markdown`**: `ReactMarkdown` + `remarkGfm` with `.markdown-preview` CSS class and `createMarkdownComponents(highlighter)` for Shiki code blocks. Same setup as the DocumentEditorModal preview.
- **`code`**: Shiki `codeToHtml()` with `github-dark-dimmed` theme. Falls back to plain `<pre><code>` if highlighting fails. Uses `dangerouslySetInnerHTML` for Shiki output only (trusted syntax-highlight markup from the Shiki library, not user content).
- **`html`**: Sandboxed `<iframe srcDoc={content} sandbox="allow-scripts">`. User content is fully isolated from the parent DOM.
- **`svg`**: Convert to base64 data URI, render as `<img>` tag. Centred in container.
- **`jsx`**: Sandboxed `<iframe>` with `srcDoc` containing React 18 UMD + Babel standalone CDN links. The user's JSX code runs inside `<script type="text/babel">` in the iframe. Expects an `App` component export. Sandbox isolates from parent.
- **`mermaid`**: Dynamic `import('mermaid')`, call `mermaid.render()` with dark theme, inject resulting SVG into a container div. Shows error message on parse failure. Uses `innerHTML` for Mermaid's library-generated SVG output.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/artefact/ArtefactPreview.tsx frontend/package.json frontend/pnpm-lock.yaml
git commit -m "Add per-type artefact preview renderers with mermaid support"
```

---

## Task 9: Frontend — ArtefactOverlay

**Files:**
- Create: `frontend/src/features/artefact/ArtefactOverlay.tsx`

- [ ] **Step 1: Create ArtefactOverlay component**

Positioned `absolute inset-0 z-30` within the chat content area. Structure:

- **Background**: Semi-transparent black overlay (`bg-black/40`)
- **Panel**: Rounded, bordered, `bg-elevated`, fills most of the overlay with margin
- **Toolbar**: Title + type badge + language label | Edit/Preview toggle | Copy/Download/Undo/Redo | X close
- **Content area**: Switches between edit mode (textarea) and preview mode (`ArtefactPreview`)
- **Edit save bar**: Appears at bottom when content is dirty, with Discard and Save buttons

Behaviour:
- Escape key closes the overlay
- Mode resets to `preview` when artefact handle/version changes
- Undo disabled when `version <= 1`
- Save via `artefactApi.patch()`, receives updated detail, calls `openOverlay(updated)`
- Undo/Redo via `artefactApi.undo()`/`artefactApi.redo()`, same pattern

- [ ] **Step 2: Commit**

```bash
git add frontend/src/features/artefact/ArtefactOverlay.tsx
git commit -m "Add ArtefactOverlay with edit/preview, undo/redo, copy, download"
```

---

## Task 10: Frontend — ArtefactCard (Inline Chat Stream)

**Files:**
- Create: `frontend/src/features/artefact/ArtefactCard.tsx`

- [ ] **Step 1: Create ArtefactCard component**

Compact button card rendered in the message stream. Shows:
- Type badge (colour-coded, same map as sidebar)
- Artefact title
- "Created: {handle}" or "Updated: {handle}" subtitle
- "Open" label on the right

On click: finds the artefact summary in the store by handle, fetches full detail via `artefactApi.get()`, calls `openOverlay()`.

Styled with the type colour as a subtle background and border.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/features/artefact/ArtefactCard.tsx
git commit -m "Add ArtefactCard inline component for chat stream"
```

---

## Task 11: Frontend — Integration (ChatView, MessageList, ToolCallActivity)

**Files:**
- Modify: `frontend/src/features/chat/ChatView.tsx`
- Modify: `frontend/src/features/chat/MessageList.tsx`
- Modify: `frontend/src/features/chat/ToolCallActivity.tsx`

- [ ] **Step 1: Integrate rail/sidebar/overlay into ChatView**

Import `ArtefactRail`, `ArtefactSidebar`, `ArtefactOverlay`, `useArtefactEvents`, `useArtefactStore`, `artefactApi`.

After `useChatStream(effectiveSessionId ?? null)` (line 137), add:
```typescript
useArtefactEvents(effectiveSessionId ?? null)
const artefactSidebarOpen = useArtefactStore((s) => s.sidebarOpen)
const artefactCount = useArtefactStore((s) => s.artefacts.length)
```

In the session-loading effect, after `store.reset(effectiveSessionId)`, add `useArtefactStore.getState().reset()`. After loading messages, add artefact list fetch:
```typescript
artefactApi.list(sessionId).then((arts) => {
  useArtefactStore.getState().setArtefacts(arts)
}).catch(() => {})
```

Restructure the return JSX: wrap the content area (between header and bookmark modal) in a flex row. Chat content (MessageList + ChatInput) goes in a `flex-1 flex-col min-w-0 relative` div. ArtefactOverlay is absolutely positioned inside that div. The artefact rail/sidebar sits beside it:

```tsx
<div className="flex flex-1 min-h-0">
  <div className="flex flex-1 flex-col min-w-0 relative">
    {/* MessageList, UploadBrowser, ChatInput */}
    <ArtefactOverlay />
  </div>
  {artefactSidebarOpen ? (
    <ArtefactSidebar sessionId={effectiveSessionId!} />
  ) : (
    artefactCount > 0 && <ArtefactRail />
  )}
</div>
```

- [ ] **Step 2: Add artefact tool labels to ToolCallActivity**

Add to `TOOL_LABELS` dict:
```typescript
create_artefact: (args) => `Creating artefact "${args.title ?? args.handle ?? '...'}"`,
update_artefact: (args) => `Updating artefact "${args.handle ?? '...'}"`,
read_artefact: (args) => `Reading artefact "${args.handle ?? '...'}"`,
list_artefacts: () => 'Listing artefacts',
```

Add artefact tool colour (gold `201,169,110`):
```typescript
const isArtefact = toolName.includes('artefact')
const colour = isKnowledge ? '140,118,215' : isArtefact ? '201,169,110' : '137,180,250'
```

- [ ] **Step 3: Render ArtefactCard in MessageList**

Add `sessionId: string | null` to `MessageListProps`. Pass from ChatView.

Import `ArtefactCard`. In the streaming section, after `activeToolCalls.filter(tc => tc.status === 'running')` render, add completed artefact tool cards:

```tsx
{activeToolCalls.filter((tc) => tc.status === 'done' && (tc.toolName === 'create_artefact' || tc.toolName === 'update_artefact')).map((tc) => (
  <ArtefactCard
    key={tc.id}
    handle={(tc.arguments.handle as string) ?? ''}
    title={(tc.arguments.title as string) ?? (tc.arguments.handle as string) ?? ''}
    artefactType={(tc.arguments.type as string) ?? 'code'}
    isUpdate={tc.toolName === 'update_artefact'}
    sessionId={sessionId ?? ''}
  />
))}
```

- [ ] **Step 4: Verify build**

Run: `cd frontend && pnpm tsc --noEmit 2>&1 | grep -v "__tests__" | grep -v "setup.ts" | grep -v "vite.config" | head -20`
Expected: no new errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/chat/ChatView.tsx frontend/src/features/chat/MessageList.tsx frontend/src/features/chat/ToolCallActivity.tsx
git commit -m "Integrate artefact rail, sidebar, overlay, and inline cards into chat UI"
```

---

## Task 12: Verify Event Persistence

- [ ] **Step 1: Verify artefact events persist in Redis Streams**

Artefact events (`artefact.created`, `artefact.updated`, `artefact.deleted`, `artefact.undo`, `artefact.redo`) must persist so they survive WebSocket reconnects. Check `backend/ws/event_bus.py` for the `_SKIP_PERSISTENCE` set. Since our new topic strings don't match any existing skip entry, they persist by default.

If `_SKIP_PERSISTENCE` uses prefix matching that would accidentally match `artefact.*`, add explicit exclusions. Otherwise no change needed.

- [ ] **Step 2: Commit (only if changes needed)**

---

## Task 13: Smoke Test & Final Verification

- [ ] **Step 1: Backend syntax check**

Run: `cd /home/chris/workspace/chatsune && uv run python -c "from backend.modules.artefact import router, init_indexes; print('OK')"`
Expected: `OK`

- [ ] **Step 2: Tool registration check**

Run: `cd /home/chris/workspace/chatsune && uv run python -c "from backend.modules.tools import get_all_groups; groups = get_all_groups(); print([g.id for g in groups])"`
Expected: List includes `'artefacts'`

- [ ] **Step 3: Frontend build check**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm run build 2>&1 | tail -5`
Expected: Build succeeds (ignoring pre-existing test errors)

- [ ] **Step 4: Final commit (if any remaining changes)**

```bash
git add -A
git commit -m "Artefact system: final adjustments and verification"
```

- [ ] **Step 5: Merge to master**

Per project convention, merge to master after implementation.

# Project Entity Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the backend-only data foundation for the new `project` module — model, shared DTOs/events, REST CRUD — so that subsequent steps can wire projects into chats, artefacts and the frontend.

**Architecture:** New module `backend/modules/project/`, structured exactly like `persona`. Owns its own MongoDB collection `projects`. Public API is a FastAPI router and an `init_indexes` hook, exported from `__init__.py`. CRUD over REST, events published over the existing event bus with scope `user:<user_id>`. PATCH semantics for `emoji` use an `UNSET` sentinel to distinguish "don't touch" from "clear".

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, motor (async MongoDB), pytest with httpx AsyncClient, `grapheme` library for single-grapheme validation.

**Spec:** `docs/superpowers/specs/2026-04-07-project-entity-foundation-design.md`

---

## File Structure

**Created:**
- `backend/modules/project/__init__.py` — public API exports
- `backend/modules/project/_models.py` — `ProjectDocument` Pydantic model
- `backend/modules/project/_repository.py` — `ProjectRepository` (collection access, indexes, DTO mapping)
- `backend/modules/project/_handlers.py` — FastAPI router with five REST endpoints
- `shared/dtos/project.py` — `ProjectDto`, `ProjectCreateDto`, `ProjectUpdateDto`, `UNSET` sentinel
- `shared/events/project.py` — `ProjectCreatedEvent`, `ProjectUpdatedEvent`, `ProjectDeletedEvent`
- `tests/test_project_repository.py` — repository-level tests
- `tests/test_project_handlers.py` — handler-level tests through httpx client

**Modified:**
- `pyproject.toml` — add `grapheme` dependency
- `shared/topics.py` — add three new topic constants
- `backend/main.py` — import router + init_indexes, register router, call init_indexes on startup

---

## Task 1: Add `grapheme` dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add `grapheme` to dependencies**

Append to the `dependencies = [...]` block in `pyproject.toml`:

```toml
    "grapheme>=0.6.0",
```

- [ ] **Step 2: Sync the lockfile**

Run: `uv sync`
Expected: `grapheme` resolved and installed, no errors.

- [ ] **Step 3: Smoke-test the import**

Run: `uv run python -c "import grapheme; print(grapheme.length('🇩🇪'))"`
Expected: prints `1` (the German flag is one grapheme even though it is two codepoints).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "Add grapheme dependency for project emoji validation"
```

---

## Task 2: Add topic constants

**Files:**
- Modify: `shared/topics.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_shared_project_contracts.py`:

```python
from shared.topics import Topics


def test_project_topics_exist():
    assert Topics.PROJECT_CREATED == "project.created"
    assert Topics.PROJECT_UPDATED == "project.updated"
    assert Topics.PROJECT_DELETED == "project.deleted"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_shared_project_contracts.py::test_project_topics_exist -v`
Expected: FAIL with `AttributeError: type object 'Topics' has no attribute 'PROJECT_CREATED'`.

- [ ] **Step 3: Add the constants**

In `shared/topics.py`, add inside the `Topics` class (e.g. after the bookmark block):

```python
    # Projects
    PROJECT_CREATED = "project.created"
    PROJECT_UPDATED = "project.updated"
    PROJECT_DELETED = "project.deleted"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_shared_project_contracts.py::test_project_topics_exist -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add shared/topics.py tests/test_shared_project_contracts.py
git commit -m "Add project topic constants"
```

---

## Task 3: Shared DTOs with UNSET sentinel for emoji

**Files:**
- Create: `shared/dtos/project.py`
- Modify: `tests/test_shared_project_contracts.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_shared_project_contracts.py`:

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from shared.dtos.project import (
    UNSET,
    ProjectCreateDto,
    ProjectDto,
    ProjectUpdateDto,
)


def test_project_dto_round_trip():
    now = datetime.now(timezone.utc)
    dto = ProjectDto(
        id="p1",
        user_id="u1",
        title="My Project",
        emoji="🔥",
        description="notes",
        nsfw=False,
        pinned=False,
        sort_order=0,
        created_at=now,
        updated_at=now,
    )
    assert dto.title == "My Project"
    assert dto.emoji == "🔥"


def test_create_dto_defaults():
    dto = ProjectCreateDto(title="Hi")
    assert dto.emoji is None
    assert dto.description == ""
    assert dto.nsfw is False


def test_create_dto_rejects_blank_title():
    with pytest.raises(ValidationError):
        ProjectCreateDto(title="   ")


def test_create_dto_rejects_long_title():
    with pytest.raises(ValidationError):
        ProjectCreateDto(title="x" * 81)


def test_create_dto_rejects_multi_grapheme_emoji():
    with pytest.raises(ValidationError):
        ProjectCreateDto(title="ok", emoji="🔥🔥")


def test_create_dto_accepts_compound_grapheme_emoji():
    # Family emoji is multiple codepoints but a single grapheme.
    dto = ProjectCreateDto(title="ok", emoji="👨‍👩‍👧")
    assert dto.emoji == "👨‍👩‍👧"


def test_create_dto_rejects_long_description():
    with pytest.raises(ValidationError):
        ProjectCreateDto(title="ok", description="x" * 2001)


def test_update_dto_emoji_unset_by_default():
    dto = ProjectUpdateDto()
    assert dto.emoji is UNSET


def test_update_dto_emoji_explicit_none_means_clear():
    dto = ProjectUpdateDto.model_validate({"emoji": None})
    assert dto.emoji is None


def test_update_dto_emoji_string_value():
    dto = ProjectUpdateDto.model_validate({"emoji": "✏️"})
    assert dto.emoji == "✏️"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_shared_project_contracts.py -v`
Expected: ImportError on `shared.dtos.project`.

- [ ] **Step 3: Create `shared/dtos/project.py`**

```python
"""DTOs for the project module."""

from datetime import datetime
from typing import Any

import grapheme
from pydantic import BaseModel, Field, field_validator


class _Unset:
    """Sentinel type used to distinguish 'field absent' from 'explicit null'
    in PATCH-style update payloads."""

    _instance: "Any" = None

    def __new__(cls):  # singleton
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET = _Unset()


def _validate_title(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("title must not be empty")
    if len(stripped) > 80:
        raise ValueError("title must be at most 80 characters")
    return stripped


def _validate_emoji(value: str | None) -> str | None:
    if value is None:
        return None
    if grapheme.length(value) != 1:
        raise ValueError("emoji must be exactly one grapheme")
    return value


def _validate_description(value: str) -> str:
    if len(value) > 2000:
        raise ValueError("description must be at most 2000 characters")
    return value


class ProjectDto(BaseModel):
    id: str
    user_id: str
    title: str
    emoji: str | None
    description: str
    nsfw: bool
    pinned: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


class ProjectCreateDto(BaseModel):
    title: str
    emoji: str | None = None
    description: str = ""
    nsfw: bool = False

    @field_validator("title")
    @classmethod
    def _check_title(cls, v: str) -> str:
        return _validate_title(v)

    @field_validator("emoji")
    @classmethod
    def _check_emoji(cls, v: str | None) -> str | None:
        return _validate_emoji(v)

    @field_validator("description")
    @classmethod
    def _check_description(cls, v: str) -> str:
        return _validate_description(v)


class ProjectUpdateDto(BaseModel):
    """Partial update payload.

    `emoji` uses the `UNSET` sentinel as its default so that callers can
    distinguish 'field omitted' from 'explicit null clears the emoji'.
    """

    model_config = {"arbitrary_types_allowed": True}

    title: str | None = None
    emoji: str | None | _Unset = Field(default=UNSET)
    description: str | None = None
    nsfw: bool | None = None

    @field_validator("title")
    @classmethod
    def _check_title(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_title(v)

    @field_validator("emoji")
    @classmethod
    def _check_emoji(cls, v: Any) -> Any:
        if isinstance(v, _Unset) or v is None:
            return v
        return _validate_emoji(v)

    @field_validator("description")
    @classmethod
    def _check_description(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _validate_description(v)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_shared_project_contracts.py -v`
Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add shared/dtos/project.py tests/test_shared_project_contracts.py
git commit -m "Add project DTOs with UNSET sentinel for PATCH emoji semantics"
```

---

## Task 4: Shared event models

**Files:**
- Create: `shared/events/project.py`
- Modify: `tests/test_shared_project_contracts.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_shared_project_contracts.py`:

```python
from shared.events.project import (
    ProjectCreatedEvent,
    ProjectDeletedEvent,
    ProjectUpdatedEvent,
)


def _sample_dto() -> ProjectDto:
    now = datetime.now(timezone.utc)
    return ProjectDto(
        id="p1",
        user_id="u1",
        title="x",
        emoji=None,
        description="",
        nsfw=False,
        pinned=False,
        sort_order=0,
        created_at=now,
        updated_at=now,
    )


def test_project_created_event():
    ev = ProjectCreatedEvent(
        project_id="p1",
        user_id="u1",
        project=_sample_dto(),
        timestamp=datetime.now(timezone.utc),
    )
    assert ev.type == "project.created"
    assert ev.project.id == "p1"


def test_project_updated_event():
    ev = ProjectUpdatedEvent(
        project_id="p1",
        user_id="u1",
        project=_sample_dto(),
        timestamp=datetime.now(timezone.utc),
    )
    assert ev.type == "project.updated"


def test_project_deleted_event():
    ev = ProjectDeletedEvent(
        project_id="p1",
        user_id="u1",
        timestamp=datetime.now(timezone.utc),
    )
    assert ev.type == "project.deleted"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_shared_project_contracts.py -v`
Expected: ImportError on `shared.events.project`.

- [ ] **Step 3: Create `shared/events/project.py`**

```python
"""Event models for the project module."""

from datetime import datetime

from pydantic import BaseModel

from shared.dtos.project import ProjectDto


class ProjectCreatedEvent(BaseModel):
    type: str = "project.created"
    project_id: str
    user_id: str
    project: ProjectDto
    timestamp: datetime


class ProjectUpdatedEvent(BaseModel):
    type: str = "project.updated"
    project_id: str
    user_id: str
    project: ProjectDto
    timestamp: datetime


class ProjectDeletedEvent(BaseModel):
    type: str = "project.deleted"
    project_id: str
    user_id: str
    timestamp: datetime
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_shared_project_contracts.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add shared/events/project.py tests/test_shared_project_contracts.py
git commit -m "Add project event models"
```

---

## Task 5: Repository — create, find, list, indexes

**Files:**
- Create: `backend/modules/project/__init__.py`
- Create: `backend/modules/project/_models.py`
- Create: `backend/modules/project/_repository.py`
- Create: `tests/test_project_repository.py`

- [ ] **Step 1: Create the package skeleton**

Create `backend/modules/project/__init__.py` with placeholder content (will be filled in Task 8):

```python
"""Project module — user-owned project containers.

Public API: import only from this file.
"""

from backend.modules.project._repository import ProjectRepository


async def init_indexes(db) -> None:
    await ProjectRepository(db).create_indexes()


__all__ = ["init_indexes", "ProjectRepository"]
```

Create `backend/modules/project/_models.py`:

```python
"""Internal MongoDB document shape for projects.

Not part of the public API. External code uses ProjectDto from shared/dtos.
"""

from datetime import datetime

from pydantic import BaseModel


class ProjectDocument(BaseModel):
    id: str
    user_id: str
    title: str
    emoji: str | None
    description: str
    nsfw: bool
    pinned: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_project_repository.py`:

```python
from datetime import datetime

import pytest

from backend.database import get_db
from backend.modules.project import ProjectRepository


@pytest.fixture
async def repo():
    db = get_db()
    r = ProjectRepository(db)
    await r.create_indexes()
    await db["projects"].delete_many({})
    yield r
    await db["projects"].delete_many({})


async def test_create_and_find(repo: ProjectRepository):
    doc = await repo.create(
        user_id="u1",
        title="Writing",
        emoji="✏️",
        description="for writing things",
        nsfw=False,
    )
    assert doc["_id"]
    assert doc["title"] == "Writing"
    assert doc["emoji"] == "✏️"
    assert doc["pinned"] is False
    assert doc["sort_order"] == 0
    assert isinstance(doc["created_at"], datetime)

    fetched = await repo.find_by_id(doc["_id"], "u1")
    assert fetched is not None
    assert fetched["_id"] == doc["_id"]


async def test_find_other_user_returns_none(repo: ProjectRepository):
    doc = await repo.create(
        user_id="u1", title="x", emoji=None, description="", nsfw=False,
    )
    assert await repo.find_by_id(doc["_id"], "u2") is None


async def test_list_for_user_orders_newest_first(repo: ProjectRepository):
    a = await repo.create(user_id="u1", title="A", emoji=None, description="", nsfw=False)
    b = await repo.create(user_id="u1", title="B", emoji=None, description="", nsfw=False)
    c = await repo.create(user_id="u1", title="C", emoji=None, description="", nsfw=False)
    await repo.create(user_id="u2", title="other", emoji=None, description="", nsfw=False)

    docs = await repo.list_for_user("u1")
    ids = [d["_id"] for d in docs]
    assert ids == [c["_id"], b["_id"], a["_id"]]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_project_repository.py -v`
Expected: ImportError or AttributeError — `ProjectRepository` has no `create` / `find_by_id` / `list_for_user`.

- [ ] **Step 4: Implement `_repository.py` (create + find + list + indexes)**

Create `backend/modules/project/_repository.py`:

```python
from datetime import UTC, datetime
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from shared.dtos.project import ProjectDto


class ProjectRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db["projects"]

    async def create_indexes(self) -> None:
        await self._collection.create_index([("user_id", 1), ("created_at", -1)])
        await self._collection.create_index(
            [("user_id", 1), ("pinned", -1), ("sort_order", 1), ("created_at", -1)],
        )

    async def create(
        self,
        user_id: str,
        title: str,
        emoji: str | None,
        description: str,
        nsfw: bool,
    ) -> dict:
        now = datetime.now(UTC)
        doc = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "title": title,
            "emoji": emoji,
            "description": description,
            "nsfw": nsfw,
            "pinned": False,
            "sort_order": 0,
            "created_at": now,
            "updated_at": now,
        }
        await self._collection.insert_one(doc)
        return doc

    async def find_by_id(self, project_id: str, user_id: str) -> dict | None:
        return await self._collection.find_one(
            {"_id": project_id, "user_id": user_id},
        )

    async def list_for_user(self, user_id: str) -> list[dict]:
        cursor = self._collection.find({"user_id": user_id}).sort("created_at", -1)
        return await cursor.to_list(length=500)

    @staticmethod
    def to_dto(doc: dict) -> ProjectDto:
        return ProjectDto(
            id=doc["_id"],
            user_id=doc["user_id"],
            title=doc["title"],
            emoji=doc.get("emoji"),
            description=doc.get("description", ""),
            nsfw=doc.get("nsfw", False),
            pinned=doc.get("pinned", False),
            sort_order=doc.get("sort_order", 0),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_project_repository.py -v`
Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/project/ tests/test_project_repository.py
git commit -m "Add project module skeleton with create/find/list repository"
```

---

## Task 6: Repository — update with sentinel awareness, delete

**Files:**
- Modify: `backend/modules/project/_repository.py`
- Modify: `tests/test_project_repository.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_project_repository.py`:

```python
async def test_update_partial_preserves_other_fields(repo: ProjectRepository):
    doc = await repo.create(
        user_id="u1", title="Old", emoji="🔥", description="d", nsfw=False,
    )
    updated = await repo.update(doc["_id"], "u1", {"title": "New"})
    assert updated is not None
    assert updated["title"] == "New"
    assert updated["emoji"] == "🔥"
    assert updated["description"] == "d"
    assert updated["updated_at"] >= doc["updated_at"]


async def test_update_other_user_returns_none(repo: ProjectRepository):
    doc = await repo.create(
        user_id="u1", title="x", emoji=None, description="", nsfw=False,
    )
    assert await repo.update(doc["_id"], "u2", {"title": "Hacked"}) is None


async def test_update_can_clear_emoji(repo: ProjectRepository):
    doc = await repo.create(
        user_id="u1", title="x", emoji="🔥", description="", nsfw=False,
    )
    updated = await repo.update(doc["_id"], "u1", {"emoji": None})
    assert updated is not None
    assert updated["emoji"] is None


async def test_delete(repo: ProjectRepository):
    doc = await repo.create(
        user_id="u1", title="x", emoji=None, description="", nsfw=False,
    )
    assert await repo.delete(doc["_id"], "u1") is True
    assert await repo.find_by_id(doc["_id"], "u1") is None


async def test_delete_other_user_returns_false(repo: ProjectRepository):
    doc = await repo.create(
        user_id="u1", title="x", emoji=None, description="", nsfw=False,
    )
    assert await repo.delete(doc["_id"], "u2") is False
    assert await repo.find_by_id(doc["_id"], "u1") is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_project_repository.py -v`
Expected: AttributeError — `ProjectRepository` has no `update` or `delete`.

- [ ] **Step 3: Add `update` and `delete` to `_repository.py`**

Add inside `class ProjectRepository`, after `list_for_user`:

```python
    async def update(
        self, project_id: str, user_id: str, fields: dict,
    ) -> dict | None:
        if not fields:
            return await self.find_by_id(project_id, user_id)
        fields = {**fields, "updated_at": datetime.now(UTC)}
        result = await self._collection.update_one(
            {"_id": project_id, "user_id": user_id},
            {"$set": fields},
        )
        if result.matched_count == 0:
            return None
        return await self.find_by_id(project_id, user_id)

    async def delete(self, project_id: str, user_id: str) -> bool:
        result = await self._collection.delete_one(
            {"_id": project_id, "user_id": user_id},
        )
        return result.deleted_count > 0
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_project_repository.py -v`
Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/project/_repository.py tests/test_project_repository.py
git commit -m "Add update and delete to project repository"
```

---

## Task 7: REST handlers — list, get, create

**Files:**
- Create: `backend/modules/project/_handlers.py`
- Modify: `backend/modules/project/__init__.py`
- Modify: `backend/main.py`
- Create: `tests/test_project_handlers.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_project_handlers.py`:

```python
from httpx import AsyncClient


async def _setup_and_login(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/setup",
        json={
            "pin": "change-me-1234",
            "username": "admin",
            "email": "admin@example.com",
            "password": "SecurePass123",
        },
    )
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_list_projects_empty(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.get("/api/projects", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_projects_requires_auth(client: AsyncClient):
    resp = await client.get("/api/projects")
    assert resp.status_code == 401


async def test_create_project(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.post(
        "/api/projects",
        json={"title": "Writing", "emoji": "✏️", "description": "for writing"},
        headers=_auth(token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Writing"
    assert data["emoji"] == "✏️"
    assert data["description"] == "for writing"
    assert data["nsfw"] is False
    assert data["pinned"] is False
    assert data["sort_order"] == 0
    assert "id" in data
    assert "created_at" in data


async def test_create_project_minimal(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.post(
        "/api/projects", json={"title": "Hi"}, headers=_auth(token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Hi"
    assert data["emoji"] is None
    assert data["description"] == ""


async def test_create_project_blank_title_rejected(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.post(
        "/api/projects", json={"title": "   "}, headers=_auth(token),
    )
    assert resp.status_code == 422


async def test_create_project_multi_grapheme_emoji_rejected(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.post(
        "/api/projects",
        json={"title": "ok", "emoji": "🔥🔥"},
        headers=_auth(token),
    )
    assert resp.status_code == 422


async def test_get_project(client: AsyncClient):
    token = await _setup_and_login(client)
    create_resp = await client.post(
        "/api/projects", json={"title": "x"}, headers=_auth(token),
    )
    pid = create_resp.json()["id"]
    resp = await client.get(f"/api/projects/{pid}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["id"] == pid


async def test_get_project_not_found(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.get("/api/projects/nonexistent", headers=_auth(token))
    assert resp.status_code == 404


async def test_list_orders_newest_first(client: AsyncClient):
    token = await _setup_and_login(client)
    for title in ["A", "B", "C"]:
        await client.post("/api/projects", json={"title": title}, headers=_auth(token))
    resp = await client.get("/api/projects", headers=_auth(token))
    titles = [p["title"] for p in resp.json()]
    assert titles == ["C", "B", "A"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_project_handlers.py -v`
Expected: all tests FAIL with 404 (router not registered).

- [ ] **Step 3: Create `_handlers.py` with list/get/create**

Create `backend/modules/project/_handlers.py`:

```python
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from backend.database import get_db
from backend.dependencies import require_active_session
from backend.modules.project._repository import ProjectRepository
from backend.ws.event_bus import EventBus, get_event_bus
from shared.dtos.project import ProjectCreateDto, ProjectUpdateDto
from shared.events.project import (
    ProjectCreatedEvent,
    ProjectDeletedEvent,
    ProjectUpdatedEvent,
)
from shared.topics import Topics

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects")


def _repo() -> ProjectRepository:
    return ProjectRepository(get_db())


@router.get("")
async def list_projects(user: dict = Depends(require_active_session)):
    docs = await _repo().list_for_user(user["sub"])
    return [ProjectRepository.to_dto(d) for d in docs]


@router.get("/{project_id}")
async def get_project(
    project_id: str,
    user: dict = Depends(require_active_session),
):
    doc = await _repo().find_by_id(project_id, user["sub"])
    if not doc:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectRepository.to_dto(doc)


@router.post("", status_code=201)
async def create_project(
    body: ProjectCreateDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    repo = _repo()
    doc = await repo.create(
        user_id=user["sub"],
        title=body.title,
        emoji=body.emoji,
        description=body.description,
        nsfw=body.nsfw,
    )
    dto = ProjectRepository.to_dto(doc)
    await event_bus.publish(
        Topics.PROJECT_CREATED,
        ProjectCreatedEvent(
            project_id=doc["_id"],
            user_id=user["sub"],
            project=dto,
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"user:{user['sub']}",
        target_user_ids=[user["sub"]],
    )
    return dto
```

- [ ] **Step 4: Export the router from `__init__.py`**

Replace `backend/modules/project/__init__.py` with:

```python
"""Project module — user-owned project containers.

Public API: import only from this file.
"""

from backend.modules.project._handlers import router
from backend.modules.project._repository import ProjectRepository


async def init_indexes(db) -> None:
    await ProjectRepository(db).create_indexes()


__all__ = ["router", "init_indexes", "ProjectRepository"]
```

- [ ] **Step 5: Register the router and indexes in `backend/main.py`**

Add an import line near the other module imports (around line 15, alongside `persona`):

```python
from backend.modules.project import router as project_router, init_indexes as project_init_indexes
```

Add an `await project_init_indexes(db)` call inside the startup index-init block (around line 49, after `artefact_init_indexes`):

```python
    await project_init_indexes(db)
```

Add `app.include_router(project_router)` near the other `include_router` calls (around line 397, after `artefact_global_router`):

```python
app.include_router(project_router)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_project_handlers.py -v`
Expected: 9 PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/project/ backend/main.py tests/test_project_handlers.py
git commit -m "Add list/get/create REST endpoints for projects"
```

---

## Task 8: REST handlers — PATCH with sentinel emoji semantics

**Files:**
- Modify: `backend/modules/project/_handlers.py`
- Modify: `tests/test_project_handlers.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_project_handlers.py`:

```python
async def test_patch_title(client: AsyncClient):
    token = await _setup_and_login(client)
    pid = (await client.post(
        "/api/projects", json={"title": "Old"}, headers=_auth(token),
    )).json()["id"]

    resp = await client.patch(
        f"/api/projects/{pid}", json={"title": "New"}, headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "New"


async def test_patch_emoji_set(client: AsyncClient):
    token = await _setup_and_login(client)
    pid = (await client.post(
        "/api/projects", json={"title": "x"}, headers=_auth(token),
    )).json()["id"]

    resp = await client.patch(
        f"/api/projects/{pid}", json={"emoji": "🔥"}, headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["emoji"] == "🔥"


async def test_patch_emoji_explicit_null_clears(client: AsyncClient):
    token = await _setup_and_login(client)
    pid = (await client.post(
        "/api/projects",
        json={"title": "x", "emoji": "🔥"},
        headers=_auth(token),
    )).json()["id"]

    resp = await client.patch(
        f"/api/projects/{pid}", json={"emoji": None}, headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["emoji"] is None


async def test_patch_emoji_omitted_preserves(client: AsyncClient):
    token = await _setup_and_login(client)
    pid = (await client.post(
        "/api/projects",
        json={"title": "x", "emoji": "🔥"},
        headers=_auth(token),
    )).json()["id"]

    resp = await client.patch(
        f"/api/projects/{pid}", json={"title": "y"}, headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "y"
    assert body["emoji"] == "🔥"


async def test_patch_other_user_returns_404(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.patch(
        "/api/projects/nonexistent", json={"title": "x"}, headers=_auth(token),
    )
    assert resp.status_code == 404


async def test_patch_invalid_title_rejected(client: AsyncClient):
    token = await _setup_and_login(client)
    pid = (await client.post(
        "/api/projects", json={"title": "x"}, headers=_auth(token),
    )).json()["id"]
    resp = await client.patch(
        f"/api/projects/{pid}", json={"title": "   "}, headers=_auth(token),
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_project_handlers.py -v`
Expected: PATCH tests fail with 405 (no PATCH route).

- [ ] **Step 3: Add the PATCH handler**

Append to `backend/modules/project/_handlers.py`:

```python
from shared.dtos.project import UNSET, _Unset  # noqa: E402


@router.patch("/{project_id}")
async def update_project(
    project_id: str,
    body: ProjectUpdateDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    fields: dict = {}
    if body.title is not None:
        fields["title"] = body.title
    if body.description is not None:
        fields["description"] = body.description
    if body.nsfw is not None:
        fields["nsfw"] = body.nsfw
    # Sentinel-aware emoji handling: UNSET → don't touch; None → clear; str → set.
    if not isinstance(body.emoji, _Unset):
        fields["emoji"] = body.emoji

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    repo = _repo()
    updated = await repo.update(project_id, user["sub"], fields)
    if not updated:
        raise HTTPException(status_code=404, detail="Project not found")

    dto = ProjectRepository.to_dto(updated)
    await event_bus.publish(
        Topics.PROJECT_UPDATED,
        ProjectUpdatedEvent(
            project_id=project_id,
            user_id=user["sub"],
            project=dto,
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"user:{user['sub']}",
        target_user_ids=[user["sub"]],
    )
    return dto
```

(The `_Unset` import lives at the bottom because `UNSET` is also re-exported and we want a single import line that mirrors the public-private split inside `shared.dtos.project`. The `# noqa: E402` is intentional — module-level import after code is fine here, since this file is short and the convention elsewhere in the codebase tolerates it.)

Note: if the file's import-style linter is strict, hoist the import to the top of the file together with the others instead. The functional behaviour is identical.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_project_handlers.py -v`
Expected: all PATCH tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/project/_handlers.py tests/test_project_handlers.py
git commit -m "Add PATCH endpoint for projects with sentinel emoji semantics"
```

---

## Task 9: REST handlers — DELETE

**Files:**
- Modify: `backend/modules/project/_handlers.py`
- Modify: `tests/test_project_handlers.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_project_handlers.py`:

```python
async def test_delete_project(client: AsyncClient):
    token = await _setup_and_login(client)
    pid = (await client.post(
        "/api/projects", json={"title": "x"}, headers=_auth(token),
    )).json()["id"]

    resp = await client.delete(f"/api/projects/{pid}", headers=_auth(token))
    assert resp.status_code == 204

    get_resp = await client.get(f"/api/projects/{pid}", headers=_auth(token))
    assert get_resp.status_code == 404


async def test_delete_other_user_returns_404(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.delete("/api/projects/nonexistent", headers=_auth(token))
    assert resp.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_project_handlers.py -v`
Expected: 405/404 mismatch — no DELETE route.

- [ ] **Step 3: Add the DELETE handler**

Append to `backend/modules/project/_handlers.py`:

```python
@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    repo = _repo()
    deleted = await repo.delete(project_id, user["sub"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")

    await event_bus.publish(
        Topics.PROJECT_DELETED,
        ProjectDeletedEvent(
            project_id=project_id,
            user_id=user["sub"],
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"user:{user['sub']}",
        target_user_ids=[user["sub"]],
    )
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_project_handlers.py -v`
Expected: all tests in the file PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/project/_handlers.py tests/test_project_handlers.py
git commit -m "Add DELETE endpoint for projects"
```

---

## Task 10: Event-publishing assertion test

**Files:**
- Modify: `tests/test_project_handlers.py`

This is the one piece the spec calls out under "Tests → Event publishing": each successful mutation publishes exactly one event with the correct topic and DTO.

- [ ] **Step 1: Find an existing event-bus capture pattern**

Run: `uv run rg -l "event_bus" tests/ | head -5`
Then read one matching test (e.g. `tests/test_personas.py` or `tests/test_chat_events_phase2.py`) to see how the project captures published events. Use the same fixture/approach so tests stay consistent. If a `captured_events` fixture exists in `tests/conftest.py`, reuse it. Otherwise, the simplest approach is to monkeypatch `EventBus.publish` for the duration of one test.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_project_handlers.py`, adapted to whatever pattern Step 1 surfaced. Below is the monkeypatch fallback (use the project's existing pattern if there is one):

```python
import pytest

from shared.topics import Topics


async def test_create_publishes_event(client: AsyncClient, monkeypatch):
    captured = []

    from backend.ws.event_bus import EventBus

    original_publish = EventBus.publish

    async def capturing_publish(self, topic, event, *, scope, target_user_ids):
        captured.append((topic, event, scope, target_user_ids))
        return await original_publish(
            self, topic, event, scope=scope, target_user_ids=target_user_ids,
        )

    monkeypatch.setattr(EventBus, "publish", capturing_publish)

    token = await _setup_and_login(client)
    resp = await client.post(
        "/api/projects", json={"title": "x"}, headers=_auth(token),
    )
    pid = resp.json()["id"]

    project_events = [c for c in captured if c[0] == Topics.PROJECT_CREATED]
    assert len(project_events) == 1
    topic, event, scope, targets = project_events[0]
    assert event.project_id == pid
    assert event.project.title == "x"
    assert scope.startswith("user:")
    assert targets == [event.user_id]


async def test_update_publishes_event(client: AsyncClient, monkeypatch):
    captured = []
    from backend.ws.event_bus import EventBus
    original = EventBus.publish

    async def cap(self, topic, event, *, scope, target_user_ids):
        captured.append((topic, event))
        return await original(self, topic, event, scope=scope, target_user_ids=target_user_ids)

    monkeypatch.setattr(EventBus, "publish", cap)

    token = await _setup_and_login(client)
    pid = (await client.post(
        "/api/projects", json={"title": "x"}, headers=_auth(token),
    )).json()["id"]
    captured.clear()

    await client.patch(
        f"/api/projects/{pid}", json={"title": "y"}, headers=_auth(token),
    )
    update_events = [c for c in captured if c[0] == Topics.PROJECT_UPDATED]
    assert len(update_events) == 1
    assert update_events[0][1].project.title == "y"


async def test_delete_publishes_event(client: AsyncClient, monkeypatch):
    captured = []
    from backend.ws.event_bus import EventBus
    original = EventBus.publish

    async def cap(self, topic, event, *, scope, target_user_ids):
        captured.append((topic, event))
        return await original(self, topic, event, scope=scope, target_user_ids=target_user_ids)

    monkeypatch.setattr(EventBus, "publish", cap)

    token = await _setup_and_login(client)
    pid = (await client.post(
        "/api/projects", json={"title": "x"}, headers=_auth(token),
    )).json()["id"]
    captured.clear()

    await client.delete(f"/api/projects/{pid}", headers=_auth(token))
    delete_events = [c for c in captured if c[0] == Topics.PROJECT_DELETED]
    assert len(delete_events) == 1
    assert delete_events[0][1].project_id == pid
```

If `EventBus.publish` has a different signature in this codebase (kwargs vs. positional), adjust the wrapper to match — verify with one read of `backend/ws/event_bus.py` before writing this test.

- [ ] **Step 3: Run the tests to verify they fail then pass**

Run: `uv run pytest tests/test_project_handlers.py -v`
Expected: the three new tests PASS (the underlying handlers were already publishing events; these tests just lock the contract in).

- [ ] **Step 4: Commit**

```bash
git add tests/test_project_handlers.py
git commit -m "Add event-publishing assertions for project CRUD"
```

---

## Task 11: Final verification

- [ ] **Step 1: Run the full project test suite**

Run: `uv run pytest tests/test_shared_project_contracts.py tests/test_project_repository.py tests/test_project_handlers.py -v`
Expected: every test PASSES, no warnings about deprecated Pydantic v1 APIs.

- [ ] **Step 2: Run the broader test suite to catch any collateral damage**

Run: `uv run pytest -x`
Expected: full suite green. If anything fails, the failure must be triaged before declaring the task done — no skipping, no marking xfail.

- [ ] **Step 3: Syntax-check the new module**

Run: `uv run python -m py_compile backend/modules/project/__init__.py backend/modules/project/_models.py backend/modules/project/_repository.py backend/modules/project/_handlers.py shared/dtos/project.py shared/events/project.py`
Expected: no output (clean compile).

- [ ] **Step 4: Spot-check the running server**

Start the backend in a separate terminal: `uv run uvicorn backend.main:app --reload`
Then in another shell:

```bash
# (assumes you have a fresh DB and have run /api/setup once via the frontend or curl)
curl -s -X POST http://localhost:8000/api/projects \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"title":"Smoke","emoji":"🔥"}'
```

Expected: 201 with a `ProjectDto` JSON body. Skip this step if the test suite already passes — it is a sanity check, not a gate.

- [ ] **Step 5: Final commit (if anything was tweaked)**

If steps 1–4 surfaced fixes, commit them with a descriptive message. Otherwise, this step is a no-op.

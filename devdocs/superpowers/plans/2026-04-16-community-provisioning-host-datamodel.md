# Community Provisioning — Host Data Model + REST Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the host-side data model and REST API for Community
Provisioning: MongoDB collections for Homelabs and API-Keys, DTOs,
events, and CRUD endpoints under `/api/llm/homelabs`.

**Architecture:** Two new collections in the LLM module
(`llm_homelabs`, `llm_homelab_api_keys`). Two repository classes and
one service class in `backend/modules/llm/_homelabs.py`. REST handlers
in `backend/modules/llm/_homelab_handlers.py`. Tokens are generated
with `secrets.token_urlsafe`, stored as SHA-256 hashes + 4-char
hints. Plaintext keys appear only in REST response DTOs, never in
events.

**Tech Stack:** Python 3.12, FastAPI, Motor (async MongoDB), Pydantic
v2, pytest + pytest-asyncio, standard library `secrets` and
`hashlib`.

**Parent spec:** `docs/superpowers/specs/2026-04-16-community-provisioning-design.md`

---

## File Structure

**New files:**

- `backend/modules/llm/_homelab_tokens.py` — token generation, hashing, hint extraction
- `backend/modules/llm/_homelabs.py` — HomelabRepository, ApiKeyRepository, HomelabService
- `backend/modules/llm/_homelab_handlers.py` — REST endpoints under `/api/llm/homelabs`
- `backend/tests/modules/llm/test_homelab_tokens.py`
- `backend/tests/modules/llm/test_homelabs.py`
- `backend/tests/modules/llm/test_homelab_handlers.py`

**Modified files:**

- `shared/topics.py` — add 9 new topic constants
- `shared/dtos/llm.py` — add 6 homelab/api-key DTOs
- `shared/events/llm.py` — add 9 event classes
- `backend/modules/llm/__init__.py` — export `HomelabService`
- `backend/main.py` — include the new router, trigger repo index creation at startup

---

## Task 1: Topic Constants

**Files:**
- Modify: `shared/topics.py`

- [ ] **Step 1: Add topic constants in the LLM section**

Open `shared/topics.py`. Find the `# --- LLM Connections (connections refactor) ---` block. After the existing LLM topics, add:

```python
    # --- LLM Homelabs (community provisioning) ---
    LLM_HOMELAB_CREATED = "llm.homelab.created"
    LLM_HOMELAB_UPDATED = "llm.homelab.updated"
    LLM_HOMELAB_DELETED = "llm.homelab.deleted"
    LLM_HOMELAB_HOST_KEY_REGENERATED = "llm.homelab.host_key_regenerated"
    LLM_HOMELAB_STATUS_CHANGED = "llm.homelab.status_changed"
    LLM_HOMELAB_LAST_SEEN = "llm.homelab.last_seen"
    LLM_API_KEY_CREATED = "llm.api_key.created"
    LLM_API_KEY_UPDATED = "llm.api_key.updated"
    LLM_API_KEY_REVOKED = "llm.api_key.revoked"
```

- [ ] **Step 2: Verify import compiles**

Run: `uv run python -m py_compile shared/topics.py`
Expected: no output, exit 0.

- [ ] **Step 3: Commit**

```bash
git add shared/topics.py
git commit -m "Add homelab and api-key topic constants"
```

---

## Task 2: Token Helper — Generation, Hashing, Hint Extraction

**Files:**
- Create: `backend/modules/llm/_homelab_tokens.py`
- Create: `backend/tests/modules/llm/test_homelab_tokens.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/modules/llm/test_homelab_tokens.py`:

```python
import pytest

from backend.modules.llm._homelab_tokens import (
    HOMELAB_ID_LENGTH,
    API_KEY_PREFIX,
    HOST_KEY_PREFIX,
    generate_api_key,
    generate_homelab_id,
    generate_host_key,
    hash_token,
    hint_for,
)


def test_generate_host_key_has_prefix_and_length():
    key = generate_host_key()
    assert key.startswith(HOST_KEY_PREFIX)
    assert len(key) == len(HOST_KEY_PREFIX) + 43  # token_urlsafe(32)


def test_generate_api_key_has_prefix_and_length():
    key = generate_api_key()
    assert key.startswith(API_KEY_PREFIX)
    assert len(key) == len(API_KEY_PREFIX) + 43


def test_generate_homelab_id_length_and_charset():
    hid = generate_homelab_id()
    assert len(hid) == HOMELAB_ID_LENGTH == 11
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    assert set(hid) <= allowed


def test_generated_tokens_are_unique():
    seen = {generate_host_key() for _ in range(100)}
    assert len(seen) == 100


def test_hash_token_is_deterministic_hex_sha256():
    assert hash_token("cshost_abc") == hash_token("cshost_abc")
    assert len(hash_token("x")) == 64
    assert all(c in "0123456789abcdef" for c in hash_token("x"))


def test_hash_token_differs_for_different_inputs():
    assert hash_token("cshost_a") != hash_token("cshost_b")


def test_hint_for_returns_last_four_chars():
    assert hint_for("cshost_1234567890xyzwABCD") == "ABCD"


def test_hint_for_short_token_pads():
    assert hint_for("ab") == "ab"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/modules/llm/test_homelab_tokens.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.modules.llm._homelab_tokens'`.

- [ ] **Step 3: Implement the helper**

Create `backend/modules/llm/_homelab_tokens.py`:

```python
"""Token generation, hashing and hint extraction for Community Provisioning.

High-entropy random tokens (256 bits) are stored as SHA-256 hashes.
Per OWASP, a single SHA-256 pass is sufficient for high-entropy tokens;
slow hashes (argon2id) are unnecessary and prohibitively expensive on
the per-request validation path.
"""

from __future__ import annotations

import hashlib
import secrets

HOST_KEY_PREFIX = "cshost_"
API_KEY_PREFIX = "csapi_"
HOMELAB_ID_LENGTH = 11  # token_urlsafe(8) → 11 chars


def generate_host_key() -> str:
    return f"{HOST_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def generate_api_key() -> str:
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def generate_homelab_id() -> str:
    return secrets.token_urlsafe(8)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hint_for(token: str) -> str:
    return token[-4:] if len(token) >= 4 else token
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest backend/tests/modules/llm/test_homelab_tokens.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_homelab_tokens.py backend/tests/modules/llm/test_homelab_tokens.py
git commit -m "Add token helpers for community provisioning"
```

---

## Task 3: Shared DTOs

**Files:**
- Modify: `shared/dtos/llm.py`

- [ ] **Step 1: Append the homelab and api-key DTOs**

Append at the end of `shared/dtos/llm.py`:

```python
# --- Community Provisioning ---


class HomelabEngineInfoDto(BaseModel):
    type: str
    version: str | None = None


class HomelabDto(BaseModel):
    homelab_id: str
    display_name: str
    host_key_hint: str
    status: Literal["active", "revoked"]
    created_at: datetime
    last_seen_at: datetime | None = None
    last_sidecar_version: str | None = None
    last_engine_info: HomelabEngineInfoDto | None = None
    is_online: bool = False


class HomelabCreatedDto(HomelabDto):
    plaintext_host_key: str = Field(
        ..., description="Shown exactly once; never returned again."
    )


class HomelabHostKeyRegeneratedDto(HomelabDto):
    plaintext_host_key: str = Field(
        ..., description="Shown exactly once; never returned again."
    )


class CreateHomelabDto(BaseModel):
    display_name: str

    @field_validator("display_name")
    @classmethod
    def _name_len(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("display_name must not be empty")
        if len(v) > 80:
            raise ValueError("display_name must be 80 characters or fewer")
        return v


class UpdateHomelabDto(BaseModel):
    display_name: str | None = None

    @field_validator("display_name")
    @classmethod
    def _name_len(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("display_name must not be empty")
        if len(v) > 80:
            raise ValueError("display_name must be 80 characters or fewer")
        return v


class ApiKeyDto(BaseModel):
    api_key_id: str
    homelab_id: str
    display_name: str
    api_key_hint: str
    allowed_model_slugs: list[str]
    status: Literal["active", "revoked"]
    created_at: datetime
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None


class ApiKeyCreatedDto(ApiKeyDto):
    plaintext_api_key: str = Field(
        ..., description="Shown exactly once; never returned again."
    )


class CreateApiKeyDto(BaseModel):
    display_name: str
    allowed_model_slugs: list[str] = Field(default_factory=list)

    @field_validator("display_name")
    @classmethod
    def _name_len(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("display_name must not be empty")
        if len(v) > 80:
            raise ValueError("display_name must be 80 characters or fewer")
        return v


class UpdateApiKeyDto(BaseModel):
    display_name: str | None = None
    allowed_model_slugs: list[str] | None = None

    @field_validator("display_name")
    @classmethod
    def _name_len(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("display_name must not be empty")
        if len(v) > 80:
            raise ValueError("display_name must be 80 characters or fewer")
        return v
```

- [ ] **Step 2: Verify compile**

Run: `uv run python -m py_compile shared/dtos/llm.py`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add shared/dtos/llm.py
git commit -m "Add homelab and api-key DTOs"
```

---

## Task 4: Shared Events

**Files:**
- Modify: `shared/events/llm.py`

- [ ] **Step 1: Append event classes**

Open `shared/events/llm.py`. Inspect the existing file to see how events are declared (they extend a base class, carry `type` fields matching the Topics constants). Follow the existing style. Append:

```python
# --- Community Provisioning ---


class HomelabCreatedEvent(BaseEvent):
    type: Literal["llm.homelab.created"] = "llm.homelab.created"
    homelab: HomelabDto


class HomelabUpdatedEvent(BaseEvent):
    type: Literal["llm.homelab.updated"] = "llm.homelab.updated"
    homelab: HomelabDto


class HomelabDeletedEvent(BaseEvent):
    type: Literal["llm.homelab.deleted"] = "llm.homelab.deleted"
    homelab_id: str


class HomelabHostKeyRegeneratedEvent(BaseEvent):
    type: Literal["llm.homelab.host_key_regenerated"] = "llm.homelab.host_key_regenerated"
    homelab: HomelabDto


class HomelabStatusChangedEvent(BaseEvent):
    type: Literal["llm.homelab.status_changed"] = "llm.homelab.status_changed"
    homelab_id: str
    is_online: bool


class HomelabLastSeenEvent(BaseEvent):
    type: Literal["llm.homelab.last_seen"] = "llm.homelab.last_seen"
    homelab_id: str
    last_seen_at: datetime


class ApiKeyCreatedEvent(BaseEvent):
    type: Literal["llm.api_key.created"] = "llm.api_key.created"
    api_key: ApiKeyDto


class ApiKeyUpdatedEvent(BaseEvent):
    type: Literal["llm.api_key.updated"] = "llm.api_key.updated"
    api_key: ApiKeyDto


class ApiKeyRevokedEvent(BaseEvent):
    type: Literal["llm.api_key.revoked"] = "llm.api_key.revoked"
    api_key_id: str
    homelab_id: str
```

Add these imports at the top of the file (or to the existing import block):

```python
from datetime import datetime
from typing import Literal

from shared.dtos.llm import ApiKeyDto, HomelabDto
```

- [ ] **Step 2: Verify compile**

Run: `uv run python -m py_compile shared/events/llm.py`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add shared/events/llm.py
git commit -m "Add homelab and api-key event classes"
```

---

## Task 5: HomelabRepository — Core CRUD

**Files:**
- Create: `backend/modules/llm/_homelabs.py`
- Create: `backend/tests/modules/llm/test_homelabs.py`

- [ ] **Step 1: Write the failing test for HomelabRepository**

Create `backend/tests/modules/llm/test_homelabs.py`:

```python
import pytest
from datetime import UTC, datetime

from backend.modules.llm._homelab_tokens import (
    HOST_KEY_PREFIX,
    hash_token,
    hint_for,
)
from backend.modules.llm._homelabs import (
    HomelabNotFoundError,
    HomelabRepository,
    TooManyHomelabsError,
)


@pytest.mark.asyncio
async def test_create_homelab_returns_plaintext_key_once(mongo_db):
    repo = HomelabRepository(mongo_db)
    await repo.create_indexes()
    homelab, plaintext = await repo.create(user_id="u1", display_name="Wohnzimmer-GPU")
    assert plaintext.startswith(HOST_KEY_PREFIX)
    assert homelab["display_name"] == "Wohnzimmer-GPU"
    assert homelab["user_id"] == "u1"
    assert homelab["status"] == "active"
    assert homelab["host_key_hash"] == hash_token(plaintext)
    assert homelab["host_key_hint"] == hint_for(plaintext)
    assert "plaintext" not in homelab


@pytest.mark.asyncio
async def test_list_returns_only_owner_homelabs(mongo_db):
    repo = HomelabRepository(mongo_db)
    await repo.create_indexes()
    await repo.create(user_id="u1", display_name="A")
    await repo.create(user_id="u1", display_name="B")
    await repo.create(user_id="u2", display_name="C")
    out = await repo.list(user_id="u1")
    assert [h["display_name"] for h in out] == ["A", "B"]


@pytest.mark.asyncio
async def test_get_by_homelab_id_scoped_to_user(mongo_db):
    repo = HomelabRepository(mongo_db)
    await repo.create_indexes()
    homelab, _ = await repo.create(user_id="u1", display_name="A")
    got = await repo.get(user_id="u1", homelab_id=homelab["homelab_id"])
    assert got["display_name"] == "A"
    with pytest.raises(HomelabNotFoundError):
        await repo.get(user_id="u2", homelab_id=homelab["homelab_id"])


@pytest.mark.asyncio
async def test_rename(mongo_db):
    repo = HomelabRepository(mongo_db)
    await repo.create_indexes()
    homelab, _ = await repo.create(user_id="u1", display_name="A")
    updated = await repo.rename(
        user_id="u1", homelab_id=homelab["homelab_id"], display_name="B"
    )
    assert updated["display_name"] == "B"


@pytest.mark.asyncio
async def test_delete(mongo_db):
    repo = HomelabRepository(mongo_db)
    await repo.create_indexes()
    homelab, _ = await repo.create(user_id="u1", display_name="A")
    await repo.delete(user_id="u1", homelab_id=homelab["homelab_id"])
    with pytest.raises(HomelabNotFoundError):
        await repo.get(user_id="u1", homelab_id=homelab["homelab_id"])


@pytest.mark.asyncio
async def test_regenerate_host_key_updates_hash_and_returns_new_plaintext(mongo_db):
    repo = HomelabRepository(mongo_db)
    await repo.create_indexes()
    homelab, plaintext = await repo.create(user_id="u1", display_name="A")
    new_homelab, new_plaintext = await repo.regenerate_host_key(
        user_id="u1", homelab_id=homelab["homelab_id"]
    )
    assert new_plaintext != plaintext
    assert new_homelab["host_key_hash"] == hash_token(new_plaintext)


@pytest.mark.asyncio
async def test_find_by_host_key_hash(mongo_db):
    repo = HomelabRepository(mongo_db)
    await repo.create_indexes()
    homelab, plaintext = await repo.create(user_id="u1", display_name="A")
    found = await repo.find_by_host_key_hash(hash_token(plaintext))
    assert found["homelab_id"] == homelab["homelab_id"]
    assert await repo.find_by_host_key_hash("nope") is None


@pytest.mark.asyncio
async def test_sanity_cap_on_create(mongo_db):
    repo = HomelabRepository(mongo_db, max_per_user=2)
    await repo.create_indexes()
    await repo.create(user_id="u1", display_name="A")
    await repo.create(user_id="u1", display_name="B")
    with pytest.raises(TooManyHomelabsError):
        await repo.create(user_id="u1", display_name="C")
```

The `mongo_db` fixture must already exist in the Chatsune test suite (it does — see `backend/tests/conftest.py` for the existing pattern; if there is a `db_fixture` or similar instead, use that). If the fixture name differs, adjust the tests accordingly before running.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/modules/llm/test_homelabs.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement HomelabRepository**

Create `backend/modules/llm/_homelabs.py` with the repository class (the API-key repo and service go in later tasks — keep commits focused):

```python
"""Host-side community provisioning: homelabs and their api-keys."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.modules.llm._homelab_tokens import (
    generate_api_key,
    generate_homelab_id,
    generate_host_key,
    hash_token,
    hint_for,
)

_log = logging.getLogger(__name__)


class HomelabNotFoundError(KeyError):
    pass


class ApiKeyNotFoundError(KeyError):
    pass


class TooManyHomelabsError(RuntimeError):
    pass


class TooManyApiKeysError(RuntimeError):
    pass


class HomelabRepository:
    def __init__(
        self, db: AsyncIOMotorDatabase, max_per_user: int = 10
    ) -> None:
        self._col = db["llm_homelabs"]
        self._max_per_user = max_per_user

    async def create_indexes(self) -> None:
        await self._col.create_index("homelab_id", unique=True)
        await self._col.create_index("host_key_hash", unique=True)
        await self._col.create_index([("user_id", 1), ("created_at", 1)])

    async def create(
        self, user_id: str, display_name: str
    ) -> tuple[dict, str]:
        count = await self._col.count_documents({"user_id": user_id})
        if count >= self._max_per_user:
            raise TooManyHomelabsError(
                f"User {user_id} already has {count} homelabs (max {self._max_per_user})"
            )
        plaintext = generate_host_key()
        now = datetime.now(UTC)
        doc = {
            "user_id": user_id,
            "homelab_id": generate_homelab_id(),
            "display_name": display_name,
            "host_key_hash": hash_token(plaintext),
            "host_key_hint": hint_for(plaintext),
            "status": "active",
            "created_at": now,
            "last_seen_at": None,
            "last_sidecar_version": None,
            "last_engine_info": None,
        }
        await self._col.insert_one(doc)
        return doc, plaintext

    async def list(self, user_id: str) -> list[dict]:
        cursor = self._col.find({"user_id": user_id}).sort("created_at", 1)
        return [doc async for doc in cursor]

    async def get(self, user_id: str, homelab_id: str) -> dict:
        doc = await self._col.find_one(
            {"user_id": user_id, "homelab_id": homelab_id}
        )
        if doc is None:
            raise HomelabNotFoundError(homelab_id)
        return doc

    async def rename(
        self, user_id: str, homelab_id: str, display_name: str
    ) -> dict:
        res = await self._col.find_one_and_update(
            {"user_id": user_id, "homelab_id": homelab_id},
            {"$set": {"display_name": display_name}},
            return_document=True,
        )
        if res is None:
            raise HomelabNotFoundError(homelab_id)
        return res

    async def delete(self, user_id: str, homelab_id: str) -> None:
        res = await self._col.delete_one(
            {"user_id": user_id, "homelab_id": homelab_id}
        )
        if res.deleted_count == 0:
            raise HomelabNotFoundError(homelab_id)

    async def regenerate_host_key(
        self, user_id: str, homelab_id: str
    ) -> tuple[dict, str]:
        plaintext = generate_host_key()
        res = await self._col.find_one_and_update(
            {"user_id": user_id, "homelab_id": homelab_id},
            {
                "$set": {
                    "host_key_hash": hash_token(plaintext),
                    "host_key_hint": hint_for(plaintext),
                }
            },
            return_document=True,
        )
        if res is None:
            raise HomelabNotFoundError(homelab_id)
        return res, plaintext

    async def find_by_host_key_hash(self, host_key_hash: str) -> dict | None:
        return await self._col.find_one(
            {"host_key_hash": host_key_hash, "status": "active"}
        )

    async def touch_last_seen(
        self,
        homelab_id: str,
        sidecar_version: str | None,
        engine_info: dict | None,
    ) -> None:
        await self._col.update_one(
            {"homelab_id": homelab_id},
            {
                "$set": {
                    "last_seen_at": datetime.now(UTC),
                    "last_sidecar_version": sidecar_version,
                    "last_engine_info": engine_info,
                }
            },
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest backend/tests/modules/llm/test_homelabs.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_homelabs.py backend/tests/modules/llm/test_homelabs.py
git commit -m "Add HomelabRepository with CRUD and host-key rotation"
```

---

## Task 6: ApiKeyRepository

**Files:**
- Modify: `backend/modules/llm/_homelabs.py`
- Modify: `backend/tests/modules/llm/test_homelabs.py`

- [ ] **Step 1: Append failing tests for ApiKeyRepository**

Append to `backend/tests/modules/llm/test_homelabs.py`:

```python
from backend.modules.llm._homelab_tokens import API_KEY_PREFIX
from backend.modules.llm._homelabs import ApiKeyRepository


@pytest.mark.asyncio
async def test_create_api_key_returns_plaintext_once(mongo_db):
    hrepo = HomelabRepository(mongo_db)
    krepo = ApiKeyRepository(mongo_db)
    await hrepo.create_indexes()
    await krepo.create_indexes()
    homelab, _ = await hrepo.create(user_id="u1", display_name="A")
    key_doc, plaintext = await krepo.create(
        user_id="u1",
        homelab_id=homelab["homelab_id"],
        display_name="Bob",
        allowed_model_slugs=["llama3.2:8b"],
    )
    assert plaintext.startswith(API_KEY_PREFIX)
    assert key_doc["display_name"] == "Bob"
    assert key_doc["allowed_model_slugs"] == ["llama3.2:8b"]
    assert key_doc["status"] == "active"
    assert key_doc["api_key_hash"] == hash_token(plaintext)


@pytest.mark.asyncio
async def test_list_api_keys_scoped_to_homelab(mongo_db):
    hrepo = HomelabRepository(mongo_db)
    krepo = ApiKeyRepository(mongo_db)
    await hrepo.create_indexes()
    await krepo.create_indexes()
    h1, _ = await hrepo.create(user_id="u1", display_name="A")
    h2, _ = await hrepo.create(user_id="u1", display_name="B")
    await krepo.create(user_id="u1", homelab_id=h1["homelab_id"], display_name="Key1", allowed_model_slugs=[])
    await krepo.create(user_id="u1", homelab_id=h1["homelab_id"], display_name="Key2", allowed_model_slugs=[])
    await krepo.create(user_id="u1", homelab_id=h2["homelab_id"], display_name="Key3", allowed_model_slugs=[])
    keys = await krepo.list(homelab_id=h1["homelab_id"])
    assert sorted(k["display_name"] for k in keys) == ["Key1", "Key2"]


@pytest.mark.asyncio
async def test_revoke_flips_status(mongo_db):
    hrepo = HomelabRepository(mongo_db)
    krepo = ApiKeyRepository(mongo_db)
    await hrepo.create_indexes()
    await krepo.create_indexes()
    homelab, _ = await hrepo.create(user_id="u1", display_name="A")
    key_doc, _ = await krepo.create(
        user_id="u1",
        homelab_id=homelab["homelab_id"],
        display_name="K",
        allowed_model_slugs=[],
    )
    await krepo.revoke(user_id="u1", homelab_id=homelab["homelab_id"], api_key_id=key_doc["api_key_id"])
    refreshed = await krepo.get(user_id="u1", homelab_id=homelab["homelab_id"], api_key_id=key_doc["api_key_id"])
    assert refreshed["status"] == "revoked"
    assert refreshed["revoked_at"] is not None


@pytest.mark.asyncio
async def test_update_rename_and_allowlist(mongo_db):
    hrepo = HomelabRepository(mongo_db)
    krepo = ApiKeyRepository(mongo_db)
    await hrepo.create_indexes()
    await krepo.create_indexes()
    homelab, _ = await hrepo.create(user_id="u1", display_name="A")
    key_doc, _ = await krepo.create(
        user_id="u1", homelab_id=homelab["homelab_id"], display_name="K", allowed_model_slugs=[],
    )
    updated = await krepo.update(
        user_id="u1",
        homelab_id=homelab["homelab_id"],
        api_key_id=key_doc["api_key_id"],
        display_name="K2",
        allowed_model_slugs=["llama3.2:8b", "mistral:7b"],
    )
    assert updated["display_name"] == "K2"
    assert updated["allowed_model_slugs"] == ["llama3.2:8b", "mistral:7b"]


@pytest.mark.asyncio
async def test_find_active_by_hash_with_homelab_scope(mongo_db):
    hrepo = HomelabRepository(mongo_db)
    krepo = ApiKeyRepository(mongo_db)
    await hrepo.create_indexes()
    await krepo.create_indexes()
    homelab, _ = await hrepo.create(user_id="u1", display_name="A")
    _, plaintext = await krepo.create(
        user_id="u1", homelab_id=homelab["homelab_id"], display_name="K", allowed_model_slugs=[],
    )
    got = await krepo.find_active_by_hash(
        homelab_id=homelab["homelab_id"], api_key_hash=hash_token(plaintext),
    )
    assert got is not None
    missing = await krepo.find_active_by_hash(
        homelab_id="other", api_key_hash=hash_token(plaintext),
    )
    assert missing is None


@pytest.mark.asyncio
async def test_sanity_cap_on_create(mongo_db):
    hrepo = HomelabRepository(mongo_db)
    krepo = ApiKeyRepository(mongo_db, max_per_homelab=2)
    await hrepo.create_indexes()
    await krepo.create_indexes()
    homelab, _ = await hrepo.create(user_id="u1", display_name="A")
    await krepo.create(user_id="u1", homelab_id=homelab["homelab_id"], display_name="A", allowed_model_slugs=[])
    await krepo.create(user_id="u1", homelab_id=homelab["homelab_id"], display_name="B", allowed_model_slugs=[])
    with pytest.raises(TooManyApiKeysError):
        await krepo.create(user_id="u1", homelab_id=homelab["homelab_id"], display_name="C", allowed_model_slugs=[])
```

- [ ] **Step 2: Run test — verify it fails**

Run: `uv run pytest backend/tests/modules/llm/test_homelabs.py -v`
Expected: 6 new tests fail on `ImportError: cannot import name 'ApiKeyRepository'`.

- [ ] **Step 3: Implement ApiKeyRepository**

Append to `backend/modules/llm/_homelabs.py`:

```python
import secrets as _secrets  # at top


class ApiKeyRepository:
    def __init__(
        self, db: AsyncIOMotorDatabase, max_per_homelab: int = 50
    ) -> None:
        self._col = db["llm_homelab_api_keys"]
        self._max_per_homelab = max_per_homelab

    async def create_indexes(self) -> None:
        await self._col.create_index("api_key_hash", unique=True)
        await self._col.create_index([("homelab_id", 1), ("created_at", 1)])

    async def create(
        self,
        user_id: str,
        homelab_id: str,
        display_name: str,
        allowed_model_slugs: list[str],
    ) -> tuple[dict, str]:
        count = await self._col.count_documents({"homelab_id": homelab_id})
        if count >= self._max_per_homelab:
            raise TooManyApiKeysError(
                f"Homelab {homelab_id} already has {count} api-keys (max {self._max_per_homelab})"
            )
        plaintext = generate_api_key()
        now = datetime.now(UTC)
        doc = {
            "homelab_id": homelab_id,
            "user_id": user_id,
            "api_key_id": _secrets.token_urlsafe(8),
            "display_name": display_name,
            "api_key_hash": hash_token(plaintext),
            "api_key_hint": hint_for(plaintext),
            "allowed_model_slugs": list(allowed_model_slugs),
            "status": "active",
            "created_at": now,
            "revoked_at": None,
            "last_used_at": None,
        }
        await self._col.insert_one(doc)
        return doc, plaintext

    async def list(self, homelab_id: str) -> list[dict]:
        cursor = self._col.find({"homelab_id": homelab_id}).sort("created_at", 1)
        return [doc async for doc in cursor]

    async def get(
        self, user_id: str, homelab_id: str, api_key_id: str
    ) -> dict:
        doc = await self._col.find_one(
            {
                "user_id": user_id,
                "homelab_id": homelab_id,
                "api_key_id": api_key_id,
            }
        )
        if doc is None:
            raise ApiKeyNotFoundError(api_key_id)
        return doc

    async def update(
        self,
        user_id: str,
        homelab_id: str,
        api_key_id: str,
        display_name: str | None = None,
        allowed_model_slugs: list[str] | None = None,
    ) -> dict:
        set_fields: dict = {}
        if display_name is not None:
            set_fields["display_name"] = display_name
        if allowed_model_slugs is not None:
            set_fields["allowed_model_slugs"] = list(allowed_model_slugs)
        if not set_fields:
            return await self.get(user_id, homelab_id, api_key_id)
        res = await self._col.find_one_and_update(
            {
                "user_id": user_id,
                "homelab_id": homelab_id,
                "api_key_id": api_key_id,
            },
            {"$set": set_fields},
            return_document=True,
        )
        if res is None:
            raise ApiKeyNotFoundError(api_key_id)
        return res

    async def revoke(
        self, user_id: str, homelab_id: str, api_key_id: str
    ) -> dict:
        now = datetime.now(UTC)
        res = await self._col.find_one_and_update(
            {
                "user_id": user_id,
                "homelab_id": homelab_id,
                "api_key_id": api_key_id,
            },
            {"$set": {"status": "revoked", "revoked_at": now}},
            return_document=True,
        )
        if res is None:
            raise ApiKeyNotFoundError(api_key_id)
        return res

    async def regenerate(
        self, user_id: str, homelab_id: str, api_key_id: str
    ) -> tuple[dict, str]:
        plaintext = generate_api_key()
        res = await self._col.find_one_and_update(
            {
                "user_id": user_id,
                "homelab_id": homelab_id,
                "api_key_id": api_key_id,
            },
            {
                "$set": {
                    "api_key_hash": hash_token(plaintext),
                    "api_key_hint": hint_for(plaintext),
                    "status": "active",
                    "revoked_at": None,
                }
            },
            return_document=True,
        )
        if res is None:
            raise ApiKeyNotFoundError(api_key_id)
        return res, plaintext

    async def find_active_by_hash(
        self, homelab_id: str, api_key_hash: str
    ) -> dict | None:
        return await self._col.find_one(
            {
                "homelab_id": homelab_id,
                "api_key_hash": api_key_hash,
                "status": "active",
            }
        )

    async def delete_for_homelab(self, homelab_id: str) -> int:
        res = await self._col.delete_many({"homelab_id": homelab_id})
        return res.deleted_count
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `uv run pytest backend/tests/modules/llm/test_homelabs.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_homelabs.py backend/tests/modules/llm/test_homelabs.py
git commit -m "Add ApiKeyRepository for homelab api-keys"
```

---

## Task 7: HomelabService (events + cascade delete)

**Files:**
- Modify: `backend/modules/llm/_homelabs.py`
- Modify: `backend/tests/modules/llm/test_homelabs.py`

- [ ] **Step 1: Append failing tests for HomelabService**

Append to `backend/tests/modules/llm/test_homelabs.py`:

```python
from unittest.mock import AsyncMock

from backend.modules.llm._homelabs import HomelabService
from shared.topics import Topics


@pytest.mark.asyncio
async def test_create_homelab_publishes_event(mongo_db):
    bus = AsyncMock()
    svc = HomelabService(mongo_db, bus)
    await svc.init()
    result = await svc.create_homelab(user_id="u1", display_name="A")
    assert result["plaintext_host_key"].startswith("cshost_")
    assert "plaintext_host_key" not in result["homelab"]
    bus.publish_to_users.assert_awaited_once()
    kwargs = bus.publish_to_users.call_args.kwargs
    assert kwargs["topic"] == Topics.LLM_HOMELAB_CREATED
    assert kwargs["user_ids"] == ["u1"]


@pytest.mark.asyncio
async def test_delete_homelab_cascades_api_keys(mongo_db):
    bus = AsyncMock()
    svc = HomelabService(mongo_db, bus)
    await svc.init()
    created = await svc.create_homelab(user_id="u1", display_name="A")
    hid = created["homelab"]["homelab_id"]
    await svc.create_api_key(
        user_id="u1", homelab_id=hid, display_name="K", allowed_model_slugs=[]
    )
    await svc.create_api_key(
        user_id="u1", homelab_id=hid, display_name="L", allowed_model_slugs=[]
    )
    await svc.delete_homelab(user_id="u1", homelab_id=hid)
    remaining = await svc._keys.list(homelab_id=hid)
    assert remaining == []


@pytest.mark.asyncio
async def test_create_api_key_publishes_event(mongo_db):
    bus = AsyncMock()
    svc = HomelabService(mongo_db, bus)
    await svc.init()
    created = await svc.create_homelab(user_id="u1", display_name="A")
    bus.reset_mock()
    await svc.create_api_key(
        user_id="u1",
        homelab_id=created["homelab"]["homelab_id"],
        display_name="Bob",
        allowed_model_slugs=["llama3.2:8b"],
    )
    bus.publish_to_users.assert_awaited_once()
    assert bus.publish_to_users.call_args.kwargs["topic"] == Topics.LLM_API_KEY_CREATED
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `uv run pytest backend/tests/modules/llm/test_homelabs.py::test_create_homelab_publishes_event -v`
Expected: `ImportError: cannot import name 'HomelabService'`.

- [ ] **Step 3: Implement HomelabService**

Append to `backend/modules/llm/_homelabs.py`:

```python
from motor.motor_asyncio import AsyncIOMotorDatabase

from shared.dtos.llm import ApiKeyDto, HomelabDto, HomelabEngineInfoDto
from shared.events.llm import (
    ApiKeyCreatedEvent,
    ApiKeyRevokedEvent,
    ApiKeyUpdatedEvent,
    HomelabCreatedEvent,
    HomelabDeletedEvent,
    HomelabHostKeyRegeneratedEvent,
    HomelabUpdatedEvent,
)
from shared.topics import Topics


def _homelab_doc_to_dto(doc: dict, is_online: bool = False) -> HomelabDto:
    engine_info = None
    if doc.get("last_engine_info"):
        engine_info = HomelabEngineInfoDto(**doc["last_engine_info"])
    return HomelabDto(
        homelab_id=doc["homelab_id"],
        display_name=doc["display_name"],
        host_key_hint=doc["host_key_hint"],
        status=doc["status"],
        created_at=doc["created_at"],
        last_seen_at=doc.get("last_seen_at"),
        last_sidecar_version=doc.get("last_sidecar_version"),
        last_engine_info=engine_info,
        is_online=is_online,
    )


def _api_key_doc_to_dto(doc: dict) -> ApiKeyDto:
    return ApiKeyDto(
        api_key_id=doc["api_key_id"],
        homelab_id=doc["homelab_id"],
        display_name=doc["display_name"],
        api_key_hint=doc["api_key_hint"],
        allowed_model_slugs=list(doc.get("allowed_model_slugs", [])),
        status=doc["status"],
        created_at=doc["created_at"],
        revoked_at=doc.get("revoked_at"),
        last_used_at=doc.get("last_used_at"),
    )


class HomelabService:
    def __init__(self, db: AsyncIOMotorDatabase, event_bus) -> None:
        self._homelabs = HomelabRepository(db)
        self._keys = ApiKeyRepository(db)
        self._bus = event_bus

    async def init(self) -> None:
        await self._homelabs.create_indexes()
        await self._keys.create_indexes()

    # --- Homelab ops

    async def list_homelabs(
        self, user_id: str, online_ids: set[str] | None = None
    ) -> list[HomelabDto]:
        docs = await self._homelabs.list(user_id)
        online_ids = online_ids or set()
        return [
            _homelab_doc_to_dto(d, is_online=d["homelab_id"] in online_ids)
            for d in docs
        ]

    async def get_homelab(
        self, user_id: str, homelab_id: str, is_online: bool = False
    ) -> HomelabDto:
        doc = await self._homelabs.get(user_id, homelab_id)
        return _homelab_doc_to_dto(doc, is_online=is_online)

    async def create_homelab(
        self, user_id: str, display_name: str
    ) -> dict:
        doc, plaintext = await self._homelabs.create(user_id, display_name)
        dto = _homelab_doc_to_dto(doc)
        await self._bus.publish_to_users(
            topic=Topics.LLM_HOMELAB_CREATED,
            user_ids=[user_id],
            event=HomelabCreatedEvent(homelab=dto),
        )
        return {"homelab": dto.model_dump(), "plaintext_host_key": plaintext}

    async def rename_homelab(
        self, user_id: str, homelab_id: str, display_name: str
    ) -> HomelabDto:
        doc = await self._homelabs.rename(user_id, homelab_id, display_name)
        dto = _homelab_doc_to_dto(doc)
        await self._bus.publish_to_users(
            topic=Topics.LLM_HOMELAB_UPDATED,
            user_ids=[user_id],
            event=HomelabUpdatedEvent(homelab=dto),
        )
        return dto

    async def delete_homelab(self, user_id: str, homelab_id: str) -> None:
        # ensure ownership
        await self._homelabs.get(user_id, homelab_id)
        await self._keys.delete_for_homelab(homelab_id)
        await self._homelabs.delete(user_id, homelab_id)
        await self._bus.publish_to_users(
            topic=Topics.LLM_HOMELAB_DELETED,
            user_ids=[user_id],
            event=HomelabDeletedEvent(homelab_id=homelab_id),
        )

    async def regenerate_host_key(
        self, user_id: str, homelab_id: str
    ) -> dict:
        doc, plaintext = await self._homelabs.regenerate_host_key(
            user_id, homelab_id
        )
        dto = _homelab_doc_to_dto(doc)
        await self._bus.publish_to_users(
            topic=Topics.LLM_HOMELAB_HOST_KEY_REGENERATED,
            user_ids=[user_id],
            event=HomelabHostKeyRegeneratedEvent(homelab=dto),
        )
        return {"homelab": dto.model_dump(), "plaintext_host_key": plaintext}

    # --- API-key ops

    async def list_api_keys(
        self, user_id: str, homelab_id: str
    ) -> list[ApiKeyDto]:
        await self._homelabs.get(user_id, homelab_id)  # ownership check
        docs = await self._keys.list(homelab_id=homelab_id)
        return [_api_key_doc_to_dto(d) for d in docs]

    async def create_api_key(
        self,
        user_id: str,
        homelab_id: str,
        display_name: str,
        allowed_model_slugs: list[str],
    ) -> dict:
        await self._homelabs.get(user_id, homelab_id)  # ownership check
        doc, plaintext = await self._keys.create(
            user_id=user_id,
            homelab_id=homelab_id,
            display_name=display_name,
            allowed_model_slugs=allowed_model_slugs,
        )
        dto = _api_key_doc_to_dto(doc)
        await self._bus.publish_to_users(
            topic=Topics.LLM_API_KEY_CREATED,
            user_ids=[user_id],
            event=ApiKeyCreatedEvent(api_key=dto),
        )
        return {"api_key": dto.model_dump(), "plaintext_api_key": plaintext}

    async def update_api_key(
        self,
        user_id: str,
        homelab_id: str,
        api_key_id: str,
        display_name: str | None,
        allowed_model_slugs: list[str] | None,
    ) -> ApiKeyDto:
        await self._homelabs.get(user_id, homelab_id)
        doc = await self._keys.update(
            user_id=user_id,
            homelab_id=homelab_id,
            api_key_id=api_key_id,
            display_name=display_name,
            allowed_model_slugs=allowed_model_slugs,
        )
        dto = _api_key_doc_to_dto(doc)
        await self._bus.publish_to_users(
            topic=Topics.LLM_API_KEY_UPDATED,
            user_ids=[user_id],
            event=ApiKeyUpdatedEvent(api_key=dto),
        )
        return dto

    async def revoke_api_key(
        self, user_id: str, homelab_id: str, api_key_id: str
    ) -> None:
        await self._homelabs.get(user_id, homelab_id)
        await self._keys.revoke(user_id, homelab_id, api_key_id)
        await self._bus.publish_to_users(
            topic=Topics.LLM_API_KEY_REVOKED,
            user_ids=[user_id],
            event=ApiKeyRevokedEvent(
                api_key_id=api_key_id, homelab_id=homelab_id
            ),
        )

    async def regenerate_api_key(
        self, user_id: str, homelab_id: str, api_key_id: str
    ) -> dict:
        await self._homelabs.get(user_id, homelab_id)
        doc, plaintext = await self._keys.regenerate(
            user_id, homelab_id, api_key_id
        )
        dto = _api_key_doc_to_dto(doc)
        await self._bus.publish_to_users(
            topic=Topics.LLM_API_KEY_UPDATED,
            user_ids=[user_id],
            event=ApiKeyUpdatedEvent(api_key=dto),
        )
        return {"api_key": dto.model_dump(), "plaintext_api_key": plaintext}

    # --- Sidecar-auth helpers (used later by CSP)

    async def resolve_homelab_by_host_key(self, plaintext: str) -> dict | None:
        return await self._homelabs.find_by_host_key_hash(
            hash_token(plaintext)
        )

    async def validate_consumer_access(
        self, homelab_id: str, api_key_plaintext: str, model_slug: str
    ) -> dict | None:
        doc = await self._keys.find_active_by_hash(
            homelab_id=homelab_id, api_key_hash=hash_token(api_key_plaintext)
        )
        if doc is None:
            return None
        if model_slug not in doc["allowed_model_slugs"]:
            return None
        return doc
```

Note: `publish_to_users` is the existing event-bus method in
`backend/ws/event_bus.py`. If the real method has a different name,
adjust both the service and the tests. Verify by running
`rg "def publish" backend/ws/event_bus.py`.

- [ ] **Step 4: Run tests — verify they pass**

Run: `uv run pytest backend/tests/modules/llm/test_homelabs.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_homelabs.py backend/tests/modules/llm/test_homelabs.py
git commit -m "Add HomelabService with event emission and cascade delete"
```

---

## Task 8: REST Handlers — Homelabs

**Files:**
- Create: `backend/modules/llm/_homelab_handlers.py`
- Create: `backend/tests/modules/llm/test_homelab_handlers.py`

- [ ] **Step 1: Write failing handler tests**

Study `backend/modules/llm/_handlers.py:1-70` and
`backend/tests/modules/llm/` (whichever existing file drives REST
through FastAPI TestClient) for the house pattern. Then create
`backend/tests/modules/llm/test_homelab_handlers.py`:

```python
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_list_rename_delete_homelab(authed_client: AsyncClient):
    r = await authed_client.post("/api/llm/homelabs", json={"display_name": "Wohnzimmer"})
    assert r.status_code == 201
    created = r.json()
    assert created["display_name"] == "Wohnzimmer"
    assert created["plaintext_host_key"].startswith("cshost_")
    hid = created["homelab_id"]

    r = await authed_client.get("/api/llm/homelabs")
    assert r.status_code == 200
    lst = r.json()
    assert any(h["homelab_id"] == hid for h in lst)
    assert all("plaintext_host_key" not in h for h in lst)

    r = await authed_client.patch(
        f"/api/llm/homelabs/{hid}", json={"display_name": "Wohnzimmer-GPU"}
    )
    assert r.status_code == 200
    assert r.json()["display_name"] == "Wohnzimmer-GPU"

    r = await authed_client.delete(f"/api/llm/homelabs/{hid}")
    assert r.status_code == 204

    r = await authed_client.get("/api/llm/homelabs")
    assert all(h["homelab_id"] != hid for h in r.json())


@pytest.mark.asyncio
async def test_regenerate_host_key_returns_new_plaintext(authed_client: AsyncClient):
    r = await authed_client.post("/api/llm/homelabs", json={"display_name": "A"})
    hid = r.json()["homelab_id"]
    original = r.json()["plaintext_host_key"]

    r = await authed_client.post(f"/api/llm/homelabs/{hid}/regenerate-host-key")
    assert r.status_code == 200
    new_plaintext = r.json()["plaintext_host_key"]
    assert new_plaintext.startswith("cshost_")
    assert new_plaintext != original


@pytest.mark.asyncio
async def test_cannot_access_other_user_homelab(
    authed_client_user1: AsyncClient, authed_client_user2: AsyncClient
):
    r = await authed_client_user1.post(
        "/api/llm/homelabs", json={"display_name": "U1's"}
    )
    hid = r.json()["homelab_id"]

    r = await authed_client_user2.get(f"/api/llm/homelabs/{hid}")
    assert r.status_code == 404

    r = await authed_client_user2.delete(f"/api/llm/homelabs/{hid}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_too_many_homelabs_returns_409(authed_client: AsyncClient, monkeypatch):
    # Cap is enforced in the repo; handlers map TooManyHomelabsError → 409.
    from backend.modules.llm import _homelabs as _h

    monkeypatch.setattr(_h.HomelabRepository, "__init__", lambda self, db, max_per_user=2: _h.HomelabRepository.__init__.__wrapped__(self, db, max_per_user=2) if hasattr(_h.HomelabRepository.__init__, "__wrapped__") else None)
    # Simpler: just create until the default cap is hit (10). Adjust if
    # the test fixture sets a smaller cap.
    for i in range(10):
        r = await authed_client.post(
            "/api/llm/homelabs", json={"display_name": f"H{i}"}
        )
        assert r.status_code == 201
    r = await authed_client.post("/api/llm/homelabs", json={"display_name": "H11"})
    assert r.status_code == 409
```

The fixture names (`authed_client`, `authed_client_user1`,
`authed_client_user2`) must match what Chatsune's conftest exposes.
If the existing suite uses different helper names, adapt the tests
before running.

- [ ] **Step 2: Run tests — verify they fail**

Run: `uv run pytest backend/tests/modules/llm/test_homelab_handlers.py -v`
Expected: 404s because the router is not mounted yet.

- [ ] **Step 3: Implement the handlers**

Create `backend/modules/llm/_homelab_handlers.py`:

```python
"""REST endpoints for host-side community provisioning."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from backend.database import get_db
from backend.dependencies import require_active_session
from backend.modules.llm._homelabs import (
    ApiKeyNotFoundError,
    HomelabNotFoundError,
    HomelabService,
    TooManyApiKeysError,
    TooManyHomelabsError,
)
from backend.ws.event_bus import EventBus, get_event_bus
from shared.dtos.llm import (
    ApiKeyCreatedDto,
    ApiKeyDto,
    CreateApiKeyDto,
    CreateHomelabDto,
    HomelabCreatedDto,
    HomelabDto,
    HomelabHostKeyRegeneratedDto,
    UpdateApiKeyDto,
    UpdateHomelabDto,
)

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm/homelabs")


def _service(bus: EventBus = Depends(get_event_bus)) -> HomelabService:
    return HomelabService(get_db(), bus)


def _as_homelab_dto(d: dict) -> HomelabDto:
    return HomelabDto(**d)


def _as_api_key_dto(d: dict) -> ApiKeyDto:
    return ApiKeyDto(**d)


# --- Homelab CRUD ---


@router.post("", status_code=status.HTTP_201_CREATED, response_model=HomelabCreatedDto)
async def create_homelab(
    body: CreateHomelabDto,
    user: dict = Depends(require_active_session),
    svc: HomelabService = Depends(_service),
):
    try:
        result = await svc.create_homelab(
            user_id=user["user_id"], display_name=body.display_name
        )
    except TooManyHomelabsError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return HomelabCreatedDto(
        plaintext_host_key=result["plaintext_host_key"], **result["homelab"]
    )


@router.get("", response_model=list[HomelabDto])
async def list_homelabs(
    user: dict = Depends(require_active_session),
    svc: HomelabService = Depends(_service),
):
    from backend.modules.llm._csp._registry import (
        get_sidecar_registry,
    )  # Plan 3 dependency

    try:
        registry = get_sidecar_registry()
        online_ids = registry.online_homelab_ids()
    except Exception:
        online_ids = set()
    return await svc.list_homelabs(user["user_id"], online_ids=online_ids)


@router.get("/{homelab_id}", response_model=HomelabDto)
async def get_homelab(
    homelab_id: str,
    user: dict = Depends(require_active_session),
    svc: HomelabService = Depends(_service),
):
    try:
        from backend.modules.llm._csp._registry import (
            get_sidecar_registry,
        )

        registry = get_sidecar_registry()
        online = homelab_id in registry.online_homelab_ids()
    except Exception:
        online = False
    try:
        return await svc.get_homelab(user["user_id"], homelab_id, is_online=online)
    except HomelabNotFoundError:
        raise HTTPException(status_code=404, detail="homelab not found")


@router.patch("/{homelab_id}", response_model=HomelabDto)
async def update_homelab(
    homelab_id: str,
    body: UpdateHomelabDto,
    user: dict = Depends(require_active_session),
    svc: HomelabService = Depends(_service),
):
    if body.display_name is None:
        raise HTTPException(status_code=400, detail="nothing to update")
    try:
        return await svc.rename_homelab(
            user["user_id"], homelab_id, body.display_name
        )
    except HomelabNotFoundError:
        raise HTTPException(status_code=404, detail="homelab not found")


@router.delete("/{homelab_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_homelab(
    homelab_id: str,
    user: dict = Depends(require_active_session),
    svc: HomelabService = Depends(_service),
):
    try:
        await svc.delete_homelab(user["user_id"], homelab_id)
    except HomelabNotFoundError:
        raise HTTPException(status_code=404, detail="homelab not found")


@router.post(
    "/{homelab_id}/regenerate-host-key",
    response_model=HomelabHostKeyRegeneratedDto,
)
async def regenerate_host_key(
    homelab_id: str,
    user: dict = Depends(require_active_session),
    svc: HomelabService = Depends(_service),
):
    try:
        result = await svc.regenerate_host_key(user["user_id"], homelab_id)
    except HomelabNotFoundError:
        raise HTTPException(status_code=404, detail="homelab not found")
    return HomelabHostKeyRegeneratedDto(
        plaintext_host_key=result["plaintext_host_key"], **result["homelab"]
    )


# --- API-keys ---


@router.get("/{homelab_id}/api-keys", response_model=list[ApiKeyDto])
async def list_api_keys(
    homelab_id: str,
    user: dict = Depends(require_active_session),
    svc: HomelabService = Depends(_service),
):
    try:
        return await svc.list_api_keys(user["user_id"], homelab_id)
    except HomelabNotFoundError:
        raise HTTPException(status_code=404, detail="homelab not found")


@router.post(
    "/{homelab_id}/api-keys",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiKeyCreatedDto,
)
async def create_api_key(
    homelab_id: str,
    body: CreateApiKeyDto,
    user: dict = Depends(require_active_session),
    svc: HomelabService = Depends(_service),
):
    try:
        result = await svc.create_api_key(
            user_id=user["user_id"],
            homelab_id=homelab_id,
            display_name=body.display_name,
            allowed_model_slugs=body.allowed_model_slugs,
        )
    except HomelabNotFoundError:
        raise HTTPException(status_code=404, detail="homelab not found")
    except TooManyApiKeysError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return ApiKeyCreatedDto(
        plaintext_api_key=result["plaintext_api_key"], **result["api_key"]
    )


@router.patch("/{homelab_id}/api-keys/{api_key_id}", response_model=ApiKeyDto)
async def update_api_key(
    homelab_id: str,
    api_key_id: str,
    body: UpdateApiKeyDto,
    user: dict = Depends(require_active_session),
    svc: HomelabService = Depends(_service),
):
    if body.display_name is None and body.allowed_model_slugs is None:
        raise HTTPException(status_code=400, detail="nothing to update")
    try:
        return await svc.update_api_key(
            user_id=user["user_id"],
            homelab_id=homelab_id,
            api_key_id=api_key_id,
            display_name=body.display_name,
            allowed_model_slugs=body.allowed_model_slugs,
        )
    except (HomelabNotFoundError, ApiKeyNotFoundError):
        raise HTTPException(status_code=404, detail="not found")


@router.delete(
    "/{homelab_id}/api-keys/{api_key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_api_key(
    homelab_id: str,
    api_key_id: str,
    user: dict = Depends(require_active_session),
    svc: HomelabService = Depends(_service),
):
    try:
        await svc.revoke_api_key(user["user_id"], homelab_id, api_key_id)
    except (HomelabNotFoundError, ApiKeyNotFoundError):
        raise HTTPException(status_code=404, detail="not found")


@router.post(
    "/{homelab_id}/api-keys/{api_key_id}/regenerate",
    response_model=ApiKeyCreatedDto,
)
async def regenerate_api_key(
    homelab_id: str,
    api_key_id: str,
    user: dict = Depends(require_active_session),
    svc: HomelabService = Depends(_service),
):
    try:
        result = await svc.regenerate_api_key(
            user["user_id"], homelab_id, api_key_id
        )
    except (HomelabNotFoundError, ApiKeyNotFoundError):
        raise HTTPException(status_code=404, detail="not found")
    return ApiKeyCreatedDto(
        plaintext_api_key=result["plaintext_api_key"], **result["api_key"]
    )
```

The SidecarRegistry import is guarded with try/except because Plan 3
has not been executed yet. Once Plan 3 lands the imports still work,
the registry is populated, and the `is_online` flag becomes
meaningful.

- [ ] **Step 4: Register the router in main.py**

In `backend/main.py` find where the existing LLM handlers are mounted
(search for `from backend.modules.llm._handlers import router as
llm_router` or similar). Add next to it:

```python
from backend.modules.llm._homelab_handlers import router as llm_homelab_router
...
app.include_router(llm_homelab_router)
```

- [ ] **Step 5: Run tests — verify they pass**

Run: `uv run pytest backend/tests/modules/llm/test_homelab_handlers.py -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_homelab_handlers.py backend/tests/modules/llm/test_homelab_handlers.py backend/main.py
git commit -m "Add REST handlers for homelabs and api-keys"
```

---

## Task 9: Module Public API + Startup Wiring

**Files:**
- Modify: `backend/modules/llm/__init__.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Export the public API**

Open `backend/modules/llm/__init__.py`. Append:

```python
from backend.modules.llm._homelabs import (
    ApiKeyNotFoundError,
    HomelabNotFoundError,
    HomelabService,
    TooManyApiKeysError,
    TooManyHomelabsError,
)

__all__ = list(globals().get("__all__", [])) + [
    "HomelabService",
    "HomelabNotFoundError",
    "ApiKeyNotFoundError",
    "TooManyHomelabsError",
    "TooManyApiKeysError",
]
```

- [ ] **Step 2: Call `HomelabService.init()` on startup**

In `backend/main.py`, find the existing startup hook (probably
`@app.on_event("startup")` or a lifespan context). Inside it, after
the database is connected and other repos' indexes are created,
add:

```python
from backend.modules.llm import HomelabService
from backend.ws.event_bus import get_event_bus

homelab_svc = HomelabService(get_db(), get_event_bus())
await homelab_svc.init()
```

- [ ] **Step 3: Smoke test**

Run: `uv run pytest backend/tests/modules/llm/ -v`
Expected: all tests pass (including new ones from Tasks 2, 5–8).

- [ ] **Step 4: Commit**

```bash
git add backend/modules/llm/__init__.py backend/main.py
git commit -m "Expose HomelabService via LLM module public API and wire startup init"
```

---

## Self-Review

After completing all tasks, verify:

1. Every topic from §9.1 of the design spec is in `shared/topics.py`.
2. Every DTO from §9.2 exists in `shared/dtos/llm.py`.
3. Every event class from §9.3 exists in `shared/events/llm.py`.
4. Every REST endpoint from §9.4 responds (204/200/201 on success,
   404 on not-found, 409 on sanity-cap breach).
5. No cross-user access is possible (tests cover it).
6. `grep -n "argon2" backend/modules/llm/_homelabs.py backend/modules/llm/_homelab_tokens.py` — no matches. SHA-256 only.
7. Plaintext keys appear ONLY in `*CreatedDto` and `*HostKeyRegeneratedDto` REST responses, never in events (Grep `plaintext` in `shared/events/llm.py` — no matches).

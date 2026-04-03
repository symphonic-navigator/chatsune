# Global Settings & User Model Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add admin-managed global settings (key-value store) and per-user per-model configuration to complete the configuration layer before frontend work begins.

**Architecture:** Two independent feature areas. Feature A creates a new `settings` module with its own MongoDB collection, REST endpoints, and events. Feature B extends the existing `llm` module with a user model config repository, endpoints following the existing curation URL pattern, and a single event type (no separate delete event — reset emits updated with defaults).

**Tech Stack:** Python, FastAPI, Motor (MongoDB), Pydantic v2, Redis (event streams), pytest + httpx (testing)

---

### Task 1: Shared contracts for global settings

**Files:**
- Create: `shared/dtos/settings.py`
- Create: `shared/events/settings.py`
- Modify: `shared/topics.py`

- [ ] **Step 1: Write the failing test for shared contracts**

Create `tests/test_shared_settings_contracts.py`:

```python
import pytest
from pydantic import ValidationError

from shared.dtos.settings import AppSettingDto, SetSettingDto
from shared.events.settings import SettingDeletedEvent, SettingUpdatedEvent
from shared.topics import Topics


def test_app_setting_dto_round_trip():
    dto = AppSettingDto(
        key="global_system_prompt",
        value="Be helpful and harmless.",
        updated_at="2026-04-03T12:00:00Z",
        updated_by="admin-user-id",
    )
    assert dto.key == "global_system_prompt"
    assert dto.value == "Be helpful and harmless."
    assert dto.updated_by == "admin-user-id"


def test_set_setting_dto_requires_value():
    with pytest.raises(ValidationError):
        SetSettingDto()


def test_set_setting_dto_accepts_value():
    dto = SetSettingDto(value="Be safe.")
    assert dto.value == "Be safe."


def test_setting_updated_event():
    event = SettingUpdatedEvent(
        key="global_system_prompt",
        value="Be helpful.",
        updated_by="admin-id",
    )
    assert event.type == "setting.updated"
    assert event.key == "global_system_prompt"


def test_setting_deleted_event():
    event = SettingDeletedEvent(
        key="global_system_prompt",
        deleted_by="admin-id",
    )
    assert event.type == "setting.deleted"
    assert event.key == "global_system_prompt"


def test_topics_setting_constants():
    assert Topics.SETTING_UPDATED == "setting.updated"
    assert Topics.SETTING_DELETED == "setting.deleted"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chris/workspace/chatsune && docker compose run --rm backend pytest tests/test_shared_settings_contracts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shared.dtos.settings'`

- [ ] **Step 3: Create shared/dtos/settings.py**

```python
from datetime import datetime

from pydantic import BaseModel


class AppSettingDto(BaseModel):
    key: str
    value: str
    updated_at: datetime
    updated_by: str


class SetSettingDto(BaseModel):
    value: str
```

- [ ] **Step 4: Create shared/events/settings.py**

```python
from pydantic import BaseModel


class SettingUpdatedEvent(BaseModel):
    type: str = "setting.updated"
    key: str
    value: str
    updated_by: str


class SettingDeletedEvent(BaseModel):
    type: str = "setting.deleted"
    key: str
    deleted_by: str
```

- [ ] **Step 5: Add topic constants to shared/topics.py**

Add these two lines at the end of the `Topics` class in `shared/topics.py`:

```python
    SETTING_UPDATED = "setting.updated"
    SETTING_DELETED = "setting.deleted"
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd /home/chris/workspace/chatsune && docker compose run --rm backend pytest tests/test_shared_settings_contracts.py -v`
Expected: All 6 tests PASS

- [ ] **Step 7: Commit**

```bash
git add shared/dtos/settings.py shared/events/settings.py shared/topics.py tests/test_shared_settings_contracts.py
git commit -m "Add shared contracts for global settings (DTOs, events, topics)"
```

---

### Task 2: Settings module — repository

**Files:**
- Create: `backend/modules/settings/__init__.py`
- Create: `backend/modules/settings/_models.py`
- Create: `backend/modules/settings/_repository.py`

- [ ] **Step 1: Write the failing test for SettingsRepository**

Create `tests/test_settings_repository.py`:

```python
import pytest
from httpx import AsyncClient


async def _setup_admin(client: AsyncClient) -> str:
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


async def test_list_settings_empty(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.get("/api/settings", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == []


async def test_set_and_get_setting(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.put(
        "/api/settings/global_system_prompt",
        json={"value": "Be helpful and harmless."},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["key"] == "global_system_prompt"
    assert data["value"] == "Be helpful and harmless."
    assert data["updated_by"] is not None

    resp = await client.get(
        "/api/settings/global_system_prompt",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["value"] == "Be helpful and harmless."


async def test_update_setting_overwrites(client: AsyncClient):
    token = await _setup_admin(client)
    await client.put(
        "/api/settings/global_system_prompt",
        json={"value": "Version 1"},
        headers=_auth(token),
    )
    resp = await client.put(
        "/api/settings/global_system_prompt",
        json={"value": "Version 2"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["value"] == "Version 2"


async def test_get_nonexistent_setting(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.get(
        "/api/settings/nonexistent",
        headers=_auth(token),
    )
    assert resp.status_code == 404


async def test_delete_setting(client: AsyncClient):
    token = await _setup_admin(client)
    await client.put(
        "/api/settings/test_key",
        json={"value": "some value"},
        headers=_auth(token),
    )
    resp = await client.delete("/api/settings/test_key", headers=_auth(token))
    assert resp.status_code == 200

    resp = await client.get("/api/settings/test_key", headers=_auth(token))
    assert resp.status_code == 404


async def test_delete_nonexistent_setting(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.delete("/api/settings/nonexistent", headers=_auth(token))
    assert resp.status_code == 404


async def test_settings_require_admin(client: AsyncClient):
    admin_token = await _setup_admin(client)
    # Create a regular user
    create_resp = await client.post(
        "/api/admin/users",
        json={
            "username": "regular",
            "display_name": "Regular User",
            "email": "user@example.com",
        },
        headers=_auth(admin_token),
    )
    generated_pw = create_resp.json()["generated_password"]
    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "regular", "password": generated_pw},
    )
    user_token = login_resp.json()["access_token"]

    resp = await client.get("/api/settings", headers=_auth(user_token))
    assert resp.status_code == 403

    resp = await client.put(
        "/api/settings/test",
        json={"value": "nope"},
        headers=_auth(user_token),
    )
    assert resp.status_code == 403


async def test_list_settings_returns_all(client: AsyncClient):
    token = await _setup_admin(client)
    await client.put(
        "/api/settings/key_a",
        json={"value": "value a"},
        headers=_auth(token),
    )
    await client.put(
        "/api/settings/key_b",
        json={"value": "value b"},
        headers=_auth(token),
    )
    resp = await client.get("/api/settings", headers=_auth(token))
    assert resp.status_code == 200
    keys = [s["key"] for s in resp.json()]
    assert "key_a" in keys
    assert "key_b" in keys
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chris/workspace/chatsune && docker compose run --rm backend pytest tests/test_settings_repository.py -v`
Expected: FAIL — import or 404 errors

- [ ] **Step 3: Create backend/modules/settings/_models.py**

```python
from datetime import datetime

from pydantic import BaseModel, Field


class AppSettingDocument(BaseModel):
    """Internal MongoDB document for app settings. Never expose outside settings module."""

    key: str = Field(alias="_id")
    value: str
    updated_at: datetime
    updated_by: str

    model_config = {"populate_by_name": True}
```

- [ ] **Step 4: Create backend/modules/settings/_repository.py**

```python
from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

from shared.dtos.settings import AppSettingDto


class SettingsRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db["app_settings"]

    async def create_indexes(self) -> None:
        pass  # _id is the key, no extra indexes needed

    async def find(self, key: str) -> dict | None:
        return await self._collection.find_one({"_id": key})

    async def upsert(self, key: str, value: str, updated_by: str) -> dict:
        now = datetime.now(UTC)
        await self._collection.update_one(
            {"_id": key},
            {
                "$set": {
                    "value": value,
                    "updated_at": now,
                    "updated_by": updated_by,
                }
            },
            upsert=True,
        )
        return await self.find(key)

    async def delete(self, key: str) -> bool:
        result = await self._collection.delete_one({"_id": key})
        return result.deleted_count > 0

    async def list_all(self) -> list[dict]:
        cursor = self._collection.find()
        return await cursor.to_list(length=1000)

    @staticmethod
    def to_dto(doc: dict) -> AppSettingDto:
        return AppSettingDto(
            key=doc["_id"],
            value=doc["value"],
            updated_at=doc["updated_at"],
            updated_by=doc["updated_by"],
        )
```

- [ ] **Step 5: Create backend/modules/settings/_handlers.py**

```python
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from backend.database import get_db
from backend.dependencies import require_admin
from backend.modules.settings._repository import SettingsRepository
from backend.ws.event_bus import EventBus, get_event_bus
from shared.dtos.settings import SetSettingDto
from shared.events.settings import SettingDeletedEvent, SettingUpdatedEvent
from shared.topics import Topics

router = APIRouter(prefix="/api/settings")


def _repo() -> SettingsRepository:
    return SettingsRepository(get_db())


@router.get("")
async def list_settings(user: dict = Depends(require_admin)):
    repo = _repo()
    docs = await repo.list_all()
    return [SettingsRepository.to_dto(doc) for doc in docs]


@router.get("/{key}")
async def get_setting(key: str, user: dict = Depends(require_admin)):
    repo = _repo()
    doc = await repo.find(key)
    if not doc:
        raise HTTPException(status_code=404, detail="Setting not found")
    return SettingsRepository.to_dto(doc)


@router.put("/{key}", status_code=200)
async def set_setting(
    key: str,
    body: SetSettingDto,
    user: dict = Depends(require_admin),
    event_bus: EventBus = Depends(get_event_bus),
):
    repo = _repo()
    doc = await repo.upsert(key, body.value, user["sub"])

    await event_bus.publish(
        Topics.SETTING_UPDATED,
        SettingUpdatedEvent(
            key=key,
            value=body.value,
            updated_by=user["sub"],
        ),
    )

    return SettingsRepository.to_dto(doc)


@router.delete("/{key}", status_code=200)
async def delete_setting(
    key: str,
    user: dict = Depends(require_admin),
    event_bus: EventBus = Depends(get_event_bus),
):
    repo = _repo()
    deleted = await repo.delete(key)
    if not deleted:
        raise HTTPException(status_code=404, detail="Setting not found")

    await event_bus.publish(
        Topics.SETTING_DELETED,
        SettingDeletedEvent(
            key=key,
            deleted_by=user["sub"],
        ),
    )

    return {"status": "ok"}
```

- [ ] **Step 6: Create backend/modules/settings/__init__.py**

```python
"""Settings module — platform-wide admin-managed configuration.

Public API: import only from this file.
"""

from backend.modules.settings._handlers import router
from backend.modules.settings._repository import SettingsRepository


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the settings module collections."""
    await SettingsRepository(db).create_indexes()


__all__ = ["router", "init_indexes", "SettingsRepository"]
```

- [ ] **Step 7: Register settings module in main.py**

Add to imports in `backend/main.py`:

```python
from backend.modules.settings import router as settings_router, init_indexes as settings_init_indexes
```

Add to the `lifespan` function, after `await persona_init_indexes(db)`:

```python
    await settings_init_indexes(db)
```

Add after `app.include_router(persona_router)`:

```python
app.include_router(settings_router)
```

- [ ] **Step 8: Register fan-out rules in event_bus.py**

Add to the `_FANOUT` dict in `backend/ws/event_bus.py`, after the `LLM_CREDENTIAL_TESTED` entry:

```python
    Topics.SETTING_UPDATED: (["admin", "master_admin"], False),
    Topics.SETTING_DELETED: (["admin", "master_admin"], False),
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd /home/chris/workspace/chatsune && docker compose run --rm backend pytest tests/test_settings_repository.py -v`
Expected: All 8 tests PASS

- [ ] **Step 10: Run full test suite**

Run: `cd /home/chris/workspace/chatsune && docker compose run --rm backend pytest -v`
Expected: All existing tests still pass

- [ ] **Step 11: Commit**

```bash
git add backend/modules/settings/ tests/test_settings_repository.py backend/main.py backend/ws/event_bus.py
git commit -m "Add settings module with key-value store, REST endpoints, and events"
```

---

### Task 3: Shared contracts for user model config

**Files:**
- Modify: `shared/dtos/llm.py`
- Modify: `shared/events/llm.py`
- Modify: `shared/topics.py`

- [ ] **Step 1: Write the failing test for new shared contracts**

Create `tests/test_shared_user_model_config_contracts.py`:

```python
from shared.dtos.llm import UserModelConfigDto, SetUserModelConfigDto
from shared.events.llm import LlmUserModelConfigUpdatedEvent
from shared.topics import Topics


def test_user_model_config_dto():
    dto = UserModelConfigDto(
        model_unique_id="ollama_cloud:llama3.2",
        is_favourite=True,
        is_hidden=False,
        notes="Great for coding",
        system_prompt_addition="Focus on the last message.",
    )
    assert dto.model_unique_id == "ollama_cloud:llama3.2"
    assert dto.is_favourite is True
    assert dto.system_prompt_addition == "Focus on the last message."


def test_user_model_config_dto_defaults():
    dto = UserModelConfigDto(model_unique_id="ollama_cloud:llama3.2")
    assert dto.is_favourite is False
    assert dto.is_hidden is False
    assert dto.notes is None
    assert dto.system_prompt_addition is None


def test_set_user_model_config_dto_all_optional():
    dto = SetUserModelConfigDto()
    assert dto.is_favourite is None
    assert dto.is_hidden is None
    assert dto.notes is None
    assert dto.system_prompt_addition is None


def test_set_user_model_config_dto_partial():
    dto = SetUserModelConfigDto(is_favourite=True)
    assert dto.is_favourite is True
    assert dto.is_hidden is None


def test_user_model_config_updated_event():
    config = UserModelConfigDto(model_unique_id="ollama_cloud:llama3.2")
    event = LlmUserModelConfigUpdatedEvent(
        model_unique_id="ollama_cloud:llama3.2",
        config=config,
    )
    assert event.type == "llm.user_model_config.updated"
    assert event.config.is_favourite is False


def test_topic_constant():
    assert Topics.LLM_USER_MODEL_CONFIG_UPDATED == "llm.user_model_config.updated"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chris/workspace/chatsune && docker compose run --rm backend pytest tests/test_shared_user_model_config_contracts.py -v`
Expected: FAIL — `ImportError: cannot import name 'UserModelConfigDto'`

- [ ] **Step 3: Add DTOs to shared/dtos/llm.py**

Append to the end of `shared/dtos/llm.py`:

```python


class UserModelConfigDto(BaseModel):
    model_unique_id: str
    is_favourite: bool = False
    is_hidden: bool = False
    notes: str | None = None
    system_prompt_addition: str | None = None


class SetUserModelConfigDto(BaseModel):
    is_favourite: bool | None = None
    is_hidden: bool | None = None
    notes: str | None = None
    system_prompt_addition: str | None = None
```

- [ ] **Step 4: Add event to shared/events/llm.py**

Append to the end of `shared/events/llm.py`, adding the import at the top:

Add to imports:

```python
from shared.dtos.llm import ModelMetaDto, UserModelConfigDto
```

(Replace the existing `from shared.dtos.llm import ModelMetaDto` line.)

Append the new event class:

```python


class LlmUserModelConfigUpdatedEvent(BaseModel):
    """Emitted when a user updates OR deletes their model config. Delete sends defaults."""
    type: str = "llm.user_model_config.updated"
    model_unique_id: str
    config: UserModelConfigDto
```

- [ ] **Step 5: Add topic constant to shared/topics.py**

Add this line at the end of the `Topics` class in `shared/topics.py`:

```python
    LLM_USER_MODEL_CONFIG_UPDATED = "llm.user_model_config.updated"
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd /home/chris/workspace/chatsune && docker compose run --rm backend pytest tests/test_shared_user_model_config_contracts.py -v`
Expected: All 6 tests PASS

- [ ] **Step 7: Commit**

```bash
git add shared/dtos/llm.py shared/events/llm.py shared/topics.py tests/test_shared_user_model_config_contracts.py
git commit -m "Add shared contracts for user model config (DTOs, event, topic)"
```

---

### Task 4: User model config — repository and endpoints

**Files:**
- Create: `backend/modules/llm/_user_config.py`
- Modify: `backend/modules/llm/_models.py`
- Modify: `backend/modules/llm/_handlers.py`
- Modify: `backend/modules/llm/__init__.py`
- Modify: `backend/ws/event_bus.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_user_model_config.py`:

```python
from httpx import AsyncClient


async def _setup_admin(client: AsyncClient) -> str:
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


async def _setup_regular_user(client: AsyncClient, admin_token: str) -> str:
    create_resp = await client.post(
        "/api/admin/users",
        json={
            "username": "regular",
            "display_name": "Regular User",
            "email": "user@example.com",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    generated_pw = create_resp.json()["generated_password"]
    resp = await client.post(
        "/api/auth/login",
        json={"username": "regular", "password": generated_pw},
    )
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_get_config_returns_defaults_when_none_exists(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.get(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["model_unique_id"] == "ollama_cloud:llama3"
    assert data["is_favourite"] is False
    assert data["is_hidden"] is False
    assert data["notes"] is None
    assert data["system_prompt_addition"] is None


async def test_set_user_model_config(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        json={
            "is_favourite": True,
            "notes": "Good for general chat",
            "system_prompt_addition": "Focus on the last message in context.",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_favourite"] is True
    assert data["is_hidden"] is False
    assert data["notes"] == "Good for general chat"
    assert data["system_prompt_addition"] == "Focus on the last message in context."


async def test_update_config_partial(client: AsyncClient):
    token = await _setup_admin(client)
    await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        json={"is_favourite": True, "notes": "Nice model"},
        headers=_auth(token),
    )
    resp = await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        json={"is_hidden": True},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    # Previously set fields are preserved
    assert data["is_favourite"] is True
    assert data["notes"] == "Nice model"
    # Newly set field is applied
    assert data["is_hidden"] is True


async def test_delete_config_resets_to_defaults(client: AsyncClient):
    token = await _setup_admin(client)
    await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        json={"is_favourite": True, "notes": "Great"},
        headers=_auth(token),
    )
    resp = await client.delete(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        headers=_auth(token),
    )
    assert resp.status_code == 200

    resp = await client.get(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_favourite"] is False
    assert data["is_hidden"] is False
    assert data["notes"] is None


async def test_delete_config_when_none_exists(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.delete(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_favourite"] is False


async def test_list_user_configs(client: AsyncClient):
    token = await _setup_admin(client)
    await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        json={"is_favourite": True},
        headers=_auth(token),
    )
    await client.put(
        "/api/llm/providers/ollama_cloud/models/mistral/user-config",
        json={"notes": "Fast"},
        headers=_auth(token),
    )
    resp = await client.get(
        "/api/llm/user-model-configs",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    unique_ids = [c["model_unique_id"] for c in data]
    assert "ollama_cloud:llama3" in unique_ids
    assert "ollama_cloud:mistral" in unique_ids


async def test_configs_are_user_scoped(client: AsyncClient):
    admin_token = await _setup_admin(client)
    user_token = await _setup_regular_user(client, admin_token)

    # Admin sets a config
    await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        json={"is_favourite": True},
        headers=_auth(admin_token),
    )

    # Regular user sees defaults, not admin's config
    resp = await client.get(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    assert resp.json()["is_favourite"] is False


async def test_unknown_provider_returns_404(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.put(
        "/api/llm/providers/nonexistent/models/llama3/user-config",
        json={"is_favourite": True},
        headers=_auth(token),
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chris/workspace/chatsune && docker compose run --rm backend pytest tests/test_user_model_config.py -v`
Expected: FAIL — 404 or import errors

- [ ] **Step 3: Add UserModelConfigDocument to _models.py**

Append to `backend/modules/llm/_models.py`:

```python


class UserModelConfigDocument(BaseModel):
    """Internal MongoDB document for per-user model configuration. Never expose outside llm module."""

    id: str = Field(alias="_id")
    user_id: str
    model_unique_id: str
    is_favourite: bool = False
    is_hidden: bool = False
    notes: str | None = None
    system_prompt_addition: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}
```

- [ ] **Step 4: Create backend/modules/llm/_user_config.py**

```python
from datetime import UTC, datetime
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from shared.dtos.llm import UserModelConfigDto


class UserModelConfigRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db["llm_user_model_configs"]

    async def create_indexes(self) -> None:
        await self._collection.create_index(
            [("user_id", 1), ("model_unique_id", 1)], unique=True
        )

    async def find(self, user_id: str, model_unique_id: str) -> dict | None:
        return await self._collection.find_one(
            {"user_id": user_id, "model_unique_id": model_unique_id}
        )

    async def upsert(
        self,
        user_id: str,
        model_unique_id: str,
        is_favourite: bool | None = None,
        is_hidden: bool | None = None,
        notes: str | None = None,
        system_prompt_addition: str | None = None,
    ) -> dict:
        now = datetime.now(UTC)
        existing = await self.find(user_id, model_unique_id)

        if existing:
            update_fields: dict = {"updated_at": now}
            if is_favourite is not None:
                update_fields["is_favourite"] = is_favourite
            if is_hidden is not None:
                update_fields["is_hidden"] = is_hidden
            if notes is not None:
                update_fields["notes"] = notes
            if system_prompt_addition is not None:
                update_fields["system_prompt_addition"] = system_prompt_addition
            await self._collection.update_one(
                {"_id": existing["_id"]},
                {"$set": update_fields},
            )
            return await self.find(user_id, model_unique_id)

        doc = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "model_unique_id": model_unique_id,
            "is_favourite": is_favourite if is_favourite is not None else False,
            "is_hidden": is_hidden if is_hidden is not None else False,
            "notes": notes,
            "system_prompt_addition": system_prompt_addition,
            "created_at": now,
            "updated_at": now,
        }
        await self._collection.insert_one(doc)
        return doc

    async def delete(self, user_id: str, model_unique_id: str) -> bool:
        result = await self._collection.delete_one(
            {"user_id": user_id, "model_unique_id": model_unique_id}
        )
        return result.deleted_count > 0

    async def list_for_user(self, user_id: str) -> list[dict]:
        cursor = self._collection.find({"user_id": user_id})
        return await cursor.to_list(length=1000)

    @staticmethod
    def to_dto(doc: dict) -> UserModelConfigDto:
        return UserModelConfigDto(
            model_unique_id=doc["model_unique_id"],
            is_favourite=doc.get("is_favourite", False),
            is_hidden=doc.get("is_hidden", False),
            notes=doc.get("notes"),
            system_prompt_addition=doc.get("system_prompt_addition"),
        )

    @staticmethod
    def default_dto(model_unique_id: str) -> UserModelConfigDto:
        return UserModelConfigDto(model_unique_id=model_unique_id)
```

- [ ] **Step 5: Add user-config endpoints to _handlers.py**

Add these imports to the top of `backend/modules/llm/_handlers.py`:

```python
from backend.modules.llm._user_config import UserModelConfigRepository
from shared.dtos.llm import (
    ModelCurationDto, ModelMetaDto, ProviderCredentialDto,
    SetModelCurationDto, SetProviderKeyDto,
    SetUserModelConfigDto, UserModelConfigDto,
)
from shared.events.llm import (
    LlmCredentialRemovedEvent,
    LlmCredentialSetEvent,
    LlmCredentialTestedEvent,
    LlmModelCuratedEvent,
    LlmUserModelConfigUpdatedEvent,
)
```

(Replace the existing `shared.dtos.llm` and `shared.events.llm` import blocks.)

Add a helper function after the existing `_curation_repo()`:

```python
def _user_config_repo() -> UserModelConfigRepository:
    return UserModelConfigRepository(get_db())
```

Add these endpoints at the end of the file:

```python
@router.get("/user-model-configs")
async def list_user_model_configs(user: dict = Depends(require_active_session)):
    repo = _user_config_repo()
    docs = await repo.list_for_user(user["sub"])
    return [UserModelConfigRepository.to_dto(doc) for doc in docs]


@router.get("/providers/{provider_id}/models/{model_slug:path}/user-config")
async def get_user_model_config(
    provider_id: str,
    model_slug: str,
    user: dict = Depends(require_active_session),
):
    if provider_id not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    model_unique_id = f"{provider_id}:{model_slug}"
    repo = _user_config_repo()
    doc = await repo.find(user["sub"], model_unique_id)
    if doc:
        return UserModelConfigRepository.to_dto(doc)
    return UserModelConfigRepository.default_dto(model_unique_id)


@router.put("/providers/{provider_id}/models/{model_slug:path}/user-config", status_code=200)
async def set_user_model_config(
    provider_id: str,
    model_slug: str,
    body: SetUserModelConfigDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    if provider_id not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    model_unique_id = f"{provider_id}:{model_slug}"
    repo = _user_config_repo()
    doc = await repo.upsert(
        user_id=user["sub"],
        model_unique_id=model_unique_id,
        is_favourite=body.is_favourite,
        is_hidden=body.is_hidden,
        notes=body.notes,
        system_prompt_addition=body.system_prompt_addition,
    )
    config_dto = UserModelConfigRepository.to_dto(doc)

    await event_bus.publish(
        Topics.LLM_USER_MODEL_CONFIG_UPDATED,
        LlmUserModelConfigUpdatedEvent(
            model_unique_id=model_unique_id,
            config=config_dto,
        ),
        target_user_ids=[user["sub"]],
    )

    return config_dto


@router.delete("/providers/{provider_id}/models/{model_slug:path}/user-config", status_code=200)
async def delete_user_model_config(
    provider_id: str,
    model_slug: str,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    if provider_id not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    model_unique_id = f"{provider_id}:{model_slug}"
    repo = _user_config_repo()
    await repo.delete(user["sub"], model_unique_id)

    default_config = UserModelConfigRepository.default_dto(model_unique_id)

    await event_bus.publish(
        Topics.LLM_USER_MODEL_CONFIG_UPDATED,
        LlmUserModelConfigUpdatedEvent(
            model_unique_id=model_unique_id,
            config=default_config,
        ),
        target_user_ids=[user["sub"]],
    )

    return default_config
```

- [ ] **Step 6: Update backend/modules/llm/__init__.py**

Replace the contents of `backend/modules/llm/__init__.py` with:

```python
"""LLM module — inference provider adapters, user credentials, model metadata.

Public API: import only from this file.
"""

from backend.modules.llm._credentials import CredentialRepository
from backend.modules.llm._curation import CurationRepository
from backend.modules.llm._handlers import router
from backend.modules.llm._registry import ADAPTER_REGISTRY
from backend.modules.llm._user_config import UserModelConfigRepository
from backend.database import get_db


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the LLM module collections."""
    await CredentialRepository(db).create_indexes()
    await CurationRepository(db).create_indexes()
    await UserModelConfigRepository(db).create_indexes()


def is_valid_provider(provider_id: str) -> bool:
    """Return True if provider_id is registered in the adapter registry."""
    return provider_id in ADAPTER_REGISTRY


__all__ = ["router", "init_indexes", "is_valid_provider", "UserModelConfigRepository"]
```

- [ ] **Step 7: Register fan-out rule in event_bus.py**

Add to the `_FANOUT` dict in `backend/ws/event_bus.py`:

```python
    Topics.LLM_USER_MODEL_CONFIG_UPDATED: ([], True),
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd /home/chris/workspace/chatsune && docker compose run --rm backend pytest tests/test_user_model_config.py -v`
Expected: All 9 tests PASS

- [ ] **Step 9: Run full test suite**

Run: `cd /home/chris/workspace/chatsune && docker compose run --rm backend pytest -v`
Expected: All tests pass (existing + new)

- [ ] **Step 10: Commit**

```bash
git add backend/modules/llm/ tests/test_user_model_config.py backend/ws/event_bus.py
git commit -m "Add user model config with per-user per-model preferences and events"
```

---

### Task 5: INSIGHTS.md entries

**Files:**
- Modify: `INSIGHTS.md`

- [ ] **Step 1: Add INS-006 and INS-007 entries**

Append to the end of `INSIGHTS.md`:

```markdown

---

## INS-006 — Three-Layer Model Data (Extension of INS-005)

**Decision:** Model data is now served from three layers, merged at read time:

1. **Provider metadata** (Redis, ephemeral, 30min TTL) — what the model *is*
   (capabilities, parameter count, context window). Fetched from upstream adapter.
2. **Admin curation** (MongoDB, persistent) — how the admin *rates* the model
   (overall rating, hidden flag, admin description). Collection: `llm_model_curations`.
3. **User config** (MongoDB, persistent, per-user) — how the user *uses* the model
   (favourite, hidden, notes, system prompt addition). Collection: `llm_user_model_configs`.

**Why three layers:**
Each layer has a different owner (provider, admin, user), lifecycle (volatile, persistent,
persistent-per-user), and event semantics. Keeping them separate means changes in one layer
never corrupt or invalidate another.

**Default behaviour:**
When no user config document exists, the API returns sensible defaults (not-favourite,
not-hidden, no notes, no system prompt addition). The document is only created on first
explicit user action.

**Delete semantics:**
There is no separate "deleted" event for user config. The DELETE endpoint removes the
MongoDB document but emits an `llm.user_model_config.updated` event with default values.
The frontend handles a single event type — this is a general pattern: if a resource has
sensible defaults, "deleted" and "reset to defaults" are identical from the client's
perspective.

---

## INS-007 — System Prompt Hierarchy

**Decision:** The system prompt for a chat session is assembled from three sources,
concatenated in priority order:

| Priority | Source | Scope |
|----------|--------|-------|
| 1 (highest) | Global system prompt | Platform-wide admin setting |
| 2 | User model config addition | Per user, per model |
| 3 | Persona system prompt | Per persona |

**Why this order:**
The global system prompt contains admin guardrails ("be harmless", content policy).
These must not be overridden by user or persona prompts. The user model config addition
carries community-sourced model-specific tweaks (e.g. "tell Mistral to focus on the last
message") — these are model-level, not persona-level. The persona prompt defines character
and behaviour, which is the most specific and variable layer.

**Implementation note:**
The three layers are concatenated as separate blocks, not merged. Each block is a distinct
section in the final prompt. The chat module (not yet implemented) will be responsible for
assembling the final prompt from these sources.

**Differentiating feature:**
The user model config system prompt addition is unique to Chatsune. Neither Open WebUI nor
SillyTavern offer per-user per-model prompt additions. This lets users encode community
knowledge about model quirks directly into their configuration.
```

- [ ] **Step 2: Commit**

```bash
git add INSIGHTS.md
git commit -m "Add INS-006 (three-layer model data) and INS-007 (system prompt hierarchy)"
```

---

### Task 6: Final verification

- [ ] **Step 1: Run the full test suite**

Run: `cd /home/chris/workspace/chatsune && docker compose run --rm backend pytest -v`
Expected: All tests pass

- [ ] **Step 2: Verify no import boundary violations**

Run: `cd /home/chris/workspace/chatsune && grep -rn "from backend.modules.settings._" backend/ --include="*.py" | grep -v "backend/modules/settings/"`
Expected: No output (no external imports of settings internals)

Run: `cd /home/chris/workspace/chatsune && grep -rn "from backend.modules.llm._user_config" backend/ --include="*.py" | grep -v "backend/modules/llm/"`
Expected: No output (no external imports of llm internals)

- [ ] **Step 3: Merge to master**

```bash
git log --oneline -5
```

Verify the commits look correct, then the work is on master already (we're working directly on master).

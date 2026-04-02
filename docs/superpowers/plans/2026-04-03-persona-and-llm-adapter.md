# Persona Module & LLM Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Persona module (full CRUD + events) and the LLM module (adapter scaffolding, user credentials, model metadata cache).

**Architecture:** Modular Monolith — each module owns its MongoDB collections and exposes a single public API via `__init__.py`. All state changes publish WebSocket events. The Ollama Cloud adapter is implemented as stubs (`NotImplementedError`) in this iteration; full integration is deferred.

**Tech Stack:** Python 3.12, FastAPI, Motor (MongoDB), Redis, Pydantic v2, cryptography (Fernet), pytest-asyncio (integration tests against real DB)

**Spec:** `docs/superpowers/specs/2026-04-03-persona-and-llm-adapter-design.md`

---

## File Map

**Create:**
- `shared/dtos/persona.py` — PersonaDto, CreatePersonaDto, UpdatePersonaDto
- `shared/dtos/llm.py` — ProviderCredentialDto, SetProviderKeyDto, ModelMetaDto
- `shared/events/persona.py` — PersonaCreatedEvent, PersonaUpdatedEvent, PersonaDeletedEvent
- `shared/events/llm.py` — LlmCredentialSetEvent, LlmCredentialRemovedEvent, LlmCredentialTestedEvent
- `backend/modules/llm/_adapters/__init__.py` — empty package marker
- `backend/modules/llm/_adapters/_base.py` — abstract BaseAdapter
- `backend/modules/llm/_adapters/_ollama_cloud.py` — OllamaCloudAdapter (stubs)
- `backend/modules/llm/_registry.py` — ADAPTER_REGISTRY dict
- `backend/modules/llm/_models.py` — UserCredentialDocument
- `backend/modules/llm/_credentials.py` — CredentialRepository + Fernet helpers
- `backend/modules/llm/_metadata.py` — lazy Redis model metadata cache
- `backend/modules/llm/_handlers.py` — 5 endpoints
- `backend/modules/llm/__init__.py` — public API
- `backend/modules/persona/_models.py` — PersonaDocument
- `backend/modules/persona/_repository.py` — PersonaRepository
- `backend/modules/persona/_handlers.py` — 6 endpoints
- `backend/modules/persona/__init__.py` — public API
- `tests/test_llm_providers.py` — LLM handler integration tests
- `tests/test_personas.py` — Persona handler integration tests

**Modify:**
- `shared/topics.py` — 6 new constants
- `backend/ws/event_bus.py` — 6 new fan-out rules
- `backend/config.py` — add `encryption_key: str`
- `backend/main.py` — include new routers, call new init_indexes
- `backend/pyproject.toml` — add `cryptography` dependency
- `.env.example` — add `ENCRYPTION_KEY` example
- `.env` — add `ENCRYPTION_KEY` value (manual step, not committed)

---

## Task 1: Shared contracts — DTOs, events, topics

**Files:**
- Create: `shared/dtos/persona.py`
- Create: `shared/dtos/llm.py`
- Create: `shared/events/persona.py`
- Create: `shared/events/llm.py`
- Modify: `shared/topics.py`

- [ ] **Step 1: Create `shared/dtos/persona.py`**

```python
from datetime import datetime

from pydantic import BaseModel


class PersonaDto(BaseModel):
    id: str
    user_id: str
    name: str
    tagline: str
    model_unique_id: str
    system_prompt: str
    temperature: float
    reasoning_enabled: bool
    colour_scheme: str
    display_order: int
    created_at: datetime
    updated_at: datetime


class CreatePersonaDto(BaseModel):
    name: str
    tagline: str
    model_unique_id: str
    system_prompt: str
    temperature: float = 0.8
    reasoning_enabled: bool = False
    colour_scheme: str = ""
    display_order: int = 0


class UpdatePersonaDto(BaseModel):
    name: str | None = None
    tagline: str | None = None
    model_unique_id: str | None = None
    system_prompt: str | None = None
    temperature: float | None = None
    reasoning_enabled: bool | None = None
    colour_scheme: str | None = None
    display_order: int | None = None
```

- [ ] **Step 2: Create `shared/dtos/llm.py`**

```python
from datetime import datetime

from pydantic import BaseModel


class ProviderCredentialDto(BaseModel):
    provider_id: str
    display_name: str
    is_configured: bool
    created_at: datetime | None = None


class SetProviderKeyDto(BaseModel):
    api_key: str


class ModelMetaDto(BaseModel):
    provider_id: str
    model_id: str
    display_name: str
    context_window: int
    supports_reasoning: bool
    supports_vision: bool
    supports_tool_calls: bool
```

- [ ] **Step 3: Create `shared/events/persona.py`**

```python
from datetime import datetime

from pydantic import BaseModel


class PersonaCreatedEvent(BaseModel):
    type: str = "persona.created"
    persona_id: str
    user_id: str
    name: str
    timestamp: datetime


class PersonaUpdatedEvent(BaseModel):
    type: str = "persona.updated"
    persona_id: str
    user_id: str
    timestamp: datetime


class PersonaDeletedEvent(BaseModel):
    type: str = "persona.deleted"
    persona_id: str
    user_id: str
    timestamp: datetime
```

- [ ] **Step 4: Create `shared/events/llm.py`**

```python
from datetime import datetime

from pydantic import BaseModel


class LlmCredentialSetEvent(BaseModel):
    type: str = "llm.credential.set"
    provider_id: str
    user_id: str
    timestamp: datetime


class LlmCredentialRemovedEvent(BaseModel):
    type: str = "llm.credential.removed"
    provider_id: str
    user_id: str
    timestamp: datetime


class LlmCredentialTestedEvent(BaseModel):
    type: str = "llm.credential.tested"
    provider_id: str
    user_id: str
    valid: bool
    timestamp: datetime
```

- [ ] **Step 5: Add 6 constants to `shared/topics.py`**

Append after the existing constants:

```python
    PERSONA_CREATED = "persona.created"
    PERSONA_UPDATED = "persona.updated"
    PERSONA_DELETED = "persona.deleted"
    LLM_CREDENTIAL_SET = "llm.credential.set"
    LLM_CREDENTIAL_REMOVED = "llm.credential.removed"
    LLM_CREDENTIAL_TESTED = "llm.credential.tested"
```

- [ ] **Step 6: Commit**

```bash
git add shared/dtos/persona.py shared/dtos/llm.py \
        shared/events/persona.py shared/events/llm.py \
        shared/topics.py
git commit -m "Add shared contracts: persona and LLM DTOs, events, topics"
```

---

## Task 2: Fan-out rules in event_bus.py

**Files:**
- Modify: `backend/ws/event_bus.py`

The EventBus `_FANOUT` dict controls which WebSocket clients receive each event.
Format: `topic: (roles_to_broadcast, send_to_target_user_ids)`.
Persona and credential events go only to the owning user — no role broadcast.

- [ ] **Step 1: Add fan-out rules to `backend/ws/event_bus.py`**

In the `_FANOUT` dict (after the existing USER_PASSWORD_RESET entry), add:

```python
    Topics.PERSONA_CREATED: ([], True),
    Topics.PERSONA_UPDATED: ([], True),
    Topics.PERSONA_DELETED: ([], True),
    Topics.LLM_CREDENTIAL_SET: ([], True),
    Topics.LLM_CREDENTIAL_REMOVED: ([], True),
    Topics.LLM_CREDENTIAL_TESTED: ([], True),
```

- [ ] **Step 2: Run existing event bus tests to verify no regressions**

```bash
cd /home/chris/workspace/chatsune/backend
uv run pytest ../tests/ws/test_event_bus.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add backend/ws/event_bus.py
git commit -m "Add fan-out rules for persona and LLM credential events"
```

---

## Task 3: Cryptography dependency and encryption key setting

API keys are stored encrypted at rest using Fernet (symmetric encryption).

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/config.py`
- Modify: `.env.example`
- Modify: `.env` (manual — not committed)

- [ ] **Step 1: Add cryptography dependency**

```bash
cd /home/chris/workspace/chatsune/backend
uv add cryptography
```

Expected: `cryptography` appears in `pyproject.toml` dependencies.

- [ ] **Step 2: Generate an encryption key for local development**

```bash
cd /home/chris/workspace/chatsune/backend
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the output. You will need it in the next step.

- [ ] **Step 3: Add `ENCRYPTION_KEY` to `.env`**

Add the generated key to `.env` (never commit this file):

```
ENCRYPTION_KEY=<paste the generated key here>
```

- [ ] **Step 4: Add `encryption_key` to `backend/config.py`**

```python
class Settings(BaseSettings):
    master_admin_pin: str
    jwt_secret: str
    encryption_key: str                    # Fernet key for encrypting API keys at rest
    mongodb_uri: str = "mongodb://mongodb:27017/chatsune?replicaSet=rs0"
    redis_uri: str = "redis://redis:6379/0"

    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30

    model_config = {"env_file": ".env"}
```

- [ ] **Step 5: Add example to `.env.example`**

Add to `.env.example`:

```
# Fernet key for encrypting API keys at rest.
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY=your-fernet-key-here
```

- [ ] **Step 6: Verify settings load correctly**

```bash
cd /home/chris/workspace/chatsune/backend
uv run python -c "from backend.config import settings; print('encryption_key length:', len(settings.encryption_key))"
```

Expected: prints a length of 44 (Fernet key is 32 bytes, base64url-encoded).

- [ ] **Step 7: Commit**

```bash
git add backend/pyproject.toml backend/config.py .env.example
# Do NOT add .env
git commit -m "Add cryptography dependency and encryption_key setting for API key storage"
```

---

## Task 4: LLM adapter scaffolding

**Files:**
- Create: `backend/modules/llm/_adapters/__init__.py`
- Create: `backend/modules/llm/_adapters/_base.py`
- Create: `backend/modules/llm/_adapters/_ollama_cloud.py`
- Create: `backend/modules/llm/_registry.py`

- [ ] **Step 1: Create `backend/modules/llm/_adapters/__init__.py`**

Empty file — makes `_adapters` a Python package:

```python
```

(Empty — no content needed.)

- [ ] **Step 2: Create `backend/modules/llm/_adapters/_base.py`**

```python
from abc import ABC, abstractmethod

from shared.dtos.llm import ModelMetaDto


class BaseAdapter(ABC):
    """Abstract base for all upstream inference provider adapters."""

    @abstractmethod
    async def validate_key(self, api_key: str) -> bool:
        """Return True if the key is valid for this provider."""
        ...

    @abstractmethod
    async def fetch_models(self) -> list[ModelMetaDto]:
        """Fetch all available models with their capabilities."""
        ...
```

- [ ] **Step 3: Create `backend/modules/llm/_adapters/_ollama_cloud.py`**

```python
from shared.dtos.llm import ModelMetaDto
from backend.modules.llm._adapters._base import BaseAdapter


class OllamaCloudAdapter(BaseAdapter):
    """Ollama Cloud inference adapter. Full implementation is deferred."""

    DISPLAY_NAME = "Ollama Cloud"

    async def validate_key(self, api_key: str) -> bool:
        raise NotImplementedError("OllamaCloudAdapter.validate_key not yet implemented")

    async def fetch_models(self) -> list[ModelMetaDto]:
        raise NotImplementedError("OllamaCloudAdapter.fetch_models not yet implemented")
```

- [ ] **Step 4: Create `backend/modules/llm/_registry.py`**

```python
from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._ollama_cloud import OllamaCloudAdapter

ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = {
    "ollama_cloud": OllamaCloudAdapter,
}

PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "ollama_cloud": "Ollama Cloud",
}
```

- [ ] **Step 5: Write failing test for registry**

Create `tests/test_llm_registry.py`:

```python
from backend.modules.llm._registry import ADAPTER_REGISTRY, PROVIDER_DISPLAY_NAMES
from backend.modules.llm._adapters._base import BaseAdapter


def test_ollama_cloud_is_registered():
    assert "ollama_cloud" in ADAPTER_REGISTRY


def test_all_registered_adapters_extend_base():
    for provider_id, adapter_class in ADAPTER_REGISTRY.items():
        assert issubclass(adapter_class, BaseAdapter), (
            f"{provider_id}: {adapter_class} does not extend BaseAdapter"
        )


def test_all_registered_adapters_have_display_name():
    for provider_id in ADAPTER_REGISTRY:
        assert provider_id in PROVIDER_DISPLAY_NAMES, (
            f"{provider_id} missing from PROVIDER_DISPLAY_NAMES"
        )
```

- [ ] **Step 6: Run test to verify it passes**

```bash
cd /home/chris/workspace/chatsune/backend
uv run pytest ../tests/test_llm_registry.py -v
```

Expected: 3 tests PASS (these tests don't need DB/Redis — pure registry checks).

- [ ] **Step 7: Commit**

```bash
git add backend/modules/llm/_adapters/ backend/modules/llm/_registry.py \
        tests/test_llm_registry.py
git commit -m "Scaffold LLM adapter base, Ollama Cloud stub, and adapter registry"
```

---

## Task 5: LLM credentials repository

**Files:**
- Create: `backend/modules/llm/_models.py`
- Create: `backend/modules/llm/_credentials.py`

- [ ] **Step 1: Create `backend/modules/llm/_models.py`**

```python
from datetime import datetime

from pydantic import BaseModel, Field


class UserCredentialDocument(BaseModel):
    """Internal MongoDB document model for LLM user credentials. Never expose outside llm module."""

    id: str = Field(alias="_id")
    user_id: str
    provider_id: str
    api_key_encrypted: str  # Fernet-encrypted; never returned via API
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}
```

- [ ] **Step 2: Create `backend/modules/llm/_credentials.py`**

```python
from datetime import UTC, datetime
from uuid import uuid4

from cryptography.fernet import Fernet
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.config import settings
from shared.dtos.llm import ProviderCredentialDto


def _fernet() -> Fernet:
    return Fernet(settings.encryption_key.encode())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


class CredentialRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db["llm_user_credentials"]

    async def create_indexes(self) -> None:
        await self._collection.create_index(
            [("user_id", 1), ("provider_id", 1)], unique=True
        )

    async def find(self, user_id: str, provider_id: str) -> dict | None:
        return await self._collection.find_one(
            {"user_id": user_id, "provider_id": provider_id}
        )

    async def upsert(self, user_id: str, provider_id: str, api_key: str) -> dict:
        now = datetime.now(UTC)
        encrypted = encrypt(api_key)
        existing = await self.find(user_id, provider_id)
        if existing:
            await self._collection.update_one(
                {"_id": existing["_id"]},
                {"$set": {"api_key_encrypted": encrypted, "updated_at": now}},
            )
            return await self.find(user_id, provider_id)
        doc = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "provider_id": provider_id,
            "api_key_encrypted": encrypted,
            "created_at": now,
            "updated_at": now,
        }
        await self._collection.insert_one(doc)
        return doc

    async def delete(self, user_id: str, provider_id: str) -> bool:
        result = await self._collection.delete_one(
            {"user_id": user_id, "provider_id": provider_id}
        )
        return result.deleted_count > 0

    async def list_for_user(self, user_id: str) -> list[dict]:
        cursor = self._collection.find({"user_id": user_id})
        return await cursor.to_list(length=100)

    def get_raw_key(self, doc: dict) -> str:
        """Decrypt and return the raw API key. Use only at inference time."""
        return decrypt(doc["api_key_encrypted"])

    @staticmethod
    def to_dto(doc: dict, display_name: str) -> ProviderCredentialDto:
        return ProviderCredentialDto(
            provider_id=doc["provider_id"],
            display_name=display_name,
            is_configured=True,
            created_at=doc["created_at"],
        )
```

- [ ] **Step 3: Commit**

```bash
git add backend/modules/llm/_models.py backend/modules/llm/_credentials.py
git commit -m "Add LLM credentials repository with Fernet encryption"
```

---

## Task 6: LLM metadata cache

**Files:**
- Create: `backend/modules/llm/_metadata.py`

- [ ] **Step 1: Create `backend/modules/llm/_metadata.py`**

```python
import json

from redis.asyncio import Redis

from backend.modules.llm._adapters._base import BaseAdapter
from shared.dtos.llm import ModelMetaDto


async def get_models(
    provider_id: str, redis: Redis, adapter: BaseAdapter
) -> list[ModelMetaDto]:
    """Return cached model list or fetch from adapter on cache miss (TTL 30 min).

    Returns [] if the adapter is not yet implemented (NotImplementedError).
    See INSIGHTS.md INS-001 for the design reasoning.
    """
    cache_key = f"llm:models:{provider_id}"
    cached = await redis.get(cache_key)
    if cached:
        return [ModelMetaDto.model_validate(m) for m in json.loads(cached)]

    try:
        models = await adapter.fetch_models()
    except NotImplementedError:
        return []

    await redis.set(
        cache_key,
        json.dumps([m.model_dump() for m in models]),
        ex=1800,  # 30 minutes TTL
    )
    return models
```

- [ ] **Step 2: Commit**

```bash
git add backend/modules/llm/_metadata.py
git commit -m "Add lazy Redis model metadata cache for LLM providers"
```

---

## Task 7: LLM handlers, public API, and wire into main

**Files:**
- Create: `backend/modules/llm/_handlers.py`
- Create: `backend/modules/llm/__init__.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Create `backend/modules/llm/_handlers.py`**

```python
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from backend.database import get_db, get_redis
from backend.dependencies import require_active_session
from backend.modules.llm._credentials import CredentialRepository
from backend.modules.llm._metadata import get_models
from backend.modules.llm._registry import ADAPTER_REGISTRY, PROVIDER_DISPLAY_NAMES
from backend.ws.event_bus import EventBus, get_event_bus
from shared.dtos.llm import ProviderCredentialDto, SetProviderKeyDto
from shared.events.llm import (
    LlmCredentialRemovedEvent,
    LlmCredentialSetEvent,
    LlmCredentialTestedEvent,
)
from shared.topics import Topics

router = APIRouter(prefix="/api/llm")


def _credential_repo() -> CredentialRepository:
    return CredentialRepository(get_db())


@router.get("/providers")
async def list_providers(user: dict = Depends(require_active_session)):
    repo = _credential_repo()
    configured = {
        doc["provider_id"]: doc
        for doc in await repo.list_for_user(user["sub"])
    }
    result = []
    for provider_id in ADAPTER_REGISTRY:
        doc = configured.get(provider_id)
        if doc:
            result.append(CredentialRepository.to_dto(doc, PROVIDER_DISPLAY_NAMES[provider_id]))
        else:
            result.append(
                ProviderCredentialDto(
                    provider_id=provider_id,
                    display_name=PROVIDER_DISPLAY_NAMES[provider_id],
                    is_configured=False,
                )
            )
    return result


@router.put("/providers/{provider_id}/key", status_code=200)
async def set_provider_key(
    provider_id: str,
    body: SetProviderKeyDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    if provider_id not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    repo = _credential_repo()
    doc = await repo.upsert(user["sub"], provider_id, body.api_key)

    await event_bus.publish(
        Topics.LLM_CREDENTIAL_SET,
        LlmCredentialSetEvent(
            provider_id=provider_id,
            user_id=user["sub"],
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[user["sub"]],
    )

    return CredentialRepository.to_dto(doc, PROVIDER_DISPLAY_NAMES[provider_id])


@router.delete("/providers/{provider_id}/key", status_code=200)
async def remove_provider_key(
    provider_id: str,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    if provider_id not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    repo = _credential_repo()
    deleted = await repo.delete(user["sub"], provider_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="No key configured for this provider")

    await event_bus.publish(
        Topics.LLM_CREDENTIAL_REMOVED,
        LlmCredentialRemovedEvent(
            provider_id=provider_id,
            user_id=user["sub"],
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[user["sub"]],
    )

    return {"status": "ok"}


@router.post("/providers/{provider_id}/test", status_code=200)
async def test_provider_key(
    provider_id: str,
    body: SetProviderKeyDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    if provider_id not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    adapter = ADAPTER_REGISTRY[provider_id]()
    try:
        valid = await adapter.validate_key(body.api_key)
    except NotImplementedError:
        raise HTTPException(
            status_code=501,
            detail=f"Provider '{provider_id}' is not yet fully implemented",
        )

    await event_bus.publish(
        Topics.LLM_CREDENTIAL_TESTED,
        LlmCredentialTestedEvent(
            provider_id=provider_id,
            user_id=user["sub"],
            valid=valid,
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[user["sub"]],
    )

    return {"valid": valid}


@router.get("/providers/{provider_id}/models")
async def list_models(
    provider_id: str,
    user: dict = Depends(require_active_session),
):
    if provider_id not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    adapter = ADAPTER_REGISTRY[provider_id]()
    redis = get_redis()
    return await get_models(provider_id, redis, adapter)
```

- [ ] **Step 2: Create `backend/modules/llm/__init__.py`**

```python
"""LLM module — inference provider adapters, user credentials, model metadata.

Public API: import only from this file.
"""

from backend.modules.llm._credentials import CredentialRepository
from backend.modules.llm._handlers import router
from backend.modules.llm._registry import ADAPTER_REGISTRY
from backend.database import get_db


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the LLM module collections."""
    await CredentialRepository(db).create_indexes()


def is_valid_provider(provider_id: str) -> bool:
    """Return True if provider_id is registered in the adapter registry."""
    return provider_id in ADAPTER_REGISTRY


__all__ = ["router", "init_indexes", "is_valid_provider"]
```

- [ ] **Step 3: Wire into `backend/main.py`**

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.database import connect_db, disconnect_db, get_db, get_redis
from backend.modules.user import router as user_router, init_indexes as user_init_indexes
from backend.modules.llm import router as llm_router, init_indexes as llm_init_indexes
from backend.ws.event_bus import EventBus, set_event_bus
from backend.ws.manager import ConnectionManager, set_manager
from backend.ws.router import ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    db = get_db()
    await user_init_indexes(db)
    await llm_init_indexes(db)
    manager = ConnectionManager()
    set_manager(manager)
    set_event_bus(EventBus(redis=get_redis(), manager=manager))
    yield
    await disconnect_db()


app = FastAPI(title="Chatsune", version="0.1.0", lifespan=lifespan)
app.include_router(user_router)
app.include_router(llm_router)
app.include_router(ws_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 4: Commit**

```bash
git add backend/modules/llm/_handlers.py backend/modules/llm/__init__.py \
        backend/main.py
git commit -m "Add LLM module: handlers, public API, wire into main"
```

---

## Task 8: LLM integration tests

**Files:**
- Create: `tests/test_llm_providers.py`

- [ ] **Step 1: Write failing tests for LLM provider endpoints**

Create `tests/test_llm_providers.py`:

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


async def test_list_providers_unauthenticated(client: AsyncClient):
    resp = await client.get("/api/llm/providers")
    assert resp.status_code == 403


async def test_list_providers_returns_all_registered(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.get("/api/llm/providers", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    provider_ids = [p["provider_id"] for p in data]
    assert "ollama_cloud" in provider_ids


async def test_list_providers_not_configured_by_default(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.get("/api/llm/providers", headers=_auth(token))
    assert resp.status_code == 200
    ollama = next(p for p in resp.json() if p["provider_id"] == "ollama_cloud")
    assert ollama["is_configured"] is False
    assert ollama["created_at"] is None


async def test_set_provider_key(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.put(
        "/api/llm/providers/ollama_cloud/key",
        json={"api_key": "test-api-key-12345"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider_id"] == "ollama_cloud"
    assert data["is_configured"] is True
    assert "api_key" not in data  # key must never be returned


async def test_set_provider_key_shows_in_list(client: AsyncClient):
    token = await _setup_and_login(client)
    await client.put(
        "/api/llm/providers/ollama_cloud/key",
        json={"api_key": "test-api-key-12345"},
        headers=_auth(token),
    )
    resp = await client.get("/api/llm/providers", headers=_auth(token))
    ollama = next(p for p in resp.json() if p["provider_id"] == "ollama_cloud")
    assert ollama["is_configured"] is True
    assert ollama["created_at"] is not None


async def test_set_provider_key_unknown_provider(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.put(
        "/api/llm/providers/nonexistent/key",
        json={"api_key": "key"},
        headers=_auth(token),
    )
    assert resp.status_code == 404


async def test_remove_provider_key(client: AsyncClient):
    token = await _setup_and_login(client)
    await client.put(
        "/api/llm/providers/ollama_cloud/key",
        json={"api_key": "test-api-key-12345"},
        headers=_auth(token),
    )
    resp = await client.delete(
        "/api/llm/providers/ollama_cloud/key",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    # Verify it's gone
    list_resp = await client.get("/api/llm/providers", headers=_auth(token))
    ollama = next(p for p in list_resp.json() if p["provider_id"] == "ollama_cloud")
    assert ollama["is_configured"] is False


async def test_remove_provider_key_when_none_set(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.delete(
        "/api/llm/providers/ollama_cloud/key",
        headers=_auth(token),
    )
    assert resp.status_code == 404


async def test_test_provider_key_returns_501_for_stub(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.post(
        "/api/llm/providers/ollama_cloud/test",
        json={"api_key": "test-api-key"},
        headers=_auth(token),
    )
    assert resp.status_code == 501


async def test_list_models_returns_empty_for_stub(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.get(
        "/api/llm/providers/ollama_cloud/models",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json() == []


async def test_key_update_overwrites_existing(client: AsyncClient):
    token = await _setup_and_login(client)
    await client.put(
        "/api/llm/providers/ollama_cloud/key",
        json={"api_key": "first-key"},
        headers=_auth(token),
    )
    await client.put(
        "/api/llm/providers/ollama_cloud/key",
        json={"api_key": "second-key"},
        headers=_auth(token),
    )
    # Verify only one entry exists (upsert, not duplicate)
    list_resp = await client.get("/api/llm/providers", headers=_auth(token))
    ollama_entries = [p for p in list_resp.json() if p["provider_id"] == "ollama_cloud"]
    assert len(ollama_entries) == 1
    assert ollama_entries[0]["is_configured"] is True
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
cd /home/chris/workspace/chatsune/backend
uv run pytest ../tests/test_llm_providers.py -v
```

Expected: all 11 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_llm_providers.py
git commit -m "Add LLM provider integration tests"
```

---

## Task 9: Persona models and repository

**Files:**
- Create: `backend/modules/persona/_models.py`
- Create: `backend/modules/persona/_repository.py`

- [ ] **Step 1: Create `backend/modules/persona/_models.py`**

```python
from datetime import datetime

from pydantic import BaseModel, Field


class PersonaDocument(BaseModel):
    """Internal MongoDB document model for personas. Never expose outside persona module."""

    id: str = Field(alias="_id")
    user_id: str
    name: str
    tagline: str
    model_unique_id: str
    system_prompt: str
    temperature: float
    reasoning_enabled: bool
    colour_scheme: str
    display_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}
```

- [ ] **Step 2: Create `backend/modules/persona/_repository.py`**

```python
from datetime import UTC, datetime
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from shared.dtos.persona import PersonaDto


class PersonaRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db["personas"]

    async def create_indexes(self) -> None:
        await self._collection.create_index("user_id")
        await self._collection.create_index([("user_id", 1), ("display_order", 1)])

    async def create(
        self,
        user_id: str,
        name: str,
        tagline: str,
        model_unique_id: str,
        system_prompt: str,
        temperature: float,
        reasoning_enabled: bool,
        colour_scheme: str,
        display_order: int,
    ) -> dict:
        now = datetime.now(UTC)
        doc = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "name": name,
            "tagline": tagline,
            "model_unique_id": model_unique_id,
            "system_prompt": system_prompt,
            "temperature": temperature,
            "reasoning_enabled": reasoning_enabled,
            "colour_scheme": colour_scheme,
            "display_order": display_order,
            "created_at": now,
            "updated_at": now,
        }
        await self._collection.insert_one(doc)
        return doc

    async def find_by_id(self, persona_id: str, user_id: str) -> dict | None:
        """Find persona by ID, scoped to the owning user."""
        return await self._collection.find_one(
            {"_id": persona_id, "user_id": user_id}
        )

    async def list_for_user(self, user_id: str) -> list[dict]:
        cursor = self._collection.find(
            {"user_id": user_id}
        ).sort("display_order", 1)
        return await cursor.to_list(length=500)

    async def update(self, persona_id: str, user_id: str, fields: dict) -> dict | None:
        fields["updated_at"] = datetime.now(UTC)
        result = await self._collection.update_one(
            {"_id": persona_id, "user_id": user_id}, {"$set": fields}
        )
        if result.matched_count == 0:
            return None
        return await self.find_by_id(persona_id, user_id)

    async def delete(self, persona_id: str, user_id: str) -> bool:
        result = await self._collection.delete_one(
            {"_id": persona_id, "user_id": user_id}
        )
        return result.deleted_count > 0

    @staticmethod
    def to_dto(doc: dict) -> PersonaDto:
        return PersonaDto(
            id=doc["_id"],
            user_id=doc["user_id"],
            name=doc["name"],
            tagline=doc["tagline"],
            model_unique_id=doc["model_unique_id"],
            system_prompt=doc["system_prompt"],
            temperature=doc["temperature"],
            reasoning_enabled=doc["reasoning_enabled"],
            colour_scheme=doc["colour_scheme"],
            display_order=doc["display_order"],
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )
```

- [ ] **Step 3: Commit**

```bash
git add backend/modules/persona/_models.py backend/modules/persona/_repository.py
git commit -m "Add persona document model and repository"
```

---

## Task 10: Persona handlers, public API, and wire into main

**Files:**
- Create: `backend/modules/persona/_handlers.py`
- Create: `backend/modules/persona/__init__.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Create `backend/modules/persona/_handlers.py`**

```python
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from backend.database import get_db
from backend.dependencies import require_active_session
from backend.modules.llm import is_valid_provider
from backend.modules.persona._repository import PersonaRepository
from backend.ws.event_bus import EventBus, get_event_bus
from shared.dtos.persona import CreatePersonaDto, UpdatePersonaDto
from shared.events.persona import (
    PersonaCreatedEvent,
    PersonaDeletedEvent,
    PersonaUpdatedEvent,
)
from shared.topics import Topics

router = APIRouter(prefix="/api/personas")


def _persona_repo() -> PersonaRepository:
    return PersonaRepository(get_db())


def _validate_model_unique_id(model_unique_id: str) -> None:
    """Validate format and that the provider is registered."""
    if ":" not in model_unique_id:
        raise HTTPException(
            status_code=400,
            detail="model_unique_id must be in format 'provider_id:model_slug'",
        )
    provider_id = model_unique_id.split(":", 1)[0]
    if not is_valid_provider(provider_id):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider '{provider_id}' in model_unique_id",
        )


@router.get("")
async def list_personas(user: dict = Depends(require_active_session)):
    repo = _persona_repo()
    docs = await repo.list_for_user(user["sub"])
    return [PersonaRepository.to_dto(d) for d in docs]


@router.post("", status_code=201)
async def create_persona(
    body: CreatePersonaDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    _validate_model_unique_id(body.model_unique_id)

    repo = _persona_repo()
    doc = await repo.create(
        user_id=user["sub"],
        name=body.name,
        tagline=body.tagline,
        model_unique_id=body.model_unique_id,
        system_prompt=body.system_prompt,
        temperature=body.temperature,
        reasoning_enabled=body.reasoning_enabled,
        colour_scheme=body.colour_scheme,
        display_order=body.display_order,
    )

    await event_bus.publish(
        Topics.PERSONA_CREATED,
        PersonaCreatedEvent(
            persona_id=doc["_id"],
            user_id=user["sub"],
            name=doc["name"],
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"persona:{doc['_id']}",
        target_user_ids=[user["sub"]],
    )

    return PersonaRepository.to_dto(doc)


@router.get("/{persona_id}")
async def get_persona(
    persona_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _persona_repo()
    doc = await repo.find_by_id(persona_id, user["sub"])
    if not doc:
        raise HTTPException(status_code=404, detail="Persona not found")
    return PersonaRepository.to_dto(doc)


@router.put("/{persona_id}")
async def replace_persona(
    persona_id: str,
    body: CreatePersonaDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    _validate_model_unique_id(body.model_unique_id)

    repo = _persona_repo()
    updated = await repo.update(
        persona_id,
        user["sub"],
        body.model_dump(),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Persona not found")

    await event_bus.publish(
        Topics.PERSONA_UPDATED,
        PersonaUpdatedEvent(
            persona_id=persona_id,
            user_id=user["sub"],
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"persona:{persona_id}",
        target_user_ids=[user["sub"]],
    )

    return PersonaRepository.to_dto(updated)


@router.patch("/{persona_id}")
async def update_persona(
    persona_id: str,
    body: UpdatePersonaDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    if "model_unique_id" in fields:
        _validate_model_unique_id(fields["model_unique_id"])

    repo = _persona_repo()
    updated = await repo.update(persona_id, user["sub"], fields)
    if not updated:
        raise HTTPException(status_code=404, detail="Persona not found")

    await event_bus.publish(
        Topics.PERSONA_UPDATED,
        PersonaUpdatedEvent(
            persona_id=persona_id,
            user_id=user["sub"],
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"persona:{persona_id}",
        target_user_ids=[user["sub"]],
    )

    return PersonaRepository.to_dto(updated)


@router.delete("/{persona_id}")
async def delete_persona(
    persona_id: str,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    repo = _persona_repo()
    deleted = await repo.delete(persona_id, user["sub"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Persona not found")

    await event_bus.publish(
        Topics.PERSONA_DELETED,
        PersonaDeletedEvent(
            persona_id=persona_id,
            user_id=user["sub"],
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"persona:{persona_id}",
        target_user_ids=[user["sub"]],
    )

    return {"status": "ok"}
```

- [ ] **Step 2: Create `backend/modules/persona/__init__.py`**

```python
"""Persona module — user-owned AI personas.

Public API: import only from this file.
"""

from backend.modules.persona._handlers import router
from backend.modules.persona._repository import PersonaRepository
from backend.database import get_db


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the persona module collections."""
    await PersonaRepository(db).create_indexes()


__all__ = ["router", "init_indexes"]
```

- [ ] **Step 3: Update `backend/main.py` to include persona module**

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.database import connect_db, disconnect_db, get_db, get_redis
from backend.modules.user import router as user_router, init_indexes as user_init_indexes
from backend.modules.llm import router as llm_router, init_indexes as llm_init_indexes
from backend.modules.persona import router as persona_router, init_indexes as persona_init_indexes
from backend.ws.event_bus import EventBus, set_event_bus
from backend.ws.manager import ConnectionManager, set_manager
from backend.ws.router import ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    db = get_db()
    await user_init_indexes(db)
    await llm_init_indexes(db)
    await persona_init_indexes(db)
    manager = ConnectionManager()
    set_manager(manager)
    set_event_bus(EventBus(redis=get_redis(), manager=manager))
    yield
    await disconnect_db()


app = FastAPI(title="Chatsune", version="0.1.0", lifespan=lifespan)
app.include_router(user_router)
app.include_router(llm_router)
app.include_router(persona_router)
app.include_router(ws_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 4: Commit**

```bash
git add backend/modules/persona/_handlers.py backend/modules/persona/__init__.py \
        backend/main.py
git commit -m "Add persona module: handlers, public API, wire into main"
```

---

## Task 11: Persona integration tests

**Files:**
- Create: `tests/test_personas.py`

- [ ] **Step 1: Write failing tests for persona endpoints**

Create `tests/test_personas.py`:

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


_VALID_PERSONA = {
    "name": "Aria",
    "tagline": "Your helpful companion",
    "model_unique_id": "ollama_cloud:llama3.2",
    "system_prompt": "You are a helpful assistant.",
    "temperature": 0.8,
    "reasoning_enabled": False,
    "colour_scheme": "#7c3aed",
    "display_order": 0,
}


async def test_list_personas_empty(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.get("/api/personas", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_persona(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.post("/api/personas", json=_VALID_PERSONA, headers=_auth(token))
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Aria"
    assert data["model_unique_id"] == "ollama_cloud:llama3.2"
    assert "id" in data
    assert "created_at" in data


async def test_create_persona_invalid_model_id_format(client: AsyncClient):
    token = await _setup_and_login(client)
    invalid = {**_VALID_PERSONA, "model_unique_id": "no-colon-here"}
    resp = await client.post("/api/personas", json=invalid, headers=_auth(token))
    assert resp.status_code == 400


async def test_create_persona_unknown_provider(client: AsyncClient):
    token = await _setup_and_login(client)
    invalid = {**_VALID_PERSONA, "model_unique_id": "nonexistent_provider:model"}
    resp = await client.post("/api/personas", json=invalid, headers=_auth(token))
    assert resp.status_code == 400


async def test_get_persona(client: AsyncClient):
    token = await _setup_and_login(client)
    create_resp = await client.post("/api/personas", json=_VALID_PERSONA, headers=_auth(token))
    persona_id = create_resp.json()["id"]

    resp = await client.get(f"/api/personas/{persona_id}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["id"] == persona_id


async def test_get_persona_not_found(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.get("/api/personas/nonexistent-id", headers=_auth(token))
    assert resp.status_code == 404


async def test_list_personas_after_create(client: AsyncClient):
    token = await _setup_and_login(client)
    await client.post("/api/personas", json=_VALID_PERSONA, headers=_auth(token))
    second = {**_VALID_PERSONA, "name": "Zara", "display_order": 1}
    await client.post("/api/personas", json=second, headers=_auth(token))

    resp = await client.get("/api/personas", headers=_auth(token))
    assert resp.status_code == 200
    names = [p["name"] for p in resp.json()]
    assert names == ["Aria", "Zara"]  # ordered by display_order


async def test_put_persona(client: AsyncClient):
    token = await _setup_and_login(client)
    create_resp = await client.post("/api/personas", json=_VALID_PERSONA, headers=_auth(token))
    persona_id = create_resp.json()["id"]

    updated = {**_VALID_PERSONA, "name": "Aria v2", "temperature": 1.2}
    resp = await client.put(f"/api/personas/{persona_id}", json=updated, headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["name"] == "Aria v2"
    assert resp.json()["temperature"] == 1.2


async def test_patch_persona(client: AsyncClient):
    token = await _setup_and_login(client)
    create_resp = await client.post("/api/personas", json=_VALID_PERSONA, headers=_auth(token))
    persona_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/personas/{persona_id}",
        json={"name": "Aria Patched"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Aria Patched"
    assert resp.json()["tagline"] == "Your helpful companion"  # unchanged


async def test_patch_persona_empty_body(client: AsyncClient):
    token = await _setup_and_login(client)
    create_resp = await client.post("/api/personas", json=_VALID_PERSONA, headers=_auth(token))
    persona_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/personas/{persona_id}", json={}, headers=_auth(token)
    )
    assert resp.status_code == 400


async def test_delete_persona(client: AsyncClient):
    token = await _setup_and_login(client)
    create_resp = await client.post("/api/personas", json=_VALID_PERSONA, headers=_auth(token))
    persona_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/personas/{persona_id}", headers=_auth(token))
    assert resp.status_code == 200

    get_resp = await client.get(f"/api/personas/{persona_id}", headers=_auth(token))
    assert get_resp.status_code == 404


async def test_delete_persona_not_found(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.delete("/api/personas/nonexistent-id", headers=_auth(token))
    assert resp.status_code == 404


async def test_unauthenticated_access_rejected(client: AsyncClient):
    resp = await client.get("/api/personas")
    assert resp.status_code == 403
```

- [ ] **Step 2: Run all tests to verify they pass**

```bash
cd /home/chris/workspace/chatsune/backend
uv run pytest ../tests/test_personas.py -v
```

Expected: all 12 tests PASS.

- [ ] **Step 3: Run the full test suite to verify no regressions**

```bash
cd /home/chris/workspace/chatsune/backend
uv run pytest ../tests/ -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_personas.py
git commit -m "Add persona integration tests"
```

---

## Done

All tasks complete. Both modules are implemented, tested, and wired into the app.

**What was built:**
- `backend/modules/persona/` — full CRUD API with events
- `backend/modules/llm/` — adapter registry, Fernet-encrypted credentials, lazy model cache, 5 endpoints, events
- Shared contracts in `shared/dtos/` and `shared/events/`
- Integration tests covering all happy paths and key error cases

**What is deferred:**
- Ollama Cloud adapter implementation (`validate_key`, `fetch_models`)
- Model metadata background refresh
- Persona cloning / sharing

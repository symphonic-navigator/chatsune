# Model Metadata, Key Validation & Curation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement enriched model metadata (parameter count, quantisation), OllamaCloud adapter (key validation + model fetching), persistent model curation, and event-based propagation.

**Architecture:** Two-layer data model — ephemeral provider model data in Redis (30min TTL) merged with persistent admin curation in MongoDB. Curation events carry full data for instant client updates; provider reload events are trigger-only.

**Tech Stack:** Python, FastAPI, Pydantic v2, MongoDB (Motor), Redis (redis-asyncio), httpx (adapter HTTP calls), pytest

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `shared/dtos/llm.py` | Modify | Add `ModelRating`, `ModelCurationDto`, `SetModelCurationDto`; extend `ModelMetaDto` |
| `shared/events/llm.py` | Modify | Add `LlmModelCuratedEvent`, `LlmModelsRefreshedEvent` |
| `shared/topics.py` | Modify | Add `LLM_MODEL_CURATED`, `LLM_MODELS_REFRESHED` |
| `backend/modules/llm/_adapters/_base.py` | Modify | Add `base_url` constructor param |
| `backend/modules/llm/_adapters/_ollama_cloud.py` | Modify | Implement `validate_key` and `fetch_models` |
| `backend/modules/llm/_models.py` | Modify | Add `ModelCurationDocument` |
| `backend/modules/llm/_curation.py` | Create | `CurationRepository` (MongoDB CRUD) |
| `backend/modules/llm/_metadata.py` | Modify | Accept event_bus, publish `LLM_MODELS_REFRESHED` on cache refresh |
| `backend/modules/llm/_handlers.py` | Modify | Add curation endpoints, merge logic, pass event_bus to metadata |
| `backend/modules/llm/__init__.py` | Modify | Export `CurationRepository`, wire indexes |
| `backend/ws/event_bus.py` | Modify | Add fanout rules for new events |
| `tests/test_ollama_cloud_adapter.py` | Create | Adapter unit tests (mocked HTTP) |
| `tests/test_model_curation.py` | Create | Curation integration tests |

---

### Task 1: Extend Shared DTOs

**Files:**
- Modify: `shared/dtos/llm.py`

- [ ] **Step 1: Add ModelRating enum, ModelCurationDto, and SetModelCurationDto**

```python
# Add at the top of the file, after the existing imports:
from enum import Enum

# Add after SetProviderKeyDto class:

class ModelRating(str, Enum):
    AVAILABLE = "available"
    RECOMMENDED = "recommended"
    NOT_RECOMMENDED = "not_recommended"


class ModelCurationDto(BaseModel):
    overall_rating: ModelRating = ModelRating.AVAILABLE
    hidden: bool = False
    admin_description: str | None = None
    last_curated_at: datetime | None = None
    last_curated_by: str | None = None


class SetModelCurationDto(BaseModel):
    overall_rating: ModelRating = ModelRating.AVAILABLE
    hidden: bool = False
    admin_description: str | None = None
```

- [ ] **Step 2: Extend ModelMetaDto with new optional fields**

Replace the existing `ModelMetaDto` class:

```python
class ModelMetaDto(BaseModel):
    provider_id: str
    model_id: str
    display_name: str
    context_window: int
    supports_reasoning: bool
    supports_vision: bool
    supports_tool_calls: bool
    parameter_count: str | None = None
    quantisation_level: str | None = None
    curation: ModelCurationDto | None = None

    @computed_field
    @property
    def unique_id(self) -> str:
        return f"{self.provider_id}:{self.model_id}"
```

- [ ] **Step 3: Verify imports are correct**

Run: `cd /home/chris/workspace/chatsune && python -c "from shared.dtos.llm import ModelRating, ModelCurationDto, SetModelCurationDto, ModelMetaDto; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add shared/dtos/llm.py
git commit -m "Extend LLM DTOs with curation and model metadata fields"
```

---

### Task 2: Add New Events and Topics

**Files:**
- Modify: `shared/events/llm.py`
- Modify: `shared/topics.py`

- [ ] **Step 1: Add new event classes to shared/events/llm.py**

Append after the existing `LlmCredentialTestedEvent` class:

```python
from shared.dtos.llm import ModelMetaDto


class LlmModelCuratedEvent(BaseModel):
    """Carries the full updated model DTO so clients can update in place."""
    type: str = "llm.model.curated"
    provider_id: str
    model_slug: str
    model: ModelMetaDto
    curated_by: str
    timestamp: datetime


class LlmModelsRefreshedEvent(BaseModel):
    """Trigger-only: tells clients to re-fetch the model list."""
    type: str = "llm.models.refreshed"
    provider_id: str
    timestamp: datetime
```

- [ ] **Step 2: Add new topic constants to shared/topics.py**

Append after `LLM_CREDENTIAL_TESTED`:

```python
    LLM_MODEL_CURATED = "llm.model.curated"
    LLM_MODELS_REFRESHED = "llm.models.refreshed"
```

- [ ] **Step 3: Add fanout rules to backend/ws/event_bus.py**

Add after the existing `Topics.LLM_CREDENTIAL_TESTED` line in `_FANOUT`:

```python
    Topics.LLM_MODEL_CURATED: (["admin", "master_admin"], True),
    Topics.LLM_MODELS_REFRESHED: (["admin", "master_admin"], True),
```

Note: These broadcast to admins AND to target_user_ids. In practice, the handlers will call `publish()` with `target_user_ids=None` and use `broadcast_to_all=True` via the roles mechanism. Since all authenticated users should receive these, we use broad roles. However, the existing fanout system only sends to roles listed + target_user_ids. To broadcast to ALL connected users, we need a small extension. Add a special marker:

Actually, looking at the existing `_fan_out` logic more carefully: it broadcasts to `roles` and optionally sends to `target_user_ids`. For model events we want ALL connected users. The simplest approach: publish with all connected user IDs as targets. But that couples to the manager.

Better approach: add a `_BROADCAST_ALL` set and handle it in `_fan_out`:

```python
# Add after _FANOUT dict:
_BROADCAST_ALL: set[str] = {
    Topics.LLM_MODEL_CURATED,
    Topics.LLM_MODELS_REFRESHED,
}
```

Then in `_fan_out`, add before the `if topic not in _FANOUT:` check:

```python
        if topic in _BROADCAST_ALL:
            await self._manager.broadcast_to_all(event_dict)
            return
```

And add `broadcast_to_all` to the `ConnectionManager`. Open `backend/ws/manager.py` and add:

```python
    async def broadcast_to_all(self, event: dict) -> None:
        """Send an event to every connected user."""
        for ws_list in self._connections.values():
            for ws in ws_list:
                try:
                    await ws.send_json(event)
                except Exception:
                    pass
```

- [ ] **Step 4: Verify imports**

Run: `cd /home/chris/workspace/chatsune && python -c "from shared.events.llm import LlmModelCuratedEvent, LlmModelsRefreshedEvent; from shared.topics import Topics; print(Topics.LLM_MODEL_CURATED); print('OK')"`
Expected:
```
llm.model.curated
OK
```

- [ ] **Step 5: Commit**

```bash
git add shared/events/llm.py shared/topics.py backend/ws/event_bus.py backend/ws/manager.py
git commit -m "Add model curation and refresh events with broadcast fanout"
```

---

### Task 3: Implement OllamaCloudAdapter

**Files:**
- Modify: `backend/modules/llm/_adapters/_base.py`
- Modify: `backend/modules/llm/_adapters/_ollama_cloud.py`
- Modify: `backend/modules/llm/_registry.py`
- Create: `tests/test_ollama_cloud_adapter.py`

- [ ] **Step 1: Update BaseAdapter to accept a base_url**

Replace `backend/modules/llm/_adapters/_base.py`:

```python
from abc import ABC, abstractmethod

from shared.dtos.llm import ModelMetaDto


class BaseAdapter(ABC):
    """Abstract base for all upstream inference provider adapters."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    @abstractmethod
    async def validate_key(self, api_key: str) -> bool:
        """Return True if the key is valid for this provider."""
        ...

    @abstractmethod
    async def fetch_models(self) -> list[ModelMetaDto]:
        """Fetch all available models with their capabilities."""
        ...
```

- [ ] **Step 2: Update registry to pass base_url from settings**

Replace `backend/modules/llm/_registry.py`:

```python
from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._ollama_cloud import OllamaCloudAdapter

ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = {
    "ollama_cloud": OllamaCloudAdapter,
}

PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "ollama_cloud": "Ollama Cloud",
}

PROVIDER_BASE_URLS: dict[str, str] = {
    "ollama_cloud": "https://ollama.com",
}
```

- [ ] **Step 3: Write the failing tests for validate_key and fetch_models**

Create `tests/test_ollama_cloud_adapter.py`:

```python
import httpx
import pytest
import respx

from backend.modules.llm._adapters._ollama_cloud import OllamaCloudAdapter


@pytest.fixture
def adapter() -> OllamaCloudAdapter:
    return OllamaCloudAdapter(base_url="https://test.ollama.com")


@respx.mock
async def test_validate_key_returns_true_on_200(adapter: OllamaCloudAdapter):
    respx.get("https://test.ollama.com/api/me").mock(
        return_value=httpx.Response(200, json={"username": "testuser"})
    )
    result = await adapter.validate_key("valid-key")
    assert result is True


@respx.mock
async def test_validate_key_returns_false_on_401(adapter: OllamaCloudAdapter):
    respx.get("https://test.ollama.com/api/me").mock(
        return_value=httpx.Response(401)
    )
    result = await adapter.validate_key("invalid-key")
    assert result is False


@respx.mock
async def test_validate_key_returns_false_on_403(adapter: OllamaCloudAdapter):
    respx.get("https://test.ollama.com/api/me").mock(
        return_value=httpx.Response(403)
    )
    result = await adapter.validate_key("forbidden-key")
    assert result is False


@respx.mock
async def test_fetch_models_returns_models_with_capabilities(adapter: OllamaCloudAdapter):
    respx.get("https://test.ollama.com/api/tags").mock(
        return_value=httpx.Response(200, json={
            "models": [
                {"name": "mistral-large-3:675b"},
            ]
        })
    )
    respx.post("https://test.ollama.com/api/show").mock(
        return_value=httpx.Response(200, json={
            "details": {
                "parameter_size": "675000000000",
                "quantization_level": "FP8",
            },
            "model_info": {
                "general.architecture": "mistral3",
                "general.parameter_count": 675000000000,
                "mistral3.context_length": 262144,
            },
            "capabilities": ["completion", "tools", "vision"],
        })
    )

    models = await adapter.fetch_models()
    assert len(models) == 1

    m = models[0]
    assert m.provider_id == "ollama_cloud"
    assert m.model_id == "mistral-large-3:675b"
    assert m.display_name == "Mistral Large 3 (675B)"
    assert m.context_window == 262144
    assert m.supports_tool_calls is True
    assert m.supports_vision is True
    assert m.supports_reasoning is False
    assert m.parameter_count == "675B"
    assert m.quantisation_level == "FP8"


@respx.mock
async def test_fetch_models_handles_missing_details(adapter: OllamaCloudAdapter):
    respx.get("https://test.ollama.com/api/tags").mock(
        return_value=httpx.Response(200, json={
            "models": [{"name": "phi3"}]
        })
    )
    respx.post("https://test.ollama.com/api/show").mock(
        return_value=httpx.Response(200, json={
            "model_info": {
                "phi3.context_length": 4096,
            },
            "capabilities": ["completion"],
        })
    )

    models = await adapter.fetch_models()
    assert len(models) == 1

    m = models[0]
    assert m.parameter_count is None
    assert m.quantisation_level is None
    assert m.context_window == 4096
    assert m.supports_tool_calls is False
    assert m.supports_vision is False


@respx.mock
async def test_fetch_models_skips_model_on_show_failure(adapter: OllamaCloudAdapter):
    respx.get("https://test.ollama.com/api/tags").mock(
        return_value=httpx.Response(200, json={
            "models": [
                {"name": "good-model"},
                {"name": "broken-model"},
            ]
        })
    )
    respx.post(
        "https://test.ollama.com/api/show",
    ).mock(side_effect=[
        httpx.Response(200, json={
            "model_info": {"arch.context_length": 8192},
            "capabilities": ["completion"],
        }),
        httpx.Response(500),
    ])

    models = await adapter.fetch_models()
    assert len(models) == 1
    assert models[0].model_id == "good-model"


def test_format_parameter_count():
    from backend.modules.llm._adapters._ollama_cloud import _format_parameter_count

    assert _format_parameter_count(675_000_000_000) == "675B"
    assert _format_parameter_count(7_000_000_000) == "7B"
    assert _format_parameter_count(7_500_000_000) == "7.5B"
    assert _format_parameter_count(70_000_000_000) == "70B"
    assert _format_parameter_count(1_500_000_000_000) == "1.5T"
    assert _format_parameter_count(405_000_000) == "405M"
    assert _format_parameter_count(0) is None
    assert _format_parameter_count(None) is None
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd /home/chris/workspace/chatsune && docker compose run --rm backend uv run pytest tests/test_ollama_cloud_adapter.py -v`
Expected: FAIL (adapter not implemented yet)

- [ ] **Step 5: Implement OllamaCloudAdapter**

Replace `backend/modules/llm/_adapters/_ollama_cloud.py`:

```python
import logging

import httpx

from backend.modules.llm._adapters._base import BaseAdapter
from shared.dtos.llm import ModelMetaDto

_log = logging.getLogger(__name__)

_TIMEOUT = 15.0


def _format_parameter_count(value: int | None) -> str | None:
    """Convert raw parameter count to human-readable form (e.g. 675B, 7.5B, 405M)."""
    if not value:
        return None
    if value >= 1_000_000_000_000:
        n = value / 1_000_000_000_000
        return f"{n:g}T"
    if value >= 1_000_000_000:
        n = value / 1_000_000_000
        return f"{n:g}B"
    if value >= 1_000_000:
        n = value / 1_000_000
        return f"{n:g}M"
    return None


def _build_display_name(model_name: str) -> str:
    """Convert 'mistral-large-3:675b' to 'Mistral Large 3 (675B)'."""
    colon_idx = model_name.find(":")
    if colon_idx >= 0:
        name_part = model_name[:colon_idx]
        tag = model_name[colon_idx + 1:]
    else:
        name_part = model_name
        tag = None

    title = " ".join(word.capitalize() for word in name_part.split("-"))

    if not tag or tag.lower() == "latest":
        return title
    return f"{title} ({tag.upper()})"


class OllamaCloudAdapter(BaseAdapter):
    """Ollama Cloud inference adapter."""

    async def validate_key(self, api_key: str) -> bool:
        """Validate key via GET /api/me. Returns True on 200, False on 401/403."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{self.base_url}/api/me",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        return resp.status_code == 200

    async def fetch_models(self) -> list[ModelMetaDto]:
        """Fetch model list from /api/tags, then details from /api/show per model."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            tags_resp = await client.get(f"{self.base_url}/api/tags")
            tags_resp.raise_for_status()
            tag_entries = tags_resp.json().get("models", [])

            models: list[ModelMetaDto] = []
            for entry in tag_entries:
                name = entry["name"]
                try:
                    show_resp = await client.post(
                        f"{self.base_url}/api/show",
                        json={"model": name},
                    )
                    show_resp.raise_for_status()
                    detail = show_resp.json()
                except Exception:
                    _log.warning("Failed to fetch details for model '%s'; skipping.", name)
                    continue

                models.append(self._map_to_dto(name, detail))

        return models

    def _map_to_dto(self, model_name: str, detail: dict) -> ModelMetaDto:
        capabilities = detail.get("capabilities", [])
        model_info = detail.get("model_info", {})
        details = detail.get("details", {})

        # Extract context window from model_info (key ends with .context_length)
        context_window = 0
        for key, value in model_info.items():
            if key.endswith(".context_length") and isinstance(value, int):
                context_window = value
                break

        # Extract parameter count — prefer details.parameter_size, fall back to model_info
        raw_params = None
        param_str = details.get("parameter_size")
        if param_str is not None:
            try:
                raw_params = int(param_str)
            except (ValueError, TypeError):
                pass
        if raw_params is None:
            raw_params = model_info.get("general.parameter_count")

        return ModelMetaDto(
            provider_id="ollama_cloud",
            model_id=model_name,
            display_name=_build_display_name(model_name),
            context_window=context_window,
            supports_reasoning="thinking" in capabilities,
            supports_vision="vision" in capabilities,
            supports_tool_calls="tools" in capabilities,
            parameter_count=_format_parameter_count(raw_params),
            quantisation_level=details.get("quantization_level"),
        )
```

- [ ] **Step 6: Update handler to pass base_url when constructing adapters**

In `backend/modules/llm/_handlers.py`, update the two lines that construct adapters.

At the top, add import:
```python
from backend.modules.llm._registry import ADAPTER_REGISTRY, PROVIDER_DISPLAY_NAMES, PROVIDER_BASE_URLS
```

Replace `ADAPTER_REGISTRY[provider_id]()` (line 112 in test_provider_key):
```python
    adapter = ADAPTER_REGISTRY[provider_id](base_url=PROVIDER_BASE_URLS[provider_id])
```

Replace `ADAPTER_REGISTRY[provider_id]()` (line 143 in list_models):
```python
    adapter = ADAPTER_REGISTRY[provider_id](base_url=PROVIDER_BASE_URLS[provider_id])
```

- [ ] **Step 7: Run adapter tests to verify they pass**

Run: `cd /home/chris/workspace/chatsune && docker compose run --rm backend uv run pytest tests/test_ollama_cloud_adapter.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add backend/modules/llm/_adapters/_base.py backend/modules/llm/_adapters/_ollama_cloud.py backend/modules/llm/_registry.py backend/modules/llm/_handlers.py tests/test_ollama_cloud_adapter.py
git commit -m "Implement OllamaCloud adapter with key validation and model fetching"
```

---

### Task 4: Add ModelCurationDocument and CurationRepository

**Files:**
- Modify: `backend/modules/llm/_models.py`
- Create: `backend/modules/llm/_curation.py`
- Modify: `backend/modules/llm/__init__.py`

- [ ] **Step 1: Add ModelCurationDocument to _models.py**

Append to `backend/modules/llm/_models.py`:

```python
class ModelCurationDocument(BaseModel):
    """Internal MongoDB document for admin model curation. Never expose outside llm module."""

    id: str = Field(alias="_id")
    provider_id: str
    model_slug: str
    overall_rating: str
    hidden: bool
    admin_description: str | None
    last_curated_at: datetime
    last_curated_by: str

    model_config = {"populate_by_name": True}
```

- [ ] **Step 2: Create CurationRepository**

Create `backend/modules/llm/_curation.py`:

```python
from datetime import UTC, datetime
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from shared.dtos.llm import ModelCurationDto, ModelRating


class CurationRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db["llm_model_curations"]

    async def create_indexes(self) -> None:
        await self._collection.create_index(
            [("provider_id", 1), ("model_slug", 1)], unique=True
        )

    async def find(self, provider_id: str, model_slug: str) -> dict | None:
        return await self._collection.find_one(
            {"provider_id": provider_id, "model_slug": model_slug}
        )

    async def upsert(
        self,
        provider_id: str,
        model_slug: str,
        overall_rating: str,
        hidden: bool,
        admin_description: str | None,
        admin_user_id: str,
    ) -> dict:
        now = datetime.now(UTC)
        existing = await self.find(provider_id, model_slug)
        if existing:
            await self._collection.update_one(
                {"_id": existing["_id"]},
                {
                    "$set": {
                        "overall_rating": overall_rating,
                        "hidden": hidden,
                        "admin_description": admin_description,
                        "last_curated_at": now,
                        "last_curated_by": admin_user_id,
                    }
                },
            )
            return await self.find(provider_id, model_slug)
        doc = {
            "_id": str(uuid4()),
            "provider_id": provider_id,
            "model_slug": model_slug,
            "overall_rating": overall_rating,
            "hidden": hidden,
            "admin_description": admin_description,
            "last_curated_at": now,
            "last_curated_by": admin_user_id,
        }
        await self._collection.insert_one(doc)
        return doc

    async def delete(self, provider_id: str, model_slug: str) -> bool:
        result = await self._collection.delete_one(
            {"provider_id": provider_id, "model_slug": model_slug}
        )
        return result.deleted_count > 0

    async def list_for_provider(self, provider_id: str) -> list[dict]:
        cursor = self._collection.find({"provider_id": provider_id})
        return await cursor.to_list(length=1000)

    @staticmethod
    def to_dto(doc: dict) -> ModelCurationDto:
        return ModelCurationDto(
            overall_rating=ModelRating(doc["overall_rating"]),
            hidden=doc["hidden"],
            admin_description=doc.get("admin_description"),
            last_curated_at=doc["last_curated_at"],
            last_curated_by=doc["last_curated_by"],
        )
```

- [ ] **Step 3: Wire CurationRepository into __init__.py**

Replace `backend/modules/llm/__init__.py`:

```python
"""LLM module — inference provider adapters, user credentials, model metadata.

Public API: import only from this file.
"""

from backend.modules.llm._credentials import CredentialRepository
from backend.modules.llm._curation import CurationRepository
from backend.modules.llm._handlers import router
from backend.modules.llm._registry import ADAPTER_REGISTRY
from backend.database import get_db


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the LLM module collections."""
    await CredentialRepository(db).create_indexes()
    await CurationRepository(db).create_indexes()


def is_valid_provider(provider_id: str) -> bool:
    """Return True if provider_id is registered in the adapter registry."""
    return provider_id in ADAPTER_REGISTRY


__all__ = ["router", "init_indexes", "is_valid_provider"]
```

- [ ] **Step 4: Verify imports**

Run: `cd /home/chris/workspace/chatsune && python -c "from backend.modules.llm._curation import CurationRepository; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_models.py backend/modules/llm/_curation.py backend/modules/llm/__init__.py
git commit -m "Add model curation document and repository"
```

---

### Task 5: Update Metadata Cache to Publish Refresh Events

**Files:**
- Modify: `backend/modules/llm/_metadata.py`

- [ ] **Step 1: Update get_models to accept event_bus and publish on cache miss**

Replace `backend/modules/llm/_metadata.py`:

```python
import json
import logging
from datetime import datetime, timezone

from redis.asyncio import Redis

from backend.modules.llm._adapters._base import BaseAdapter
from shared.dtos.llm import ModelMetaDto
from shared.events.llm import LlmModelsRefreshedEvent
from shared.topics import Topics

_log = logging.getLogger(__name__)


async def get_models(
    provider_id: str,
    redis: Redis,
    adapter: BaseAdapter,
    event_bus=None,
) -> list[ModelMetaDto]:
    """Return cached model list or fetch from adapter on cache miss (TTL 30 min).

    Returns [] if the adapter is not yet implemented (NotImplementedError).
    See INSIGHTS.md INS-001 for the design reasoning.

    If event_bus is provided, publishes LLM_MODELS_REFRESHED on cache refresh.
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

    if event_bus is not None:
        try:
            await event_bus.publish(
                Topics.LLM_MODELS_REFRESHED,
                LlmModelsRefreshedEvent(
                    provider_id=provider_id,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
        except Exception:
            _log.warning("Failed to publish models_refreshed event for %s", provider_id)

    return models
```

- [ ] **Step 2: Verify import**

Run: `cd /home/chris/workspace/chatsune && python -c "from backend.modules.llm._metadata import get_models; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/modules/llm/_metadata.py
git commit -m "Publish models_refreshed event on cache miss reload"
```

---

### Task 6: Add Curation Endpoints and Merge Logic

**Files:**
- Modify: `backend/modules/llm/_handlers.py`
- Create: `tests/test_model_curation.py`

- [ ] **Step 1: Write the failing integration tests**

Create `tests/test_model_curation.py`:

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
    await client.post(
        "/api/users",
        json={
            "username": "regular",
            "email": "user@example.com",
            "password": "UserPass123",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    resp = await client.post(
        "/api/login",
        json={"username": "regular", "password": "UserPass123"},
    )
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_set_curation_requires_admin(client: AsyncClient):
    admin_token = await _setup_admin(client)
    user_token = await _setup_regular_user(client, admin_token)
    resp = await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/curation",
        json={"overall_rating": "recommended", "hidden": False},
        headers=_auth(user_token),
    )
    assert resp.status_code == 403


async def test_set_curation_success(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/curation",
        json={
            "overall_rating": "recommended",
            "hidden": False,
            "admin_description": "Great general-purpose model",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["overall_rating"] == "recommended"
    assert data["hidden"] is False
    assert data["admin_description"] == "Great general-purpose model"
    assert data["last_curated_by"] is not None


async def test_set_curation_unknown_provider(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.put(
        "/api/llm/providers/nonexistent/models/llama3/curation",
        json={"overall_rating": "available"},
        headers=_auth(token),
    )
    assert resp.status_code == 404


async def test_update_curation_overwrites(client: AsyncClient):
    token = await _setup_admin(client)
    await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/curation",
        json={"overall_rating": "recommended"},
        headers=_auth(token),
    )
    resp = await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/curation",
        json={"overall_rating": "not_recommended", "hidden": True},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["overall_rating"] == "not_recommended"
    assert data["hidden"] is True


async def test_delete_curation(client: AsyncClient):
    token = await _setup_admin(client)
    await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/curation",
        json={"overall_rating": "recommended"},
        headers=_auth(token),
    )
    resp = await client.delete(
        "/api/llm/providers/ollama_cloud/models/llama3/curation",
        headers=_auth(token),
    )
    assert resp.status_code == 200


async def test_delete_curation_when_none_exists(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.delete(
        "/api/llm/providers/ollama_cloud/models/llama3/curation",
        headers=_auth(token),
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/chris/workspace/chatsune && docker compose run --rm backend uv run pytest tests/test_model_curation.py -v`
Expected: FAIL (endpoints don't exist yet)

- [ ] **Step 3: Implement curation endpoints in _handlers.py**

Add these imports at the top of `backend/modules/llm/_handlers.py`:

```python
from backend.dependencies import require_admin
from backend.modules.llm._curation import CurationRepository
from backend.modules.llm._registry import PROVIDER_BASE_URLS
from shared.dtos.llm import ModelCurationDto, SetModelCurationDto
from shared.events.llm import LlmModelCuratedEvent, LlmModelsRefreshedEvent
```

Update the existing import line to also import `PROVIDER_BASE_URLS`:
```python
from backend.modules.llm._registry import ADAPTER_REGISTRY, PROVIDER_DISPLAY_NAMES, PROVIDER_BASE_URLS
```

Add helper:

```python
def _curation_repo() -> CurationRepository:
    return CurationRepository(get_db())
```

Update the `list_models` endpoint to merge curation data and pass event_bus:

```python
@router.get("/providers/{provider_id}/models")
async def list_models(
    provider_id: str,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    if provider_id not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    adapter = ADAPTER_REGISTRY[provider_id](base_url=PROVIDER_BASE_URLS[provider_id])
    redis = get_redis()
    models = await get_models(provider_id, redis, adapter, event_bus=event_bus)

    # Merge curation data
    curation_repo = _curation_repo()
    curations = await curation_repo.list_for_provider(provider_id)
    curation_map = {doc["model_slug"]: doc for doc in curations}

    result = []
    for model in models:
        curation_doc = curation_map.get(model.model_id)
        if curation_doc:
            model = model.model_copy(
                update={"curation": CurationRepository.to_dto(curation_doc)}
            )
        result.append(model)

    return result
```

Add curation endpoints:

```python
@router.put("/providers/{provider_id}/models/{model_slug:path}/curation", status_code=200)
async def set_model_curation(
    provider_id: str,
    model_slug: str,
    body: SetModelCurationDto,
    user: dict = Depends(require_admin),
    event_bus: EventBus = Depends(get_event_bus),
):
    if provider_id not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    repo = _curation_repo()
    doc = await repo.upsert(
        provider_id=provider_id,
        model_slug=model_slug,
        overall_rating=body.overall_rating.value,
        hidden=body.hidden,
        admin_description=body.admin_description,
        admin_user_id=user["sub"],
    )

    curation_dto = CurationRepository.to_dto(doc)

    # Build a minimal model DTO for the event payload
    model_dto = ModelMetaDto(
        provider_id=provider_id,
        model_id=model_slug,
        display_name=model_slug,  # best-effort; full name comes from cache
        context_window=0,
        supports_reasoning=False,
        supports_vision=False,
        supports_tool_calls=False,
        curation=curation_dto,
    )

    # Try to enrich from cache
    redis = get_redis()
    adapter = ADAPTER_REGISTRY[provider_id](base_url=PROVIDER_BASE_URLS[provider_id])
    cached_models = await get_models(provider_id, redis, adapter)
    for cached in cached_models:
        if cached.model_id == model_slug:
            model_dto = cached.model_copy(update={"curation": curation_dto})
            break

    await event_bus.publish(
        Topics.LLM_MODEL_CURATED,
        LlmModelCuratedEvent(
            provider_id=provider_id,
            model_slug=model_slug,
            model=model_dto,
            curated_by=user["sub"],
            timestamp=datetime.now(timezone.utc),
        ),
    )

    return curation_dto


@router.delete("/providers/{provider_id}/models/{model_slug:path}/curation", status_code=200)
async def remove_model_curation(
    provider_id: str,
    model_slug: str,
    user: dict = Depends(require_admin),
    event_bus: EventBus = Depends(get_event_bus),
):
    if provider_id not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    repo = _curation_repo()
    deleted = await repo.delete(provider_id, model_slug)
    if not deleted:
        raise HTTPException(status_code=404, detail="No curation exists for this model")

    # Publish event with curation=None (reverted to uncurated)
    model_dto = ModelMetaDto(
        provider_id=provider_id,
        model_id=model_slug,
        display_name=model_slug,
        context_window=0,
        supports_reasoning=False,
        supports_vision=False,
        supports_tool_calls=False,
        curation=None,
    )

    redis = get_redis()
    adapter = ADAPTER_REGISTRY[provider_id](base_url=PROVIDER_BASE_URLS[provider_id])
    cached_models = await get_models(provider_id, redis, adapter)
    for cached in cached_models:
        if cached.model_id == model_slug:
            model_dto = cached.model_copy(update={"curation": None})
            break

    await event_bus.publish(
        Topics.LLM_MODEL_CURATED,
        LlmModelCuratedEvent(
            provider_id=provider_id,
            model_slug=model_slug,
            model=model_dto,
            curated_by=user["sub"],
            timestamp=datetime.now(timezone.utc),
        ),
    )

    return {"status": "ok"}
```

- [ ] **Step 4: Run curation integration tests**

Run: `cd /home/chris/workspace/chatsune && docker compose run --rm backend uv run pytest tests/test_model_curation.py -v`
Expected: All PASS

- [ ] **Step 5: Run the full test suite to verify no regressions**

Run: `cd /home/chris/workspace/chatsune && docker compose run --rm backend uv run pytest -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_handlers.py tests/test_model_curation.py
git commit -m "Add model curation endpoints with event-based propagation"
```

---

### Task 7: Add respx Dependency

**Files:**
- Modify: `pyproject.toml`

This task must run before Task 3's tests can execute. It can be done as part of Task 3 or beforehand.

- [ ] **Step 1: Add respx to dev dependencies**

Run: `cd /home/chris/workspace/chatsune && docker compose run --rm backend uv add --dev respx`

- [ ] **Step 2: Verify it installs**

Run: `cd /home/chris/workspace/chatsune && docker compose run --rm backend uv run python -c "import respx; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "Add respx dev dependency for HTTP mocking"
```

---

### Task 8: Update INSIGHTS.md

**Files:**
- Modify: `INSIGHTS.md`

- [ ] **Step 1: Add INS-005 for the two-layer model data architecture**

Append to `INSIGHTS.md`:

```markdown
## INS-005: Two-Layer Model Data (Ephemeral + Persistent)

**Decision:** Provider model metadata (Redis, 30min TTL) is stored separately from admin curation (MongoDB, persistent). They are merged at read time.

**Why:** Provider data is volatile — models appear, disappear, change specs on the upstream. Curation is an admin decision that must survive cache flushes and temporary provider outages. Coupling them (as Prototype 2 did) means a cache flush or provider hiccup wipes admin work. Separating them means curation persists even if a model temporarily vanishes.

**Event differentiation:** `llm.model.curated` events carry the full merged DTO (instant client update). `llm.models.refreshed` events are trigger-only (client re-fetches). This distinction matters for frontend implementation: curated = update store in place, refreshed = invalidate and re-fetch.
```

- [ ] **Step 2: Commit**

```bash
git add INSIGHTS.md
git commit -m "Add INS-005: two-layer model data architecture decision"
```

---

## Execution Order

Tasks have the following dependencies:

1. **Task 1** (DTOs) — no dependencies, must come first
2. **Task 2** (Events + Topics + Fanout) — depends on Task 1
3. **Task 7** (respx dependency) — no dependencies, can run anytime before Task 3
4. **Task 3** (OllamaCloudAdapter) — depends on Tasks 1, 2, 7
5. **Task 4** (CurationRepository) — depends on Task 1
6. **Task 5** (Metadata refresh events) — depends on Task 2
7. **Task 6** (Curation endpoints + merge) — depends on Tasks 3, 4, 5
8. **Task 8** (INSIGHTS.md) — no code dependencies, can run anytime

Recommended order: 1 → 2 → 7 → 3 → 4 → 5 → 6 → 8

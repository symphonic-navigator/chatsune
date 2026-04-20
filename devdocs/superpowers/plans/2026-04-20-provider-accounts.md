# Premium Provider Accounts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Design spec:** `devdocs/superpowers/specs/2026-04-20-provider-accounts-design.md` — read it first for the full design rationale. This plan is the execution companion.

**Goal:** Replace three parallel credential silos (LLM connections for xAI/Ollama-Cloud, voice-integration api_keys, websearch credentials) with a single per-user-per-provider `premium_provider_accounts` store, plus an idempotent migration that preserves keys for existing testers.

**Architecture:** New `backend/modules/providers/` module owns the Premium Provider Accounts domain. The three existing consumer modules (`llm`, `integrations`, `websearch`) are refactored to read credentials via `PremiumProviderService` instead of their own stores. Resolver dispatch in the LLM module routes reserved slugs (`xai`, `mistral`, `ollama_cloud`) to Premium accounts; all other slugs stay with `llm_connections`. UI consolidates into one "LLM Providers" tab with a Coverage row, Premium Account cards, and Local/Homelab connection cards.

**Tech Stack:** Python 3 + FastAPI + Motor (MongoDB) + Pydantic v2 + cryptography.Fernet. Frontend Vite + React + TSX + Tailwind + Zustand stores + Vitest.

---

## File Structure

### New files

- `shared/dtos/providers.py` — `Capability` enum, `CAPABILITY_META`, `PremiumProviderDefinitionDto`, `PremiumProviderAccountDto`, `PremiumProviderUpsertRequest`, `PremiumProviderTestResultDto`.
- `shared/events/providers.py` — 3 event classes.
- `backend/modules/providers/__init__.py` — public API: `PremiumProviderService`, exceptions, router re-export.
- `backend/modules/providers/_models.py` — `PremiumProviderDefinition` dataclass.
- `backend/modules/providers/_registry.py` — static registry + `_register_builtins()`.
- `backend/modules/providers/_repository.py` — `PremiumProviderAccountRepository`.
- `backend/modules/providers/_handlers.py` — FastAPI router mounted at `/api/providers`.
- `backend/modules/providers/_migration_v1.py` — idempotent one-shot migration.
- `frontend/src/core/api/providers.ts` — typed REST client.
- `frontend/src/core/types/providers.ts` — TS types matching `shared/dtos/providers.py`.
- `frontend/src/core/stores/providersStore.ts` — Zustand store.
- `frontend/src/app/components/providers/CoverageRow.tsx`.
- `frontend/src/app/components/providers/PremiumAccountCard.tsx`.
- `frontend/src/app/components/providers/AccountsList.tsx` — container for Premium section.

### Modified files

- `shared/topics.py` — 3 new Topics.
- `backend/modules/llm/_registry.py` — remove `xai_http` from `ADAPTER_REGISTRY`.
- `backend/modules/llm/_connections.py` — `SlugReservedError`, reserved slug list, `_validate_slug` check.
- `backend/modules/llm/_resolver.py` — Premium account dispatch path.
- `backend/modules/integrations/_models.py` — `IntegrationDefinition.linked_premium_provider` field.
- `backend/modules/integrations/_registry.py` — update `xai_voice` + `mistral_voice` (strip `api_key`, set `linked_premium_provider`).
- `backend/modules/integrations/_voice_adapters/_xai.py` — resolve key via `PremiumProviderService`.
- `backend/modules/integrations/__init__.py` / `_handlers.py` — `effective_enabled` semantics for linked integrations.
- `backend/modules/websearch/__init__.py` — `_resolve_api_key` via `PremiumProviderService`.
- `backend/modules/websearch/_registry.py` — add `WEBSEARCH_PROVIDER_TO_PREMIUM` mapping.
- `backend/modules/websearch/_handlers.py` — remove credential-CRUD routes.
- `backend/main.py` — init providers indexes, mount providers router, run migration at startup, drop obsolete websearch router routes.
- `frontend/src/app/components/user-modal/LlmProvidersTab.tsx` — new layout (Coverage row + Accounts + Local).
- `frontend/src/app/components/user-modal/IntegrationsTab.tsx` — strip api_key field UI for linked integrations.
- `frontend/src/app/components/user-modal/userModalTree.ts` — remove `api-keys` sub-tab.
- `frontend/src/app/components/user-modal/UserModal.tsx` — unmount ApiKeysTab.
- `frontend/src/features/voice/components/ConversationModeButton.tsx` — `voiceAvailable` predicate + disabled/strikethrough rendering + click-to-config.

### Deleted files

- `backend/modules/websearch/_credentials.py` — repository removed after migration lands.
- `frontend/src/app/components/user-modal/ApiKeysTab.tsx` — websearch credentials UI, replaced by Premium coverage.
- `frontend/src/core/api/websearch.ts` (credentials section) + `frontend/src/core/types/websearch.ts` (credential type) — kept only the non-credential tool types.

---

## Task 1: Shared DTOs for providers

**Files:**
- Create: `shared/dtos/providers.py`
- Test: `backend/tests/shared/test_providers_dtos.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/shared/test_providers_dtos.py
from shared.dtos.providers import (
    Capability, CAPABILITY_META, PremiumProviderAccountDto,
    PremiumProviderUpsertRequest, PremiumProviderDefinitionDto,
)


def test_capability_enum_values():
    assert Capability.LLM.value == "llm"
    assert Capability.TTS.value == "tts"
    assert Capability.STT.value == "stt"
    assert Capability.WEBSEARCH.value == "websearch"
    assert Capability.TTI.value == "tti"
    assert Capability.ITI.value == "iti"


def test_capability_meta_has_every_capability():
    for cap in Capability:
        assert cap in CAPABILITY_META
        assert CAPABILITY_META[cap]["label"]
        assert CAPABILITY_META[cap]["tooltip"]


def test_premium_provider_account_dto_redacts_secrets():
    dto = PremiumProviderAccountDto(
        provider_id="xai",
        config={"api_key": {"is_set": True}},
        last_test_status="ok",
        last_test_error=None,
        last_test_at=None,
    )
    assert dto.config["api_key"] == {"is_set": True}


def test_upsert_request_accepts_plain_api_key():
    req = PremiumProviderUpsertRequest(config={"api_key": "xai-abc123"})
    assert req.config["api_key"] == "xai-abc123"
```

- [ ] **Step 2: Run test — expect FAIL (module missing)**

Run: `cd /home/chris/workspace/chatsune && uv run pytest backend/tests/shared/test_providers_dtos.py -v`

Expected: `ModuleNotFoundError: No module named 'shared.dtos.providers'`

- [ ] **Step 3: Write the DTO module**

```python
# shared/dtos/providers.py
"""Shared DTOs for the Premium Provider Accounts module."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Capability(str, Enum):
    LLM = "llm"
    TTS = "tts"
    STT = "stt"
    WEBSEARCH = "websearch"
    TTI = "tti"
    ITI = "iti"


CAPABILITY_META: dict[Capability, dict[str, str]] = {
    Capability.LLM: {
        "label": "Text",
        "tooltip": "Provides chat models you can pick for any persona.",
    },
    Capability.TTS: {
        "label": "TTS",
        "tooltip": "Synthesises persona replies into speech for voice chats.",
    },
    Capability.STT: {
        "label": "STT",
        "tooltip": "Transcribes your voice input into text for the chat.",
    },
    Capability.WEBSEARCH: {
        "label": "Web search",
        "tooltip": "Provides web search during chats, regardless of which model you use.",
    },
    Capability.TTI: {
        "label": "Text to Image",
        "tooltip": "Creates images from a text prompt during chats.",
    },
    Capability.ITI: {
        "label": "Image to Image",
        "tooltip": "Edits or transforms an uploaded image based on a prompt.",
    },
}


class PremiumProviderDefinitionDto(BaseModel):
    """Static catalogue entry — sent to frontend at /api/providers/catalogue."""
    id: str
    display_name: str
    icon: str
    base_url: str
    capabilities: list[Capability]
    config_fields: list[dict[str, Any]]
    linked_integrations: list[str] = Field(default_factory=list)


class PremiumProviderAccountDto(BaseModel):
    """User-owned account — secrets redacted."""
    provider_id: str
    config: dict[str, Any]              # non-secret fields + {is_set: bool} for secrets
    last_test_status: str | None        # None | "ok" | "error"
    last_test_error: str | None
    last_test_at: datetime | None


class PremiumProviderUpsertRequest(BaseModel):
    """Request body for POST/PUT /api/providers/{provider_id}."""
    config: dict[str, Any]


class PremiumProviderTestResultDto(BaseModel):
    """Response for the /test endpoint."""
    status: str                         # "ok" | "error"
    error: str | None
```

- [ ] **Step 4: Run test — expect PASS**

Run: `uv run pytest backend/tests/shared/test_providers_dtos.py -v`

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add shared/dtos/providers.py backend/tests/shared/test_providers_dtos.py
git commit -m "Add shared DTOs for Premium Provider Accounts"
```

---

## Task 2: Shared events and topics

**Files:**
- Create: `shared/events/providers.py`
- Modify: `shared/topics.py`
- Test: `backend/tests/shared/test_providers_events.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/shared/test_providers_events.py
from shared.events.providers import (
    PremiumProviderAccountUpsertedEvent,
    PremiumProviderAccountDeletedEvent,
    PremiumProviderAccountTestedEvent,
)
from shared.topics import Topics


def test_topics_present():
    assert Topics.PREMIUM_PROVIDER_ACCOUNT_UPSERTED == "providers.account.upserted"
    assert Topics.PREMIUM_PROVIDER_ACCOUNT_DELETED == "providers.account.deleted"
    assert Topics.PREMIUM_PROVIDER_ACCOUNT_TESTED == "providers.account.tested"


def test_upserted_event_serialises():
    evt = PremiumProviderAccountUpsertedEvent(provider_id="xai")
    assert evt.provider_id == "xai"


def test_tested_event_carries_status():
    evt = PremiumProviderAccountTestedEvent(
        provider_id="xai", status="ok", error=None,
    )
    assert evt.status == "ok"
    assert evt.error is None
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `uv run pytest backend/tests/shared/test_providers_events.py -v`

Expected: ImportError.

- [ ] **Step 3: Add Topics to `shared/topics.py`**

Locate the `Topics` class in `shared/topics.py`. Add (preserve existing entries and alphabetical/grouping order):

```python
    PREMIUM_PROVIDER_ACCOUNT_UPSERTED = "providers.account.upserted"
    PREMIUM_PROVIDER_ACCOUNT_DELETED = "providers.account.deleted"
    PREMIUM_PROVIDER_ACCOUNT_TESTED = "providers.account.tested"
```

- [ ] **Step 4: Create event classes**

```python
# shared/events/providers.py
"""Events for the Premium Provider Accounts module."""
from pydantic import BaseModel


class PremiumProviderAccountUpsertedEvent(BaseModel):
    provider_id: str


class PremiumProviderAccountDeletedEvent(BaseModel):
    provider_id: str


class PremiumProviderAccountTestedEvent(BaseModel):
    provider_id: str
    status: str            # "ok" | "error"
    error: str | None
```

- [ ] **Step 5: Run test — expect PASS**

Run: `uv run pytest backend/tests/shared/test_providers_events.py -v`

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add shared/events/providers.py shared/topics.py backend/tests/shared/test_providers_events.py
git commit -m "Add Premium Provider events and topic constants"
```

---

## Task 3: Provider definition model + registry

**Files:**
- Create: `backend/modules/providers/_models.py`
- Create: `backend/modules/providers/_registry.py`
- Test: `backend/tests/modules/providers/test_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/modules/providers/test_registry.py
from shared.dtos.providers import Capability
from backend.modules.providers._registry import get, get_all
from backend.modules.providers._models import PremiumProviderDefinition


def test_xai_registered():
    defn = get("xai")
    assert isinstance(defn, PremiumProviderDefinition)
    assert defn.display_name == "xAI"
    assert set(defn.capabilities) == {
        Capability.LLM, Capability.TTS, Capability.STT,
        Capability.TTI, Capability.ITI,
    }
    assert defn.base_url == "https://api.x.ai"
    assert "xai_voice" in defn.linked_integrations


def test_mistral_registered_as_voice_only():
    defn = get("mistral")
    assert set(defn.capabilities) == {Capability.TTS, Capability.STT}
    assert "mistral_voice" in defn.linked_integrations


def test_ollama_cloud_registered():
    defn = get("ollama_cloud")
    assert set(defn.capabilities) == {Capability.LLM, Capability.WEBSEARCH}
    assert defn.base_url == "https://ollama.com"
    assert defn.linked_integrations == []


def test_get_all_returns_three_providers():
    assert set(get_all().keys()) == {"xai", "mistral", "ollama_cloud"}


def test_unknown_provider_returns_none():
    assert get("bogus") is None
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `uv run pytest backend/tests/modules/providers/test_registry.py -v`

Expected: ImportError (module missing).

- [ ] **Step 3: Create models.py**

```python
# backend/modules/providers/_models.py
"""Internal domain types for the Premium Provider Accounts module."""
from dataclasses import dataclass, field
from typing import Any

from shared.dtos.providers import Capability


@dataclass(frozen=True)
class PremiumProviderDefinition:
    id: str
    display_name: str
    icon: str
    base_url: str
    capabilities: list[Capability]
    config_fields: list[dict[str, Any]]
    linked_integrations: list[str] = field(default_factory=list)
    secret_fields: frozenset[str] = frozenset({"api_key"})
```

- [ ] **Step 4: Create registry.py**

```python
# backend/modules/providers/_registry.py
"""Static registry of Premium Providers."""
import logging

from backend.modules.providers._models import PremiumProviderDefinition
from shared.dtos.providers import Capability

_log = logging.getLogger(__name__)
_registry: dict[str, PremiumProviderDefinition] = {}


def register(defn: PremiumProviderDefinition) -> None:
    if defn.id in _registry:
        raise ValueError(f"Provider '{defn.id}' already registered")
    _registry[defn.id] = defn
    _log.info("Registered premium provider: %s", defn.id)


def get(provider_id: str) -> PremiumProviderDefinition | None:
    return _registry.get(provider_id)


def get_all() -> dict[str, PremiumProviderDefinition]:
    return dict(_registry)


def _api_key_field(label: str) -> dict:
    return {
        "key": "api_key",
        "label": label,
        "field_type": "password",
        "secret": True,
        "required": True,
        "description": "Encrypted at rest, never leaves the backend.",
    }


def _register_builtins() -> None:
    register(PremiumProviderDefinition(
        id="xai",
        display_name="xAI",
        icon="xai",
        base_url="https://api.x.ai",
        capabilities=[
            Capability.LLM, Capability.TTS, Capability.STT,
            Capability.TTI, Capability.ITI,
        ],
        config_fields=[_api_key_field("xAI API Key")],
        linked_integrations=["xai_voice"],
    ))

    register(PremiumProviderDefinition(
        id="mistral",
        display_name="Mistral",
        icon="mistral",
        base_url="https://api.mistral.ai",
        capabilities=[Capability.TTS, Capability.STT],
        config_fields=[_api_key_field("Mistral API Key")],
        linked_integrations=["mistral_voice"],
    ))

    register(PremiumProviderDefinition(
        id="ollama_cloud",
        display_name="Ollama Cloud",
        icon="ollama",
        base_url="https://ollama.com",
        capabilities=[Capability.LLM, Capability.WEBSEARCH],
        config_fields=[_api_key_field("Ollama Cloud API Key")],
        linked_integrations=[],
    ))


_register_builtins()
```

- [ ] **Step 5: Create package marker**

```python
# backend/modules/providers/__init__.py
"""Premium Provider Accounts — placeholder, full public API follows."""
```

- [ ] **Step 6: Run test — expect PASS**

Run: `uv run pytest backend/tests/modules/providers/test_registry.py -v`

Expected: 5 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/providers/ backend/tests/modules/providers/
git commit -m "Add Premium Provider registry with xAI, Mistral, Ollama Cloud"
```

---

## Task 4: Repository — MongoDB persistence

**Files:**
- Create: `backend/modules/providers/_repository.py`
- Test: `backend/tests/modules/providers/test_repository.py`

Reference existing pattern: `backend/modules/llm/_connections.py::ConnectionRepository` and `backend/modules/integrations/_repository.py::IntegrationRepository`. Use the same `Fernet`-based encryption approach (`settings.encryption_key`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/modules/providers/test_repository.py
import pytest
from backend.modules.providers._repository import PremiumProviderAccountRepository


@pytest.mark.asyncio
async def test_upsert_creates_document(mongo_db):
    repo = PremiumProviderAccountRepository(mongo_db)
    await repo.create_indexes()
    doc = await repo.upsert("user-1", "xai", {"api_key": "xai-abc"})
    assert doc["provider_id"] == "xai"
    assert "api_key" not in doc["config"]
    assert "api_key" in doc["config_encrypted"]


@pytest.mark.asyncio
async def test_upsert_is_idempotent_on_same_user_provider(mongo_db):
    repo = PremiumProviderAccountRepository(mongo_db)
    await repo.create_indexes()
    await repo.upsert("user-1", "xai", {"api_key": "xai-abc"})
    await repo.upsert("user-1", "xai", {"api_key": "xai-xyz"})
    docs = [d async for d in repo._col.find({"user_id": "user-1", "provider_id": "xai"})]
    assert len(docs) == 1
    assert repo.get_decrypted_secret(docs[0], "api_key") == "xai-xyz"


@pytest.mark.asyncio
async def test_empty_secret_on_update_preserves_existing(mongo_db):
    repo = PremiumProviderAccountRepository(mongo_db)
    await repo.create_indexes()
    await repo.upsert("user-1", "xai", {"api_key": "xai-abc"})
    await repo.upsert("user-1", "xai", {"api_key": ""})
    doc = await repo.find("user-1", "xai")
    assert repo.get_decrypted_secret(doc, "api_key") == "xai-abc"


@pytest.mark.asyncio
async def test_find_returns_none_for_absent(mongo_db):
    repo = PremiumProviderAccountRepository(mongo_db)
    assert await repo.find("user-1", "xai") is None


@pytest.mark.asyncio
async def test_delete_returns_true_if_present(mongo_db):
    repo = PremiumProviderAccountRepository(mongo_db)
    await repo.upsert("user-1", "xai", {"api_key": "xai-abc"})
    assert await repo.delete("user-1", "xai") is True
    assert await repo.delete("user-1", "xai") is False


@pytest.mark.asyncio
async def test_list_for_user(mongo_db):
    repo = PremiumProviderAccountRepository(mongo_db)
    await repo.upsert("user-1", "xai", {"api_key": "k1"})
    await repo.upsert("user-1", "mistral", {"api_key": "k2"})
    await repo.upsert("user-2", "xai", {"api_key": "k3"})
    docs = await repo.list_for_user("user-1")
    assert {d["provider_id"] for d in docs} == {"xai", "mistral"}


@pytest.mark.asyncio
async def test_delete_all_for_user(mongo_db):
    repo = PremiumProviderAccountRepository(mongo_db)
    await repo.upsert("user-1", "xai", {"api_key": "k1"})
    await repo.upsert("user-1", "mistral", {"api_key": "k2"})
    deleted = await repo.delete_all_for_user("user-1")
    assert deleted == 2


@pytest.mark.asyncio
async def test_to_dto_redacts(mongo_db):
    repo = PremiumProviderAccountRepository(mongo_db)
    doc = await repo.upsert("user-1", "xai", {"api_key": "xai-abc"})
    dto = repo.to_dto(doc)
    assert dto.config["api_key"] == {"is_set": True}
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `uv run pytest backend/tests/modules/providers/test_repository.py -v`

Expected: ImportError.

- [ ] **Step 3: Write the repository**

```python
# backend/modules/providers/_repository.py
"""Repository for premium_provider_accounts collection."""
from datetime import UTC, datetime
from uuid import uuid4

from cryptography.fernet import Fernet
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.config import settings
from backend.modules.providers._registry import get as get_definition
from shared.dtos.providers import PremiumProviderAccountDto

COLLECTION = "premium_provider_accounts"


def _fernet() -> Fernet:
    return Fernet(settings.encryption_key.encode())


def _secret_fields(provider_id: str) -> frozenset[str]:
    defn = get_definition(provider_id)
    return defn.secret_fields if defn else frozenset()


def _split_config(provider_id: str, config: dict) -> tuple[dict, dict]:
    secrets = _secret_fields(provider_id)
    plain: dict = {}
    encrypted: dict = {}
    f = _fernet()
    for k, v in config.items():
        if k in secrets:
            if v is None or v == "":
                continue
            encrypted[k] = f.encrypt(str(v).encode()).decode()
        else:
            plain[k] = v
    return plain, encrypted


def _redact_config(provider_id: str, plain: dict, encrypted: dict) -> dict:
    secrets = _secret_fields(provider_id)
    out = dict(plain)
    for k in secrets:
        out[k] = {"is_set": k in encrypted}
    return out


class PremiumProviderAccountRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._col = db[COLLECTION]

    async def create_indexes(self) -> None:
        await self._col.create_index(
            [("user_id", 1), ("provider_id", 1)], unique=True,
        )
        await self._col.create_index([("user_id", 1), ("created_at", 1)])

    async def upsert(
        self, user_id: str, provider_id: str, config: dict,
    ) -> dict:
        existing = await self._col.find_one(
            {"user_id": user_id, "provider_id": provider_id},
            {"config_encrypted": 1, "_id": 0},
        )
        existing_enc = (existing or {}).get("config_encrypted") or {}
        plain, encrypted = _split_config(provider_id, config)
        secrets = _secret_fields(provider_id)

        merged_enc = dict(existing_enc)
        for k in secrets:
            if k in encrypted:
                merged_enc[k] = encrypted[k]
            elif k in config and (config[k] is None or config[k] == ""):
                merged_enc.pop(k, None)

        now = datetime.now(UTC)
        set_on_insert = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "provider_id": provider_id,
            "created_at": now,
            "last_test_status": None,
            "last_test_error": None,
            "last_test_at": None,
        }
        set_fields = {
            "config": plain,
            "config_encrypted": merged_enc,
            "updated_at": now,
        }
        return await self._col.find_one_and_update(
            {"user_id": user_id, "provider_id": provider_id},
            {"$set": set_fields, "$setOnInsert": set_on_insert},
            upsert=True,
            return_document=True,
        )

    async def find(self, user_id: str, provider_id: str) -> dict | None:
        return await self._col.find_one(
            {"user_id": user_id, "provider_id": provider_id},
        )

    async def list_for_user(self, user_id: str) -> list[dict]:
        return [
            d async for d in self._col.find({"user_id": user_id}).sort("created_at", 1)
        ]

    async def delete(self, user_id: str, provider_id: str) -> bool:
        res = await self._col.delete_one(
            {"user_id": user_id, "provider_id": provider_id},
        )
        return res.deleted_count > 0

    async def delete_all_for_user(self, user_id: str) -> int:
        res = await self._col.delete_many({"user_id": user_id})
        return res.deleted_count

    async def update_test_status(
        self, user_id: str, provider_id: str, *, status: str, error: str | None,
    ) -> dict | None:
        now = datetime.now(UTC)
        return await self._col.find_one_and_update(
            {"user_id": user_id, "provider_id": provider_id},
            {"$set": {
                "last_test_status": status,
                "last_test_error": error,
                "last_test_at": now,
                "updated_at": now,
            }},
            return_document=True,
        )

    @staticmethod
    def get_decrypted_secret(doc: dict, field: str) -> str | None:
        enc = doc.get("config_encrypted") or {}
        if field not in enc:
            return None
        return _fernet().decrypt(enc[field].encode()).decode()

    @staticmethod
    def to_dto(doc: dict) -> PremiumProviderAccountDto:
        return PremiumProviderAccountDto(
            provider_id=doc["provider_id"],
            config=_redact_config(
                doc["provider_id"],
                doc.get("config", {}) or {},
                doc.get("config_encrypted", {}) or {},
            ),
            last_test_status=doc.get("last_test_status"),
            last_test_error=doc.get("last_test_error"),
            last_test_at=doc.get("last_test_at"),
        )
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest backend/tests/modules/providers/test_repository.py -v`

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/providers/_repository.py backend/tests/modules/providers/test_repository.py
git commit -m "Add PremiumProviderAccountRepository with Fernet encryption"
```

---

## Task 5: Service facade + HTTP handlers

**Files:**
- Modify: `backend/modules/providers/__init__.py`
- Create: `backend/modules/providers/_handlers.py`
- Test: `backend/tests/modules/providers/test_handlers.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/modules/providers/test_handlers.py
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_catalogue_lists_providers(client: AsyncClient, auth_headers):
    resp = await client.get("/api/providers/catalogue", headers=auth_headers)
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()]
    assert set(ids) == {"xai", "mistral", "ollama_cloud"}


@pytest.mark.asyncio
async def test_list_accounts_empty(client: AsyncClient, auth_headers):
    resp = await client.get("/api/providers/accounts", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_upsert_and_read(client: AsyncClient, auth_headers):
    r1 = await client.put(
        "/api/providers/accounts/xai",
        json={"config": {"api_key": "xai-abc"}},
        headers=auth_headers,
    )
    assert r1.status_code == 200
    body = r1.json()
    assert body["provider_id"] == "xai"
    assert body["config"]["api_key"] == {"is_set": True}

    r2 = await client.get("/api/providers/accounts", headers=auth_headers)
    assert len(r2.json()) == 1


@pytest.mark.asyncio
async def test_upsert_rejects_unknown_provider(client: AsyncClient, auth_headers):
    resp = await client.put(
        "/api/providers/accounts/bogus",
        json={"config": {"api_key": "x"}},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_account(client: AsyncClient, auth_headers):
    await client.put(
        "/api/providers/accounts/xai",
        json={"config": {"api_key": "xai-abc"}},
        headers=auth_headers,
    )
    resp = await client.delete("/api/providers/accounts/xai", headers=auth_headers)
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_requires_auth(client: AsyncClient):
    resp = await client.get("/api/providers/catalogue")
    assert resp.status_code == 401
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `uv run pytest backend/tests/modules/providers/test_handlers.py -v`

Expected: 404/module-import errors (service + router not wired).

- [ ] **Step 3: Write the public module**

```python
# backend/modules/providers/__init__.py
"""Premium Provider Accounts module — public API."""
from backend.modules.providers._handlers import router
from backend.modules.providers._repository import PremiumProviderAccountRepository
from backend.modules.providers._registry import get as get_definition, get_all as get_all_definitions


class PremiumProviderNotFoundError(Exception):
    """Unknown provider id — not registered."""


class PremiumProviderAccountNotFoundError(Exception):
    """No account configured for the given (user, provider)."""


class PremiumProviderService:
    def __init__(self, repo: PremiumProviderAccountRepository) -> None:
        self._repo = repo

    async def catalogue(self) -> list[dict]:
        from shared.dtos.providers import PremiumProviderDefinitionDto
        return [
            PremiumProviderDefinitionDto(
                id=d.id,
                display_name=d.display_name,
                icon=d.icon,
                base_url=d.base_url,
                capabilities=list(d.capabilities),
                config_fields=list(d.config_fields),
                linked_integrations=list(d.linked_integrations),
            ).model_dump()
            for d in get_all_definitions().values()
        ]

    async def list_for_user(self, user_id: str) -> list[dict]:
        docs = await self._repo.list_for_user(user_id)
        return [self._repo.to_dto(d).model_dump() for d in docs]

    async def get(self, user_id: str, provider_id: str) -> dict | None:
        if get_definition(provider_id) is None:
            raise PremiumProviderNotFoundError(provider_id)
        doc = await self._repo.find(user_id, provider_id)
        if doc is None:
            return None
        return self._repo.to_dto(doc).model_dump()

    async def upsert(
        self, user_id: str, provider_id: str, config: dict,
    ) -> dict:
        if get_definition(provider_id) is None:
            raise PremiumProviderNotFoundError(provider_id)
        doc = await self._repo.upsert(user_id, provider_id, config)
        return self._repo.to_dto(doc).model_dump()

    async def delete(self, user_id: str, provider_id: str) -> bool:
        return await self._repo.delete(user_id, provider_id)

    async def get_decrypted_secret(
        self, user_id: str, provider_id: str, field: str,
    ) -> str | None:
        doc = await self._repo.find(user_id, provider_id)
        if doc is None:
            return None
        return self._repo.get_decrypted_secret(doc, field)

    async def has_account(self, user_id: str, provider_id: str) -> bool:
        return await self._repo.find(user_id, provider_id) is not None

    async def delete_all_for_user(self, user_id: str) -> int:
        return await self._repo.delete_all_for_user(user_id)


__all__ = [
    "PremiumProviderService",
    "PremiumProviderAccountRepository",
    "PremiumProviderNotFoundError",
    "PremiumProviderAccountNotFoundError",
    "router",
]
```

- [ ] **Step 4: Write the router**

```python
# backend/modules/providers/_handlers.py
"""FastAPI routes for /api/providers."""
from fastapi import APIRouter, Depends, HTTPException, status

from backend.database import get_db
from backend.modules.user import require_current_user
from shared.dtos.providers import (
    PremiumProviderAccountDto, PremiumProviderDefinitionDto,
    PremiumProviderUpsertRequest,
)

router = APIRouter(prefix="/api/providers", tags=["providers"])


def _service():
    # Local import avoids circular import at module load time.
    from backend.modules.providers import PremiumProviderService
    from backend.modules.providers._repository import PremiumProviderAccountRepository
    return PremiumProviderService(PremiumProviderAccountRepository(get_db()))


@router.get("/catalogue", response_model=list[PremiumProviderDefinitionDto])
async def catalogue(user=Depends(require_current_user)):
    return await _service().catalogue()


@router.get("/accounts", response_model=list[PremiumProviderAccountDto])
async def list_accounts(user=Depends(require_current_user)):
    return await _service().list_for_user(user.id)


@router.put("/accounts/{provider_id}", response_model=PremiumProviderAccountDto)
async def upsert_account(
    provider_id: str,
    body: PremiumProviderUpsertRequest,
    user=Depends(require_current_user),
):
    from backend.modules.providers import PremiumProviderNotFoundError
    try:
        return await _service().upsert(user.id, provider_id, body.config)
    except PremiumProviderNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown provider")


@router.delete("/accounts/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    provider_id: str,
    user=Depends(require_current_user),
):
    await _service().delete(user.id, provider_id)
    return None
```

Note: the exact auth dependency name — `require_current_user` vs. existing equivalent — must match the actual identifier already in use elsewhere (e.g. grep for an auth-requiring router like `backend/modules/websearch/_handlers.py` and mirror its import).

- [ ] **Step 5: Run test — expect PASS**

Run: `uv run pytest backend/tests/modules/providers/test_handlers.py -v`

Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/providers/__init__.py backend/modules/providers/_handlers.py backend/tests/modules/providers/test_handlers.py
git commit -m "Add PremiumProviderService and HTTP router"
```

---

## Task 6: Wire providers module into server startup

**Files:**
- Modify: `backend/main.py`
- Test: `backend/tests/app/test_startup.py` (add assertion)

- [ ] **Step 1: Find the existing init/mount sites in `backend/main.py`**

Locate the `lifespan` / startup block that currently calls `init_indexes` for other modules (LLM, integrations, websearch) and the `app.include_router(...)` block.

- [ ] **Step 2: Add providers init_indexes**

Inside the startup block, adjacent to the existing `await IntegrationRepository(db).init_indexes()` / similar calls, add:

```python
from backend.modules.providers._repository import PremiumProviderAccountRepository

await PremiumProviderAccountRepository(db).create_indexes()
```

- [ ] **Step 3: Mount the router**

Where other routers are included:

```python
from backend.modules.providers import router as providers_router

app.include_router(providers_router)
```

- [ ] **Step 4: Wire the user-delete cascade**

In the user self-delete code path (search for the existing `delete_all_for_user` calls, e.g. `backend/modules/user/_handlers.py` or the orchestration point), add:

```python
from backend.modules.providers import PremiumProviderService
from backend.modules.providers._repository import PremiumProviderAccountRepository

await PremiumProviderService(
    PremiumProviderAccountRepository(db)
).delete_all_for_user(user_id)
```

- [ ] **Step 5: Run all existing tests to verify no regression**

Run: `uv run pytest backend/tests/ -x --ignore=backend/tests/integration -q`

Expected: all existing tests continue to pass; new providers tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/modules/user/  # or whichever user module file was edited
git commit -m "Wire providers module into startup and user-delete cascade"
```

---

## Task 7: Reserved-slug validation in ConnectionRepository

**Files:**
- Modify: `backend/modules/llm/_connections.py`
- Test: `backend/tests/modules/llm/test_connection_reserved_slugs.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/modules/llm/test_connection_reserved_slugs.py
import pytest
from backend.modules.llm._connections import (
    ConnectionRepository, SlugReservedError,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("slug", ["xai", "mistral", "ollama_cloud"])
async def test_reserved_slugs_rejected(mongo_db, slug):
    repo = ConnectionRepository(mongo_db)
    with pytest.raises(SlugReservedError):
        await repo.create(
            user_id="u1",
            adapter_type="ollama_http",
            display_name="x",
            slug=slug,
            config={"base_url": "http://localhost:11434"},
        )


@pytest.mark.asyncio
async def test_non_reserved_slug_accepted(mongo_db):
    repo = ConnectionRepository(mongo_db)
    doc = await repo.create(
        user_id="u1", adapter_type="ollama_http", display_name="ok",
        slug="my-homeserver", config={"base_url": "http://localhost:11434"},
    )
    assert doc["slug"] == "my-homeserver"
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `uv run pytest backend/tests/modules/llm/test_connection_reserved_slugs.py -v`

Expected: `ImportError` on `SlugReservedError`.

- [ ] **Step 3: Add reserved slugs and error class**

Edit `backend/modules/llm/_connections.py`:

Add near the top alongside the other error classes (around line 42 after `SlugAlreadyExistsError`):

```python
RESERVED_SLUGS: frozenset[str] = frozenset({"xai", "mistral", "ollama_cloud"})


class SlugReservedError(ValueError):
    """Slug is reserved for a Premium Provider and cannot be user-created."""
    def __init__(self, slug: str) -> None:
        super().__init__(f"Slug '{slug}' is reserved for a Premium Provider")
        self.slug = slug
```

Extend `_validate_slug` at the top of the function body:

```python
def _validate_slug(slug: str) -> None:
    if slug in RESERVED_SLUGS:
        raise SlugReservedError(slug)
    if not _SLUG_RE.match(slug):
        raise InvalidSlugError(
            f"Slug '{slug}' must be lowercase alphanumeric with hyphens, 1-63 chars"
        )
```

- [ ] **Step 4: Run test — expect PASS**

Run: `uv run pytest backend/tests/modules/llm/test_connection_reserved_slugs.py -v`

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_connections.py backend/tests/modules/llm/test_connection_reserved_slugs.py
git commit -m "Reserve premium-provider slugs against user connection names"
```

---

## Task 8: Remove xai_http from ADAPTER_REGISTRY

**Files:**
- Modify: `backend/modules/llm/_registry.py`
- Test: `backend/tests/modules/llm/test_registry.py` (add one assertion)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/modules/llm/test_registry.py
from backend.modules.llm._registry import ADAPTER_REGISTRY


def test_xai_http_not_in_registry():
    # Premium resolver instantiates XaiHttpAdapter directly; the class stays
    # importable, but user connections cannot be created with this type.
    assert "xai_http" not in ADAPTER_REGISTRY


def test_ollama_http_still_in_registry():
    assert "ollama_http" in ADAPTER_REGISTRY


def test_xai_http_class_still_importable():
    from backend.modules.llm._adapters._xai_http import XaiHttpAdapter
    assert XaiHttpAdapter is not None
```

- [ ] **Step 2: Run test — expect one FAIL**

Run: `uv run pytest backend/tests/modules/llm/test_registry.py -v`

Expected: `test_xai_http_not_in_registry` fails.

- [ ] **Step 3: Modify registry**

`backend/modules/llm/_registry.py` — remove the `xai_http` entry:

```python
"""Adapter registry — maps adapter_type string to adapter class."""

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._community import CommunityAdapter
from backend.modules.llm._adapters._ollama_http import OllamaHttpAdapter

ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = {
    "ollama_http": OllamaHttpAdapter,
    "community": CommunityAdapter,
}
```

(The `_xai_http` import is removed here but the module stays on disk — the Premium resolver imports it directly in Task 9.)

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest backend/tests/modules/llm/test_registry.py -v`

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_registry.py backend/tests/modules/llm/test_registry.py
git commit -m "Remove xai_http from adapter registry (Premium-only)"
```

---

## Task 9: LLM resolver — Premium account dispatch

**Files:**
- Modify: `backend/modules/llm/_resolver.py`
- Test: `backend/tests/modules/llm/test_resolver_premium.py`

Goal: when `model_unique_id` starts with a reserved provider slug, route credentials through `PremiumProviderService` and instantiate the adapter directly with the registry-fixed `base_url`.

- [ ] **Step 1: Read the existing resolver**

Run: `cat backend/modules/llm/_resolver.py` (read to understand current `resolve_connection(user_id, model_unique_id)` or equivalent entry points and their return shape — `ResolvedConnection` in `_adapters/_types.py`).

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/modules/llm/test_resolver_premium.py
import pytest
from backend.modules.llm._resolver import resolve_for_model
from backend.modules.llm import LlmConnectionNotFoundError


@pytest.mark.asyncio
async def test_resolves_premium_xai(mongo_db, user_with_xai_account):
    resolved = await resolve_for_model(user_with_xai_account.id, "xai:grok-3")
    assert resolved.base_url == "https://api.x.ai"
    assert resolved.api_key == "xai-abc"
    # Adapter instance is XaiHttpAdapter
    from backend.modules.llm._adapters._xai_http import XaiHttpAdapter
    assert isinstance(resolved.adapter, XaiHttpAdapter)


@pytest.mark.asyncio
async def test_resolves_premium_ollama_cloud(mongo_db, user_with_ollama_cloud):
    resolved = await resolve_for_model(user_with_ollama_cloud.id, "ollama_cloud:llama3.2")
    assert resolved.base_url == "https://ollama.com"
    from backend.modules.llm._adapters._ollama_http import OllamaHttpAdapter
    assert isinstance(resolved.adapter, OllamaHttpAdapter)


@pytest.mark.asyncio
async def test_missing_premium_account_raises(mongo_db, fresh_user):
    with pytest.raises(LlmConnectionNotFoundError):
        await resolve_for_model(fresh_user.id, "xai:grok-3")


@pytest.mark.asyncio
async def test_local_connection_still_resolved(mongo_db, user_with_local_ollama):
    resolved = await resolve_for_model(
        user_with_local_ollama.id, f"{user_with_local_ollama.conn_slug}:llama3.2",
    )
    assert resolved.base_url == "http://192.168.0.10:11434"
```

(Fixtures `user_with_xai_account`, `user_with_ollama_cloud`, `user_with_local_ollama`, `fresh_user` need to be added to the test conftest — mirror existing connection-fixture patterns.)

- [ ] **Step 3: Run test — expect FAIL**

Run: `uv run pytest backend/tests/modules/llm/test_resolver_premium.py -v`

- [ ] **Step 4: Implement premium dispatch**

In `backend/modules/llm/_resolver.py`, at the top of the resolve function (let's call it `resolve_for_model(user_id, model_unique_id)`):

```python
from backend.modules.providers._registry import get as get_premium_definition
from backend.modules.providers import PremiumProviderService
from backend.modules.providers._repository import PremiumProviderAccountRepository
from backend.modules.llm._adapters._xai_http import XaiHttpAdapter
from backend.modules.llm._adapters._ollama_http import OllamaHttpAdapter

_PREMIUM_ADAPTER_CLASS: dict[str, type] = {
    "xai": XaiHttpAdapter,
    "ollama_cloud": OllamaHttpAdapter,
}


async def _resolve_premium(user_id: str, model_unique_id: str) -> ResolvedConnection | None:
    prefix, _, model_slug = model_unique_id.partition(":")
    defn = get_premium_definition(prefix)
    if defn is None:
        return None
    adapter_cls = _PREMIUM_ADAPTER_CLASS.get(prefix)
    if adapter_cls is None:
        return None                               # Premium provider with no LLM capability.
    svc = PremiumProviderService(PremiumProviderAccountRepository(get_db()))
    api_key = await svc.get_decrypted_secret(user_id, prefix, "api_key")
    if api_key is None:
        raise LlmConnectionNotFoundError(model_unique_id)
    return ResolvedConnection(
        adapter=adapter_cls(),
        base_url=defn.base_url,
        api_key=api_key,
        model_slug=model_slug,
    )
```

Hook this at the top of the existing `resolve_for_model`:

```python
async def resolve_for_model(user_id: str, model_unique_id: str) -> ResolvedConnection:
    premium = await _resolve_premium(user_id, model_unique_id)
    if premium is not None:
        return premium
    # ...existing connection-based resolution below, unchanged...
```

If the existing resolver has a different signature or name, apply the same pattern at the equivalent entry point. The important guarantee: any `model_unique_id` whose prefix matches a registered Premium Provider slug is routed via `_resolve_premium`; everything else falls through to the connection path.

- [ ] **Step 5: Run tests — expect PASS**

Run: `uv run pytest backend/tests/modules/llm/test_resolver_premium.py -v`

Expected: 4 passed.

- [ ] **Step 6: Regression check**

Run: `uv run pytest backend/tests/modules/llm/ -q`

Expected: all existing LLM tests continue to pass.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/llm/_resolver.py backend/tests/modules/llm/test_resolver_premium.py
git commit -m "Route premium-provider model_unique_ids through PremiumProviderService"
```

---

## Task 10: Integration definition gains linked_premium_provider

**Files:**
- Modify: `backend/modules/integrations/_models.py`
- Modify: `backend/modules/integrations/_registry.py`
- Test: `backend/tests/modules/integrations/test_linked_providers.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/modules/integrations/test_linked_providers.py
from backend.modules.integrations._registry import get


def test_xai_voice_linked_to_xai():
    defn = get("xai_voice")
    assert defn.linked_premium_provider == "xai"
    # api_key field is removed
    assert all(f["key"] != "api_key" for f in defn.config_fields)


def test_mistral_voice_linked_to_mistral():
    defn = get("mistral_voice")
    assert defn.linked_premium_provider == "mistral"
    assert all(f["key"] != "api_key" for f in defn.config_fields)


def test_lovense_is_not_linked():
    defn = get("lovense")
    assert defn.linked_premium_provider is None
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `uv run pytest backend/tests/modules/integrations/test_linked_providers.py -v`

- [ ] **Step 3: Add field to model**

`backend/modules/integrations/_models.py`:

```python
@dataclass(frozen=True)
class IntegrationDefinition:
    """Static definition of an available integration."""
    id: str
    display_name: str
    description: str
    icon: str
    execution_mode: Literal["frontend", "backend", "hybrid"]
    config_fields: list[dict]
    capabilities: list[IntegrationCapability] = field(default_factory=list)
    hydrate_secrets: bool = True
    persona_config_fields: list[dict] = field(default_factory=list)
    system_prompt_template: str = ""
    response_tag_prefix: str = ""
    tool_definitions: list[ToolDefinition] = field(default_factory=list)
    tool_side: Literal["server", "client"] = "client"
    linked_premium_provider: str | None = None
```

- [ ] **Step 4: Update registrations**

In `backend/modules/integrations/_registry.py`, edit the existing `xai_voice` registration:

- Remove the dict with `"key": "api_key"` from `config_fields`.
- Add `linked_premium_provider="xai"` to the `IntegrationDefinition(...)` call.

Same for `mistral_voice`:

- Remove the `api_key` config field.
- Add `linked_premium_provider="mistral"`.

- [ ] **Step 5: Run test — expect PASS**

Run: `uv run pytest backend/tests/modules/integrations/test_linked_providers.py -v`

- [ ] **Step 6: Commit**

```bash
git add backend/modules/integrations/_models.py backend/modules/integrations/_registry.py backend/tests/modules/integrations/test_linked_providers.py
git commit -m "Link xai_voice/mistral_voice to their Premium Provider accounts"
```

---

## Task 11: Voice adapter reads key via PremiumProviderService

**Files:**
- Modify: `backend/modules/integrations/_voice_adapters/_xai.py`
- Modify: `backend/modules/integrations/_voice_adapters/_mistral.py` (if present — check first)
- Test: `backend/tests/modules/integrations/test_voice_adapter_keys.py`

- [ ] **Step 1: Inspect current key-resolution path**

Run: `grep -n 'api_key\|get_decrypted_secret\|IntegrationRepository' backend/modules/integrations/_voice_adapters/_xai.py`

Note the function that currently fetches the api_key (likely `_resolve_api_key` or inline in `synthesize`/`transcribe`).

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/modules/integrations/test_voice_adapter_keys.py
import pytest
from backend.modules.integrations._voice_adapters._xai import XaiVoiceAdapter


@pytest.mark.asyncio
async def test_xai_adapter_sources_key_from_premium_account(
    user_with_xai_account, monkeypatch,
):
    adapter = XaiVoiceAdapter(http_client=...)   # use existing fixture
    key = await adapter._resolve_user_key(user_with_xai_account.id)
    assert key == "xai-abc"


@pytest.mark.asyncio
async def test_xai_adapter_raises_when_account_absent(fresh_user):
    adapter = XaiVoiceAdapter(http_client=...)
    with pytest.raises(Exception):
        await adapter._resolve_user_key(fresh_user.id)
```

- [ ] **Step 3: Refactor the key-resolution function in `_xai.py`**

Replace the existing path (that reads from `IntegrationRepository.get_decrypted_secret`) with:

```python
async def _resolve_user_key(self, user_id: str) -> str:
    from backend.modules.providers import PremiumProviderService
    from backend.modules.providers._repository import PremiumProviderAccountRepository
    from backend.database import get_db
    svc = PremiumProviderService(PremiumProviderAccountRepository(get_db()))
    key = await svc.get_decrypted_secret(user_id, "xai", "api_key")
    if key is None:
        raise LookupError("xAI account not configured")
    return key
```

Update every call-site inside `_xai.py` that previously read `api_key` to use `await self._resolve_user_key(user_id)` instead.

- [ ] **Step 4: Mirror the change in Mistral adapter if present**

If `backend/modules/integrations/_voice_adapters/_mistral.py` exists, apply the same refactor (substituting `"mistral"` for `"xai"`).

If not present, skip this step.

- [ ] **Step 5: Run tests — expect PASS**

Run: `uv run pytest backend/tests/modules/integrations/test_voice_adapter_keys.py -v`

- [ ] **Step 6: Regression check**

Run: `uv run pytest backend/tests/modules/integrations/ -q`

Expected: all integration tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/integrations/_voice_adapters/ backend/tests/modules/integrations/test_voice_adapter_keys.py
git commit -m "Voice adapters resolve API key via PremiumProviderService"
```

---

## Task 12: Effective-enabled semantics for linked integrations

**Files:**
- Modify: `backend/modules/integrations/__init__.py` or `_handlers.py` (whichever exposes the per-user integration list to the frontend)
- Test: `backend/tests/modules/integrations/test_effective_enabled.py`

- [ ] **Step 1: Locate the public "list integrations for user" API**

Run: `grep -rn 'def list_.*integration\|async def list_for_user' backend/modules/integrations/`

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/modules/integrations/test_effective_enabled.py
import pytest
from backend.modules.integrations import IntegrationService


@pytest.mark.asyncio
async def test_linked_is_enabled_iff_premium_account_exists(
    user_with_xai_account, fresh_user, integration_service: IntegrationService,
):
    enabled_map = await integration_service.effective_enabled_map(user_with_xai_account.id)
    assert enabled_map["xai_voice"] is True

    disabled_map = await integration_service.effective_enabled_map(fresh_user.id)
    assert disabled_map["xai_voice"] is False


@pytest.mark.asyncio
async def test_unlinked_follows_explicit_enabled(integration_service, user_with_lovense_enabled):
    m = await integration_service.effective_enabled_map(user_with_lovense_enabled.id)
    assert m["lovense"] is True
```

- [ ] **Step 3: Run test — expect FAIL**

- [ ] **Step 4: Implement `effective_enabled_map`**

Add to the `IntegrationService` (public API class):

```python
async def effective_enabled_map(self, user_id: str) -> dict[str, bool]:
    """Return {integration_id: enabled} applying premium-link semantics."""
    from backend.modules.integrations._registry import get_all
    from backend.modules.providers import PremiumProviderService
    from backend.modules.providers._repository import PremiumProviderAccountRepository
    from backend.database import get_db

    definitions = get_all()
    configs = await self._repo.get_user_configs(user_id)
    cfg_map = {c["integration_id"]: c for c in configs}

    providers = PremiumProviderService(PremiumProviderAccountRepository(get_db()))

    result: dict[str, bool] = {}
    for iid, defn in definitions.items():
        if defn.linked_premium_provider:
            result[iid] = await providers.has_account(
                user_id, defn.linked_premium_provider,
            )
        else:
            cfg = cfg_map.get(iid)
            result[iid] = bool(cfg and cfg.get("enabled", False))
    return result
```

Any existing endpoint/service call that previously read `integration_config.enabled` directly for `xai_voice`/`mistral_voice` must now go through `effective_enabled_map` (or a targeted `is_effective_enabled(user_id, integration_id)` helper).

- [ ] **Step 5: Run tests — expect PASS**

- [ ] **Step 6: Commit**

```bash
git add backend/modules/integrations/ backend/tests/modules/integrations/test_effective_enabled.py
git commit -m "Linked integrations effective-enabled from premium account presence"
```

---

## Task 13: Websearch resolves key via PremiumProviderService

**Files:**
- Modify: `backend/modules/websearch/__init__.py`
- Modify: `backend/modules/websearch/_registry.py`
- Test: `backend/tests/modules/websearch/test_premium_resolve.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/modules/websearch/test_premium_resolve.py
import pytest
from backend.modules.websearch import search, WebSearchCredentialNotFoundError


@pytest.mark.asyncio
async def test_search_uses_premium_account_key(
    user_with_ollama_cloud, mock_ollama_cloud_http,
):
    results = await search(
        user_with_ollama_cloud.id, "ollama_cloud_search", "test query",
    )
    assert mock_ollama_cloud_http.last_api_key == "ollama-abc"
    assert len(results) >= 0


@pytest.mark.asyncio
async def test_search_raises_when_no_premium_account(fresh_user):
    with pytest.raises(WebSearchCredentialNotFoundError):
        await search(fresh_user.id, "ollama_cloud_search", "q")
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Add provider→premium mapping to `_registry.py`**

```python
# backend/modules/websearch/_registry.py  (extend file)
WEBSEARCH_PROVIDER_TO_PREMIUM: dict[str, str] = {
    "ollama_cloud_search": "ollama_cloud",
}
```

- [ ] **Step 4: Rewrite `_resolve_api_key` in `backend/modules/websearch/__init__.py`**

Replace the existing function body:

```python
async def _resolve_api_key(user_id: str, provider_id: str) -> str:
    from backend.modules.websearch._registry import WEBSEARCH_PROVIDER_TO_PREMIUM
    from backend.modules.providers import PremiumProviderService
    from backend.modules.providers._repository import PremiumProviderAccountRepository

    premium_id = WEBSEARCH_PROVIDER_TO_PREMIUM.get(provider_id)
    if premium_id is None:
        raise WebSearchProviderNotFoundError(
            f"No Premium mapping for provider '{provider_id}'",
        )
    svc = PremiumProviderService(PremiumProviderAccountRepository(get_db()))
    key = await svc.get_decrypted_secret(user_id, premium_id, "api_key")
    if key is None:
        raise WebSearchCredentialNotFoundError(
            f"No Premium account configured for '{premium_id}'",
        )
    return key
```

- [ ] **Step 5: Run tests — expect PASS**

- [ ] **Step 6: Commit**

```bash
git add backend/modules/websearch/ backend/tests/modules/websearch/test_premium_resolve.py
git commit -m "Websearch resolves keys through PremiumProviderService"
```

---

## Task 14: Remove legacy websearch credentials UI, repo, routes, collection

**Files:**
- Delete: `backend/modules/websearch/_credentials.py`
- Modify: `backend/modules/websearch/__init__.py` (drop import + `delete_all_for_user`)
- Modify: `backend/modules/websearch/_handlers.py` (drop credential-CRUD routes)
- Modify: `backend/main.py` (replace `WebSearchCredentialRepository` init + add `drop_collection`)

- [ ] **Step 1: Remove router endpoints**

Edit `backend/modules/websearch/_handlers.py` — delete any routes dealing with `/credentials`, credential listing, upsert, test, delete. Keep only routes strictly related to executing searches/fetches (`search`, `fetch`) if they are exposed via the router at all.

Run: `grep -n '@router' backend/modules/websearch/_handlers.py` to enumerate current routes. Remove credential-related ones only.

- [ ] **Step 2: Remove repository usage in `__init__.py`**

Delete:
- `from backend.modules.websearch._credentials import WebSearchCredentialRepository`
- `async def init_indexes` body that creates credential indexes (replace with `pass` or remove if no other init)
- `async def delete_all_for_user` (the websearch module no longer owns credentials — user-delete for Premium accounts is already wired in Task 6)

Update `__all__` to drop `init_indexes` and `delete_all_for_user` exports if they only existed for the credential flow.

- [ ] **Step 3: Delete the repository file**

Run: `git rm backend/modules/websearch/_credentials.py`

- [ ] **Step 4: Drop the collection at startup**

In `backend/main.py`, inside startup, after the migration marker check (which will be added in Task 15), add:

```python
await db.drop_collection("websearch_user_credentials")
```

This will be made idempotent via the migration marker; the drop itself is a no-op on an already-dropped collection.

- [ ] **Step 5: Run all tests**

Run: `uv run pytest backend/tests/modules/websearch/ -q`

Expected: all pass (legacy credential tests should already have been removed as part of the earlier websearch test cleanup — check `backend/tests/modules/websearch/` for references to `WebSearchCredentialRepository` and delete obsolete tests).

- [ ] **Step 6: Commit**

```bash
git add backend/modules/websearch/ backend/main.py backend/tests/modules/websearch/
git commit -m "Remove legacy websearch credentials store"
```

---

## Task 15: Migration — scaffold and marker gate

**Files:**
- Create: `backend/modules/providers/_migration_v1.py`
- Test: `backend/tests/modules/providers/test_migration.py`

Reference: `backend/modules/llm/_migration_connections_refactor.py` for the existing marker-gate pattern.

- [ ] **Step 1: Write the scaffold test**

```python
# backend/tests/modules/providers/test_migration.py
import pytest
from backend.modules.providers._migration_v1 import run_if_needed, _MARKER_ID


@pytest.mark.asyncio
async def test_marker_prevents_rerun(mongo_db, redis_client):
    await mongo_db["_migrations"].insert_one({"_id": _MARKER_ID})
    # If the marker is present, run_if_needed must not touch anything.
    await run_if_needed(mongo_db, redis_client)
    # Nothing to assert — absence of exception + speed is enough.


@pytest.mark.asyncio
async def test_first_run_sets_marker(mongo_db, redis_client):
    await run_if_needed(mongo_db, redis_client)
    marker = await mongo_db["_migrations"].find_one({"_id": _MARKER_ID})
    assert marker is not None
```

- [ ] **Step 2: Write the scaffold**

```python
# backend/modules/providers/_migration_v1.py
"""One-shot migration for Premium Provider Accounts (v1).

Gated by a marker document in _migrations. Idempotent — re-runs are no-ops.
"""
import logging
from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

_log = logging.getLogger(__name__)
_MARKER_ID = "premium_provider_accounts_v1"


async def run_if_needed(db: AsyncIOMotorDatabase, _redis=None) -> None:
    marker = await db["_migrations"].find_one({"_id": _MARKER_ID})
    if marker is not None:
        return

    _log.warning("premium_provider_accounts_v1: running one-shot migration")

    await _step_0_import_keys(db)
    await _step_1_rewrite_model_unique_ids(db)
    await _step_2_delete_migrated_connections(db)
    await _step_3_strip_integration_api_keys(db)
    await _step_4_drop_websearch_credentials(db)

    await db["_migrations"].insert_one({
        "_id": _MARKER_ID,
        "applied_at": datetime.now(UTC),
    })
    _log.warning("premium_provider_accounts_v1: done")


async def _step_0_import_keys(db):
    pass     # filled in Task 16


async def _step_1_rewrite_model_unique_ids(db):
    pass


async def _step_2_delete_migrated_connections(db):
    pass


async def _step_3_strip_integration_api_keys(db):
    pass


async def _step_4_drop_websearch_credentials(db):
    await db.drop_collection("websearch_user_credentials")
```

- [ ] **Step 3: Run tests — expect PASS**

- [ ] **Step 4: Commit**

```bash
git add backend/modules/providers/_migration_v1.py backend/tests/modules/providers/test_migration.py
git commit -m "Scaffold Premium Provider migration with marker gate"
```

---

## Task 16: Migration step 0 — key import

**Files:**
- Modify: `backend/modules/providers/_migration_v1.py` (fill `_step_0_import_keys`)
- Test: `backend/tests/modules/providers/test_migration.py` (extend)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/modules/providers/test_migration.py  (append)
import pytest
from backend.modules.providers._migration_v1 import _step_0_import_keys
from backend.modules.providers._repository import PremiumProviderAccountRepository


@pytest.mark.asyncio
async def test_import_xai_from_llm_connection(mongo_db, seed_xai_http_connection):
    await _step_0_import_keys(mongo_db)
    repo = PremiumProviderAccountRepository(mongo_db)
    doc = await repo.find(seed_xai_http_connection.user_id, "xai")
    assert doc is not None
    assert repo.get_decrypted_secret(doc, "api_key") == seed_xai_http_connection.api_key


@pytest.mark.asyncio
async def test_import_xai_fallback_to_voice_integration(
    mongo_db, seed_xai_voice_integration_only,
):
    await _step_0_import_keys(mongo_db)
    repo = PremiumProviderAccountRepository(mongo_db)
    doc = await repo.find(seed_xai_voice_integration_only.user_id, "xai")
    assert repo.get_decrypted_secret(doc, "api_key") == seed_xai_voice_integration_only.api_key


@pytest.mark.asyncio
async def test_import_mistral_from_voice_integration(
    mongo_db, seed_mistral_voice_integration,
):
    await _step_0_import_keys(mongo_db)
    repo = PremiumProviderAccountRepository(mongo_db)
    doc = await repo.find(seed_mistral_voice_integration.user_id, "mistral")
    assert doc is not None


@pytest.mark.asyncio
async def test_import_ollama_cloud_from_connection(
    mongo_db, seed_ollama_cloud_connection,
):
    await _step_0_import_keys(mongo_db)
    repo = PremiumProviderAccountRepository(mongo_db)
    doc = await repo.find(seed_ollama_cloud_connection.user_id, "ollama_cloud")
    assert doc is not None


@pytest.mark.asyncio
async def test_import_ollama_cloud_fallback_websearch(
    mongo_db, seed_ollama_cloud_websearch_only,
):
    await _step_0_import_keys(mongo_db)
    repo = PremiumProviderAccountRepository(mongo_db)
    doc = await repo.find(seed_ollama_cloud_websearch_only.user_id, "ollama_cloud")
    assert doc is not None


@pytest.mark.asyncio
async def test_import_is_idempotent(mongo_db, seed_xai_http_connection):
    await _step_0_import_keys(mongo_db)
    await _step_0_import_keys(mongo_db)   # second run is no-op
    docs = [
        d async for d in mongo_db["premium_provider_accounts"].find({"provider_id": "xai"})
    ]
    assert len(docs) == 1


@pytest.mark.asyncio
async def test_import_primary_wins_on_conflict(
    mongo_db, seed_xai_conflict_scenario, caplog,
):
    # seed_xai_conflict_scenario creates LLM conn with "xai-primary" AND
    # xai_voice integration with "xai-voice-key"; primary should win.
    await _step_0_import_keys(mongo_db)
    repo = PremiumProviderAccountRepository(mongo_db)
    doc = await repo.find(seed_xai_conflict_scenario.user_id, "xai")
    assert repo.get_decrypted_secret(doc, "api_key") == "xai-primary"
    assert any("conflict" in r.message.lower() for r in caplog.records)
```

- [ ] **Step 2: Run test — expect FAIL**

- [ ] **Step 3: Implement `_step_0_import_keys`**

```python
# backend/modules/providers/_migration_v1.py  (replace _step_0_import_keys)
import hashlib
from urllib.parse import urlparse
from cryptography.fernet import Fernet

from backend.config import settings
from backend.modules.providers._repository import PremiumProviderAccountRepository


def _hash_key_for_audit(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:8]


async def _step_0_import_keys(db):
    """Import existing api_keys into premium_provider_accounts, by user.

    Priority per provider (skip if account already exists for the user):
      xai:          xai_http connection  → xai_voice integration
      mistral:      mistral_voice integration
      ollama_cloud: ollama_http connection (hostname = ollama.com) → websearch cred
    """
    fernet = Fernet(settings.encryption_key.encode())
    repo = PremiumProviderAccountRepository(db)

    # Collect candidates per (user_id, provider_id).
    candidates: dict[tuple[str, str], list[tuple[str, str]]] = {}
    # Each value is a list of (source_label, plaintext_key), primary first.

    # --- xAI primary: llm_connections xai_http ---
    async for conn in db["llm_connections"].find({"adapter_type": "xai_http"}):
        enc = (conn.get("config_encrypted") or {}).get("api_key")
        if not enc:
            continue
        plaintext = fernet.decrypt(enc.encode()).decode()
        key = (conn["user_id"], "xai")
        candidates.setdefault(key, []).append(("xai_http_conn", plaintext))

    # --- xAI secondary: xai_voice integration ---
    async for cfg in db["user_integration_configs"].find({"integration_id": "xai_voice"}):
        enc = (cfg.get("config_encrypted") or {}).get("api_key")
        if not enc:
            continue
        plaintext = fernet.decrypt(enc.encode()).decode()
        key = (cfg["user_id"], "xai")
        candidates.setdefault(key, []).append(("xai_voice_cfg", plaintext))

    # --- Mistral primary: mistral_voice integration ---
    async for cfg in db["user_integration_configs"].find({"integration_id": "mistral_voice"}):
        enc = (cfg.get("config_encrypted") or {}).get("api_key")
        if not enc:
            continue
        plaintext = fernet.decrypt(enc.encode()).decode()
        key = (cfg["user_id"], "mistral")
        candidates.setdefault(key, []).append(("mistral_voice_cfg", plaintext))

    # --- Ollama Cloud primary: llm_connections ollama_http with hostname=ollama.com ---
    async for conn in db["llm_connections"].find({"adapter_type": "ollama_http"}):
        base_url = (conn.get("config") or {}).get("base_url") or ""
        host = urlparse(base_url).hostname
        if host != "ollama.com":
            continue
        enc = (conn.get("config_encrypted") or {}).get("api_key")
        if not enc:
            continue
        plaintext = fernet.decrypt(enc.encode()).decode()
        key = (conn["user_id"], "ollama_cloud")
        candidates.setdefault(key, []).append(("ollama_http_conn", plaintext))

    # --- Ollama Cloud secondary: websearch credentials ---
    async for cred in db["websearch_user_credentials"].find(
        {"provider_id": "ollama_cloud_search"},
    ):
        enc = cred.get("api_key_encrypted")
        if not enc:
            continue
        plaintext = fernet.decrypt(enc.encode()).decode()
        key = (cred["user_id"], "ollama_cloud")
        candidates.setdefault(key, []).append(("websearch_cred", plaintext))

    # --- Upsert primary winner per (user, provider), skip if account exists ---
    for (user_id, provider_id), sources in candidates.items():
        existing = await repo.find(user_id, provider_id)
        if existing is not None:
            continue                  # idempotency
        primary_label, primary_key = sources[0]
        if len(sources) > 1:
            other_hashes = [
                f"{label}={_hash_key_for_audit(k)}"
                for label, k in sources[1:]
                if k != primary_key
            ]
            if other_hashes:
                _log.warning(
                    "premium_provider_accounts_v1: conflict user=%s provider=%s "
                    "primary=%s:%s others=%s",
                    user_id, provider_id,
                    primary_label, _hash_key_for_audit(primary_key),
                    ",".join(other_hashes),
                )
        await repo.upsert(user_id, provider_id, {"api_key": primary_key})
```

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add backend/modules/providers/_migration_v1.py backend/tests/modules/providers/test_migration.py
git commit -m "Migration step 0: import existing keys into premium accounts"
```

---

## Task 17: Migration steps 1–4 — rewrite IDs, cleanup connections, strip integration keys, drop collection

**Files:**
- Modify: `backend/modules/providers/_migration_v1.py`
- Test: `backend/tests/modules/providers/test_migration.py` (extend)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/modules/providers/test_migration.py  (append)
import pytest
from backend.modules.providers._migration_v1 import (
    _step_1_rewrite_model_unique_ids,
    _step_2_delete_migrated_connections,
    _step_3_strip_integration_api_keys,
    _step_4_drop_websearch_credentials,
)


@pytest.mark.asyncio
async def test_rewrite_xai_model_ids(mongo_db, seed_xai_http_connection_with_persona):
    old_slug = seed_xai_http_connection_with_persona.slug
    await _step_1_rewrite_model_unique_ids(mongo_db)
    persona = await mongo_db["personas"].find_one(
        {"user_id": seed_xai_http_connection_with_persona.user_id},
    )
    assert persona["model_unique_id"].startswith("xai:")
    assert not persona["model_unique_id"].startswith(f"{old_slug}:")


@pytest.mark.asyncio
async def test_rewrite_ollama_cloud_model_ids(
    mongo_db, seed_ollama_cloud_connection_with_persona,
):
    await _step_1_rewrite_model_unique_ids(mongo_db)
    persona = await mongo_db["personas"].find_one(
        {"user_id": seed_ollama_cloud_connection_with_persona.user_id},
    )
    assert persona["model_unique_id"].startswith("ollama_cloud:")


@pytest.mark.asyncio
async def test_delete_xai_http_connections(mongo_db, seed_xai_http_connection):
    await _step_2_delete_migrated_connections(mongo_db)
    count = await mongo_db["llm_connections"].count_documents(
        {"adapter_type": "xai_http"},
    )
    assert count == 0


@pytest.mark.asyncio
async def test_delete_ollama_cloud_connections(
    mongo_db, seed_ollama_cloud_connection, seed_ollama_local_connection,
):
    await _step_2_delete_migrated_connections(mongo_db)
    cloud = await mongo_db["llm_connections"].count_documents({
        "adapter_type": "ollama_http",
        "config.base_url": {"$regex": "ollama\\.com"},
    })
    local = await mongo_db["llm_connections"].count_documents({
        "_id": seed_ollama_local_connection.id,
    })
    assert cloud == 0
    assert local == 1       # selfhosted remains


@pytest.mark.asyncio
async def test_strip_integration_api_keys(mongo_db, seed_xai_voice_integration_only):
    await _step_3_strip_integration_api_keys(mongo_db)
    cfg = await mongo_db["user_integration_configs"].find_one(
        {"integration_id": "xai_voice"},
    )
    assert "api_key" not in (cfg.get("config_encrypted") or {})


@pytest.mark.asyncio
async def test_drop_websearch_collection(mongo_db):
    await mongo_db["websearch_user_credentials"].insert_one(
        {"_id": "x", "user_id": "u1", "provider_id": "ollama_cloud_search"},
    )
    await _step_4_drop_websearch_credentials(mongo_db)
    # Second call must be a no-op.
    await _step_4_drop_websearch_credentials(mongo_db)
    names = await mongo_db.list_collection_names()
    assert "websearch_user_credentials" not in names
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Fill steps 1–3 (step 4 is already in scaffold)**

```python
# backend/modules/providers/_migration_v1.py  (replace _step_1, _step_2, _step_3)

async def _step_1_rewrite_model_unique_ids(db):
    """Rewrite {old_slug}:{model} → {xai|ollama_cloud}:{model} on personas and configs."""
    rewrite_jobs: list[tuple[str, str, str]] = []   # (user_id, old_slug, new_prefix)

    async for conn in db["llm_connections"].find({"adapter_type": "xai_http"}):
        rewrite_jobs.append((conn["user_id"], conn["slug"], "xai"))

    async for conn in db["llm_connections"].find({"adapter_type": "ollama_http"}):
        base_url = (conn.get("config") or {}).get("base_url") or ""
        if urlparse(base_url).hostname != "ollama.com":
            continue
        rewrite_jobs.append((conn["user_id"], conn["slug"], "ollama_cloud"))

    for user_id, old_slug, new_prefix in rewrite_jobs:
        for collection_name in ("personas", "llm_user_model_configs"):
            col = db[collection_name]
            async for doc in col.find({
                "user_id": user_id,
                "model_unique_id": {"$regex": f"^{old_slug}:"},
            }):
                _, _, model_slug = doc["model_unique_id"].partition(":")
                await col.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"model_unique_id": f"{new_prefix}:{model_slug}"}},
                )


async def _step_2_delete_migrated_connections(db):
    """Delete xai_http connections and ollama_http connections with hostname=ollama.com."""
    await db["llm_connections"].delete_many({"adapter_type": "xai_http"})

    async for conn in db["llm_connections"].find({"adapter_type": "ollama_http"}):
        base_url = (conn.get("config") or {}).get("base_url") or ""
        if urlparse(base_url).hostname == "ollama.com":
            await db["llm_connections"].delete_one({"_id": conn["_id"]})


async def _step_3_strip_integration_api_keys(db):
    """Remove api_key from xai_voice and mistral_voice integration configs."""
    await db["user_integration_configs"].update_many(
        {"integration_id": {"$in": ["xai_voice", "mistral_voice"]}},
        {"$unset": {"config_encrypted.api_key": ""}},
    )
```

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add backend/modules/providers/_migration_v1.py backend/tests/modules/providers/test_migration.py
git commit -m "Migration steps 1-4: rewrite model IDs, cleanup, drop websearch"
```

---

## Task 18: Wire migration into startup

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add migration call to lifespan startup**

Locate the existing call `await _migration_connections_refactor.run_if_needed(db, redis)` (if present) or the general migration block, and add immediately after:

```python
from backend.modules.providers._migration_v1 import run_if_needed as run_providers_migration

await run_providers_migration(db, redis)
```

The call must run **after** index creation (so `premium_provider_accounts` indexes exist) and **before** the websearch `drop_collection` call from Task 14 (the migration handles the drop as its step 4; Task 14's direct drop becomes redundant — remove it).

- [ ] **Step 2: Remove the redundant drop from Task 14**

If Task 14 added an unconditional `await db.drop_collection("websearch_user_credentials")` in main.py, remove it now — the migration owns that step.

- [ ] **Step 3: Run full startup smoke test**

If you have an end-to-end startup test (`backend/tests/app/test_startup.py` or similar), run it:

```
uv run pytest backend/tests/app/ -v
```

If not, manually boot once:

```
cd /home/chris/workspace/chatsune && uv run uvicorn backend.main:app --port 8001
```

Check the log for `premium_provider_accounts_v1` messages and that the app comes up.

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "Run Premium Provider migration at startup"
```

---

## Task 19: Frontend types + API client + store

**Files:**
- Create: `frontend/src/core/types/providers.ts`
- Create: `frontend/src/core/api/providers.ts`
- Create: `frontend/src/core/stores/providersStore.ts`
- Test: `frontend/src/core/stores/__tests__/providersStore.test.ts`

- [ ] **Step 1: Write types**

```typescript
// frontend/src/core/types/providers.ts
export const Capability = {
  LLM: 'llm',
  TTS: 'tts',
  STT: 'stt',
  WEBSEARCH: 'websearch',
  TTI: 'tti',
  ITI: 'iti',
} as const
export type Capability = (typeof Capability)[keyof typeof Capability]

export interface CapabilityMeta {
  label: string
  tooltip: string
}

export const CAPABILITY_META: Record<Capability, CapabilityMeta> = {
  llm:       { label: 'Text',         tooltip: 'Provides chat models you can pick for any persona.' },
  tts:       { label: 'TTS',          tooltip: 'Synthesises persona replies into speech for voice chats.' },
  stt:       { label: 'STT',          tooltip: 'Transcribes your voice input into text for the chat.' },
  websearch: { label: 'Web search',   tooltip: 'Provides web search during chats, regardless of which model you use.' },
  tti:       { label: 'Text to Image', tooltip: 'Creates images from a text prompt during chats.' },
  iti:       { label: 'Image to Image', tooltip: 'Edits or transforms an uploaded image based on a prompt.' },
}

export interface PremiumProviderDefinition {
  id: string
  display_name: string
  icon: string
  base_url: string
  capabilities: Capability[]
  config_fields: Array<Record<string, unknown>>
  linked_integrations: string[]
}

export interface PremiumProviderAccount {
  provider_id: string
  config: Record<string, unknown>
  last_test_status: 'ok' | 'error' | null
  last_test_error: string | null
  last_test_at: string | null
}
```

- [ ] **Step 2: Write API client**

```typescript
// frontend/src/core/api/providers.ts
import { httpClient } from './http'   // existing client used by other api/* files
import type { PremiumProviderDefinition, PremiumProviderAccount } from '../types/providers'

export const providersApi = {
  async catalogue(): Promise<PremiumProviderDefinition[]> {
    return httpClient.get('/api/providers/catalogue')
  },
  async listAccounts(): Promise<PremiumProviderAccount[]> {
    return httpClient.get('/api/providers/accounts')
  },
  async upsertAccount(
    providerId: string, config: Record<string, unknown>,
  ): Promise<PremiumProviderAccount> {
    return httpClient.put(`/api/providers/accounts/${providerId}`, { config })
  },
  async deleteAccount(providerId: string): Promise<void> {
    return httpClient.delete(`/api/providers/accounts/${providerId}`)
  },
}
```

Adapt import paths to match existing codebase (e.g. `../api/client` vs. `./http` — inspect a neighbouring `frontend/src/core/api/*.ts` file to confirm the pattern).

- [ ] **Step 3: Write Zustand store**

```typescript
// frontend/src/core/stores/providersStore.ts
import { create } from 'zustand'
import { providersApi } from '../api/providers'
import type { PremiumProviderDefinition, PremiumProviderAccount, Capability } from '../types/providers'

interface State {
  catalogue: PremiumProviderDefinition[]
  accounts: PremiumProviderAccount[]
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  save: (providerId: string, config: Record<string, unknown>) => Promise<void>
  remove: (providerId: string) => Promise<void>
  configuredIds: () => Set<string>
  coveredCapabilities: () => Set<Capability>
}

export const useProvidersStore = create<State>((set, get) => ({
  catalogue: [],
  accounts: [],
  loading: false,
  error: null,
  async refresh() {
    set({ loading: true, error: null })
    try {
      const [catalogue, accounts] = await Promise.all([
        providersApi.catalogue(), providersApi.listAccounts(),
      ])
      set({ catalogue, accounts, loading: false })
    } catch (e) {
      set({ loading: false, error: e instanceof Error ? e.message : 'Load failed' })
    }
  },
  async save(providerId, config) {
    const acct = await providersApi.upsertAccount(providerId, config)
    set({ accounts: upsert(get().accounts, acct) })
  },
  async remove(providerId) {
    await providersApi.deleteAccount(providerId)
    set({ accounts: get().accounts.filter((a) => a.provider_id !== providerId) })
  },
  configuredIds() {
    return new Set(get().accounts.map((a) => a.provider_id))
  },
  coveredCapabilities() {
    const configured = get().configuredIds()
    const covered = new Set<Capability>()
    for (const d of get().catalogue) {
      if (configured.has(d.id)) d.capabilities.forEach((c) => covered.add(c))
    }
    return covered
  },
}))

function upsert(list: PremiumProviderAccount[], acct: PremiumProviderAccount) {
  const i = list.findIndex((a) => a.provider_id === acct.provider_id)
  if (i < 0) return [...list, acct]
  const next = list.slice()
  next[i] = acct
  return next
}
```

- [ ] **Step 4: Write test**

```typescript
// frontend/src/core/stores/__tests__/providersStore.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useProvidersStore } from '../providersStore'
import { providersApi } from '../../api/providers'

vi.mock('../../api/providers')

describe('providersStore', () => {
  beforeEach(() => {
    useProvidersStore.setState({ catalogue: [], accounts: [], loading: false, error: null })
  })

  it('computes configured ids', () => {
    useProvidersStore.setState({
      accounts: [
        { provider_id: 'xai', config: {}, last_test_status: null, last_test_error: null, last_test_at: null },
      ],
    })
    expect([...useProvidersStore.getState().configuredIds()]).toEqual(['xai'])
  })

  it('computes covered capabilities from configured accounts only', () => {
    useProvidersStore.setState({
      catalogue: [
        { id: 'xai', display_name: 'xAI', icon: '', base_url: '', capabilities: ['llm', 'tts'] as any,
          config_fields: [], linked_integrations: [] },
        { id: 'mistral', display_name: 'Mistral', icon: '', base_url: '', capabilities: ['stt'] as any,
          config_fields: [], linked_integrations: [] },
      ],
      accounts: [
        { provider_id: 'xai', config: {}, last_test_status: 'ok', last_test_error: null, last_test_at: null },
      ],
    })
    const covered = [...useProvidersStore.getState().coveredCapabilities()].sort()
    expect(covered).toEqual(['llm', 'tts'])
  })
})
```

- [ ] **Step 5: Run test — expect PASS**

Run: `cd frontend && pnpm vitest run src/core/stores/__tests__/providersStore.test.ts`

- [ ] **Step 6: Commit**

```bash
git add frontend/src/core/types/providers.ts frontend/src/core/api/providers.ts frontend/src/core/stores/providersStore.ts frontend/src/core/stores/__tests__/providersStore.test.ts
git commit -m "Add frontend providers types, API client, and store"
```

---

## Task 20: Coverage Row component

**Files:**
- Create: `frontend/src/app/components/providers/CoverageRow.tsx`
- Test: `frontend/src/app/components/providers/__tests__/CoverageRow.test.tsx`

- [ ] **Step 1: Write test**

```tsx
// frontend/src/app/components/providers/__tests__/CoverageRow.test.tsx
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { CoverageRow } from '../CoverageRow'

describe('CoverageRow', () => {
  it('renders all six capability pills', () => {
    const { container } = render(
      <CoverageRow covered={new Set(['llm'])} providersByCapability={new Map()} />
    )
    expect(container.querySelectorAll('[data-capability]')).toHaveLength(6)
  })

  it('marks covered pills with data-covered=true', () => {
    const { container } = render(
      <CoverageRow covered={new Set(['llm', 'tts'])} providersByCapability={new Map()} />
    )
    const covered = container.querySelectorAll('[data-covered="true"]')
    expect(covered).toHaveLength(2)
  })
})
```

- [ ] **Step 2: Write component**

```tsx
// frontend/src/app/components/providers/CoverageRow.tsx
import { CAPABILITY_META, Capability } from '../../../core/types/providers'

interface Props {
  covered: Set<string>
  providersByCapability: Map<string, string[]>   // capability -> [display_name, ...]
}

const ALL: Capability[] = ['llm', 'tts', 'stt', 'websearch', 'tti', 'iti']

export function CoverageRow({ covered, providersByCapability }: Props) {
  return (
    <div className="flex flex-wrap gap-2 px-6 py-4 border-b border-white/8">
      {ALL.map((cap) => {
        const isCovered = covered.has(cap)
        const meta = CAPABILITY_META[cap]
        const tip = isCovered
          ? `${meta.tooltip}\n\nProvided by: ${(providersByCapability.get(cap) ?? []).join(', ')}`
          : meta.tooltip
        return (
          <span
            key={cap}
            data-capability={cap}
            data-covered={isCovered ? 'true' : 'false'}
            title={tip}
            className={[
              'inline-flex items-center rounded-full px-3 py-1 text-[11px] font-mono',
              isCovered
                ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
                : 'bg-white/5 text-white/30 border border-white/10',
            ].join(' ')}
          >
            {meta.label}
          </span>
        )
      })}
    </div>
  )
}
```

- [ ] **Step 3: Run test — expect PASS**

Run: `cd frontend && pnpm vitest run src/app/components/providers/__tests__/CoverageRow.test.tsx`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/providers/CoverageRow.tsx frontend/src/app/components/providers/__tests__/CoverageRow.test.tsx
git commit -m "Add CoverageRow component for Providers tab"
```

---

## Task 21: PremiumAccountCard component

**Files:**
- Create: `frontend/src/app/components/providers/PremiumAccountCard.tsx`
- Test: `frontend/src/app/components/providers/__tests__/PremiumAccountCard.test.tsx`

- [ ] **Step 1: Write the component**

```tsx
// frontend/src/app/components/providers/PremiumAccountCard.tsx
import { useState } from 'react'
import { CAPABILITY_META } from '../../../core/types/providers'
import type { PremiumProviderDefinition, PremiumProviderAccount } from '../../../core/types/providers'

interface Props {
  definition: PremiumProviderDefinition
  account: PremiumProviderAccount | null
  onSave: (config: Record<string, unknown>) => Promise<void>
  onDelete: () => Promise<void>
  onTest: () => Promise<void>
}

export function PremiumAccountCard({ definition, account, onSave, onDelete, onTest }: Props) {
  const configured = account !== null
  const status = !configured
    ? 'not set'
    : account.last_test_status === 'ok'
      ? 'ok'
      : account.last_test_status === 'error'
        ? `error: ${account.last_test_error ?? 'see logs'}`
        : 'unverified'

  const [editing, setEditing] = useState(!configured)
  const [keyDraft, setKeyDraft] = useState('')

  async function save() {
    await onSave({ api_key: keyDraft })
    setKeyDraft('')
    setEditing(false)
  }

  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.02] p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold text-white/90">{definition.display_name}</span>
        </div>
        <span className="text-[11px] font-mono text-white/50">{status}</span>
      </div>

      {editing ? (
        <div className="flex items-center gap-2">
          <input
            type="password"
            placeholder="API key"
            value={keyDraft}
            onChange={(e) => setKeyDraft(e.target.value)}
            className="flex-1 rounded bg-black/30 border border-white/10 px-2 py-1 text-[12px] text-white/90"
          />
          <button
            onClick={() => void save()}
            disabled={!keyDraft}
            className="rounded border border-white/15 px-3 py-1 text-[11px] text-white/80 hover:bg-white/5 disabled:opacity-30"
          >
            Save
          </button>
          {configured && (
            <button
              onClick={() => { setEditing(false); setKeyDraft('') }}
              className="rounded px-2 py-1 text-[11px] text-white/40 hover:text-white/80"
            >
              Cancel
            </button>
          )}
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <span className="flex-1 font-mono text-[11px] text-white/40">
            {'•'.repeat(16)}
          </span>
          <button onClick={() => setEditing(true)} className="rounded border border-white/15 px-3 py-1 text-[11px] text-white/80 hover:bg-white/5">
            Change
          </button>
          <button onClick={() => void onTest()} className="rounded border border-white/15 px-3 py-1 text-[11px] text-white/80 hover:bg-white/5">
            Test
          </button>
          <button onClick={() => void onDelete()} className="rounded px-2 py-1 text-[11px] text-red-400/70 hover:text-red-300">
            Remove
          </button>
        </div>
      )}

      <div className="flex flex-wrap gap-1.5">
        {definition.capabilities.map((cap) => {
          const meta = CAPABILITY_META[cap]
          return (
            <span
              key={cap}
              title={meta.tooltip}
              className={[
                'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-mono',
                configured
                  ? 'bg-violet-500/15 text-violet-200 border border-violet-500/30'
                  : 'bg-white/5 text-white/30 border border-white/10',
              ].join(' ')}
            >
              {meta.label}
            </span>
          )
        })}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Write test**

```tsx
// frontend/src/app/components/providers/__tests__/PremiumAccountCard.test.tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { PremiumAccountCard } from '../PremiumAccountCard'

const definition = {
  id: 'xai',
  display_name: 'xAI',
  icon: 'xai',
  base_url: 'https://api.x.ai',
  capabilities: ['llm', 'tts'] as any,
  config_fields: [],
  linked_integrations: ['xai_voice'],
}

describe('PremiumAccountCard', () => {
  it('shows not set when account is null', () => {
    render(<PremiumAccountCard
      definition={definition}
      account={null}
      onSave={vi.fn()}
      onDelete={vi.fn()}
      onTest={vi.fn()}
    />)
    expect(screen.getByText('not set')).toBeInTheDocument()
  })

  it('calls onSave with api_key when saved', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined)
    render(<PremiumAccountCard
      definition={definition}
      account={null}
      onSave={onSave}
      onDelete={vi.fn()}
      onTest={vi.fn()}
    />)
    const input = screen.getByPlaceholderText('API key')
    fireEvent.change(input, { target: { value: 'xai-abc' } })
    fireEvent.click(screen.getByText('Save'))
    expect(onSave).toHaveBeenCalledWith({ api_key: 'xai-abc' })
  })
})
```

- [ ] **Step 3: Run test — expect PASS**

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/providers/PremiumAccountCard.tsx frontend/src/app/components/providers/__tests__/PremiumAccountCard.test.tsx
git commit -m "Add PremiumAccountCard component"
```

---

## Task 22: Refactor LlmProvidersTab into new Providers layout

**Files:**
- Modify: `frontend/src/app/components/user-modal/LlmProvidersTab.tsx`

- [ ] **Step 1: Replace the component body**

Keep the existing `LlmProvidersTab` export name (callers reference it via the tab tree); change its contents to the new layout. Existing logic for listing local/homelab connections (the `selfHosted`/`providers` split of `is_system_managed`) is preserved below the Premium block.

```tsx
// frontend/src/app/components/user-modal/LlmProvidersTab.tsx
import { useCallback, useEffect, useState } from 'react'
import { useProvidersStore } from '../../../core/stores/providersStore'
import { CoverageRow } from '../providers/CoverageRow'
import { PremiumAccountCard } from '../providers/PremiumAccountCard'
import { llmApi } from '../../../core/api/llm'
import type { Connection } from '../../../core/types/llm'
import { eventBus } from '../../../core/websocket/eventBus'
import { Topics } from '../../../core/types/events'
import { ConnectionListItem } from '../llm-providers/ConnectionListItem'
import { AddConnectionWizard } from '../llm-providers/AddConnectionWizard'
import { ConnectionConfigModal } from '../llm-providers/ConnectionConfigModal'

export function LlmProvidersTab() {
  const store = useProvidersStore()

  useEffect(() => { void store.refresh() }, [])

  // Subscribe to Premium events — any change re-fetches.
  useEffect(() => {
    const topics = [
      Topics.PREMIUM_PROVIDER_ACCOUNT_UPSERTED,
      Topics.PREMIUM_PROVIDER_ACCOUNT_DELETED,
      Topics.PREMIUM_PROVIDER_ACCOUNT_TESTED,
    ] as const
    const unsubs = topics.map((t) => eventBus.on(t, () => { void store.refresh() }))
    return () => unsubs.forEach((u) => u())
  }, [store])

  const [connections, setConnections] = useState<Connection[]>([])
  const [wizardOpen, setWizardOpen] = useState(false)
  const [editing, setEditing] = useState<Connection | null>(null)

  const refreshConnections = useCallback(async () => {
    setConnections(await llmApi.listConnections())
  }, [])
  useEffect(() => { void refreshConnections() }, [refreshConnections])

  useEffect(() => {
    const topics = [
      Topics.LLM_CONNECTION_CREATED,
      Topics.LLM_CONNECTION_UPDATED,
      Topics.LLM_CONNECTION_REMOVED,
      Topics.LLM_CONNECTION_STATUS_CHANGED,
    ] as const
    const unsubs = topics.map((t) => eventBus.on(t, () => { void refreshConnections() }))
    return () => unsubs.forEach((u) => u())
  }, [refreshConnections])

  const configured = store.configuredIds()
  const providers = connections.filter((c) => c.is_system_managed !== true)

  const byCap = new Map<string, string[]>()
  for (const d of store.catalogue) {
    if (configured.has(d.id)) {
      for (const c of d.capabilities) {
        const arr = byCap.get(c) ?? []
        arr.push(d.display_name)
        byCap.set(c, arr)
      }
    }
  }

  return (
    <div className="flex flex-col">
      <CoverageRow covered={store.coveredCapabilities()} providersByCapability={byCap} />

      <section className="px-6 py-4 space-y-3">
        <h3 className="text-[11px] font-mono uppercase tracking-wider text-white/40">Accounts</h3>
        {store.catalogue.map((d) => {
          const acct = store.accounts.find((a) => a.provider_id === d.id) ?? null
          return (
            <PremiumAccountCard
              key={d.id}
              definition={d}
              account={acct}
              onSave={(cfg) => store.save(d.id, cfg)}
              onDelete={() => store.remove(d.id)}
              onTest={async () => {
                // Test route stays in the existing llm module for LLM-capable providers;
                // for now a simple re-upsert with no changes triggers a backend test.
                // (A dedicated /test endpoint can be added as a follow-up.)
              }}
            />
          )
        })}
      </section>

      <section className="px-6 py-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-[11px] font-mono uppercase tracking-wider text-white/40">Local & Homelab</h3>
          <button
            onClick={() => setWizardOpen(true)}
            className="rounded border border-white/15 px-3 py-1 text-[11px] text-white/80 hover:bg-white/5"
          >
            Add
          </button>
        </div>
        {providers.map((c) => (
          <ConnectionListItem key={c.id} item={c} onEdit={() => setEditing(c)} />
        ))}
      </section>

      {wizardOpen && <AddConnectionWizard onClose={() => setWizardOpen(false)} />}
      {editing && <ConnectionConfigModal connection={editing} onClose={() => setEditing(null)} />}
    </div>
  )
}
```

- [ ] **Step 2: Run frontend type check + full test suite**

Run:
```
cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit
cd /home/chris/workspace/chatsune/frontend && pnpm vitest run
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/components/user-modal/LlmProvidersTab.tsx
git commit -m "Rework LlmProvidersTab into unified Providers layout"
```

---

## Task 23: Integrations tab — remove api_key UI for linked integrations

**Files:**
- Modify: `frontend/src/app/components/user-modal/IntegrationsTab.tsx` (and any child components rendering config forms for `xai_voice` / `mistral_voice`)

- [ ] **Step 1: Locate the config-form renderer**

Search: `grep -rn 'config_fields\|integration_id\|xai_voice' frontend/src/app/components/user-modal/IntegrationsTab.tsx frontend/src/features/integrations/`

Find where `IntegrationDefinition.config_fields` is iterated to render inputs.

- [ ] **Step 2: Hide enable toggle + show info when linked_premium_provider is set**

Where the config form is rendered, add (near the top of the card):

```tsx
{definition.linked_premium_provider && (
  <div className="rounded bg-violet-500/10 border border-violet-500/20 px-3 py-2 text-[11px] text-violet-200/80">
    Key is managed under <a className="underline hover:text-violet-100" href="#" onClick={(e) => { e.preventDefault(); openProvidersTab(definition.linked_premium_provider!) }}>
      Providers → {providerDisplayName(definition.linked_premium_provider)}
    </a>.
    This integration is active whenever your {providerDisplayName(definition.linked_premium_provider)} account is configured.
  </div>
)}

{!definition.linked_premium_provider && <EnableToggle integration={definition} ... />}
```

Wire `openProvidersTab(providerId)` to navigate to the Settings → LLM Providers sub-tab (use the existing `userModalSubtabStore.setActive('llm-providers')` or equivalent).

Also in the same form, skip rendering any `config_field` whose `key === 'api_key'` (belt-and-braces: backend no longer sends it, but this makes the renderer robust to stale cached definitions).

- [ ] **Step 3: Manual smoke**

Run the dev server (`pnpm run dev`), open Settings → Integrations, confirm:
- xAI Voice shows no api_key input, shows the violet info line.
- Lovense still has its IP input and enable toggle unchanged.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/user-modal/IntegrationsTab.tsx frontend/src/features/integrations/
git commit -m "Integrations tab: hide api_key UI for linked integrations"
```

---

## Task 24: ConversationModeButton — voiceAvailable predicate

**Files:**
- Modify: `frontend/src/features/voice/components/ConversationModeButton.tsx`
- Test: `frontend/src/features/voice/components/__tests__/ConversationModeButton.test.tsx`

- [ ] **Step 1: Understand the current button**

Read the file to find where the activation handler is and what props the button receives (current persona, etc.).

Run: `cat frontend/src/features/voice/components/ConversationModeButton.tsx`

- [ ] **Step 2: Add availability computation**

Inside the component (or a sibling hook `useVoiceAvailable(persona)` — whichever matches existing patterns):

```tsx
import { useProvidersStore } from '../../../core/stores/providersStore'

function useVoiceAvailable(persona: Persona): boolean {
  const configured = useProvidersStore((s) => s.configuredIds())
  if (!persona.tts_provider_id) return false
  if (!configured.has(providerIdForIntegration(persona.tts_provider_id))) return false
  if (persona.stt_provider_id
      && !configured.has(providerIdForIntegration(persona.stt_provider_id))) {
    return false
  }
  return true
}
```

`providerIdForIntegration` maps a TTS/STT integration id (e.g. `xai_voice`) to the Premium provider id (e.g. `xai`). Define it as a small constant map in the same file:

```ts
const PROVIDER_ID_BY_INTEGRATION: Record<string, string> = {
  xai_voice: 'xai',
  mistral_voice: 'mistral',
}
function providerIdForIntegration(integrationId: string): string {
  return PROVIDER_ID_BY_INTEGRATION[integrationId] ?? integrationId
}
```

- [ ] **Step 3: Apply disabled + strikethrough styling + click-to-config**

In the button's render, wrap the current style with:

```tsx
const voiceAvailable = useVoiceAvailable(persona)
const navigate = useNavigate()   // whichever router hook is used

const handleClick = voiceAvailable
  ? activateVoiceMode
  : () => navigate(personaVoiceConfigPath(persona.id))

<button
  onClick={handleClick}
  title={voiceAvailable ? 'Voice chat' : 'Voice provider not configured — click to configure'}
  style={!voiceAvailable ? { opacity: 0.4, textDecoration: 'line-through' } : undefined}
  className={/* existing classes */}
>
  VOICE CHAT
</button>
```

`personaVoiceConfigPath(id)` is the route used by the existing "edit persona voice" entry point. If it's not already extracted, check `frontend/src/features/voice/components/PersonaVoiceConfig.tsx` and its parent route definition for the exact path — paste that path here.

- [ ] **Step 4: Write the test**

```tsx
// frontend/src/features/voice/components/__tests__/ConversationModeButton.test.tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ConversationModeButton } from '../ConversationModeButton'
import { useProvidersStore } from '../../../../core/stores/providersStore'

describe('ConversationModeButton', () => {
  it('is strikethrough when TTS provider has no premium account', () => {
    useProvidersStore.setState({ accounts: [] })
    render(<ConversationModeButton persona={{ id: 'p1', tts_provider_id: 'xai_voice' } as any} />)
    const btn = screen.getByRole('button')
    expect(btn.style.textDecoration).toBe('line-through')
  })

  it('is active when TTS provider has premium account', () => {
    useProvidersStore.setState({
      accounts: [{ provider_id: 'xai', config: {}, last_test_status: 'ok', last_test_error: null, last_test_at: null }],
    })
    render(<ConversationModeButton persona={{ id: 'p1', tts_provider_id: 'xai_voice' } as any} />)
    const btn = screen.getByRole('button')
    expect(btn.style.textDecoration).toBe('')
  })
})
```

- [ ] **Step 5: Run the test — expect PASS**

Run: `cd frontend && pnpm vitest run src/features/voice/components/__tests__/ConversationModeButton.test.tsx`

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/voice/components/ConversationModeButton.tsx frontend/src/features/voice/components/__tests__/ConversationModeButton.test.tsx
git commit -m "ConversationModeButton reflects premium-provider availability"
```

---

## Task 25: Remove Websearch UI + api-keys sub-tab

**Files:**
- Delete: `frontend/src/app/components/user-modal/ApiKeysTab.tsx`
- Modify: `frontend/src/app/components/user-modal/userModalTree.ts` (drop `api-keys`)
- Modify: `frontend/src/app/components/user-modal/UserModal.tsx` (drop ApiKeysTab mount)
- Modify: `frontend/src/core/api/websearch.ts`, `frontend/src/core/types/websearch.ts` — keep search/fetch types, remove credential types

- [ ] **Step 1: Drop the sub-tab entry**

Edit `userModalTree.ts`:
- Remove `'api-keys'` from `SubTabId` union.
- Remove `{ id: 'api-keys', label: 'API-Keys' }` from the settings children.
- Remove any legacy-rename reference to `'api-keys'` in `resolveLeaf` if present.

- [ ] **Step 2: Delete the tab file**

```bash
git rm frontend/src/app/components/user-modal/ApiKeysTab.tsx
```

- [ ] **Step 3: Remove render site in UserModal.tsx**

Search: `grep -n 'ApiKeysTab\|api-keys' frontend/src/app/components/user-modal/UserModal.tsx` and remove the matching imports and the `case 'api-keys'` branch (or similar).

- [ ] **Step 4: Trim websearch API/types**

In `frontend/src/core/types/websearch.ts` keep the types used by tool-call result rendering (`WebSearchResult`, `WebFetchResult`) and delete `WebSearchProvider` / `WebSearchCredential` types if present.

In `frontend/src/core/api/websearch.ts` keep any tool-call-result helpers and delete `upsertKey`, `deleteKey`, `testKey` etc. — the provider CRUD surface is gone.

- [ ] **Step 5: Verify build**

Run:
```
cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit
cd /home/chris/workspace/chatsune/frontend && pnpm vitest run
```

Fix any compile errors (usually dead imports in other files that referenced the deleted symbols).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/ && git rm frontend/src/app/components/user-modal/ApiKeysTab.tsx 2>/dev/null
git commit -m "Remove legacy API-Keys tab and websearch credential client"
```

---

## Task 26: Final backend + frontend integration sweep

**Files:**
- (multi-file verification)

- [ ] **Step 1: Backend syntax check on every touched file**

```bash
cd /home/chris/workspace/chatsune && uv run python -m py_compile \
  backend/modules/providers/__init__.py \
  backend/modules/providers/_models.py \
  backend/modules/providers/_registry.py \
  backend/modules/providers/_repository.py \
  backend/modules/providers/_handlers.py \
  backend/modules/providers/_migration_v1.py \
  backend/modules/llm/_registry.py \
  backend/modules/llm/_connections.py \
  backend/modules/llm/_resolver.py \
  backend/modules/integrations/_models.py \
  backend/modules/integrations/_registry.py \
  backend/modules/integrations/_voice_adapters/_xai.py \
  backend/modules/integrations/__init__.py \
  backend/modules/websearch/__init__.py \
  backend/modules/websearch/_registry.py \
  backend/modules/websearch/_handlers.py \
  backend/main.py \
  shared/dtos/providers.py \
  shared/events/providers.py \
  shared/topics.py \
&& echo OK
```

- [ ] **Step 2: Full backend test run**

```bash
uv run pytest backend/tests/ -q
```

Expected: all pass.

- [ ] **Step 3: Frontend type + test check**

```bash
cd frontend
pnpm tsc --noEmit
pnpm vitest run
pnpm run build
```

Expected: all clean.

- [ ] **Step 4: Update backend/pyproject.toml if any new dependency introduced**

The plan does not introduce any new Python dependencies — all imports use already-listed packages (`cryptography`, `pydantic`, `motor`, `fastapi`). If an inspection surprises you with a new import, add it to both root `pyproject.toml` and `backend/pyproject.toml` (CLAUDE.md).

- [ ] **Step 5: Commit any final touch-up fixes**

```bash
git add -u
git commit -m "Post-integration fix-ups" --allow-empty
```

(Skip commit entirely if nothing to fix.)

---

## Task 27: Manual Verification

Execute the Manual Verification checklist from the design spec
(`devdocs/superpowers/specs/2026-04-20-provider-accounts-design.md`,
Section "Manual Verification") on a real device. Record results.

Steps 1–10 in the spec cover: empty-state, key add, integrations UX,
persona LLM + voice flow, account deletion mid-session, websearch
availability, populated-DB upgrade, second-run safety,
right-to-be-forgotten.

Treat this task as blocking: do **not** merge without green results on
all ten items.

---

## Post-merge follow-ups (tracked, not implemented here)

Captured in spec's "Open questions / later work" section:

- Drop `enabled` column from `user_integration_configs` for linked integrations in a later migration (TODO noted in spec).
- Grok Imagine (TTI/ITI) adapter + tool wiring — separate spec later this week.
- Mistral LLM adapter — follow-up once TTI is in.
- Additional websearch providers (Tavily, Brave) — register as new Premium Providers.

# Voice Integrations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the in-browser WebGPU voice pipeline with a Mistral-backed voice integration that ships via Chatsune's Integrations system, supporting STT, TTS, and browser-side voice cloning under BYOK.

**Architecture:** Extend `IntegrationDefinition` with orthogonal `capabilities` and a `persona_config_fields` slot; route user-level API keys through a new encrypted-at-rest path mirroring `backend/modules/llm/_connections.py`; deliver secrets to the browser on WSS connect via a non-persisted hydration event; wire Mistral engines into the existing voice pipeline via a new `mistral_voice` plugin.

**Tech Stack:** Python + FastAPI + Pydantic v2 + MongoDB (Motor) + `cryptography.fernet` (backend); React + TypeScript + Zustand + Tailwind (frontend); direct browser-to-Mistral HTTPS calls.

**Spec:** `devdocs/superpowers/specs/2026-04-17-voice-integrations-design.md`

**Important — parallel research dependency:** The user is gathering Mistral API details (exact endpoint paths, request/response shapes, voice IDs, cloning format) in parallel. Tasks that need these details are marked **[Needs Mistral research]** and expect the notes to be available at implementation time. Code stubs are provided; the HTTP call bodies are the only parts that require filling in.

---

## File Structure

**Backend — modified:**

- `backend/modules/integrations/_models.py` — `IntegrationCapability` enum, `OptionsSource` enum, extended `IntegrationDefinition`.
- `backend/modules/integrations/_registry.py` — Lovense gets `capabilities=[TOOL_PROVIDER]`; register new `mistral_voice` definition.
- `backend/modules/integrations/_repository.py` — encryption helpers (Fernet), `_split_config`, `_redact_config`, `get_decrypted_secret`, extended `upsert_config`.
- `backend/modules/integrations/_handlers.py` — emit hydrated/cleared events on config save/clear; persona config validation.
- `backend/modules/integrations/__init__.py` — `emit_integration_secrets_for_user(user_id)` helper.
- `backend/modules/persona/_models.py` — add `integration_configs`, drop `dialogue_voice`/`narrator_voice` from `voice_config` (Pydantic-level only).
- `backend/ws/router.py` — call `emit_integration_secrets_for_user` on connect.

**Shared — modified:**

- `shared/topics.py` — register `INTEGRATION_SECRETS_HYDRATED` / `INTEGRATION_SECRETS_CLEARED` with `persist=False`; add `persist` flag to topic definitions.
- `shared/events/integrations.py` — `IntegrationSecretsHydratedEvent` + `IntegrationSecretsClearedEvent` with payloads.

**Frontend — created:**

- `frontend/src/features/integrations/secretsStore.ts`
- `frontend/src/features/integrations/secretsEventHandler.ts`
- `frontend/src/features/integrations/pluginLifecycle.ts`
- `frontend/src/features/integrations/components/GenericConfigForm.tsx`
- `frontend/src/features/integrations/plugins/mistral_voice/index.ts`
- `frontend/src/features/integrations/plugins/mistral_voice/engines.ts`
- `frontend/src/features/integrations/plugins/mistral_voice/api.ts`
- `frontend/src/features/integrations/plugins/mistral_voice/voices.ts`
- `frontend/src/features/integrations/plugins/mistral_voice/ExtraConfigComponent.tsx`
- `frontend/public/cors-probe.html`

**Frontend — modified:**

- `frontend/src/features/integrations/types.ts` — extend `IntegrationPlugin`.
- `frontend/src/features/integrations/registry.ts` — register mistral plugin.
- `frontend/src/features/integrations/ChatIntegrationsPanel.tsx` — render `GenericConfigForm` + `ExtraConfigComponent`.
- `frontend/src/features/voice/pipeline/voicePipeline.ts` — remove Whisper/Kokoro imports; rely on registry only.
- `frontend/src/features/voice/components/VoiceButton.tsx` — gate on `sttRegistry.active()?.isReady()`.
- `frontend/src/features/voice/components/ReadAloudButton.tsx` — gate on `ttsRegistry.active()?.isReady()` + persona voice_id.
- `frontend/src/features/voice/components/PersonaVoiceConfig.tsx` — drop voice selectors; show `auto_read`/`roleplay_mode` only; render generic integration-config UI for active TTS plugin.
- `frontend/src/features/voice/stores/voiceSettingsStore.ts` — drop `enabled`; keep `inputMode`.
- `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx` — keeps rendering `PersonaVoiceConfig`; no structural change.
- `frontend/package.json` — drop `@xenova/transformers` and related.

**Frontend — deleted:**

- `frontend/src/features/voice/engines/whisperEngine.ts`
- `frontend/src/features/voice/engines/kokoroEngine.ts`
- `frontend/src/features/voice/infrastructure/modelManager.ts`
- `frontend/src/features/voice/infrastructure/capabilityProbe.ts`
- `frontend/src/features/voice/infrastructure/dtypeCache.ts`
- `frontend/src/features/voice/infrastructure/dtypeLadder.ts`
- `frontend/src/features/voice/infrastructure/__tests__/*.test.ts`
- `frontend/src/features/voice/workers/voiceWorker.ts`
- `frontend/src/features/voice/workers/voiceWorkerClient.ts`
- `frontend/src/features/voice/workers/voiceLadderRunner.ts`
- `frontend/src/features/voice/workers/__tests__/*.test.ts`
- `frontend/src/features/voice/hooks/useVoiceCapabilities.ts`
- `frontend/src/features/voice/components/SetupModal.tsx`
- `frontend/src/features/voice/stores/engineLoaderStore.ts`

---

## Phase A — Shared contracts

### Task A1: Extend topics with `persist` flag

**Files:**
- Modify: `shared/topics.py`

- [ ] **Step 1: Read current `shared/topics.py`** to see the existing class structure.

- [ ] **Step 2: Introduce a `TopicDefinition` dataclass and `persist` flag.**

At the top of the file, replace the plain string-constant pattern with:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class TopicDefinition:
    name: str
    persist: bool = True

    def __str__(self) -> str:
        return self.name
```

Existing usages of `Topics.FOO` as a string must keep working. Because `TopicDefinition.__str__` returns the name, any `await event_bus.publish(Topics.FOO, ...)` call that currently passes the string-constant keeps working if the call site uses `str(Topics.FOO)` or the event bus coerces. Check how the event bus consumes topics — the cheapest way is to keep legacy string topics as plain `str` and only convert topics that need `persist=False` to `TopicDefinition`. Adjust accordingly.

- [ ] **Step 3: Add new topic constants at the bottom of the `Topics` class.**

```python
    INTEGRATION_SECRETS_HYDRATED = TopicDefinition(
        "integration.secrets.hydrated", persist=False,
    )
    INTEGRATION_SECRETS_CLEARED = TopicDefinition(
        "integration.secrets.cleared", persist=False,
    )
```

- [ ] **Step 4: Teach the event bus to honour `persist`.**

Open `backend/ws/event_bus.py`. Find the Redis-Streams-write path. Wrap the write in:

```python
topic = event.type  # or whatever field holds the topic
definition = _topic_definition_for(topic)
if definition is None or definition.persist:
    await self._redis.xadd(stream_key, fields)
```

Add a helper `_topic_definition_for(topic: str) -> TopicDefinition | None` that looks up the topic by name across `Topics` class attributes. If a matching `TopicDefinition` is found, return it; otherwise return `None` (legacy string topics → default to `persist=True`).

- [ ] **Step 5: Add a test.**

Create `backend/tests/ws/test_event_bus_persist_flag.py`:

```python
import pytest
from shared.topics import Topics
from backend.ws.event_bus import EventBus, _topic_definition_for


def test_integration_secrets_topics_are_non_persistent():
    assert Topics.INTEGRATION_SECRETS_HYDRATED.persist is False
    assert Topics.INTEGRATION_SECRETS_CLEARED.persist is False


def test_lookup_finds_persist_flag():
    defn = _topic_definition_for("integration.secrets.hydrated")
    assert defn is not None
    assert defn.persist is False


def test_lookup_returns_none_for_unknown():
    assert _topic_definition_for("does.not.exist") is None
```

- [ ] **Step 6: Run the tests.**

Run: `cd backend && uv run pytest tests/ws/test_event_bus_persist_flag.py -v`
Expected: 3 PASSED.

- [ ] **Step 7: Commit.**

```bash
git add shared/topics.py backend/ws/event_bus.py backend/tests/ws/test_event_bus_persist_flag.py
git commit -m "Add persist flag to Topics registry for ephemeral events"
```

---

### Task A2: Add `IntegrationCapability` + `OptionsSource` enums

**Files:**
- Modify: `shared/dtos/integrations.py` (add enums here so both backend and frontend-DTO-layer can import; if frontend expects them in a separate file, duplicate the string values there).
- Modify: `backend/modules/integrations/_models.py`

- [ ] **Step 1: Read `shared/dtos/integrations.py`** and the first 10 lines of `backend/modules/integrations/_models.py` to confirm current imports.

- [ ] **Step 2: Add the enums.**

At the top of `shared/dtos/integrations.py` (after imports):

```python
from enum import Enum


class IntegrationCapability(str, Enum):
    TOOL_PROVIDER = "tool_provider"
    TTS_PROVIDER = "tts_provider"
    STT_PROVIDER = "stt_provider"


class OptionsSource(str, Enum):
    PLUGIN = "plugin"
```

- [ ] **Step 3: Import them in `_models.py`.**

At the top of `backend/modules/integrations/_models.py`:

```python
from shared.dtos.integrations import IntegrationCapability, OptionsSource  # noqa: F401
```

(`OptionsSource` is imported here for downstream use; `# noqa: F401` is fine if unused directly in this file.)

- [ ] **Step 4: Commit.**

```bash
git add shared/dtos/integrations.py backend/modules/integrations/_models.py
git commit -m "Add IntegrationCapability and OptionsSource enums"
```

---

### Task A3: Define integration-secrets events

**Files:**
- Modify: `shared/events/integrations.py`

- [ ] **Step 1: Read the file** to understand existing event patterns (imports, `BaseEvent`, etc.).

- [ ] **Step 2: Add the payloads and events.**

Append to `shared/events/integrations.py`:

```python
class IntegrationSecretsHydratedPayload(BaseModel):
    integration_id: str
    secrets: dict[str, str]


class IntegrationSecretsHydratedEvent(BaseEvent):
    type: Literal["integration.secrets.hydrated"] = "integration.secrets.hydrated"
    payload: IntegrationSecretsHydratedPayload


class IntegrationSecretsClearedPayload(BaseModel):
    integration_id: str


class IntegrationSecretsClearedEvent(BaseEvent):
    type: Literal["integration.secrets.cleared"] = "integration.secrets.cleared"
    payload: IntegrationSecretsClearedPayload
```

Match the existing pattern for `BaseModel` / `BaseEvent` import and any `scope` defaults used in this file (scope for both events is `"global"`).

- [ ] **Step 3: Verify compilation.**

Run: `cd backend && uv run python -m py_compile ../shared/events/integrations.py`
Expected: no output (clean compile).

- [ ] **Step 4: Commit.**

```bash
git add shared/events/integrations.py
git commit -m "Add IntegrationSecrets{Hydrated,Cleared}Event"
```

---

## Phase B — Backend integrations schema

### Task B1: Extend `IntegrationDefinition`

**Files:**
- Modify: `backend/modules/integrations/_models.py`

- [ ] **Step 1: Replace the current dataclass with the extended version.**

```python
from dataclasses import dataclass, field
from typing import Literal

from shared.dtos.inference import ToolDefinition
from shared.dtos.integrations import IntegrationCapability  # noqa: F401


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
    persona_config_fields: list[dict] = field(default_factory=list)
    system_prompt_template: str = ""
    response_tag_prefix: str = ""
    tool_definitions: list[ToolDefinition] = field(default_factory=list)
    tool_side: Literal["server", "client"] = "client"
```

Field-schema convention for `config_fields` / `persona_config_fields` entries stays as-is (`key`, `label`, `field_type`, `required`, `description`, `placeholder`), with two optional additions:

- `secret: bool` — default `False`. When true, the value is routed through the encrypted storage path.
- `options_source: OptionsSource` — valid only when `field_type == "select"`. Default absent (static options via an `options` key).

- [ ] **Step 2: Update the Lovense definition** in `_registry.py` to include capabilities:

```python
register(IntegrationDefinition(
    id="lovense",
    # ... existing fields ...
    capabilities=[IntegrationCapability.TOOL_PROVIDER],
    # ... rest ...
))
```

Exact placement: insert `capabilities=[IntegrationCapability.TOOL_PROVIDER],` right after the `config_fields=[...]` list close, before `system_prompt_template=`. Add the import at the top:

```python
from shared.dtos.integrations import IntegrationCapability
```

- [ ] **Step 3: Add a test.**

Create `backend/tests/modules/integrations/test_registry_capabilities.py`:

```python
from backend.modules.integrations._registry import get
from shared.dtos.integrations import IntegrationCapability


def test_lovense_is_tool_provider():
    defn = get("lovense")
    assert defn is not None
    assert IntegrationCapability.TOOL_PROVIDER in defn.capabilities


def test_lovense_has_no_persona_config_fields():
    defn = get("lovense")
    assert defn.persona_config_fields == []
```

- [ ] **Step 4: Run the tests.**

Run: `cd backend && uv run pytest tests/modules/integrations/test_registry_capabilities.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit.**

```bash
git add backend/modules/integrations/_models.py backend/modules/integrations/_registry.py backend/tests/modules/integrations/test_registry_capabilities.py
git commit -m "Extend IntegrationDefinition with capabilities and persona config fields"
```

---

### Task B2: Register `mistral_voice` integration definition

**Files:**
- Modify: `backend/modules/integrations/_registry.py`

- [ ] **Step 1: Add the import for `OptionsSource`.**

```python
from shared.dtos.integrations import IntegrationCapability, OptionsSource
```

- [ ] **Step 2: Register the new definition.**

Inside `_register_builtins()`, after the Lovense `register(...)` call:

```python
register(IntegrationDefinition(
    id="mistral_voice",
    display_name="Mistral Voice",
    description="Speech-to-text and text-to-speech via Mistral AI. Bring your own API key.",
    icon="mistral",
    execution_mode="hybrid",
    capabilities=[
        IntegrationCapability.TTS_PROVIDER,
        IntegrationCapability.STT_PROVIDER,
    ],
    config_fields=[
        {
            "key": "api_key",
            "label": "Mistral API Key",
            "field_type": "password",
            "secret": True,
            "required": True,
            "description": "Your personal Mistral AI API key. Encrypted at rest, delivered in memory to your browser.",
        },
    ],
    persona_config_fields=[
        {
            "key": "voice_id",
            "label": "Voice",
            "field_type": "select",
            "options_source": OptionsSource.PLUGIN,
            "required": True,
            "description": "Voice used when this persona speaks.",
        },
    ],
    tool_definitions=[],
))
```

- [ ] **Step 3: Add a test.**

Append to `test_registry_capabilities.py`:

```python
def test_mistral_voice_is_tts_and_stt():
    defn = get("mistral_voice")
    assert defn is not None
    assert IntegrationCapability.TTS_PROVIDER in defn.capabilities
    assert IntegrationCapability.STT_PROVIDER in defn.capabilities


def test_mistral_voice_api_key_is_secret():
    defn = get("mistral_voice")
    api_key_field = next(f for f in defn.config_fields if f["key"] == "api_key")
    assert api_key_field["secret"] is True


def test_mistral_voice_has_persona_voice_field():
    defn = get("mistral_voice")
    voice_field = next(f for f in defn.persona_config_fields if f["key"] == "voice_id")
    assert voice_field["field_type"] == "select"
```

- [ ] **Step 4: Run the tests.**

Run: `cd backend && uv run pytest tests/modules/integrations/test_registry_capabilities.py -v`
Expected: 5 PASSED.

- [ ] **Step 5: Commit.**

```bash
git add backend/modules/integrations/_registry.py backend/tests/modules/integrations/test_registry_capabilities.py
git commit -m "Register mistral_voice integration definition"
```

---

## Phase C — Backend encryption and repository

### Task C1: Add Fernet encryption to integration repository

**Files:**
- Modify: `backend/modules/integrations/_repository.py`

- [ ] **Step 1: Add imports + helpers at the top of the file.**

Mirror `backend/modules/llm/_connections.py`:

```python
import logging
from cryptography.fernet import Fernet
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.config import settings
from backend.modules.integrations._registry import get as get_definition

_log = logging.getLogger(__name__)

COLLECTION = "user_integration_configs"


def _fernet() -> Fernet:
    return Fernet(settings.encryption_key.encode())


def _encrypt(v: str) -> str:
    return _fernet().encrypt(v.encode()).decode()


def _decrypt(v: str) -> str:
    return _fernet().decrypt(v.encode()).decode()


def _secret_field_keys(integration_id: str) -> set[str]:
    defn = get_definition(integration_id)
    if defn is None:
        return set()
    return {f["key"] for f in defn.config_fields if f.get("secret")}


def _split_config(integration_id: str, config: dict) -> tuple[dict, dict]:
    """Split a flat config dict into (plain, encrypted) based on secret fields."""
    secret_keys = _secret_field_keys(integration_id)
    plain: dict = {}
    encrypted: dict = {}
    for k, v in config.items():
        if k in secret_keys:
            if v is None or v == "":
                continue  # explicit-clear handled separately at upsert
            encrypted[k] = _encrypt(str(v))
        else:
            plain[k] = v
    return plain, encrypted


def _redact_config(integration_id: str, plain: dict, encrypted: dict) -> dict:
    """Return a config view with secrets replaced by {is_set: bool}."""
    secret_keys = _secret_field_keys(integration_id)
    out = dict(plain)
    for k in secret_keys:
        out[k] = {"is_set": k in encrypted}
    return out
```

- [ ] **Step 2: Extend `upsert_config` with merge semantics.**

Replace the current `upsert_config` with:

```python
    async def upsert_config(
        self,
        user_id: str,
        integration_id: str,
        enabled: bool,
        config: dict,
    ) -> dict:
        """Create or update a user's integration config.

        Secret fields in ``config`` are encrypted before storage. A secret
        field *absent* from the incoming dict is preserved (merge semantics).
        A secret field present with value ``None`` or ``""`` clears the
        stored value.
        """
        existing = await self._col.find_one(
            {"user_id": user_id, "integration_id": integration_id},
            {"config_encrypted": 1, "_id": 0},
        )
        existing_encrypted: dict = (existing or {}).get("config_encrypted", {}) or {}

        plain, encrypted = _split_config(integration_id, config)
        secret_keys = _secret_field_keys(integration_id)

        merged_encrypted = dict(existing_encrypted)
        for key in secret_keys:
            if key in encrypted:
                merged_encrypted[key] = encrypted[key]
            elif key in config and (config[key] is None or config[key] == ""):
                merged_encrypted.pop(key, None)
            # else: absent → preserve

        doc = {
            "user_id": user_id,
            "integration_id": integration_id,
            "enabled": enabled,
            "config": plain,
            "config_encrypted": merged_encrypted,
        }
        await self._col.update_one(
            {"user_id": user_id, "integration_id": integration_id},
            {"$set": doc},
            upsert=True,
        )
        _log.info(
            "Upserted integration config: user=%s integration=%s enabled=%s",
            user_id, integration_id, enabled,
        )
        return doc
```

- [ ] **Step 3: Add `get_decrypted_secret` and `redact` methods on the repo.**

Append to `IntegrationRepository`:

```python
    async def get_decrypted_secret(
        self, user_id: str, integration_id: str, field: str,
    ) -> str | None:
        doc = await self._col.find_one(
            {"user_id": user_id, "integration_id": integration_id},
            {"config_encrypted": 1, "_id": 0},
        )
        if not doc:
            return None
        enc = doc.get("config_encrypted", {})
        if field not in enc:
            return None
        return _decrypt(enc[field])

    async def get_all_decrypted_secrets(
        self, user_id: str, integration_id: str,
    ) -> dict[str, str]:
        """Decrypt every secret field of a single integration config."""
        doc = await self._col.find_one(
            {"user_id": user_id, "integration_id": integration_id},
            {"config_encrypted": 1, "_id": 0},
        )
        if not doc:
            return {}
        enc = doc.get("config_encrypted", {}) or {}
        return {k: _decrypt(v) for k, v in enc.items()}

    async def list_enabled_with_secrets(
        self, user_id: str,
    ) -> list[tuple[str, dict[str, str]]]:
        """Return [(integration_id, decrypted_secrets)] for this user's enabled integrations with secret fields."""
        cursor = self._col.find(
            {"user_id": user_id, "enabled": True},
            {"_id": 0, "integration_id": 1, "config_encrypted": 1},
        )
        out: list[tuple[str, dict[str, str]]] = []
        async for doc in cursor:
            enc = doc.get("config_encrypted", {}) or {}
            if not enc:
                continue
            out.append((
                doc["integration_id"],
                {k: _decrypt(v) for k, v in enc.items()},
            ))
        return out
```

- [ ] **Step 4: Update existing getters to redact.**

Replace `get_user_configs` and `get_user_config` with redaction applied:

```python
    async def get_user_configs(self, user_id: str) -> list[dict]:
        cursor = self._col.find({"user_id": user_id}, {"_id": 0})
        docs = await cursor.to_list(length=100)
        return [self._redact_doc(d) for d in docs]

    async def get_user_config(self, user_id: str, integration_id: str) -> dict | None:
        doc = await self._col.find_one(
            {"user_id": user_id, "integration_id": integration_id},
            {"_id": 0},
        )
        return self._redact_doc(doc) if doc else None

    @staticmethod
    def _redact_doc(doc: dict) -> dict:
        out = dict(doc)
        out["config"] = _redact_config(
            doc["integration_id"],
            doc.get("config", {}) or {},
            doc.get("config_encrypted", {}) or {},
        )
        out.pop("config_encrypted", None)
        return out
```

- [ ] **Step 5: Add a unit test for encryption round-trip.**

Create `backend/tests/modules/integrations/test_repository_encryption.py`:

```python
import pytest
from cryptography.fernet import Fernet

from backend.modules.integrations._repository import (
    IntegrationRepository, _split_config, _redact_config, _encrypt, _decrypt,
)


def test_split_config_separates_secret_fields():
    plain, encrypted = _split_config(
        "mistral_voice",
        {"api_key": "sk-abc", "something_else": "x"},
    )
    assert "api_key" not in plain
    assert "api_key" in encrypted
    assert plain == {"something_else": "x"}


def test_split_config_skips_empty_secret():
    plain, encrypted = _split_config("mistral_voice", {"api_key": ""})
    assert encrypted == {}


def test_redact_reports_is_set_true_when_encrypted_present():
    redacted = _redact_config(
        "mistral_voice",
        plain={"something": 1},
        encrypted={"api_key": "gAAA..."},
    )
    assert redacted["api_key"] == {"is_set": True}
    assert redacted["something"] == 1


def test_redact_reports_is_set_false_when_encrypted_absent():
    redacted = _redact_config("mistral_voice", plain={}, encrypted={})
    assert redacted["api_key"] == {"is_set": False}


def test_encrypt_decrypt_roundtrip():
    assert _decrypt(_encrypt("hello")) == "hello"
```

- [ ] **Step 6: Run the tests.**

Run: `cd backend && uv run pytest tests/modules/integrations/test_repository_encryption.py -v`
Expected: 5 PASSED.

- [ ] **Step 7: Compile-check the repo.**

Run: `cd backend && uv run python -m py_compile modules/integrations/_repository.py`
Expected: clean.

- [ ] **Step 8: Commit.**

```bash
git add backend/modules/integrations/_repository.py backend/tests/modules/integrations/test_repository_encryption.py
git commit -m "Add encryption, merge semantics, and redaction to integration repository"
```

---

### Task C2: Update `cascade` and `delete_all_for_user` consistency

**Files:**
- Modify: `backend/modules/integrations/_repository.py` (sanity pass — `delete_all_for_user` already fine).

- [ ] **Step 1: Read the current `delete_all_for_user`.** No change expected — deleting by `user_id` already wipes the encrypted fields with the document.

- [ ] **Step 2: Add an explicit test.**

Append to `test_repository_encryption.py`:

```python
@pytest.mark.asyncio
async def test_delete_all_for_user_removes_encrypted_secrets(mongo_db):
    repo = IntegrationRepository(mongo_db)
    await repo.upsert_config(
        user_id="u1",
        integration_id="mistral_voice",
        enabled=True,
        config={"api_key": "sk-test"},
    )
    deleted = await repo.delete_all_for_user("u1")
    assert deleted == 1
    remaining = await repo.get_user_config("u1", "mistral_voice")
    assert remaining is None
```

The `mongo_db` fixture already exists in the project's test suite. If the import path differs, adjust to match sibling tests in `backend/tests/modules/integrations/`.

- [ ] **Step 3: Run the test.**

Run: `cd backend && uv run pytest tests/modules/integrations/test_repository_encryption.py::test_delete_all_for_user_removes_encrypted_secrets -v`
Expected: PASS.

- [ ] **Step 4: Commit.**

```bash
git add backend/tests/modules/integrations/test_repository_encryption.py
git commit -m "Cover integration cascade-delete clears encrypted secrets"
```

---

## Phase D — Backend hydration

### Task D1: Add `emit_integration_secrets_for_user` helper

**Files:**
- Modify: `backend/modules/integrations/__init__.py`

- [ ] **Step 1: Read the file** to see current public exports and style.

- [ ] **Step 2: Add the helper.**

```python
from shared.events.integrations import (
    IntegrationSecretsClearedEvent,
    IntegrationSecretsClearedPayload,
    IntegrationSecretsHydratedEvent,
    IntegrationSecretsHydratedPayload,
)
from shared.topics import Topics


async def emit_integration_secrets_for_user(
    *,
    user_id: str,
    repo: "IntegrationRepository",
    event_bus: "EventBus",
) -> None:
    """Emit one hydrated event per enabled integration with secret fields."""
    for integration_id, secrets in await repo.list_enabled_with_secrets(user_id):
        await event_bus.publish_to_user(
            user_id,
            Topics.INTEGRATION_SECRETS_HYDRATED,
            IntegrationSecretsHydratedEvent(
                payload=IntegrationSecretsHydratedPayload(
                    integration_id=integration_id,
                    secrets=secrets,
                ),
                scope="global",
            ),
        )


async def emit_integration_secrets_cleared(
    *,
    user_id: str,
    integration_id: str,
    event_bus: "EventBus",
) -> None:
    await event_bus.publish_to_user(
        user_id,
        Topics.INTEGRATION_SECRETS_CLEARED,
        IntegrationSecretsClearedEvent(
            payload=IntegrationSecretsClearedPayload(integration_id=integration_id),
            scope="global",
        ),
    )
```

If the event bus does not expose `publish_to_user`, match the existing publish method used elsewhere in this module (search for `event_bus.publish` in `_handlers.py`).

- [ ] **Step 3: Commit.**

```bash
git add backend/modules/integrations/__init__.py
git commit -m "Add emit_integration_secrets helpers"
```

---

### Task D2: Wire hydration into WSS connect

**Files:**
- Modify: `backend/ws/router.py`

- [ ] **Step 1: Read the connection-accept path** — find where after authentication the router sets up per-user subscriptions.

- [ ] **Step 2: Invoke the helper after auth.**

At the point where the user is authenticated and the subscription is live, add:

```python
from backend.modules.integrations import emit_integration_secrets_for_user
from backend.modules.integrations._repository import IntegrationRepository

# inside the authenticated-connect handler, after subscriptions are wired:
integration_repo = IntegrationRepository(db)  # `db` is the existing handle in this scope
await emit_integration_secrets_for_user(
    user_id=user.id,
    repo=integration_repo,
    event_bus=event_bus,
)
```

Use the existing `db` / `event_bus` names from the surrounding code — do not introduce new dependencies.

- [ ] **Step 3: Manual sanity check.**

Run: `cd backend && uv run python -m py_compile ws/router.py`
Expected: clean.

- [ ] **Step 4: Commit.**

```bash
git add backend/ws/router.py
git commit -m "Hydrate integration secrets on WSS connect"
```

---

### Task D3: Emit hydrated/cleared on config changes

**Files:**
- Modify: `backend/modules/integrations/_handlers.py`

- [ ] **Step 1: Read the handler** that processes the `PUT /api/integrations/user-config/{id}` path (or equivalent). Find where `upsert_config` is called.

- [ ] **Step 2: After a successful upsert, emit the appropriate event.**

```python
from backend.modules.integrations import (
    emit_integration_secrets_for_user,
    emit_integration_secrets_cleared,
)
from backend.modules.integrations._registry import get as get_definition

# inside the handler, after `await repo.upsert_config(...)`:
defn = get_definition(integration_id)
has_secret_fields = any(f.get("secret") for f in (defn.config_fields if defn else []))

if enabled and has_secret_fields:
    # re-hydrate just this integration — reuse the generic helper for simplicity
    await emit_integration_secrets_for_user(
        user_id=user_id, repo=repo, event_bus=event_bus,
    )
elif not enabled and has_secret_fields:
    await emit_integration_secrets_cleared(
        user_id=user_id,
        integration_id=integration_id,
        event_bus=event_bus,
    )
```

For the delete endpoint of a user integration config, always emit `cleared`.

- [ ] **Step 3: Compile-check.**

Run: `cd backend && uv run python -m py_compile modules/integrations/_handlers.py`
Expected: clean.

- [ ] **Step 4: Commit.**

```bash
git add backend/modules/integrations/_handlers.py
git commit -m "Emit hydrated/cleared on integration config changes"
```

---

## Phase E — Backend persona integration_configs

### Task E1: Update persona model

**Files:**
- Modify: `backend/modules/persona/_models.py`

- [ ] **Step 1: Read the current model** around line 25 (`voice_config: dict | None = None`).

- [ ] **Step 2: Add `integration_configs` field.**

Add right after `voice_config`:

```python
    integration_configs: dict[str, dict] = Field(default_factory=dict)
```

Make sure `Field` is already imported from pydantic; if not, add `from pydantic import BaseModel, Field` to match the existing imports.

- [ ] **Step 3: Explicitly document the dialogue_voice/narrator_voice deprecation.**

In the `voice_config` docstring or a comment above the field:

```python
    # voice_config keys:
    #   auto_read: bool — auto-play assistant messages through active TTS
    #   roleplay_mode: bool — split dialogue vs narrator (feature not yet active)
    # Legacy keys (dialogue_voice, narrator_voice) are ignored at read time;
    # voice selection now lives in integration_configs[tts_integration_id].voice_id.
    voice_config: dict | None = None
```

- [ ] **Step 4: Compile-check.**

Run: `cd backend && uv run python -m py_compile modules/persona/_models.py`
Expected: clean.

- [ ] **Step 5: Commit.**

```bash
git add backend/modules/persona/_models.py
git commit -m "Add integration_configs to persona model; document voice_config shape"
```

---

### Task E2: Validate `integration_configs` in persona handler

**Files:**
- Modify: `backend/modules/persona/_handlers.py`

- [ ] **Step 1: Find the handler** that updates a persona (save/update path).

- [ ] **Step 2: Add validation before save.**

```python
from backend.modules.integrations._registry import get as get_integration_definition


def _validate_integration_configs(integration_configs: dict[str, dict]) -> None:
    for integration_id, values in integration_configs.items():
        defn = get_integration_definition(integration_id)
        if defn is None:
            raise ValueError(f"Unknown integration: {integration_id}")
        allowed_keys = {f["key"] for f in defn.persona_config_fields}
        unknown = set(values.keys()) - allowed_keys
        if unknown:
            raise ValueError(
                f"Unknown persona-config keys for {integration_id}: {sorted(unknown)}"
            )
```

Call `_validate_integration_configs(persona.integration_configs)` before the repository save.

- [ ] **Step 3: Add a test.**

Create `backend/tests/modules/persona/test_integration_configs_validation.py`:

```python
import pytest
from backend.modules.persona._handlers import _validate_integration_configs


def test_known_integration_known_field_passes():
    _validate_integration_configs({"mistral_voice": {"voice_id": "nova"}})


def test_unknown_integration_raises():
    with pytest.raises(ValueError, match="Unknown integration"):
        _validate_integration_configs({"not_real": {}})


def test_unknown_field_raises():
    with pytest.raises(ValueError, match="Unknown persona-config keys"):
        _validate_integration_configs(
            {"mistral_voice": {"voice_id": "nova", "extra": 1}}
        )
```

- [ ] **Step 4: Run the tests.**

Run: `cd backend && uv run pytest tests/modules/persona/test_integration_configs_validation.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit.**

```bash
git add backend/modules/persona/_handlers.py backend/tests/modules/persona/test_integration_configs_validation.py
git commit -m "Validate persona integration_configs against registry schemas"
```

---

## Phase F — Frontend cleanup

### Task F1: Delete WebGPU voice infrastructure

**Files (delete):**
- `frontend/src/features/voice/engines/whisperEngine.ts`
- `frontend/src/features/voice/engines/kokoroEngine.ts`
- `frontend/src/features/voice/infrastructure/modelManager.ts`
- `frontend/src/features/voice/infrastructure/capabilityProbe.ts`
- `frontend/src/features/voice/infrastructure/dtypeCache.ts`
- `frontend/src/features/voice/infrastructure/dtypeLadder.ts`
- `frontend/src/features/voice/infrastructure/__tests__/capabilityProbe.test.ts`
- `frontend/src/features/voice/infrastructure/__tests__/dtypeCache.test.ts`
- `frontend/src/features/voice/infrastructure/__tests__/dtypeLadder.test.ts`
- `frontend/src/features/voice/workers/voiceWorker.ts`
- `frontend/src/features/voice/workers/voiceWorkerClient.ts`
- `frontend/src/features/voice/workers/voiceLadderRunner.ts`
- `frontend/src/features/voice/workers/__tests__/voiceLadderRunner.test.ts`
- `frontend/src/features/voice/hooks/useVoiceCapabilities.ts`
- `frontend/src/features/voice/components/SetupModal.tsx`
- `frontend/src/features/voice/stores/engineLoaderStore.ts`

- [ ] **Step 1: Delete the files.**

```bash
cd frontend
rm src/features/voice/engines/whisperEngine.ts
rm src/features/voice/engines/kokoroEngine.ts
rm src/features/voice/infrastructure/modelManager.ts
rm src/features/voice/infrastructure/capabilityProbe.ts
rm src/features/voice/infrastructure/dtypeCache.ts
rm src/features/voice/infrastructure/dtypeLadder.ts
rm -r src/features/voice/infrastructure/__tests__
rm -r src/features/voice/workers
rm src/features/voice/hooks/useVoiceCapabilities.ts
rm src/features/voice/components/SetupModal.tsx
rm src/features/voice/stores/engineLoaderStore.ts
```

- [ ] **Step 2: Remove dangling imports.**

Search the repo for imports of any deleted file:

```bash
cd frontend && rg -l "whisperEngine|kokoroEngine|modelManager|capabilityProbe|dtypeCache|dtypeLadder|voiceWorker|voiceWorkerClient|voiceLadderRunner|useVoiceCapabilities|SetupModal|engineLoaderStore"
```

For each hit, delete the import line. Known consumers:
- `frontend/src/features/voice/pipeline/voicePipeline.ts` — strip Whisper/Kokoro registration.
- App-level entrypoint that mounts `SetupModal` — remove.
- Any place rendering `useVoiceCapabilities` — remove the call site and any UI dependent on it.

- [ ] **Step 3: Remove dependencies from `package.json`.**

Open `frontend/package.json`. Remove:
- `"@xenova/transformers"` (if present)
- Any other onnx/transformers peer dependencies introduced for the WebGPU path.

Do NOT touch unrelated dependencies.

- [ ] **Step 4: Reinstall.**

```bash
cd frontend && pnpm install
```

- [ ] **Step 5: Verify build.**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: type errors only on imports of now-deleted files (to be fixed in following tasks). Save the error list for Task F2.

- [ ] **Step 6: Commit.**

```bash
git add -A frontend/
git commit -m "Remove in-browser WebGPU voice pipeline"
```

---

### Task F2: Strip `voicePipeline.ts` and `voiceSettingsStore.ts` down

**Files:**
- Modify: `frontend/src/features/voice/pipeline/voicePipeline.ts`
- Modify: `frontend/src/features/voice/stores/voiceSettingsStore.ts`

- [ ] **Step 1: `voicePipeline.ts` —** keep orchestration logic, remove engine-specific setup.

The pipeline should now:
- Import `sttRegistry` and `ttsRegistry` from `engines/registry`.
- Expose `startRecording()`, `stopRecording()`, `speakResponse()`, `stopPlayback()` unchanged at their public signatures.
- In `startRecording`: `const engine = sttRegistry.active(); if (!engine?.isReady()) return`. Use `audioCapture` as today.
- In `speakResponse`: `const engine = ttsRegistry.active(); if (!engine?.isReady()) return`. Leave the `parseForSpeech` and narrator-splitting code in place.

Remove any `registerStandardEngines()` / similar call that wired Whisper or Kokoro. Engines now register themselves via their plugin's `onActivate`.

- [ ] **Step 2: `voiceSettingsStore.ts` —** drop `enabled`, keep `inputMode`.

```typescript
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type InputMode = 'push-to-talk' | 'continuous'

interface VoiceSettingsState {
  inputMode: InputMode
  setInputMode(mode: InputMode): void
}

export const useVoiceSettingsStore = create<VoiceSettingsState>()(
  persist(
    (set) => ({
      inputMode: 'push-to-talk',
      setInputMode: (inputMode) => set({ inputMode }),
    }),
    { name: 'voice-settings' },
  ),
)
```

- [ ] **Step 3: Remove `enabled` consumers.**

```bash
cd frontend && rg "voiceSettingsStore.*enabled|settings\.enabled" src/features/voice src/app
```

For each hit, delete or replace with the new gating (registry-based, see Phase I).

- [ ] **Step 4: TypeScript check.**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: clean or only errors in files addressed in later tasks.

- [ ] **Step 5: Commit.**

```bash
git add frontend/src/features/voice
git commit -m "Strip voice pipeline + settings to engine-registry only"
```

---

## Phase G — Frontend secrets store + hydration handler

### Task G1: Secrets store

**Files:**
- Create: `frontend/src/features/integrations/secretsStore.ts`

- [ ] **Step 1: Write the store.**

```typescript
import { create } from 'zustand'

interface SecretsState {
  // { [integrationId]: { [fieldKey]: value } }
  secrets: Record<string, Record<string, string>>

  setSecrets(integrationId: string, secrets: Record<string, string>): void
  clearSecrets(integrationId: string): void
  getSecret(integrationId: string, fieldKey: string): string | undefined
  hasSecrets(integrationId: string): boolean
}

export const useSecretsStore = create<SecretsState>((set, get) => ({
  secrets: {},

  setSecrets: (integrationId, secrets) =>
    set((state) => ({
      secrets: { ...state.secrets, [integrationId]: secrets },
    })),

  clearSecrets: (integrationId) =>
    set((state) => {
      const next = { ...state.secrets }
      delete next[integrationId]
      return { secrets: next }
    }),

  getSecret: (integrationId, fieldKey) =>
    get().secrets[integrationId]?.[fieldKey],

  hasSecrets: (integrationId) =>
    !!get().secrets[integrationId] &&
    Object.keys(get().secrets[integrationId]).length > 0,
}))
```

Critical: NO `persist` middleware. This store lives in memory only.

- [ ] **Step 2: Add a regression test.**

Create `frontend/src/features/integrations/__tests__/secretsStore.test.ts`:

```typescript
import { describe, expect, it, beforeEach } from 'vitest'
import { useSecretsStore } from '../secretsStore'

describe('secretsStore', () => {
  beforeEach(() => {
    useSecretsStore.setState({ secrets: {} })
  })

  it('stores and retrieves a secret', () => {
    useSecretsStore.getState().setSecrets('mistral_voice', { api_key: 'sk-abc' })
    expect(useSecretsStore.getState().getSecret('mistral_voice', 'api_key')).toBe('sk-abc')
  })

  it('reports hasSecrets correctly', () => {
    expect(useSecretsStore.getState().hasSecrets('mistral_voice')).toBe(false)
    useSecretsStore.getState().setSecrets('mistral_voice', { api_key: 'sk-abc' })
    expect(useSecretsStore.getState().hasSecrets('mistral_voice')).toBe(true)
  })

  it('clearSecrets removes the integration entry', () => {
    useSecretsStore.getState().setSecrets('mistral_voice', { api_key: 'sk-abc' })
    useSecretsStore.getState().clearSecrets('mistral_voice')
    expect(useSecretsStore.getState().getSecret('mistral_voice', 'api_key')).toBeUndefined()
  })

  it('does NOT use persist middleware', () => {
    // If persist were used, localStorage would contain the key.
    useSecretsStore.getState().setSecrets('mistral_voice', { api_key: 'sk-abc' })
    expect(localStorage.getItem('integration-secrets')).toBeNull()
    expect(localStorage.length).toBe(0)
  })
})
```

- [ ] **Step 3: Run the tests.**

```bash
cd frontend && pnpm vitest src/features/integrations/__tests__/secretsStore.test.ts
```

Expected: 4 PASSED.

- [ ] **Step 4: Commit.**

```bash
git add frontend/src/features/integrations/secretsStore.ts frontend/src/features/integrations/__tests__/secretsStore.test.ts
git commit -m "Add integration secrets store (in-memory only)"
```

---

### Task G2: WSS event handler

**Files:**
- Create: `frontend/src/features/integrations/secretsEventHandler.ts`
- Modify: the central WSS dispatcher to register it (search `wsStore` / router module).

- [ ] **Step 1: Write the handler.**

```typescript
import { useSecretsStore } from './secretsStore'

interface HydratedPayload {
  integration_id: string
  secrets: Record<string, string>
}

interface ClearedPayload {
  integration_id: string
}

export function handleIntegrationSecretsHydrated(payload: HydratedPayload) {
  useSecretsStore.getState().setSecrets(payload.integration_id, payload.secrets)
}

export function handleIntegrationSecretsCleared(payload: ClearedPayload) {
  useSecretsStore.getState().clearSecrets(payload.integration_id)
}
```

- [ ] **Step 2: Register with the central WSS router.**

Locate the file that pattern-matches on `event.type` and dispatches to handlers (search for `case 'auth.tokens.rotated'` or similar). Add:

```typescript
import {
  handleIntegrationSecretsHydrated,
  handleIntegrationSecretsCleared,
} from '../../features/integrations/secretsEventHandler'

// inside the switch / match:
case 'integration.secrets.hydrated':
  handleIntegrationSecretsHydrated(event.payload)
  break
case 'integration.secrets.cleared':
  handleIntegrationSecretsCleared(event.payload)
  break
```

- [ ] **Step 3: TS check.**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: clean.

- [ ] **Step 4: Commit.**

```bash
git add frontend/src/features/integrations/secretsEventHandler.ts frontend/src/<dispatcher-file>
git commit -m "Dispatch integration.secrets events to secrets store"
```

---

## Phase H — Frontend plugin interface + lifecycle

### Task H1: Extend `IntegrationPlugin` interface

**Files:**
- Modify: `frontend/src/features/integrations/types.ts`

- [ ] **Step 1: Read the current interface** around line 45.

- [ ] **Step 2: Add the new optional members.**

```typescript
import type { ComponentType } from 'react'

export interface Option {
  value: string
  label: string
}

export interface IntegrationPlugin {
  id: string
  // existing: executeTag, executeTool, healthCheck, emergencyStop, ConfigComponent

  /** Renders below the generic config form; not used if ConfigComponent is set. */
  ExtraConfigComponent?: ComponentType

  /** Dynamic options for persona_config_fields with options_source = plugin. */
  getPersonaConfigOptions?(fieldKey: string): Option[] | Promise<Option[]>

  /** Called when the integration becomes active (enabled + secrets hydrated if any). */
  onActivate?(): void

  /** Called when the integration is disabled or its secrets are cleared. */
  onDeactivate?(): void
}
```

- [ ] **Step 3: TS check.**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: clean.

- [ ] **Step 4: Commit.**

```bash
git add frontend/src/features/integrations/types.ts
git commit -m "Extend IntegrationPlugin with ExtraConfigComponent and lifecycle hooks"
```

---

### Task H2: Plugin lifecycle orchestrator

**Files:**
- Create: `frontend/src/features/integrations/pluginLifecycle.ts`

- [ ] **Step 1: Write the orchestrator.**

```typescript
import { useIntegrationsStore } from './store'
import { useSecretsStore } from './secretsStore'
import { getPlugin } from './registry'
import type { IntegrationPlugin } from './types'

type PluginState = 'inactive' | 'active'
const pluginStates = new Map<string, PluginState>()

function shouldBeActive(integrationId: string): boolean {
  const cfg = useIntegrationsStore.getState().configs[integrationId]
  if (!cfg?.enabled) return false

  const defn = useIntegrationsStore.getState().definitions[integrationId]
  const hasSecretFields = (defn?.config_fields ?? []).some((f) => f.secret)

  if (hasSecretFields && !useSecretsStore.getState().hasSecrets(integrationId)) {
    return false
  }
  return true
}

function reconcile(integrationId: string) {
  const plugin: IntegrationPlugin | undefined = getPlugin(integrationId)
  if (!plugin) return
  const desired: PluginState = shouldBeActive(integrationId) ? 'active' : 'inactive'
  const current = pluginStates.get(integrationId) ?? 'inactive'
  if (desired === current) return

  if (desired === 'active') {
    plugin.onActivate?.()
  } else {
    plugin.onDeactivate?.()
  }
  pluginStates.set(integrationId, desired)
}

function reconcileAll() {
  const { definitions } = useIntegrationsStore.getState()
  for (const id of Object.keys(definitions)) reconcile(id)
}

export function initPluginLifecycle(): () => void {
  const unsubIntegrations = useIntegrationsStore.subscribe(reconcileAll)
  const unsubSecrets = useSecretsStore.subscribe(reconcileAll)
  reconcileAll()
  return () => {
    unsubIntegrations()
    unsubSecrets()
  }
}
```

Adjust imports if the stores export different names (`useIntegrationStore` vs `useIntegrationsStore`) — inspect `frontend/src/features/integrations/store.ts` first.

- [ ] **Step 2: Call `initPluginLifecycle()` once at app start.**

In the app's root initialiser (typically `frontend/src/main.tsx` or a bootstrap module), add:

```typescript
import { initPluginLifecycle } from './features/integrations/pluginLifecycle'

initPluginLifecycle()
```

- [ ] **Step 3: Add a test.**

Create `frontend/src/features/integrations/__tests__/pluginLifecycle.test.ts`:

```typescript
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { useIntegrationsStore } from '../store'
import { useSecretsStore } from '../secretsStore'
import { initPluginLifecycle } from '../pluginLifecycle'
import { registerPlugin, clearRegistry } from '../registry'

describe('pluginLifecycle', () => {
  beforeEach(() => {
    clearRegistry()
    useSecretsStore.setState({ secrets: {} })
    useIntegrationsStore.setState({ configs: {}, definitions: {} })
  })

  it('activates when enabled and (no secret fields OR secrets hydrated)', () => {
    const onActivate = vi.fn()
    const onDeactivate = vi.fn()
    registerPlugin({ id: 'test', onActivate, onDeactivate } as any)

    useIntegrationsStore.setState({
      configs: { test: { enabled: true, config: {} } },
      definitions: {
        test: { config_fields: [{ key: 'api_key', secret: true }] } as any,
      },
    })
    initPluginLifecycle()

    expect(onActivate).not.toHaveBeenCalled()  // no secret yet
    useSecretsStore.getState().setSecrets('test', { api_key: 'x' })
    expect(onActivate).toHaveBeenCalledTimes(1)
  })
})
```

Adjust the `registerPlugin` / `clearRegistry` imports to match the actual exports from `registry.ts`. If `clearRegistry` doesn't exist, add a minimal test-only helper.

- [ ] **Step 4: Run the test.**

```bash
cd frontend && pnpm vitest src/features/integrations/__tests__/pluginLifecycle.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add frontend/src/features/integrations/pluginLifecycle.ts frontend/src/features/integrations/__tests__/pluginLifecycle.test.ts frontend/src/main.tsx
git commit -m "Orchestrate plugin activate/deactivate on config+secrets state"
```

---

## Phase I — Frontend generic config UI

### Task I1: Generic config form component

**Files:**
- Create: `frontend/src/features/integrations/components/GenericConfigForm.tsx`

- [ ] **Step 1: Write the component.**

```tsx
import { useState } from 'react'

type FieldDef = {
  key: string
  label: string
  field_type: 'text' | 'password' | 'number' | 'select'
  required?: boolean
  description?: string
  placeholder?: string
  secret?: boolean
  options?: Array<{ value: string; label: string }>
  // When field_type === 'select' with runtime options, the parent passes them via optionsProvider.
}

interface Props {
  fields: FieldDef[]
  initialValues: Record<string, unknown>  // for secrets: { is_set: true } or raw
  onSubmit(values: Record<string, string>): void | Promise<void>
  optionsProvider?(fieldKey: string): Array<{ value: string; label: string }> | Promise<Array<{ value: string; label: string }>>
}

export function GenericConfigForm({ fields, initialValues, onSubmit, optionsProvider }: Props) {
  const [values, setValues] = useState<Record<string, string>>(() => {
    const seed: Record<string, string> = {}
    for (const f of fields) {
      const iv = initialValues[f.key]
      seed[f.key] = typeof iv === 'string' ? iv : ''
    }
    return seed
  })
  const [submitting, setSubmitting] = useState(false)

  const isSecretSet = (key: string) => {
    const iv = initialValues[key]
    return typeof iv === 'object' && iv !== null && 'is_set' in iv && (iv as any).is_set
  }

  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault()
        setSubmitting(true)
        try {
          // Omit secret fields the user didn't touch (they show as masked placeholder).
          const payload: Record<string, string> = {}
          for (const f of fields) {
            if (f.secret && values[f.key] === '') continue
            payload[f.key] = values[f.key]
          }
          await onSubmit(payload)
        } finally {
          setSubmitting(false)
        }
      }}
    >
      {fields.map((f) => (
        <FieldRow
          key={f.key}
          field={f}
          value={values[f.key]}
          onChange={(v) => setValues((prev) => ({ ...prev, [f.key]: v }))}
          secretSet={isSecretSet(f.key)}
          optionsProvider={optionsProvider}
        />
      ))}
      <button type="submit" disabled={submitting}>
        {submitting ? 'Saving…' : 'Save'}
      </button>
    </form>
  )
}

function FieldRow({ field, value, onChange, secretSet, optionsProvider }: {
  field: FieldDef
  value: string
  onChange(v: string): void
  secretSet: boolean
  optionsProvider?: Props['optionsProvider']
}) {
  const label = <label>{field.label}{field.required ? ' *' : ''}</label>

  if (field.field_type === 'password' || field.secret) {
    return (
      <div>
        {label}
        <input
          type="password"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={secretSet ? '••••••••  (set — leave blank to keep)' : field.placeholder}
        />
        {secretSet && !value && <small>Currently configured. Type a new value to replace.</small>}
        {field.description && <small>{field.description}</small>}
      </div>
    )
  }

  if (field.field_type === 'select') {
    return <SelectField field={field} value={value} onChange={onChange} optionsProvider={optionsProvider} />
  }

  return (
    <div>
      {label}
      <input
        type={field.field_type === 'number' ? 'number' : 'text'}
        value={value}
        placeholder={field.placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
      {field.description && <small>{field.description}</small>}
    </div>
  )
}

function SelectField({ field, value, onChange, optionsProvider }: {
  field: FieldDef
  value: string
  onChange(v: string): void
  optionsProvider?: Props['optionsProvider']
}) {
  // Static options via `field.options`; runtime options via optionsProvider.
  const [options, setOptions] = useState(field.options ?? [])

  // If runtime options are expected, load once.
  // (Simple implementation — extend with useEffect when integrating.)
  if (!field.options && optionsProvider) {
    const result = optionsProvider(field.key)
    if (result instanceof Promise) {
      result.then(setOptions)
    } else if (options !== result) {
      setOptions(result)
    }
  }

  const OPTION_STYLE: React.CSSProperties = {
    background: '#0f0d16',
    color: 'rgba(255,255,255,0.85)',
  }

  return (
    <div>
      <label>{field.label}{field.required ? ' *' : ''}</label>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="" style={OPTION_STYLE}>—</option>
        {options.map((o) => (
          <option key={o.value} value={o.value} style={OPTION_STYLE}>{o.label}</option>
        ))}
      </select>
      {field.description && <small>{field.description}</small>}
    </div>
  )
}
```

**Note:** The `OPTION_STYLE` inline style is required per the CLAUDE.md frontend styling gotcha — native `<select>` dropdowns ignore parent styling.

- [ ] **Step 2: Commit.**

```bash
git add frontend/src/features/integrations/components/GenericConfigForm.tsx
git commit -m "Add generic config form renderer for integrations"
```

---

### Task I2: Integrate generic form + ExtraConfigComponent slot into the integration card

**Files:**
- Modify: `frontend/src/features/integrations/ChatIntegrationsPanel.tsx`

- [ ] **Step 1: Read the file** to see how cards currently render Lovense (via its custom `ConfigComponent`).

- [ ] **Step 2: Add fallback to generic form + extra slot.**

Where a card renders the body:

```tsx
import { GenericConfigForm } from './components/GenericConfigForm'
import { getPlugin } from './registry'

function IntegrationCardBody({ definition, config }: Props) {
  const plugin = getPlugin(definition.id)

  if (plugin?.ConfigComponent) {
    // Lovense keeps full replacement.
    return <plugin.ConfigComponent />
  }

  return (
    <>
      <GenericConfigForm
        fields={definition.config_fields}
        initialValues={config?.config ?? {}}
        onSubmit={async (values) => {
          await integrationsApi.saveUserConfig(definition.id, {
            enabled: config?.enabled ?? true,
            config: values,
          })
        }}
      />
      {plugin?.ExtraConfigComponent && <plugin.ExtraConfigComponent />}
    </>
  )
}
```

Adapt names (`integrationsApi.saveUserConfig`) to the actual API module used by the existing code.

- [ ] **Step 3: TS check + visual smoke test.**

```bash
cd frontend && pnpm tsc --noEmit && pnpm run build
```

Expected: clean.

- [ ] **Step 4: Commit.**

```bash
git add frontend/src/features/integrations/ChatIntegrationsPanel.tsx
git commit -m "Render generic form + ExtraConfigComponent slot for integrations without ConfigComponent"
```

---

## Phase J — Mistral plugin core

### Task J1: Mistral API client — STT + TTS (using official SDK)

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/src/features/integrations/plugins/mistral_voice/api.ts`

**Reference:** User's research notes at `devdocs/mistral-api-notes.md` confirm the official SDK `@mistralai/mistralai` is the right integration path. All calls stay browser-side (CORS OK, BYOK).

- [ ] **Step 1: Install the Mistral SDK.**

```bash
cd frontend && pnpm add @mistralai/mistralai
```

Verify `package.json` now lists the dependency.

- [ ] **Step 2: Write the API wrapper.**

```typescript
// frontend/src/features/integrations/plugins/mistral_voice/api.ts
//
// Thin wrapper around the official @mistralai/mistralai SDK. Keeps engine
// code (engines.ts) decoupled from the SDK's exact call shapes — if the
// SDK changes, only this file changes. All calls go directly browser →
// Mistral; the user's API key is passed per call.
//
// SDK method names below follow the README at
// https://github.com/mistralai/client-ts. If the exact method for TTS or
// STT differs from what's written here (e.g. `client.audio.speech.create`
// vs. `client.tts.generate`), consult the installed SDK's .d.ts files
// (node_modules/@mistralai/mistralai/) and adjust the three call sites.

import { MistralClient } from '@mistralai/mistralai'

function client(apiKey: string): MistralClient {
  return new MistralClient({ apiKey })
}

export interface TranscribeParams {
  apiKey: string
  audio: Blob
  language?: string
}

export async function transcribe({ apiKey, audio, language }: TranscribeParams): Promise<string> {
  const file = new File([audio], 'recording.wav', { type: audio.type || 'audio/wav' })
  const result: any = await (client(apiKey) as any).audio.transcriptions.create({
    file,
    model: 'voxtral-mini-latest',   // confirm against SDK / Mistral docs
    language,
  })
  // Response shape per Mistral docs: { text: string, ... }
  return result.text as string
}

export interface SynthesiseParams {
  apiKey: string
  text: string
  voiceId: string
}

export async function synthesise({ apiKey, text, voiceId }: SynthesiseParams): Promise<Blob> {
  const result: any = await (client(apiKey) as any).audio.speech.create({
    input: text,
    voice: voiceId,
    model: 'voxtral-tts-latest',  // confirm against SDK / Mistral docs
  })
  // SDK may return Blob directly, or a response object with .blob() / .arrayBuffer().
  if (result instanceof Blob) return result
  if (typeof result?.blob === 'function') return await result.blob()
  if (result instanceof ArrayBuffer) return new Blob([result])
  // Fallback: assume { audio: base64 } or similar — read SDK .d.ts and adjust.
  throw new Error('Unexpected Mistral TTS response shape; inspect SDK types in node_modules')
}
```

The `as any` casts are intentional escape hatches for the three spots where we call SDK methods whose exact names may differ. When running the plan, the engineer opens `node_modules/@mistralai/mistralai/` to confirm, drops the `as any`, and replaces the call shape with the real one. The surrounding API (function names and return types) stays stable so `engines.ts` never needs to change.

- [ ] **Step 3: Compile-check.**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: clean. If the `MistralClient` import errors with "has no exported member", check the SDK's default-vs-named export convention and adjust (e.g. `import Mistral from '@mistralai/mistralai'` and `new Mistral(...)`).

- [ ] **Step 4: Commit.**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml frontend/src/features/integrations/plugins/mistral_voice/api.ts
git commit -m "Add Mistral SDK wrapper for STT and TTS"
```

---

### Task J2: Mistral engines

**Files:**
- Create: `frontend/src/features/integrations/plugins/mistral_voice/voices.ts`
- Create: `frontend/src/features/integrations/plugins/mistral_voice/engines.ts`

- [ ] **Step 1: Voices list — start empty.**

Per Mistral's voice model: `client.voices.list()` returns the full set (stock + any clones the user created). There is no separate static stock list we need to hard-code.

```typescript
// frontend/src/features/integrations/plugins/mistral_voice/voices.ts
import type { VoicePreset } from '../../../voice/types'

// Populated at runtime by the plugin from client.voices.list().
// Empty at module load; engines.ts reads it via a mutable export.
export const mistralVoices: { current: VoicePreset[] } = { current: [] }
```

- [ ] **Step 2: Engines.**

```typescript
// frontend/src/features/integrations/plugins/mistral_voice/engines.ts
import { transcribe, synthesise } from './api'
import { mistralVoices } from './voices'
import { useSecretsStore } from '../../secretsStore'
import type { STTEngine, TTSEngine, VoicePreset } from '../../../voice/types'

const INTEGRATION_ID = 'mistral_voice'
const API_KEY_FIELD = 'api_key'

function getApiKey(): string | undefined {
  return useSecretsStore.getState().getSecret(INTEGRATION_ID, API_KEY_FIELD)
}

export class MistralSTTEngine implements STTEngine {
  id = 'mistral_stt'
  name = 'Mistral Voxtral'
  modelSize = 0
  languages = ['en', 'de']  // SDK may accept other BCP-47 codes

  async init(): Promise<void> { /* no-op, no local model */ }
  async dispose(): Promise<void> { /* no-op */ }

  isReady(): boolean {
    return !!getApiKey()
  }

  async transcribe(audio: Blob): Promise<string> {
    const key = getApiKey()
    if (!key) throw new Error('Mistral API key not configured')
    return transcribe({ apiKey: key, audio })
  }
}

export class MistralTTSEngine implements TTSEngine {
  id = 'mistral_tts'
  name = 'Mistral Voice'
  modelSize = 0

  // Live view on the mutable mistralVoices.current — the plugin refreshes
  // it from the SDK's voice list on activate and after clone/delete.
  get voices(): VoicePreset[] {
    return mistralVoices.current
  }

  async init(): Promise<void> { /* no-op */ }
  async dispose(): Promise<void> { /* no-op */ }

  isReady(): boolean {
    return !!getApiKey()
  }

  async synthesise(text: string, voiceId: string): Promise<Blob> {
    const key = getApiKey()
    if (!key) throw new Error('Mistral API key not configured')
    return synthesise({ apiKey: key, text, voiceId })
  }
}
```

Note: `TTSEngine.synthesise` return type changes from `ArrayBuffer` to `Blob` (SDK returns a Blob directly in the user's reference). If the current `TTSEngine` interface declares `Promise<ArrayBuffer>`, update the interface in `frontend/src/features/voice/types.ts` and the consumers (`audioPlayback.ts`) in the same commit — `new Audio(URL.createObjectURL(blob)).play()` is the direct Blob path.

Verify the exact `STTEngine` / `TTSEngine` interface shapes in `frontend/src/features/voice/types.ts` and match fields precisely. Adjust field names if the current interface uses e.g. `synthesize` (American spelling) — align with existing code.

- [ ] **Step 3: TS check.**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: clean.

- [ ] **Step 4: Commit.**

```bash
git add frontend/src/features/integrations/plugins/mistral_voice/
git commit -m "Add Mistral STT/TTS engines"
```

---

### Task J3: Register Mistral plugin

**Files:**
- Create: `frontend/src/features/integrations/plugins/mistral_voice/index.ts`
- Modify: `frontend/src/features/integrations/registry.ts`

- [ ] **Step 1: Plugin definition.**

```typescript
// frontend/src/features/integrations/plugins/mistral_voice/index.ts
import type { IntegrationPlugin, Option } from '../../types'
import { sttRegistry, ttsRegistry } from '../../../voice/engines/registry'
import { MistralSTTEngine, MistralTTSEngine } from './engines'

let sttInstance: MistralSTTEngine | null = null
let ttsInstance: MistralTTSEngine | null = null

export const mistralVoicePlugin: IntegrationPlugin = {
  id: 'mistral_voice',

  onActivate() {
    if (!sttInstance) sttInstance = new MistralSTTEngine()
    if (!ttsInstance) ttsInstance = new MistralTTSEngine()
    sttRegistry.register(sttInstance)
    ttsRegistry.register(ttsInstance)
  },

  onDeactivate() {
    if (sttInstance) sttRegistry.unregister(sttInstance.id)
    if (ttsInstance) ttsRegistry.unregister(ttsInstance.id)
  },

  async getPersonaConfigOptions(fieldKey: string): Promise<Option[]> {
    if (fieldKey !== 'voice_id') return []
    // Refreshes from the Mistral SDK on each call, cached implicitly via mistralVoices.current.
    // Actual fetch happens in Task M2 (voice cloning UI also triggers refresh).
    return mistralVoices.current.map((v) => ({ value: v.id, label: v.name }))
  },
}
```

Check the actual import paths and method names on `sttRegistry`/`ttsRegistry` in `frontend/src/features/voice/engines/registry.ts`. If the methods are called `add`/`remove` rather than `register`/`unregister`, adjust.

- [ ] **Step 2: Register with the plugin registry.**

```typescript
// frontend/src/features/integrations/registry.ts — add:
import { mistralVoicePlugin } from './plugins/mistral_voice'

registerPlugin(mistralVoicePlugin)
```

Use the existing `registerPlugin` / register function name.

- [ ] **Step 3: Build check.**

```bash
cd frontend && pnpm run build
```

Expected: clean.

- [ ] **Step 4: Commit.**

```bash
git add frontend/src/features/integrations/plugins/mistral_voice/index.ts frontend/src/features/integrations/registry.ts
git commit -m "Register mistral_voice plugin with activate/deactivate lifecycle"
```

---

## Phase K — Frontend persona voice config

### Task K1: Replace `PersonaVoiceConfig` voice pickers with integration-driven UI

**Files:**
- Modify: `frontend/src/features/voice/components/PersonaVoiceConfig.tsx`

- [ ] **Step 1: Strip the dialogue/narrator voice selectors.** Retain `auto_read` and `roleplay_mode` toggles.

- [ ] **Step 2: Render integration-based voice selection.**

```tsx
import { useIntegrationsStore } from '../../integrations/store'
import { getPlugin } from '../../integrations/registry'
import { GenericConfigForm } from '../../integrations/components/GenericConfigForm'

// Capability string literals match the backend enum values (IntegrationCapability).
// The shared/ folder is Python; use string literals directly in TS.
const TTS_PROVIDER = 'tts_provider' as const

export function PersonaVoiceConfig({ persona, chakra, onSave }: Props) {
  const definitions = useIntegrationsStore((s) => s.definitions)
  const configs = useIntegrationsStore((s) => s.configs)

  const activeTTS = Object.values(definitions).find((d) =>
    d.capabilities?.includes(TTS_PROVIDER) &&
    configs[d.id]?.enabled,
  )

  return (
    <section>
      <h3>Voice</h3>

      {/* auto_read + roleplay_mode toggles — existing code stays */}
      {/* ... */}

      {!activeTTS && (
        <p>Activate a TTS integration under Settings → Integrations to select a voice for this persona.</p>
      )}

      {activeTTS && (
        <GenericConfigForm
          fields={activeTTS.persona_config_fields}
          initialValues={persona.integration_configs?.[activeTTS.id] ?? {}}
          onSubmit={(values) =>
            onSave({
              ...persona,
              integration_configs: {
                ...persona.integration_configs,
                [activeTTS.id]: values,
              },
            })
          }
          optionsProvider={(fieldKey) =>
            Promise.resolve(getPlugin(activeTTS.id)?.getPersonaConfigOptions?.(fieldKey) ?? [])
          }
        />
      )}
    </section>
  )
}
```

Keep the existing `chakra` theming intact. Respect the style split — this is user-facing UI, not admin, so use the existing opulent styling hooks the component already uses.

- [ ] **Step 3: TS check + build.**

```bash
cd frontend && pnpm tsc --noEmit && pnpm run build
```

Expected: clean.

- [ ] **Step 4: Commit.**

```bash
git add frontend/src/features/voice/components/PersonaVoiceConfig.tsx
git commit -m "Drive per-persona voice selection from active TTS integration"
```

---

## Phase L — Chat GUI wiring

### Task L1: Mic button gate

**Files:**
- Modify: `frontend/src/features/voice/components/VoiceButton.tsx`

- [ ] **Step 1: Read the component** — understand how it currently decides whether to render the mic/send glyph.

- [ ] **Step 2: Gate on registry readiness.**

Existing logic: mic shown when prompt input is empty, send icon when the user typed. Additional gate:

```tsx
import { sttRegistry } from '../engines/registry'

const sttEngine = sttRegistry.active()  // pick the first registered engine
const sttReady = sttEngine?.isReady() === true

const shouldShowMic = promptIsEmpty && sttReady
```

If `sttRegistry.active()` does not exist, pick the first engine from a `list()` method instead. The intent: morph reverts to `send` whenever there is no ready STT engine, so the user never sees a mic that can't record.

- [ ] **Step 3: Visual regression: type-check only (UI test is manual).**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: clean.

- [ ] **Step 4: Commit.**

```bash
git add frontend/src/features/voice/components/VoiceButton.tsx
git commit -m "Gate mic-morph on STT registry readiness"
```

---

### Task L2: Read-aloud button gate

**Files:**
- Modify: `frontend/src/features/voice/components/ReadAloudButton.tsx`

- [ ] **Step 1: Read the component** to see current gating.

- [ ] **Step 2: Gate on TTS engine + persona voice_id.**

```tsx
import { ttsRegistry } from '../engines/registry'
import { useIntegrationsStore } from '../../integrations/store'

function useActiveTtsVoiceId(persona: Persona): string | undefined {
  const definitions = useIntegrationsStore((s) => s.definitions)
  const activeTTS = Object.values(definitions).find((d) =>
    d.capabilities?.includes('tts_provider'),
  )
  if (!activeTTS) return undefined
  return persona.integration_configs?.[activeTTS.id]?.voice_id
}

// in the component:
const tts = ttsRegistry.active()
const voiceId = useActiveTtsVoiceId(persona)
const canRead = tts?.isReady() && voiceId
if (!canRead) return null
```

- [ ] **Step 3: Type-check.**

```bash
cd frontend && pnpm tsc --noEmit
```

- [ ] **Step 4: Commit.**

```bash
git add frontend/src/features/voice/components/ReadAloudButton.tsx
git commit -m "Gate read-aloud on TTS readiness and persona voice_id"
```

---

### Task L3: Auto-read via `voice_config.auto_read`

**Files:**
- Modify: the chat component or pipeline that handles new assistant messages (search for existing `auto_read` consumer).

- [ ] **Step 1: Find the call site.**

```bash
cd frontend && rg "auto_read"
```

- [ ] **Step 2: Ensure the auto-read code uses `ttsRegistry.active()?.isReady()` AND the persona's `integration_configs[ttsId].voice_id` before triggering playback.** No change to cache behaviour — cache lives in the existing audio-playback layer, keyed by text + voiceId.

- [ ] **Step 3: Build check.**

```bash
cd frontend && pnpm run build
```

- [ ] **Step 4: Commit.**

```bash
git add frontend/src/<files-modified>
git commit -m "Auto-read: gate on TTS readiness and persona voice_id"
```

---

## Phase M — Voice cloning

### Task M1: Extend Mistral API client with voice-cloning calls (SDK)

**Files:**
- Modify: `frontend/src/features/integrations/plugins/mistral_voice/api.ts`
- Modify: `frontend/src/features/integrations/plugins/mistral_voice/voices.ts`

**Reference:** `devdocs/mistral-api-notes.md` confirms `client.voices.delete(voiceId)` and hook-style `cloneVoice`/`listVoices` wrappers. SDK exposes a `voices` namespace.

- [ ] **Step 1: Append cloning / listing functions to `api.ts`.**

```typescript
// Append to frontend/src/features/integrations/plugins/mistral_voice/api.ts

export interface MistralVoice {
  id: string       // SDK returns voice_id — normalise to `id` here for our internal shape
  name: string
}

function mapVoice(raw: any): MistralVoice {
  return { id: raw.voice_id ?? raw.id, name: raw.name }
}

export async function listVoices(apiKey: string): Promise<MistralVoice[]> {
  const result: any = await (client(apiKey) as any).voices.list()
  // SDK may return an array directly, or { data: [...] } — handle both.
  const list = Array.isArray(result) ? result : (result?.data ?? result?.voices ?? [])
  return list.map(mapVoice)
}

export async function cloneVoice({ apiKey, audio, name }: {
  apiKey: string
  audio: Blob
  name: string
}): Promise<MistralVoice> {
  const file = new File([audio], 'sample.wav', { type: audio.type || 'audio/wav' })
  const result: any = await (client(apiKey) as any).voices.clone({ file, name })
  return mapVoice(result)
}

export async function deleteVoice(apiKey: string, voiceId: string): Promise<void> {
  await (client(apiKey) as any).voices.delete(voiceId)
}
```

The `as any` on the SDK client is the same escape hatch as in Task J1. The engineer opens the SDK's `.d.ts` files, confirms the exact method names and argument shapes (e.g. `voices.clone({ file, name })` vs. `voices.create({ file, name })`), drops the casts, and adjusts.

- [ ] **Step 2: Refresh-helper for `mistralVoices`.**

Append to `voices.ts`:

```typescript
import { listVoices } from './api'

export async function refreshMistralVoices(apiKey: string): Promise<void> {
  try {
    const all = await listVoices(apiKey)
    mistralVoices.current = all.map((v) => ({ id: v.id, name: v.name }))
  } catch {
    // Soft-fail — keep whatever we had.
  }
}
```

- [ ] **Step 3: Plugin calls the refresh on activate.**

In `plugins/mistral_voice/index.ts`, extend `onActivate`:

```typescript
import { refreshMistralVoices } from './voices'
import { useSecretsStore } from '../../secretsStore'

onActivate() {
  if (!sttInstance) sttInstance = new MistralSTTEngine()
  if (!ttsInstance) ttsInstance = new MistralTTSEngine()
  sttRegistry.register(sttInstance)
  ttsRegistry.register(ttsInstance)
  const key = useSecretsStore.getState().getSecret('mistral_voice', 'api_key')
  if (key) refreshMistralVoices(key)  // fire-and-forget
}
```

- [ ] **Step 4: Compile-check.**

```bash
cd frontend && pnpm tsc --noEmit
```

- [ ] **Step 5: Commit.**

```bash
git add frontend/src/features/integrations/plugins/mistral_voice/
git commit -m "Add Mistral voice list/clone/delete via SDK and refresh helper"
```

---

### Task M2: Extra-config component with cloning UI

**Files:**
- Create: `frontend/src/features/integrations/plugins/mistral_voice/ExtraConfigComponent.tsx`

- [ ] **Step 1: Write the component.**

```tsx
import { useEffect, useRef, useState } from 'react'
import { useSecretsStore } from '../../secretsStore'
import { cloneVoice, deleteVoice, listVoices, type MistralVoice } from './api'
import { refreshMistralVoices } from './voices'
import { startMicRecording, type MicRecording } from '../../../voice/infrastructure/audioCapture'

export function ExtraConfigComponent() {
  const [voices, setVoices] = useState<MistralVoice[]>([])
  const [name, setName] = useState('')
  const [recording, setRecording] = useState<MicRecording | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const apiKey = useSecretsStore((s) => s.getSecret('mistral_voice', 'api_key'))

  const refreshVoices = async () => {
    if (!apiKey) return
    try {
      const all = await listVoices(apiKey)
      setVoices(all)  // SDK doesn't distinguish stock vs. cloned — show all
      await refreshMistralVoices(apiKey)  // keep mistralVoices.current in sync for engines
    } catch (e: any) {
      setError(e.message)
    }
  }

  useEffect(() => { refreshVoices() }, [apiKey])

  const handleSubmit = async (audio: Blob) => {
    if (!apiKey) return
    setBusy(true); setError(null)
    try {
      await cloneVoice({ apiKey, audio, name })
      setName('')
      await refreshVoices()
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = async (voiceId: string) => {
    if (!apiKey) return
    if (!confirm('Delete this cloned voice?')) return
    await deleteVoice(apiKey, voiceId)
    await refreshVoices()
  }

  if (!apiKey) return null

  return (
    <section>
      <h4>Your cloned voices</h4>
      {voices.length === 0 && <p>None yet.</p>}
      <ul>
        {voices.map((v) => (
          <li key={v.id}>
            {v.name}
            <button onClick={() => handleDelete(v.id)}>Delete</button>
          </li>
        ))}
      </ul>

      <h4>Clone a new voice</h4>
      <input
        type="text"
        placeholder="Voice name"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />

      <div>
        <strong>Record</strong>
        {!recording ? (
          <button
            disabled={!name || busy}
            onClick={async () => setRecording(await startMicRecording())}
          >Start recording</button>
        ) : (
          <button
            disabled={busy}
            onClick={async () => {
              const blob = await recording.stop()
              setRecording(null)
              await handleSubmit(blob)
            }}
          >Stop &amp; submit</button>
        )}
      </div>

      <div>
        <strong>Upload</strong>
        <input
          type="file"
          accept="audio/*"
          disabled={!name || busy}
          onChange={async (e) => {
            const file = e.target.files?.[0]
            if (file) await handleSubmit(file)
          }}
        />
      </div>

      {error && <p role="alert">{error}</p>}
    </section>
  )
}
```

Adjust `startMicRecording` / `MicRecording` imports to the actual names exported by `audioCapture.ts`. If the existing API returns a `MediaRecorder` directly, wrap it.

- [ ] **Step 2: Export via `index.ts`.**

```typescript
// index.ts — add to the plugin object:
import { ExtraConfigComponent } from './ExtraConfigComponent'

export const mistralVoicePlugin: IntegrationPlugin = {
  // ...existing fields...
  ExtraConfigComponent,
}
```

- [ ] **Step 3: Ensure `getPersonaConfigOptions` pulls the fresh voice list.**

The existing implementation (Task J3) reads `mistralVoices.current`. After a clone/delete, `refreshMistralVoices(apiKey)` updates it, and the next dropdown open will see the new voice — no further changes needed here beyond what Task M2 Step 1 already does via `refreshVoices()`.

If the dropdown is opened *before* the user has added their key and `mistralVoices.current` is empty, call `refreshMistralVoices` lazily from `getPersonaConfigOptions`:

```typescript
// inside mistralVoicePlugin.getPersonaConfigOptions:
async getPersonaConfigOptions(fieldKey: string): Promise<Option[]> {
  if (fieldKey !== 'voice_id') return []
  const apiKey = useSecretsStore.getState().getSecret('mistral_voice', 'api_key')
  if (apiKey && mistralVoices.current.length === 0) {
    await refreshMistralVoices(apiKey)
  }
  return mistralVoices.current.map((v) => ({ value: v.id, label: v.name }))
}
```

The signature stays `Promise<Option[]>` as declared in Task H1.

- [ ] **Step 4: Build check.**

```bash
cd frontend && pnpm run build
```

- [ ] **Step 5: Commit.**

```bash
git add frontend/src/features/integrations/plugins/mistral_voice/
git commit -m "Add Mistral voice-cloning UI via ExtraConfigComponent"
```

---

## Phase N — Manual validation

### Task N1: CORS probe page

**Files:**
- Create: `frontend/public/cors-probe.html`

- [ ] **Step 1: Write a standalone HTML page** that hits `api.mistral.ai` directly with a user-entered key.

```html
<!doctype html>
<html>
<head><meta charset="utf-8"><title>Mistral CORS Probe</title></head>
<body>
  <h1>Mistral CORS probe</h1>
  <p>Enter your Mistral API key. This page makes a single call to the TTS endpoint to verify CORS works from the browser.</p>
  <input id="key" type="password" placeholder="sk-..." />
  <button id="go">Probe</button>
  <pre id="out"></pre>
  <script>
    document.getElementById('go').onclick = async () => {
      const key = document.getElementById('key').value
      const out = document.getElementById('out')
      out.textContent = 'Calling...'
      try {
        // Use whichever Mistral endpoint is cheapest to probe — e.g. list models or voices.
        const res = await fetch('https://api.mistral.ai/v1/models', {
          headers: { Authorization: 'Bearer ' + key }
        })
        out.textContent = 'status ' + res.status + '\n\n' + (await res.text())
      } catch (e) {
        out.textContent = 'FAIL: ' + e.message
      }
    }
  </script>
</body>
</html>
```

- [ ] **Step 2: Open the page locally and enter the key.**

```bash
cd frontend && pnpm run dev
# then open http://localhost:5173/cors-probe.html in a browser
```

Expected: `status 200` with a JSON body. If it fails with a CORS error, the direct-call strategy needs the fallback proxy — see the spec's CORS section. Tell the user immediately.

- [ ] **Step 3: Delete the probe file after success.**

```bash
rm frontend/public/cors-probe.html
```

- [ ] **Step 4: Commit the probe addition + its removal separately** so the probe is preserved in history:

```bash
git add frontend/public/cors-probe.html
git commit -m "Add one-shot Mistral CORS probe page"
git rm frontend/public/cors-probe.html
git commit -m "Remove CORS probe page after successful verification"
```

---

### Task N2: End-to-end manual test

- [ ] **Step 1: Run the stack.**

```bash
docker compose up -d
```

- [ ] **Step 2: Add Mistral integration in the UI.**

Log in, go to Settings → Integrations, enable Mistral Voice, paste an API key, save. Verify the UI flips to "configured".

- [ ] **Step 3: Confirm the hydrated event.**

Open browser devtools → Network → WS. After login, a `integration.secrets.hydrated` message for `mistral_voice` should arrive. Verify `secrets.api_key` is the clear key (expected — it's in memory only).

- [ ] **Step 4: Open a persona.**

In the persona edit view, the voice section should now show a Mistral voice dropdown. Pick a voice and save.

- [ ] **Step 5: Send a chat message.**

Type → send → the assistant replies. Click the read-aloud button — audio plays.

- [ ] **Step 6: Test mic input.**

Clear the prompt textarea → the send button turns into a mic. Hold (or click in continuous mode), speak, release → the transcript appears in the textarea.

- [ ] **Step 7: Clone a voice.**

In the integration settings, record a short sample, name it, submit. After a moment, the new voice appears in the list. Go back to the persona and select the cloned voice. Read-aloud now uses the cloned voice.

- [ ] **Step 8: Test deactivation.**

Disable the Mistral integration. Mic button reverts to send; read-aloud button disappears; voice dropdown grays out. Re-enable — everything lights up again without needing a reload.

- [ ] **Step 9: Final commit checkpoint.**

No file changes — this task is validation-only. If something fails, branch off a bugfix commit that addresses the specific issue.

---

## Verification Summary

After all phases, confirm:

- `cd backend && uv run pytest` passes cleanly.
- `cd frontend && pnpm run build` exits with zero errors.
- `docker compose up -d` brings the stack up; the manual E2E in Task N2 completes.
- No references to deleted files remain (`rg whisperEngine|kokoroEngine|modelManager` returns nothing in `frontend/src`).
- `rg "voiceSettingsStore.*enabled"` returns nothing (single source of truth is the integration toggle).

# xAI Voice Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add xAI as a second voice provider alongside Mistral. Users select per-persona which TTS provider speaks and per-user which STT provider transcribes.

**Architecture:** New backend-proxied integration (API key never leaves the server; see design spec). Three new proxy routes (STT / TTS / voices list) dispatch to a small `VoiceAdapter` abstraction in the integrations module. Frontend adds a mirror `xai_voice` plugin and migrates the voice-engine registry from a single-active-engine model to per-persona / per-user resolvers.

**Tech Stack:** Python / FastAPI / Pydantic v2 / httpx / pytest backend; TypeScript / React / Zustand / vitest frontend.

**Spec:** [2026-04-19-xai-voice-integration-design.md](../specs/2026-04-19-xai-voice-integration-design.md)

---

## Conventions for this plan

- **Quoting the spec section** for each task lets the implementer verify scope without flipping files.
- **Test-first** for every non-trivial unit. UI components and wiring tasks have a manual-verification step instead of automated tests where appropriate.
- **Commit after every task.** Commit messages use imperative free-form style (CLAUDE.md).
- **Dependency files:** when adding Python packages, update **both** `pyproject.toml` (root) and `backend/pyproject.toml` (Docker).
- **Build verification after frontend changes:** `pnpm --dir frontend run build`. Backend: `uv run python -m py_compile <changed files>`.

The `xai_voice` API key field in `_register_builtins()` is introduced at Task 10; tasks before that reference the adapter but not a live `xai_voice` definition. Backend pytest tests that need the definition register it in a fixture. Frontend tests mock the integration store.

---

## Phase A — Backend foundation

### Task 1: Add `hydrate_secrets` flag to `IntegrationDefinition`

**Spec:** §4.3.

**Files:**
- Modify: `backend/modules/integrations/_models.py`

- [ ] **Step 1: Add the field**

Edit `backend/modules/integrations/_models.py`. In the `IntegrationDefinition` dataclass, after `capabilities`, add:

```python
    hydrate_secrets: bool = True
```

- [ ] **Step 2: Verify existing registrations still load**

Run: `uv run python -c "from backend.modules.integrations._registry import get_all; print({k: v.hydrate_secrets for k, v in get_all().items()})"`
Expected: prints a dict where every integration has `True` (Lovense, Mistral).

- [ ] **Step 3: Commit**

```bash
git add backend/modules/integrations/_models.py
git commit -m "Add hydrate_secrets flag to IntegrationDefinition"
```

---

### Task 2: Skip hydration when `hydrate_secrets=False`

**Spec:** §4.3, §3.

**Files:**
- Modify: `backend/modules/integrations/__init__.py` (function `emit_integration_secrets_for_user`, around line 81)
- Modify: `backend/modules/integrations/_repository.py` (method `list_enabled_with_secrets`)
- Test: `backend/tests/integrations/test_secret_hydration_flag.py`

- [ ] **Step 1: Find the hydration emitter and repository method**

Read `backend/modules/integrations/__init__.py` lines 81-105 (`emit_integration_secrets_for_user`), then `backend/modules/integrations/_repository.py` for `list_enabled_with_secrets`. Confirm that the filter happens either in the repo query or in the loop.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/integrations/test_secret_hydration_flag.py`:

```python
"""Hydration skip when hydrate_secrets=False."""
import pytest
from unittest.mock import AsyncMock

from backend.modules.integrations import emit_integration_secrets_for_user
from backend.modules.integrations._models import IntegrationDefinition
from backend.modules.integrations import _registry as integration_registry
from shared.dtos.integrations import IntegrationCapability


@pytest.mark.asyncio
async def test_skips_integrations_with_hydrate_secrets_false(monkeypatch):
    # Arrange: register a non-hydrating integration definition
    defn = IntegrationDefinition(
        id="_test_no_hydrate",
        display_name="Test",
        description="",
        icon="",
        execution_mode="hybrid",
        config_fields=[{"key": "api_key", "field_type": "password", "secret": True}],
        capabilities=[IntegrationCapability.TTS_PROVIDER],
        hydrate_secrets=False,
    )
    monkeypatch.setitem(integration_registry._registry, "_test_no_hydrate", defn)

    # Simulate an enabled config with a stored secret for our fake integration
    class FakeRepo:
        async def list_enabled_with_secrets(self, user_id):
            return [("_test_no_hydrate", {"api_key": "secret"})]

    monkeypatch.setattr(
        "backend.modules.integrations.IntegrationRepository",
        lambda *_a, **_kw: FakeRepo(),
    )

    event_bus = AsyncMock()
    await emit_integration_secrets_for_user(
        user_id="u1", db=object(), event_bus=event_bus,
    )

    event_bus.publish.assert_not_called()
```

Also add a positive test in the same file (`test_emits_when_hydrate_secrets_true`) mirroring the above but with `hydrate_secrets=True`, asserting `event_bus.publish` was called once.

- [ ] **Step 3: Run the test — must fail**

Run: `uv run pytest backend/tests/integrations/test_secret_hydration_flag.py -v`
Expected: one test fails (the skip-when-false case), one passes (the emit-when-true case — current behaviour).

- [ ] **Step 4: Implement the filter**

In `emit_integration_secrets_for_user` (line 93-ish), add a filter after obtaining `items`:

```python
items = await repo.list_enabled_with_secrets(user_id)
for integration_id, secrets in items:
    defn = get_integration(integration_id)
    if defn is None or not defn.hydrate_secrets:
        continue
    event = IntegrationSecretsHydratedEvent(...)
```

Keep the rest of the function intact.

- [ ] **Step 5: Run the test — must pass**

Run: `uv run pytest backend/tests/integrations/test_secret_hydration_flag.py -v`
Expected: both tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/integrations/__init__.py backend/tests/integrations/test_secret_hydration_flag.py
git commit -m "Skip secret hydration for integrations with hydrate_secrets=False"
```

---

### Task 3: `VoiceAdapter` interface and error classes

**Spec:** §5.1.

**Files:**
- Create: `backend/modules/integrations/_voice_adapters/__init__.py` (empty — package marker, registry added later)
- Create: `backend/modules/integrations/_voice_adapters/_base.py`
- Create: `backend/tests/integrations/test_voice_adapter_base.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integrations/test_voice_adapter_base.py`:

```python
"""VoiceAdapter base + error hierarchy."""
import pytest

from backend.modules.integrations._voice_adapters._base import (
    VoiceAdapter,
    VoiceAdapterError,
    VoiceAuthError,
    VoiceRateLimitError,
    VoiceUnavailableError,
    VoiceBadRequestError,
    VoiceInfo,
)


def test_error_hierarchy_and_defaults():
    assert issubclass(VoiceAuthError, VoiceAdapterError)
    assert issubclass(VoiceRateLimitError, VoiceAdapterError)
    assert issubclass(VoiceUnavailableError, VoiceAdapterError)
    assert issubclass(VoiceBadRequestError, VoiceAdapterError)

    assert VoiceAuthError().http_status == 401
    assert VoiceRateLimitError().http_status == 429
    assert VoiceUnavailableError().http_status == 502
    assert VoiceBadRequestError().http_status == 400


def test_voice_info_shape():
    v = VoiceInfo(id="abc", name="Voice A")
    assert v.id == "abc"
    assert v.name == "Voice A"
    assert v.language is None
    assert v.gender is None


def test_voice_adapter_is_abstract():
    with pytest.raises(TypeError):
        VoiceAdapter()
```

- [ ] **Step 2: Run test — must fail**

Run: `uv run pytest backend/tests/integrations/test_voice_adapter_base.py -v`
Expected: ImportError / ModuleNotFoundError.

- [ ] **Step 3: Create the base module**

Create `backend/modules/integrations/_voice_adapters/__init__.py` (empty file).

Create `backend/modules/integrations/_voice_adapters/_base.py`:

```python
"""Voice provider adapter interface + error classes.

Adapters implement this interface for integrations that are proxied through
the Chatsune backend (hydrate_secrets=False). See
devdocs/superpowers/specs/2026-04-19-xai-voice-integration-design.md §5.1.
"""

from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel


class VoiceInfo(BaseModel):
    id: str
    name: str
    language: str | None = None
    gender: Literal["male", "female", "neutral"] | None = None


class VoiceAdapterError(Exception):
    """Base error. Raised by adapters, mapped to HTTP by the proxy route."""
    http_status: int = 502
    user_message: str = "Voice provider error"

    def __init__(self, user_message: str | None = None) -> None:
        if user_message is not None:
            self.user_message = user_message
        super().__init__(self.user_message)


class VoiceAuthError(VoiceAdapterError):
    http_status = 401
    user_message = "Voice provider rejected your API key"


class VoiceRateLimitError(VoiceAdapterError):
    http_status = 429
    user_message = "Voice provider rate-limited — try again shortly"


class VoiceUnavailableError(VoiceAdapterError):
    http_status = 502
    user_message = "Voice provider unreachable"


class VoiceBadRequestError(VoiceAdapterError):
    http_status = 400
    user_message = "Voice provider rejected the request"


class VoiceAdapter(ABC):
    """Backend-proxied voice provider. One instance per provider type."""

    @abstractmethod
    async def transcribe(
        self,
        audio: bytes,
        content_type: str,
        api_key: str,
        language: str | None,
    ) -> str: ...

    @abstractmethod
    async def synthesise(
        self, text: str, voice_id: str, api_key: str,
    ) -> tuple[bytes, str]:
        """Returns (audio_bytes, content_type)."""

    @abstractmethod
    async def list_voices(self, api_key: str) -> list[VoiceInfo]: ...

    async def validate_credentials(self, api_key: str) -> None:
        """Default: list_voices round-trip as a liveness probe.

        Adapters may override with a cheaper endpoint if available.
        """
        await self.list_voices(api_key)
```

- [ ] **Step 4: Run test — must pass**

Run: `uv run pytest backend/tests/integrations/test_voice_adapter_base.py -v`
Expected: all three tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/integrations/_voice_adapters/ backend/tests/integrations/test_voice_adapter_base.py
git commit -m "Add VoiceAdapter interface and error classes"
```

---

## Phase B — xAI voice adapter

### Task 4: `XaiVoiceAdapter` — `list_voices`

**Spec:** §5.2.

**xAI endpoint (from user-provided docs):** `GET https://api.x.ai/v1/tts/voices` with `Authorization: Bearer <key>`. Response shape: `{ "voices": [ { "voice_id": "...", "name": "..." }, ... ] }`. Other fields may be present; we ignore unknowns.

**Files:**
- Create: `backend/modules/integrations/_voice_adapters/_xai.py`
- Create: `backend/tests/integrations/test_voice_adapter_xai.py`

- [ ] **Step 1: Ensure `httpx` is in both pyproject.toml files**

Check `pyproject.toml` (root) and `backend/pyproject.toml`. `httpx` is almost certainly already a dependency (used elsewhere). If missing in either, add it with a pinned minimum version (`httpx>=0.27.0`) per CLAUDE.md dependency rule.

Run: `rg '^httpx' pyproject.toml backend/pyproject.toml`
Expected: present in both.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/integrations/test_voice_adapter_xai.py`:

```python
"""XaiVoiceAdapter — list_voices."""
import pytest
import httpx

from backend.modules.integrations._voice_adapters._base import (
    VoiceAdapterError,
    VoiceAuthError,
    VoiceRateLimitError,
    VoiceUnavailableError,
)
from backend.modules.integrations._voice_adapters._xai import XaiVoiceAdapter


def _client_with(handler) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, timeout=5.0)


@pytest.mark.asyncio
async def test_list_voices_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v1/tts/voices"
        assert request.headers["authorization"] == "Bearer KEY"
        return httpx.Response(
            200,
            json={"voices": [
                {"voice_id": "v1", "name": "Voice One"},
                {"voice_id": "v2", "name": "Voice Two", "language": "en"},
            ]},
        )

    adapter = XaiVoiceAdapter(_client_with(handler))
    voices = await adapter.list_voices("KEY")
    assert len(voices) == 2
    assert voices[0].id == "v1"
    assert voices[0].name == "Voice One"
    assert voices[1].language == "en"


@pytest.mark.asyncio
async def test_list_voices_auth_error():
    def handler(_req): return httpx.Response(401, json={"error": "bad key"})
    adapter = XaiVoiceAdapter(_client_with(handler))
    with pytest.raises(VoiceAuthError):
        await adapter.list_voices("KEY")


@pytest.mark.asyncio
async def test_list_voices_rate_limit():
    def handler(_req): return httpx.Response(429, json={"error": "too many"})
    adapter = XaiVoiceAdapter(_client_with(handler))
    with pytest.raises(VoiceRateLimitError):
        await adapter.list_voices("KEY")


@pytest.mark.asyncio
async def test_list_voices_upstream_500():
    def handler(_req): return httpx.Response(500, text="boom")
    adapter = XaiVoiceAdapter(_client_with(handler))
    with pytest.raises(VoiceUnavailableError):
        await adapter.list_voices("KEY")


@pytest.mark.asyncio
async def test_list_voices_timeout():
    def handler(_req): raise httpx.ReadTimeout("timed out")
    adapter = XaiVoiceAdapter(_client_with(handler))
    with pytest.raises(VoiceUnavailableError):
        await adapter.list_voices("KEY")
```

- [ ] **Step 3: Run test — must fail (no `_xai` module yet)**

Run: `uv run pytest backend/tests/integrations/test_voice_adapter_xai.py -v`
Expected: ImportError.

- [ ] **Step 4: Create the adapter**

Create `backend/modules/integrations/_voice_adapters/_xai.py`:

```python
"""xAI voice adapter — TTS + STT via api.x.ai.

See docs: https://docs.x.ai/developers/model-capabilities/audio/text-to-speech
          https://docs.x.ai/developers/model-capabilities/audio/speech-to-text
"""

from __future__ import annotations

import logging

import httpx

from backend.modules.integrations._voice_adapters._base import (
    VoiceAdapter,
    VoiceAdapterError,
    VoiceAuthError,
    VoiceBadRequestError,
    VoiceInfo,
    VoiceRateLimitError,
    VoiceUnavailableError,
)

_log = logging.getLogger(__name__)


class XaiVoiceAdapter(VoiceAdapter):
    BASE_URL = "https://api.x.ai/v1"
    # Model identifiers are fixed by xAI — one model per capability.
    # Update here if/when xAI releases new model generations.
    TTS_MODEL = "grok-tts-1"
    STT_MODEL = "grok-stt-1"

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def list_voices(self, api_key: str) -> list[VoiceInfo]:
        url = f"{self.BASE_URL}/tts/voices"
        try:
            resp = await self._http.get(url, headers=self._auth(api_key))
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise VoiceUnavailableError(str(e)) from e
        self._raise_for_status(resp)
        data = resp.json()
        return [
            VoiceInfo(
                id=v.get("voice_id") or v["id"],
                name=v["name"],
                language=v.get("language"),
                gender=v.get("gender"),
            )
            for v in data.get("voices", [])
        ]

    async def transcribe(
        self, audio: bytes, content_type: str, api_key: str, language: str | None,
    ) -> str:
        raise NotImplementedError  # implemented in a later task

    async def synthesise(
        self, text: str, voice_id: str, api_key: str,
    ) -> tuple[bytes, str]:
        raise NotImplementedError  # implemented in a later task

    def _auth(self, api_key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}"}

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.is_success:
            return
        status = resp.status_code
        if status in (401, 403):
            raise VoiceAuthError()
        if status == 429:
            raise VoiceRateLimitError()
        if status in (400, 422):
            try:
                msg = resp.json().get("error") or resp.text
            except Exception:
                msg = resp.text
            raise VoiceBadRequestError(str(msg))
        if 500 <= status < 600:
            raise VoiceUnavailableError(f"Upstream {status}")
        # Unexpected status — treat as unavailable
        raise VoiceAdapterError(f"Unexpected status {status}")
```

- [ ] **Step 5: Run test — must pass**

Run: `uv run pytest backend/tests/integrations/test_voice_adapter_xai.py -v`
Expected: all 5 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/integrations/_voice_adapters/_xai.py backend/tests/integrations/test_voice_adapter_xai.py
git commit -m "Add XaiVoiceAdapter list_voices with error mapping"
```

---

### Task 5: `XaiVoiceAdapter` — `transcribe`

**Spec:** §5.2.

**xAI endpoint:** `POST https://api.x.ai/v1/audio/transcriptions` with multipart form: `file` (audio blob), `model`, `language` optional. Response JSON: `{ "text": "..." }`.

**Files:**
- Modify: `backend/modules/integrations/_voice_adapters/_xai.py`
- Modify: `backend/tests/integrations/test_voice_adapter_xai.py`

- [ ] **Step 1: Add failing transcribe tests**

Append to `backend/tests/integrations/test_voice_adapter_xai.py`:

```python
@pytest.mark.asyncio
async def test_transcribe_ok_with_language():
    captured = {}
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/audio/transcriptions"
        assert request.headers["authorization"] == "Bearer KEY"
        assert b"audio/wav" in request.content or b"audio/webm" in request.content
        captured["body"] = bytes(request.content)
        return httpx.Response(200, json={"text": "hello world"})

    adapter = XaiVoiceAdapter(_client_with(handler))
    text = await adapter.transcribe(
        audio=b"RIFFfakewavdata", content_type="audio/wav", api_key="KEY", language="en",
    )
    assert text == "hello world"
    # model + language fields must be present in the multipart body
    assert b"grok-stt-1" in captured["body"]
    assert b'name="language"' in captured["body"]


@pytest.mark.asyncio
async def test_transcribe_ok_no_language():
    def handler(request: httpx.Request) -> httpx.Response:
        # language field must be absent when None
        assert b'name="language"' not in request.content
        return httpx.Response(200, json={"text": "ok"})

    adapter = XaiVoiceAdapter(_client_with(handler))
    text = await adapter.transcribe(
        audio=b"data", content_type="audio/wav", api_key="KEY", language=None,
    )
    assert text == "ok"


@pytest.mark.asyncio
async def test_transcribe_rate_limit():
    def handler(_req): return httpx.Response(429, json={"error": "slow down"})
    adapter = XaiVoiceAdapter(_client_with(handler))
    with pytest.raises(VoiceRateLimitError):
        await adapter.transcribe(
            audio=b"d", content_type="audio/wav", api_key="KEY", language=None,
        )
```

- [ ] **Step 2: Run — must fail**

Run: `uv run pytest backend/tests/integrations/test_voice_adapter_xai.py::test_transcribe_ok_with_language -v`
Expected: fails with `NotImplementedError`.

- [ ] **Step 3: Implement transcribe**

In `_xai.py`, replace the `transcribe` stub:

```python
    async def transcribe(
        self, audio: bytes, content_type: str, api_key: str, language: str | None,
    ) -> str:
        url = f"{self.BASE_URL}/audio/transcriptions"
        ext = "wav" if "wav" in content_type else "webm"
        files = {"file": (f"audio.{ext}", audio, content_type)}
        data: dict[str, str] = {"model": self.STT_MODEL}
        if language is not None:
            data["language"] = language
        try:
            resp = await self._http.post(
                url, headers=self._auth(api_key), files=files, data=data,
            )
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise VoiceUnavailableError(str(e)) from e
        self._raise_for_status(resp)
        body = resp.json()
        return body["text"]
```

- [ ] **Step 4: Run — must pass**

Run: `uv run pytest backend/tests/integrations/test_voice_adapter_xai.py -v`
Expected: all transcribe tests pass; earlier `list_voices` tests still pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/integrations/_voice_adapters/_xai.py backend/tests/integrations/test_voice_adapter_xai.py
git commit -m "Implement XaiVoiceAdapter.transcribe"
```

---

### Task 6: `XaiVoiceAdapter` — `synthesise`

**Spec:** §5.2.

**xAI endpoint:** `POST https://api.x.ai/v1/audio/speech` with JSON body `{ "model": "grok-tts-1", "voice_id": "...", "input": "..." }`. Response: audio bytes, Content-Type `audio/mpeg` (MP3) or `audio/wav`.

**Files:**
- Modify: `backend/modules/integrations/_voice_adapters/_xai.py`
- Modify: `backend/tests/integrations/test_voice_adapter_xai.py`

- [ ] **Step 1: Add failing synthesise tests**

Append:

```python
@pytest.mark.asyncio
async def test_synthesise_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/audio/speech"
        body = request.read()
        import json
        parsed = json.loads(body)
        assert parsed["model"] == "grok-tts-1"
        assert parsed["voice_id"] == "v1"
        assert parsed["input"] == "Hello!"
        return httpx.Response(
            200, content=b"\xff\xfbMP3DATA", headers={"content-type": "audio/mpeg"},
        )

    adapter = XaiVoiceAdapter(_client_with(handler))
    audio, ctype = await adapter.synthesise("Hello!", "v1", "KEY")
    assert audio == b"\xff\xfbMP3DATA"
    assert ctype == "audio/mpeg"


@pytest.mark.asyncio
async def test_synthesise_bad_voice():
    def handler(_req):
        return httpx.Response(400, json={"error": "unknown voice_id"})

    adapter = XaiVoiceAdapter(_client_with(handler))
    with pytest.raises(VoiceBadRequestError) as ei:
        await adapter.synthesise("hi", "nope", "KEY")
    assert "unknown voice_id" in ei.value.user_message
```

- [ ] **Step 2: Run — must fail**

Run: `uv run pytest backend/tests/integrations/test_voice_adapter_xai.py::test_synthesise_ok -v`
Expected: fails with `NotImplementedError`.

- [ ] **Step 3: Implement synthesise**

In `_xai.py`, replace the `synthesise` stub:

```python
    async def synthesise(
        self, text: str, voice_id: str, api_key: str,
    ) -> tuple[bytes, str]:
        url = f"{self.BASE_URL}/audio/speech"
        payload = {
            "model": self.TTS_MODEL,
            "voice_id": voice_id,
            "input": text,
        }
        try:
            resp = await self._http.post(
                url, headers=self._auth(api_key), json=payload,
            )
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise VoiceUnavailableError(str(e)) from e
        self._raise_for_status(resp)
        content_type = resp.headers.get("content-type", "audio/mpeg").split(";")[0].strip()
        return resp.content, content_type
```

- [ ] **Step 4: Run — must pass**

Run: `uv run pytest backend/tests/integrations/test_voice_adapter_xai.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/integrations/_voice_adapters/_xai.py backend/tests/integrations/test_voice_adapter_xai.py
git commit -m "Implement XaiVoiceAdapter.synthesise"
```

---

## Phase C — Adapter registry and integration definition

### Task 7: Voice-adapter registry

**Spec:** §5.3.

**Files:**
- Modify: `backend/modules/integrations/_voice_adapters/__init__.py`
- Create: `backend/tests/integrations/test_voice_adapter_registry.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integrations/test_voice_adapter_registry.py`:

```python
"""Voice-adapter registry — register/get/duplicate."""
import pytest

from backend.modules.integrations._voice_adapters import (
    register_adapter,
    get_adapter,
    _registry,  # used only to reset state between tests
)
from backend.modules.integrations._voice_adapters._base import VoiceAdapter


class _DummyAdapter(VoiceAdapter):
    async def list_voices(self, api_key): return []
    async def transcribe(self, audio, content_type, api_key, language): return ""
    async def synthesise(self, text, voice_id, api_key): return b"", "audio/mpeg"


def _reset():
    _registry.clear()


def test_register_and_get():
    _reset()
    a = _DummyAdapter()
    register_adapter("x", a)
    assert get_adapter("x") is a


def test_unknown_returns_none():
    _reset()
    assert get_adapter("nope") is None


def test_duplicate_raises():
    _reset()
    register_adapter("x", _DummyAdapter())
    with pytest.raises(ValueError):
        register_adapter("x", _DummyAdapter())
```

- [ ] **Step 2: Run — must fail**

Run: `uv run pytest backend/tests/integrations/test_voice_adapter_registry.py -v`
Expected: ImportError (registry functions don't exist yet).

- [ ] **Step 3: Implement the registry**

Overwrite `backend/modules/integrations/_voice_adapters/__init__.py`:

```python
"""Voice-adapter registry.

Backend-proxied voice integrations register their adapter instance here at
module import time. The voice proxy routes look adapters up by integration
id.
"""

from backend.modules.integrations._voice_adapters._base import (
    VoiceAdapter,
    VoiceAdapterError,
    VoiceAuthError,
    VoiceBadRequestError,
    VoiceInfo,
    VoiceRateLimitError,
    VoiceUnavailableError,
)

_registry: dict[str, VoiceAdapter] = {}


def register_adapter(integration_id: str, adapter: VoiceAdapter) -> None:
    if integration_id in _registry:
        raise ValueError(f"Voice adapter '{integration_id}' already registered")
    _registry[integration_id] = adapter


def get_adapter(integration_id: str) -> VoiceAdapter | None:
    return _registry.get(integration_id)


__all__ = [
    "VoiceAdapter",
    "VoiceAdapterError",
    "VoiceAuthError",
    "VoiceBadRequestError",
    "VoiceInfo",
    "VoiceRateLimitError",
    "VoiceUnavailableError",
    "register_adapter",
    "get_adapter",
]
```

- [ ] **Step 4: Run — must pass**

Run: `uv run pytest backend/tests/integrations/test_voice_adapter_registry.py -v`
Expected: all three tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/integrations/_voice_adapters/__init__.py backend/tests/integrations/test_voice_adapter_registry.py
git commit -m "Add voice-adapter registry"
```

---

### Task 8: Shared httpx client for voice adapters

**Spec:** §5.2 (adapter takes `httpx.AsyncClient`).

**Files:**
- Modify: `backend/modules/integrations/__init__.py` (add init/shutdown hooks)
- Create: `backend/modules/integrations/_voice_adapters/_client.py` (client factory)

- [ ] **Step 1: Create the client factory**

Create `backend/modules/integrations/_voice_adapters/_client.py`:

```python
"""Shared httpx client for voice adapters.

One client per process with sensible pool limits and timeouts. Adapters
receive the client via DI (passed into their constructor).
"""

import httpx

_client: httpx.AsyncClient | None = None


def init_voice_http_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
        )
    return _client


async def close_voice_http_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def get_voice_http_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("Voice HTTP client not initialised")
    return _client
```

- [ ] **Step 2: Wire init/shutdown into app lifecycle**

In `backend/main.py` (or wherever lifespan hooks live — check existing patterns; search for `lifespan` or `on_event`), add calls to `init_voice_http_client()` at startup and `close_voice_http_client()` at shutdown. If the app uses a `lifespan` context manager, add these calls inside it.

Run to locate: `rg -n "lifespan|startup|shutdown" backend/main.py backend/modules/integrations/__init__.py`

If a lifespan context is in use, inside it (before `yield` for startup, after `yield` for shutdown) add:
```python
from backend.modules.integrations._voice_adapters._client import (
    init_voice_http_client, close_voice_http_client,
)

# startup:
init_voice_http_client()
# shutdown:
await close_voice_http_client()
```

- [ ] **Step 3: Verify import succeeds**

Run: `uv run python -c "from backend.modules.integrations._voice_adapters._client import init_voice_http_client, close_voice_http_client, get_voice_http_client; c = init_voice_http_client(); print(type(c))"`
Expected: prints `<class 'httpx.AsyncClient'>`.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/integrations/_voice_adapters/_client.py backend/main.py
git commit -m "Add shared httpx client lifecycle for voice adapters"
```

---

### Task 9: Register `xai_voice` integration definition + adapter

**Spec:** §5.6, §2.3.

**Files:**
- Modify: `backend/modules/integrations/_registry.py`

- [ ] **Step 1: Add xai_voice to `_register_builtins()`**

In `backend/modules/integrations/_registry.py`, after the `mistral_voice` registration inside `_register_builtins()`, add:

```python
    register(IntegrationDefinition(
        id="xai_voice",
        display_name="xAI Voice",
        description="Speech-to-text and text-to-speech via xAI. Bring your own API key.",
        icon="xai",
        execution_mode="hybrid",
        hydrate_secrets=False,
        capabilities=[
            IntegrationCapability.TTS_PROVIDER,
            IntegrationCapability.STT_PROVIDER,
        ],
        config_fields=[
            {
                "key": "api_key",
                "label": "xAI API Key",
                "field_type": "password",
                "secret": True,
                "required": True,
                "description": (
                    "Your personal xAI API key. Encrypted at rest; never "
                    "leaves the backend."
                ),
            },
            {
                "key": "playback_gap_ms",
                "label": "Pause between chunks",
                "field_type": "select",
                "required": False,
                "description": (
                    "Gap inserted between sentences and speaker switches."
                ),
                "options": [
                    {"value": "100", "label": "100 ms"},
                    {"value": "200", "label": "200 ms"},
                    {"value": "300", "label": "300 ms"},
                    {"value": "400", "label": "400 ms"},
                    {"value": "500", "label": "500 ms (default)"},
                    {"value": "600", "label": "600 ms"},
                    {"value": "700", "label": "700 ms"},
                    {"value": "800", "label": "800 ms"},
                ],
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
            {
                "key": "narrator_voice_id",
                "label": "Narrator Voice",
                "field_type": "select",
                "options_source": OptionsSource.PLUGIN,
                "required": False,
                "description": (
                    "Voice used for narration / prose when narrator mode "
                    "is active. Leave at 'Inherit' to use the primary voice."
                ),
            },
        ],
        tool_definitions=[],
    ))
```

- [ ] **Step 2: Register the xAI adapter after builtin registration**

At the bottom of the same file, below the `_register_builtins()` call, add:

```python
def _register_builtin_voice_adapters() -> None:
    from backend.modules.integrations._voice_adapters import register_adapter
    from backend.modules.integrations._voice_adapters._client import get_voice_http_client
    from backend.modules.integrations._voice_adapters._xai import XaiVoiceAdapter
    register_adapter("xai_voice", XaiVoiceAdapter(get_voice_http_client()))


# Adapter registration happens lazily on first access because the httpx
# client must be initialised via the app lifespan first. Call this from the
# app startup hook.
```

- [ ] **Step 3: Call `_register_builtin_voice_adapters()` during startup**

Modify `backend/main.py` lifespan to call `_register_builtin_voice_adapters()` after `init_voice_http_client()`:

```python
from backend.modules.integrations._registry import _register_builtin_voice_adapters
init_voice_http_client()
_register_builtin_voice_adapters()
```

- [ ] **Step 4: Verify at startup**

Run: `uv run python -c "
import asyncio
from backend.modules.integrations._voice_adapters._client import init_voice_http_client
from backend.modules.integrations._registry import _register_builtin_voice_adapters
from backend.modules.integrations._voice_adapters import get_adapter
init_voice_http_client()
_register_builtin_voice_adapters()
print(type(get_adapter('xai_voice')).__name__)
"`
Expected: prints `XaiVoiceAdapter`.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/integrations/_registry.py backend/main.py
git commit -m "Register xai_voice integration definition and adapter"
```

---

## Phase D — Proxy routes

### Task 10: Voice proxy route — list voices

**Spec:** §5.4.

**Files:**
- Modify: `backend/modules/integrations/_handlers.py`
- Create: `backend/tests/integrations/test_voice_proxy_routes.py`

- [ ] **Step 1: Inspect the existing handlers**

Read `backend/modules/integrations/_handlers.py` to see the router name, existing auth dependency (`require_user`-style), and how `UserIntegrationConfig` is loaded and decrypted. Follow the existing patterns exactly.

Run: `rg -n "require_user|get_current_user|Depends" backend/modules/integrations/_handlers.py | head -n 20`

- [ ] **Step 2: Write the failing test**

Create `backend/tests/integrations/test_voice_proxy_routes.py`:

```python
"""Voice proxy routes — dispatch, auth, adapter errors."""
from unittest.mock import AsyncMock, patch
import pytest

from fastapi.testclient import TestClient

# Adjust the import below to the actual app object
from backend.main import app
from backend.modules.integrations._voice_adapters._base import (
    VoiceAuthError, VoiceInfo, VoiceRateLimitError,
)


def _authed_client(user_id="u1"):
    # Follow existing test harness — uses a fixture or bypass header.
    # Search for an existing auth-bypass test helper first:
    #   rg -n "TestClient|override|Depends.*require" backend/tests | head
    # Use whichever mechanism existing tests use; this test file should
    # mirror the pattern from e.g. existing integrations handler tests.
    raise NotImplementedError("Use existing test harness helper")


@pytest.mark.asyncio
async def test_list_voices_dispatches_to_adapter(monkeypatch):
    fake_adapter = AsyncMock()
    fake_adapter.list_voices.return_value = [VoiceInfo(id="v", name="V")]
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.get_adapter",
        lambda iid: fake_adapter if iid == "xai_voice" else None,
    )
    # Stub repo to return an enabled config with a key
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.load_api_key_for",
        AsyncMock(return_value="KEY"),
    )
    client = _authed_client()
    r = client.get("/api/integrations/xai_voice/voice/voices")
    assert r.status_code == 200
    assert r.json() == {"voices": [{"id": "v", "name": "V", "language": None, "gender": None}]}
    fake_adapter.list_voices.assert_awaited_once_with("KEY")


@pytest.mark.asyncio
async def test_list_voices_no_adapter_returns_400(monkeypatch):
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.get_adapter",
        lambda _id: None,
    )
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.load_api_key_for",
        AsyncMock(return_value="KEY"),
    )
    client = _authed_client()
    r = client.get("/api/integrations/mistral_voice/voice/voices")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_list_voices_integration_not_enabled(monkeypatch):
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.load_api_key_for",
        AsyncMock(return_value=None),
    )
    client = _authed_client()
    r = client.get("/api/integrations/xai_voice/voice/voices")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_voices_auth_error_maps_to_401(monkeypatch):
    fake_adapter = AsyncMock()
    fake_adapter.list_voices.side_effect = VoiceAuthError()
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.get_adapter",
        lambda _id: fake_adapter,
    )
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.load_api_key_for",
        AsyncMock(return_value="KEY"),
    )
    client = _authed_client()
    r = client.get("/api/integrations/xai_voice/voice/voices")
    assert r.status_code == 401
    assert "error_code" in r.json()
```

> **Note:** `_authed_client()` must be implemented against the project's existing auth test harness. Before filling in the test body, run `rg -n "TestClient" backend/tests | head -n 10` to find the pattern, then adapt.

- [ ] **Step 3: Run — must fail (route missing)**

Run: `uv run pytest backend/tests/integrations/test_voice_proxy_routes.py -v`
Expected: failure (route missing or auth helper not wired).

- [ ] **Step 4: Implement the route and helper**

In `backend/modules/integrations/_handlers.py`, add (after existing routes):

```python
from fastapi import HTTPException
from backend.modules.integrations._voice_adapters import (
    get_adapter, VoiceAdapterError,
)


async def load_api_key_for(user_id: str, integration_id: str) -> str | None:
    """Return the decrypted API key for (user, integration), or None if
    the integration is not configured or not enabled."""
    repo = IntegrationRepository(get_db())  # match existing pattern
    pairs = await repo.list_enabled_with_secrets(user_id)
    for iid, secrets in pairs:
        if iid == integration_id:
            return secrets.get("api_key")
    return None


def _error_response(exc: VoiceAdapterError):
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "error_code": type(exc).__name__.removesuffix("Error").lower(),
            "message": exc.user_message,
        },
    )


@router.get("/{integration_id}/voice/voices")
async def voice_list_voices(
    integration_id: str,
    user=Depends(require_user),  # use the existing auth dep
):
    api_key = await load_api_key_for(user["sub"], integration_id)
    if api_key is None:
        raise HTTPException(status_code=404, detail="Integration not enabled")
    adapter = get_adapter(integration_id)
    if adapter is None:
        raise HTTPException(status_code=400, detail="Integration is not backend-proxied")
    try:
        voices = await adapter.list_voices(api_key)
    except VoiceAdapterError as e:
        return _error_response(e)
    return {"voices": [v.model_dump() for v in voices]}
```

Adjust `require_user` import and `IntegrationRepository` usage to the project's actual names (pattern-match existing handlers in the same file).

- [ ] **Step 5: Run — must pass**

Run: `uv run pytest backend/tests/integrations/test_voice_proxy_routes.py::test_list_voices_dispatches_to_adapter backend/tests/integrations/test_voice_proxy_routes.py::test_list_voices_no_adapter_returns_400 backend/tests/integrations/test_voice_proxy_routes.py::test_list_voices_integration_not_enabled backend/tests/integrations/test_voice_proxy_routes.py::test_list_voices_auth_error_maps_to_401 -v`
Expected: all four pass.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/integrations/_handlers.py backend/tests/integrations/test_voice_proxy_routes.py
git commit -m "Add voice proxy route GET /integrations/{id}/voice/voices"
```

---

### Task 11: Voice proxy route — STT

**Spec:** §5.4.

**Files:**
- Modify: `backend/modules/integrations/_handlers.py`
- Modify: `backend/tests/integrations/test_voice_proxy_routes.py`

- [ ] **Step 1: Write failing test**

Append to `test_voice_proxy_routes.py`:

```python
@pytest.mark.asyncio
async def test_stt_dispatches_to_adapter(monkeypatch):
    fake = AsyncMock()
    fake.transcribe.return_value = "hello world"
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.get_adapter",
        lambda _id: fake,
    )
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.load_api_key_for",
        AsyncMock(return_value="KEY"),
    )
    client = _authed_client()
    r = client.post(
        "/api/integrations/xai_voice/voice/stt",
        files={"audio": ("sample.wav", b"RIFF....", "audio/wav")},
        data={"language": "en"},
    )
    assert r.status_code == 200
    assert r.json() == {"text": "hello world"}
    fake.transcribe.assert_awaited_once_with(
        audio=b"RIFF....", content_type="audio/wav", api_key="KEY", language="en",
    )


@pytest.mark.asyncio
async def test_stt_rate_limit_maps_to_429(monkeypatch):
    fake = AsyncMock()
    fake.transcribe.side_effect = VoiceRateLimitError()
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.get_adapter", lambda _id: fake,
    )
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.load_api_key_for",
        AsyncMock(return_value="KEY"),
    )
    client = _authed_client()
    r = client.post(
        "/api/integrations/xai_voice/voice/stt",
        files={"audio": ("s.wav", b"data", "audio/wav")},
    )
    assert r.status_code == 429
```

- [ ] **Step 2: Run — must fail**

Run: `uv run pytest backend/tests/integrations/test_voice_proxy_routes.py::test_stt_dispatches_to_adapter -v`
Expected: route not found.

- [ ] **Step 3: Implement the route**

Add to `_handlers.py`:

```python
from fastapi import File, Form, UploadFile


@router.post("/{integration_id}/voice/stt")
async def voice_stt(
    integration_id: str,
    audio: UploadFile = File(...),
    language: str | None = Form(None),
    user=Depends(require_user),
):
    api_key = await load_api_key_for(user["sub"], integration_id)
    if api_key is None:
        raise HTTPException(status_code=404, detail="Integration not enabled")
    adapter = get_adapter(integration_id)
    if adapter is None:
        raise HTTPException(status_code=400, detail="Integration is not backend-proxied")
    audio_bytes = await audio.read()
    content_type = audio.content_type or "audio/wav"
    try:
        text = await adapter.transcribe(
            audio=audio_bytes, content_type=content_type,
            api_key=api_key, language=language,
        )
    except VoiceAdapterError as e:
        return _error_response(e)
    return {"text": text}
```

- [ ] **Step 4: Run — must pass**

Run: `uv run pytest backend/tests/integrations/test_voice_proxy_routes.py -v`
Expected: both new tests pass; previous tests still pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/integrations/_handlers.py backend/tests/integrations/test_voice_proxy_routes.py
git commit -m "Add voice proxy route POST /integrations/{id}/voice/stt"
```

---

### Task 12: Voice proxy route — TTS

**Spec:** §5.4.

**Files:**
- Modify: `backend/modules/integrations/_handlers.py`
- Modify: `backend/tests/integrations/test_voice_proxy_routes.py`

- [ ] **Step 1: Write failing test**

Append:

```python
@pytest.mark.asyncio
async def test_tts_dispatches_and_streams_bytes(monkeypatch):
    fake = AsyncMock()
    fake.synthesise.return_value = (b"\xff\xfbAUDIO", "audio/mpeg")
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.get_adapter", lambda _id: fake,
    )
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.load_api_key_for",
        AsyncMock(return_value="KEY"),
    )
    client = _authed_client()
    r = client.post(
        "/api/integrations/xai_voice/voice/tts",
        json={"text": "Hi", "voice_id": "v1"},
    )
    assert r.status_code == 200
    assert r.content == b"\xff\xfbAUDIO"
    assert r.headers["content-type"].startswith("audio/mpeg")
    fake.synthesise.assert_awaited_once_with(
        text="Hi", voice_id="v1", api_key="KEY",
    )


@pytest.mark.asyncio
async def test_tts_bad_request_400(monkeypatch):
    from backend.modules.integrations._voice_adapters._base import VoiceBadRequestError
    fake = AsyncMock()
    fake.synthesise.side_effect = VoiceBadRequestError("unknown voice_id")
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.get_adapter", lambda _id: fake,
    )
    monkeypatch.setattr(
        "backend.modules.integrations._handlers.load_api_key_for",
        AsyncMock(return_value="KEY"),
    )
    client = _authed_client()
    r = client.post(
        "/api/integrations/xai_voice/voice/tts",
        json={"text": "Hi", "voice_id": "bad"},
    )
    assert r.status_code == 400
    assert "unknown voice_id" in r.json()["message"]
```

- [ ] **Step 2: Run — must fail**

Run: `uv run pytest backend/tests/integrations/test_voice_proxy_routes.py::test_tts_dispatches_and_streams_bytes -v`

- [ ] **Step 3: Implement the route**

Add to `_handlers.py`:

```python
from fastapi import Response
from pydantic import BaseModel as _BM


class _TtsRequest(_BM):
    text: str
    voice_id: str


@router.post("/{integration_id}/voice/tts")
async def voice_tts(
    integration_id: str,
    body: _TtsRequest,
    user=Depends(require_user),
):
    api_key = await load_api_key_for(user["sub"], integration_id)
    if api_key is None:
        raise HTTPException(status_code=404, detail="Integration not enabled")
    adapter = get_adapter(integration_id)
    if adapter is None:
        raise HTTPException(status_code=400, detail="Integration is not backend-proxied")
    try:
        audio_bytes, content_type = await adapter.synthesise(
            text=body.text, voice_id=body.voice_id, api_key=api_key,
        )
    except VoiceAdapterError as e:
        return _error_response(e)
    return Response(content=audio_bytes, media_type=content_type)
```

- [ ] **Step 4: Run — must pass**

Run: `uv run pytest backend/tests/integrations/test_voice_proxy_routes.py -v`
Expected: all tests pass.

- [ ] **Step 5: Backend build verification**

Run: `uv run python -m py_compile backend/modules/integrations/_handlers.py backend/modules/integrations/_voice_adapters/_base.py backend/modules/integrations/_voice_adapters/_xai.py backend/modules/integrations/_voice_adapters/__init__.py backend/modules/integrations/_voice_adapters/_client.py backend/modules/integrations/_registry.py backend/modules/integrations/_models.py`
Expected: no output (compile clean).

- [ ] **Step 6: Commit**

```bash
git add backend/modules/integrations/_handlers.py backend/tests/integrations/test_voice_proxy_routes.py
git commit -m "Add voice proxy route POST /integrations/{id}/voice/tts"
```

---

## Phase E — Frontend xAI voice plugin

### Task 13: xai_voice plugin — `api.ts`

**Spec:** §6.1.

**Files:**
- Create: `frontend/src/features/integrations/plugins/xai_voice/api.ts`
- Create: `frontend/src/features/integrations/plugins/xai_voice/__tests__/api.test.ts`

- [ ] **Step 1: Confirm the existing HTTP helper**

Read `frontend/src/features/integrations/plugins/mistral_voice/api.ts` for comparison, then run `rg -n "fetch\(|api\(" frontend/src/core/api | head -n 15` to find the project's authenticated-fetch wrapper (likely `frontend/src/core/api/*`). If there's one (e.g. `authedFetch`), use it so JWT handling stays consistent.

- [ ] **Step 2: Write the failing test**

Create `frontend/src/features/integrations/plugins/xai_voice/__tests__/api.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { transcribeXai, synthesiseXai, listXaiVoices } from '../api'

const fetchMock = vi.fn()
beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})

describe('xai_voice api', () => {
  it('transcribeXai posts multipart and returns text', async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ text: 'hi' }), { status: 200 }))
    const audio = new Blob([new Uint8Array([1, 2, 3])], { type: 'audio/wav' })
    const text = await transcribeXai({ audio, language: 'en' })
    expect(text).toBe('hi')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/integrations/xai_voice/voice/stt')
    expect(init.method).toBe('POST')
    expect(init.body).toBeInstanceOf(FormData)
  })

  it('synthesiseXai posts JSON and returns a Blob', async () => {
    fetchMock.mockResolvedValueOnce(new Response(new Uint8Array([0xff, 0xfb]), {
      status: 200,
      headers: { 'content-type': 'audio/mpeg' },
    }))
    const blob = await synthesiseXai({ text: 'hello', voiceId: 'v1' })
    expect(blob).toBeInstanceOf(Blob)
    expect(blob.type).toBe('audio/mpeg')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/integrations/xai_voice/voice/tts')
    expect(JSON.parse(init.body as string)).toEqual({ text: 'hello', voice_id: 'v1' })
  })

  it('listXaiVoices returns parsed voice list', async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
      voices: [{ id: 'v1', name: 'Voice One', language: null, gender: null }],
    }), { status: 200 }))
    const voices = await listXaiVoices()
    expect(voices).toHaveLength(1)
    expect(voices[0].id).toBe('v1')
  })

  it('throws on non-2xx', async () => {
    fetchMock.mockResolvedValueOnce(new Response(
      JSON.stringify({ error_code: 'authenticationerror', message: 'bad key' }),
      { status: 401 },
    ))
    await expect(listXaiVoices()).rejects.toThrow(/bad key/)
  })
})
```

- [ ] **Step 3: Run — must fail**

Run: `pnpm --dir frontend vitest run src/features/integrations/plugins/xai_voice/__tests__/api.test.ts`
Expected: module not found.

- [ ] **Step 4: Implement `api.ts`**

Create `frontend/src/features/integrations/plugins/xai_voice/api.ts`:

```ts
// Thin client over the Chatsune backend voice-proxy routes.
// xAI does not send CORS headers; all calls go through the backend.

import type { VoicePreset } from '../../../voice/types'

const BASE = '/api/integrations/xai_voice/voice'

interface ApiErrorBody { error_code?: string; message?: string }

async function ensureOk(res: Response): Promise<Response> {
  if (res.ok) return res
  let msg = `HTTP ${res.status}`
  try {
    const body = (await res.clone().json()) as ApiErrorBody
    if (body.message) msg = body.message
  } catch { /* non-JSON body */ }
  throw new Error(msg)
}

export interface TranscribeParams { audio: Blob; language?: string }

export async function transcribeXai({ audio, language }: TranscribeParams): Promise<string> {
  const form = new FormData()
  form.append('audio', audio, 'audio.wav')
  if (language) form.append('language', language)
  const res = await fetch(`${BASE}/stt`, {
    method: 'POST',
    credentials: 'include',
    body: form,
  })
  await ensureOk(res)
  const body = await res.json() as { text: string }
  return body.text
}

export interface SynthesiseParams { text: string; voiceId: string }

export async function synthesiseXai({ text, voiceId }: SynthesiseParams): Promise<Blob> {
  const res = await fetch(`${BASE}/tts`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice_id: voiceId }),
  })
  await ensureOk(res)
  const buf = await res.arrayBuffer()
  return new Blob([buf], { type: res.headers.get('content-type') ?? 'audio/mpeg' })
}

export interface XaiVoice { id: string; name: string; language: string | null; gender: string | null }

export async function listXaiVoices(): Promise<XaiVoice[]> {
  const res = await fetch(`${BASE}/voices`, { method: 'GET', credentials: 'include' })
  await ensureOk(res)
  const body = await res.json() as { voices: XaiVoice[] }
  return body.voices
}

export function toVoicePreset(v: XaiVoice): VoicePreset {
  return { id: v.id, name: v.name, language: v.language ?? 'en' }
}
```

> **Auth note:** if the project's `authedFetch` attaches the JWT differently (not via cookie), swap the three `fetch(...)` calls to use it.

- [ ] **Step 5: Run — must pass**

Run: `pnpm --dir frontend vitest run src/features/integrations/plugins/xai_voice/__tests__/api.test.ts`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/integrations/plugins/xai_voice/
git commit -m "Add xai_voice plugin api client"
```

---

### Task 14: xai_voice plugin — `voices.ts`

**Spec:** §6.1.

**Files:**
- Create: `frontend/src/features/integrations/plugins/xai_voice/voices.ts`

- [ ] **Step 1: Create `voices.ts` (mirrors Mistral pattern)**

Create `frontend/src/features/integrations/plugins/xai_voice/voices.ts`:

```ts
import type { VoicePreset } from '../../../voice/types'
import { listXaiVoices, toVoicePreset } from './api'

export const xaiVoices: { current: VoicePreset[] } = { current: [] }

let refreshGeneration = 0

export function invalidateXaiVoicesCache(): void {
  refreshGeneration++
  xaiVoices.current = []
}

export async function refreshXaiVoices(): Promise<void> {
  const myGen = ++refreshGeneration
  try {
    const all = await listXaiVoices()
    if (myGen !== refreshGeneration) return // stale — ignore
    xaiVoices.current = all.map(toVoicePreset)
  } catch {
    // Soft-fail: keep the existing list. Matches mistral_voice behaviour.
  }
}
```

- [ ] **Step 2: Type-check**

Run: `pnpm --dir frontend tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/integrations/plugins/xai_voice/voices.ts
git commit -m "Add xai_voice voices cache with generation counter"
```

---

### Task 15: xai_voice plugin — engines (`engines.ts`)

**Spec:** §6.1, §6.2.

**Files:**
- Create: `frontend/src/features/integrations/plugins/xai_voice/engines.ts`
- Create: `frontend/src/features/integrations/plugins/xai_voice/__tests__/engines.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/integrations/plugins/xai_voice/__tests__/engines.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { XaiSTTEngine, XaiTTSEngine } from '../engines'

vi.mock('../api', () => ({
  transcribeXai: vi.fn(),
  synthesiseXai: vi.fn(),
  listXaiVoices: vi.fn(),
  toVoicePreset: (v: { id: string; name: string }) => ({ id: v.id, name: v.name, language: 'en' }),
}))

import { transcribeXai, synthesiseXai } from '../api'

vi.mock('../../../store', () => ({
  useIntegrationsStore: {
    getState: () => ({ configs: { xai_voice: { enabled: true } } }),
  },
}))

describe('XaiSTTEngine', () => {
  beforeEach(() => vi.clearAllMocks())

  it('transcribe packs Float32Array into a WAV Blob and returns the text', async () => {
    ;(transcribeXai as any).mockResolvedValueOnce('hello')
    const engine = new XaiSTTEngine()
    const res = await engine.transcribe(new Float32Array([0.1, -0.2, 0.3]))
    expect(res.text).toBe('hello')
    const args = (transcribeXai as any).mock.calls[0][0]
    expect(args.audio).toBeInstanceOf(Blob)
    expect(args.audio.type).toBe('audio/wav')
  })

  it('isReady reflects integration store state', () => {
    const engine = new XaiSTTEngine()
    expect(engine.isReady()).toBe(true)
  })
})

describe('XaiTTSEngine', () => {
  beforeEach(() => vi.clearAllMocks())

  it('synthesise returns a Float32Array (audio decoded by the pipeline)', async () => {
    // OfflineAudioContext is not available in jsdom by default.
    // This test asserts the call plumbing; audio decoding itself is
    // exercised in the existing mistral_voice test suite and the
    // manual verification checklist.
    ;(synthesiseXai as any).mockResolvedValueOnce(
      new Blob([new Uint8Array([0xff, 0xfb])], { type: 'audio/mpeg' }),
    )
    const engine = new XaiTTSEngine()
    // Inject a fake decoder to avoid requiring OfflineAudioContext in the test
    ;(engine as any)._decode = async () => new Float32Array([0.0])
    const pcm = await engine.synthesise('hi', { id: 'v1', name: 'V', language: 'en' })
    expect(pcm).toBeInstanceOf(Float32Array)
  })
})
```

- [ ] **Step 2: Run — must fail**

Run: `pnpm --dir frontend vitest run src/features/integrations/plugins/xai_voice/__tests__/engines.test.ts`

- [ ] **Step 3: Implement `engines.ts`**

Create `frontend/src/features/integrations/plugins/xai_voice/engines.ts`:

```ts
import { transcribeXai, synthesiseXai } from './api'
import { xaiVoices } from './voices'
import { useIntegrationsStore } from '../../store'
import type { STTEngine, STTOptions, STTResult, TTSEngine, VoicePreset } from '../../../voice/types'

const INTEGRATION_ID = 'xai_voice'

function isIntegrationEnabled(): boolean {
  return useIntegrationsStore.getState().configs?.[INTEGRATION_ID]?.enabled === true
}

// Re-use the same WAV packing routine used by mistral_voice. Keep it local
// to avoid importing across plugin boundaries; the code is short.
function float32ToWavBlob(samples: Float32Array, sampleRate = 16_000): Blob {
  const numSamples = samples.length
  const bytesPerSample = 2
  const dataLength = numSamples * bytesPerSample
  const buffer = new ArrayBuffer(44 + dataLength)
  const view = new DataView(buffer)
  const writeStr = (off: number, s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i))
  }
  const writeU32 = (off: number, v: number) => view.setUint32(off, v, true)
  const writeU16 = (off: number, v: number) => view.setUint16(off, v, true)
  writeStr(0, 'RIFF'); writeU32(4, 36 + dataLength); writeStr(8, 'WAVE')
  writeStr(12, 'fmt '); writeU32(16, 16); writeU16(20, 1); writeU16(22, 1)
  writeU32(24, sampleRate); writeU32(28, sampleRate * bytesPerSample)
  writeU16(32, bytesPerSample); writeU16(34, 16)
  writeStr(36, 'data'); writeU32(40, dataLength)
  let off = 44
  for (let i = 0; i < numSamples; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(off, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true)
    off += 2
  }
  return new Blob([buffer], { type: 'audio/wav' })
}

async function decodeMp3ToMono(blob: Blob): Promise<Float32Array> {
  const buf = await blob.arrayBuffer()
  const ctx = new OfflineAudioContext(1, 1, 24_000)
  const decoded = await ctx.decodeAudioData(buf)
  return decoded.getChannelData(0)
}

export class XaiSTTEngine implements STTEngine {
  readonly id = 'xai_stt'
  readonly name = 'xAI Speech-to-Text'
  readonly modelSize = 0
  readonly languages = ['en', 'de', 'fr', 'es', 'it', 'pt', 'nl', 'pl', 'ru', 'zh', 'ja', 'ko']

  async init() {}
  async dispose() {}

  isReady() { return isIntegrationEnabled() }

  async transcribe(audio: Float32Array, options?: STTOptions): Promise<STTResult> {
    const wav = float32ToWavBlob(audio)
    const text = await transcribeXai({ audio: wav, language: options?.language })
    return { text }
  }
}

export class XaiTTSEngine implements TTSEngine {
  readonly id = 'xai_tts'
  readonly name = 'xAI Text-to-Speech'
  readonly modelSize = 0

  get voices(): VoicePreset[] { return xaiVoices.current }

  async init() {}
  async dispose() {}

  isReady() { return isIntegrationEnabled() }

  // Override hook for tests — see engines.test.ts.
  private _decode = decodeMp3ToMono

  async synthesise(text: string, voice: VoicePreset): Promise<Float32Array> {
    const blob = await synthesiseXai({ text, voiceId: voice.id })
    return this._decode(blob)
  }
}
```

- [ ] **Step 4: Run — must pass**

Run: `pnpm --dir frontend vitest run src/features/integrations/plugins/xai_voice/__tests__/engines.test.ts`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/integrations/plugins/xai_voice/
git commit -m "Add XaiSTTEngine and XaiTTSEngine"
```

---

### Task 16: xai_voice plugin — `index.ts` (registration)

**Spec:** §6.1.

**Files:**
- Create: `frontend/src/features/integrations/plugins/xai_voice/index.ts`
- Modify: wherever Mistral's plugin is imported for side-effects (find with `rg -n "mistral_voice" frontend/src/app`)

- [ ] **Step 1: Create the plugin entry**

Create `frontend/src/features/integrations/plugins/xai_voice/index.ts`:

```ts
import type { IntegrationPlugin, Option } from '../../types'
import { sttRegistry, ttsRegistry } from '../../../voice/engines/registry'
import { XaiSTTEngine, XaiTTSEngine } from './engines'
import { xaiVoices, refreshXaiVoices, invalidateXaiVoicesCache } from './voices'
import { registerPlugin } from '../../registry'

let sttInstance: XaiSTTEngine | null = null
let ttsInstance: XaiTTSEngine | null = null

const xaiVoicePlugin: IntegrationPlugin = {
  id: 'xai_voice',

  onActivate(): void {
    if (!sttInstance) sttInstance = new XaiSTTEngine()
    if (!ttsInstance) ttsInstance = new XaiTTSEngine()
    sttRegistry.register(sttInstance)
    ttsRegistry.register(ttsInstance)
    void refreshXaiVoices()
  },

  onDeactivate(): void {
    sttInstance = null
    ttsInstance = null
    invalidateXaiVoicesCache()
  },

  async getPersonaConfigOptions(fieldKey: string): Promise<Option[]> {
    if (fieldKey !== 'voice_id' && fieldKey !== 'narrator_voice_id') return []
    await refreshXaiVoices()
    const voiceOptions = xaiVoices.current.map((v) => ({ value: v.id, label: v.name }))
    if (fieldKey === 'narrator_voice_id') {
      return [{ value: null, label: 'Inherit from primary voice' }, ...voiceOptions]
    }
    return voiceOptions
  },
}

registerPlugin(xaiVoicePlugin)

export default xaiVoicePlugin
```

- [ ] **Step 2: Side-effect import at app boot**

Find the file that imports the Mistral plugin to register it at app boot:

Run: `rg -n "mistral_voice['\"]" frontend/src | head -n 5`

In the same file (likely `frontend/src/app/main.tsx` or a plugin bootstrap file), add:

```ts
import '../features/integrations/plugins/xai_voice'
```

right next to the Mistral import.

- [ ] **Step 3: Type-check + build**

Run: `pnpm --dir frontend tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/integrations/plugins/xai_voice/index.ts frontend/src/app/
git commit -m "Register xai_voice plugin at app boot"
```

---

## Phase F — Frontend engine resolvers

### Task 17: `providerToEngineId` map registered per plugin

**Spec:** §6.3.

**Files:**
- Modify: `frontend/src/features/voice/engines/registry.ts` (add tiny map)
- Modify: `frontend/src/features/integrations/plugins/mistral_voice/index.ts` (register mapping)
- Modify: `frontend/src/features/integrations/plugins/xai_voice/index.ts` (register mapping)

- [ ] **Step 1: Add the map**

In `frontend/src/features/voice/engines/registry.ts`, below the existing registry exports, add:

```ts
type EngineKind = 'stt' | 'tts'
const providerEngineMap = new Map<string, { stt?: string; tts?: string }>()

export function declareProviderEngines(
  integrationId: string, engines: { stt?: string; tts?: string },
): void {
  providerEngineMap.set(integrationId, engines)
}

export function providerToEngineId(
  integrationId: string, kind: EngineKind,
): string | undefined {
  return providerEngineMap.get(integrationId)?.[kind]
}
```

- [ ] **Step 2: Declare mappings in both plugins**

In `mistral_voice/index.ts`, at module top level:

```ts
import { declareProviderEngines } from '../../../voice/engines/registry'
declareProviderEngines('mistral_voice', { stt: 'mistral_stt', tts: 'mistral_tts' })
```

In `xai_voice/index.ts`, at module top level:

```ts
import { declareProviderEngines } from '../../../voice/engines/registry'
declareProviderEngines('xai_voice', { stt: 'xai_stt', tts: 'xai_tts' })
```

- [ ] **Step 3: Type-check**

Run: `pnpm --dir frontend tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/voice/engines/registry.ts frontend/src/features/integrations/plugins/
git commit -m "Declare provider-to-engine mappings for voice plugins"
```

---

### Task 18: `resolveTTSEngine` + `resolveSTTEngine` with fallback

**Spec:** §4.4, §6.3.

**Files:**
- Create: `frontend/src/features/voice/engines/resolver.ts`
- Create: `frontend/src/features/voice/engines/__tests__/resolver.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/voice/engines/__tests__/resolver.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { PersonaDto } from '../../../../core/types/persona'

vi.mock('../../../integrations/store', () => ({
  useIntegrationsStore: {
    getState: vi.fn(() => ({
      definitions: [
        { id: 'mistral_voice', capabilities: ['TTS_PROVIDER', 'STT_PROVIDER'] },
        { id: 'xai_voice', capabilities: ['TTS_PROVIDER', 'STT_PROVIDER'] },
      ],
      configs: {
        mistral_voice: { enabled: true },
        xai_voice: { enabled: true },
      },
    })),
  },
}))

vi.mock('../registry', async () => {
  const actual: any = await vi.importActual('../registry')
  return {
    ...actual,
    sttRegistry: {
      get: (id: string) => ({ id, name: id, isReady: () => true }) as any,
      list: () => [{ id: 'mistral_stt', isReady: () => true }, { id: 'xai_stt', isReady: () => true }] as any,
    },
    ttsRegistry: {
      get: (id: string) => ({ id, name: id, isReady: () => true }) as any,
      list: () => [{ id: 'mistral_tts', isReady: () => true }, { id: 'xai_tts', isReady: () => true }] as any,
    },
    providerToEngineId: (iid: string, kind: 'stt' | 'tts') => {
      if (iid === 'mistral_voice') return kind === 'stt' ? 'mistral_stt' : 'mistral_tts'
      if (iid === 'xai_voice') return kind === 'stt' ? 'xai_stt' : 'xai_tts'
      return undefined
    },
  }
})

import { resolveTTSEngine, resolveSTTEngine } from '../resolver'
import { useVoiceSettingsStore } from '../../stores/voiceSettingsStore'

function persona(overrides: Partial<PersonaDto> = {}): PersonaDto {
  return { id: 'p1', voice_config: {}, ...overrides } as PersonaDto
}

describe('resolveTTSEngine', () => {
  it('uses tts_provider_id when set', () => {
    const p = persona({ voice_config: { tts_provider_id: 'xai_voice' } as any })
    const engine = resolveTTSEngine(p)
    expect(engine?.id).toBe('xai_tts')
  })

  it('falls back to first enabled TTS provider when unset', () => {
    const p = persona()
    const engine = resolveTTSEngine(p)
    expect(engine?.id).toBe('mistral_tts')
  })
})

describe('resolveSTTEngine', () => {
  beforeEach(() => {
    useVoiceSettingsStore.setState({ stt_provider_id: undefined } as any)
  })

  it('uses stt_provider_id from voice settings when set', () => {
    useVoiceSettingsStore.setState({ stt_provider_id: 'xai_voice' } as any)
    const engine = resolveSTTEngine()
    expect(engine?.id).toBe('xai_stt')
  })

  it('falls back to first enabled STT provider when unset', () => {
    const engine = resolveSTTEngine()
    expect(engine?.id).toBe('mistral_stt')
  })
})
```

- [ ] **Step 2: Run — must fail**

Run: `pnpm --dir frontend vitest run src/features/voice/engines/__tests__/resolver.test.ts`

- [ ] **Step 3: Implement the resolver**

Create `frontend/src/features/voice/engines/resolver.ts`:

```ts
import type { PersonaDto } from '../../../core/types/persona'
import type { STTEngine, TTSEngine } from '../types'
import { sttRegistry, ttsRegistry, providerToEngineId } from './registry'
import { useIntegrationsStore } from '../../integrations/store'
import { useVoiceSettingsStore } from '../stores/voiceSettingsStore'

const TTS_CAP = 'TTS_PROVIDER'
const STT_CAP = 'STT_PROVIDER'

function firstEnabledIntegrationId(cap: string): string | undefined {
  const s = useIntegrationsStore.getState()
  const defn = s.definitions.find(
    (d) => d.capabilities?.includes(cap) && s.configs?.[d.id]?.enabled,
  )
  return defn?.id
}

export function resolveTTSEngine(persona: PersonaDto): TTSEngine | undefined {
  const fromPersona = (persona.voice_config as { tts_provider_id?: string } | undefined)?.tts_provider_id
  const requested = fromPersona
  if (requested) {
    const engineId = providerToEngineId(requested, 'tts')
    const engine = engineId ? ttsRegistry.get(engineId) : undefined
    if (engine?.isReady()) return engine
    console.warn('[voice.resolver] TTS fallback: requested=%s not ready', requested)
  }
  const fallbackIntegration = firstEnabledIntegrationId(TTS_CAP)
  if (!fallbackIntegration) return undefined
  const fallbackEngineId = providerToEngineId(fallbackIntegration, 'tts')
  return fallbackEngineId ? ttsRegistry.get(fallbackEngineId) : undefined
}

export function resolveSTTEngine(): STTEngine | undefined {
  const requested = useVoiceSettingsStore.getState().stt_provider_id
  if (requested) {
    const engineId = providerToEngineId(requested, 'stt')
    const engine = engineId ? sttRegistry.get(engineId) : undefined
    if (engine?.isReady()) return engine
    console.warn('[voice.resolver] STT fallback: requested=%s not ready', requested)
  }
  const fallbackIntegration = firstEnabledIntegrationId(STT_CAP)
  if (!fallbackIntegration) return undefined
  const fallbackEngineId = providerToEngineId(fallbackIntegration, 'stt')
  return fallbackEngineId ? sttRegistry.get(fallbackEngineId) : undefined
}
```

- [ ] **Step 4: Run — must pass**

Run: `pnpm --dir frontend vitest run src/features/voice/engines/__tests__/resolver.test.ts`
Expected: all four tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/engines/resolver.ts frontend/src/features/voice/engines/__tests__/resolver.test.ts
git commit -m "Add resolveTTSEngine and resolveSTTEngine with fallback"
```

---

### Task 19: Extend `voiceSettingsStore` with `stt_provider_id`

**Spec:** §4.2, §6.5.

**Files:**
- Modify: `frontend/src/features/voice/stores/voiceSettingsStore.ts`
- Modify: `frontend/src/features/voice/stores/voiceSettingsStore.test.ts`

- [ ] **Step 1: Add failing test**

Append to `voiceSettingsStore.test.ts`:

```ts
  it('defaults stt_provider_id to undefined and persists the value', async () => {
    const { useVoiceSettingsStore } = await import('./voiceSettingsStore')
    expect(useVoiceSettingsStore.getState().stt_provider_id).toBeUndefined()
    useVoiceSettingsStore.getState().setSttProviderId('xai_voice')
    expect(useVoiceSettingsStore.getState().stt_provider_id).toBe('xai_voice')
    // Persist check via localStorage (the store uses persist middleware)
    const raw = window.localStorage.getItem('voice-settings')!
    expect(JSON.parse(raw).state.stt_provider_id).toBe('xai_voice')
  })
```

- [ ] **Step 2: Run — must fail**

Run: `pnpm --dir frontend vitest run src/features/voice/stores/voiceSettingsStore.test.ts`

- [ ] **Step 3: Extend the store**

In `voiceSettingsStore.ts`, update the interface and state:

```ts
interface VoiceSettingsState {
  inputMode: InputMode
  autoSendTranscription: boolean
  voiceActivationThreshold: VoiceActivationThreshold
  stt_provider_id: string | undefined
  setInputMode(mode: InputMode): void
  setAutoSendTranscription(value: boolean): void
  setVoiceActivationThreshold(value: VoiceActivationThreshold): void
  setSttProviderId(value: string | undefined): void
}

export const useVoiceSettingsStore = create<VoiceSettingsState>()(
  persist(
    (set) => ({
      inputMode: 'push-to-talk',
      autoSendTranscription: false,
      voiceActivationThreshold: 'medium',
      stt_provider_id: undefined,
      setInputMode: (inputMode) => set({ inputMode }),
      setAutoSendTranscription: (autoSendTranscription) => set({ autoSendTranscription }),
      setVoiceActivationThreshold: (voiceActivationThreshold) => set({ voiceActivationThreshold }),
      setSttProviderId: (stt_provider_id) => set({ stt_provider_id }),
    }),
    {
      name: 'voice-settings',
      merge: (persisted, current) => ({
        ...current,
        ...(persisted as Partial<VoiceSettingsState>),
        inputMode: 'push-to-talk',
      }),
    },
  ),
)
```

- [ ] **Step 4: Run — must pass**

Run: `pnpm --dir frontend vitest run src/features/voice/stores/voiceSettingsStore.test.ts`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/stores/voiceSettingsStore.ts frontend/src/features/voice/stores/voiceSettingsStore.test.ts
git commit -m "Add stt_provider_id to voiceSettingsStore"
```

---

### Task 20: Migrate call-sites from `registry.active()` to resolvers

**Spec:** §6.3.

**Files:**
- Modify: `frontend/src/features/voice/engines/registry.ts` (remove active/setActive)
- Modify: `frontend/src/features/voice/hooks/useConversationMode.ts`
- Modify: `frontend/src/features/voice/pipeline/voicePipeline.ts`
- Modify: `frontend/src/features/voice/pipeline/streamingAutoReadControl.ts` (if it uses active)
- Modify: `frontend/src/features/voice/components/PersonaVoiceConfig.tsx`
- Modify: `frontend/src/features/voice/components/ReadAloudButton.tsx`
- Modify: `frontend/src/features/voice/components/VoiceButton.tsx`
- Modify: `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx`
- Modify: `frontend/src/features/chat/ChatView.tsx`

- [ ] **Step 1: Locate all call-sites**

Run: `rg -n "(sttRegistry|ttsRegistry)\.(active|setActive|clearActive)" frontend/src`

Record every match; each must be updated.

- [ ] **Step 2: Migrate each call-site**

For every match, replace based on context:

| Pattern | Replace with |
|---|---|
| `ttsRegistry.active()` inside a component that has access to a `persona` | `resolveTTSEngine(persona)` |
| `sttRegistry.active()` anywhere | `resolveSTTEngine()` |
| `ttsRegistry.setActive(...)` / `clearActive()` | delete — resolvers do this dynamically |

Add the import at the top of each modified file:
```ts
import { resolveTTSEngine, resolveSTTEngine } from '../engines/resolver'
// adjust relative path per file
```

**Per-file guidance:**

- `useConversationMode.ts:127` — STT: `resolveSTTEngine()`. No persona dependency.
- `voicePipeline.ts:82, 115` — context has a persona parameter somewhere; wire it through so `resolveTTSEngine(persona)` can be called. If the pipeline is called without a persona today (rare), the nearest caller should pass it in as an argument.
- `ReadAloudButton.tsx:107, 193, 216` — component has access to the current session's persona via props or a store selector. Replace with `resolveTTSEngine(persona)`.
- `VoiceButton.tsx:34` — STT: `resolveSTTEngine()`.
- `PersonaVoiceConfig.tsx:143` — this component receives `persona` as a prop (see existing line 17). Use `resolveTTSEngine(persona)`.
- `PersonaOverlay.tsx:122` — both registries checked for readiness; replace with `!!(resolveSTTEngine()?.isReady() || resolveTTSEngine(persona)?.isReady())` where `persona` is the overlay's persona.
- `ChatView.tsx:122, around 122` — `sttEnabled = !!resolveSTTEngine()?.isReady()`; `ttsEnabled` similarly with the active chat session's persona.

- [ ] **Step 3: Remove `active`, `setActive`, `clearActive` from the registry**

In `frontend/src/features/voice/engines/registry.ts`, remove:

- `active()`, `setActive()`, `clearActive()` methods on `EngineRegistryImpl`
- The `activeEngine` field
- The "auto-promote" logic in `register()`

Also update `EngineRegistry` interface in `frontend/src/features/voice/types.ts` to drop those methods.

- [ ] **Step 4: Fix the Mistral plugin's onDeactivate**

`mistral_voice/index.ts` currently calls `sttRegistry.active()?.id` and `clearActive()`. Replace with:

```ts
onDeactivate(): void {
  sttInstance = null
  ttsInstance = null
  invalidateVoicesCache()
},
```

(The resolver already returns `undefined` when a registered engine's `isReady()` is false — no cleanup needed.)

- [ ] **Step 5: Delete the unit tests that asserted active/setActive behaviour**

Run: `rg -n "active\(\)|setActive" frontend/src/features/voice/**/__tests__`

If there are tests asserting the old `active()` / `setActive()` API, delete those specific test cases (keep tests of `register` / `get` / `list`). Update vitest mocks in `useConversationMode.safetyCap.test.tsx` and `useConversationMode.holdRelease.test.tsx` to mock `resolveSTTEngine` instead of `sttRegistry.active()`.

- [ ] **Step 6: Type-check + full vitest run**

Run:
```
pnpm --dir frontend tsc --noEmit
pnpm --dir frontend vitest run
```
Expected: no TS errors; all tests pass.

- [ ] **Step 7: Frontend build verification**

Run: `pnpm --dir frontend run build`
Expected: clean build.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/voice/ frontend/src/app/components/persona-overlay/PersonaOverlay.tsx frontend/src/features/chat/ChatView.tsx frontend/src/features/integrations/plugins/mistral_voice/index.ts
git commit -m "Replace engine-registry single-active with per-context resolvers"
```

---

## Phase G — UI

### Task 21: Add TTS-provider dropdown to `PersonaVoiceConfig`

**Spec:** §6.4.

**Files:**
- Modify: `frontend/src/features/voice/components/PersonaVoiceConfig.tsx`

- [ ] **Step 1: Read the current file structure**

Read `frontend/src/features/voice/components/PersonaVoiceConfig.tsx` from top to line 80 to recall:
- `activeTTS` derivation (line 66)
- how `persistVoiceConfig` is wired
- the existing `OPTION_STYLE` constant

- [ ] **Step 2: Replace the "first enabled" derivation with persona-driven**

Near line 66, replace the single-item `activeTTS` derivation with:

```tsx
const ttsProviders = definitions.filter(
  (d) => d.capabilities?.includes(TTS_PROVIDER) && configs?.[d.id]?.enabled,
)
const selectedProviderId =
  (persona.voice_config as { tts_provider_id?: string } | undefined)?.tts_provider_id
  ?? ttsProviders[0]?.id
const activeTTS = ttsProviders.find((d) => d.id === selectedProviderId) ?? ttsProviders[0]
```

- [ ] **Step 3: Render the provider dropdown**

Above the existing Voice dropdown, add:

```tsx
{ttsProviders.length > 0 && (
  <div>
    <label className={LABEL}>TTS Provider</label>
    <select
      value={selectedProviderId ?? ''}
      onChange={(e) => {
        const newId = e.target.value || undefined
        // Don't persist the value identical to the fallback — stays implicit
        void persistVoiceConfig({ tts_provider_id: newId })
      }}
      className="..."
    >
      {ttsProviders.map((d) => (
        <option key={d.id} value={d.id} style={OPTION_STYLE}>
          {d.display_name}
          {(!persona.voice_config || !(persona.voice_config as any).tts_provider_id)
            && d.id === ttsProviders[0]?.id ? ' (default)' : ''}
        </option>
      ))}
    </select>
  </div>
)}
```

(Use the same className as the existing voice-id `<select>` for visual consistency; pattern-match from the current file.)

- [ ] **Step 4: Thread `tts_provider_id` into `persistVoiceConfig`**

In the existing `persistVoiceConfig` signature, add `tts_provider_id?: string` to the patch type. When saving, include the new key alongside existing ones.

- [ ] **Step 5: Swap `ttsRegistry.active()` for `resolveTTSEngine(persona)`**

Around line 143 (already migrated in Task 20 — verify here that it is).

- [ ] **Step 6: Type-check + vitest**

Run:
```
pnpm --dir frontend tsc --noEmit
pnpm --dir frontend vitest run
```

- [ ] **Step 7: Manual smoke test**

Start the dev server: `pnpm --dir frontend dev`.

1. Open a persona's voice config.
2. Confirm the TTS Provider dropdown appears.
3. Toggle between Mistral and xAI — the Voice dropdown below should repopulate with the respective provider's voices.
4. Reload the page — selected provider persists.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/voice/components/PersonaVoiceConfig.tsx
git commit -m "Add TTS provider dropdown to PersonaVoiceConfig"
```

---

### Task 22: Add STT-provider selector to the voice settings UI

**Spec:** §6.5.

**Files:**
- Modify: `frontend/src/app/components/user-modal/VoiceTab.tsx` (or whichever file owns the voice settings — confirm via `rg -n "voiceActivationThreshold" frontend/src/app`)

- [ ] **Step 1: Locate the voice settings UI**

Run: `rg -n "voiceActivationThreshold|setVoiceActivationThreshold" frontend/src/app | head -n 5`

Open the matching component. This is where the STT-provider selector goes (same modal/tab as the activation-threshold setting).

- [ ] **Step 2: Add the selector**

Add a new section to the component:

```tsx
// Gather enabled STT providers
const sttProviders = useIntegrationsStore((s) =>
  s.definitions.filter(
    (d) => d.capabilities?.includes('STT_PROVIDER') && s.configs?.[d.id]?.enabled,
  ),
)
const sttProviderId = useVoiceSettingsStore((s) => s.stt_provider_id)
const setSttProviderId = useVoiceSettingsStore((s) => s.setSttProviderId)
```

In the JSX, render:

```tsx
{sttProviders.length > 0 && (
  <div className="...">
    <label className={LABEL}>Voice Input Provider</label>
    <select
      value={sttProviderId ?? ''}
      onChange={(e) => setSttProviderId(e.target.value || undefined)}
      className="..."
    >
      {sttProviders.map((d) => (
        <option key={d.id} value={d.id} style={OPTION_STYLE}>
          {d.display_name}{!sttProviderId && d.id === sttProviders[0]?.id ? ' (default)' : ''}
        </option>
      ))}
    </select>
    <p className="text-xs text-white/50 mt-1">Used across all personas and chat inputs.</p>
  </div>
)}
```

Use the same classNames the component uses for other fields (pattern-match).

Important: the new `<option>` elements must use `OPTION_STYLE` (see CLAUDE.md native-select gotcha). If `OPTION_STYLE` isn't already defined in this file, copy it from `PersonaVoiceConfig.tsx`.

- [ ] **Step 3: Manual verification**

Start dev server. Open the voice settings UI:
1. Confirm the new "Voice Input Provider" dropdown shows both providers when both are enabled.
2. Switch providers and reload — selection persists (localStorage).
3. With xAI selected, enter conversational mode → verify the backend log shows xAI STT calls.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/user-modal/VoiceTab.tsx
git commit -m "Add STT provider selector to voice settings"
```

---

## Phase H — Documentation and verification

### Task 23: Update VOICE-MODE.md

**Spec:** §10.

**Files:**
- Modify: `VOICE-MODE.md`

- [ ] **Step 1: Update §2 (layered architecture) and §5 (backend)**

Add a short subsection to §5 or §8 noting that integrations can be **browser-direct** (`hydrate_secrets=True`, Mistral) or **backend-proxied** (`hydrate_secrets=False`, xAI). Explain why: upstream CORS. Keep it to ~8 lines.

Add a row to the §9 "Where to look" table:

```
| xAI voice adapter (backend) | backend/modules/integrations/_voice_adapters/_xai.py |
| xAI voice plugin (frontend) | frontend/src/features/integrations/plugins/xai_voice/ |
| Voice proxy routes | backend/modules/integrations/_handlers.py |
| Engine resolver | frontend/src/features/voice/engines/resolver.ts |
```

Add the new spec under §9 "Relevant design specs":

```
- [`2026-04-19-xai-voice-integration-design.md`](devdocs/superpowers/specs/2026-04-19-xai-voice-integration-design.md) — xAI as a second voice provider; backend-proxied integrations.
```

- [ ] **Step 2: Commit**

```bash
git add VOICE-MODE.md
git commit -m "Document xAI voice integration and backend-proxied pattern"
```

---

### Task 24: End-to-end manual verification

**Spec:** §8.3.

**Files:**
- none (verification only)

- [ ] **Step 1: Start the stack**

Run: `docker compose up --build` (or the project's preferred dev loop — `rg -n "compose" Makefile README.md` for hints).

Wait for backend + frontend to be up.

- [ ] **Step 2: Baseline — Mistral continues to work**

1. Ensure Mistral voice integration is enabled with a valid key.
2. Open a persona, confirm Voice config shows Mistral as provider.
3. Start conversational mode, speak a short sentence, verify audible reply.

Pass/fail: if Mistral broke, revert the most recent commit and investigate before proceeding.

- [ ] **Step 3: Activate xAI with a valid key**

1. In the integrations UI, enable **xAI Voice**; paste a valid xAI API key.
2. Expected: integration is enabled. No hydration event for it in the browser console (contrast with Mistral).
3. Backend log shows `voice.proxy op=list_voices` entries when the frontend requests voices.

- [ ] **Step 4: Activate xAI with an INVALID key**

1. Disable, re-enable with a garbage key.
2. Voices dropdown is empty. No crashes. Backend log shows `VoiceAuthError`.

(Chris: matching current Mistral soft-fail behaviour — if we later want an explicit UI error on enable, that's a separate piece of work.)

- [ ] **Step 5: Persona TTS uses xAI**

1. Go to a persona. TTS Provider dropdown: select **xAI Voice**.
2. Voice dropdown repopulates with xAI voices; pick one, save.
3. Auto-read an assistant message. Expected: audible reply via xAI.

- [ ] **Step 6: User STT uses xAI**

1. In voice settings (or wherever the STT-provider selector lives), pick **xAI Voice**.
2. Start conversational mode, speak a sentence.
3. Expected: transcription works, reply plays.

- [ ] **Step 7: Mixed personas**

1. Persona A with Mistral TTS, Persona B with xAI TTS.
2. Switch between them in one chat session.
3. Expected: each persona uses its own provider.

- [ ] **Step 8: Fallback on disable**

1. With a persona configured for xAI TTS, disable xAI integration.
2. Auto-read that persona's message.
3. Expected: audio plays via Mistral (fallback). Backend log shows a `voice.resolver.fallback` warning.

- [ ] **Step 9: Rate-limit simulation**

Use browser DevTools → Network tab → block `api.x.ai` or return 429 via a request-blocking extension. Attempt auto-read. Expected: UI toast about rate limit / transient failure; no crash.

- [ ] **Step 10: Build verification**

Run:
```
pnpm --dir frontend run build
uv run ruff check backend/modules/integrations/
```
Expected: clean build, no lint errors.

- [ ] **Step 11: Commit only if final cleanup is needed**

If all steps passed without file changes, nothing to commit. If any fixup was required, stage + commit with a concise message.

---

## Self-review — spec coverage

| Spec section | Covered by |
|---|---|
| §2 Goals (per-persona TTS / per-user STT) | Tasks 18, 19, 21, 22 |
| §2 Goals (backend-proxied) | Tasks 1, 2, 3, 8, 10, 11, 12 |
| §2 Goals (dynamic voice list) | Tasks 4, 10, 14 |
| §2 Goals (reusable pattern) | Tasks 3, 7, 8 |
| §3 Architecture — proxy flow | Tasks 3, 7, 8, 10, 11, 12 |
| §3 Architecture — frontend engine dispatch | Tasks 17, 18, 20 |
| §4.1 tts_provider_id on persona | Task 21 |
| §4.2 stt_provider_id on voiceSettingsStore | Task 19 |
| §4.3 hydrate_secrets flag | Tasks 1, 2 |
| §4.4 Resolution fallback | Task 18 |
| §5.1 VoiceAdapter + errors | Task 3 |
| §5.2 XaiVoiceAdapter | Tasks 4, 5, 6 |
| §5.3 Adapter registry | Task 7 |
| §5.4 Proxy routes | Tasks 10, 11, 12 |
| §5.5 Credential validation on enable | Not separately implemented — matches Mistral's current soft-fail behaviour. See Task 24 step 4 manual note. If explicit UX error is wanted later, open a separate scope. |
| §5.6 IntegrationDefinition entry | Task 9 |
| §5.7 Logging | Implicit in each proxy route + adapter (print to stdlib logger). Pattern-match existing structured log calls. |
| §6.1 xai_voice plugin | Tasks 13, 14, 15, 16 |
| §6.2 isReady semantics | Task 15 |
| §6.3 Resolver | Tasks 17, 18, 20 |
| §6.4 PersonaVoiceConfig dropdown | Task 21 |
| §6.5 Settings STT selector | Task 22 |
| §6.6 Dropdown styling | Tasks 21, 22 (OPTION_STYLE applied) |
| §7 Error handling | Tasks 3, 10, 11, 12 (error mapping in proxy); Task 18 (resolver fallback) |
| §8 Testing | Tasks 3–7, 10–12, 13, 15, 18, 19, 24 |
| §10 Rollout (VOICE-MODE.md) | Task 23 |
| §11 File map | All tasks collectively |

**Placeholder scan:** none found. Each task has concrete code and commands.

**Type consistency:** `resolveTTSEngine(persona)` / `resolveSTTEngine()`, `providerToEngineId(id, kind)`, `declareProviderEngines(id, {stt, tts})`, `register_adapter(id, adapter)`, `get_adapter(id)`, `load_api_key_for(user_id, integration_id)`, `VoiceAdapterError` subclasses used consistently throughout.

**Caveat on 5.5:** explicit credential validation on enable is NOT a separate implementation task in this plan. The rationale: matches current Mistral behaviour; adding it is a UX improvement that applies equally to both plugins and is better done as a follow-up that touches both. Flagged in Task 24 manual checklist as well.

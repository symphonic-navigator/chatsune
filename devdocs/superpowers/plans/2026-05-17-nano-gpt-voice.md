# Nano-GPT Voice (xAI) Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make nano-gpt a TTS and STT provider in Chatsune by adding a backend voice adapter that routes voice calls to xAI through nano-gpt's API, plus a new Integration `nano_gpt_voice_xai` exposing xAI's five voices (Eve, Ara, Leo, Rex, Sal).

**Architecture:** New `VoiceAdapter` subclass at `backend/modules/integrations/_voice_adapters/_nano_gpt_voice_xai.py` mirroring the `XaiVoiceAdapter` pattern but pointing at nano-gpt's OpenAI-compatible voice endpoints with `x-api-key` auth. A new `IntegrationDefinition` `nano_gpt_voice_xai` registers the adapter and surfaces persona/account config (mirroring `xai_voice`). The `nano_gpt` Premium Provider gains `TTS` + `STT` capability badges. A new frontend plugin under `frontend/src/features/integrations/plugins/nano_gpt_voice_xai/` mirrors the `xai_voice` plugin and is wired into the three import sites. A roundtrip smoke test in `backend/llm_harness/` exercises both endpoints against the live API and validates that documented shapes hold.

**Tech Stack:** Python (FastAPI, httpx, pytest), TypeScript (Vite, React, Vitest).

**Spec reference:** `devdocs/superpowers/specs/2026-05-17-nano-gpt-voice-design.md`.

---

## Pre-flight (one-time, before Task 1)

The spec file has two uncommitted patches in the working tree. Bundle them with the Task 1 commit by `git add`ing the spec file along with the Task 1 files. No standalone commit needed.

```bash
git status devdocs/superpowers/specs/2026-05-17-nano-gpt-voice-design.md
# Expect: modified (markup-passthrough confirmation + risk-row downgrade)
```

---

## Task 1: Backend voice adapter — scaffold + `list_voices`

Goal: Adapter class exists, hardcoded voice list returns correctly, test passes.

**Files:**
- Create: `backend/modules/integrations/_voice_adapters/_nano_gpt_voice_xai.py`
- Create: `tests/modules/integrations/test_voice_adapter_nano_gpt_voice_xai.py`

- [ ] **Step 1: Write the failing test**

Create `tests/modules/integrations/test_voice_adapter_nano_gpt_voice_xai.py`:

```python
"""Tests for the nano-gpt voice adapter (xAI backend)."""

from __future__ import annotations

import httpx
import pytest
import respx

from backend.modules.integrations._voice_adapters._base import (
    VoiceAuthError,
    VoiceBadRequestError,
    VoiceUnavailableError,
)
from backend.modules.integrations._voice_adapters._nano_gpt_voice_xai import (
    NanoGptVoiceXaiAdapter,
)


@pytest.fixture
def http_client():
    return httpx.AsyncClient(timeout=30.0)


@pytest.fixture
def adapter(http_client: httpx.AsyncClient) -> NanoGptVoiceXaiAdapter:
    return NanoGptVoiceXaiAdapter(http_client)


@pytest.mark.asyncio
async def test_list_voices_returns_hardcoded_five(adapter: NanoGptVoiceXaiAdapter) -> None:
    voices = await adapter.list_voices(api_key="ignored")
    names = [v.name for v in voices]
    assert names == ["Eve", "Ara", "Leo", "Rex", "Sal"]
    ids = [v.id for v in voices]
    assert ids == ["Eve", "Ara", "Leo", "Rex", "Sal"]
    # Best-guess gender hints
    by_name = {v.name: v.gender for v in voices}
    assert by_name["Eve"] == "female"
    assert by_name["Leo"] == "male"
    assert by_name["Sal"] == "neutral"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/chris/workspace/chatsune
uv run pytest tests/modules/integrations/test_voice_adapter_nano_gpt_voice_xai.py::test_list_voices_returns_hardcoded_five -v
```

Expected: `ModuleNotFoundError: No module named '...._nano_gpt_voice_xai'`.

- [ ] **Step 3: Create the adapter with hardcoded voice list**

Create `backend/modules/integrations/_voice_adapters/_nano_gpt_voice_xai.py`:

```python
"""nano-gpt voice adapter — routes xAI TTS/STT through nano-gpt.

See devdocs/superpowers/specs/2026-05-17-nano-gpt-voice-design.md.

nano-gpt exposes OpenAI-compatible voice endpoints at
``/v1/audio/speech`` (TTS) and ``/v1/audio/transcriptions`` (STT) and
authenticates them via an ``x-api-key`` header (NOT the ``Authorization:
Bearer`` header used by the LLM endpoints).

The xAI voice model slugs are nano-gpt internal identifiers and aren't in
nano-gpt's public docs as of 2026-05-17; the values here are confirmed
working by nano-gpt's owners.
"""

from __future__ import annotations

import logging

import httpx

from backend.database import get_db
from backend.modules.integrations._voice_adapters._base import (
    VoiceAdapter,
    VoiceAdapterError,
    VoiceAuthError,
    VoiceBadRequestError,
    VoiceInfo,
    VoiceRateLimitError,
    VoiceUnavailableError,
    log_upstream_failure,
)

_log = logging.getLogger(__name__)

# Hardcoded — nano-gpt does not expose an xAI voice list endpoint. Keep
# this list in lock-step with the mirror at
# frontend/src/features/integrations/plugins/nano_gpt_voice_xai/voices.ts.
_VOICES: list[VoiceInfo] = [
    VoiceInfo(id="Eve", name="Eve", gender="female"),
    VoiceInfo(id="Ara", name="Ara", gender="female"),
    VoiceInfo(id="Leo", name="Leo", gender="male"),
    VoiceInfo(id="Rex", name="Rex", gender="male"),
    VoiceInfo(id="Sal", name="Sal", gender="neutral"),
]


class NanoGptVoiceXaiAdapter(VoiceAdapter):
    BASE_URL = "https://nano-gpt.com/api/v1"
    TTS_MODEL = "xai-tts"
    STT_MODEL = "xai/speech-to-text/v1"

    # Premium Provider Account slug that carries this adapter's API key.
    PREMIUM_PROVIDER_ID = "nano_gpt"

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def list_voices(self, api_key: str) -> list[VoiceInfo]:
        # api_key is unused — voice list is hardcoded. We still accept
        # the parameter so the VoiceAdapter contract is honoured.
        return list(_VOICES)

    async def synthesise(
        self, text: str, voice_id: str, api_key: str,
    ) -> tuple[bytes, str]:
        raise NotImplementedError  # Task 2

    async def transcribe(
        self, audio: bytes, content_type: str, api_key: str, language: str | None,
    ) -> str:
        raise NotImplementedError  # Task 3

    async def validate_credentials(self, api_key: str) -> None:
        # Cheap probe — reuse nano-gpt's models endpoint that the Premium
        # Provider already hits during account setup.
        url = "https://nano-gpt.com/api/personalized/v1/models"
        try:
            resp = await self._http.get(url, headers=self._auth(api_key))
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise VoiceUnavailableError(str(e)) from e
        self._raise_for_status(
            resp, operation="validate_credentials", request_context={"url": url},
        )

    def _auth(self, api_key: str) -> dict[str, str]:
        return {"x-api-key": api_key}

    def _raise_for_status(
        self,
        resp: httpx.Response,
        *,
        operation: str | None = None,
        request_context: dict | None = None,
    ) -> None:
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
            log_upstream_failure(
                _log, "nano_gpt_voice_xai", operation or "unknown",
                resp, request_context or {},
            )
            raise VoiceUnavailableError(f"Upstream {status}")
        raise VoiceAdapterError(f"Unexpected status {status}")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/modules/integrations/test_voice_adapter_nano_gpt_voice_xai.py::test_list_voices_returns_hardcoded_five -v
```

Expected: PASS.

- [ ] **Step 5: Compile check**

```bash
uv run python -m py_compile backend/modules/integrations/_voice_adapters/_nano_gpt_voice_xai.py
```

Expected: silent success.

- [ ] **Step 6: Commit (bundles uncommitted spec patches)**

```bash
git add devdocs/superpowers/specs/2026-05-17-nano-gpt-voice-design.md
git add devdocs/superpowers/plans/2026-05-17-nano-gpt-voice.md
git add backend/modules/integrations/_voice_adapters/_nano_gpt_voice_xai.py
git add tests/modules/integrations/test_voice_adapter_nano_gpt_voice_xai.py
git commit -m "$(cat <<'EOF'
Add nano-gpt voice adapter scaffold with hardcoded xAI voices

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Voice adapter — `synthesise` (TTS)

Goal: TTS call POSTs to nano-gpt with the correct body and returns audio bytes; the test uses `respx` to verify the request shape.

**Files:**
- Modify: `backend/modules/integrations/_voice_adapters/_nano_gpt_voice_xai.py`
- Modify: `tests/modules/integrations/test_voice_adapter_nano_gpt_voice_xai.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/modules/integrations/test_voice_adapter_nano_gpt_voice_xai.py`:

```python
@pytest.mark.asyncio
@respx.mock
async def test_synthesise_posts_expected_body_and_returns_audio(
    adapter: NanoGptVoiceXaiAdapter,
) -> None:
    route = respx.post("https://nano-gpt.com/api/v1/audio/speech").mock(
        return_value=httpx.Response(
            200,
            content=b"\x00\x01\x02FAKE_MP3",
            headers={"content-type": "audio/mpeg"},
        ),
    )
    audio, ctype = await adapter.synthesise(
        text="Hello there.", voice_id="Eve", api_key="key-123",
    )
    assert audio == b"\x00\x01\x02FAKE_MP3"
    assert ctype == "audio/mpeg"
    assert route.called
    req = route.calls.last.request
    assert req.headers["x-api-key"] == "key-123"
    import json
    body = json.loads(req.content)
    assert body == {"model": "xai-tts", "voice": "Eve", "input": "Hello there."}


@pytest.mark.asyncio
@respx.mock
async def test_synthesise_maps_401_to_voice_auth_error(
    adapter: NanoGptVoiceXaiAdapter,
) -> None:
    respx.post("https://nano-gpt.com/api/v1/audio/speech").mock(
        return_value=httpx.Response(401, json={"error": "bad key"}),
    )
    with pytest.raises(VoiceAuthError):
        await adapter.synthesise(text="hi", voice_id="Eve", api_key="bad")
```

- [ ] **Step 2: Run tests to verify both fail**

```bash
uv run pytest tests/modules/integrations/test_voice_adapter_nano_gpt_voice_xai.py -v
```

Expected: the new two FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement `synthesise`**

Replace the placeholder `synthesise` body in `backend/modules/integrations/_voice_adapters/_nano_gpt_voice_xai.py`:

```python
    async def synthesise(
        self, text: str, voice_id: str, api_key: str,
    ) -> tuple[bytes, str]:
        url = f"{self.BASE_URL}/audio/speech"
        payload = {
            "model": self.TTS_MODEL,
            "voice": voice_id,
            "input": text,
        }
        try:
            resp = await self._http.post(
                url, headers=self._auth(api_key), json=payload,
            )
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise VoiceUnavailableError(str(e)) from e
        self._raise_for_status(
            resp,
            operation="synthesise",
            request_context={
                "url": url,
                "text_len": len(text),
                "voice_id": voice_id,
                "model": self.TTS_MODEL,
            },
        )
        content_type = resp.headers.get("content-type", "audio/mpeg").split(";")[0].strip()
        return resp.content, content_type
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/modules/integrations/test_voice_adapter_nano_gpt_voice_xai.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/integrations/_voice_adapters/_nano_gpt_voice_xai.py \
        tests/modules/integrations/test_voice_adapter_nano_gpt_voice_xai.py
git commit -m "$(cat <<'EOF'
Implement nano-gpt voice adapter synthesise (xAI TTS)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Voice adapter — `transcribe` (STT)

Goal: STT call sends multipart with `file` field, `model` and optional `language`; response `text` is extracted; tests cover both happy path and 400.

**Files:**
- Modify: `backend/modules/integrations/_voice_adapters/_nano_gpt_voice_xai.py`
- Modify: `tests/modules/integrations/test_voice_adapter_nano_gpt_voice_xai.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/modules/integrations/test_voice_adapter_nano_gpt_voice_xai.py`:

```python
@pytest.mark.asyncio
@respx.mock
async def test_transcribe_posts_multipart_and_extracts_text(
    adapter: NanoGptVoiceXaiAdapter,
) -> None:
    route = respx.post(
        "https://nano-gpt.com/api/v1/audio/transcriptions",
    ).mock(return_value=httpx.Response(
        200, json={"text": "Hello there."},
    ))
    text = await adapter.transcribe(
        audio=b"FAKE_WAV_BYTES",
        content_type="audio/wav",
        api_key="key-123",
        language="en",
    )
    assert text == "Hello there."
    assert route.called
    req = route.calls.last.request
    assert req.headers["x-api-key"] == "key-123"
    # respx exposes content as bytes; check our key field names are in the
    # multipart payload.
    body = req.content.decode("utf-8", errors="replace")
    assert "name=\"file\"" in body
    assert "name=\"model\"" in body
    assert "xai/speech-to-text/v1" in body
    assert "name=\"language\"" in body
    assert "en" in body


@pytest.mark.asyncio
@respx.mock
async def test_transcribe_without_language_omits_field(
    adapter: NanoGptVoiceXaiAdapter,
) -> None:
    route = respx.post(
        "https://nano-gpt.com/api/v1/audio/transcriptions",
    ).mock(return_value=httpx.Response(200, json={"text": "ok"}))
    await adapter.transcribe(
        audio=b"x", content_type="audio/wav", api_key="k", language=None,
    )
    body = route.calls.last.request.content.decode("utf-8", errors="replace")
    assert "name=\"language\"" not in body


@pytest.mark.asyncio
@respx.mock
async def test_transcribe_maps_400_to_voice_bad_request(
    adapter: NanoGptVoiceXaiAdapter,
) -> None:
    respx.post("https://nano-gpt.com/api/v1/audio/transcriptions").mock(
        return_value=httpx.Response(400, json={"error": "bad audio"}),
    )
    with pytest.raises(VoiceBadRequestError):
        await adapter.transcribe(
            audio=b"x", content_type="audio/wav", api_key="k", language=None,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/modules/integrations/test_voice_adapter_nano_gpt_voice_xai.py -v
```

Expected: three new FAILs (`NotImplementedError`).

- [ ] **Step 3: Implement `transcribe`**

Replace the placeholder `transcribe` body in `backend/modules/integrations/_voice_adapters/_nano_gpt_voice_xai.py`:

```python
    async def transcribe(
        self, audio: bytes, content_type: str, api_key: str, language: str | None,
    ) -> str:
        url = f"{self.BASE_URL}/audio/transcriptions"
        # nano-gpt's OpenAI-compatible endpoint expects the standard
        # Whisper-style ``file`` multipart field plus ``model``.
        ext = "wav" if "wav" in content_type else "webm"
        files = {"file": (f"audio.{ext}", audio, content_type)}
        data: dict[str, str] = {"model": self.STT_MODEL}
        if language:
            data["language"] = language
        try:
            resp = await self._http.post(
                url, headers=self._auth(api_key), files=files, data=data,
            )
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise VoiceUnavailableError(str(e)) from e
        self._raise_for_status(
            resp,
            operation="transcribe",
            request_context={
                "url": url,
                "audio_bytes": len(audio),
                "content_type": content_type,
                "language": language,
                "model": self.STT_MODEL,
            },
        )
        body = resp.json()
        return body["text"]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/modules/integrations/test_voice_adapter_nano_gpt_voice_xai.py -v
```

Expected: all six tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/integrations/_voice_adapters/_nano_gpt_voice_xai.py \
        tests/modules/integrations/test_voice_adapter_nano_gpt_voice_xai.py
git commit -m "$(cat <<'EOF'
Implement nano-gpt voice adapter transcribe (xAI STT)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Register the adapter and add the IntegrationDefinition

Goal: The new integration is discoverable, its adapter is wired up at startup, and the `nano_gpt` Premium Provider now advertises `TTS` and `STT`.

**Files:**
- Modify: `backend/modules/integrations/_registry.py`
- Modify: `backend/modules/providers/_registry.py`

- [ ] **Step 1: Add the IntegrationDefinition**

Open `backend/modules/integrations/_registry.py`. Locate the `xai_voice` registration (currently around lines 223-283). Immediately after the `xai_voice` `register(...)` block, add the following block (inside the same function — same indentation as the existing `register(IntegrationDefinition(...))` calls):

```python
    register(IntegrationDefinition(
        id="nano_gpt_voice_xai",
        display_name="xAI Voice via nano-gpt",
        description=(
            "Speech-to-text and text-to-speech via xAI, routed through "
            "nano-gpt. Uses the nano-gpt account's API key — no separate "
            "xAI account required."
        ),
        icon="nano_gpt",
        execution_mode="hybrid",
        hydrate_secrets=False,
        system_prompt_template=build_system_prompt_extension(),
        capabilities=[
            IntegrationCapability.TTS_PROVIDER,
            IntegrationCapability.STT_PROVIDER,
            IntegrationCapability.TTS_EXPRESSIVE_MARKUP,
        ],
        linked_premium_provider="nano_gpt",
        config_fields=[
            {
                "key": "playback_gap_ms",
                "label": "Pause between chunks",
                "field_type": "select",
                "required": False,
                "description": (
                    "Gap inserted between sentences and speaker switches. "
                    "xAI already leaves a natural silence at sentence ends, "
                    "so no extra gap is needed by default."
                ),
                "options": [
                    {"value": "0",   "label": "0 ms (default)"},
                    {"value": "100", "label": "100 ms"},
                    {"value": "200", "label": "200 ms"},
                    {"value": "300", "label": "300 ms"},
                    {"value": "400", "label": "400 ms"},
                    {"value": "500", "label": "500 ms"},
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

- [ ] **Step 2: Register the adapter at startup**

In the same file, locate `_register_builtin_voice_adapters()` (around line 304). Add the import and the `register_adapter(...)` call alongside the existing two:

```python
def _register_builtin_voice_adapters() -> None:
    """Register voice adapters for backend-proxied integrations.

    Must be called AFTER the voice HTTP client is initialised (see
    backend/modules/integrations/_voice_adapters/_client.py).
    """
    from backend.modules.integrations._voice_adapters import register_adapter
    from backend.modules.integrations._voice_adapters._client import get_voice_http_client
    from backend.modules.integrations._voice_adapters._mistral import MistralVoiceAdapter
    from backend.modules.integrations._voice_adapters._nano_gpt_voice_xai import (
        NanoGptVoiceXaiAdapter,
    )
    from backend.modules.integrations._voice_adapters._xai import XaiVoiceAdapter
    register_adapter("xai_voice", XaiVoiceAdapter(get_voice_http_client()))
    register_adapter("mistral_voice", MistralVoiceAdapter(get_voice_http_client()))
    register_adapter(
        "nano_gpt_voice_xai",
        NanoGptVoiceXaiAdapter(get_voice_http_client()),
    )
```

- [ ] **Step 3: Extend the Premium Provider capabilities**

Open `backend/modules/providers/_registry.py`. Around line 117, the `nano_gpt` block has:

```python
capabilities=[Capability.LLM, Capability.TTI],
```

Replace with:

```python
capabilities=[Capability.LLM, Capability.TTI, Capability.TTS, Capability.STT],
```

- [ ] **Step 4: Compile check both files**

```bash
uv run python -m py_compile \
  backend/modules/integrations/_registry.py \
  backend/modules/providers/_registry.py
```

Expected: silent success.

- [ ] **Step 5: Run the adapter test suite to make sure imports still resolve**

```bash
uv run pytest tests/modules/integrations/test_voice_adapter_nano_gpt_voice_xai.py -v
uv run pytest tests/modules/integrations/test_voice_adapter_xai.py -v
```

Expected: all PASS — the xai voice adapter tests still pass (no regression).

- [ ] **Step 6: Commit**

```bash
git add backend/modules/integrations/_registry.py \
        backend/modules/providers/_registry.py
git commit -m "$(cat <<'EOF'
Register nano_gpt_voice_xai integration and expose nano-gpt TTS/STT

Adds the IntegrationDefinition, wires up the adapter at startup, and
flags the nano-gpt Premium Provider as TTS+STT capable so the badges
surface in the account UI.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Frontend plugin — scaffold (api.ts, voices.ts)

Goal: The new plugin directory exists with the HTTP client wrapper and the voice-list module. Plugin still doesn't register engines yet (Task 6).

**Files:**
- Create: `frontend/src/features/integrations/plugins/nano_gpt_voice_xai/api.ts`
- Create: `frontend/src/features/integrations/plugins/nano_gpt_voice_xai/voices.ts`

- [ ] **Step 1: Create `api.ts`**

Create `frontend/src/features/integrations/plugins/nano_gpt_voice_xai/api.ts`:

```typescript
// Thin client over the Chatsune backend voice-proxy routes for nano-gpt
// (xAI backend). nano-gpt does not send CORS headers; all calls go
// through the backend.

import type { VoicePreset } from '../../../voice/types'
import { apiUrl, currentAccessToken } from '../../../../core/api/client'

const BASE = '/api/integrations/nano_gpt_voice_xai/voice'

interface ApiErrorBody { error_code?: string; message?: string }

function authHeaders(): Record<string, string> {
  const token = currentAccessToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function ensureOk(res: Response): Promise<Response> {
  if (res.ok) return res
  let msg = `HTTP ${res.status}`
  try {
    const body = (await res.clone().json()) as ApiErrorBody
    if (body.message) msg = body.message
  } catch { /* non-JSON body */ }
  throw new Error(msg)
}

function filenameForMime(mimeType: string): string {
  if (mimeType.startsWith('audio/webm')) return 'audio.webm'
  if (mimeType.startsWith('audio/mp4')) return 'audio.m4a'
  return 'audio.wav'
}

export interface TranscribeParams { audio: Blob; mimeType: string; language?: string }

export async function transcribeNanoGptXai(
  { audio, mimeType, language }: TranscribeParams,
): Promise<string> {
  const form = new FormData()
  const file = new File([audio], filenameForMime(mimeType), { type: mimeType })
  form.append('audio', file, file.name)
  if (language) form.append('language', language)
  const res = await fetch(apiUrl(`${BASE}/stt`), {
    method: 'POST',
    credentials: 'include',
    headers: authHeaders(),
    body: form,
  })
  await ensureOk(res)
  const body = (await res.json()) as { text: string }
  return body.text
}

export interface SynthesiseParams { text: string; voiceId: string }

export async function synthesiseNanoGptXai(
  { text, voiceId }: SynthesiseParams,
): Promise<Blob> {
  const res = await fetch(apiUrl(`${BASE}/tts`), {
    method: 'POST',
    credentials: 'include',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice_id: voiceId }),
  })
  await ensureOk(res)
  const buf = await res.arrayBuffer()
  return new Blob([buf], { type: res.headers.get('content-type') ?? 'audio/mpeg' })
}

export interface NanoGptXaiVoice {
  id: string
  name: string
  language: string | null
  gender: string | null
}

export async function listNanoGptXaiVoices(): Promise<NanoGptXaiVoice[]> {
  const res = await fetch(apiUrl(`${BASE}/voices`), {
    method: 'GET',
    credentials: 'include',
    headers: authHeaders(),
  })
  await ensureOk(res)
  const body = (await res.json()) as { voices: NanoGptXaiVoice[] }
  return body.voices
}

export function toVoicePreset(v: NanoGptXaiVoice): VoicePreset {
  return { id: v.id, name: v.name, language: v.language ?? 'en' }
}
```

- [ ] **Step 2: Create `voices.ts`**

Create `frontend/src/features/integrations/plugins/nano_gpt_voice_xai/voices.ts`:

```typescript
import type { VoicePreset } from '../../../voice/types'
import { listNanoGptXaiVoices, toVoicePreset } from './api'

export const nanoGptXaiVoices: { current: VoicePreset[] } = { current: [] }

let inflight: Promise<void> | null = null
let currentGeneration = 0

export function invalidateNanoGptXaiVoicesCache(): void {
  currentGeneration++
  inflight = null
  nanoGptXaiVoices.current = []
}

export function refreshNanoGptXaiVoices(): Promise<void> {
  if (inflight) return inflight
  const gen = ++currentGeneration
  inflight = (async () => {
    try {
      const all = await listNanoGptXaiVoices()
      if (gen !== currentGeneration) return
      nanoGptXaiVoices.current = all.map(toVoicePreset)
    } catch {
      // Soft-fail: keep the existing list.
    } finally {
      inflight = null
    }
  })()
  return inflight
}
```

- [ ] **Step 3: Type-check**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm tsc --noEmit
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/integrations/plugins/nano_gpt_voice_xai/api.ts \
        frontend/src/features/integrations/plugins/nano_gpt_voice_xai/voices.ts
git commit -m "$(cat <<'EOF'
Add nano-gpt voice plugin api+voices modules

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Frontend plugin — engines + index, wire imports

Goal: Plugin registers itself, exposes TTS and STT engines, and is loaded at the three known import sites. STT picker and persona TTS picker pick up "xAI Voice via nano-gpt" automatically.

**Files:**
- Create: `frontend/src/features/integrations/plugins/nano_gpt_voice_xai/engines.ts`
- Create: `frontend/src/features/integrations/plugins/nano_gpt_voice_xai/index.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/app/components/persona-overlay/IntegrationsTab.tsx`
- Modify: `frontend/src/app/components/user-modal/IntegrationsTab.tsx`

- [ ] **Step 1: Create `engines.ts`**

Create `frontend/src/features/integrations/plugins/nano_gpt_voice_xai/engines.ts`:

```typescript
import { transcribeNanoGptXai, synthesiseNanoGptXai } from './api'
import { nanoGptXaiVoices } from './voices'
import { useIntegrationsStore } from '../../store'
import type {
  CapturedAudio,
  STTEngine,
  STTOptions,
  STTResult,
  TTSEngine,
  VoicePreset,
} from '../../../voice/types'

const INTEGRATION_ID = 'nano_gpt_voice_xai'

function isIntegrationEnabled(): boolean {
  return useIntegrationsStore.getState().configs?.[INTEGRATION_ID]
    ?.effective_enabled === true
}

async function decodeAudioToMono(blob: Blob): Promise<Float32Array> {
  const buf = await blob.arrayBuffer()
  const ctx = new OfflineAudioContext(1, 1, 24_000)
  const decoded = await ctx.decodeAudioData(buf)
  return decoded.getChannelData(0)
}

export class NanoGptXaiSTTEngine implements STTEngine {
  readonly id = 'nano_gpt_voice_xai_stt'
  readonly name = 'xAI Speech-to-Text via nano-gpt'
  readonly modelSize = 0
  readonly languages = [
    'en', 'de', 'fr', 'es', 'it', 'pt', 'nl', 'pl', 'ru', 'zh', 'ja', 'ko',
  ]

  async init() {}
  async dispose() {}

  isReady() { return isIntegrationEnabled() }

  async transcribe(audio: CapturedAudio, options?: STTOptions): Promise<STTResult> {
    const text = await transcribeNanoGptXai({
      audio: audio.blob,
      mimeType: audio.mimeType,
      language: options?.language,
    })
    return { text }
  }
}

export class NanoGptXaiTTSEngine implements TTSEngine {
  readonly id = 'nano_gpt_voice_xai_tts'
  readonly name = 'xAI Text-to-Speech via nano-gpt'
  readonly modelSize = 0

  get voices(): VoicePreset[] { return nanoGptXaiVoices.current }

  async init() {}
  async dispose() {}

  isReady() { return isIntegrationEnabled() }

  // Override hook for tests (OfflineAudioContext is not available in jsdom).
  private _decode = decodeAudioToMono

  async synthesise(_text: string, _voice: VoicePreset): Promise<Float32Array> {
    const blob = await synthesiseNanoGptXai({ text: _text, voiceId: _voice.id })
    return this._decode(blob)
  }
}
```

- [ ] **Step 2: Create `index.ts`**

Create `frontend/src/features/integrations/plugins/nano_gpt_voice_xai/index.ts`:

```typescript
import type { IntegrationPlugin, Option } from '../../types'
import {
  sttRegistry,
  ttsRegistry,
  declareProviderEngines,
} from '../../../voice/engines/registry'
import { NanoGptXaiSTTEngine, NanoGptXaiTTSEngine } from './engines'
import {
  nanoGptXaiVoices,
  refreshNanoGptXaiVoices,
  invalidateNanoGptXaiVoicesCache,
} from './voices'
import { registerPlugin } from '../../registry'

declareProviderEngines('nano_gpt_voice_xai', {
  stt: 'nano_gpt_voice_xai_stt',
  tts: 'nano_gpt_voice_xai_tts',
})

let sttInstance: NanoGptXaiSTTEngine | null = null
let ttsInstance: NanoGptXaiTTSEngine | null = null

const nanoGptVoiceXaiPlugin: IntegrationPlugin = {
  id: 'nano_gpt_voice_xai',

  onActivate(): void {
    if (!sttInstance) sttInstance = new NanoGptXaiSTTEngine()
    if (!ttsInstance) ttsInstance = new NanoGptXaiTTSEngine()
    sttRegistry.register(sttInstance)
    ttsRegistry.register(ttsInstance)
    void refreshNanoGptXaiVoices()
  },

  onDeactivate(): void {
    sttInstance = null
    ttsInstance = null
    invalidateNanoGptXaiVoicesCache()
  },

  async getPersonaConfigOptions(fieldKey: string): Promise<Option[]> {
    if (fieldKey !== 'voice_id' && fieldKey !== 'narrator_voice_id') return []
    await refreshNanoGptXaiVoices()
    const voiceOptions = nanoGptXaiVoices.current.map(
      (v) => ({ value: v.id, label: v.name }),
    )
    if (fieldKey === 'narrator_voice_id') {
      return [
        { value: null, label: 'Inherit from primary voice' },
        ...voiceOptions,
      ]
    }
    return voiceOptions
  },
}

registerPlugin(nanoGptVoiceXaiPlugin)

export default nanoGptVoiceXaiPlugin
```

- [ ] **Step 3: Wire imports at the three known sites**

Add `import './features/integrations/plugins/nano_gpt_voice_xai'` immediately after the corresponding `xai_voice` import (so plugin registration happens at app/modal load time) in each of:

- `frontend/src/App.tsx`:

```typescript
import './features/integrations/plugins/mistral_voice'
import './features/integrations/plugins/xai_voice'
import './features/integrations/plugins/nano_gpt_voice_xai'   // <-- add
```

- `frontend/src/app/components/persona-overlay/IntegrationsTab.tsx` — add the same import (path relative as in the existing imports — `../../../features/integrations/plugins/nano_gpt_voice_xai`).

- `frontend/src/app/components/user-modal/IntegrationsTab.tsx` — same.

For each file, the import path must match the relative depth of the existing `xai_voice` import in that file. Use `rg -n "plugins/xai_voice" frontend/src/` to confirm the exact spelling at each call site before adding.

- [ ] **Step 4: Type-check**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm tsc --noEmit
```

Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/integrations/plugins/nano_gpt_voice_xai/engines.ts \
        frontend/src/features/integrations/plugins/nano_gpt_voice_xai/index.ts \
        frontend/src/App.tsx \
        frontend/src/app/components/persona-overlay/IntegrationsTab.tsx \
        frontend/src/app/components/user-modal/IntegrationsTab.tsx
git commit -m "$(cat <<'EOF'
Register nano-gpt voice plugin engines and wire imports

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Frontend plugin unit tests

Goal: api + engine unit tests mirror the structure of `xai_voice/__tests__/` so CI catches regressions in the request shape and engine wiring.

**Files:**
- Create: `frontend/src/features/integrations/plugins/nano_gpt_voice_xai/__tests__/api.test.ts`
- Create: `frontend/src/features/integrations/plugins/nano_gpt_voice_xai/__tests__/engines.test.ts`

- [ ] **Step 1: Inspect the existing xai_voice tests as the template**

```bash
cat frontend/src/features/integrations/plugins/xai_voice/__tests__/api.test.ts
cat frontend/src/features/integrations/plugins/xai_voice/__tests__/engines.test.ts
```

- [ ] **Step 2: Write `api.test.ts`**

Mirror the xai_voice `api.test.ts` structure exactly — same `fetch` mocking, same assertions — but adapted to:
- BASE = `/api/integrations/nano_gpt_voice_xai/voice`
- Imports from `../api`, function names `transcribeNanoGptXai`, `synthesiseNanoGptXai`, `listNanoGptXaiVoices`
- For the TTS test, the request body is `{ text, voice_id }` (same as xai)
- For the STT test, the multipart `audio` field name matches the api module

If the xai test exists and works, this should be a near-mechanical port. Keep test descriptions distinct ("nano-gpt xAI TTS posts JSON body", etc.) so the suite reports clearly.

- [ ] **Step 3: Write `engines.test.ts`**

Mirror xai_voice's `engines.test.ts`. Replace class names with `NanoGptXaiSTTEngine` / `NanoGptXaiTTSEngine` and update mocked API module paths.

- [ ] **Step 4: Run the frontend tests**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm vitest run src/features/integrations/plugins/nano_gpt_voice_xai
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/integrations/plugins/nano_gpt_voice_xai/__tests__/
git commit -m "$(cat <<'EOF'
Add unit tests for nano-gpt voice plugin (api + engines)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Roundtrip smoke test against live nano-gpt

Goal: A standalone script verifies that the documented request shapes actually work against the live nano-gpt API. Reads the API key from `.nano-test-key` (already present in repo root, gitignored). The script doubles as a regression check.

**Files:**
- Create: `backend/llm_harness/nano_gpt_voice_roundtrip.py`

- [ ] **Step 1: Confirm the key file exists**

```bash
ls -la /home/chris/workspace/chatsune/.nano-test-key
```

Expected: file exists and is gitignored (verified earlier).

- [ ] **Step 2: Create the smoke test**

Create `backend/llm_harness/nano_gpt_voice_roundtrip.py`:

```python
"""Roundtrip smoke test: TTS → STT against live nano-gpt (xAI backend).

Usage:
    uv run python -m backend.llm_harness.nano_gpt_voice_roundtrip

Reads the API key from ``.nano-test-key`` (repo root, plain text,
gitignored).

Why this exists: nano-gpt's voice routes are not formally documented for
xAI, and we have seen documented shapes diverge for image-gen. This
script exercises the real adapter end-to-end and prints the request /
response shapes so any divergence from
``devdocs/superpowers/specs/2026-05-17-nano-gpt-voice-design.md``
surfaces immediately.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import httpx

from backend.modules.integrations._voice_adapters._nano_gpt_voice_xai import (
    NanoGptVoiceXaiAdapter,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
KEY_FILE = REPO_ROOT / ".nano-test-key"

SAMPLE_TEXT = "The quick brown fox jumps over the lazy dog."
SAMPLE_VOICE = "Eve"
SAMPLE_LANG = "en"


def _word_overlap(a: str, b: str) -> float:
    """Return the fraction of ``a``'s tokens that appear in ``b``.

    Whisper-class STT is reliable on a known sentence but punctuation
    and casing differ, so we measure token overlap rather than exact
    match.
    """
    tokens_a = set(re.findall(r"[a-z]+", a.lower()))
    tokens_b = set(re.findall(r"[a-z]+", b.lower()))
    if not tokens_a:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a)


async def main() -> int:
    if not KEY_FILE.exists():
        print(f"ERROR: API key file not found at {KEY_FILE}")
        return 2
    api_key = KEY_FILE.read_text().strip()
    if not api_key:
        print(f"ERROR: API key file at {KEY_FILE} is empty")
        return 2

    async with httpx.AsyncClient(timeout=60.0) as client:
        adapter = NanoGptVoiceXaiAdapter(client)

        print(f"→ TTS: model={adapter.TTS_MODEL!r} voice={SAMPLE_VOICE!r} "
              f"text={SAMPLE_TEXT!r}")
        audio_bytes, ctype = await adapter.synthesise(
            text=SAMPLE_TEXT, voice_id=SAMPLE_VOICE, api_key=api_key,
        )
        print(f"  ← {len(audio_bytes)} bytes  content-type={ctype}")
        if len(audio_bytes) == 0:
            print("FAIL: TTS returned empty audio")
            return 1

        print(f"→ STT: model={adapter.STT_MODEL!r} language={SAMPLE_LANG!r}")
        text = await adapter.transcribe(
            audio=audio_bytes,
            content_type=ctype,
            api_key=api_key,
            language=SAMPLE_LANG,
        )
        print(f"  ← text={text!r}")
        overlap = _word_overlap(SAMPLE_TEXT, text)
        print(f"  ← word overlap with original: {overlap:.0%}")
        if overlap < 0.6:
            print(f"FAIL: STT transcription differs too much from original "
                  f"(overlap {overlap:.0%}, need ≥60%)")
            return 1

    print("OK: roundtrip succeeded")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 3: Compile check**

```bash
uv run python -m py_compile backend/llm_harness/nano_gpt_voice_roundtrip.py
```

Expected: silent success.

- [ ] **Step 4: Run the smoke test against the live API**

```bash
cd /home/chris/workspace/chatsune
uv run python -m backend.llm_harness.nano_gpt_voice_roundtrip
```

Expected: prints the TTS byte count + content-type, the STT text, the word-overlap percentage, and "OK: roundtrip succeeded".

**If this fails:** the documented request shapes diverge from reality. Inspect the printed request/response, fix the adapter at `backend/modules/integrations/_voice_adapters/_nano_gpt_voice_xai.py`, update the corresponding adapter test(s), and re-run. Common divergences to check:

- Auth header: nano-gpt may accept `Authorization: Bearer …` instead of (or in addition to) `x-api-key`. Try Bearer if `x-api-key` 401s.
- STT field name: nano-gpt's OpenAI-compat may want `file` (current default) or the nano-specific endpoint may want `audio`. If the OpenAI-compat endpoint 404s, fall back to `POST /api/transcribe` with `audio` field.
- TTS body key: may be `input` (current) or `text`. Both are common.
- Async response: nano-gpt may return `{"audioUrl": "...", "runId": "..."}` instead of binary audio. If so, the adapter must follow the URL or poll status.

Update §4.3 of the spec inline if anything changes.

- [ ] **Step 5: Commit (only after the smoke test passes)**

```bash
git add backend/llm_harness/nano_gpt_voice_roundtrip.py
# If the adapter or tests had to change, stage those too:
git add -u backend/modules/integrations/_voice_adapters/_nano_gpt_voice_xai.py \
           tests/modules/integrations/test_voice_adapter_nano_gpt_voice_xai.py \
           devdocs/superpowers/specs/2026-05-17-nano-gpt-voice-design.md
git commit -m "$(cat <<'EOF'
Add nano-gpt voice roundtrip smoke test

Verifies TTS→STT against the live nano-gpt API. Catches divergences
from documented shapes (auth header, field names, response envelope).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Final build verification + merge prep

Goal: All builds clean, all tests pass, integration is end-to-end functional in a running dev server, branch ready to squash to master.

- [ ] **Step 1: Backend full test suite (the new tests + smoke test must not have broken anything)**

```bash
cd /home/chris/workspace/chatsune
uv run pytest -q
```

Expected: same pass/fail count as before this change (no new failures).

- [ ] **Step 2: Frontend full test suite**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm tsc --noEmit
pnpm vitest run
pnpm run build
```

Expected: typecheck clean, all tests pass, build succeeds.

- [ ] **Step 3: Manual smoke against running dev server**

Per project convention: start backend + frontend, configure a Premium Provider Account with the nano-gpt key (or reuse an existing one), then verify:

1. nano-gpt account card shows TTS and STT badges (`PremiumAccountCard` / `CoverageRow`).
2. In a Persona's TTS settings, "xAI Voice via nano-gpt" appears in the provider dropdown and the five voices populate.
3. In the user's Voice Settings, "xAI Voice via nano-gpt" appears in the STT provider dropdown.
4. Sending a chat message with TTS enabled plays audio.
5. Voice input produces a transcript that lands in the chat box.

For each of (1)–(5), note pass/fail. If anything fails, fix and re-run from the relevant earlier task.

- [ ] **Step 4: Squash to one commit and merge to master**

Per project convention (`feedback_squash_spec_commits.md`): spec + plan + implementation get squashed into a single commit on master.

```bash
cd /home/chris/workspace/chatsune
git log --oneline d1c06a9d^..HEAD
# Confirm the commit set you intend to squash.
```

Then either:
- `git rebase -i <merge-base>` and reword the squashed commit, or
- `git reset --soft <merge-base> && git commit -m "Add nano-gpt voice (xAI TTS+STT) integration"` and re-create one tidy commit.

Final commit message body should briefly enumerate: spec, plan, backend adapter+tests, integration registration, premium-provider capability extension, frontend plugin+tests, smoke test.

```bash
git push origin master
```

---

## Self-review notes

- **Spec coverage:** All 9 spec sections covered. §1 Premium-provider capability extension → Task 4. §2 Integration definition → Task 4. §3 Voice adapter → Tasks 1-3. §4 Voice list source-of-truth → comment in Task 1 + mirror in Task 5. §5 Frontend plugin → Tasks 5-7. §6 Persona-config UI / §7 User-STT-settings UI → no code change (Task 9 step 3 manually verifies). §6 (verification roundtrip) → Task 8. §7 Build verification → Task 9. §8 Rollout (squash) → Task 9 step 4. §9 Risks → addressed where possible (smoke test catches auth-header / field-name / async-envelope risks in Task 8).
- **Type consistency:** `NanoGptVoiceXaiAdapter` (Python), `NanoGptXaiSTTEngine` / `NanoGptXaiTTSEngine` (TS), `nano_gpt_voice_xai` (integration id), `nano_gpt_voice_xai_stt` / `nano_gpt_voice_xai_tts` (engine ids). Voice IDs are plain names without prefix.
- **TDD discipline:** Backend adapter is fully TDD'd. Frontend tests in Task 7 are ports of the existing `xai_voice` tests rather than fresh red→green cycles, because the engine is structurally identical and the test scaffolding is non-trivial to author from scratch.
- **No placeholders:** Each step has actual code or actual commands. Task 7 references "mirror the xai_voice test" rather than duplicating ~100 lines that already exist in-tree and are required reading anyway.

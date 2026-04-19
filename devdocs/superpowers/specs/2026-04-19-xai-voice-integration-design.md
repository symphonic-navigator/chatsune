# xAI Voice Integration — Design

**Status:** Draft · 2026-04-19
**Author:** Chris (with Claude)
**Supersedes:** —
**Related:** [Voice Mode overview](../../../VOICE-MODE.md) · [2026-04-17 voice integrations design](./2026-04-17-voice-integrations-design.md)

---

## 1. Problem

Chatsune currently offers one voice provider: Mistral (via the `mistral_voice`
integration). The community has asked for xAI as an alternative — same
feature surface (STT + TTS) but different voice catalogue and pricing. Users
should be able to pick per-persona which provider speaks the assistant's
reply, and pick globally which provider transcribes their speech.

xAI introduces one architectural wrinkle: the upstream API does not send
CORS headers, so browser-direct calls (the pattern used for Mistral) are
not possible. Inference for xAI must go through the Chatsune backend as
an authenticated proxy.

## 2. Goals & non-goals

### Goals

- Add an `xai_voice` integration that provides STT and TTS via xAI's
  cloud API.
- Per-persona TTS provider selection; per-user STT provider selection.
- Dynamic voice list (fetched from xAI at plugin activation time).
- Backend-proxied: the xAI API key never leaves the backend.
- Backwards-compatible with existing personas and user settings — no
  data migration required.
- Introduce a reusable pattern for backend-proxied voice providers so
  additional providers (ElevenLabs, OpenAI, etc.) can be added later with
  a narrow implementation surface, if ever needed.

### Non-goals

- xAI voice cloning (xAI does not offer it in this form; future adapter
  capabilities will be modelled as optional mixins if needed).
- xAI streaming audio (cost-prohibitive; the existing sentence-level
  streaming in the voice pipeline remains the model for low-latency
  playback).
- A unified "API key store" across integrations (see separate discussion
  — deferred until ≥3 overlapping cases and a real pain point).
- Any changes to the voice pipeline itself (sentencer, parser,
  modulation, playback, conversational mode, tentative barge, auto-read,
  narrator mode) — all remain provider-agnostic and unchanged.

## 3. Architecture overview

The xAI integration follows the existing integration plugin pattern but
adds a new axis: **backend-proxied** vs the existing **browser-direct**
pattern used by Mistral.

```
Browser                                Backend                         xAI
───────                                ───────                         ───
VoiceButton / ReadAloudButton
  │
  ▼
sttRegistry / ttsRegistry
  │
  ▼
resolveEngineForPersona(persona)       ← new: dispatch per persona/user
  │                                      (falls back to "first enabled"
  │                                       when no provider_id is set)
  ▼
XaiSTTEngine / XaiTTSEngine            POST /api/integrations/
  │                                         xai_voice/voice/stt
  └──── HTTP (auth: JWT) ─────────►      │
                                          ▼
                                       VoiceAdapter registry
                                          │ lookup('xai_voice')
                                          ▼
                                       XaiVoiceAdapter.transcribe(...)
                                          │                           ─► POST /v1/audio/
                                          │                              transcriptions
                                          ◄─────────────────────────── ◄─
                                          │
  ◄──── JSON response ──────────────────  │
  ▼
text / audio → audioPlayback / onSend
```

Key properties:

- **Two new frontend plugins:** `xai_voice` (mirror of `mistral_voice`).
  Registers its own STT/TTS engines. The engines call the Chatsune
  backend, not xAI.
- **One new backend adapter:** `XaiVoiceAdapter` in
  `backend/modules/integrations/_voice_adapters/_xai.py`. Implements
  `VoiceAdapter` (`transcribe`, `synthesise`, `list_voices`).
- **Three new backend routes (per integration-id):**
  - `POST /api/integrations/{id}/voice/stt` (multipart)
  - `POST /api/integrations/{id}/voice/tts` (JSON → binary audio)
  - `GET  /api/integrations/{id}/voice/voices`
- **No secret hydration for xAI:** the `IntegrationDefinition` gains a
  flag `hydrate_secrets: bool`, default `True` (preserves Mistral
  behaviour). For xAI it is `False`; the API key stays server-side.
- **Resolution topology:**
  - TTS engine is resolved **per persona** from
    `persona.voice_config.tts_provider_id`.
  - STT engine is resolved **per user** from
    `user.settings.stt_provider_id`.
  - Both fall back to "first enabled integration with the relevant
    capability" when the field is unset (same behaviour as today).

### Unchanged

- The voice pipeline (sentencer, parser, modulation, audio playback).
- Conversational mode, tentative barge, auto-read, narrator mode.
- The integration registry and the `IntegrationDefinition` mechanism.
- The Mistral voice plugin (continues browser-direct as today).

## 4. Data model

All new fields are optional; no DB migration is required. Existing
documents deserialise without error and behave identically to today via
the fallback path.

### 4.1 Persona (`persona.voice_config`)

```python
# backend/modules/persona/_models.py — VoiceConfig
tts_provider_id: str | None = None   # new — None means "use first enabled"
```

`voice_id` and `narrator_voice_id` continue to live in
`persona.integration_configs[<provider_id>]`. Switching the persona's
TTS provider reads `voice_id` from the other sub-dict. This preserves the
user's previous voice choice per provider — "last time you had Mistral
selected, it was Samantha" is remembered automatically.

### 4.2 User settings

```python
# backend/modules/settings/_models.py
stt_provider_id: str | None = None   # new — per user
```

### 4.3 IntegrationDefinition

```python
# backend/modules/integrations/_models.py — IntegrationDefinition
hydrate_secrets: bool = True   # default True = Mistral behaviour
```

- `mistral_voice`: `hydrate_secrets=True` (browser-direct, unchanged)
- `xai_voice`: `hydrate_secrets=False` (API key stays backend-side)
- `lovense`: `hydrate_secrets=True` (unchanged)

The WebSocket hydration handler reads this flag; integrations with
`hydrate_secrets=False` emit no `integration.secrets.hydrated` event.

### 4.4 Resolution logic

```
tts_provider_id set?
  ├── yes  → use this provider
  └── no   → fallback: first enabled integration with TTS_PROVIDER
              (identical to current behaviour)

If provider_id points to a disabled/unregistered provider:
  → the resolver falls back as if the field were None
  → emit a `voice.resolver.fallback` warning log
  → never crashes the UI
```

## 5. Backend components

### 5.1 `VoiceAdapter` interface

New file `backend/modules/integrations/_voice_adapters/_base.py`:

```python
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
    # user_message set per-case


class VoiceAdapter(ABC):
    """Backend-proxied voice provider. One instance per provider type."""

    @abstractmethod
    async def transcribe(
        self, audio: bytes, content_type: str, api_key: str, language: str | None,
    ) -> str: ...

    @abstractmethod
    async def synthesise(
        self, text: str, voice_id: str, api_key: str,
    ) -> tuple[bytes, str]:
        """Returns (audio_bytes, content_type)."""

    @abstractmethod
    async def list_voices(self, api_key: str) -> list[VoiceInfo]: ...

    async def validate_credentials(self, api_key: str) -> None:
        """Default: list_voices. Adapters may override with a cheaper probe."""
        await self.list_voices(api_key)
```

Three methods, no capability matrix. Future additions (cloning, etc.)
can be optional mixins.

### 5.2 `XaiVoiceAdapter`

`backend/modules/integrations/_voice_adapters/_xai.py`:

- `BASE_URL = "https://api.x.ai/v1"`
- TTS and STT model IDs hardcoded per the xAI docs (exact identifiers
  confirmed at implementation time — xAI ships one model each by design).
- Uses a shared `httpx.AsyncClient` with `timeout=60.0`, injected at
  construction time.
- Maps HTTP status codes: 401/403 → `VoiceAuthError`, 429 →
  `VoiceRateLimitError`, 400/422 → `VoiceBadRequestError`, 5xx / timeout
  / connection error → `VoiceUnavailableError`.
- `transcribe`: `POST /v1/audio/transcriptions` (multipart/form-data).
- `synthesise`: `POST /v1/audio/speech` (JSON body, returns audio/mpeg).
- `list_voices`: `GET /v1/tts/voices`, parses the `voices` array,
  maps each entry to `VoiceInfo`.

### 5.3 Adapter registry

`backend/modules/integrations/_voice_adapters/__init__.py`:

```python
_registry: dict[str, VoiceAdapter] = {}

def register(integration_id: str, adapter: VoiceAdapter) -> None: ...
def get(integration_id: str) -> VoiceAdapter | None: ...
```

Registered at module import time, alongside where the integration
definition is registered.

### 5.4 Proxy routes

In `backend/modules/integrations/_handlers.py`:

```
POST /api/integrations/{integration_id}/voice/stt
  Body: multipart/form-data
    - audio: file (audio/wav or audio/webm)
    - language: str | None
  Response: { "text": "..." }

POST /api/integrations/{integration_id}/voice/tts
  Body: JSON
    {
      "text": "...",
      "voice_id": "..."
    }
  Response: binary audio (Content-Type set by adapter)

GET /api/integrations/{integration_id}/voice/voices
  Response: { "voices": [ { "id", "name", "language", "gender" }, ... ] }
```

Per-route flow:

1. JWT auth (existing dependency).
2. Load `UserIntegrationConfig` for (user, integration_id). 404 if not
   present or not enabled.
3. Decrypt API key (Fernet, existing pattern).
4. Get adapter from registry. 400 if integration has no adapter
   (`hydrate_secrets=True`, i.e. browser-direct integration).
5. Call adapter method.
6. Catch `VoiceAdapterError` → map to HTTP `status_code` with
   `{"error_code", "message"}` body.
7. Pass through on success.

No retries at this layer — retry ownership sits in the frontend so the
user sees state correctly.

### 5.5 Credential validation on enable

When a user enables a backend-proxied integration (or updates its key),
the backend calls `adapter.validate_credentials(api_key)`. On failure,
the integration stays disabled and the error propagates to the UI.

**If the existing Mistral plugin does not already validate on enable,
this is added as part of this work for both Mistral and xAI.** (Mistral
has a simpler path — the call happens from the browser, but the smoke
test can be done once during activation in either layer. Implementation
will confirm what's already there and add the minimum missing piece.)

### 5.6 `IntegrationDefinition` entry

Added to `_register_builtins()` in `_registry.py`:

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
            "description": "Your personal xAI API key. Encrypted at rest; "
                           "never leaves the backend.",
        },
        {
            "key": "playback_gap_ms",
            "label": "Pause between chunks",
            "field_type": "select",
            "required": False,
            "description": "Gap inserted between sentences and speaker switches.",
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
            "description": "Voice used for narration / prose when narrator "
                           "mode is active. Leave at 'Inherit' to use the "
                           "primary voice.",
        },
    ],
    tool_definitions=[],
))
```

### 5.7 Logging

Per-call structured logging, aligned with the Claude-Oriented-Logging
principle in CLAUDE.md:

```python
logger.info("voice.proxy", extra={
    "integration_id": "xai_voice",
    "op": "transcribe" | "synthesise" | "list_voices",
    "user_id": "...",
    "duration_ms": ...,
    "upstream_status": 200,
})
```

On error, additionally `error_code` and `error_class`. API keys are
never logged.

## 6. Frontend components

### 6.1 New plugin `xai_voice`

New directory
`frontend/src/features/integrations/plugins/xai_voice/`:

- `index.ts` — mirrors `mistral_voice/index.ts`. Registers STT/TTS
  engines in `onActivate`, clears them in `onDeactivate`. Triggers
  `refreshXaiVoices()` on activate.
- `engines.ts` — `XaiSTTEngine` and `XaiTTSEngine`. Delegate to `api.ts`
  (no API key handling — browser doesn't know the key).
- `api.ts` — thin client over
  `/api/integrations/xai_voice/voice/{stt,tts,voices}`. Auth via the
  existing JWT mechanism in the WebSocket/HTTP layer.
- `voices.ts` — `xaiVoices: { current: VoicePreset[] }` +
  `refreshXaiVoices()`. Generation-counter logic identical to Mistral
  (stale-refresh protection during rapid activate/deactivate cycles).
- No `ExtraConfigComponent.tsx` — xAI has no cloning. The field in the
  `IntegrationPlugin` interface is already optional.

### 6.2 `isReady()` semantics

Mistral reads from `secretsStore` (the hydrated API key). xAI reads from
the integrations config store (is the integration enabled?). Different
semantics is correct: "ready" means "can I make a call", and for xAI the
call goes through the authenticated backend, which depends only on
integration-enabled state.

```ts
// XaiTTSEngine.isReady():
useIntegrationsStore.getState().configs?.['xai_voice']?.enabled === true
```

### 6.3 Engine resolution — from global to per-context

The largest frontend change. Today `sttRegistry.active()` and
`ttsRegistry.active()` return a single globally-selected engine (first
registered wins). We replace that with small resolver helpers — without
inflating state management:

```ts
// frontend/src/features/voice/engines/resolver.ts (new)

/** Resolve TTS engine for a given persona. */
export function resolveTTSEngine(persona: PersonaDto): TTSEngine | undefined {
  const providerId = persona.voice_config?.tts_provider_id
  if (providerId) {
    const engineId = providerToEngineId(providerId, 'tts')
    const engine = engineId ? ttsRegistry.get(engineId) : undefined
    if (engine?.isReady()) return engine
    // fallback — log warning
  }
  return firstEnabledTTSEngine()
}

/** Resolve STT engine for the current user. */
export function resolveSTTEngine(): STTEngine | undefined {
  const providerId = useUserSettingsStore.getState().stt_provider_id
  if (providerId) {
    const engineId = providerToEngineId(providerId, 'stt')
    const engine = engineId ? sttRegistry.get(engineId) : undefined
    if (engine?.isReady()) return engine
  }
  return firstEnabledSTTEngine()
}
```

`providerToEngineId()` is a tiny registry map (`"mistral_voice" →
"mistral_tts"`, `"xai_voice" → "xai_tts"`). Each plugin registers its
pair at plugin-registration time.

**Registry changes:**
- Keep: `register()`, `get()`, `list()`.
- Remove: `active()`, `setActive()`, `clearActive()`, and the
  auto-promote-first-registered logic.
- Migrate: ~8–10 call sites in `frontend/src/features/voice/` that use
  `sttRegistry.active()` / `ttsRegistry.active()` → switch to the
  resolver helpers. Each call site has the context (a persona or not)
  to pick the right helper.

### 6.4 UI — `PersonaVoiceConfig.tsx` additions

Add a **TTS Provider** dropdown above the existing **Voice** dropdown:

```
┌────────────────────────────────────────┐
│ TTS Provider                           │
│ ┌────────────────────────────────────┐ │
│ │ Mistral Voice (default)          ▾ │ │
│ │ xAI Voice                          │ │
│ └────────────────────────────────────┘ │
│                                        │
│ Voice                                  │
│ ┌────────────────────────────────────┐ │
│ │ [voices of selected provider]    ▾ │ │
│ └────────────────────────────────────┘ │
│ ... narrator voice, speed, pitch ...   │
└────────────────────────────────────────┘
```

- Populated from `definitions.filter(d => d.capabilities?.includes(TTS_PROVIDER) && configs?.[d.id]?.enabled)`.
- "(default)" label shown when `persona.voice_config.tts_provider_id`
  is unset, next to whichever provider the fallback resolves to.
- When the user switches provider: `voice_id` is read from
  `persona.integration_configs[<new_provider>]`. If empty, the first
  available voice in that provider's voice list is proposed (not
  auto-saved — follows the existing debounced save pattern).
- Visible even when only one provider is enabled — clear UX signal.

### 6.5 UI — user settings

New section in the settings overlay:

```
┌────────────────────────────────────────┐
│ Voice Input Provider                   │
│ ┌────────────────────────────────────┐ │
│ │ Mistral Voice (default)          ▾ │ │
│ │ xAI Voice                          │ │
│ └────────────────────────────────────┘ │
│ Used across all personas and chat      │
│ inputs.                                │
└────────────────────────────────────────┘
```

Per-user, not per-persona. Same dropdown-population logic with the
`STT_PROVIDER` capability filter.

### 6.6 Dropdown styling reminder

Per CLAUDE.md — native `<select>` open lists don't inherit styles; the
`OPTION_STYLE` must be applied to each `<option>` element (already done
in the existing `PersonaVoiceConfig.tsx`; must be repeated in the new
settings dropdown).

## 7. Error handling

### 7.1 Error classes

As in §5.1. The xAI adapter maps HTTP failures to the right subclass;
the proxy route catches `VoiceAdapterError` and emits
`{"error_code", "message"}` with the appropriate `http_status`.

### 7.2 Timeouts

`httpx.AsyncClient(timeout=60.0)` at construction. No in-adapter retry —
retries belong in the frontend where the user state is known (and
prevents double-billing on partial 5xx). The STT path may get a shorter
override (~10 s) once implementation confirms typical latency.

### 7.3 Frontend behaviour

- **Conversational mode, STT fails:** treat as empty-STT-result. If a
  tentative barge was in flight, `resumeFromMute()`; otherwise pipeline
  returns to `listening`. Toast: "Transcription failed — try again".
- **Auto-read / Push-to-speak, TTS fails:** cancel the streaming
  read-aloud session (`cancelStreamingAutoRead()`), toast with the
  upstream `user_message`.
- **Resolver finds a disabled provider:** return `undefined`, log
  `voice.resolver.fallback` at warn level, fall back to first-enabled.
  UI shows voice buttons disabled/absent — same as "no provider
  configured at all" today. No crashes.
- **Rate limit toast:** distinguished message, same structural error
  flow.

### 7.4 Credential validation on enable

See §5.5 — smoke test via `adapter.validate_credentials()`.

### 7.5 Logging

Errors log with `integration_id`, `op`, `user_id`, `upstream_status`,
`error_class`. Never log API keys, request bodies containing audio, or
response bodies containing audio.

## 8. Testing

### 8.1 Backend unit tests (pytest + `httpx.MockTransport`)

**`XaiVoiceAdapter`:**
- `transcribe` sends correct multipart form; parses `text` from response.
- `synthesise` sends correct JSON body; returns audio bytes + content-type.
- `list_voices` parses response and maps to `VoiceInfo`.
- Error mapping: 401 → `VoiceAuthError`; 429 → `VoiceRateLimitError`;
  500 → `VoiceUnavailableError`; timeout → `VoiceUnavailableError`;
  422 → `VoiceBadRequestError`.

**Voice proxy route:**
- 401 without JWT.
- 404 if integration not enabled for user.
- 400 if integration has no registered adapter (i.e.
  `hydrate_secrets=True`, browser-direct).
- Happy path dispatches to the correct adapter with the decrypted key.

### 8.2 Frontend unit tests (vitest + mocked fetch)

**Resolver (`resolver.ts`):**
- Persona with `tts_provider_id="xai_voice"` + xAI ready → returns xAI
  engine.
- Persona with `tts_provider_id="xai_voice"` + xAI not ready → fallback
  to first-enabled, warn log.
- Persona without `tts_provider_id` → first-enabled integration.
- No integration enabled → `undefined`.

**`XaiSTTEngine` / `XaiTTSEngine`:**
- `transcribe` posts multipart to `/api/integrations/xai_voice/voice/stt`
  and extracts `text`.
- `synthesise` posts JSON and decodes response audio to `Float32Array`.
- `isReady()` reacts correctly to integration-config changes.

### 8.3 Manual verification (pre-merge)

1. Activate xAI integration with a valid key → smoke test passes →
   voices list loads.
2. Activate with an invalid key → smoke test fails → clear error
   message → integration stays disabled.
3. Set persona TTS to xAI → auto-read of an assistant message uses xAI
   TTS.
4. Set user STT to xAI → start conversational mode → xAI transcribes.
5. Mixed operation: Persona A with Mistral TTS, Persona B with xAI TTS;
   switch between them in the same session → each persona uses its own
   provider.
6. Disable xAI while a persona points to it → auto-read falls back to
   Mistral; backend warn log present.
7. Simulate rate limit (devtools block or test fixture) → rate-limit
   toast, pipeline recovers cleanly.
8. Build verification: `pnpm run build` (frontend) and `uv run python
   -m py_compile` on changed backend files.

### 8.4 Not tested

- Trivial UI components (provider dropdown).
- The unchanged voice pipeline (sentencer, parser, modulation).
- xAI API behaviour itself — their concern; the smoke test catches key
  issues in practice.

## 9. Open decisions / to be confirmed at implementation

- Exact xAI model identifiers (TTS model, STT model) — xAI docs at
  implementation time; both are fixed per provider design.
- Exact response schema for `/v1/tts/voices` (field names: `voice_id`
  vs `id`, `name`, any language/gender fields).
- Whether Mistral plugin already validates credentials on enable, or
  whether the smoke-test hook is added fresh as part of this work.
- Whether the existing Mistral `playback_gap_ms` is read from
  `UserIntegrationConfig` or elsewhere in the frontend (confirm the
  wiring is already generic enough to reuse for xAI). Expected: yes.

## 10. Rollout

- No feature flag needed: the integration is opt-in per user (the user
  must add their key and enable it).
- Existing users: no behaviour change. They see a new integration
  "xAI Voice" in the integrations list. Opting in is a deliberate
  action; opting out is removing the key / disabling the integration.
- Documentation: update `VOICE-MODE.md` §5 to note that some
  integrations are backend-proxied (`hydrate_secrets=False`) and why.
- Future related decisions deferred: unified API key store (see
  discussion — deferred until more overlapping cases and a real pain
  point surface).

## 11. File map

**New files:**

```
backend/modules/integrations/_voice_adapters/__init__.py
backend/modules/integrations/_voice_adapters/_base.py
backend/modules/integrations/_voice_adapters/_xai.py
backend/modules/integrations/_voice_adapters/_test_xai.py  (pytest)

frontend/src/features/integrations/plugins/xai_voice/index.ts
frontend/src/features/integrations/plugins/xai_voice/engines.ts
frontend/src/features/integrations/plugins/xai_voice/api.ts
frontend/src/features/integrations/plugins/xai_voice/voices.ts

frontend/src/features/voice/engines/resolver.ts
frontend/src/features/voice/engines/__tests__/resolver.test.ts
```

**Modified files:**

```
backend/modules/integrations/_registry.py        (register xai_voice)
backend/modules/integrations/_models.py          (hydrate_secrets flag)
backend/modules/integrations/_handlers.py        (proxy routes + hydration
                                                  skip when hydrate_secrets
                                                  is False)
backend/modules/persona/_models.py               (tts_provider_id)
backend/modules/settings/_models.py              (stt_provider_id)

frontend/src/features/voice/engines/registry.ts  (drop active/setActive)
frontend/src/features/voice/components/PersonaVoiceConfig.tsx
                                                 (provider dropdown +
                                                  resolver)
frontend/src/features/voice/components/ReadAloudButton.tsx (resolver)
frontend/src/features/voice/components/VoiceButton.tsx     (resolver)
frontend/src/features/voice/hooks/useConversationMode.ts   (resolver)
frontend/src/features/voice/pipeline/voicePipeline.ts      (resolver)
frontend/src/features/voice/pipeline/streamingAutoReadControl.ts
                                                 (resolver if active()
                                                  still used)
frontend/src/app/components/persona-overlay/PersonaOverlay.tsx
                                                 (resolver-based check)
frontend/src/features/chat/ChatView.tsx          (resolver-based check)
[settings overlay component]                     (STT provider picker)

VOICE-MODE.md                                    (note proxied mode)
```

(Exact settings-overlay file path confirmed at implementation time.)

# Voice via Integrations System — Design

**Date:** 2026-04-17
**Status:** Accepted (pending implementation plan)

---

## Context

Prototype 3 shipped a browser-side WebGPU/WASM voice pipeline (Whisper for STT,
Kokoro for TTS, Transformers.js). It works, but getting WebGPU/WASM to behave
reliably across devices, browsers, and model quantisations is a research
project in itself — not something to land under time pressure for the beta
tester cohort.

Rather than keep that pipeline on life support, we extract it into a separate
future project ("lab-bench for WebGPU voice"), and ship voice for the beta via
an API provider instead.

**Provider choice:** Mistral AI. API shape is simple enough, and their TOS
covers our self-hosted-multi-user use-case (confirmed via LeChat).

**Architectural principle:** voice is wired through Chatsune's existing
Integrations system — same path as Lovense, no parallel subsystem. Each user
brings their own Mistral API key (BYOK), consistent with the LLM Connections
architecture.

---

## Goals

- Remove the existing WebGPU-based voice implementation cleanly.
- Extend the Integrations system to carry voice capabilities (STT, TTS),
  orthogonal to the existing tool-provider capability.
- Ship a Mistral Voice integration (STT + TTS in one definition) as the first
  implementation.
- **Voice cloning** as part of the Mistral integration: the user can clone a
  custom voice by recording in the browser or uploading an audio file;
  cloned voices become selectable per persona alongside Mistral's stock
  voices.
- BYOK: user-scoped API key, encrypted-at-rest in the backend, delivered to
  the browser in memory only (never persisted browser-side).
- Per-persona voice selection (generic pattern, not hard-coded to Mistral).
- Keep latency low: browser calls Mistral directly, no backend proxy hop.

## Non-Goals

- **End-to-end encryption / safe enclave.** Worthwhile follow-up project,
  out of scope here. Server-side-encryption-at-rest is sufficient for BYOK.
- **Narrator / roleplay dual-voice splitting.** Infrastructure in
  `voicePipeline.ts` already supports it, but a second voice selector per
  persona is deferred to the next iteration.
- **Second voice provider.** Design allows it, but only Mistral ships now.
- **Per-persona voice on/off toggle.** Voice is global; if the integration is
  active and the persona has a voice selected, the buttons light up.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│ Browser                                                      │
│  ┌──────────────────┐      ┌─────────────────────────────┐  │
│  │ secretsStore     │◀─────│ WSS: integration.secrets.*  │  │
│  │ (in-memory only) │      └─────────────────────────────┘  │
│  └──────────────────┘                                        │
│          │                                                    │
│          ▼                                                    │
│  ┌──────────────────┐      ┌─────────────────────────────┐  │
│  │ MistralSTTEngine │─────▶│ https://api.mistral.ai/v1/* │──┼──▶ Mistral
│  │ MistralTTSEngine │◀─────│  (direct, CORS-enabled)     │  │
│  └──────────────────┘      └─────────────────────────────┘  │
│          ▲                                                    │
│          │ registered on plugin activation                    │
│          │                                                    │
│  ┌──────────────────┐                                         │
│  │ voicePipeline    │  (unchanged — uses STTEngine/TTSEngine) │
│  └──────────────────┘                                         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Backend                                                      │
│  ┌──────────────────┐        ┌──────────────────────────┐   │
│  │ integrations     │◀───────│ POST /user-config        │   │
│  │  ._repository    │        └──────────────────────────┘   │
│  │  (Fernet encrypt)│                                        │
│  └────────┬─────────┘                                        │
│           │                                                   │
│           ▼                                                   │
│  ┌──────────────────┐        ┌──────────────────────────┐   │
│  │ ws/router        │───────▶│ integration.secrets.     │   │
│  │  (on connect)    │        │   hydrated (WSS, no-log) │   │
│  └──────────────────┘        └──────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

Key property: the Mistral API key travels **backend → browser** over the
authenticated WSS channel on session start, lives in a Zustand store without
persist middleware, and never hits `localStorage` / `IndexedDB`.

---

## Data Model

### Integration Definition (Python dataclass)

```python
class IntegrationCapability(str, Enum):
    TOOL_PROVIDER = "tool_provider"
    TTS_PROVIDER  = "tts_provider"
    STT_PROVIDER  = "stt_provider"


class OptionsSource(str, Enum):
    PLUGIN = "plugin"   # only value for now; enum kept for extensibility


@dataclass
class IntegrationDefinition:
    id: str
    display_name: str
    description: str
    icon: str

    # NEW — orthogonal to execution_mode
    capabilities: list[IntegrationCapability]

    execution_mode: Literal["frontend", "backend", "hybrid"]

    # Existing config_fields, now with optional `secret: bool` and
    # `options_source: OptionsSource | None`.
    config_fields: list[dict]

    # NEW — same shape as config_fields, applied per-persona.
    persona_config_fields: list[dict] = field(default_factory=list)

    # Existing: system prompt template, response tag prefix, tool defs,
    # tool_side, etc. — unchanged.
    ...
```

### Lovense Definition (backward-compatible update)

```python
IntegrationDefinition(
    id="lovense",
    capabilities=[IntegrationCapability.TOOL_PROVIDER],
    execution_mode="frontend",
    # no secret fields, no persona_config_fields — unchanged behaviour
    ...
)
```

### Mistral Voice Definition (new)

```python
IntegrationDefinition(
    id="mistral_voice",
    display_name="Mistral Voice",
    description="Speech-to-text and text-to-speech via Mistral AI.",
    capabilities=[
        IntegrationCapability.TTS_PROVIDER,
        IntegrationCapability.STT_PROVIDER,
    ],
    execution_mode="hybrid",   # key backend-side, inference triggered by browser
    config_fields=[
        {
            "name": "api_key",
            "type": "password",
            "label": "Mistral API Key",
            "secret": True,
            "required": True,
        },
    ],
    persona_config_fields=[
        {
            "name": "voice_id",
            "type": "select",
            "label": "Voice",
            "options_source": OptionsSource.PLUGIN,
            "required": True,
        },
    ],
    tool_definitions=[],
)
```

### `UserIntegrationConfig` (MongoDB)

Mirrors the pattern from `backend/modules/llm/_connections.py`:

```json
{
  "_id": "...",
  "user_id": "...",
  "integration_id": "mistral_voice",
  "enabled": true,
  "config": {},
  "config_encrypted": {"api_key": "gAAAAA..."}
}
```

- On save: `_split_config` routes `secret: True` fields into
  `config_encrypted` (Fernet with `settings.encryption_key`); rest stays in
  `config` (plain).
- On read via REST: `_redact_config` replaces secrets with
  `{"is_set": true|false}` — never leaves the server in clear text.
- On read for hydration: decrypted and emitted on the WSS channel (see below).

### `Persona` (MongoDB)

Two changes:

**Added:**

```python
integration_configs: dict[str, dict[str, Any]] = {}
# { "mistral_voice": { "voice_id": "nova" } }
```

**Deprecated fields on `voice_config`:**

- `dialogue_voice` — dropped from Pydantic model. Existing DB values are
  Kokoro preset IDs and incompatible with Mistral voices. No migration:
  users select a Mistral voice once per persona; the old field is naturally
  dropped on next persona write (Pydantic `extra="ignore"` ensures reads
  succeed either way).
- `narrator_voice` — same treatment as `dialogue_voice`. Returns in the
  narrator iteration.

**Retained on `voice_config`:**

- `auto_read: bool` — provider-agnostic UI behaviour.
- `roleplay_mode: bool` — provider-agnostic; no effect until narrator
  iteration lands, but kept so the user's preference persists.

This approach satisfies the beta-era migration rule (never wipe, reads remain
backward-compatible, no migration script needed).

---

## Events

### New Events (in `shared/events/integrations.py`)

```python
class IntegrationSecretsHydratedPayload(BaseModel):
    integration_id: str
    secrets: dict[str, str]   # field name -> clear text

class IntegrationSecretsHydratedEvent(BaseEvent):
    type: Literal["integration.secrets.hydrated"]
    payload: IntegrationSecretsHydratedPayload

class IntegrationSecretsClearedPayload(BaseModel):
    integration_id: str

class IntegrationSecretsClearedEvent(BaseEvent):
    type: Literal["integration.secrets.cleared"]
    payload: IntegrationSecretsClearedPayload
```

- **Scope:** `global` (user-wide).
- **Emitted:**
  - On WSS connect — one hydrated event per enabled integration that has any
    `secret: True` config field with a value.
  - On user-config save — hydrated event emitted with the latest value.
  - On disable / delete / explicit-clear of a secret field — cleared event.

### Topics Registry — New `persist` Flag

Add a boolean `persist` flag to the topics registry (default `True`). The
two new events listed above register with `persist=False`. The WSS event
pipeline skips Redis-Streams persistence for non-persisted events, so clear
secrets never rest in the 24-hour event log. On reconnect, hydrated events
are re-emitted freshly from the database, never replayed from the log.

---

## Backend Flow

### Storage (`_repository.py`)

Mirror of `backend/modules/llm/_connections.py`:

- `_fernet()` — uses `settings.encryption_key`.
- `_split_config(integration_id, config)` — splits into `plain` / `encrypted`
  based on `secret: True` flags from the `IntegrationDefinition.config_fields`.
- `_redact_config(...)` — produces the `{is_set: bool}` view for REST reads.
- `get_decrypted_secret(doc, field)` — used by the WSS hydration path.

### Hydration Path

A dedicated helper emits hydrated events for a given user:

```python
async def emit_integration_secrets(user_id, event_bus):
    for cfg in await user_integration_repo.list_enabled(user_id):
        definition = REGISTRY.get(cfg["integration_id"])
        secret_fields = [f["name"] for f in definition.config_fields
                         if f.get("secret")]
        if not secret_fields:
            continue
        secrets = {}
        for f in secret_fields:
            val = repo.get_decrypted_secret(cfg, f)
            if val is not None:
                secrets[f] = val
        if secrets:
            await event_bus.publish_global(
                Topics.INTEGRATION_SECRETS_HYDRATED,
                IntegrationSecretsHydratedPayload(
                    integration_id=cfg["integration_id"],
                    secrets=secrets,
                ),
            )
```

Called from `ws/router.py` on connection authentication.

### Persona-Level Config Validation

Persona updates go through the persona module's handler (unchanged entry
point). New validation step: for each `integration_id` in
`integration_configs`, fetch the `IntegrationDefinition`, ensure every key is
declared in `persona_config_fields` and matches the declared type. Unknown
keys rejected with a structured error event.

---

## Frontend Flow

### Code Removed

- `frontend/src/features/voice/engines/whisperEngine.ts`
- `frontend/src/features/voice/engines/kokoroEngine.ts`
- `frontend/src/features/voice/modelManager.ts`
- All WebGPU / ONNX / Transformers.js dependencies in `package.json`.
- `VoiceSettings.enabled` field and its UI toggle. Input-mode preference
  (push-to-talk vs. continuous) stays.

### Code Retained

- `voicePipeline.ts` — depends only on the `STTEngine` / `TTSEngine`
  interfaces, not on any concrete engine.
- `engines/registry.ts` — generic, reused.
- `audioCapture.ts`, `audioPlayback.ts` — browser-native primitives.
- Existing TTS output cache (keyed by text + voice_id) continues to serve
  read-aloud replays without re-inferencing.
- `VoiceButton.tsx` behaviour: the send-button-morphs-to-mic pattern stays
  exactly as it is today — mic when the prompt textarea is empty, send icon
  once the user types. No separate mic button.

### New Code

**Secrets store** — `frontend/src/features/integrations/secretsStore.ts`:

```ts
interface SecretsState {
  secrets: Record<string, Record<string, string>>
  setSecrets(integrationId: string, secrets: Record<string, string>): void
  clearSecrets(integrationId: string): void
  getSecret(integrationId: string, field: string): string | undefined
}
```

Zustand store, **no** persist middleware. WSS event handler calls
`setSecrets` / `clearSecrets`.

**Mistral plugin** —
`frontend/src/features/integrations/plugins/mistral_voice/`:

```
  index.ts                 (IntegrationPlugin registration)
  engines.ts               (MistralSTTEngine, MistralTTSEngine)
  api.ts                   (Mistral API calls: transcribe, synthesise,
                            list voices, clone voice, delete voice)
  voices.ts                (stock voice presets + cache for cloned voices)
  ExtraConfigComponent.tsx (voice-cloning UI — see below)
```

Engines pull the API key from `secretsStore` at call time. `isReady()` returns
`false` when the secret is absent (triggers UI grey-out). Engines never
receive the key as a constructor argument — they look it up on each call so
clears take effect instantly.

**Voice cloning flow (`ExtraConfigComponent`)** — rendered as an extra panel
*below* the generic config fields in the Mistral integration card. The
generic renderer handles the API key field as usual; the extra panel adds:

- List of the user's cloned voices: name + delete button per entry,
  fetched from Mistral's voice list API, filtered to the user's own
  clones.
- "Clone a new voice" flow, two paths:
  1. **Record** — in-browser recording via the existing `audioCapture.ts`
     primitives, with a simple record / stop / preview / submit cycle.
  2. **Upload** — file input accepting common audio formats; browser
     validates format/length client-side, then submits.
- After submission: direct browser call to Mistral's voice-cloning
  endpoint with the audio payload + user-supplied name. Mistral returns
  a voice ID, the plugin refreshes its voice list, and the new voice
  becomes immediately selectable in any persona's voice dropdown.

Audio samples for cloning go **directly browser → Mistral**. They never
touch our backend — biometric data stays with the provider the user chose,
consistent with the BYOK/direct-call stance elsewhere in the design.

Cloned voices live **at Mistral**, not in our database — Mistral is the
source of truth for the user's voice assets (listable, deletable via their
API).

**Impact on `getPersonaConfigOptions("voice_id")`**: returns a
`Promise<Option[]>`. Implementation merges stock voices with the user's
cloned-voice list, cached to avoid refetching on every dropdown open.
Invalidated when the user creates or deletes a clone.

**Plugin registration lifecycle** — extension of `IntegrationPlugin`:

```ts
interface IntegrationPlugin {
  id: string
  // Existing members: executeTag, executeTool, healthCheck, ConfigComponent.

  // `ConfigComponent` (existing) replaces the generic renderer entirely —
  // used by Lovense for its pairing flow.
  //
  // NEW: `ExtraConfigComponent` renders *in addition* to the generic
  // renderer, below the declared config_fields. Used by Mistral for the
  // voice-cloning panel. A plugin uses one or the other, not both.
  ExtraConfigComponent?: React.ComponentType

  // NEW: dynamic option source for persona_config_fields of type "select"
  // with options_source: PLUGIN.
  getPersonaConfigOptions?(fieldName: string): Option[] | Promise<Option[]>

  // NEW: wire engines in/out of the relevant registries.
  onActivate?(): void
  onDeactivate?(): void
}
```

Plugin system triggers `onActivate` when the integration is enabled. For
integrations whose definition declares any `secret: True` fields, activation
is gated on secrets having hydrated as well (so the engine never comes up
without its key). For integrations with no secret fields (Lovense),
activation happens as soon as `enabled=true`. `onDeactivate` runs on
disable or cleared-secrets.

### Generic Config UI

The existing Integrations admin screen renders each integration as a card.
Config fields are now rendered generically from `config_fields`:

- `type: "password"` or `secret: true` → masked input. Shows "API key set"
  badge when the current value's `is_set` is true. No reveal button (user
  re-enters to replace).
- `type: "select"` with `options_source: PLUGIN` → dropdown fed by
  `plugin.getPersonaConfigOptions(field_name)`.
- Other types: standard inputs.

On save → `PUT /api/integrations/user-config/{integration_id}` → backend
encrypts → WSS `integration.secrets.hydrated` → UI flips to "configured"
state and the plugin's `onActivate` runs.

**Plugin custom UI slots:**

- Lovense keeps its full-replacement `ConfigComponent` (pairing flow is
  fundamentally different from a form).
- Mistral uses the new `ExtraConfigComponent` slot — generic renderer
  handles the API key field, the extra panel handles voice cloning.
  Clean separation: no plugin reimplements form-field rendering that the
  generic renderer already covers.

### Persona Edit View

Adds an "Integration Settings" section. For each active integration that
declares `persona_config_fields`, render a block with the fields. Uses the
same generic renderer as user-level config, but persists to
`persona.integration_configs[integration_id]`.

The existing Voice Settings block (`auto_read`, `roleplay_mode`) lives
alongside this new section — provider-agnostic, unchanged. If no TTS
integration is active, the voice-settings block greys out with the hint:
"Activate a TTS integration under Settings → Integrations."

### Chat GUI Wiring

- **Mic input:** existing send-button-morphs-to-mic logic. Additional gate:
  the mic half of the morph only shows if `sttRegistry.active()` returns an
  engine AND that engine's `isReady()` is true. Otherwise the button stays
  in send-mode regardless of textarea emptiness.
- **Read-aloud per message:** a small speaker button appears on assistant
  message bubbles when an active TTS engine is ready AND the active persona
  has a `voice_id` set under the active TTS integration's entry in
  `integration_configs`. (Wiring stays generic — no hard-coded reference to
  Mistral — so a future second TTS provider drops in without chat-GUI
  changes.)
- **Auto-read:** driven by `voice_config.auto_read`; plays new assistant
  messages through the active TTS engine (same readiness gate as above).
  Result cached as today, so replaying via the per-message button is cheap.

---

## Security

### API Key Lifecycle

1. User enters API key in the Mistral integration config form → POST to
   backend.
2. Backend encrypts with Fernet (`settings.encryption_key`, 32 bytes base64).
3. Stored in `UserIntegrationConfig.config_encrypted`.
4. On WSS connect, backend decrypts and emits
   `integration.secrets.hydrated` (scope: `global`, `persist: false`).
5. Browser stores secret in Zustand (no persist middleware). Lost on tab
   close / reload — re-fetched on next WSS connect.
6. Mistral API calls happen browser → `api.mistral.ai` directly, with
   `Authorization: Bearer <key>`.

### Threat Model

- **Database leak:** keys encrypted at rest (Fernet). Attacker needs both DB
  dump and `encryption_key` to read.
- **WSS transit:** TLS.
- **Redis Streams:** `persist: false` keeps clear secrets out of the 24-hour
  event log.
- **XSS in the browser:** can read the secret from memory (same risk surface
  as the auth JWT). Accepted — this is a BYOK user-owned credential, and the
  cost is to the user's own Mistral quota, not a shared system secret.
- **`localStorage` avoidance:** minimises persistence-based exfiltration
  paths (malicious extensions, shared devices).

### CORS

Mistral API endpoints accept browser-origin requests with bearer auth.
A small throwaway test page will confirm this end-to-end after the scaffold
is in place (~10 lines of code, separate from the main app). If CORS turns
out to block in practice, fall back to a thin streaming proxy endpoint —
design already compatible (hybrid execution mode is declared).

---

## Testing

- **Backend:** encryption round-trip, `_split_config` / `_redact_config`
  behaviour, integration-definition schema validation (unknown keys in
  persona config rejected), hydrated event emission on connect and on
  config change.
- **Frontend:** secrets-store never persists, engine registration on
  activate/deactivate, voice pipeline unchanged.
- **Manual end-to-end:** one-off CORS probe page, then full flow — add key,
  see hydrated event arrive, start a voice message, transcribe, auto-read
  response.

---

## Open Items (for Implementation Plan)

- Mistral API details: exact endpoint paths for STT, TTS, voice cloning,
  voice listing, and voice deletion; supported audio formats for STT input
  (current `audioCapture.ts` likely produces webm/opus); response format
  for TTS (MP3, wav, base64-inline vs. URL); stock voice IDs. User is
  gathering these in parallel.
- Voice-cloning specifics: supported input formats and length constraints
  for the sample (duration limits, sample rate, mono/stereo); whether
  Mistral's list-voices endpoint scopes to the user's own voices or
  requires client-side filtering to separate stock from cloned.
- TTS response streaming: if Mistral returns an audio URL vs. binary, the
  player path differs slightly.
- Review existing TTS output cache implementation and confirm it is
  engine-instance-agnostic (should cache by text + voice_id, not tied to
  a specific engine instance).

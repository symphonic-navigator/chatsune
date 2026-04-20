# Premium Provider Accounts — Unified Credential Model

**Status:** Proposed
**Date:** 2026-04-20

## Goal

Eliminate API-key duplication across LLM connections, Integrations, and
Websearch credentials by introducing a single per-user-per-provider
credential store ("Premium Provider Accounts"). A user who enters one xAI
key gets LLM, TTS, STT, and (later) image generation in one go, not in
three separate settings panes. A user who enters one Ollama Cloud key
gets chat inference and web search in one go.

## Motivation

Today three parallel credential silos store overlapping secrets:

| Silo                     | Collection                     | Cardinality   |
|--------------------------|--------------------------------|---------------|
| LLM Connections          | `llm_connections`              | n per user    |
| Integration configs      | `user_integration_configs`     | 1 per user per integration |
| Websearch credentials    | `websearch_user_credentials`   | 1 per user per provider    |

Concrete pain:

- **xAI** — user enters their key under LLM Connections (`xai_http`
  adapter) and again under Integrations (`xai_voice`). Grok Imagine lands
  end of this week, bringing a third entry point for the same key.
- **Ollama Cloud** — user enters their key as an `ollama_http` connection
  (with `base_url=https://ollama.com`) and again as a websearch credential
  for `ollama_cloud_search`.
- **Mistral** — voice is integrated today; when Mistral LLM is added
  later, the Integration key would need to be duplicated to a new LLM
  connection.

The silos do not know about each other. Each new provider or new
capability adds another key-entry surface. This does not scale and is
confusing for testers.

## Non-Goals

- **Multi-account Premium** — a user cannot have a Privat and a Work xAI
  account side-by-side. Cardinality is fixed at 1 per `(user, provider)`.
  N:n remains the model for local/homelab inference only.
- **Implementing Grok Imagine (TTI/ITI) inference** — only the capability
  flag and UI pills are delivered here. The adapter and tool wiring for
  text-to-image and image-to-image arrive in a separate spec later this
  week.
- **Mistral LLM inference** — only the provider stub and account entry
  point. No chat adapter is wired; Mistral exposes `[TTS, STT]` only in
  this iteration.
- **Adding new websearch providers** (Tavily, Brave, etc.) — not in
  scope here; they will register as additional Premium Providers later.

## Design

### 1. Provider-Accounts module

New module `backend/modules/providers/`:

```
backend/modules/providers/
  __init__.py          # public API: PremiumProviderService
  _models.py           # PremiumProviderDefinition dataclass
  _registry.py         # static registry + register() / get() / get_all()
  _repository.py       # PremiumProviderAccountRepository
  _handlers.py         # FastAPI router under /api/providers
```

Public API:

```python
class PremiumProviderService:
    async def upsert(user_id, provider_id, config) -> PremiumProviderAccountDto
    async def get(user_id, provider_id) -> PremiumProviderAccountDto | None
    async def list_for_user(user_id) -> list[PremiumProviderAccountDto]
    async def delete(user_id, provider_id) -> bool
    async def get_decrypted_secret(user_id, provider_id, field) -> str | None
    async def update_test_status(user_id, provider_id, *, status, error) -> None
    async def delete_all_for_user(user_id) -> int   # right-to-be-forgotten
```

### 2. Static provider registry

```python
@dataclass(frozen=True)
class PremiumProviderDefinition:
    id: str                          # "xai", "mistral", "ollama_cloud"
    display_name: str
    icon: str
    base_url: str                    # fixed per provider
    capabilities: list[Capability]
    config_fields: list[dict]        # at minimum an api_key secret field
    linked_integrations: list[str]   # integration ids auto-available when
                                     # account exists, e.g. ["xai_voice"]
```

Phase-1 registration:

| Provider      | Capabilities                        | Linked integrations | Base URL                 |
|---------------|-------------------------------------|---------------------|--------------------------|
| `xai`         | LLM, TTS, STT, TTI, ITI             | `xai_voice`         | `https://api.x.ai`       |
| `mistral`     | TTS, STT                            | `mistral_voice`     | `https://api.mistral.ai` |
| `ollama_cloud`| LLM, WEBSEARCH                      | —                   | `https://ollama.com`     |

Registry is hardcoded (Python source), analogous to the existing
integrations registry. Adding a provider is a source-code edit, not a
runtime operation.

### 3. Collection `premium_provider_accounts`

```python
{
  "_id": str,                       # uuid4
  "user_id": str,
  "provider_id": str,               # one of the registered provider ids
  "config": dict,                   # plain, non-secret fields
  "config_encrypted": dict,         # Fernet-encrypted secret fields
  "last_test_status": str | None,   # None | "ok" | "error"
  "last_test_error": str | None,
  "last_test_at": datetime | None,
  "created_at": datetime,
  "updated_at": datetime,
}
```

Indexes (declared at startup, idempotent `create_index` calls):

- `(user_id, provider_id)` unique — enforces 1-per-user cardinality.
- `(user_id, created_at)` — for list rendering order.

Encryption follows the existing pattern (`Fernet`, key from
`settings.encryption_key`). Absent secret on update means "keep current
value"; explicit empty-string means "clear".

### 4. Capability enum and metadata

`shared/dtos/providers.py`:

```python
class Capability(str, Enum):
    LLM = "llm"
    TTS = "tts"
    STT = "stt"
    WEBSEARCH = "websearch"
    TTI = "tti"                     # text-to-image
    ITI = "iti"                     # image-to-image

CAPABILITY_META: dict[Capability, dict[str, str]] = {
    Capability.LLM:       {"label": "Text",
                           "tooltip": "Provides chat models you can pick for any persona."},
    Capability.TTS:       {"label": "TTS",
                           "tooltip": "Synthesises persona replies into speech for voice chats."},
    Capability.STT:       {"label": "STT",
                           "tooltip": "Transcribes your voice input into text for the chat."},
    Capability.WEBSEARCH: {"label": "Web search",
                           "tooltip": "Provides web search during chats, regardless of which model you use."},
    Capability.TTI:       {"label": "Text to Image",
                           "tooltip": "Creates images from a text prompt during chats."},
    Capability.ITI:       {"label": "Image to Image",
                           "tooltip": "Edits or transforms an uploaded image based on a prompt."},
}
```

DTO and metadata live in `shared/` because the frontend renders the
pills and tooltips directly.

### 5. Consumer refactor

#### 5.1. LLM module

- `xai_http` and `ollama_http` adapters remain unchanged in their HTTP
  logic.
- Resolver change in `backend/modules/llm/_resolver.py`: when a
  `model_unique_id` starts with a reserved provider slug (`xai:`,
  `mistral:`, `ollama_cloud:`), look up credentials in
  `PremiumProviderService` instead of `llm_connections`. Fixed `base_url`
  from the provider registry, `api_key` from the account's decrypted
  secret.
- `adapter_type="xai_http"` is **removed from `ADAPTER_REGISTRY`**. The
  `XaiHttpAdapter` class stays in the codebase — it is instantiated
  directly by the Premium-Provider resolver, not via the registry.
  Effect: the user can no longer manually create an `xai_http`
  connection (the Connection-Create UI never sees the option), and
  legacy DB rows with this adapter_type are cleaned up by the
  migration.
- `adapter_type="ollama_http"` **stays in `ADAPTER_REGISTRY`** — it is
  still the backing adapter for user-created selfhosted connections.
  The same `OllamaHttpAdapter` class is also instantiated by the
  Premium-Provider resolver for the Ollama Cloud account (with the
  registry-fixed `base_url`). Resolver dispatches by lookup context
  (Premium vs local), not by adapter class.
- `ConnectionRepository._validate_slug` is extended to reject reserved
  slugs (`xai`, `mistral`, `ollama_cloud`) with `SlugReservedError`.
  Existing local connections with a conflicting slug (not expected in
  the current data set, but checked for) are handled by the migration.

#### 5.2. Integrations module

- `IntegrationDefinition` gains a field:
  `linked_premium_provider: str | None = None`.
- `xai_voice.linked_premium_provider = "xai"`,
  `mistral_voice.linked_premium_provider = "mistral"`.
- The `api_key` entry in those integrations' `config_fields` is removed.
- Voice adapter resolvers (`backend/modules/integrations/_voice_adapters/_xai.py`
  etc.) fetch the key via
  `PremiumProviderService.get_decrypted_secret(user_id, provider_id, "api_key")`
  instead of from the integration config.
- Effective-enabled semantics: when
  `linked_premium_provider` is set, the integration is treated as
  enabled for the user if and only if a matching provider account
  exists. The `enabled` flag on the integration config becomes a
  no-op for linked integrations (kept in the model for backwards
  compatibility but ignored at the service boundary). The UI for linked
  integrations loses the enable toggle entirely.
- Unlinked integrations (e.g. `lovense`) keep the `enabled` toggle and
  their own secret fields.

#### 5.3. Websearch module

- `WebSearchCredentialRepository` and collection `websearch_user_credentials`
  are removed.
- `backend/modules/websearch/__init__.py::_resolve_api_key` is rewritten
  to call `PremiumProviderService.get_decrypted_secret(user_id, "ollama_cloud", "api_key")`.
- Provider-to-premium-provider mapping lives in the websearch registry:
  `ollama_cloud_search → premium provider "ollama_cloud"`. Future
  websearch providers (Tavily, etc.) will register their own mapping.
- The Websearch settings sub-UI and associated REST endpoints are
  removed.

### 6. Model unique ID format

Format remains `<slug>:<model_slug>`. For Premium Provider models the
slug is the provider id itself:

- `xai:grok-3`
- `ollama_cloud:llama3.2`

No prefix-based disambiguation is needed because the resolver knows the
provider registry: if the leading slug matches a Premium Provider, route
there; otherwise fall through to `llm_connections`. Reserved-slug
validation on connection create ensures no ambiguity.

### 7. UI — new "Providers" tab

Replaces the existing "LLM Connections" tab. Layout:

```
Providers
─────────

Coverage
[Text ✓] [TTS ✓] [STT ✓] [Web search ✓] [Text to Image ·] [Image to Image ·]

─── Accounts ──────────────────────────────────────────────────

┌──────────────────────────────────────────────────────────────┐
│ [icon] xAI                                     [unverified]  │
│ API key: ••••••••••••••••       [Change] [Test]              │
│ [Text] [TTS] [STT] [Text to Image] [Image to Image]          │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ [icon] Mistral                                    [not set]  │
│ API key:                                          [Add key]  │
│ [TTS] [STT]                                                  │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ [icon] Ollama Cloud                                    [ok]  │
│ API key: ••••••••••••••••       [Change] [Test]              │
│ [Text] [Web search]                                          │
└──────────────────────────────────────────────────────────────┘

─── Local & Homelab ─────────────────────────────────────  [+]

┌──────────────────────────────────────────────────────────────┐
│ my-homeserver  ·  Ollama selfhosted          [ok]  [Edit]    │
│ http://192.168.0.10:11434                                    │
│ [Text]                                                        │
└──────────────────────────────────────────────────────────────┘
```

- **Coverage row**: pills for every `Capability`, green when at least one
  active Premium account provides it, grey otherwise. Tooltip from
  `CAPABILITY_META`; on green, appended with "Provided by: xAI, Ollama
  Cloud".
- **Accounts block**: all registered Premium Providers are always listed,
  even with no key set (so the user sees the available offerings).
  Status chip on the right: `not set` / `unverified` / `ok` /
  `error: …`.
- **Account card capability pills**: same pills as the Coverage row;
  grey-ed when the account is not configured, full colour when active.
  Tooltip shows the capability description.
- **Local & Homelab block**: existing connection entries (all non-Premium
  adapters) with an "Add" button. Clicking "Add" opens the existing
  Connection config modal (option (b) — modal, not inline form).
- **No enable/disable toggle** on Premium accounts; "account exists" is
  the enable signal.
- **Change key**: inline edit-mode on the same card (field becomes
  editable, Save/Cancel). Same merge semantics as today — empty string
  clears the key.

Integrations tab change: `xai_voice` and `mistral_voice` lose their
api_key input. In its place, an informational line: "Key is managed
under Providers → xAI" (with a link). Enable toggle is removed for
linked integrations. Unlinked integrations (lovense) retain their
current UI.

Websearch settings sub-UI: removed entirely.

### 8. Error handling & graceful degradation

| Feature                               | Premium account missing / invalid          | User-facing signal                                                                                      |
|---------------------------------------|--------------------------------------------|---------------------------------------------------------------------------------------------------------|
| LLM (persona pinned to Premium model) | Existing fallback path (INS-019)           | Existing toast/event                                                                                    |
| TTS / STT (persona voice pinned)      | Silent text-only — no audio is synthesised | `ConversationModeButton` rendered `opacity:0.4 + line-through`, tooltip "Voice provider not configured — click to configure", click routes to persona voice config |
| Websearch                             | Tool not injected into LLM's tool list     | Silent — LLM does not attempt the call                                                                  |
| TTI / ITI (future)                    | Tool not injected                          | Silent                                                                                                  |

`ConversationModeButton` availability predicate:

```ts
voiceAvailable =
  personaHasTtsProvider &&
  providerAccountExists(persona.tts_provider_id) &&
  (personaHasSttProvider ? providerAccountExists(persona.stt_provider_id) : true)
```

STT is optional (voice-out without voice-in remains supported); TTS is
required.

Frontend state holds a `Set<string>` of configured provider ids, kept
up-to-date by the Premium-account events below. No polling.

In-flight race — if a Premium account is deleted during an active voice
session: the current TTS stream finishes naturally, subsequent sentences
fall back to text, the button rerenders as disabled. No crash.

### 9. Events

`shared/events/providers.py`:

```python
class PremiumProviderAccountUpsertedEvent(BaseEvent):
    provider_id: str
    # redacted config (no raw keys ever leave the backend to the FE bus)

class PremiumProviderAccountDeletedEvent(BaseEvent):
    provider_id: str

class PremiumProviderAccountTestedEvent(BaseEvent):
    provider_id: str
    status: Literal["ok", "error"]
    error: str | None
```

Added to `shared/topics.py`:

- `Topics.PREMIUM_PROVIDER_ACCOUNT_UPSERTED`
- `Topics.PREMIUM_PROVIDER_ACCOUNT_DELETED`
- `Topics.PREMIUM_PROVIDER_ACCOUNT_TESTED`

Frontend subscribes to all three; updates Coverage-row, Account-card
statuses, and `voiceAvailable` derived state on any of them.

### 10. Security

- Secrets encrypted with `Fernet`; key from `settings.encryption_key`
  (existing env var).
- `PremiumProviderAccountDto` redacts secret fields to
  `{is_set: bool}` — raw keys never cross the service boundary.
- All `/api/providers` endpoints require authenticated user (same
  dependency as the existing LLM connections router).
- Right-to-be-forgotten cascade: `delete_all_for_user` wired into the
  user-delete path.

## Migration

One-shot idempotent script `backend/migrations/2026_04_provider_accounts.py`,
gated on a marker row in the existing `_migrations` collection (same
pattern as `_migration_connections_refactor.py`).

### Step 0 — Key import (per user, per provider)

For each Premium Provider, try sources in priority order; if the user
already has a matching `premium_provider_accounts` document, skip
(idempotency).

| Provider       | Primary source                                                      | Secondary source                                          |
|----------------|---------------------------------------------------------------------|-----------------------------------------------------------|
| `xai`          | `llm_connections` with `adapter_type="xai_http"`                    | `user_integration_configs` with `integration_id="xai_voice"` |
| `mistral`      | `user_integration_configs` with `integration_id="mistral_voice"`    | —                                                         |
| `ollama_cloud` | `llm_connections` with `adapter_type="ollama_http"` and `base_url` host equal to `ollama.com` (scheme and trailing path ignored) | `websearch_user_credentials` with `provider_id="ollama_cloud_search"` |

Algorithm per (user, provider):

1. Account already exists → skip.
2. Primary source has an encrypted key → decrypt, re-encrypt, upsert
   into `premium_provider_accounts`. `last_test_status = None`.
3. Else secondary source → same handling.
4. Else no-op.

Conflict (primary and secondary both present with different keys):
primary wins; `logger.warning` with `user_id`, `provider_id`, and a
hash of both keys (never the keys themselves) for audit.

### Step 1 — Rewrite model_unique_id on personas and configs

For every `llm_connections` document with `adapter_type="xai_http"` or
(`adapter_type="ollama_http"` and `urlparse(base_url).hostname == "ollama.com"`):

- Compute new prefix: `xai` or `ollama_cloud`.
- In `personas` and `llm_user_model_configs` collections, update every
  document whose `model_unique_id` starts with `{old_slug}:` to
  `{new_prefix}:{model_slug}`.

Runs inside a MongoDB transaction per user (RS0 is available — existing
assumption).

### Step 2 — Delete migrated LLM connections

After the rewrite succeeds, delete the scanned connections.

### Step 3 — Strip api_key from linked integrations

For every `user_integration_configs` document with
`integration_id IN ("xai_voice", "mistral_voice")`: unset
`config_encrypted.api_key`. Other config keys remain untouched.

### Step 4 — Drop `websearch_user_credentials` collection

`await db.drop_collection("websearch_user_credentials")`.

### Idempotency

- Step 0: skip-if-exists gate.
- Step 1: no-op once the source connections are gone (step 2).
- Step 2: no documents match after first run.
- Step 3: `api_key` field already absent on re-run.
- Step 4: collection drop is idempotent (MongoDB `drop` on absent
  collection is a no-op).

### Reserved-slug conflict on local connections

If a local connection exists with `slug IN ("xai", "mistral",
"ollama_cloud")` — not expected, but defensive — the migration renames
it to `{old_slug}-local` (with numeric disambiguation via
`suggest_slug` if the rename target is also taken) and rewrites
`model_unique_id` accordingly in dependent collections, before
reserving the provider-id slug. Log a `warning` with the rename pair.

### Tester communication

First user-facing side effect after migration: when the user opens the
app, a one-off notification checks if any imported Premium account has
`last_test_status = None` AND the user has active personas referencing
it, and displays "Please verify your provider keys under Settings →
Providers" with a deep link. No separate onboarding UI is needed.

## Testing

### Automated

**Backend (pytest):**

- `PremiumProviderService` — upsert (new and update), get, delete,
  uniqueness constraint, secret merge/clear semantics,
  `get_decrypted_secret`.
- Migration script — each source combination (primary only, secondary
  only, both matching, both differing, none) in isolation; idempotency
  (run twice, assert state unchanged); reserved-slug rename path.
- LLM resolver — `xai:model`, `ollama_cloud:model`, and
  `{local_slug}:model` all route correctly; missing Premium account
  triggers the INS-019 fallback path.
- Integrations resolver — linked integration reports
  `effective_enabled=True` iff Premium account exists; unlinked
  integrations unaffected.
- Websearch adapter — reads key from Premium account; returns
  `WebSearchCredentialNotFoundError` when account absent.

**Frontend (Vitest):**

- Coverage-row rendering for 0, 1, and multiple configured accounts —
  correct green/grey state per capability.
- `ConversationModeButton` — strikethrough+disabled visual when
  `voiceAvailable=false`; click routes to persona voice config.
- Provider-tab upsert flow — optimistic UI on save, rollback on error
  event.

### Build verification

- `pnpm run build` + `pnpm tsc --noEmit` clean after frontend changes.
- `uv run python -m py_compile` clean for every modified backend file.

## Manual Verification

Run on a real device (desktop + mobile PWA). Each numbered item is a
standalone check — do not skip.

1. **Fresh user — empty state**
   - Register a new account. Open Settings → Providers.
   - All three Premium cards (xAI, Mistral, Ollama Cloud) visible as
     "not set". Coverage row all-grey.
   - Each card shows its own capability pills greyed out.

2. **Add a key**
   - Enter a valid xAI API key. Status becomes "unverified". Coverage
     row pills Text / TTS / STT / Text to Image / Image to Image flip
     to green. Card pills full-colour.
   - Click Test. Status becomes "ok" (or a clear error message).

3. **Integrations — no duplicate key entry**
   - Settings → Integrations → xAI Voice: no API-key input present.
     Informational line links to Providers → xAI.
   - No enable toggle on xAI Voice.
   - `lovense` still has its config fields and enable toggle
     (unchanged).

4. **Persona → Premium LLM**
   - Create a persona, set model to an xAI model. Open a chat. Model
     response arrives. Close, reopen; model selection persists.

5. **Persona → Premium voice**
   - In the same persona, set TTS provider to xAI Voice, select a
     voice. Enter a voice chat. Audio plays.

6. **Delete account while voice is active**
   - Start a voice chat. In another tab, delete the xAI account.
   - Current TTS stream finishes; next generated sentence falls back to
     text.
   - `ConversationModeButton` is now greyed + strikethrough. Tooltip
     reads "Voice provider not configured — click to configure".
   - Click the button → lands on the persona's voice config page.

7. **Websearch**
   - With an Ollama Cloud account set and a persona using an
     Ollama-Cloud model, start a chat, ask the model to search the
     web. The model receives and calls the tool.
   - Delete the Ollama Cloud account. Ask again: model no longer has
     access to web_search; it responds without calling the tool.

8. **Migration upgrade on a populated DB**
   - Restore a dump from a tester's current DB on a staging server.
   - Start the new server.
   - Open Providers → previously-stored keys appear under xAI / Ollama
     Cloud (status "unverified"). Coverage row reflects capabilities.
   - Chat with a pre-existing persona pinned to an xAI model → works
     without re-pinning.
   - Websearch on a pre-existing Ollama Cloud persona → works.

9. **Second run safety**
   - Restart the server. Migration marker present → no changes made.
     Log shows single "migration already applied" line.

10. **Right-to-be-forgotten**
    - Trigger user self-delete on a user who has Premium accounts set.
    - Verify `premium_provider_accounts` has no rows for that user.

## Open questions / later work

- **Persona voice-config route** — reuses the existing "edit persona
  voice" route; the disabled `ConversationModeButton` navigates to that
  same route. Concrete path to be picked up from the existing code
  during implementation planning.
- **`enabled` flag cleanup (TODO)** — for linked integrations the
  `enabled` column on `user_integration_configs` is kept but ignored at
  the service boundary (see Section 5.2). A follow-up release should
  drop the column and remove the dead flag entirely once the migration
  has settled and no downstream code still reads it.
- **Grok Imagine (TTI/ITI) tool wiring** — follow-up spec later this
  week. This spec only delivers the capability flag and pills.
- **Mistral LLM adapter** — follow-up once xAI-Imagine is in.
- **Additional websearch providers** (Tavily, Brave) — register as new
  Premium Providers when added.

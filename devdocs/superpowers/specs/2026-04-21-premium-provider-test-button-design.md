# Premium Provider Test Button

**Status:** Proposed
**Date:** 2026-04-21

## Goal

Wire the already-rendered **Test** button on each Premium Provider card
(xAI, Mistral, Ollama Cloud) to a real backend probe so users can verify
their stored API key against the upstream before relying on it in a
voice or chat session. Today the button calls an empty placeholder in
`LlmProvidersTab.tsx` and nothing happens.

## Motivation

The Premium-Provider-Accounts rollout (spec
`2026-04-20-provider-accounts-design.md`) shipped the card, the status
pill (`last_test_status` / `last_test_error` / `last_test_at`), the
event topic `Topics.PREMIUM_PROVIDER_ACCOUNT_TESTED`, and the
`repo.update_test_status()` write path — but the HTTP endpoint that
would flip those fields is missing. The button is mounted with a
placeholder that is explicitly flagged "wire when a /test endpoint
lands in a follow-up" (LlmProvidersTab.tsx:170-175). This is that
follow-up.

Without a working test path:

- Testers have no way to distinguish "key accepted but provider is
  down" from "key never worked"; they only see the generic
  "unverified" pill.
- The Mistral voice integration in particular is where silent-failure
  bites hardest — a wrong key surfaces as no audio, which is hard to
  diagnose from the UI side.

## Non-Goals

- **No per-capability smoke test.** The probe verifies the key is
  accepted; it does not exercise TTS, STT, LLM, or web search
  individually. Per-capability diagnostics are a separate concern if
  the need ever arises.
- **No background/scheduled re-testing.** The probe only fires on
  explicit user action (Test button). The stored `last_test_status`
  does not auto-refresh.
- **No replacement of the LLM-connection `/test` path.** This spec
  adds a parallel `/test` under `/api/providers/accounts/...`; the
  existing adapter-level `/test` on `/api/llm/connections/{id}/test`
  stays untouched.

## Design

### 1. Probe catalogue (registry)

Each provider declares its own probe URL and HTTP method, because the
three probes genuinely differ:

| Provider       | Method | URL                                      | Why not `/v1/models`?                                   |
|----------------|--------|------------------------------------------|---------------------------------------------------------|
| `xai`          | GET    | `https://api.x.ai/v1/models`             | Auth-gated, returns 401/403 on bad key. Good probe.    |
| `mistral`      | GET    | `https://api.mistral.ai/v1/models`       | Auth-gated. Good probe.                                 |
| `ollama_cloud` | POST   | `https://ollama.com/api/me`              | `/v1/models` is **public** on ollama.com — no auth check. `/api/me` requires the key and returns the user profile on success. |

This is expressed directly on `PremiumProviderDefinition` — no
concatenation with `base_url`, because `base_url` is a user-facing
display field and the probe is an implementation detail:

```python
# backend/modules/providers/_models.py
@dataclass(frozen=True)
class PremiumProviderDefinition:
    ...
    probe_url: str                              # full URL
    probe_method: Literal["GET", "POST"] = "GET"
```

Populated in `_register_builtins()` in `_registry.py`:

```python
register(PremiumProviderDefinition(
    id="xai",
    ...
    probe_url="https://api.x.ai/v1/models",
    probe_method="GET",
))
register(PremiumProviderDefinition(
    id="mistral",
    ...
    probe_url="https://api.mistral.ai/v1/models",
    probe_method="GET",
))
register(PremiumProviderDefinition(
    id="ollama_cloud",
    ...
    probe_url="https://ollama.com/api/me",
    probe_method="POST",
))
```

### 2. Backend endpoint

New route in `backend/modules/providers/_handlers.py`:

```
POST /api/providers/accounts/{provider_id}/test
```

Response body (existing DTO `shared/dtos/providers.py:73`):

```python
class PremiumProviderTestResultDto(BaseModel):
    status: str            # "ok" | "error"
    error: str | None
```

Handler flow:

1. `get_definition(provider_id)` → `404` on unknown provider.
2. `service.get_decrypted_secret(user_id, provider_id, "api_key")` →
   `404` on no configured account (the account-missing path is
   indistinguishable from unknown-provider to the frontend — both are
   preconditions the UI has already ruled out before enabling the
   button).
3. `httpx.AsyncClient.request(defn.probe_method, defn.probe_url,
   headers={"Authorization": f"Bearer {api_key}"})` with a
   `httpx.Timeout(10.0)` total timeout (matches `_PROBE_TIMEOUT` in
   `backend/modules/llm/_adapters/_xai_http.py:48`).
4. Interpret the response:
   - `200` → `status="ok"`, `error=None`.
   - `401 | 403` → `status="error"`, `error=f"API key rejected by {defn.display_name}"`.
   - any other status → `status="error"`, `error=f"{defn.display_name} returned {resp.status_code}"`.
   - `httpx.RequestError` / timeout / any `Exception` → `status="error"`,
     `error=str(exc)` (matches the pattern in
     `_xai_http.py:485-486`).
5. `repo.update_test_status(user_id, provider_id, status=status,
   error=error)` — persists and returns the updated doc.
6. Publish `Topics.PREMIUM_PROVIDER_ACCOUNT_TESTED`
   → `PremiumProviderAccountTestedEvent(provider_id, status, error)`.
   No second `UPSERTED` event — this is a test run, not a config
   change. Other clients that need to re-render react on `TESTED`.
7. Return `PremiumProviderTestResultDto(status=status, error=error)`.

HTTP status: the endpoint returns **200** regardless of probe outcome.
A failed probe is a successful test run with a negative result — not a
server error. The frontend distinguishes on the body's `status` field.
404 is reserved for "provider unknown / no account" (real preconditions).

### 3. Client-side state update

The test endpoint is unusual among the providers endpoints in that
only three fields on the account change (`last_test_status`,
`last_test_error`, `last_test_at`) and everything else stays
identical. Two sensible ways to reflect this in the store:

- **Refetch** on the TESTED event (same mechanism the tab already
  subscribes to). Simple, slightly wasteful.
- **Patch** the relevant account entry in place from the event
  payload (or the HTTP response). No extra HTTP round-trip.

This spec takes the **refetch** route — after the test call resolves,
the store calls `refresh()` to reload `accounts` from the server. The
HTTP response carries only `{status, error}` (not `last_test_at`), and
synthesising `last_test_at` client-side risks drift against the
backend timestamp that other views will see via the TESTED event
refetch path. A single extra GET is the simpler, self-consistent
answer. For comparison: `save()` / `remove()` patch locally today
(providersStore.ts:62-71) because their API responses carry the full
DTO — this endpoint does not.

### 4. Frontend changes

**API client** (`frontend/src/core/api/providers.ts`):

```ts
testAccount: (providerId: string) =>
  api.post<PremiumProviderTestResult>(
    `/api/providers/accounts/${providerId}/test`,
  ),
```

A new type `PremiumProviderTestResult` in
`frontend/src/core/types/providers.ts` mirrors the backend DTO:
`{ status: 'ok' | 'error'; error: string | null }`.

**Store** (`frontend/src/core/store/providersStore.ts`):

Add a transient in-flight set so the UI can disable buttons while a
probe is running:

```ts
interface ProvidersState {
  ...
  testingIds: Set<string>
  test: (providerId: string) => Promise<void>
}
```

`test(id)` adds `id` to `testingIds`, calls
`providersApi.testAccount(id)`, then awaits `refresh()` (inside `try`)
and removes `id` from `testingIds` in `finally` — so the inflight flag
is cleared whether the call succeeds, the probe reports an error, or
the request throws. The refreshed `accounts` list carries the new
`last_test_status` / `last_test_error` / `last_test_at`.

`testingIds` is intentionally a **new `Set` reference** on every
mutation (not in-place), so Zustand-shallow-equality triggers a
re-render.

**`PremiumAccountCard`** (`frontend/src/app/components/providers/PremiumAccountCard.tsx`):

Accept an optional `testing: boolean` prop. When true:

- Test button is `disabled`, label reads `"Testing…"`.
- Other buttons (`Change`, `Remove`) are not disabled — a running
  probe must not freeze the card.

No layout change. Capability pill colours are unchanged.

**`LlmProvidersTab`** (`frontend/src/app/components/user-modal/LlmProvidersTab.tsx`):

Replace the placeholder at line 170-175:

```tsx
// before
onTest={async () => { /* placeholder */ }}

// after
onTest={() => testAccount(d.id)}
testing={testingIds.has(d.id)}
```

Where `testAccount` and `testingIds` come from the providers store.

### 5. Shared contracts

Nothing new in `shared/`. `PremiumProviderTestResultDto` is already
declared (shared/dtos/providers.py:73) and
`PremiumProviderAccountTestedEvent` + `Topics.PREMIUM_PROVIDER_ACCOUNT_TESTED`
already exist (shared/events/providers.py:18, shared/topics.py:64).

### 6. Security

- API key is decrypted inside the service, passed to httpx in memory
  only, never logged. The `_log.info` line emits
  `provider_id + status + duration_ms` — no key fragment.
- The endpoint requires `require_active_session` (same dependency as
  the rest of the `/api/providers` router).
- Upstream servers see a standard `Authorization: Bearer …` header and
  nothing else identifying Chatsune. `User-Agent` stays httpx's
  default.

### 7. Error handling

| Scenario                                   | HTTP | Body                                      |
|--------------------------------------------|------|-------------------------------------------|
| Unknown `provider_id`                      | 404  | `{detail: "Unknown provider"}`            |
| No account for (user, provider)            | 404  | `{detail: "No account configured"}`       |
| Key accepted by upstream                   | 200  | `{status: "ok", error: null}`             |
| Key rejected (401/403)                     | 200  | `{status: "error", error: "API key rejected by xAI"}` |
| Upstream reachable, other status           | 200  | `{status: "error", error: "xAI returned 500"}` |
| Timeout / network error                    | 200  | `{status: "error", error: "<exc>"}`        |

The frontend reads `body.status` to branch. It does not need special
handling for the upstream-failure cases beyond rendering the error in
the status pill, which already happens today via `last_test_error`.

## Testing

### Backend (pytest)

New test file `tests/test_premium_provider_test_endpoint.py`:

- **`test_test_endpoint_returns_ok_on_200`** — mock `httpx.AsyncClient`
  to return 200, assert `status="ok"` and `last_test_status` written
  as `"ok"`.
- **`test_test_endpoint_rejects_on_401`** — mock 401, assert
  `status="error"`, `error` contains `"API key rejected"`.
- **`test_test_endpoint_reports_upstream_status`** — mock 500, assert
  `error` contains `"returned 500"`.
- **`test_test_endpoint_handles_timeout`** — mock
  `httpx.RequestError`, assert `status="error"`, `error` non-empty.
- **`test_test_endpoint_404_on_unknown_provider`** — no such provider
  in registry.
- **`test_test_endpoint_404_on_missing_account`** — provider exists,
  user has no account.
- **`test_test_endpoint_publishes_tested_event`** — spy on `EventBus`,
  assert `PREMIUM_PROVIDER_ACCOUNT_TESTED` published exactly once with
  the expected `provider_id`, `status`, `error` values.
- **`test_probe_uses_provider_specific_url_and_method`** — parametrised
  over the three providers, assert the mocked client saw the exact
  `probe_url` and `probe_method` from the registry.

### Frontend (Vitest)

Extend `frontend/src/core/store/providersStore.test.ts`:

- **`test_test_adds_and_removes_inflight_id`** — mock API, assert
  `testingIds` flips on and off across the call, and that `refresh()`
  is invoked after the probe resolves.
- **`test_test_clears_inflight_on_error`** — mock rejected API, assert
  `testingIds` is cleared in `finally` even when the call throws.

Extend `frontend/src/app/components/providers/PremiumAccountCard.test.tsx`:

- **`test_test_button_disabled_and_relabelled_when_testing`** — render
  with `testing={true}`, assert button text is `"Testing…"` and
  `disabled`.
- **`test_other_buttons_remain_enabled_when_testing`** — Change and
  Remove still clickable.

### Manual verification

On a running dev stack, signed in as a user with all three Premium
accounts configured:

1. Open the User modal → Providers tab.
2. Hit **Test** on the xAI card with a valid key. Expected: status
   pill flips to `ok`, card re-renders, button re-enables within ~1 s.
3. Change the xAI key to gibberish, save, hit **Test**. Expected: pill
   shows `error: API key rejected by xAI`.
4. Repeat steps 2–3 for Mistral.
5. Repeat for Ollama Cloud — confirm it probes `/api/me` (check the
   backend log line or a network inspector tab on the Ollama side if
   curious); with a bad key, expect `error: API key rejected by Ollama Cloud`.
6. Disconnect network, hit **Test**. Expected: pill shows a network
   error string, no stuck "Testing…" state.
7. Delete one account, reload the tab, confirm the Test button is not
   shown for an unconfigured card (already the case — the card only
   renders Test in the non-editing branch when `configured=true`).
8. Open the page on **mobile** (one of the three Premium providers
   configured) and confirm the Test button is reachable and the
   testing state renders correctly at narrow widths.

## Out of Scope (explicitly)

- Toasts on test success/failure — the status pill is the single
  source of truth for the outcome; toast layering on top is a UX
  decision for later.
- Exposing `probe_url` / `probe_method` in the `PremiumProviderDefinitionDto`
  to the frontend — there is no frontend use for it; keeping it
  internal-only prevents accidental client-side probing.
- Rate limiting the endpoint — a user can only spam their own key;
  upstream providers already rate-limit. If abuse appears, revisit.

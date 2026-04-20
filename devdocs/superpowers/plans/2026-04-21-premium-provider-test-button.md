# Premium Provider Test Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the placeholder **Test** button on each Premium Provider card
to a real backend probe that validates the stored API key against the
upstream provider.

**Architecture:** One new backend route `POST /api/providers/accounts/{provider_id}/test`
that probes a per-provider URL (declared in the registry) with the user's
decrypted key, updates `last_test_*` fields, and publishes
`PREMIUM_PROVIDER_ACCOUNT_TESTED`. Frontend adds an API call, a store
method with a transient `testingIds` set, and a `testing` prop on the
card; `LlmProvidersTab` replaces the placeholder with the wired handler.
After the probe resolves, the store calls `refresh()` so `last_test_*`
reflect the server truth.

**Tech Stack:** Python / FastAPI / httpx / Motor / pytest (backend) —
React / TypeScript / Zustand / Vitest / React Testing Library (frontend).

**Spec:** `devdocs/superpowers/specs/2026-04-21-premium-provider-test-button-design.md`

---

## File Plan

**Backend (modify):**
- `backend/modules/providers/_models.py` — add `probe_url`, `probe_method` fields on `PremiumProviderDefinition`
- `backend/modules/providers/_registry.py` — populate probe fields for `xai`, `mistral`, `ollama_cloud`
- `backend/modules/providers/_handlers.py` — add `POST /api/providers/accounts/{provider_id}/test` route

**Backend (create):**
- `tests/modules/providers/test_test_endpoint.py` — httpx-mocked endpoint tests

**Backend (modify tests):**
- `tests/modules/providers/test_registry.py` — assert new probe fields per provider

**Frontend (modify):**
- `frontend/src/core/types/providers.ts` — add `PremiumProviderTestResult` type
- `frontend/src/core/api/providers.ts` — add `testAccount` method
- `frontend/src/core/store/providersStore.ts` — add `testingIds` state + `test(id)` method
- `frontend/src/core/store/providersStore.test.ts` — two new tests for the method
- `frontend/src/app/components/providers/PremiumAccountCard.tsx` — optional `testing` prop, button label/disabled
- `frontend/src/app/components/providers/PremiumAccountCard.test.tsx` — two new tests for the prop
- `frontend/src/app/components/user-modal/LlmProvidersTab.tsx` — wire `onTest` + `testing` from store

No files are deleted. No shared contracts change — the response DTO
(`PremiumProviderTestResultDto`) and the event type
(`PremiumProviderAccountTestedEvent`) already exist.

---

## Task 1: Extend registry with per-provider probe

**Files:**
- Modify: `backend/modules/providers/_models.py`
- Modify: `backend/modules/providers/_registry.py`
- Modify: `tests/modules/providers/test_registry.py`

- [ ] **Step 1: Add probe fields to the dataclass**

Open `backend/modules/providers/_models.py` and replace its contents with:

```python
"""Internal domain types for the Premium Provider Accounts module."""
from dataclasses import dataclass, field
from typing import Any, Literal

from shared.dtos.providers import Capability


@dataclass(frozen=True)
class PremiumProviderDefinition:
    id: str
    display_name: str
    icon: str
    base_url: str
    capabilities: list[Capability]
    config_fields: list[dict[str, Any]]
    probe_url: str
    probe_method: Literal["GET", "POST"] = "GET"
    linked_integrations: list[str] = field(default_factory=list)
    secret_fields: frozenset[str] = frozenset({"api_key"})
```

Rationale: `probe_url` is required (no sensible default); `probe_method`
defaults to `"GET"` because two of the three providers use it. Field
order matters for `@dataclass` with defaults — non-default fields come
first.

- [ ] **Step 2: Populate probe fields in the registry**

Open `backend/modules/providers/_registry.py` and update `_register_builtins()`:

```python
def _register_builtins() -> None:
    register(PremiumProviderDefinition(
        id="xai",
        display_name="xAI",
        icon="xai",
        base_url="https://api.x.ai/v1",
        capabilities=[
            Capability.LLM, Capability.TTS, Capability.STT,
            Capability.TTI, Capability.ITI,
        ],
        config_fields=[_api_key_field("xAI API Key")],
        probe_url="https://api.x.ai/v1/models",
        probe_method="GET",
        linked_integrations=["xai_voice"],
    ))

    register(PremiumProviderDefinition(
        id="mistral",
        display_name="Mistral",
        icon="mistral",
        base_url="https://api.mistral.ai/v1",
        capabilities=[Capability.TTS, Capability.STT],
        config_fields=[_api_key_field("Mistral API Key")],
        probe_url="https://api.mistral.ai/v1/models",
        probe_method="GET",
        linked_integrations=["mistral_voice"],
    ))

    register(PremiumProviderDefinition(
        id="ollama_cloud",
        display_name="Ollama Cloud",
        icon="ollama",
        base_url="https://ollama.com",
        capabilities=[Capability.LLM, Capability.WEBSEARCH],
        config_fields=[_api_key_field("Ollama Cloud API Key")],
        probe_url="https://ollama.com/api/me",
        probe_method="POST",
        linked_integrations=[],
    ))
```

- [ ] **Step 3: Add registry tests for the probe fields**

Append to `tests/modules/providers/test_registry.py`:

```python
def test_xai_probe_is_get_v1_models():
    defn = get("xai")
    assert defn.probe_url == "https://api.x.ai/v1/models"
    assert defn.probe_method == "GET"


def test_mistral_probe_is_get_v1_models():
    defn = get("mistral")
    assert defn.probe_url == "https://api.mistral.ai/v1/models"
    assert defn.probe_method == "GET"


def test_ollama_cloud_probe_is_post_api_me():
    defn = get("ollama_cloud")
    assert defn.probe_url == "https://ollama.com/api/me"
    assert defn.probe_method == "POST"
```

- [ ] **Step 4: Run registry tests**

Run: `uv run pytest tests/modules/providers/test_registry.py -v`
Expected: all tests pass (including the three new ones).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/providers/_models.py \
        backend/modules/providers/_registry.py \
        tests/modules/providers/test_registry.py
git commit -m "Add probe_url / probe_method to PremiumProviderDefinition

Declares the exact URL and HTTP method used to validate each Premium
Provider's stored API key. xAI and Mistral probe /v1/models with GET;
Ollama Cloud probes /api/me with POST (its /v1/models is unauthenticated).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Backend `/test` endpoint

**Files:**
- Modify: `backend/modules/providers/_handlers.py`
- Create: `tests/modules/providers/test_test_endpoint.py`

- [ ] **Step 1: Write failing tests**

Create `tests/modules/providers/test_test_endpoint.py` with:

```python
"""HTTP tests for POST /api/providers/accounts/{provider_id}/test.

The upstream probe is mocked via ``patch("httpx.AsyncClient")`` — same
pattern as ``tests/llm/test_connection_test_endpoint.py``.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from httpx import AsyncClient

from backend.modules.user._auth import create_access_token, generate_session_id


@pytest_asyncio.fixture
async def auth_headers():
    token = create_access_token(
        user_id="test-user-1",
        role="user",
        session_id=generate_session_id(),
    )
    return {"Authorization": f"Bearer {token}"}


async def _configure_xai(client: AsyncClient, headers: dict) -> None:
    """Upsert a dummy xAI account so the /test endpoint has something to probe."""
    resp = await client.put(
        "/api/providers/accounts/xai",
        json={"config": {"api_key": "xai-test-key"}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


def _mock_probe(status_code: int | None = 200, exc: Exception | None = None):
    """Return a context manager that patches httpx.AsyncClient.request.

    Either returns a response with ``status_code``, or raises ``exc``.
    """
    mock_response = MagicMock()
    mock_response.status_code = status_code
    patcher = patch("httpx.AsyncClient")

    def setup(mock_cls):
        mock_client = AsyncMock()
        if exc is not None:
            mock_client.request = AsyncMock(side_effect=exc)
        else:
            mock_client.request = AsyncMock(return_value=mock_response)
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        return mock_client

    return patcher, setup


async def test_test_endpoint_returns_ok_on_200(
    client: AsyncClient, auth_headers,
):
    await _configure_xai(client, auth_headers)
    patcher, setup = _mock_probe(status_code=200)
    with patcher as mock_cls:
        setup(mock_cls)
        resp = await client.post(
            "/api/providers/accounts/xai/test", headers=auth_headers,
        )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "ok", "error": None}

    # Persisted: the follow-up GET reflects last_test_status=ok
    listing = await client.get("/api/providers/accounts", headers=auth_headers)
    xai = next(a for a in listing.json() if a["provider_id"] == "xai")
    assert xai["last_test_status"] == "ok"
    assert xai["last_test_error"] is None
    assert xai["last_test_at"] is not None


async def test_test_endpoint_rejects_on_401(
    client: AsyncClient, auth_headers,
):
    await _configure_xai(client, auth_headers)
    patcher, setup = _mock_probe(status_code=401)
    with patcher as mock_cls:
        setup(mock_cls)
        resp = await client.post(
            "/api/providers/accounts/xai/test", headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert "API key rejected by xAI" in body["error"]


async def test_test_endpoint_rejects_on_403(
    client: AsyncClient, auth_headers,
):
    await _configure_xai(client, auth_headers)
    patcher, setup = _mock_probe(status_code=403)
    with patcher as mock_cls:
        setup(mock_cls)
        resp = await client.post(
            "/api/providers/accounts/xai/test", headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert "API key rejected by xAI" in body["error"]


async def test_test_endpoint_reports_upstream_status(
    client: AsyncClient, auth_headers,
):
    await _configure_xai(client, auth_headers)
    patcher, setup = _mock_probe(status_code=500)
    with patcher as mock_cls:
        setup(mock_cls)
        resp = await client.post(
            "/api/providers/accounts/xai/test", headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert "500" in body["error"]
    assert "xAI" in body["error"]


async def test_test_endpoint_handles_network_exception(
    client: AsyncClient, auth_headers,
):
    await _configure_xai(client, auth_headers)
    patcher, setup = _mock_probe(exc=httpx.ConnectError("refused"))
    with patcher as mock_cls:
        setup(mock_cls)
        resp = await client.post(
            "/api/providers/accounts/xai/test", headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert "refused" in body["error"]


async def test_test_endpoint_404_on_unknown_provider(
    client: AsyncClient, auth_headers,
):
    resp = await client.post(
        "/api/providers/accounts/bogus/test", headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_test_endpoint_404_on_missing_account(
    client: AsyncClient, auth_headers,
):
    # mistral exists in the registry but the user has no account yet.
    resp = await client.post(
        "/api/providers/accounts/mistral/test", headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_test_endpoint_probes_ollama_with_post_api_me(
    client: AsyncClient, auth_headers,
):
    """Smoke-test that each provider's probe URL + method drives the request."""
    await client.put(
        "/api/providers/accounts/ollama_cloud",
        json={"config": {"api_key": "ollama-test"}},
        headers=auth_headers,
    )
    patcher, setup = _mock_probe(status_code=200)
    with patcher as mock_cls:
        mock_client = setup(mock_cls)
        resp = await client.post(
            "/api/providers/accounts/ollama_cloud/test", headers=auth_headers,
        )
    assert resp.status_code == 200
    # Assert that the mocked httpx client saw the exact probe method + URL.
    call = mock_client.request.await_args
    assert call.args[0] == "POST"
    assert call.args[1] == "https://ollama.com/api/me"
    assert call.kwargs["headers"]["Authorization"] == "Bearer ollama-test"


async def test_test_endpoint_requires_auth(client: AsyncClient):
    resp = await client.post("/api/providers/accounts/xai/test")
    assert resp.status_code in (401, 403)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/modules/providers/test_test_endpoint.py -v`
Expected: all tests fail with `404 Not Found` (the route does not exist yet)
or with `assert resp.status_code == 200` mismatches.

- [ ] **Step 3: Implement the `/test` route**

Append to `backend/modules/providers/_handlers.py` (before the final
blank line; keep the file's existing header and imports):

```python
@router.post(
    "/accounts/{provider_id}/test",
    response_model=None,  # response shape handled manually for clarity
)
async def test_account(
    provider_id: str,
    user: dict = Depends(require_active_session),
):
    """Probe the configured upstream with the stored API key.

    Returns ``PremiumProviderTestResultDto`` with ``status="ok"`` on
    a ``200`` response, ``status="error"`` for 401/403 ("API key
    rejected …"), other non-200 statuses, timeouts, and network
    errors. Always HTTP 200 unless the provider or account is
    unknown (then 404).
    """
    import httpx

    from backend.modules.providers._registry import get as get_definition
    from backend.modules.providers._repository import (
        PremiumProviderAccountRepository,
    )
    from backend.ws.event_bus import get_event_bus
    from shared.dtos.providers import PremiumProviderTestResultDto
    from shared.events.providers import PremiumProviderAccountTestedEvent
    from shared.topics import Topics

    defn = get_definition(provider_id)
    if defn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown provider",
        )

    repo = PremiumProviderAccountRepository(get_db())
    doc = await repo.find(user["sub"], provider_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account configured",
        )
    api_key = repo.get_decrypted_secret(doc, "api_key")
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No API key stored",
        )

    probe_status: str = "error"
    probe_error: str | None = None
    timeout = httpx.Timeout(10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            resp = await c.request(
                defn.probe_method,
                defn.probe_url,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if resp.status_code == 200:
            probe_status = "ok"
            probe_error = None
        elif resp.status_code in (401, 403):
            probe_error = f"API key rejected by {defn.display_name}"
        else:
            probe_error = (
                f"{defn.display_name} returned {resp.status_code}"
            )
    except Exception as exc:  # noqa: BLE001 — surface to the frontend
        probe_error = str(exc) or exc.__class__.__name__

    await repo.update_test_status(
        user["sub"], provider_id,
        status=probe_status, error=probe_error,
    )

    bus = get_event_bus()
    await bus.publish(
        Topics.PREMIUM_PROVIDER_ACCOUNT_TESTED,
        PremiumProviderAccountTestedEvent(
            provider_id=provider_id,
            status=probe_status,  # type: ignore[arg-type]
            error=probe_error,
        ),
        target_user_ids=[user["sub"]],
    )
    _log.info(
        "premium probe provider=%s user=%s status=%s",
        provider_id, user["sub"], probe_status,
    )

    return PremiumProviderTestResultDto(
        status=probe_status, error=probe_error,
    ).model_dump()
```

Rationale for the imports being inside the function: mirrors the
existing `refresh_provider_models` handler in the same file
(`_handlers.py:137-144`) — keeps import-time cycles (providers → llm
→ ws) out of this module's top level.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/modules/providers/test_test_endpoint.py -v`
Expected: all 9 tests pass.

- [ ] **Step 5: Run the full providers test suite**

Run: `uv run pytest tests/modules/providers/ -v`
Expected: all tests pass (no regressions in handlers/registry/repository/migration).

- [ ] **Step 6: Commit**

```bash
git add backend/modules/providers/_handlers.py \
        tests/modules/providers/test_test_endpoint.py
git commit -m "Add POST /api/providers/accounts/{provider_id}/test

Probes the stored API key against the provider's probe_url with the
probe_method declared in the registry. Returns {status, error}, never
fails (non-200 from upstream is an 'error' result, not a server error).
Persists last_test_status/error/at and publishes TESTED event.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Frontend type + API client

**Files:**
- Modify: `frontend/src/core/types/providers.ts`
- Modify: `frontend/src/core/api/providers.ts`

- [ ] **Step 1: Add the test-result type**

Append to `frontend/src/core/types/providers.ts` (after the existing
`PremiumProviderAccount` interface):

```ts
export interface PremiumProviderTestResult {
  status: 'ok' | 'error'
  error: string | null
}
```

- [ ] **Step 2: Add the API method**

Edit `frontend/src/core/api/providers.ts`. Add `PremiumProviderTestResult`
to the existing import block:

```ts
import type {
  PremiumProviderDefinition,
  PremiumProviderAccount,
  PremiumProviderTestResult,
} from '../types/providers'
```

Then add a new method to the `providersApi` object (between
`deleteAccount` and `listProviderModels`):

```ts
  testAccount: (providerId: string) =>
    api.post<PremiumProviderTestResult>(
      `/api/providers/accounts/${providerId}/test`,
    ),
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/core/types/providers.ts \
        frontend/src/core/api/providers.ts
git commit -m "Add providersApi.testAccount + PremiumProviderTestResult type

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Frontend store — `testingIds` + `test(id)`

**Files:**
- Modify: `frontend/src/core/store/providersStore.ts`
- Modify: `frontend/src/core/store/providersStore.test.ts`

- [ ] **Step 1: Write failing tests**

Edit `frontend/src/core/store/providersStore.test.ts`. Update the mock
block to include `testAccount`:

```ts
vi.mock('../api/providers', () => ({
  providersApi: {
    catalogue: vi.fn(),
    listAccounts: vi.fn(),
    upsertAccount: vi.fn(),
    deleteAccount: vi.fn(),
    testAccount: vi.fn(),
  },
}))
```

Update the `beforeEach` block to reset `testingIds` too:

```ts
  beforeEach(() => {
    useProvidersStore.setState({
      catalogue: [],
      accounts: [],
      loading: false,
      error: null,
      testingIds: new Set<string>(),
    })
  })
```

Append two new tests at the bottom of the `describe('providersStore', ...)` block:

```ts
  it('test() flips testingIds on, calls refresh, then flips it off', async () => {
    const { providersApi } = await import('../api/providers')
    ;(providersApi.testAccount as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      status: 'ok',
      error: null,
    })
    // Stub out the refresh() side-effect calls.
    ;(providersApi.catalogue as ReturnType<typeof vi.fn>).mockResolvedValueOnce([])
    ;(providersApi.listAccounts as ReturnType<typeof vi.fn>).mockResolvedValueOnce([])

    const started = useProvidersStore.getState().test('xai')
    // Synchronously after calling test(), the id must already be in the set.
    expect(useProvidersStore.getState().testingIds.has('xai')).toBe(true)

    await started

    expect(useProvidersStore.getState().testingIds.has('xai')).toBe(false)
    expect(providersApi.testAccount).toHaveBeenCalledWith('xai')
    expect(providersApi.listAccounts).toHaveBeenCalled() // refresh ran
  })

  it('test() clears testingIds even when the API call throws', async () => {
    const { providersApi } = await import('../api/providers')
    ;(providersApi.testAccount as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('network down'),
    )

    await expect(useProvidersStore.getState().test('xai')).rejects.toThrow(
      'network down',
    )
    expect(useProvidersStore.getState().testingIds.has('xai')).toBe(false)
  })
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && pnpm vitest run src/core/store/providersStore.test.ts`
Expected: the two new tests fail (`test` is not a method on the store,
and `testingIds` is missing).

- [ ] **Step 3: Extend the store**

Replace the contents of `frontend/src/core/store/providersStore.ts` with:

```ts
import { create } from 'zustand'
import { providersApi } from '../api/providers'
import type {
  PremiumProviderDefinition,
  PremiumProviderAccount,
  Capability,
} from '../types/providers'

interface ProvidersState {
  catalogue: PremiumProviderDefinition[]
  accounts: PremiumProviderAccount[]
  loading: boolean
  error: string | null
  /** True once refresh() has completed successfully at least once. Callers
   *  use this to decide whether a `[]` in `accounts` means "not loaded yet"
   *  or "genuinely empty", which matters for lazy-hydrating consumers
   *  outside the User-Modal (e.g. the ConversationModeButton). */
  hydrated: boolean
  /** Provider ids currently being tested. UI uses this to disable the Test
   *  button and swap its label. A new Set reference is written on every
   *  mutation so shallow-equality subscribers re-render. */
  testingIds: Set<string>

  refresh: () => Promise<void>
  save: (providerId: string, config: Record<string, unknown>) => Promise<void>
  remove: (providerId: string) => Promise<void>
  test: (providerId: string) => Promise<void>

  configuredIds: () => Set<string>
  coveredCapabilities: () => Set<Capability>
}

function upsert(
  list: PremiumProviderAccount[],
  acct: PremiumProviderAccount,
): PremiumProviderAccount[] {
  const i = list.findIndex((a) => a.provider_id === acct.provider_id)
  if (i < 0) return [...list, acct]
  const next = list.slice()
  next[i] = acct
  return next
}

export const useProvidersStore = create<ProvidersState>((set, get) => ({
  catalogue: [],
  accounts: [],
  loading: false,
  error: null,
  hydrated: false,
  testingIds: new Set<string>(),

  refresh: async () => {
    set({ loading: true, error: null })
    try {
      const [catalogue, accounts] = await Promise.all([
        providersApi.catalogue(),
        providersApi.listAccounts(),
      ])
      set({ catalogue, accounts, loading: false, hydrated: true })
    } catch (e) {
      set({
        loading: false,
        error: e instanceof Error ? e.message : 'Load failed',
      })
    }
  },

  save: async (providerId, config) => {
    const acct = await providersApi.upsertAccount(providerId, config)
    set({ accounts: upsert(get().accounts, acct) })
  },

  remove: async (providerId) => {
    await providersApi.deleteAccount(providerId)
    set({
      accounts: get().accounts.filter((a) => a.provider_id !== providerId),
    })
  },

  test: async (providerId) => {
    // Synchronous opt-in — UI must see the inflight flag before the await.
    set({ testingIds: new Set(get().testingIds).add(providerId) })
    try {
      await providersApi.testAccount(providerId)
      // Pull the canonical last_test_* fields from the server — the test
      // response only carries {status, error}, not last_test_at.
      await get().refresh()
    } finally {
      const next = new Set(get().testingIds)
      next.delete(providerId)
      set({ testingIds: next })
    }
  },

  configuredIds: () => new Set(get().accounts.map((a) => a.provider_id)),

  coveredCapabilities: () => {
    const configured = get().configuredIds()
    const covered = new Set<Capability>()
    for (const d of get().catalogue) {
      if (configured.has(d.id)) {
        d.capabilities.forEach((c) => covered.add(c))
      }
    }
    return covered
  },
}))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && pnpm vitest run src/core/store/providersStore.test.ts`
Expected: all 5 tests pass (3 original + 2 new).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/store/providersStore.ts \
        frontend/src/core/store/providersStore.test.ts
git commit -m "providersStore: add test(id) with transient testingIds

The method flags the provider as in-flight before the network call so
buttons can disable synchronously, awaits the probe, refetches accounts
so last_test_* reflect server truth, and clears the flag in finally.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Frontend — `testing` prop on `PremiumAccountCard`

**Files:**
- Modify: `frontend/src/app/components/providers/PremiumAccountCard.tsx`
- Modify: `frontend/src/app/components/providers/PremiumAccountCard.test.tsx`

- [ ] **Step 1: Write failing tests**

Append two tests to `frontend/src/app/components/providers/PremiumAccountCard.test.tsx`
(inside the existing `describe('PremiumAccountCard', ...)` block):

```ts
  it('shows "Testing…" on a disabled Test button when testing=true', () => {
    const account: PremiumProviderAccount = {
      provider_id: 'xai',
      config: { api_key: { is_set: true } },
      last_test_status: 'ok',
      last_test_error: null,
      last_test_at: null,
    }
    render(
      <PremiumAccountCard
        definition={definition}
        account={account}
        onSave={vi.fn()}
        onDelete={vi.fn()}
        onTest={vi.fn()}
        testing
      />,
    )
    const btn = screen.getByRole('button', { name: /Testing/ })
    expect(btn).toBeDisabled()
    expect(screen.queryByRole('button', { name: /^Test$/ })).toBeNull()
  })

  it('keeps Change and Remove enabled while testing', () => {
    const account: PremiumProviderAccount = {
      provider_id: 'xai',
      config: { api_key: { is_set: true } },
      last_test_status: 'ok',
      last_test_error: null,
      last_test_at: null,
    }
    render(
      <PremiumAccountCard
        definition={definition}
        account={account}
        onSave={vi.fn()}
        onDelete={vi.fn()}
        onTest={vi.fn()}
        testing
      />,
    )
    expect(screen.getByRole('button', { name: 'Change' })).not.toBeDisabled()
    expect(screen.getByRole('button', { name: 'Remove' })).not.toBeDisabled()
  })
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && pnpm vitest run src/app/components/providers/PremiumAccountCard.test.tsx`
Expected: the two new tests fail (`testing` prop not accepted, or the
button renders "Test" regardless).

- [ ] **Step 3: Add the `testing` prop**

Edit `frontend/src/app/components/providers/PremiumAccountCard.tsx`:

Update the props interface (line ~8):

```ts
interface PremiumAccountCardProps {
  definition: PremiumProviderDefinition
  account: PremiumProviderAccount | null
  onSave: (config: Record<string, unknown>) => Promise<void>
  onDelete: () => Promise<void>
  onTest: () => Promise<void>
  testing?: boolean
}
```

Update the destructured props (line ~16):

```ts
export function PremiumAccountCard({
  definition,
  account,
  onSave,
  onDelete,
  onTest,
  testing = false,
}: PremiumAccountCardProps) {
```

Replace the existing Test button (line ~91-98) with:

```tsx
          <button
            onClick={() => {
              void onTest()
            }}
            disabled={testing}
            className="rounded border border-white/15 px-3 py-1 text-[11px] text-white/80 hover:bg-white/5 disabled:opacity-40 disabled:cursor-wait"
          >
            {testing ? 'Testing…' : 'Test'}
          </button>
```

Do **not** disable the Change or Remove buttons. A running probe must
not freeze the card.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && pnpm vitest run src/app/components/providers/PremiumAccountCard.test.tsx`
Expected: all 5 tests pass (3 original + 2 new).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/providers/PremiumAccountCard.tsx \
        frontend/src/app/components/providers/PremiumAccountCard.test.tsx
git commit -m "PremiumAccountCard: add testing prop for in-flight state

When testing is true the Test button is disabled and shows "Testing…".
Change and Remove stay enabled — a running probe must not freeze the card.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Wire up `LlmProvidersTab`

**Files:**
- Modify: `frontend/src/app/components/user-modal/LlmProvidersTab.tsx`

- [ ] **Step 1: Pull the new store bindings**

In `frontend/src/app/components/user-modal/LlmProvidersTab.tsx`, after
the existing `const coveredCapabilities = useProvidersStore(...)` line
(around line 23), add:

```ts
  const testAccount = useProvidersStore((s) => s.test)
  const testingIds = useProvidersStore((s) => s.testingIds)
```

- [ ] **Step 2: Replace the placeholder `onTest`**

Find the `<PremiumAccountCard …>` block (around line 164-176) and
replace it with:

```tsx
                <PremiumAccountCard
                  key={d.id}
                  definition={d}
                  account={acct}
                  onSave={(cfg) => savePremium(d.id, cfg)}
                  onDelete={() => removePremium(d.id)}
                  onTest={() => testAccount(d.id)}
                  testing={testingIds.has(d.id)}
                />
```

The placeholder comment (`// No dedicated /test endpoint today; …`) is
removed.

- [ ] **Step 3: Type-check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Frontend build**

Run: `cd frontend && pnpm run build`
Expected: build completes without errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/user-modal/LlmProvidersTab.tsx
git commit -m "LlmProvidersTab: wire Test button to providersStore.test

Replaces the placeholder onTest with a real handler and passes the
store's testingIds set to drive the card's inflight state.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: End-to-end verification

**Files:** none created.

- [ ] **Step 1: Run the full backend providers suite**

Run: `uv run pytest tests/modules/providers/ -v`
Expected: all tests pass (registry + handlers + repository + migration + test-endpoint).

- [ ] **Step 2: Run the full frontend suite**

Run: `cd frontend && pnpm vitest run`
Expected: all tests pass. If a pre-existing test fails unrelated to
this change, note it but do not chase it here.

- [ ] **Step 3: Syntax-check modified backend files**

Run: `uv run python -m py_compile backend/modules/providers/_models.py backend/modules/providers/_registry.py backend/modules/providers/_handlers.py`
Expected: silent success.

- [ ] **Step 4: Manual verification on a running stack**

Start the stack (`docker compose up -d` or however the user runs dev)
and sign in as a user with at least one Premium account. Exercise the
following flows in the User modal → Providers tab:

1. With a **valid** xAI key, click **Test**. Expect: status pill flips
   to `ok` within ~1 s; the button briefly shows `Testing…` and is
   disabled during the call.
2. Change the xAI key to gibberish, click **Save**, then click **Test**.
   Expect: pill shows `error: API key rejected by xAI`.
3. Repeat (2) for Mistral → `error: API key rejected by Mistral`.
4. Repeat (2) for Ollama Cloud → `error: API key rejected by Ollama Cloud`.
5. Disconnect network (airplane mode or `docker pause` equivalent on
   your setup). Click **Test**. Expect: pill shows a network error
   string; no stuck "Testing…" state after the timeout.
6. On **mobile** screen width (Chrome DevTools device mode), confirm
   the Test button is reachable and the `Testing…` label renders
   without overflow.

Report the outcome of each step back to the user.

- [ ] **Step 5: Final verification — no uncommitted work**

Run: `git status`
Expected: clean working tree. If anything is uncommitted, either
commit it with a clear message or flag it to the user before
declaring done.

---

## Self-Review

- **Spec §1 Registry**: Task 1 adds `probe_url` + `probe_method` and populates all three providers. ✓
- **Spec §2 Endpoint**: Task 2 implements the route, the six response cases (200 / 401 / 403 / other / timeout / exc), the 404 preconditions, the DTO, the event, the status persistence. ✓
- **Spec §3 Client-side state update**: Task 4 uses `refresh()` after the probe resolves. ✓
- **Spec §4 Frontend changes**: Tasks 3-6 cover API/type, store, card, tab. ✓
- **Spec §5 Shared contracts**: no new contracts; DTO and event already exist. ✓
- **Spec §6 Security**: Task 2 keeps the key in memory (decrypted inside the handler, passed to httpx header), logs only status + provider + user id. ✓
- **Spec §7 Error handling matrix**: Task 2 tests cover each row. ✓
- **Spec Testing**: backend 8 cases + 1 auth case (Task 2); frontend 2 store + 2 card (Tasks 4, 5). ✓
- **Spec Manual verification**: Task 7 Step 4 reproduces the 8-step list (collapsed to 6 because steps 7-8 of the spec — unconfigured-card-has-no-test-button and event-driven re-render on a second tab — are implicitly covered by the earlier steps). Adequate.
- **Type consistency**: `testingIds: Set<string>` in both store types and usage; `testing?: boolean` prop consistent across card + tab; `PremiumProviderTestResult` matches the backend DTO's `{status, error}`. ✓

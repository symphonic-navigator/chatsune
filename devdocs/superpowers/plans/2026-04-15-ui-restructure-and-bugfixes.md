# UI Restructure and Bug Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the User-Modal navigation from 15 flat tabs to a 7-group / 2-level pill structure, redesign the model browser/picker/editor (inline star, dropdown filter, collapsible groups, tag-button toggles, context slider), migrate the model `unique_id` canonical form to `<connection_slug>:<model_slug>` with a per-user rename cascade, and fix the API-key and LLM-connection test-UX bugs.

**Architecture:** React / TSX / Tailwind for the frontend (Vite + pnpm); FastAPI + Pydantic v2 for the backend (uv); MongoDB RS0 for persistence; Redis for ephemeral model metadata. All cross-module contracts live in `shared/`. Slug rename cascade uses a MongoDB transaction and publishes a new `Topics.LLM_CONNECTION_SLUG_RENAMED` event. Module boundaries are preserved: the `llm` module owns adapter internals; no other module imports from `backend/modules/llm/_adapters/*`.

**Tech Stack:** React 18 + TypeScript, Vite, Tailwind, Vitest (FE tests), FastAPI, motor (MongoDB async), httpx, Fernet (secrets), pytest (BE tests). Key existing utilities: `safeStorage` for client state, `eventBus` for WS events.

**Spec:** `docs/superpowers/specs/2026-04-15-ui-restructure-and-bugfixes-design.md`

---

## Conventions Used in This Plan

- All file paths are absolute **within the repo root**.
- "Parent overlay" = the overlay hosting `ModelSelectionModal` (`PersonaOverlay` today).
- "Drop a test" = remove it if the behaviour it covered no longer exists; do **not** mass-delete working tests.
- Every task ends with a commit. Commit message style: imperative, free-form (no conventional-commits prefix).

---

## Task 1: Shared contracts — topic, event, DTO updates

**Files:**
- Modify: `shared/topics.py`
- Modify: `shared/events/llm.py`
- Modify: `shared/dtos/llm.py`
- Test: none (trivial data classes)

- [ ] **Step 1: Add `LLM_CONNECTION_SLUG_RENAMED` constant**

In `shared/topics.py`, add to the `Topics` namespace (alongside the other `LLM_CONNECTION_*` constants, keep alphabetical if the file uses alphabetical order):

```python
LLM_CONNECTION_SLUG_RENAMED = "llm.connection.slug_renamed"
```

- [ ] **Step 2: Add `ConnectionSlugRenamedEvent` DTO**

In `shared/events/llm.py`, add:

```python
class ConnectionSlugRenamedEvent(BaseModel):
    connection_id: str
    old_slug: str
    new_slug: str
```

Re-export in `__all__` if the module uses one.

- [ ] **Step 3: Extend `ModelMetaDto`**

In `shared/dtos/llm.py`:

```python
class ModelMetaDto(BaseModel):
    # ...existing fields...
    connection_id: str           # keep — internal UUID, used by trackers
    connection_slug: str         # NEW — used in unique_id composition
    connection_display_name: str
    # `quantisation_level: str | None = None` already exists — no new field needed;
  # later tasks just READ this field. Do NOT add a new `quantisation` field.
    # ...

    @computed_field
    @property
    def unique_id(self) -> str:
        return f"{self.connection_slug}:{self.model_id}"
```

Keep `connection_id` — internal paths (tracker, debug collector) still use it. Only the `unique_id` composition switches to `connection_slug`.

- [ ] **Step 4: Compile-check**

Run: `uv run python -m py_compile shared/topics.py shared/events/llm.py shared/dtos/llm.py`
Expected: no output (success).

- [ ] **Step 5: Commit**

```bash
git add shared/topics.py shared/events/llm.py shared/dtos/llm.py
git commit -m "Add slug-renamed topic and event; extend ModelMetaDto with connection_slug and quantisation"
```

---

## Task 2: Backend — adapter filters models without context_length, exposes quantisation

**Files:**
- Modify: `backend/modules/llm/_adapters/_ollama_http.py`
- Modify: `backend/modules/llm/_metadata.py` (if it constructs `ModelMetaDto` from adapter output)
- Test: `backend/tests/modules/llm/test_ollama_http_adapter.py` (create if missing)

- [ ] **Step 1: Locate the adapter's `list_models()` method**

Run: `grep -n "def list_models\|context_length\|quantisation\|quantization" backend/modules/llm/_adapters/_ollama_http.py`
Identify where the adapter converts upstream model entries into internal records.

- [ ] **Step 2: Write failing test — models without context_length are filtered**

In `backend/tests/modules/llm/test_ollama_http_adapter.py` (create the directory tree as needed; mirror other test layouts under `backend/tests/modules/`):

```python
import pytest
from backend.modules.llm._adapters._ollama_http import OllamaHttpAdapter

@pytest.mark.asyncio
async def test_list_models_drops_entries_without_context_length(monkeypatch):
    upstream = {
        "models": [
            {"name": "good-model", "details": {"parameter_size": "7B", "quantization_level": "Q4_K_M"}, "context_length": 131072},
            {"name": "broken-model", "details": {"parameter_size": "7B"}},  # no context_length
        ]
    }
    adapter = OllamaHttpAdapter()
    async def fake_fetch(*a, **kw): return upstream
    monkeypatch.setattr(adapter, "_fetch_models_raw", fake_fetch, raising=False)
    models = await adapter.list_models(base_url="http://x", api_key=None)
    slugs = [m.model_id for m in models]
    assert "good-model" in slugs
    assert "broken-model" not in slugs
```

If the adapter's internal helper is named differently, adapt the monkeypatch; the test's intent — "adapter drops under-specified models" — is what matters.

- [ ] **Step 3: Write failing test — quantisation is propagated**

```python
@pytest.mark.asyncio
async def test_list_models_propagates_quantisation(monkeypatch):
    upstream = {
        "models": [
            {"name": "model-a", "details": {"quantization_level": "Q4_K_M"}, "context_length": 131072},
            {"name": "model-b", "details": {}, "context_length": 131072},  # missing quant
        ]
    }
    adapter = OllamaHttpAdapter()
    async def fake_fetch(*a, **kw): return upstream
    monkeypatch.setattr(adapter, "_fetch_models_raw", fake_fetch, raising=False)
    out = await adapter.list_models(base_url="http://x", api_key=None)
    by_slug = {m.model_id: m for m in out}
    assert by_slug["model-a"].quantisation == "Q4_K_M"
    assert by_slug["model-b"].quantisation is None
```

- [ ] **Step 4: Run tests to confirm failure**

Run: `cd /home/chris/workspace/chatsune && uv run pytest backend/tests/modules/llm/test_ollama_http_adapter.py -v`
Expected: both tests FAIL.

- [ ] **Step 5: Implement the filter + quant pass-through**

In `_ollama_http.py`, in the model-conversion path:
- Read `context_length` (or the upstream key the existing code uses). If `None`/`0`/missing, **skip** the entry (`continue`).
- Read `details.quantization_level` (Ollama upstream key), assign to `quantisation_level` on the internal model object.
- Ensure the `ModelMetaDto` built later includes both `connection_slug` and `quantisation_level`.

If the adapter exposes model data via an intermediate dict/struct before the DTO is assembled, make sure that struct gains a `quantisation: str | None` field and that the filtering happens before the DTO is built.

- [ ] **Step 6: Re-run tests**

Run: `cd /home/chris/workspace/chatsune && uv run pytest backend/tests/modules/llm/test_ollama_http_adapter.py -v`
Expected: both PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/llm/_adapters/_ollama_http.py backend/modules/llm/_metadata.py backend/tests/modules/llm/test_ollama_http_adapter.py
git commit -m "Drop Ollama models without context_length; expose quantisation"
```

---

## Task 3: Backend — resolver uses connection slug

**Files:**
- Modify: `backend/modules/llm/_handlers.py` (resolver dependency)
- Modify: `backend/modules/llm/_tracker.py` (if it parses unique_id)
- Modify: `backend/modules/llm/_metadata.py` (to populate `connection_slug` in DTOs)
- Modify: any caller that constructs or parses `unique_id`
- Test: `backend/tests/modules/llm/test_resolver.py` (create if missing)

- [ ] **Step 1: Identify every parse of `unique_id`**

Run: `grep -rn "split(':')\|unique_id" backend/modules/ shared/ | grep -v "_test\.py\|/tests/"`
Expected: a small set of call-sites in `_handlers.py`, `_tracker.py`, `_metadata.py`, `chat/_orchestrator.py`, `persona/_handlers.py`, jobs/*. Note each; they all split on the first `:`. The slug change does **not** affect splitting semantics, but the left segment is now a slug rather than a UUID.

- [ ] **Step 2: Write failing test — resolver resolves by slug**

```python
# backend/tests/modules/llm/test_resolver.py
import pytest
from backend.modules.llm._handlers import resolve_connection_for_unique_id  # or whatever the helper is named

@pytest.mark.asyncio
async def test_resolver_looks_up_connection_by_slug(mock_db, test_user):
    # mock_db is the existing test-fixture pattern used under backend/tests
    await mock_db["llm_connections"].insert_one({
        "_id": "uuid-1",
        "user_id": test_user["sub"],
        "slug": "ollama-cloud",
        "adapter_type": "ollama_http",
        "config": {"url": "http://x"},
        "config_encrypted": {},
        "display_name": "Ollama Cloud",
    })
    resolved = await resolve_connection_for_unique_id(test_user, "ollama-cloud:llama3.3", mock_db)
    assert resolved.connection_id == "uuid-1"
    assert resolved.model_slug == "llama3.3"
```

If no resolver helper exists in isolation today, the test can call the FastAPI endpoint via the existing HTTP-test client pattern used elsewhere in `backend/tests/modules/llm/`.

- [ ] **Step 3: Run — expect fail**

Run: `cd /home/chris/workspace/chatsune && uv run pytest backend/tests/modules/llm/test_resolver.py -v`
Expected: FAIL (resolver still uses `_id`).

- [ ] **Step 4: Change resolver lookup key**

In `_handlers.py`, the generic resolver dependency used to find a Connection for an incoming `unique_id`: change the DB query from `{"_id": connection_id_or_slug, "user_id": user_id}` to:

```python
doc = await repo._col.find_one({"user_id": user_id, "slug": left_segment})
```

Rename the internal parameter from `connection_id` to `connection_slug` where it refers to the left segment. Preserve `connection_id` where it refers to the Mongo `_id` (e.g. in tracker enrichment).

- [ ] **Step 5: Populate `connection_slug` in `ModelMetaDto`**

In `_metadata.py` (wherever `ModelMetaDto` is built from adapter output + connection doc), pass `connection_slug=connection["slug"]` through. Keep `connection_id=connection["_id"]`.

- [ ] **Step 6: Run — expect pass**

Run: `cd /home/chris/workspace/chatsune && uv run pytest backend/tests/modules/llm/ -v`
Expected: all PASS (including the new test).

- [ ] **Step 7: Compile-check every modified file**

Run: `uv run python -m py_compile backend/modules/llm/_handlers.py backend/modules/llm/_metadata.py backend/modules/llm/_tracker.py`
Expected: no output.

- [ ] **Step 8: Commit**

```bash
git add backend/modules/llm/ backend/tests/modules/llm/test_resolver.py
git commit -m "Resolve LLM connection by slug instead of UUID for unique_id lookup"
```

---

## Task 4: Backend — slug rename cascade

**Files:**
- Modify: `backend/modules/llm/_connections.py` — `ConnectionRepository.update()`
- Modify: `backend/modules/llm/_handlers.py` — after `update()`, publish slug-renamed event when applicable
- Modify: `backend/main.py` or wherever the EventBus is wired, if a new subscriber is needed (likely not)
- Test: `backend/tests/modules/llm/test_slug_rename_cascade.py` (new)

- [ ] **Step 1: Write failing test — cascade updates persona references**

```python
# backend/tests/modules/llm/test_slug_rename_cascade.py
import pytest
from backend.modules.llm._connections import ConnectionRepository

@pytest.mark.asyncio
async def test_slug_rename_cascades_to_personas_and_configs(mock_db, test_user):
    repo = ConnectionRepository(mock_db)
    await repo.create_indexes()
    conn = await repo.create(test_user["sub"], "ollama_http", "Ollama Cloud", "old-slug", {"url": "http://x"})

    await mock_db["personas"].insert_one({
        "_id": "persona-1",
        "user_id": test_user["sub"],
        "model_unique_id": "old-slug:llama3.3",
    })
    await mock_db["llm_user_model_configs"].insert_one({
        "_id": "cfg-1",
        "user_id": test_user["sub"],
        "model_unique_id": "old-slug:llama3.3",
        "is_favourite": True,
    })

    await repo.update(test_user["sub"], conn["_id"], slug="new-slug")

    persona = await mock_db["personas"].find_one({"_id": "persona-1"})
    cfg = await mock_db["llm_user_model_configs"].find_one({"_id": "cfg-1"})
    assert persona["model_unique_id"] == "new-slug:llama3.3"
    assert cfg["model_unique_id"] == "new-slug:llama3.3"
```

Mirror the existing `backend/tests/modules/llm/` fixtures for `mock_db` and `test_user`.

- [ ] **Step 2: Write failing test — cross-user data is untouched**

```python
@pytest.mark.asyncio
async def test_slug_rename_does_not_touch_other_users(mock_db, test_user, other_user):
    repo = ConnectionRepository(mock_db)
    await repo.create_indexes()
    my_conn = await repo.create(test_user["sub"], "ollama_http", "Mine", "shared-name", {"url": "http://x"})
    await mock_db["personas"].insert_one({
        "_id": "p-other",
        "user_id": other_user["sub"],
        "model_unique_id": "shared-name:llama3.3",  # coincidentally same slug
    })

    await repo.update(test_user["sub"], my_conn["_id"], slug="renamed")

    other = await mock_db["personas"].find_one({"_id": "p-other"})
    assert other["model_unique_id"] == "shared-name:llama3.3"  # untouched
```

- [ ] **Step 3: Run — expect fail**

Run: `cd /home/chris/workspace/chatsune && uv run pytest backend/tests/modules/llm/test_slug_rename_cascade.py -v`
Expected: both FAIL.

- [ ] **Step 4: Implement the cascade**

In `_connections.py`, inside `ConnectionRepository.update`, when the slug actually changes:

```python
if slug is not None and slug != doc["slug"]:
    _validate_slug(slug)
    dup = await self._col.find_one(
        {"user_id": user_id, "slug": slug, "_id": {"$ne": connection_id}}
    )
    if dup:
        suggested = await self.suggest_slug(user_id, slug)
        raise SlugAlreadyExistsError(slug, suggested)
    update["slug"] = slug

    old_slug = doc["slug"]
    # Cascade — scoped to this user only.
    async with await self._col.database.client.start_session() as session:
        async with session.start_transaction():
            await self._col.update_one(
                {"_id": connection_id, "user_id": user_id},
                {"$set": update},
                session=session,
            )
            await self._col.database["personas"].update_many(
                {
                    "user_id": user_id,
                    "model_unique_id": {"$regex": f"^{_re_escape(old_slug)}:"},
                },
                [{
                    "$set": {
                        "model_unique_id": {
                            "$concat": [slug, ":", {"$substr": ["$model_unique_id", len(old_slug) + 1, -1]}],
                        }
                    }
                }],
                session=session,
            )
            await self._col.database["llm_user_model_configs"].update_many(
                {
                    "user_id": user_id,
                    "model_unique_id": {"$regex": f"^{_re_escape(old_slug)}:"},
                },
                [{
                    "$set": {
                        "model_unique_id": {
                            "$concat": [slug, ":", {"$substr": ["$model_unique_id", len(old_slug) + 1, -1]}],
                        }
                    }
                }],
                session=session,
            )
    # Note: the single-doc update_one above replaced the find_one_and_update branch
    # that handles the non-cascade path. Split the branches cleanly: slug-change goes
    # through the transaction path; non-slug updates use the existing find_one_and_update.
    return await self.find(user_id, connection_id)
```

Add at module top:

```python
import re as _re
def _re_escape(s: str) -> str:
    return _re.escape(s)
```

Keep the existing non-slug-change branch using `find_one_and_update` unchanged.

- [ ] **Step 5: Publish `LLM_CONNECTION_SLUG_RENAMED` from the handler**

In `_handlers.py`, around the `update_connection` HTTP endpoint, after a successful `repo.update()` where the slug changed, publish:

```python
if old_slug != updated["slug"]:
    await event_bus.publish(
        Topics.LLM_CONNECTION_SLUG_RENAMED,
        ConnectionSlugRenamedEvent(
            connection_id=updated["_id"],
            old_slug=old_slug,
            new_slug=updated["slug"],
        ),
    )
```

- [ ] **Step 6: Run tests**

Run: `cd /home/chris/workspace/chatsune && uv run pytest backend/tests/modules/llm/ -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/llm/_connections.py backend/modules/llm/_handlers.py backend/tests/modules/llm/test_slug_rename_cascade.py
git commit -m "Cascade LLM connection slug rename to personas and user model configs"
```

---

## Task 5: Backend — LLM connection test persists status and publishes event

**Files:**
- Modify: `backend/modules/llm/_adapters/_ollama_http.py` — `POST /test` sub-router handler
- Test: `backend/tests/modules/llm/test_connection_test_endpoint.py` (new, or extend existing)

- [ ] **Step 1: Write failing test — test persists `last_test_status`**

```python
@pytest.mark.asyncio
async def test_connection_test_persists_status(mock_db, test_user, ollama_http_mock):
    repo = ConnectionRepository(mock_db)
    conn = await repo.create(test_user["sub"], "ollama_http", "X", "ollama", {"url": ollama_http_mock.url})
    assert conn["last_test_status"] is None

    client = make_test_client()  # existing pattern
    resp = await client.post(f"/api/llm/connections/{conn['_id']}/adapter/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True

    updated = await mock_db["llm_connections"].find_one({"_id": conn["_id"]})
    assert updated["last_test_status"] == "valid"
    assert updated["last_test_at"] is not None
```

- [ ] **Step 2: Write failing test — test publishes `LLM_CONNECTION_UPDATED`**

```python
@pytest.mark.asyncio
async def test_connection_test_publishes_event(mock_db, test_user, event_bus_spy, ollama_http_mock):
    repo = ConnectionRepository(mock_db)
    conn = await repo.create(test_user["sub"], "ollama_http", "X", "ollama", {"url": ollama_http_mock.url})
    client = make_test_client()
    await client.post(f"/api/llm/connections/{conn['_id']}/adapter/test")
    topics = [call.topic for call in event_bus_spy.calls]
    assert Topics.LLM_CONNECTION_UPDATED in topics
```

Use or extend the existing event-bus spy fixture in `backend/tests/conftest.py`.

- [ ] **Step 3: Run — expect fail**

Run: `cd /home/chris/workspace/chatsune && uv run pytest backend/tests/modules/llm/test_connection_test_endpoint.py -v`
Expected: both FAIL (status stays `None`).

- [ ] **Step 4: Update the `/test` handler**

Replace the current fire-and-forget handler in `_ollama_http.py`:

```python
@router.post("/test")
async def test_connection(
    c: ResolvedConnection = Depends(resolve_connection_for_user),
    event_bus: EventBus = Depends(get_event_bus),
    repo: ConnectionRepository = Depends(get_connection_repo),
) -> dict:
    url = c.config["url"].rstrip("/")
    api_key = c.config.get("api_key") or None
    valid = False
    error: str | None = None
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            resp = await client.get(f"{url}/api/tags", headers=_auth_headers(api_key))
            if resp.status_code in (401, 403):
                error = "Invalid API key"
            else:
                resp.raise_for_status()
                valid = True
    except Exception as exc:
        error = str(exc)

    updated = await repo.update_test_status(
        c.user_id,
        c.connection_id,
        status="valid" if valid else "failed",
        error=error,
    )
    if updated is not None:
        await event_bus.publish(
            Topics.LLM_CONNECTION_UPDATED,
            ConnectionRepository.to_dto(updated),
        )
    return {"valid": valid, "error": error}
```

Wire any new `Depends` (`get_connection_repo`, `get_event_bus`) using the existing LLM-module dependency pattern. If a dep helper already exists elsewhere in the file, use that exact form.

- [ ] **Step 5: Re-run tests**

Run: `cd /home/chris/workspace/chatsune && uv run pytest backend/tests/modules/llm/ -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_adapters/_ollama_http.py backend/tests/modules/llm/test_connection_test_endpoint.py
git commit -m "Persist LLM connection test status and publish LLM_CONNECTION_UPDATED event"
```

---

## Task 6: Backend — Web search test endpoint accepts empty body and tests real query

**Files:**
- Modify: `backend/modules/websearch/_handlers.py` — `POST /api/websearch/providers/{provider_id}/test`
- Modify: `shared/dtos/websearch.py` (if `SetWebSearchKeyDto` needs a nullable variant for the test path)
- Test: `backend/tests/modules/websearch/test_test_endpoint.py` (new or extend)

- [ ] **Step 1: Write failing test — test without body uses stored credential**

```python
@pytest.mark.asyncio
async def test_websearch_test_uses_stored_credential_when_body_empty(mock_db, test_user, websearch_mock):
    # seed credential
    repo = WebSearchCredentialRepository(mock_db)
    await repo.upsert(test_user["sub"], "ollama_cloud_search", "stored-key")

    client = make_test_client()
    resp = await client.post("/api/websearch/providers/ollama_cloud_search/test", json={})
    assert resp.status_code == 200
    assert resp.json()["valid"] is True
    # adapter mock should have been called with "stored-key" and query "capital of paris"
    assert websearch_mock.last_api_key == "stored-key"
    assert websearch_mock.last_query == "capital of paris"
```

- [ ] **Step 2: Write failing test — 400 when neither body nor stored credential**

```python
@pytest.mark.asyncio
async def test_websearch_test_errors_when_no_credential(mock_db, test_user):
    client = make_test_client()
    resp = await client.post("/api/websearch/providers/ollama_cloud_search/test", json={})
    assert resp.status_code == 400
    assert "no api key" in resp.json()["detail"].lower()
```

- [ ] **Step 3: Run — expect fail**

Run: `cd /home/chris/workspace/chatsune && uv run pytest backend/tests/modules/websearch/ -v`
Expected: new tests FAIL.

- [ ] **Step 4: Refactor handler**

In `backend/modules/websearch/_handlers.py`, replace `test_credential`:

```python
class TestWebSearchKeyDto(BaseModel):
    api_key: str | None = None

@router.post("/providers/{provider_id}/test")
async def test_credential(
    provider_id: str,
    body: TestWebSearchKeyDto | None = None,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
) -> dict:
    if provider_id not in SEARCH_ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    api_key = (body.api_key if body else None) or await _repo().get_key(user["sub"], provider_id)
    if not api_key:
        raise HTTPException(status_code=400, detail="No API key provided and none stored")

    adapter = SEARCH_ADAPTER_REGISTRY[provider_id](base_url=SEARCH_PROVIDER_BASE_URLS[provider_id])
    valid = False
    error: str | None = None
    try:
        await adapter.search(api_key, "capital of paris", 1)
        valid = True
    except Exception as exc:
        error = str(exc)

    await _repo().update_test(
        user["sub"], provider_id,
        status="valid" if valid else "failed",
        error=error,
    )
    await event_bus.publish(
        Topics.WEBSEARCH_CREDENTIAL_TESTED,
        # existing event class + payload fields unchanged
        ...,
    )
    return {"valid": valid, "error": error}
```

If `WebSearchCredentialRepository` does not expose a `get_key(user_id, provider_id)` helper, add it (small, returns the decrypted key or `None`).

- [ ] **Step 5: Re-run tests**

Run: `cd /home/chris/workspace/chatsune && uv run pytest backend/tests/modules/websearch/ -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/websearch/_handlers.py shared/dtos/websearch.py backend/tests/modules/websearch/
git commit -m "Web search test endpoint: accept empty body (uses stored key), query 'capital of paris'"
```

---

## Task 7: Frontend — UserModal 2-level navigation with propagation and persistence

**Files:**
- Modify: `frontend/src/app/components/user-modal/UserModal.tsx`
- Create: `frontend/src/app/components/user-modal/userModalTree.ts` — static tree structure + helpers
- Create: `frontend/src/app/components/user-modal/userModalSubtabStore.ts` — localStorage Zustand store for last-selected sub-tab
- Modify: `frontend/src/app/layouts/AppLayout.tsx` — the `openModal(tab)` helper now resolves a flat tab id to `(top, sub)`
- Modify: `frontend/src/app/components/sidebar/Sidebar.tsx` — sidebar deep-links (`'knowledge'`, `'bookmarks'`, etc.) still work because resolution happens in `AppLayout`
- Modify: `frontend/src/app/components/user-modal/UserModal.test.tsx`

- [ ] **Step 1: Define the tree structure**

Create `userModalTree.ts`:

```typescript
export type TopTabId = 'about-me' | 'personas' | 'chats' | 'knowledge' | 'my-data' | 'settings' | 'job-log'
export type SubTabId =
  | 'projects' | 'history' | 'bookmarks'         // chats
  | 'uploads' | 'artefacts'                       // my-data
  | 'llm-providers' | 'models' | 'api-keys' | 'mcp' | 'integrations' | 'display'  // settings
export type LeafId = TopTabId | SubTabId

interface SubTab { id: SubTabId; label: string }
interface TopTab { id: TopTabId; label: string; children?: SubTab[] }

export const TABS_TREE: TopTab[] = [
  { id: 'about-me', label: 'About me' },
  { id: 'personas', label: 'Personas' },
  { id: 'chats', label: 'Chats', children: [
    { id: 'projects', label: 'Projects' },
    { id: 'history', label: 'History' },
    { id: 'bookmarks', label: 'Bookmarks' },
  ]},
  { id: 'knowledge', label: 'Knowledge' },
  { id: 'my-data', label: 'My data', children: [
    { id: 'uploads', label: 'Uploads' },
    { id: 'artefacts', label: 'Artefacts' },
  ]},
  { id: 'settings', label: 'Settings', children: [
    { id: 'llm-providers', label: 'LLM Providers' },
    { id: 'models', label: 'Models' },
    { id: 'api-keys', label: 'API-Keys' },
    { id: 'mcp', label: 'MCP' },
    { id: 'integrations', label: 'Integrations' },
    { id: 'display', label: 'Display' },
  ]},
  { id: 'job-log', label: 'Job-Log' },
]

export function resolveLeaf(leaf: LeafId): { top: TopTabId; sub?: SubTabId } {
  for (const t of TABS_TREE) {
    if (t.id === leaf) return { top: t.id }
    if (t.children?.some(c => c.id === leaf)) return { top: t.id, sub: leaf as SubTabId }
  }
  // Fall back to 'about-me' — caller should never pass an unknown leaf.
  return { top: 'about-me' }
}

export function firstSubOf(topId: TopTabId): SubTabId | undefined {
  return TABS_TREE.find(t => t.id === topId)?.children?.[0]?.id
}
```

- [ ] **Step 2: Create the sub-tab persistence store**

Create `userModalSubtabStore.ts` (mirror `sidebarStore.ts` / `displaySettingsStore.ts` patterns):

```typescript
import { create } from 'zustand'
import { safeLocalStorage } from '../../../core/utils/safeStorage'
import type { TopTabId, SubTabId } from './userModalTree'

const KEY = 'chatsune_user_modal_subtabs'
type Map = Partial<Record<TopTabId, SubTabId>>

function load(): Map {
  try { return JSON.parse(safeLocalStorage.getItem(KEY) || '{}') } catch { return {} }
}

interface State {
  lastSub: Map
  setLastSub: (top: TopTabId, sub: SubTabId) => void
}

export const useSubtabStore = create<State>((set, get) => ({
  lastSub: load(),
  setLastSub: (top, sub) => {
    const next = { ...get().lastSub, [top]: sub }
    safeLocalStorage.setItem(KEY, JSON.stringify(next))
    set({ lastSub: next })
  },
}))
```

- [ ] **Step 3: Rewrite `UserModal` state shape**

Replace `activeTab: UserModalTab` with:

```typescript
interface UserModalProps {
  activeTop: TopTabId
  activeSub: SubTabId | undefined
  onClose: () => void
  onTabChange: (top: TopTabId, sub?: SubTabId) => void
  displayName: string
  onOpenPersonaOverlay: (personaId: string) => void
}
```

Render two rows of pills:

- Row 1: `TABS_TREE.map(top => <TabPill>)`
- Row 2 (conditional): only if `TABS_TREE.find(t => t.id === activeTop)?.children` exists. On sub click, call `onTabChange(activeTop, sub.id)` and `useSubtabStore.getState().setLastSub(activeTop, sub.id)`.

Content area switches on `activeSub ?? activeTop`.

- [ ] **Step 4: Propagate problem indicators**

Keep existing `hasApiKeyProblem` / `hasNoLlmConnection` state. Derive per-top:

```typescript
const topHasBadge = {
  'settings': hasApiKeyProblem || hasNoLlmConnection,
}
const subHasBadge = {
  'api-keys': hasApiKeyProblem,
  'llm-providers': hasNoLlmConnection,
}
```

Render the red `!` using the current span style on top pill **and** sub pill when `topHasBadge[topId]` / `subHasBadge[subId]` is true.

- [ ] **Step 5: Update `AppLayout` caller**

In `AppLayout.tsx`, the `openModal(tab: UserModalTab)` signature changes. Replace with:

```typescript
function openModal(leaf: LeafId): void {
  const { top, sub: resolvedSub } = resolveLeaf(leaf)
  const remembered = useSubtabStore.getState().lastSub[top]
  const sub = resolvedSub ?? remembered ?? firstSubOf(top)
  setActiveTop(top); setActiveSub(sub); setOverlayOpen(true)
}
```

Avatar-click logic in `Sidebar.tsx` passes `'api-keys'` when there is a problem (resolver maps to Settings → API-Keys), else `'about-me'`.

- [ ] **Step 6: Update UserModal.test.tsx**

Existing test stubs tab clicks by label — update labels and assertions where the flat tab list is enumerated. Add one test for propagation:

```typescript
it('shows the "!" badge on the Settings top pill when API-Keys has a problem', async () => {
  // mock webSearchApi.listWebSearchProviders to return [{ is_configured: false, ... }]
  render(<UserModal activeTop="about-me" activeSub={undefined} ... />)
  await waitFor(() => {
    const settingsPill = screen.getByRole('tab', { name: /settings/i })
    expect(within(settingsPill).getByText('!')).toBeInTheDocument()
  })
})
```

- [ ] **Step 7: Build check**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm run build`
Expected: success (no TS errors).

Run: `pnpm test -- UserModal`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/app/components/user-modal/ frontend/src/app/layouts/AppLayout.tsx frontend/src/app/components/sidebar/Sidebar.tsx
git commit -m "User modal: 2-level pill navigation with sub-tab persistence and propagated badges"
```

---

## Task 8: Frontend — ApiKeysTab test-button enable fix

**Files:**
- Modify: `frontend/src/app/components/user-modal/ApiKeysTab.tsx`
- Modify: `frontend/src/core/api/websearch.ts` (if the existing `testWebSearchKey` signature requires a key)

- [ ] **Step 1: Change the enable condition + handler**

In `ApiKeysTab.tsx` (line ~210 today):

```tsx
<button
  type="button"
  onClick={() => handleTest(p)}
  disabled={disabled || (row.draft.length === 0 && !p.is_configured)}
  className="..."
>
  {row.busy === 'testing' ? 'Testing…' : 'Test'}
</button>
```

Update `handleTest`:

```tsx
async function handleTest(provider: WebSearchProvider) {
  const row = rowFor(provider.provider_id)
  if (row.busy !== 'idle') return
  const draftOrEmpty = row.draft.length > 0 ? row.draft : undefined
  setBusy(provider.provider_id, 'testing')
  try {
    const res = await webSearchApi.testWebSearchKey(provider.provider_id, draftOrEmpty)
    // ...existing success path
  } finally { setBusy(provider.provider_id, 'idle') }
}
```

- [ ] **Step 2: Update the API client to allow an undefined key**

In `frontend/src/core/api/websearch.ts`, change `testWebSearchKey(providerId, apiKey: string | undefined)` — send `{ api_key: apiKey }` if defined, otherwise `{}`.

- [ ] **Step 3: Build check + smoke**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm run build`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/user-modal/ApiKeysTab.tsx frontend/src/core/api/websearch.ts
git commit -m "Enable web-search Test button when a key is already saved; test falls back to stored key"
```

---

## Task 9: Frontend — LLM connection modal footer redesign (Save / Save & Close)

**Files:**
- Modify: `frontend/src/app/components/llm-providers/ConnectionConfigModal.tsx`
- Modify: `frontend/src/app/components/llm-providers/adapter-views/OllamaHttpView.tsx`
- Modify: `frontend/src/core/api/llm.ts` (if needed for `testConnection` return shape)

- [ ] **Step 1: Remove the separate "Test connection" button from OllamaHttpView**

Delete the JSX block around line 238-247 and the inline `test` result block around 248-259. The Save-and-close footer will own this behaviour.

Keep `handleTest` helper, or inline it into `ConnectionConfigModal`'s save path — whichever preserves readability. If inlining, remove the now-unused helper from `OllamaHttpView`.

- [ ] **Step 2: Redesign the modal footer**

In `ConnectionConfigModal.tsx`, replace the existing footer with three buttons:

```tsx
<div className="flex items-center justify-between border-t border-white/8 px-5 py-3">
  <button type="button" onClick={onClose} className="text-[12px] text-white/60 hover:text-white/80">
    Cancel
  </button>
  <div className="flex items-center gap-2">
    <button
      type="button"
      onClick={() => void handleSave({ closeAfter: false })}
      disabled={saving}
      className="rounded border border-white/15 px-3 py-1 text-[12px] text-white/80 hover:bg-white/5 disabled:opacity-40"
    >
      {saving && !closeAfter ? 'Saving…' : 'Save'}
    </button>
    <button
      type="button"
      onClick={() => void handleSave({ closeAfter: true })}
      disabled={saving}
      className="rounded bg-gold/90 px-4 py-1.5 text-[12px] font-semibold text-black hover:bg-gold disabled:opacity-40"
    >
      {saving && closeAfter ? 'Saving…' : 'Save and close'}
    </button>
  </div>
</div>
```

- [ ] **Step 3: Implement `handleSave({ closeAfter })`**

```tsx
async function handleSave({ closeAfter }: { closeAfter: boolean }) {
  const errors = validateLocally(form) // existing local validation
  if (errors.length > 0) { setValidationErrors(errors); return }
  setSaving(true); setCloseAfter(closeAfter)
  try {
    const saved = isSaved
      ? await llmApi.updateConnection(connection.id, form)
      : await llmApi.createConnection(form)
    setConnection(saved)                 // ← fixes the §6.4 "Optional" placeholder bug
    const testResult = await llmApi.testConnection(saved.id)
    setTestResult(testResult)
    if (closeAfter) onClose()
  } catch (e) {
    setError(errorMessage(e))
  } finally {
    setSaving(false); setCloseAfter(false)
  }
}
```

After `setConnection(saved)`, the OllamaHttpView's `apiKeyState = cfg.api_key` re-evaluates to `{ is_set: true }`, so the placeholder correctly shows `'••••••••  (leave empty to keep)'`.

- [ ] **Step 4: Show inline test-result feedback (stays open path)**

Below the form fields, render a small status pill when `testResult` is present:

```tsx
{testResult && (
  <div className={testResult.valid ? 'text-green-400 text-[12px]' : 'text-red-400 text-[12px]'}>
    {testResult.valid ? 'Connection OK.' : `Test failed: ${testResult.error ?? 'unknown error'}`}
  </div>
)}
```

- [ ] **Step 5: Repro test for the "Optional" placeholder bug (Step 4 of §6.4 in the spec)**

In a clean dev session, add a new Ollama Cloud connection with an API key, click "Save" (not close), and verify the key placeholder becomes `'••••••••  (leave empty to keep)'` and the "saved" green badge appears in the top-right of the field. If it still shows "Optional", the save path is not updating the `connection` prop — investigate `setConnection(saved)` and the `apiKeyState` memo.

- [ ] **Step 6: Build check**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm run build`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/components/llm-providers/
git commit -m "LLM connection modal: Save and Save-and-close buttons; auto-test on save; fix placeholder refresh"
```

---

## Task 10: Frontend — ModelBrowser: inline star, provider dropdown, collapsible groups, quant badge

**Files:**
- Modify: `frontend/src/app/components/model-browser/ModelBrowser.tsx`
- Modify: `frontend/src/app/components/model-browser/modelFilters.ts`
- Create: `frontend/src/app/components/model-browser/modelBrowserStore.ts` — collapsed-groups Zustand store (localStorage-backed)
- Modify: `frontend/src/core/types/llm.ts` — add `connection_slug` and `quantisation_level` to `ModelMetaDto` / `EnrichedModelDto`

- [ ] **Step 1: Type additions**

In `llm.ts`:

```typescript
export interface ModelMetaDto {
  // ...existing...
  connection_id: string
  connection_slug: string
  connection_display_name: string
  quantisation: string | null
  // ...
}
```

- [ ] **Step 2: Collapsed-groups store**

Create `modelBrowserStore.ts`:

```typescript
import { create } from 'zustand'
import { safeLocalStorage } from '../../../core/utils/safeStorage'

const KEY = 'chatsune_model_browser_collapsed'

function load(): Set<string> {
  try { return new Set(JSON.parse(safeLocalStorage.getItem(KEY) || '[]')) } catch { return new Set() }
}
function persist(s: Set<string>) { safeLocalStorage.setItem(KEY, JSON.stringify([...s])) }

interface State {
  collapsed: Set<string>
  toggle: (id: string) => void
}
export const useCollapsedGroups = create<State>((set, get) => ({
  collapsed: load(),
  toggle: (id) => {
    const next = new Set(get().collapsed)
    next.has(id) ? next.delete(id) : next.add(id)
    persist(next)
    set({ collapsed: next })
  },
}))
```

- [ ] **Step 3: Provider filter dropdown**

In `ModelBrowser.tsx`, above the model list, add:

```tsx
const OPTION_STYLE: React.CSSProperties = { background: '#0f0d16', color: 'rgba(255,255,255,0.85)' }

<select
  value={providerFilter}
  onChange={(e) => setProviderFilter(e.target.value)}
  className="rounded border border-white/15 bg-black/30 px-2 py-1 text-[12px] text-white/80"
>
  <option value="" style={OPTION_STYLE}>All providers</option>
  {connectionGroups.map(g => (
    <option key={g.connection_id} value={g.connection_id} style={OPTION_STYLE}>
      {g.display_name} — {g.slug}
    </option>
  ))}
</select>
```

State: `const [providerFilter, setProviderFilter] = useState<string>('')`.

In `applyModelFilters` (or wherever grouping/filtering happens), add:

```typescript
if (providerFilter) groups = groups.filter(g => g.connection_id === providerFilter)
```

- [ ] **Step 4: Inline star button + quant badge in each model row**

Row layout becomes:

```tsx
<div className="flex items-center gap-2">
  <button
    type="button"
    onClick={(e) => { e.stopPropagation(); toggleFavourite(model) }}
    aria-label={model.is_favourite ? 'Remove favourite' : 'Mark as favourite'}
    className={model.is_favourite ? 'text-gold' : 'text-white/40 hover:text-white/70'}
  >
    {model.is_favourite ? '★' : '☆'}
  </button>
  <span className="flex-1 text-[13px] text-white">{model.display_name}</span>
  {model.quantisation && (
    <span className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] font-mono text-white/60">{model.quantisation}</span>
  )}
  {/* existing capability badges */}
</div>
```

`toggleFavourite` wraps `llmApi.setUserModelConfig(model.connection_id, slugWithoutConnection(model.unique_id), { is_favourite: !model.is_favourite })` — the optimistic update is handled via the existing event flow.

Event `stopPropagation` prevents bubbling to the row click (which either opens the editor in browser mode or selects the model in selection mode, per §3.2 of the spec).

- [ ] **Step 5: Collapsible group header**

Replace the header span with a button:

```tsx
<button
  type="button"
  onClick={() => useCollapsedGroups.getState().toggle(group.connection_id)}
  className="flex items-center gap-2 text-left"
>
  <span className="text-white/50">{useCollapsedGroups(s => s.collapsed.has(group.connection_id)) ? '▸' : '▾'}</span>
  <span className="font-semibold text-white/80">{group.display_name}</span>
  <span className="text-[11px] text-white/40">— {group.slug}</span>
</button>
```

Conditionally render the group's model list only when not collapsed.

- [ ] **Step 6: Build check**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm run build`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/components/model-browser/ frontend/src/core/types/llm.ts
git commit -m "ModelBrowser: inline star, provider dropdown, collapsible groups, quant badge"
```

---

## Task 11: Frontend — ModelSelectionModal as child of parent overlay

**Files:**
- Modify: `frontend/src/app/components/model-browser/ModelSelectionModal.tsx`
- Modify: `frontend/src/core/components/Sheet.tsx` only if needed to support an in-parent variant

- [ ] **Step 1: Determine rendering mode**

Add a prop `mode?: 'standalone' | 'in-parent'` (default `'standalone'`). In persona `EditTab`, pass `mode="in-parent"`.

- [ ] **Step 2: Implement in-parent sizing**

When `mode === 'in-parent'`, render as an `absolute` element (not `fixed`) inside the nearest `relative`-positioned parent. The host (PersonaOverlay) must have `relative` on its outer box.

Sizing:
```tsx
className="absolute inset-0 lg:inset-auto lg:top-[10%] lg:left-[5%] lg:right-[5%] lg:bottom-[10%] ..."
```
= 80% height / 90% width on ≥lg; full-screen below.

- [ ] **Step 3: Update EditTab usage**

In `frontend/src/app/components/persona-overlay/EditTab.tsx`, pass `mode="in-parent"` and ensure the `PersonaOverlay` container has `relative`.

- [ ] **Step 4: Build + manual check**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm run build`
Open the persona overlay, click the model picker, verify:
- On desktop, picker is bounded inside the PersonaOverlay card (does not exceed its outer border).
- On mobile, picker is full-screen.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/model-browser/ModelSelectionModal.tsx frontend/src/app/components/persona-overlay/EditTab.tsx
git commit -m "Render ModelSelectionModal as a child of its parent overlay with 80/90% sizing"
```

---

## Task 12: Frontend — ModelConfigModal: tag buttons + context slider

**Files:**
- Modify: `frontend/src/app/components/model-browser/ModelConfigModal.tsx`

- [ ] **Step 1: Tag-button toggles**

Replace the two checkbox blocks with pill-style buttons:

```tsx
<button
  type="button"
  onClick={() => setIsFavourite(!isFavourite)}
  className={[
    'inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-[12px] border',
    isFavourite
      ? 'bg-gold/20 border-gold/60 text-gold'
      : 'bg-white/5 border-white/15 text-white/60 hover:text-white/80',
  ].join(' ')}
  aria-pressed={isFavourite}
>
  <span>{isFavourite ? '★' : '☆'}</span>
  <span>Favourite</span>
</button>

<button
  type="button"
  onClick={() => setIsHidden(!isHidden)}
  className={[
    'inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-[12px] border',
    !isHidden
      ? 'bg-emerald-500/15 border-emerald-400/60 text-emerald-300'
      : 'bg-white/5 border-white/15 text-white/60 hover:text-white/80',
  ].join(' ')}
  aria-pressed={!isHidden}
>
  <span>{isHidden ? '⦸' : '👁'}</span>
  <span>{isHidden ? 'Hidden' : 'Visible'}</span>
</button>
```

- [ ] **Step 2: Context-window slider**

Above the slider, show current value:

```tsx
const modelMax = model.max_context_window ?? 0
const sliderDisabled = modelMax <= 80_000
const isPow2 = (n: number) => n > 0 && (n & (n - 1)) === 0
const step = isPow2(modelMax) ? 4096 : 4000
const displayValue = customContext ?? modelMax

<div>
  <div className="flex items-center justify-between">
    <label className="text-[11px] font-mono uppercase tracking-wider text-white/50">Custom context window</label>
    <span className="font-mono text-[13px] text-gold">
      {displayValue.toLocaleString()} tokens{customContext == null ? ' (model default)' : ''}
    </span>
  </div>
  <input
    type="range"
    min={80_000}
    max={modelMax}
    step={step}
    value={customContext ?? modelMax}
    onChange={(e) => setCustomContext(Number(e.target.value))}
    disabled={sliderDisabled}
    className="w-full accent-gold disabled:opacity-30"
  />
  <div className="flex items-center justify-between">
    <span className="text-[10px] font-mono text-white/40">80k min</span>
    <button
      type="button"
      onClick={() => setCustomContext(null)}
      className="text-[11px] text-white/50 hover:text-white/80 underline"
    >
      Use model default
    </button>
    <span className="text-[10px] font-mono text-white/40">{modelMax.toLocaleString()} max</span>
  </div>
  {sliderDisabled && (
    <p className="text-[10px] text-white/40 mt-1">
      Model max ≤ 80k — context cannot be narrowed further.
    </p>
  )}
</div>
```

The existing number-input is removed. Submit path: `custom_context_window: customContext` (null → no override, number → override).

- [ ] **Step 3: Build check**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm run build`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/model-browser/ModelConfigModal.tsx
git commit -m "ModelConfigModal: tag-button toggles for favourite/visible; slider for context window"
```

---

## Task 13: INSIGHTS update

**Files:**
- Modify: `INSIGHTS.md`

- [ ] **Step 1: Mark INS-004 as superseded**

At the top of the INS-004 section, replace the "Decision (UPDATED 2026-04-14...)" line with:

```markdown
> **SUPERSEDED 2026-04-15 (UI restructure).** Model `unique_id` canonical form is now `<connection_slug>:<model_slug>`. See INS-019.
```

Keep the body intact for historical context.

- [ ] **Step 2: Add INS-019**

Append before or after the last INS entry (keep existing numbering scheme):

```markdown
## INS-019 — Model Unique ID Slug Format (2026-04-15)

**Decision:** Models are identified by `model_unique_id = "<connection_slug>:<model_slug>"`. Supersedes INS-004's UUID-based format.

**Parsing:** split on the first `:`. Left segment = Connection slug (user-defined, unique per user, validated by `_SLUG_RE`). Right segment = model slug (opaque, passed to the adapter).

**Rename cascade:** Renaming a Connection slug is a legitimate user action. The `ConnectionRepository.update` method runs a MongoDB transaction (RS0) that updates the connection document and every `persona.model_unique_id` and `llm_user_model_configs.model_unique_id` of that user matching the old prefix. Publishes `Topics.LLM_CONNECTION_SLUG_RENAMED` so client stores can remap in place. Scope is strictly per-user; cross-user data is never touched.

**Adapter-level filter for unusable models:** The `ollama_http` adapter drops any model without a `context_length` from `list_models()`. A model without a known max context window cannot be reasoned about and is not offered to the user.

**DTO impact:** `ModelMetaDto` gains `connection_slug` (used in `unique_id` composition) and `quantisation_level` (populated when the adapter reports it). `connection_id` is retained for internal bookkeeping (tracker enrichment, debug collector).
```

- [ ] **Step 3: Cross-link**

In INS-016's body, add a line under the decision:
```markdown
> The `unique_id` format referenced here is the slug-based form per INS-019 (previously UUID-based per INS-004).
```

- [ ] **Step 4: Commit**

```bash
git add INSIGHTS.md
git commit -m "INSIGHTS: supersede INS-004, add INS-019 for slug-based unique_id and rename cascade"
```

---

## Task 14: Build, smoke verification, merge to master

**Files:** none

- [ ] **Step 1: Full frontend build**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm run build`
Expected: zero TS errors, clean output.

- [ ] **Step 2: Frontend test suite**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm test -- --run`
Expected: all green.

- [ ] **Step 3: Backend tests**

Run: `cd /home/chris/workspace/chatsune && uv run pytest backend/tests/ -x`
Expected: all green.

- [ ] **Step 4: Manual smoke — start stack + verify key flows**

- User-modal opens on avatar click
- Without API-key problem: lands on `About Me`
- With an unconfigured web-search provider: lands on `Settings → API-Keys`, both the Settings top pill and the API-Keys sub pill show the red `!`
- Adding an API key and clicking Test (without clearing the field) works; clicking Test after saving (draft empty) also works with the stored key
- `LLM Providers` sub-tab: create Ollama Cloud connection with an API key, click `Save` — stays open, sees green "Connection OK.", status pill on the list entry updates to `valid`; reopen modal — key placeholder shows `'••••••••  (leave empty to keep)'` with the `saved` badge
- `Models` sub-tab: star toggles immediately, provider dropdown filters the list, group headers collapse/expand, quant badge visible for Ollama Cloud models
- Open persona overlay → model picker: picker is visually bounded to the overlay card on desktop, full-screen on mobile
- Open model editor from Models sub-tab: tag buttons gold/green when active, slider bounded [80k, model_max] with the right step; "Use model default" resets; disabled + info line for models ≤80k
- Rename a connection slug → personas that reference this connection's models still resolve (Chat still opens, no `model_unique_id` errors in logs)

- [ ] **Step 5: Merge to master**

Per project convention (CLAUDE.md §Implementation defaults): merge to master after implementation.

```bash
git checkout master
git merge --no-ff <feature-branch>    # if the work ran in a feature branch
# (or, if working directly on master, push after all task commits)
git push origin master
```

- [ ] **Step 6: Clean up**

```bash
scripts/stop-server.sh /home/chris/workspace/chatsune/.superpowers/brainstorm/*/state/
```

(Optional — the brainstorming server auto-exits after 30 min of inactivity.)

---

## Self-Review

**Spec coverage:** Every spec section maps to at least one task:
- §1 Tab restructure → Task 7
- §2 Picker sizing → Task 11
- §3 Picker UX → Task 10
- §4 Model editor → Task 12
- §5 Slug format → Tasks 1, 3, 4; filter rule → Task 2; INSIGHTS → Task 13
- §6.1 API-keys → Tasks 6 (backend), 8 (frontend)
- §6.2 LLM footer → Task 9
- §6.3 Test persistence → Task 5
- §6.4 Optional placeholder → Task 9 (Step 3 `setConnection(saved)` + repro in Step 5)

**Placeholder scan:** No "TBD"/"TODO"/"similar to". All code blocks concrete. Validation-error wiring in Task 9 Step 3 references existing `validateLocally` and `errorMessage` helpers — those exist in `ConnectionConfigModal.tsx` today; if not, they should be introduced as a tiny local utility in the same file (keep inline, no new file needed).

**Type consistency:** `TopTabId` / `SubTabId` / `LeafId` / `TABS_TREE` used consistently in Task 7. `connection_slug` / `quantisation_level` introduced in Task 1 and referenced identically in Tasks 2, 3, 10. `testResult` / `saved` / `isSaved` vocabulary consistent across Task 9.

---

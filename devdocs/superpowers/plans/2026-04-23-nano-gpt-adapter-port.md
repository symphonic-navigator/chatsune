# Nano-GPT Upstream Adapter — Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the pre-built nano-gpt upstream adapter from `/home/chris/projects/nano-explore` into chatsune's LLM module, including model catalogue, pairing logic for thinking/non-thinking toggle via dual slugs, and Redis-backed pair map. Introduce a new `billing_category` field on `ModelMetaDto` and label every existing adapter accordingly.

**Architecture:**
- New adapter file `backend/modules/llm/_adapters/_nano_gpt_http.py` plus a sibling `_nano_gpt_catalog.py` module holding the pure filter/pair/map logic (ported 1:1 from `nano-explore/src/nano_explore/catalog.py`).
- Pair map stored in Redis under `nano_gpt:pair_map:{connection_id}`, 30-minute TTL, populated by `fetch_models()` and read by `stream_completion()` (Phase 2).
- `stream_completion()` is deliberately a `NotImplementedError` stub in this session — it will be implemented in a follow-up session with fresh context per the per-session scope rule.
- `ModelMetaDto.billing_category: Literal["free", "subscription", "pay_per_token"] | None = None` — default `None` so existing cached documents deserialise unchanged (CLAUDE.md §Data-Model Migrations). All five adapters (xAI, Mistral, Community, Ollama, Nano-GPT) populate it.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, redis.asyncio, pytest-asyncio. No new dependencies.

**Out of scope (future sessions):**
- `stream_completion()` full SSE loop and thinking-slug routing
- Frontend model-picker grouping / billing badges
- "Subscription user vs. pay-per-token user" warning (nano-gpt users without subscription incur per-token cost on subscription-labelled models)
- TTI, ITI, compact-and-continue, Lorebooks (Chris' roadmap, explicitly later)

---

## File Structure

**Create:**
- `backend/modules/llm/_adapters/_nano_gpt_http.py` — `NanoGptHttpAdapter` class
- `backend/modules/llm/_adapters/_nano_gpt_catalog.py` — pure filter/pair/map logic
- `backend/modules/llm/_adapters/_nano_gpt_pair_map.py` — Redis pair-map persistence helpers
- `backend/tests/modules/llm/adapters/test_nano_gpt_catalog.py` — filter/pair/mapping tests
- `backend/tests/modules/llm/adapters/test_nano_gpt_http.py` — adapter end-to-end tests
- `backend/tests/modules/llm/adapters/fixtures/nano_gpt/*.json` — 13 fixtures copied from `nano-explore/tests/fixtures/`

**Modify:**
- `shared/dtos/llm.py` — add `billing_category` to `ModelMetaDto`
- `backend/modules/llm/_adapters/_xai_http.py` — set `billing_category="pay_per_token"`
- `backend/modules/llm/_adapters/_mistral_http.py` — set `billing_category="pay_per_token"`
- `backend/modules/llm/_adapters/_community.py` — set `billing_category="free"`
- `backend/modules/llm/_adapters/_ollama_http.py` — set `billing_category` based on URL host (ollama.com → subscription, else free)
- `backend/modules/llm/_registry.py` — register `nano_gpt_http`
- `backend/tests/modules/llm/adapters/test_{xai,mistral,community,ollama}_http.py` — extend to assert billing_category

---

### Task 1: Extend `ModelMetaDto` with `billing_category`

**Files:**
- Modify: `shared/dtos/llm.py:12-33`
- Test: `backend/tests/shared/dtos/test_llm_model_meta.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/shared/dtos/test_llm_model_meta.py`:

```python
from shared.dtos.llm import ModelMetaDto


def _base_kwargs() -> dict:
    return {
        "connection_id": "c1",
        "model_id": "m1",
        "display_name": "M 1",
        "context_window": 128000,
        "supports_reasoning": False,
        "supports_vision": False,
        "supports_tool_calls": False,
    }


def test_billing_category_defaults_to_none():
    dto = ModelMetaDto(**_base_kwargs())
    assert dto.billing_category is None


def test_billing_category_accepts_free():
    dto = ModelMetaDto(**_base_kwargs(), billing_category="free")
    assert dto.billing_category == "free"


def test_billing_category_accepts_subscription():
    dto = ModelMetaDto(**_base_kwargs(), billing_category="subscription")
    assert dto.billing_category == "subscription"


def test_billing_category_accepts_pay_per_token():
    dto = ModelMetaDto(**_base_kwargs(), billing_category="pay_per_token")
    assert dto.billing_category == "pay_per_token"


def test_billing_category_rejects_unknown_value():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ModelMetaDto(**_base_kwargs(), billing_category="enterprise")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chris/workspace/chatsune && uv run pytest backend/tests/shared/dtos/test_llm_model_meta.py -v`
Expected: 5 tests FAIL with "ModelMetaDto got unexpected keyword argument 'billing_category'" (or similar Pydantic rejection).

- [ ] **Step 3: Add field to `ModelMetaDto`**

In `shared/dtos/llm.py`, insert after line 28 (`is_deprecated: bool = False`):

```python
    # Billing category — "free" (self-hosted / community-shared), "subscription"
    # (covered by a user's upstream plan, e.g. Ollama Cloud or nano-gpt in-plan),
    # or "pay_per_token" (charged per-request, e.g. xAI, Mistral, nano-gpt
    # out-of-plan). Default ``None`` keeps pre-existing cached documents
    # readable — see CLAUDE.md §Data-Model Migrations.
    billing_category: Literal["free", "subscription", "pay_per_token"] | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest backend/tests/shared/dtos/test_llm_model_meta.py -v`
Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add shared/dtos/llm.py backend/tests/shared/dtos/test_llm_model_meta.py
git commit -m "Add billing_category field to ModelMetaDto"
```

---

### Task 2: Label xAI, Mistral, Community adapters with fixed billing_category

**Files:**
- Modify: `backend/modules/llm/_adapters/_xai_http.py:294-309` (fetch_models)
- Modify: `backend/modules/llm/_adapters/_mistral_http.py` (_map_to_dto helper)
- Modify: `backend/modules/llm/_adapters/_community.py` (wherever ModelMetaDto is built)
- Modify tests: `backend/tests/modules/llm/adapters/test_{xai,mistral,community}_http.py`

- [ ] **Step 1: Write the failing assertions**

In `test_xai_http.py`, locate the `test_fetch_models_*` (or equivalent) test, add:

```python
@pytest.mark.asyncio
async def test_fetch_models_sets_pay_per_token_billing():
    adapter = XaiHttpAdapter()
    conn = _resolved_conn()
    models = await adapter.fetch_models(conn)
    assert models, "expected at least one model"
    assert all(m.billing_category == "pay_per_token" for m in models)
```

In `test_mistral_http.py`, add analogous test (use the existing dedup-pipeline fixture):

```python
@pytest.mark.asyncio
async def test_fetch_models_sets_pay_per_token_billing(monkeypatch):
    # reuse existing mocked /models response fixture
    adapter = MistralHttpAdapter()
    conn = _resolved_conn()
    models = await adapter.fetch_models(conn)
    assert all(m.billing_category == "pay_per_token" for m in models)
```

In `test_community.py`, add:

```python
@pytest.mark.asyncio
async def test_fetch_models_sets_free_billing(monkeypatch):
    adapter = CommunityAdapter()
    conn = _resolved_conn()
    # existing mock setup for sidecar response
    models = await adapter.fetch_models(conn)
    assert all(m.billing_category == "free" for m in models)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_xai_http.py backend/tests/modules/llm/adapters/test_mistral_http.py backend/tests/modules/llm/adapters/test_community.py -v -k billing`
Expected: 3 FAIL with `AssertionError: None != "pay_per_token"` (or `"free"`).

- [ ] **Step 3: Update xAI `fetch_models()`**

In `_xai_http.py:294-309`, locate the `ModelMetaDto(...)` construction inside `fetch_models()`. Add `billing_category="pay_per_token",` to the kwargs:

```python
return [
    ModelMetaDto(
        connection_id=c.id,
        connection_slug=c.slug,
        connection_display_name=c.display_name,
        model_id="grok-4.1-fast",
        display_name="Grok 4.1 Fast",
        context_window=256000,
        supports_reasoning=True,
        supports_vision=False,
        supports_tool_calls=True,
        billing_category="pay_per_token",
    )
]
```

- [ ] **Step 4: Update Mistral `_map_to_dto()`**

Locate the helper in `_mistral_http.py` that builds `ModelMetaDto` from an upstream model entry. Add `billing_category="pay_per_token",` to the kwargs (check file contents first — the helper is near the dedup pipeline around line 300-357).

- [ ] **Step 5: Update Community adapter**

In `_community.py`, locate where `ModelMetaDto` is constructed inside `fetch_models()` (around line 240-260). Add `billing_category="free",`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_xai_http.py backend/tests/modules/llm/adapters/test_mistral_http.py backend/tests/modules/llm/adapters/test_community.py -v`
Expected: All tests PASS, including the new billing-category ones and all pre-existing tests.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/llm/_adapters/_xai_http.py \
        backend/modules/llm/_adapters/_mistral_http.py \
        backend/modules/llm/_adapters/_community.py \
        backend/tests/modules/llm/adapters/test_xai_http.py \
        backend/tests/modules/llm/adapters/test_mistral_http.py \
        backend/tests/modules/llm/adapters/test_community.py
git commit -m "Label xAI, Mistral and Community adapters with billing_category"
```

---

### Task 3: Label Ollama adapter based on URL host

**Files:**
- Modify: `backend/modules/llm/_adapters/_ollama_http.py` (_map_to_dto + helper)
- Test: `backend/tests/modules/llm/adapters/test_ollama_http.py`

- [ ] **Step 1: Write the failing test**

Add to `test_ollama_http.py`:

```python
from backend.modules.llm._adapters._ollama_http import _billing_category_for_url


def test_billing_category_for_ollama_cloud():
    assert _billing_category_for_url("https://ollama.com") == "subscription"
    assert _billing_category_for_url("https://ollama.com/") == "subscription"
    assert _billing_category_for_url("https://api.ollama.com") == "subscription"


def test_billing_category_for_localhost():
    assert _billing_category_for_url("http://localhost:11434") == "free"
    assert _billing_category_for_url("http://127.0.0.1:11434") == "free"


def test_billing_category_for_custom_self_hosted():
    assert _billing_category_for_url("https://my.homelab.net:11434") == "free"


@pytest.mark.asyncio
async def test_fetch_models_labels_billing_for_local(monkeypatch):
    # existing mock for /api/tags + /api/show, URL = localhost
    adapter = OllamaHttpAdapter()
    conn = _resolved_conn(url="http://localhost:11434")
    models = await adapter.fetch_models(conn)
    assert all(m.billing_category == "free" for m in models)


@pytest.mark.asyncio
async def test_fetch_models_labels_billing_for_cloud(monkeypatch):
    adapter = OllamaHttpAdapter()
    conn = _resolved_conn(url="https://ollama.com", api_key="k")
    models = await adapter.fetch_models(conn)
    assert all(m.billing_category == "subscription" for m in models)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_ollama_http.py -v -k billing`
Expected: FAIL with `ImportError` on `_billing_category_for_url` and with assertion errors on the async tests.

- [ ] **Step 3: Add helper + wire into `_map_to_dto()`**

In `_ollama_http.py`, add near the top-level helpers (below imports, above the class):

```python
from urllib.parse import urlparse


def _billing_category_for_url(url: str) -> Literal["free", "subscription"]:
    host = urlparse(url).hostname or ""
    if host == "ollama.com" or host.endswith(".ollama.com"):
        return "subscription"
    return "free"
```

Then locate `_map_to_dto(conn_id, display_name, slug, name, detail)` (the existing helper called from `fetch_models()` at line 284-286) and thread a `billing_category` argument through. Update the call site in `fetch_models()`:

```python
billing = _billing_category_for_url(c.config["url"])
metas = [
    _map_to_dto(c.id, c.display_name, c.slug, name, detail, billing=billing)
    for name, detail in results if detail is not None
]
```

In `_map_to_dto`, add `billing: Literal["free", "subscription"]` to the signature and pass it to the `ModelMetaDto(...)` construction.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_ollama_http.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_ollama_http.py backend/tests/modules/llm/adapters/test_ollama_http.py
git commit -m "Label Ollama adapter with URL-based billing_category"
```

---

### Task 4: Copy nano-gpt test fixtures

**Files:**
- Create: `backend/tests/modules/llm/adapters/fixtures/nano_gpt/*.json` (13 files)

- [ ] **Step 1: Copy all fixtures**

```bash
mkdir -p /home/chris/workspace/chatsune/backend/tests/modules/llm/adapters/fixtures/nano_gpt
cp /home/chris/projects/nano-explore/tests/fixtures/*.json \
   /home/chris/workspace/chatsune/backend/tests/modules/llm/adapters/fixtures/nano_gpt/
```

- [ ] **Step 2: Verify 13 files copied**

```bash
ls /home/chris/workspace/chatsune/backend/tests/modules/llm/adapters/fixtures/nano_gpt/ | wc -l
```
Expected: `13`.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/modules/llm/adapters/fixtures/nano_gpt/
git commit -m "Add nano-gpt test fixtures ported from nano-explore"
```

---

### Task 5: Port `catalog.py` as `_nano_gpt_catalog.py`

**Files:**
- Create: `backend/modules/llm/_adapters/_nano_gpt_catalog.py` (ported from `/home/chris/projects/nano-explore/src/nano_explore/catalog.py`)
- Create: `backend/tests/modules/llm/adapters/test_nano_gpt_catalog.py` (ported from `nano-explore/tests/test_{filters,pairing,mapping,catalogue}.py`)

- [ ] **Step 1: Read the source module**

```bash
cat /home/chris/projects/nano-explore/src/nano_explore/catalog.py
```

- [ ] **Step 2: Read the source tests**

```bash
cat /home/chris/projects/nano-explore/tests/test_filters.py \
    /home/chris/projects/nano-explore/tests/test_pairing.py \
    /home/chris/projects/nano-explore/tests/test_mapping.py \
    /home/chris/projects/nano-explore/tests/test_catalogue.py
```

- [ ] **Step 3: Create `_nano_gpt_catalog.py`**

Write `backend/modules/llm/_adapters/_nano_gpt_catalog.py` as a 1:1 copy of `catalog.py`, with two changes:

1. **Import swap** — replace:
   ```python
   from nano_explore._stubs import ModelMetaDto
   ```
   with:
   ```python
   from shared.dtos.llm import ModelMetaDto
   ```

2. **Populate `billing_category`** — in `to_model_meta(entry, pair_info=None)`, derive from `entry.get("subscription", {}).get("included")`:
   ```python
   is_subscription = bool((entry.get("subscription") or {}).get("included"))
   billing_category = "subscription" if is_subscription else "pay_per_token"
   ```
   Pass `billing_category=billing_category` to the `ModelMetaDto(...)` constructor. Remove `is_subscription` from the extras dict return (the separate `is_subscription` bit is now redundant — billing_category carries this information).

- [ ] **Step 4: Create `test_nano_gpt_catalog.py`**

Concatenate the four source test modules into one file. Update imports:

```python
# old
from nano_explore.catalog import filter_context, build_pairs, ...
# new
from backend.modules.llm._adapters._nano_gpt_catalog import (
    filter_context, filter_budget_variants, build_pairs,
    filter_reasoning_only, derive_display_name, to_model_meta,
    build_catalogue,
)
```

Update fixture loading paths — the fixture directory is now `backend/tests/modules/llm/adapters/fixtures/nano_gpt/`. Use `Path(__file__).parent / "fixtures" / "nano_gpt" / "pair_colon.json"` pattern.

Add new assertions to `test_mapping.py`-ported tests for `billing_category`:

```python
def test_to_model_meta_sets_subscription_for_included():
    entry = {"id": "x", "context_length": 128000, "subscription": {"included": True}, ...}
    dto, _extras = to_model_meta(entry, pair_info=None)
    assert dto.billing_category == "subscription"


def test_to_model_meta_sets_pay_per_token_for_not_included():
    entry = {"id": "y", "context_length": 128000, "subscription": {"included": False}, ...}
    dto, _extras = to_model_meta(entry, pair_info=None)
    assert dto.billing_category == "pay_per_token"
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_nano_gpt_catalog.py -v`
Expected: All tests PASS (26 tests: 8 filters + 7 pairing + 5 mapping + 6 catalogue + 2 new billing).

- [ ] **Step 6: Verify backend build**

Run: `uv run python -m py_compile backend/modules/llm/_adapters/_nano_gpt_catalog.py`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/llm/_adapters/_nano_gpt_catalog.py \
        backend/tests/modules/llm/adapters/test_nano_gpt_catalog.py
git commit -m "Port nano-gpt catalogue logic (filter/pair/map) with tests"
```

---

### Task 6: Redis pair-map persistence helpers

**Files:**
- Create: `backend/modules/llm/_adapters/_nano_gpt_pair_map.py`
- Test: `backend/tests/modules/llm/adapters/test_nano_gpt_pair_map.py`

- [ ] **Step 1: Write the failing test**

```python
import json
import pytest
from redis.asyncio import Redis
from backend.modules.llm._adapters._nano_gpt_pair_map import (
    save_pair_map, load_pair_map, PAIR_MAP_TTL_SECONDS,
)


@pytest.mark.asyncio
async def test_save_and_load_pair_map(redis_client: Redis):
    pair_map = {
        "anthropic/claude-opus-4.6": {
            "non_thinking_slug": "anthropic/claude-opus-4.6",
            "thinking_slug": "anthropic/claude-opus-4.6:thinking",
        },
    }
    await save_pair_map(redis_client, connection_id="c1", pair_map=pair_map)
    loaded = await load_pair_map(redis_client, connection_id="c1")
    assert loaded == pair_map


@pytest.mark.asyncio
async def test_load_pair_map_missing_returns_empty(redis_client: Redis):
    loaded = await load_pair_map(redis_client, connection_id="does-not-exist")
    assert loaded == {}


@pytest.mark.asyncio
async def test_save_pair_map_sets_ttl(redis_client: Redis):
    await save_pair_map(redis_client, connection_id="c2", pair_map={"m": {"non_thinking_slug": "m", "thinking_slug": None}})
    ttl = await redis_client.ttl("nano_gpt:pair_map:c2")
    assert 0 < ttl <= PAIR_MAP_TTL_SECONDS
```

`redis_client` must be provided via an existing conftest or fakeredis fixture — check `backend/tests/conftest.py` for the existing pattern and reuse it (the metadata-cache tests already use this).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_nano_gpt_pair_map.py -v`
Expected: FAIL with `ModuleNotFoundError` on `_nano_gpt_pair_map`.

- [ ] **Step 3: Implement the helpers**

Create `backend/modules/llm/_adapters/_nano_gpt_pair_map.py`:

```python
"""Redis persistence for nano-gpt's pair map.

The nano-gpt adapter represents thinking capability by pairs of upstream
slugs (``base`` + ``base:thinking``, or inverse variants). ``fetch_models``
builds this map at catalogue time; ``stream_completion`` reads it at
request time to pick the correct upstream slug. The shared
``ModelMetaDto`` intentionally does **not** carry this adapter-specific
pair data — it lives here, Redis-scoped per connection, 30-minute TTL
matching the sibling metadata cache.
"""
import json
from redis.asyncio import Redis

PAIR_MAP_TTL_SECONDS = 30 * 60

PairMap = dict[str, dict[str, str | None]]


def _key(connection_id: str) -> str:
    return f"nano_gpt:pair_map:{connection_id}"


async def save_pair_map(
    redis: Redis, *, connection_id: str, pair_map: PairMap,
) -> None:
    await redis.set(
        _key(connection_id),
        json.dumps(pair_map),
        ex=PAIR_MAP_TTL_SECONDS,
    )


async def load_pair_map(
    redis: Redis, *, connection_id: str,
) -> PairMap:
    raw = await redis.get(_key(connection_id))
    if raw is None:
        return {}
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_nano_gpt_pair_map.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_nano_gpt_pair_map.py \
        backend/tests/modules/llm/adapters/test_nano_gpt_pair_map.py
git commit -m "Add Redis pair-map persistence for nano-gpt adapter"
```

---

### Task 7: Port `NanoGptHttpAdapter` skeleton (class, templates, config_schema)

**Files:**
- Create: `backend/modules/llm/_adapters/_nano_gpt_http.py`
- Test: `backend/tests/modules/llm/adapters/test_nano_gpt_http.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/modules/llm/adapters/test_nano_gpt_http.py`:

```python
from datetime import datetime, UTC
import pytest
from backend.modules.llm._adapters._nano_gpt_http import NanoGptHttpAdapter
from backend.modules.llm._adapters._types import ResolvedConnection


def _resolved_conn(api_key: str = "nano-test-key") -> ResolvedConnection:
    now = datetime.now(UTC)
    return ResolvedConnection(
        id="conn-nano-1",
        user_id="u1",
        adapter_type="nano_gpt_http",
        display_name="Chris's Nano-GPT",
        slug="chris-nano",
        config={
            "base_url": "https://api.nano-gpt.com/v1",
            "api_key": api_key,
            "max_parallel": 3,
        },
        created_at=now,
        updated_at=now,
    )


def test_adapter_identity():
    assert NanoGptHttpAdapter.adapter_type == "nano_gpt_http"
    assert NanoGptHttpAdapter.display_name == "Nano-GPT"
    assert NanoGptHttpAdapter.view_id == "nano_gpt_http"
    assert NanoGptHttpAdapter.secret_fields == frozenset({"api_key"})


def test_templates_shape():
    tpls = NanoGptHttpAdapter.templates()
    assert len(tpls) == 1
    tpl = tpls[0]
    assert tpl.id == "nano_gpt_default"
    assert tpl.display_name == "Nano-GPT"
    assert tpl.slug_prefix == "nano"
    assert tpl.config_defaults["base_url"] == "https://api.nano-gpt.com/v1"
    assert "api_key" in tpl.required_config_fields


def test_config_schema_shape():
    schema = NanoGptHttpAdapter.config_schema()
    names = {f.name for f in schema}
    assert names == {"base_url", "api_key", "max_parallel"}
    api_key_field = next(f for f in schema if f.name == "api_key")
    assert api_key_field.type == "secret"
    assert api_key_field.required is True


def test_stream_completion_raises_not_implemented():
    adapter = NanoGptHttpAdapter()
    conn = _resolved_conn()
    # CompletionRequest is not constructed here — we expect the method
    # itself to raise NotImplementedError without dispatching upstream.
    with pytest.raises(NotImplementedError, match="Phase 2"):
        # stream_completion returns an AsyncIterator; invoking the
        # generator function should raise immediately when we pull.
        async def _drain():
            agen = adapter.stream_completion(conn, request=None)  # type: ignore[arg-type]
            async for _ in agen:
                pass
        import asyncio
        asyncio.get_event_loop().run_until_complete(_drain())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_nano_gpt_http.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the adapter skeleton**

Create `backend/modules/llm/_adapters/_nano_gpt_http.py`:

```python
"""Nano-GPT HTTP adapter.

Implements the model catalogue (filter/pair/map via ``_nano_gpt_catalog``)
and the Redis-backed pair map (``_nano_gpt_pair_map``). ``stream_completion``
is intentionally a Phase-2 stub.

Key design note — **do not** send ``reasoning`` or ``thinking`` flags in
the request body. Nano-GPT does not honour them; thinking is switched
exclusively by picking the ``thinking_slug`` from the pair map as the
upstream model. This differs from the Ollama adapter's ``"think"``
payload attachment and must not be copied.
"""
from typing import AsyncIterator

from shared.dtos.inference import CompletionRequest
from shared.dtos.llm import ModelMetaDto
from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._events import ProviderStreamEvent
from backend.modules.llm._adapters._types import (
    AdapterTemplate, ConfigFieldHint, ResolvedConnection,
)


class NanoGptHttpAdapter(BaseAdapter):
    adapter_type = "nano_gpt_http"
    display_name = "Nano-GPT"
    view_id = "nano_gpt_http"
    secret_fields = frozenset({"api_key"})

    @classmethod
    def templates(cls) -> list[AdapterTemplate]:
        return [
            AdapterTemplate(
                id="nano_gpt_default",
                display_name="Nano-GPT",
                slug_prefix="nano",
                config_defaults={
                    "base_url": "https://api.nano-gpt.com/v1",
                    "api_key": "",
                    "max_parallel": 3,
                },
                required_config_fields=("api_key",),
            ),
        ]

    @classmethod
    def config_schema(cls) -> list[ConfigFieldHint]:
        return [
            ConfigFieldHint(
                name="base_url", type="url", label="Base URL",
                required=False,
                placeholder="https://api.nano-gpt.com/v1",
            ),
            ConfigFieldHint(
                name="api_key", type="secret", label="API Key",
                required=True,
            ),
            ConfigFieldHint(
                name="max_parallel", type="integer",
                label="Max parallel inferences",
                min=1, max=32,
            ),
        ]

    async def fetch_models(
        self, connection: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        raise NotImplementedError("wired in Task 8")

    async def stream_completion(
        self, connection: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        raise NotImplementedError(
            "Nano-GPT stream_completion is Phase 2 — see "
            "devdocs/superpowers/plans/2026-04-23-nano-gpt-adapter-port.md"
        )
        yield  # pragma: no cover — makes the function an async generator
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_nano_gpt_http.py::test_adapter_identity backend/tests/modules/llm/adapters/test_nano_gpt_http.py::test_templates_shape backend/tests/modules/llm/adapters/test_nano_gpt_http.py::test_config_schema_shape backend/tests/modules/llm/adapters/test_nano_gpt_http.py::test_stream_completion_raises_not_implemented -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_nano_gpt_http.py \
        backend/tests/modules/llm/adapters/test_nano_gpt_http.py
git commit -m "Add NanoGptHttpAdapter skeleton with templates and config schema"
```

---

### Task 8: Wire `fetch_models()` end-to-end (HTTP fetch + catalogue + Redis pair-map)

**Files:**
- Modify: `backend/modules/llm/_adapters/_nano_gpt_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_nano_gpt_http.py`

- [ ] **Step 1: Write the failing test**

Add to `test_nano_gpt_http.py`:

```python
import json
from pathlib import Path
from unittest.mock import AsyncMock

FIXTURES = Path(__file__).parent / "fixtures" / "nano_gpt"


@pytest.mark.asyncio
async def test_fetch_models_from_mini_dump(redis_client, monkeypatch):
    # Load a mini dump fixture (combined pairs + singles + rejectable entries)
    mini_dump = json.loads((FIXTURES / "mini_dump.json").read_text())

    # Mock httpx call to return the mini dump
    async def _fake_get(url, headers=None):
        class _Resp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"data": mini_dump}
        return _Resp()

    monkeypatch.setattr(
        "backend.modules.llm._adapters._nano_gpt_http._http_get_models",
        AsyncMock(side_effect=_fake_get),
    )

    adapter = NanoGptHttpAdapter(redis=redis_client)
    conn = _resolved_conn()

    models = await adapter.fetch_models(conn)

    # Some surviving models (count depends on fixture; assert >0 and all have billing)
    assert len(models) > 0
    for m in models:
        assert m.billing_category in {"subscription", "pay_per_token"}

    # Pair map persisted in Redis
    from backend.modules.llm._adapters._nano_gpt_pair_map import load_pair_map
    pair_map = await load_pair_map(redis_client, connection_id=conn.id)
    assert pair_map  # non-empty — mini dump contains at least one pair
```

Also add a test that pair-map `thinking_slug` is populated for known pair fixtures — pick one concrete model id from `mini_dump.json` and assert its pair-map entry shape.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_nano_gpt_http.py -v -k fetch_models`
Expected: FAIL with `NotImplementedError: wired in Task 8`.

- [ ] **Step 3: Implement `fetch_models()`**

Replace the stub with:

```python
import httpx
from redis.asyncio import Redis
from backend.modules.llm._adapters._nano_gpt_catalog import build_catalogue
from backend.modules.llm._adapters._nano_gpt_pair_map import save_pair_map

_DEFAULT_BASE_URL = "https://api.nano-gpt.com/v1"
_TIMEOUT = 30.0


async def _http_get_models(
    *, base_url: str, api_key: str, timeout: float = _TIMEOUT,
) -> list[dict]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            f"{base_url.rstrip('/')}/models",
            params={"detailed": "true"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()
        payload = resp.json()
    # Nano-GPT's /v1/models wraps entries in `{"data": [...]}` (OpenAI style)
    return payload.get("data", [])


class NanoGptHttpAdapter(BaseAdapter):
    # … (existing class attrs, templates, config_schema) …

    def __init__(self, *, redis: Redis | None = None) -> None:
        self._redis = redis

    async def fetch_models(
        self, connection: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        if self._redis is None:
            raise RuntimeError(
                "NanoGptHttpAdapter requires a redis client for pair-map persistence"
            )
        base_url = connection.config.get("base_url") or _DEFAULT_BASE_URL
        api_key = connection.config["api_key"]

        raw = await _http_get_models(base_url=base_url, api_key=api_key)
        result = build_catalogue(raw)

        # Populate connection-specific fields on each DTO
        dtos = [
            m.model_copy(update={
                "connection_id": connection.id,
                "connection_slug": connection.slug,
                "connection_display_name": connection.display_name,
            })
            for m in result.canonical
        ]

        await save_pair_map(
            self._redis,
            connection_id=connection.id,
            pair_map=result.pair_map,
        )
        return dtos
```

Note: the adapter now takes a `redis` client in `__init__`. Check `_registry.py` to see how adapter instances are constructed — if there's a service factory, plumb the redis client through; otherwise document the construction contract in the adapter docstring and update the registry call site in Task 9.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_nano_gpt_http.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Verify Python build**

Run: `uv run python -m py_compile backend/modules/llm/_adapters/_nano_gpt_http.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_adapters/_nano_gpt_http.py \
        backend/tests/modules/llm/adapters/test_nano_gpt_http.py
git commit -m "Wire nano-gpt fetch_models with catalogue pipeline and Redis pair map"
```

---

### Task 9: Register `nano_gpt_http` in `ADAPTER_REGISTRY`

**Files:**
- Modify: `backend/modules/llm/_registry.py:18-45`
- Test: `backend/tests/modules/llm/test_registry.py` (or analogous existing file)

- [ ] **Step 1: Write the failing test**

Add (or create) in the relevant existing test file:

```python
from backend.modules.llm._registry import ADAPTER_REGISTRY, get_adapter_class
from backend.modules.llm._adapters._nano_gpt_http import NanoGptHttpAdapter


def test_nano_gpt_registered():
    assert "nano_gpt_http" in ADAPTER_REGISTRY
    assert ADAPTER_REGISTRY["nano_gpt_http"] is NanoGptHttpAdapter


def test_get_adapter_class_nano_gpt():
    assert get_adapter_class("nano_gpt_http") is NanoGptHttpAdapter
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/modules/llm/test_registry.py -v -k nano_gpt`
Expected: FAIL with `KeyError` / `AssertionError`.

- [ ] **Step 3: Register the adapter**

In `backend/modules/llm/_registry.py`, add the import near the top:

```python
from backend.modules.llm._adapters._nano_gpt_http import NanoGptHttpAdapter
```

Add to the `ADAPTER_REGISTRY` dict:

```python
ADAPTER_REGISTRY = {
    "ollama_http": OllamaHttpAdapter,
    "community": CommunityAdapter,
    "nano_gpt_http": NanoGptHttpAdapter,
}
```

- [ ] **Step 4: Verify adapter instantiation plumbs redis**

Check how `get_adapter_class(...)` is used in the service layer — specifically whether adapters are instantiated with arguments. If the existing call site is e.g. `adapter = cls()` without arguments, `NanoGptHttpAdapter()` will work but `fetch_models()` will fail on `self._redis is None`. Locate the construction site (likely in `backend/modules/llm/__init__.py` or a service file) and plumb the redis client in. If this is too invasive for this session, document it as a known follow-up and skip — the unit tests construct the adapter directly with `redis=redis_client` and pass.

**Decision:** if the plumbing is a one-line change, do it here. If it touches >3 files or service initialisation, stop and flag back to Chris before proceeding.

- [ ] **Step 5: Run tests**

Run: `uv run pytest backend/tests/modules/llm/ -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_registry.py backend/tests/modules/llm/test_registry.py
git commit -m "Register nano_gpt_http adapter"
```

---

### Task 10: Full verification pass

**Files:** none modified.

- [ ] **Step 1: Run full backend test suite**

Run: `cd /home/chris/workspace/chatsune && uv run pytest backend/ shared/ -v 2>&1 | tail -80`
Expected: all tests PASS, no errors, no skipped-that-were-not-expected.

- [ ] **Step 2: Verify Python build**

Run: `uv run python -m py_compile backend/modules/llm/_adapters/_nano_gpt_http.py backend/modules/llm/_adapters/_nano_gpt_catalog.py backend/modules/llm/_adapters/_nano_gpt_pair_map.py`
Expected: no errors.

- [ ] **Step 3: Check that no `_stubs` references remain**

Run: `rg "_stubs" backend/modules/llm/_adapters/`
Expected: no matches (the stubs were nano-explore-only and should not have leaked in).

- [ ] **Step 4: Check backend Docker build works**

The project has two pyproject.toml — if any new runtime dep was added, `backend/pyproject.toml` must list it. This port adds no new deps (uses existing `pydantic`, `httpx`, `redis`, `pytest-asyncio`). Verify:

Run: `grep -E 'pydantic|httpx|redis' backend/pyproject.toml`
Expected: all three listed.

- [ ] **Step 5: Manual verification steps (to run at end of session, not now)**

These are for Chris to eyeball once the plan is executed:

1. Fire up `docker compose up -d` and verify backend starts cleanly (`docker logs chatsune-backend | tail`). No startup errors.
2. In the frontend connection wizard, "Nano-GPT" should appear as a selectable adapter with templates/config-schema rendered.
3. Provide a real nano-gpt API key in a test connection and call the connection-test endpoint — `/api/llm/connections/{id}/adapter/test` (or whichever is wired). The expectation here is "the connection fails cleanly" or succeeds at the model list — not that streaming works (it is NotImplementedError).
4. Verify `redis-cli keys 'nano_gpt:pair_map:*'` shows a key after `fetch_models` has run.

---

## Self-Review Checklist

(Run this yourself after writing the plan.)

**1. Spec coverage** — does every point in the briefing have a task?

- ✅ Import swap `_stubs` → chatsune — Task 5
- ✅ Adapter file location `_nano_gpt_http.py` — Task 7
- ✅ Pair-map in Redis with 30min TTL — Task 6
- ✅ Connection wizard config (templates, config_schema) — Task 7
- ✅ `stream_completion` as Phase-2 stub — Task 7 (NotImplementedError)
- ✅ Registry registration — Task 9
- ✅ Tests ported — Tasks 4, 5, 6, 7, 8, 9
- ✅ No reasoning/thinking flags in request body — documented in docstring (Task 7), enforced by NotImplementedError in this session
- ✅ Reasoning filter after pair building — preserved by 1:1 port (Task 5)
- ✅ Inverted `-nothinking` pair handled — preserved by 1:1 port + existing fixture (Task 5)
- ✅ `billing_category` field — Task 1
- ✅ Other adapters labelled — Tasks 2, 3

**2. Placeholder scan** — any TBD/TODO/"similar to Task X"?

- None detected. Every task has full code or concrete steps.

**3. Type consistency** — method / field names consistent across tasks?

- `billing_category` used identically in Tasks 1, 2, 3, 5.
- `NanoGptHttpAdapter` class name used consistently from Task 7 onward.
- `save_pair_map` / `load_pair_map` defined in Task 6, referenced by name in Task 8 — match.
- `_http_get_models` defined in Task 8, referenced by monkeypatch in same task — match.

---

## Execution Handoff

**Plan saved.** Recommended execution mode given Chris' preference (global CLAUDE.md: "Subagent preferred" + project CLAUDE.md: "subagent driven implementation always"):

**Subagent-Driven Execution** via `superpowers:subagent-driven-development` — fresh subagent per task, two-stage review between tasks, fast iteration.

# OpenRouter Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add OpenRouter as the fifth Premium Provider and fourth LLM
adapter, restricted to text generation, with a defensive output-modality
filter, auto-cache pass-through, and an explicit `is_moderated` capture
on `ModelMetaDto`.

**Architecture:** New adapter file (`_openrouter_http.py`, structurally
a Mistral clone) plus registry / resolver wiring. One new optional
field on `ModelMetaDto` (`is_moderated: bool | None`). One new
`INSIGHTS.md` entry (INS-032) documenting the deferred
`cache_control` markers.

**Tech Stack:** Python 3.12, FastAPI, httpx async client, Pydantic v2,
pytest. OpenAI-compatible Chat Completions over SSE.

**Spec reference:** `devdocs/specs/2026-04-28-openrouter-integration-design.md`.

**Hard constraints for executing agents:**
- **Do not merge, do not push, do not switch branches.** Stay on the
  current branch. After all tasks complete, hand back to the user for
  merge.
- All new tests must run **without** Mongo (no fixture in this plan
  hits the four DB-using files listed in the user's
  `feedback_db_tests_on_host` memory).
- British English in all code, comments, and identifiers (per the
  user's global instructions).

---

## File Structure

### Files to create

- `backend/modules/llm/_adapters/_openrouter_http.py` — adapter
  implementation. ~500 LOC, Mistral-clone shape.
- `backend/tests/modules/llm/adapters/test_openrouter_http.py` —
  adapter unit tests.

### Files to modify

- `shared/dtos/llm.py` — add `is_moderated: bool | None = None` to
  `ModelMetaDto`.
- `backend/modules/providers/_registry.py` — register the
  `openrouter` Premium Provider.
- `backend/modules/llm/_adapters/__init__.py` — re-export
  `OpenRouterHttpAdapter`.
- `backend/modules/llm/_registry.py` — add to
  `_PREMIUM_ONLY_ADAPTERS`.
- `backend/modules/llm/_resolver.py` — extend
  `_PREMIUM_ADAPTER_TYPE` with `"openrouter": "openrouter_http"`.
- `INSIGHTS.md` — append INS-032.

---

## Task 1: Add `is_moderated` field to `ModelMetaDto`

**Why first:** every later task that emits or asserts a `ModelMetaDto`
relies on the new field existing. A schema change in isolation is the
smallest possible commit.

**Files:**
- Modify: `shared/dtos/llm.py:34` (insert after `billing_category`)
- Test: a new free-standing test file at
  `backend/tests/modules/shared/test_model_meta_is_moderated.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/modules/shared/test_model_meta_is_moderated.py
"""Schema test for the is_moderated field on ModelMetaDto."""

from shared.dtos.llm import ModelMetaDto


def _base() -> dict:
    return {
        "connection_id": "c1",
        "connection_slug": "openrouter",
        "connection_display_name": "OpenRouter",
        "model_id": "openai/gpt-4o",
        "display_name": "GPT-4o",
        "context_window": 128_000,
        "supports_reasoning": False,
        "supports_vision": True,
        "supports_tool_calls": True,
    }


def test_is_moderated_defaults_to_none():
    dto = ModelMetaDto(**_base())
    assert dto.is_moderated is None


def test_is_moderated_accepts_true():
    dto = ModelMetaDto(**_base(), is_moderated=True)
    assert dto.is_moderated is True


def test_is_moderated_accepts_false():
    dto = ModelMetaDto(**_base(), is_moderated=False)
    assert dto.is_moderated is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/modules/shared/test_model_meta_is_moderated.py -v`
Expected: FAIL — Pydantic does not know `is_moderated`.

- [ ] **Step 3: Add the field to `ModelMetaDto`**

In `shared/dtos/llm.py`, immediately after the `billing_category` line
(line 34), insert:

```python
    # ``True``/``False`` when the upstream provider makes an explicit
    # statement (today: only OpenRouter via ``top_provider.is_moderated``).
    # ``None`` = no statement — every other adapter leaves this default.
    # A future "Allow moderated" filter must handle all three buckets
    # (yes / no / unknown) sensibly. Default ``None`` keeps pre-existing
    # cached documents readable — see CLAUDE.md §Data-Model Migrations.
    is_moderated: bool | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest backend/tests/modules/shared/test_model_meta_is_moderated.py -v`
Expected: PASS, three tests.

- [ ] **Step 5: Commit**

```bash
git add shared/dtos/llm.py \
        backend/tests/modules/shared/test_model_meta_is_moderated.py
git commit -m "$(cat <<'EOF'
Add is_moderated capture field to ModelMetaDto

Optional bool | None with None default. None means "upstream made no
statement"; True/False is set explicitly by adapters that read it (today
only OpenRouter via top_provider.is_moderated). Backwards-compatible with
existing cached documents per CLAUDE.md §Data-Model Migrations.
EOF
)"
```

---

## Task 2: Register the `openrouter` Premium Provider

**Files:**
- Modify: `backend/modules/providers/_registry.py:90` (append within
  `_register_builtins`, after the `nano_gpt` block)
- Test: `backend/tests/modules/providers/test_openrouter_registration.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/modules/providers/test_openrouter_registration.py
"""Verifies the openrouter provider is registered with the right shape."""

from backend.modules.providers._registry import get
from shared.dtos.providers import Capability


def test_openrouter_provider_is_registered():
    defn = get("openrouter")
    assert defn is not None


def test_openrouter_capabilities_are_llm_only():
    defn = get("openrouter")
    assert defn.capabilities == [Capability.LLM]


def test_openrouter_probe_url_targets_user_endpoint():
    defn = get("openrouter")
    # /models/user (authenticated) — not /models (public) — so an
    # invalid key actually fails the probe.
    assert defn.probe_url == (
        "https://openrouter.ai/api/v1/models/user?output_modalities=text"
    )
    assert defn.probe_method == "GET"


def test_openrouter_base_url():
    defn = get("openrouter")
    assert defn.base_url == "https://openrouter.ai/api/v1"


def test_openrouter_has_api_key_field():
    defn = get("openrouter")
    keys = [f["key"] for f in defn.config_fields]
    assert keys == ["api_key"]


def test_openrouter_has_no_linked_integrations():
    defn = get("openrouter")
    assert defn.linked_integrations == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/modules/providers/test_openrouter_registration.py -v`
Expected: FAIL — `get("openrouter")` returns `None`.

- [ ] **Step 3: Register the provider**

In `backend/modules/providers/_registry.py`, append within
`_register_builtins()`, immediately after the `nano_gpt` block:

```python
    register(PremiumProviderDefinition(
        id="openrouter",
        display_name="OpenRouter",
        icon="openrouter",
        base_url="https://openrouter.ai/api/v1",
        capabilities=[Capability.LLM],
        config_fields=[_api_key_field("OpenRouter API Key")],
        # /models/user requires the key and 401s on bad keys, so it's
        # the right probe target. /models is public and would falsely
        # accept anything.
        probe_url="https://openrouter.ai/api/v1/models/user?output_modalities=text",
        probe_method="GET",
        linked_integrations=[],
    ))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest backend/tests/modules/providers/test_openrouter_registration.py -v`
Expected: PASS, six tests.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/providers/_registry.py \
        backend/tests/modules/providers/test_openrouter_registration.py
git commit -m "Register OpenRouter as a Premium Provider (LLM capability)"
```

---

## Task 3: Wire `openrouter` into the resolver mapping

**Files:**
- Modify: `backend/modules/llm/_resolver.py:33` (append entry to
  `_PREMIUM_ADAPTER_TYPE`)
- Test: `backend/tests/modules/llm/test_resolver_openrouter.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/modules/llm/test_resolver_openrouter.py
"""Verifies the resolver maps the openrouter premium id to its adapter."""

from backend.modules.llm._resolver import _PREMIUM_ADAPTER_TYPE


def test_openrouter_maps_to_openrouter_http_adapter():
    assert _PREMIUM_ADAPTER_TYPE["openrouter"] == "openrouter_http"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/modules/llm/test_resolver_openrouter.py -v`
Expected: FAIL — KeyError on `"openrouter"`.

- [ ] **Step 3: Add the mapping**

In `backend/modules/llm/_resolver.py`, extend the
`_PREMIUM_ADAPTER_TYPE` dict (around line 33–38) with one line:

```python
_PREMIUM_ADAPTER_TYPE: dict[str, str] = {
    "xai": "xai_http",
    "mistral": "mistral_http",
    "ollama_cloud": "ollama_http",
    "nano_gpt": "nano_gpt_http",
    "openrouter": "openrouter_http",
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest backend/tests/modules/llm/test_resolver_openrouter.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_resolver.py \
        backend/tests/modules/llm/test_resolver_openrouter.py
git commit -m "Map premium 'openrouter' to openrouter_http adapter"
```

---

## Task 4: Create the adapter skeleton (identity + abstract methods raise)

The skeleton lets the registry and import machinery start working
immediately. Real `fetch_models` and `stream_completion` are filled in
by Tasks 5–11.

**Files:**
- Create: `backend/modules/llm/_adapters/_openrouter_http.py`
- Modify: `backend/modules/llm/_adapters/__init__.py` (re-export)
- Modify: `backend/modules/llm/_registry.py:33` (add to
  `_PREMIUM_ONLY_ADAPTERS`)
- Test: `backend/tests/modules/llm/adapters/test_openrouter_http.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/modules/llm/adapters/test_openrouter_http.py
"""Tests for the OpenRouter HTTP adapter.

Covers identity, model-list mapping, defensive modality filter,
auth/error handling, payload shape (incl. reasoning logic), SSE parser
extensions, and the /test sub-router.
"""

from __future__ import annotations

import pytest

from backend.modules.llm._adapters._openrouter_http import (
    OpenRouterHttpAdapter,
)
from backend.modules.llm._registry import (
    ADAPTER_REGISTRY,
    get_adapter_class,
)


def test_adapter_identity():
    a = OpenRouterHttpAdapter()
    assert a.adapter_type == "openrouter_http"
    assert a.display_name == "OpenRouter"
    assert a.view_id == "openrouter_http"
    assert a.secret_fields == frozenset({"api_key"})


def test_adapter_is_premium_only_not_user_creatable():
    # User-facing registry must NOT contain openrouter — it is premium-only.
    assert "openrouter_http" not in ADAPTER_REGISTRY
    # But the resolver helper should find it.
    assert get_adapter_class("openrouter_http") is OpenRouterHttpAdapter
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_openrouter_http.py -v`
Expected: FAIL — `ImportError: cannot import name 'OpenRouterHttpAdapter'`.

- [ ] **Step 3: Create the skeleton file**

Create `backend/modules/llm/_adapters/_openrouter_http.py`:

```python
"""OpenRouter HTTP adapter — OpenAI-compatible Chat Completions.

Premium-only adapter: not user-creatable. Instantiated exclusively via
the Premium Provider resolver (see ``backend.modules.llm._resolver``).
Routes to OpenRouter's unified API which fans out to 50+ upstream
providers; we apply ``output_modalities=text`` at the model-listing
endpoint so only text-output models reach the Model Browser.

Cache control: pass-through. OpenRouter performs automatic prefix
caching for OpenAI / Gemini / DeepSeek; Anthropic-style explicit
``cache_control`` markers are deferred — see INS-032 in INSIGHTS.md.

Structurally a Mistral clone. The OpenAI-compatible SSE parser,
tool-call accumulator, and gutter-timer logic are intentionally copied
in (not imported); the shared-helper extract refactor is tracked
separately.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._events import ProviderStreamEvent
from backend.modules.llm._adapters._types import ResolvedConnection
from shared.dtos.inference import CompletionRequest
from shared.dtos.llm import ModelMetaDto


class OpenRouterHttpAdapter(BaseAdapter):
    adapter_type = "openrouter_http"
    display_name = "OpenRouter"
    view_id = "openrouter_http"
    secret_fields = frozenset({"api_key"})

    async def fetch_models(
        self, c: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        raise NotImplementedError  # filled in Task 5

    async def stream_completion(
        self, c: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        raise NotImplementedError  # filled in Task 10
        yield  # pragma: no cover  # makes the type checker accept the signature
```

- [ ] **Step 4: Add the re-export**

Inspect `backend/modules/llm/_adapters/__init__.py` and add an
`OpenRouterHttpAdapter` import / re-export following the pattern used
for the existing adapters. If the file simply imports each class for
side-effect (registration), insert:

```python
from backend.modules.llm._adapters._openrouter_http import OpenRouterHttpAdapter  # noqa: F401
```

at the same level as the existing `MistralHttpAdapter` import.

- [ ] **Step 5: Add to `_PREMIUM_ONLY_ADAPTERS`**

In `backend/modules/llm/_registry.py`, near line 33–37:

```python
from backend.modules.llm._adapters._openrouter_http import OpenRouterHttpAdapter
```

…and extend the dict:

```python
_PREMIUM_ONLY_ADAPTERS: dict[str, type[BaseAdapter]] = {
    "xai_http": XaiHttpAdapter,
    "mistral_http": MistralHttpAdapter,
    "nano_gpt_http": NanoGptHttpAdapter,
    "openrouter_http": OpenRouterHttpAdapter,
}
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
uv run pytest backend/tests/modules/llm/adapters/test_openrouter_http.py::test_adapter_identity -v
uv run pytest backend/tests/modules/llm/adapters/test_openrouter_http.py::test_adapter_is_premium_only_not_user_creatable -v
```

Expected: both PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/llm/_adapters/_openrouter_http.py \
        backend/modules/llm/_adapters/__init__.py \
        backend/modules/llm/_registry.py \
        backend/tests/modules/llm/adapters/test_openrouter_http.py
git commit -m "Add OpenRouter adapter skeleton; register as premium-only"
```

---

## Task 5: Implement `fetch_models` happy-path mapping

**Files:**
- Modify: `backend/modules/llm/_adapters/_openrouter_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_openrouter_http.py`

- [ ] **Step 1: Write the failing test**

Append to `test_openrouter_http.py`:

```python
import json
from datetime import UTC, datetime
from unittest.mock import patch

import httpx

from backend.modules.llm._adapters._types import ResolvedConnection


def _resolved() -> ResolvedConnection:
    return ResolvedConnection(
        id="premium:openrouter",
        user_id="u1",
        adapter_type="openrouter_http",
        display_name="OpenRouter",
        slug="openrouter",
        config={
            "url": "https://openrouter.ai/api/v1",
            "api_key": "sk-or-v1-fake",
        },
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


_MODELS_USER_RESPONSE = {
    "data": [
        {
            "id": "openai/gpt-4o",
            "name": "OpenAI: GPT-4o",
            "context_length": 128_000,
            "architecture": {
                "modality": "text+image->text",
                "input_modalities": ["text", "image"],
                "output_modalities": ["text"],
            },
            "pricing": {"prompt": "0.0000025", "completion": "0.00001"},
            "top_provider": {
                "context_length": 128_000,
                "max_completion_tokens": 16_384,
                "is_moderated": True,
            },
            "supported_parameters": [
                "max_tokens", "temperature", "tools", "tool_choice",
            ],
            "expiration_date": None,
        },
        {
            "id": "deepseek/deepseek-r1:free",
            "name": "DeepSeek: R1 (free)",
            "context_length": 64_000,
            "architecture": {
                "modality": "text->text",
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
            "pricing": {"prompt": "0", "completion": "0"},
            "top_provider": {
                "context_length": 64_000,
                "max_completion_tokens": 8_192,
                "is_moderated": False,
            },
            "supported_parameters": [
                "include_reasoning", "reasoning", "max_tokens", "temperature",
            ],
            "expiration_date": None,
        },
    ],
}


class _FakeAsyncClient:
    """Stand-in for httpx.AsyncClient that returns a canned response."""

    def __init__(self, *_, **__):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def get(self, url, headers=None):  # noqa: ARG002
        return httpx.Response(
            status_code=200,
            content=json.dumps(_MODELS_USER_RESPONSE).encode(),
            request=httpx.Request("GET", url),
        )


@pytest.mark.asyncio
async def test_fetch_models_maps_fields_correctly():
    a = OpenRouterHttpAdapter()
    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        _FakeAsyncClient,
    ):
        models = await a.fetch_models(_resolved())

    by_id = {m.model_id: m for m in models}

    gpt = by_id["openai/gpt-4o"]
    assert gpt.display_name == "OpenAI: GPT-4o"
    assert gpt.context_window == 128_000
    assert gpt.supports_vision is True       # input_modalities contains "image"
    assert gpt.supports_reasoning is False   # neither key in supported_parameters
    assert gpt.supports_tool_calls is True   # "tools" in supported_parameters
    assert gpt.is_moderated is True
    assert gpt.is_deprecated is False
    assert gpt.billing_category == "pay_per_token"
    assert gpt.connection_slug == "openrouter"

    r1 = by_id["deepseek/deepseek-r1:free"]
    assert r1.supports_vision is False
    assert r1.supports_reasoning is True     # both reasoning keys present
    assert r1.supports_tool_calls is False   # "tools" missing
    assert r1.is_moderated is False
    assert r1.billing_category == "free"     # both pricing fields == "0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_openrouter_http.py::test_fetch_models_maps_fields_correctly -v`
Expected: FAIL — `NotImplementedError`.

- [ ] **Step 3: Implement `fetch_models`**

Replace the `fetch_models` body in `_openrouter_http.py`:

```python
import logging

import httpx

_log = logging.getLogger(__name__)
_PROBE_TIMEOUT = httpx.Timeout(10.0)


def _supports(parameters: list[str], *names: str) -> bool:
    return any(n in parameters for n in names)


def _billing_category(pricing: dict) -> str:
    prompt = pricing.get("prompt") if isinstance(pricing, dict) else None
    completion = pricing.get("completion") if isinstance(pricing, dict) else None
    if prompt == "0" and completion == "0":
        return "free"
    return "pay_per_token"


def _entry_to_meta(entry: dict, c: ResolvedConnection) -> ModelMetaDto | None:
    arch = entry.get("architecture") or {}
    input_mods = arch.get("input_modalities") or []
    params = entry.get("supported_parameters") or []
    pricing = entry.get("pricing") or {}
    top = entry.get("top_provider") or {}

    raw_moderated = top.get("is_moderated")
    is_moderated: bool | None
    if isinstance(raw_moderated, bool):
        is_moderated = raw_moderated
    else:
        is_moderated = None

    return ModelMetaDto(
        connection_id=c.id,
        connection_slug=c.slug,
        connection_display_name=c.display_name,
        model_id=entry["id"],
        display_name=entry.get("name") or entry["id"],
        context_window=int(entry.get("context_length") or 0),
        supports_reasoning=_supports(params, "reasoning", "include_reasoning"),
        supports_vision="image" in input_mods,
        supports_tool_calls=_supports(params, "tools"),
        is_deprecated=entry.get("expiration_date") is not None,
        billing_category=_billing_category(pricing),
        is_moderated=is_moderated,
    )
```

…and replace the body of `OpenRouterHttpAdapter.fetch_models`:

```python
    async def fetch_models(
        self, c: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        url = c.config["url"].rstrip("/")
        api_key = c.config.get("api_key") or ""
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
                resp = await client.get(
                    f"{url}/models/user?output_modalities=text",
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            _log.warning("openrouter_http.fetch_models transport: %s", exc)
            return []

        if resp.status_code in (401, 403):
            _log.warning(
                "openrouter_http.fetch_models auth failure: status=%d",
                resp.status_code,
            )
            return []
        if resp.status_code != 200:
            _log.warning(
                "openrouter_http.fetch_models upstream %d: %s",
                resp.status_code, resp.text[:200],
            )
            return []

        try:
            data = resp.json()
        except ValueError:
            _log.warning("openrouter_http.fetch_models malformed JSON")
            return []

        entries = data.get("data") or []
        if not isinstance(entries, list):
            return []

        metas: list[ModelMetaDto] = []
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("id"):
                continue
            meta = _entry_to_meta(entry, c)
            if meta is not None:
                metas.append(meta)
        return metas
```

(Add `pytest_asyncio` is unnecessary; existing Mistral tests use
`@pytest.mark.asyncio` — make sure the test file marks the suite if
required. Check `backend/tests/modules/llm/adapters/test_mistral_http.py`
top-of-file or `pyproject.toml` for the `asyncio_mode` setting. If
`asyncio_mode = "auto"` is set, the marker is optional; otherwise the
marker stays.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_openrouter_http.py::test_fetch_models_maps_fields_correctly -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_openrouter_http.py \
        backend/tests/modules/llm/adapters/test_openrouter_http.py
git commit -m "Implement OpenRouter fetch_models field mapping"
```

---

## Task 6: Add the defensive output-modality filter

Drops entries whose `architecture.output_modalities` is missing or not
exactly `["text"]`. Belt-and-braces around the `?output_modalities=text`
query param.

**Files:**
- Modify: `backend/modules/llm/_adapters/_openrouter_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_openrouter_http.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
_MODELS_USER_RESPONSE_WITH_IMAGE_OUTPUT = {
    "data": [
        {
            "id": "openai/gpt-4o",
            "name": "OpenAI: GPT-4o",
            "context_length": 128_000,
            "architecture": {
                "modality": "text+image->text",
                "input_modalities": ["text", "image"],
                "output_modalities": ["text"],
            },
            "pricing": {"prompt": "0", "completion": "0"},
            "top_provider": {"is_moderated": False},
            "supported_parameters": [],
            "expiration_date": None,
        },
        {
            "id": "stability/sdxl",
            "name": "SDXL",
            "context_length": 2048,
            "architecture": {
                "modality": "text->image",
                "input_modalities": ["text"],
                "output_modalities": ["image"],
            },
            "pricing": {"prompt": "0", "completion": "0"},
            "top_provider": {"is_moderated": False},
            "supported_parameters": [],
            "expiration_date": None,
        },
        {
            "id": "multimodal/text-and-image-output",
            "name": "Mixed Output",
            "context_length": 32_000,
            "architecture": {
                "modality": "text->text+image",
                "input_modalities": ["text"],
                "output_modalities": ["text", "image"],
            },
            "pricing": {"prompt": "0", "completion": "0"},
            "top_provider": {"is_moderated": False},
            "supported_parameters": [],
            "expiration_date": None,
        },
        {
            "id": "broken/missing-arch",
            "name": "No Architecture",
            "context_length": 1024,
            "pricing": {"prompt": "0", "completion": "0"},
            "top_provider": {"is_moderated": False},
            "supported_parameters": [],
            "expiration_date": None,
        },
    ],
}


class _FakeAsyncClientImageOutput(_FakeAsyncClient):
    async def get(self, url, headers=None):  # noqa: ARG002
        return httpx.Response(
            status_code=200,
            content=json.dumps(
                _MODELS_USER_RESPONSE_WITH_IMAGE_OUTPUT
            ).encode(),
            request=httpx.Request("GET", url),
        )


@pytest.mark.asyncio
async def test_fetch_models_filters_non_text_output():
    a = OpenRouterHttpAdapter()
    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        _FakeAsyncClientImageOutput,
    ):
        models = await a.fetch_models(_resolved())

    ids = {m.model_id for m in models}
    # Only the strict text-only output model survives.
    assert ids == {"openai/gpt-4o"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_openrouter_http.py::test_fetch_models_filters_non_text_output -v`
Expected: FAIL — currently all four entries pass through.

- [ ] **Step 3: Add the filter to `_entry_to_meta`**

Modify `_entry_to_meta` to return `None` when the output-modality
constraint is not satisfied. Place the check right at the top of the
function:

```python
def _entry_to_meta(entry: dict, c: ResolvedConnection) -> ModelMetaDto | None:
    arch = entry.get("architecture") or {}
    output_mods = arch.get("output_modalities")
    # Strict: exactly ["text"]. Image-only, audio-only, and mixed
    # output (e.g. text+image) are out of scope for Phase 1.
    if output_mods != ["text"]:
        return None

    input_mods = arch.get("input_modalities") or []
    # ... (rest unchanged)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_openrouter_http.py::test_fetch_models_filters_non_text_output -v`
Expected: PASS.

Also re-run the previous test to ensure no regression:

```bash
uv run pytest backend/tests/modules/llm/adapters/test_openrouter_http.py::test_fetch_models_maps_fields_correctly -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_openrouter_http.py \
        backend/tests/modules/llm/adapters/test_openrouter_http.py
git commit -m "Filter non-text output modalities in OpenRouter fetch_models"
```

---

## Task 7: `fetch_models` auth and transport error paths

**Files:**
- Modify: `backend/tests/modules/llm/adapters/test_openrouter_http.py`

(No production code changes — implementation already handles these
in Task 5; this task locks the behaviour in with explicit tests.)

- [ ] **Step 1: Write the failing tests**

Append:

```python
class _FakeAsyncClient401(_FakeAsyncClient):
    async def get(self, url, headers=None):  # noqa: ARG002
        return httpx.Response(
            status_code=401,
            content=b'{"error":{"code":401,"message":"Bad key"}}',
            request=httpx.Request("GET", url),
        )


class _FakeAsyncClient500(_FakeAsyncClient):
    async def get(self, url, headers=None):  # noqa: ARG002
        return httpx.Response(
            status_code=500,
            content=b"upstream blew up",
            request=httpx.Request("GET", url),
        )


class _FakeAsyncClientTransport(_FakeAsyncClient):
    async def get(self, url, headers=None):  # noqa: ARG002
        raise httpx.ConnectError("network down")


@pytest.mark.asyncio
async def test_fetch_models_returns_empty_on_401():
    a = OpenRouterHttpAdapter()
    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        _FakeAsyncClient401,
    ):
        models = await a.fetch_models(_resolved())
    assert models == []


@pytest.mark.asyncio
async def test_fetch_models_returns_empty_on_5xx():
    a = OpenRouterHttpAdapter()
    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        _FakeAsyncClient500,
    ):
        models = await a.fetch_models(_resolved())
    assert models == []


@pytest.mark.asyncio
async def test_fetch_models_returns_empty_on_transport_error():
    a = OpenRouterHttpAdapter()
    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        _FakeAsyncClientTransport,
    ):
        models = await a.fetch_models(_resolved())
    assert models == []
```

- [ ] **Step 2: Run tests to verify they pass**

Run:
```bash
uv run pytest backend/tests/modules/llm/adapters/test_openrouter_http.py -k fetch_models -v
```

Expected: all five `fetch_models_*` tests PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/modules/llm/adapters/test_openrouter_http.py
git commit -m "Add OpenRouter fetch_models error-path tests"
```

---

## Task 8: Clone SSE helpers from Mistral with `delta.reasoning` extension

Adds module-level helpers: `_ToolCallAccumulator`, `_parse_sse_line`,
`_chunk_to_events`, plus the `_SSE_DONE` sentinel and OpenAI-compatible
`_REFUSAL_REASONS` constants. Extension vs Mistral: `delta.reasoning`
(plain key, OpenRouter normalisation) yields a `ThinkingDelta` in
addition to `delta.reasoning_content` (already handled).

**Files:**
- Modify: `backend/modules/llm/_adapters/_openrouter_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_openrouter_http.py`

- [ ] **Step 1: Write the failing tests**

Append to the test file:

```python
from backend.modules.llm._adapters._events import (
    ContentDelta,
    StreamDone,
    StreamRefused,
    ThinkingDelta,
    ToolCallEvent,
)
from backend.modules.llm._adapters._openrouter_http import (
    _chunk_to_events,
    _parse_sse_line,
    _SSE_DONE,
    _ToolCallAccumulator,
)


def test_parse_sse_line_returns_dict_for_data_line():
    out = _parse_sse_line('data: {"a":1}')
    assert out == {"a": 1}


def test_parse_sse_line_returns_done_sentinel_for_done_marker():
    assert _parse_sse_line("data: [DONE]") is _SSE_DONE


def test_parse_sse_line_returns_none_for_empty_or_malformed():
    assert _parse_sse_line("") is None
    assert _parse_sse_line("data: not json") is None


def test_chunk_emits_content_delta():
    acc = _ToolCallAccumulator()
    events = _chunk_to_events(
        {"choices": [{"delta": {"content": "hi"}}]}, acc,
    )
    assert events == [ContentDelta(delta="hi")]


def test_chunk_emits_thinking_delta_for_reasoning_content():
    acc = _ToolCallAccumulator()
    events = _chunk_to_events(
        {"choices": [{"delta": {"reasoning_content": "hmm"}}]}, acc,
    )
    assert events == [ThinkingDelta(delta="hmm")]


def test_chunk_emits_thinking_delta_for_plain_reasoning_key():
    """OpenRouter normalises some upstream models' thinking output to
    `delta.reasoning` (plain key). Must produce a ThinkingDelta."""
    acc = _ToolCallAccumulator()
    events = _chunk_to_events(
        {"choices": [{"delta": {"reasoning": "thinking"}}]}, acc,
    )
    assert events == [ThinkingDelta(delta="thinking")]


def test_chunk_emits_stream_done_on_usage_chunk():
    acc = _ToolCallAccumulator()
    events = _chunk_to_events(
        {
            "choices": [],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }, acc,
    )
    assert events == [StreamDone(input_tokens=10, output_tokens=20)]


def test_chunk_emits_refusal_on_content_filter():
    acc = _ToolCallAccumulator()
    events = _chunk_to_events(
        {"choices": [{"finish_reason": "content_filter", "delta": {}}]},
        acc,
    )
    assert any(isinstance(e, StreamRefused) for e in events)


def test_accumulator_collects_tool_call_across_fragments():
    acc = _ToolCallAccumulator()
    acc.ingest([{"index": 0, "id": "call_1",
                 "function": {"name": "lookup", "arguments": '{"q":'}}])
    acc.ingest([{"index": 0,
                 "function": {"arguments": '"hello"}'}}])
    finalised = acc.finalised()
    assert finalised == [{
        "id": "call_1", "name": "lookup", "arguments": '{"q":"hello"}',
    }]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_openrouter_http.py -k "parse_sse_line or chunk_emits or accumulator" -v`
Expected: FAIL with ImportError on the new helper symbols.

- [ ] **Step 3: Add the helpers to `_openrouter_http.py`**

These are copied verbatim from `_mistral_http.py` lines ~50–161, with
**one addition** in `_chunk_to_events`. Add the helpers at module
scope, above the adapter class. The complete code:

```python
import json
from uuid import uuid4

from backend.modules.llm._adapters._events import (
    ContentDelta,
    StreamAborted,
    StreamDone,
    StreamError,
    StreamRefused,
    StreamSlow,
    ThinkingDelta,
    ToolCallEvent,
)

_REFUSAL_REASONS: frozenset[str] = frozenset({"content_filter", "refusal"})

_SSE_DONE = object()


class _ToolCallAccumulator:
    """Gathers OpenAI-style tool_call fragments across SSE chunks."""

    def __init__(self) -> None:
        self._by_index: dict[int, dict] = {}

    def ingest(self, fragments: list[dict]) -> None:
        for frag in fragments:
            idx = frag.get("index")
            if idx is None:
                continue
            slot = self._by_index.setdefault(idx, {
                "id": None, "name": "", "args": "",
            })
            if frag.get("id"):
                slot["id"] = frag["id"]
            fn = frag.get("function") or {}
            if fn.get("name"):
                slot["name"] = fn["name"]
            if fn.get("arguments"):
                slot["args"] += fn["arguments"]

    def finalised(self) -> list[dict]:
        calls: list[dict] = []
        for _, slot in sorted(self._by_index.items()):
            calls.append({
                "id": slot["id"] or f"call_{uuid4().hex[:12]}",
                "name": slot["name"],
                "arguments": slot["args"] or "{}",
            })
        return calls


def _chunk_to_events(
    chunk: dict, acc: _ToolCallAccumulator,
) -> list[ProviderStreamEvent]:
    events: list[ProviderStreamEvent] = []
    choices = chunk.get("choices") or []
    usage = chunk.get("usage") or {}

    if usage and not choices:
        events.append(StreamDone(
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        ))
        return events

    if not choices:
        return events

    choice = choices[0]
    delta = choice.get("delta") or {}

    # OpenAI convention: reasoning_content
    reasoning_content = delta.get("reasoning_content") or ""
    if reasoning_content:
        events.append(ThinkingDelta(delta=reasoning_content))

    # OpenRouter normalisation: plain reasoning key.
    # Some upstream providers stream their thinking under the bare
    # ``reasoning`` field; emit ThinkingDelta for both.
    reasoning = delta.get("reasoning") or ""
    if reasoning:
        events.append(ThinkingDelta(delta=reasoning))

    content = delta.get("content") or ""
    if content:
        events.append(ContentDelta(delta=content))

    tool_frags = delta.get("tool_calls") or []
    if tool_frags:
        acc.ingest(tool_frags)

    finish = choice.get("finish_reason")
    if finish is None:
        return events

    if finish == "tool_calls":
        for call in acc.finalised():
            events.append(ToolCallEvent(
                id=call["id"], name=call["name"],
                arguments=call["arguments"],
            ))
    elif finish in _REFUSAL_REASONS:
        events.append(StreamRefused(
            reason=finish,
            refusal_text=delta.get("refusal") or None,
        ))

    return events


def _parse_sse_line(line: str) -> dict | object | None:
    line = line.strip()
    if not line or not line.startswith("data:"):
        return None
    payload = line[len("data:"):].strip()
    if payload == "[DONE]":
        return _SSE_DONE
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        _log.warning("Skipping malformed SSE JSON: %s", payload[:200])
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_openrouter_http.py -k "parse_sse_line or chunk_emits or accumulator" -v`
Expected: nine tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_openrouter_http.py \
        backend/tests/modules/llm/adapters/test_openrouter_http.py
git commit -m "Add OpenRouter SSE helpers (clone of Mistral) with delta.reasoning extension"
```

---

## Task 9: Implement `_translate_message`, `_build_chat_payload` (incl. reasoning logic)

**Files:**
- Modify: `backend/modules/llm/_adapters/_openrouter_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_openrouter_http.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
from backend.modules.llm._adapters._openrouter_http import (
    _build_chat_payload,
    _translate_message,
)
from shared.dtos.inference import (
    CompletionMessage,
    CompletionRequest,
    ContentPart,
    ToolCallResult,
    ToolDefinition,
)


def test_translate_text_only_user_message():
    msg = CompletionMessage(role="user",
                            content=[ContentPart(type="text", text="hi")])
    assert _translate_message(msg) == {"role": "user", "content": "hi"}


def test_translate_image_message_uses_openai_image_url_format():
    msg = CompletionMessage(role="user", content=[
        ContentPart(type="text", text="describe"),
        ContentPart(type="image", data="aGVsbG8=", media_type="image/png"),
    ])
    out = _translate_message(msg)
    assert out["role"] == "user"
    assert isinstance(out["content"], list)
    assert out["content"][0] == {"type": "text", "text": "describe"}
    assert out["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,aGVsbG8="},
    }


def test_build_payload_passes_model_through():
    req = CompletionRequest(
        model="openai/gpt-4o",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="hi")],
        )],
    )
    payload = _build_chat_payload(req)
    assert payload["model"] == "openai/gpt-4o"
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}


def test_build_payload_includes_temperature_when_set():
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
        temperature=0.4,
    )
    assert _build_chat_payload(req)["temperature"] == 0.4


def test_build_payload_omits_temperature_when_none():
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
    )
    assert "temperature" not in _build_chat_payload(req)


def test_build_payload_translates_tools():
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
        tools=[ToolDefinition(
            name="lookup", description="d", parameters={"type": "object"},
        )],
    )
    payload = _build_chat_payload(req)
    assert payload["tools"] == [{
        "type": "function",
        "function": {
            "name": "lookup", "description": "d",
            "parameters": {"type": "object"},
        },
    }]


def test_reasoning_field_omitted_when_enabled_and_supported():
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
        supports_reasoning=True, reasoning_enabled=True,
    )
    assert "reasoning" not in _build_chat_payload(req)


def test_reasoning_field_set_to_exclude_when_disabled_and_supported():
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
        supports_reasoning=True, reasoning_enabled=False,
    )
    payload = _build_chat_payload(req)
    assert payload["reasoning"] == {"exclude": True}


def test_reasoning_field_omitted_when_unsupported():
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
        supports_reasoning=False, reasoning_enabled=True,
    )
    assert "reasoning" not in _build_chat_payload(req)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_openrouter_http.py -k "translate or build_payload or reasoning_field" -v`
Expected: FAIL on ImportError of `_translate_message` / `_build_chat_payload`.

- [ ] **Step 3: Add `_translate_message` and `_build_chat_payload`**

Append at module scope below the SSE helpers:

```python
from shared.dtos.inference import CompletionMessage, CompletionRequest


def _translate_message(msg: CompletionMessage) -> dict:
    text_parts = [p for p in msg.content if p.type == "text" and p.text]
    image_parts = [p for p in msg.content if p.type == "image" and p.data]

    if not image_parts:
        content: str | list[dict] = "".join(p.text or "" for p in text_parts)
    else:
        content = []
        for p in text_parts:
            content.append({"type": "text", "text": p.text or ""})
        for p in image_parts:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{p.media_type};base64,{p.data}",
                },
            })

    result: dict = {"role": msg.role, "content": content}
    if msg.tool_calls:
        result["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": tc.arguments},
            }
            for tc in msg.tool_calls
        ]
    if msg.tool_call_id is not None:
        result["tool_call_id"] = msg.tool_call_id
    return result


def _build_chat_payload(request: CompletionRequest) -> dict:
    payload: dict = {
        "model": request.model,
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [_translate_message(m) for m in request.messages],
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.name, "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in request.tools
        ]
    # Reasoning: only emit when meaningful. We do not expose effort
    # levels in this iteration. ``exclude: true`` controls visibility,
    # not whether the model reasons; built-in reasoners ignore it.
    if request.supports_reasoning and not request.reasoning_enabled:
        payload["reasoning"] = {"exclude": True}
    return payload
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_openrouter_http.py -k "translate or build_payload or reasoning_field" -v`
Expected: nine tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_openrouter_http.py \
        backend/tests/modules/llm/adapters/test_openrouter_http.py
git commit -m "Add OpenRouter payload builder with reasoning visibility logic"
```

---

## Task 10: Implement `stream_completion` happy path

**Files:**
- Modify: `backend/modules/llm/_adapters/_openrouter_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_openrouter_http.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
import asyncio


class _FakeStreamResponse:
    """httpx response stand-in that yields prepared SSE lines."""

    def __init__(self, lines: list[str], status_code: int = 200):
        self._lines = lines
        self.status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            await asyncio.sleep(0)
            yield line

    async def aread(self):
        return b""


class _FakeStreamingClient:
    """httpx.AsyncClient stand-in that returns a canned SSE stream."""

    def __init__(self, lines, status_code=200):
        self._lines = lines
        self._status = status_code

    def __call__(self, *_, **__):  # used as ctor when patched
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def stream(self, method, url, json=None, headers=None):  # noqa: ARG002
        return _FakeStreamResponse(self._lines, self._status)


@pytest.mark.asyncio
async def test_stream_completion_emits_content_then_done():
    lines = [
        'data: {"choices":[{"delta":{"content":"Hel"}}]}',
        'data: {"choices":[{"delta":{"content":"lo"}}]}',
        'data: {"choices":[{"finish_reason":"stop","delta":{}}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":2}}',
        "data: [DONE]",
    ]
    fake = _FakeStreamingClient(lines)

    a = OpenRouterHttpAdapter()
    req = CompletionRequest(
        model="openai/gpt-4o",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="hi")],
        )],
    )

    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        lambda *_args, **_kw: fake,
    ):
        events = []
        async for ev in a.stream_completion(_resolved(), req):
            events.append(ev)

    contents = [e for e in events if isinstance(e, ContentDelta)]
    dones = [e for e in events if isinstance(e, StreamDone)]
    assert "".join(c.delta for c in contents) == "Hello"
    assert len(dones) == 1
    assert dones[0].input_tokens == 3
    assert dones[0].output_tokens == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_openrouter_http.py::test_stream_completion_emits_content_then_done -v`
Expected: FAIL — `NotImplementedError`.

- [ ] **Step 3: Implement `stream_completion`**

Add at module scope:

```python
import asyncio
import os
import time

GUTTER_SLOW_SECONDS: float = 30.0
GUTTER_ABORT_SECONDS: float = float(
    os.environ.get("LLM_STREAM_ABORT_SECONDS", "120"),
)
_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=15.0)
_TRACE_PAYLOADS = os.environ.get("LLM_TRACE_PAYLOADS") == "1"

_OPENROUTER_REFERER = "https://chatsune.app"
_OPENROUTER_X_TITLE = "Chatsune"
```

…and replace the `stream_completion` body:

```python
    async def stream_completion(
        self, c: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        url = c.config["url"].rstrip("/")
        api_key = c.config.get("api_key") or ""
        payload = _build_chat_payload(request)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": _OPENROUTER_REFERER,
            "X-Title": _OPENROUTER_X_TITLE,
        }

        acc = _ToolCallAccumulator()
        seen_done = False
        pending_next: asyncio.Task | None = None

        if _TRACE_PAYLOADS:
            _log.info(
                "LLM_TRACE path=openrouter-out url=%s payload=%s",
                url, json.dumps(payload, default=str, sort_keys=True),
            )

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                async with client.stream(
                    "POST", f"{url}/chat/completions",
                    json=payload, headers=headers,
                ) as resp:
                    if resp.status_code in (401, 403):
                        yield StreamError(
                            error_code="invalid_api_key",
                            message="OpenRouter rejected the API key",
                        )
                        return
                    if resp.status_code == 429:
                        yield StreamError(
                            error_code="provider_unavailable",
                            message="OpenRouter rate limit hit",
                        )
                        return
                    if resp.status_code != 200:
                        body = await resp.aread()
                        detail = body.decode("utf-8", errors="replace")[:500]
                        _log.error(
                            "openrouter_http upstream %d: %s",
                            resp.status_code, detail,
                        )
                        yield StreamError(
                            error_code="provider_unavailable",
                            message=f"OpenRouter returned {resp.status_code}: {detail}",
                        )
                        return

                    stream_iter = resp.aiter_lines().__aiter__()
                    line_start = time.monotonic()
                    slow_fired = False

                    while True:
                        elapsed = time.monotonic() - line_start
                        budget = (
                            GUTTER_ABORT_SECONDS - elapsed if slow_fired
                            else GUTTER_SLOW_SECONDS - elapsed
                        )
                        if budget <= 0:
                            if not slow_fired:
                                _log.info(
                                    "openrouter_http.gutter_slow model=%s idle=%.1fs",
                                    payload.get("model"), elapsed,
                                )
                                yield StreamSlow()
                                slow_fired = True
                                continue
                            _log.warning(
                                "openrouter_http.gutter_abort model=%s idle=%.1fs",
                                payload.get("model"), elapsed,
                            )
                            if pending_next is not None:
                                pending_next.cancel()
                            yield StreamAborted(reason="gutter_timeout")
                            return
                        if pending_next is None:
                            pending_next = asyncio.ensure_future(
                                stream_iter.__anext__(),
                            )
                        done, _pending = await asyncio.wait(
                            {pending_next}, timeout=budget,
                        )
                        if not done:
                            continue
                        task = done.pop()
                        pending_next = None
                        try:
                            line = task.result()
                        except StopAsyncIteration:
                            break
                        line_start = time.monotonic()
                        slow_fired = False

                        parsed = _parse_sse_line(line)
                        if parsed is None:
                            continue
                        if parsed is _SSE_DONE:
                            break

                        for event in _chunk_to_events(parsed, acc):
                            if isinstance(event, StreamDone):
                                seen_done = True
                            yield event
                            if isinstance(event, (StreamDone,
                                                   StreamRefused,
                                                   StreamError)):
                                return

            except asyncio.CancelledError:
                if pending_next is not None and not pending_next.done():
                    pending_next.cancel()
                raise
            except httpx.ConnectError:
                yield StreamError(
                    error_code="provider_unavailable",
                    message="Cannot connect to OpenRouter",
                )
                return

        if not seen_done:
            yield StreamDone()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_openrouter_http.py::test_stream_completion_emits_content_then_done -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_openrouter_http.py \
        backend/tests/modules/llm/adapters/test_openrouter_http.py
git commit -m "Implement OpenRouter stream_completion happy path"
```

---

## Task 11: `stream_completion` error mapping

**Files:**
- Modify: `backend/tests/modules/llm/adapters/test_openrouter_http.py`

(No production code change — error mapping is already in place from
Task 10. This task locks the contract with explicit tests.)

- [ ] **Step 1: Write the failing tests**

Append:

```python
@pytest.mark.asyncio
async def test_stream_completion_401_yields_invalid_api_key():
    fake = _FakeStreamingClient([], status_code=401)
    a = OpenRouterHttpAdapter()
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
    )
    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        lambda *_a, **_k: fake,
    ):
        events = [e async for e in a.stream_completion(_resolved(), req)]
    errs = [e for e in events if isinstance(e, StreamError)]
    assert len(errs) == 1
    assert errs[0].error_code == "invalid_api_key"


@pytest.mark.asyncio
async def test_stream_completion_429_yields_provider_unavailable():
    fake = _FakeStreamingClient([], status_code=429)
    a = OpenRouterHttpAdapter()
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
    )
    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        lambda *_a, **_k: fake,
    ):
        events = [e async for e in a.stream_completion(_resolved(), req)]
    errs = [e for e in events if isinstance(e, StreamError)]
    assert len(errs) == 1
    assert errs[0].error_code == "provider_unavailable"
    assert "rate limit" in errs[0].message.lower()


@pytest.mark.asyncio
async def test_stream_completion_5xx_yields_provider_unavailable():
    fake = _FakeStreamingClient([], status_code=500)
    a = OpenRouterHttpAdapter()
    req = CompletionRequest(
        model="m",
        messages=[CompletionMessage(
            role="user", content=[ContentPart(type="text", text="x")],
        )],
    )
    with patch(
        "backend.modules.llm._adapters._openrouter_http.httpx.AsyncClient",
        lambda *_a, **_k: fake,
    ):
        events = [e async for e in a.stream_completion(_resolved(), req)]
    errs = [e for e in events if isinstance(e, StreamError)]
    assert len(errs) == 1
    assert errs[0].error_code == "provider_unavailable"
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_openrouter_http.py -k stream_completion -v`
Expected: all four `stream_completion_*` tests PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/modules/llm/adapters/test_openrouter_http.py
git commit -m "Add OpenRouter stream_completion error-path tests"
```

---

## Task 12: Adapter sub-router (`POST /test`)

**Files:**
- Modify: `backend/modules/llm/_adapters/_openrouter_http.py` (add
  `router` classmethod and `_build_adapter_router` helper)
- Modify: `backend/tests/modules/llm/adapters/test_openrouter_http.py`

Pattern source: `backend/modules/llm/_adapters/_xai_http.py:585–679`.

- [ ] **Step 1: Read the xAI sub-router for reference**

Inspect `backend/modules/llm/_adapters/_xai_http.py:585` onwards. The
key idea: `_build_adapter_router()` returns an `APIRouter` with a
`POST /test` route that depends on `resolve_connection_for_user`,
calls `fetch_models` with the resolved connection, and returns
`{"valid": bool, "error": str | None}`. It also writes
`update_test_status` on the connection repo.

For OpenRouter, the implementation is simpler: there is no Connection
document to update (premium-synthesised connection is in-memory). We
return only `{"valid": bool, "error": str | None}`.

- [ ] **Step 2: Write the failing test**

Append:

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.modules.llm._adapters._openrouter_http import OpenRouterHttpAdapter


def _make_app_with_test_route(monkeypatch):
    """Mount the adapter router under a stubbed dependency that
    returns a pre-baked ResolvedConnection — no real auth or DB."""
    app = FastAPI()
    router = OpenRouterHttpAdapter.router()
    assert router is not None

    from backend.modules.llm._resolver import resolve_connection_for_user

    async def fake_resolver():
        return _resolved()

    app.dependency_overrides[resolve_connection_for_user] = fake_resolver
    app.include_router(router, prefix="/api/llm/connections/{connection_id}/adapter")
    return app


@pytest.mark.asyncio
async def test_router_post_test_valid_when_models_returned(monkeypatch):
    app = _make_app_with_test_route(monkeypatch)

    async def fake_fetch(self, c):  # noqa: ARG001
        return [object()]  # any non-empty list

    monkeypatch.setattr(OpenRouterHttpAdapter, "fetch_models", fake_fetch)

    with TestClient(app) as client:
        r = client.post("/api/llm/connections/premium:openrouter/adapter/test")
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert body["error"] is None


@pytest.mark.asyncio
async def test_router_post_test_invalid_when_no_models(monkeypatch):
    app = _make_app_with_test_route(monkeypatch)

    async def fake_fetch(self, c):  # noqa: ARG001
        return []

    monkeypatch.setattr(OpenRouterHttpAdapter, "fetch_models", fake_fetch)

    with TestClient(app) as client:
        r = client.post("/api/llm/connections/premium:openrouter/adapter/test")
    body = r.json()
    assert body["valid"] is False
    assert body["error"]  # non-empty string
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_openrouter_http.py -k router_post_test -v`
Expected: FAIL — `OpenRouterHttpAdapter.router()` returns the base
class `None`.

- [ ] **Step 4: Implement the sub-router**

Add to `_openrouter_http.py`:

```python
from fastapi import APIRouter, Depends

from backend.modules.llm._resolver import resolve_connection_for_user


def _build_adapter_router() -> APIRouter:
    router = APIRouter()

    @router.post("/test")
    async def test_connection(
        c: ResolvedConnection = Depends(resolve_connection_for_user),
    ) -> dict:
        adapter = OpenRouterHttpAdapter()
        models = await adapter.fetch_models(c)
        if models:
            return {"valid": True, "error": None}
        return {
            "valid": False,
            "error": (
                "OpenRouter returned no models — check the API key, "
                "your OpenRouter privacy guardrails, or upstream availability."
            ),
        }

    return router
```

…and add the `router` classmethod to the adapter class:

```python
    @classmethod
    def router(cls) -> APIRouter:
        return _build_adapter_router()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_openrouter_http.py -k router_post_test -v`
Expected: two tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_adapters/_openrouter_http.py \
        backend/tests/modules/llm/adapters/test_openrouter_http.py
git commit -m "Add OpenRouter adapter /test sub-router"
```

---

## Task 13: Append INS-032 to `INSIGHTS.md`

**Files:**
- Modify: `INSIGHTS.md`

- [ ] **Step 1: Append the entry**

Open `INSIGHTS.md` and append at the end:

```markdown

## INS-032 — OpenRouter prompt caching is per-provider, not uniform (2026-04-28)

**Context:** OpenRouter routes to 50+ upstream providers, each with a
different caching story:

- **OpenAI / Gemini / DeepSeek models** — automatic prefix caching
  above ~1024 tokens. No marker needed, transparent savings. (List
  grows empirically; validated via the OpenRouter dashboard.)
- **Anthropic models** — require explicit
  `cache_control: {type: "ephemeral"}` markers on individual
  message-content blocks (typically system prompt and long tool
  definitions). Without markers, every turn pays full token price.
- **Others (Llama, Mistral on OR, etc.)** — usually no caching.

**Phase-1 decision:** Pass-through with no `cache_control` markers.
OpenAI / Gemini / DeepSeek auto-caching covers the bulk of realistic
Chatsune traffic out of the box; Anthropic models run uncached.

**What testers must know:** users who route mostly to Claude through
OpenRouter will see no cache savings until we ship marker support.
Iterate on real usage data before optimising.

**Why not implement markers now:** `cache_control` belongs at the
content-block level inside chat messages, not on the message itself.
Adding it would require either an OR-specific message translator
(more code, more divergence from Mistral / xAI / nano-gpt) or a
parameter on the shared `CompletionMessage` model that every other
adapter would ignore. Neither is justified before we have usage data.
```

- [ ] **Step 2: Commit**

```bash
git add INSIGHTS.md
git commit -m "INS-032: OpenRouter prompt caching is per-provider"
```

---

## Task 14: Final smoke check

- [ ] **Step 1: Compile-check the new adapter**

Run: `uv run python -m py_compile backend/modules/llm/_adapters/_openrouter_http.py`
Expected: no output, exit 0.

- [ ] **Step 2: Run the full OpenRouter test suite**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_openrouter_http.py -v`
Expected: all tests PASS.

- [ ] **Step 3: Run the schema and registration test files**

Run:
```bash
uv run pytest \
  backend/tests/modules/shared/test_model_meta_is_moderated.py \
  backend/tests/modules/providers/test_openrouter_registration.py \
  backend/tests/modules/llm/test_resolver_openrouter.py -v
```
Expected: all tests PASS.

- [ ] **Step 4: Sanity-run the broader LLM adapter suite for regressions**

Run: `uv run pytest backend/tests/modules/llm/adapters/ -v`
Expected: all tests PASS (no regression in xAI / Mistral / Nano-GPT
suites caused by shared imports / changes to `ModelMetaDto`).

- [ ] **Step 5: Hand back to user**

The implementation is complete. **Do not merge, do not push, do not
switch branches.** Report task completion to the user with a summary
of files changed and the commit count. The user will run the manual
verification steps from spec section 9 against a live Chatsune
instance with a real OpenRouter API key, then merge.

---

## Self-Review Notes

- **Spec coverage:** every numbered section of
  `2026-04-28-openrouter-integration-design.md` maps to a task:
  - §3 architecture overview → tasks 1, 2, 3, 4 (file structure + wiring)
  - §4 registry entry → task 2
  - §5.1 class identity → task 4
  - §5.2 fetch_models mapping → tasks 5, 6, 7
  - §5.3 stream_completion body → tasks 9, 10
  - §5.4 reasoning handling → task 9
  - §5.5 SSE parser → task 8
  - §5.6 error mapping → tasks 10, 11
  - §5.7 sub-router → task 12
  - §6 schema change + migration → task 1
  - §7 INSIGHTS-032 → task 13
  - §8 tests → tasks 1–12 (TDD throughout)
  - §9 manual verification → handed off in task 14, executed by user.

- **Type consistency:** every reference to `ModelMetaDto.is_moderated`,
  `_translate_message`, `_build_chat_payload`, `_chunk_to_events`,
  `_parse_sse_line`, `_ToolCallAccumulator`, `_SSE_DONE`,
  `OpenRouterHttpAdapter` matches across tasks. Function signatures
  agree with the BaseAdapter contract.

- **No placeholders:** every code step is concrete; every test step
  shows full test bodies; every commit step shows the exact `git`
  command.

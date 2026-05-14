# Tensorix Premium Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Tensorix as a curated Premium LLM Provider with seven hand-picked models, per-model binary or stepped reasoning controls, and explicit sort priority placing it directly under Ollama Cloud in the wizard.

**Architecture:** Tensorix is OpenAI-compatible (litellm-backed). The integration slots into the existing two-layer Premium-Provider + Premium-only adapter pattern, parallel to Mistral. No new frontend components are needed — the existing `ThinkingButton` already renders both binary and stepped reasoning based on `ReasoningCapability.effort`.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic v2 / httpx (backend); Vite / React / TSX (frontend). pytest + xUnit-style test functions. No new dependencies.

**Spec reference:** `devdocs/specs/2026-05-15-tensorix-provider-design.md`

**Important Architecture Insight (discovered during planning):**
The spec described a custom `reasoning_mode` DTO field. **This is not needed.** The existing `ReasoningCapability.effort: ReasoningEffortSpec | None` already encodes binary (`effort=None`) vs. stepped (`effort=ReasoningEffortSpec(buckets=...)`), and the existing `ThinkingButton.tsx` renders both shapes correctly. This plan uses the existing machinery — no frontend changes, no new DTO fields.

---

## File Map

**Create:**
- `backend/modules/llm/_adapters/_tensorix_http.py` — adapter (~600 LOC, Mistral-shaped).
- `backend/tests/modules/llm/adapters/test_tensorix_http.py` — adapter unit tests.
- `tests/llm_scenarios/tensorix_deepseek_v4_flash_simple.json`
- `tests/llm_scenarios/tensorix_deepseek_v4_pro_stepped_reasoning.json`
- `tests/llm_scenarios/tensorix_kimi_k2_6_tools.json`

**Modify:**
- `backend/modules/providers/_models.py` — add `sort_priority` field.
- `backend/modules/providers/_registry.py` — register Tensorix; assign sort_priority to existing providers.
- `backend/modules/providers/__init__.py` (`PremiumProviderService.catalogue`) — sort by `sort_priority`, emit field.
- `shared/dtos/providers.py` (`PremiumProviderDefinitionDto`) — add `sort_priority` field.
- `backend/modules/llm/_registry.py` — add `tensorix_http` to `_PREMIUM_ONLY_ADAPTERS`.
- `backend/modules/llm/_resolver.py` — extend `_PREMIUM_ADAPTER_TYPE` with `"tensorix": "tensorix_http"`.

**Do not touch:**
- Frontend `ThinkingButton.tsx` / `ReasoningToolsCluster.tsx` — already handle both reasoning shapes via `effort` field.
- `_handlers.py::_mount_adapter_routers` — it iterates only `ADAPTER_REGISTRY` (user-createable), not `_PREMIUM_ONLY_ADAPTERS`. Tensorix follows Mistral and ships a `/test` sub-router for parity; if the premium mount path is added later, Tensorix's router is already there. (Mistral's commit `c505e99d` set this precedent.)

---

## Task 1: Add `sort_priority` to `PremiumProviderDefinition`

**Files:**
- Modify: `backend/modules/providers/_models.py`

- [ ] **Step 1: Add the field with a sensible default**

Edit `backend/modules/providers/_models.py` so the dataclass becomes:

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
    # Lower value = earlier in the catalogue list. Ties break by
    # registration order (Python dicts preserve insertion order, and
    # ``sorted`` is stable). Default 100 keeps unspecified providers
    # at the tail of the list.
    sort_priority: int = 100
```

- [ ] **Step 2: Verify backend still compiles**

Run: `uv run python -m py_compile backend/modules/providers/_models.py`
Expected: exit code 0, no output.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/providers/_models.py
git commit -m "Add sort_priority field to PremiumProviderDefinition"
```

---

## Task 2: Add `sort_priority` to `PremiumProviderDefinitionDto`

**Files:**
- Modify: `shared/dtos/providers.py`

- [ ] **Step 1: Add the field to the DTO**

Edit `shared/dtos/providers.py`, changing the DTO to:

```python
class PremiumProviderDefinitionDto(BaseModel):
    """Static catalogue entry — sent to frontend at /api/providers/catalogue."""
    id: str
    display_name: str
    icon: str
    base_url: str
    capabilities: list[Capability]
    config_fields: list[dict[str, Any]]
    linked_integrations: list[str] = Field(default_factory=list)
    # See PremiumProviderDefinition.sort_priority. Default 100 keeps
    # pre-existing cached payloads readable per CLAUDE.md §Data-Model
    # Migrations.
    sort_priority: int = 100
```

- [ ] **Step 2: Verify compile**

Run: `uv run python -m py_compile shared/dtos/providers.py`
Expected: exit code 0.

- [ ] **Step 3: Commit**

```bash
git add shared/dtos/providers.py
git commit -m "Add sort_priority field to PremiumProviderDefinitionDto"
```

---

## Task 3: Sort providers in `catalogue()` and bubble `sort_priority`

**Files:**
- Modify: `backend/modules/providers/__init__.py`
- Test: extend `backend/modules/providers/__init__.py` callers indirectly by adding a focused unit test.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/modules/providers/test_catalogue_ordering.py` (the providers test folder may not exist yet — `mkdir -p backend/tests/modules/providers && touch backend/tests/modules/providers/__init__.py` first):

```python
"""Tests for premium-provider catalogue ordering by sort_priority."""
from __future__ import annotations

import pytest

from backend.modules.providers import PremiumProviderService


class _StubRepo:
    """Repository stub — catalogue() never reads from it."""
    async def list_for_user(self, user_id: str):  # pragma: no cover
        return []


@pytest.mark.asyncio
async def test_catalogue_is_sorted_by_sort_priority():
    svc = PremiumProviderService(_StubRepo())  # type: ignore[arg-type]
    out = await svc.catalogue()
    priorities = [item["sort_priority"] for item in out]
    assert priorities == sorted(priorities), (
        f"catalogue not sorted by sort_priority: {priorities}"
    )


@pytest.mark.asyncio
async def test_catalogue_emits_sort_priority_field():
    svc = PremiumProviderService(_StubRepo())  # type: ignore[arg-type]
    out = await svc.catalogue()
    assert all("sort_priority" in item for item in out)
    assert all(isinstance(item["sort_priority"], int) for item in out)
```

- [ ] **Step 2: Run it — confirm it fails**

Run: `uv run pytest backend/tests/modules/providers/test_catalogue_ordering.py -v`
Expected: FAIL — `sort_priority` is not in the DTO output yet (Task 2 added the field with default, but Task 3 hasn't wired the field through `catalogue()`).

- [ ] **Step 3: Update `catalogue()` to read + sort + emit `sort_priority`**

Edit `backend/modules/providers/__init__.py`, replacing the `catalogue` method body:

```python
    async def catalogue(self) -> list[dict]:
        defs = sorted(
            get_all_definitions().values(),
            key=lambda d: d.sort_priority,
        )
        return [
            PremiumProviderDefinitionDto(
                id=d.id,
                display_name=d.display_name,
                icon=d.icon,
                base_url=d.base_url,
                capabilities=list(d.capabilities),
                config_fields=list(d.config_fields),
                linked_integrations=list(d.linked_integrations),
                sort_priority=d.sort_priority,
            ).model_dump()
            for d in defs
        ]
```

- [ ] **Step 4: Run the test — should pass**

Run: `uv run pytest backend/tests/modules/providers/test_catalogue_ordering.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/providers/__init__.py backend/tests/modules/providers/
git commit -m "Sort premium-provider catalogue by sort_priority"
```

---

## Task 4: Assign explicit `sort_priority` to featured providers; register Tensorix

**Files:**
- Modify: `backend/modules/providers/_registry.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/modules/providers/test_catalogue_ordering.py`:

```python
@pytest.mark.asyncio
async def test_featured_providers_appear_in_expected_order():
    """Ollama Cloud → Tensorix → xAI → Mistral; the rest follow."""
    svc = PremiumProviderService(_StubRepo())  # type: ignore[arg-type]
    out = await svc.catalogue()
    ids = [item["id"] for item in out]
    # Featured tier is fully ordered.
    assert ids.index("ollama_cloud") < ids.index("tensorix")
    assert ids.index("tensorix") < ids.index("xai")
    assert ids.index("xai") < ids.index("mistral")
    # Long tail comes after Mistral.
    for tail_id in ("nano_gpt", "openrouter", "novita"):
        assert ids.index("mistral") < ids.index(tail_id), (
            f"{tail_id} should come after mistral; ids={ids}"
        )


@pytest.mark.asyncio
async def test_tensorix_is_registered_with_correct_metadata():
    svc = PremiumProviderService(_StubRepo())  # type: ignore[arg-type]
    out = await svc.catalogue()
    tensorix = next(p for p in out if p["id"] == "tensorix")
    assert tensorix["display_name"] == "Tensorix"
    assert tensorix["base_url"] == "https://api.tensorix.ai/v1"
    assert tensorix["icon"] == "tensorix"
    # LLM only.
    assert tensorix["capabilities"] == ["llm"]
```

- [ ] **Step 2: Run — confirm FAIL**

Run: `uv run pytest backend/tests/modules/providers/test_catalogue_ordering.py -v`
Expected: the two new tests FAIL (Tensorix not registered; existing providers default to sort_priority=100 so ordering is undefined).

- [ ] **Step 3: Update the registry — assign priorities and register Tensorix**

Replace the body of `_register_builtins()` in `backend/modules/providers/_registry.py` with:

```python
def _register_builtins() -> None:
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
        sort_priority=10,
    ))

    register(PremiumProviderDefinition(
        id="tensorix",
        display_name="Tensorix",
        icon="tensorix",
        base_url="https://api.tensorix.ai/v1",
        capabilities=[Capability.LLM],
        config_fields=[_api_key_field("Tensorix API Key")],
        # /v1/model/info requires a valid Bearer key and 401s on bad
        # keys, so it's the right probe target.
        probe_url="https://api.tensorix.ai/v1/model/info",
        probe_method="GET",
        linked_integrations=[],
        sort_priority=20,
    ))

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
        sort_priority=30,
    ))

    register(PremiumProviderDefinition(
        id="mistral",
        display_name="Mistral",
        icon="mistral",
        base_url="https://api.mistral.ai/v1",
        capabilities=[Capability.LLM, Capability.TTS, Capability.STT],
        config_fields=[_api_key_field("Mistral API Key")],
        probe_url="https://api.mistral.ai/v1/models",
        probe_method="GET",
        linked_integrations=["mistral_voice"],
        sort_priority=40,
    ))

    register(PremiumProviderDefinition(
        id="nano_gpt",
        display_name="Nano-GPT",
        icon="nano_gpt",
        base_url="https://nano-gpt.com/api/v1",
        capabilities=[Capability.LLM],
        config_fields=[_api_key_field("Nano-GPT API Key")],
        # Nano-GPT's ``/v1/models`` endpoint is unauthenticated — it returns
        # the full system catalogue regardless of key. Only the personalised
        # endpoint rejects an invalid key, so we probe against that.
        probe_url="https://nano-gpt.com/api/personalized/v1/models",
        probe_method="GET",
        linked_integrations=[],
    ))

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

    register(PremiumProviderDefinition(
        id="novita",
        display_name="Novita AI",
        icon="novita",
        base_url="https://api.novita.ai/openai/v1",
        capabilities=[Capability.LLM],
        config_fields=[_api_key_field("Novita AI API Key")],
        # /openai/v1/models is unauthenticated, so it cannot validate the
        # key. /openapi/v1/billing/balance/detail requires auth and 401s
        # on a bad key — see spec §"Endpoints".
        probe_url="https://api.novita.ai/openapi/v1/billing/balance/detail",
        probe_method="GET",
        linked_integrations=[],
    ))
```

- [ ] **Step 4: Run — confirm PASS**

Run: `uv run pytest backend/tests/modules/providers/test_catalogue_ordering.py -v`
Expected: all four tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/providers/_registry.py backend/tests/modules/providers/test_catalogue_ordering.py
git commit -m "Register Tensorix premium provider and order featured tier"
```

---

## Task 5: Create Tensorix adapter skeleton — curated model table

**Files:**
- Create: `backend/modules/llm/_adapters/_tensorix_http.py`
- Create: `backend/tests/modules/llm/adapters/test_tensorix_http.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/modules/llm/adapters/test_tensorix_http.py`:

```python
"""Tests for the Tensorix HTTP adapter."""
from __future__ import annotations

import pytest

from backend.modules.llm._adapters._tensorix_http import (
    _TENSORIX_MODELS,
    _TENSORIX_MODELS_BY_ID,
    _TensorixModelEntry,
)


def test_tensorix_models_table_has_exactly_seven_entries():
    assert len(_TENSORIX_MODELS) == 7
    ids = {m.model_id for m in _TENSORIX_MODELS}
    assert ids == {
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "kimi-k2-6",
        "glm-5-1",
        "glm-5",
        "deepseek-v3-2",
        "glm-4-6",
    }


def test_tensorix_models_upstream_slugs_match_api_reality():
    by_id = {m.model_id: m.upstream_slug for m in _TENSORIX_MODELS}
    assert by_id["deepseek-v4-flash"] == "deepseek/deepseek-v4-flash"
    assert by_id["deepseek-v4-pro"] == "deepseek/deepseek-v4-pro"
    assert by_id["kimi-k2-6"] == "moonshotai/Kimi-K2.6"
    assert by_id["glm-5-1"] == "z-ai/glm-5.1"
    assert by_id["glm-5"] == "z-ai/glm-5"
    assert by_id["deepseek-v3-2"] == "deepseek/deepseek-v3.2"
    assert by_id["glm-4-6"] == "z-ai/glm-4.6"


def test_tensorix_models_all_first_class():
    assert all(m.first_class_support for m in _TENSORIX_MODELS)


def test_tensorix_models_reasoning_mode_assignments():
    by_id = {m.model_id: m.reasoning_mode for m in _TENSORIX_MODELS}
    assert by_id["deepseek-v4-flash"] == "binary"
    assert by_id["deepseek-v4-pro"] == "stepped"
    assert by_id["kimi-k2-6"] == "binary"
    assert by_id["glm-5-1"] == "stepped"
    assert by_id["glm-5"] == "stepped"
    assert by_id["deepseek-v3-2"] == "binary"
    assert by_id["glm-4-6"] == "binary"


def test_tensorix_models_vision_only_for_kimi():
    by_id = {m.model_id: m.supports_vision for m in _TENSORIX_MODELS}
    assert by_id["kimi-k2-6"] is True
    for k, v in by_id.items():
        if k != "kimi-k2-6":
            assert v is False, f"{k} should not advertise vision"


def test_tensorix_models_all_support_tools():
    assert all(m.supports_tool_calls for m in _TENSORIX_MODELS)


def test_tensorix_models_by_id_lookup_consistent():
    for m in _TENSORIX_MODELS:
        assert _TENSORIX_MODELS_BY_ID[m.model_id] is m
```

- [ ] **Step 2: Run — confirm FAIL**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_tensorix_http.py -v`
Expected: collection error / ImportError — module does not exist yet.

- [ ] **Step 3: Create the adapter skeleton with the curated tuple**

Create `backend/modules/llm/_adapters/_tensorix_http.py`:

```python
"""Tensorix HTTP adapter — OpenAI-compatible Chat Completions.

Hosts a curated seven-model list (DeepSeek V4 Flash/Pro/V3.2, Kimi K2.6,
GLM 4.6/5/5.1) against the Tensorix Cloud API. Tensorix is OpenAI-
compatible (litellm-backed) and offers GDPR/ZDR/EU-compute guarantees.

Reasoning is per-model:
- ``binary`` models accept a simple on/off toggle. ON sends
  ``reasoning_effort="high"``; OFF omits the field.
- ``stepped`` models accept ``reasoning_effort`` in {"low","medium","high"}
  with an explicit "off" that omits the field.

See devdocs/specs/2026-05-15-tensorix-provider-design.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends

from backend._retry import (
    MAX_RETRY_ATTEMPTS,
    compute_retry_delay,
    log_retry,
    parse_retry_after,
    should_retry_status,
)
from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._events import (
    ContentDelta,
    ProviderStreamEvent,
    StreamAborted,
    StreamDone,
    StreamError,
    StreamRefused,
    StreamSlow,
    ThinkingDelta,
    ToolCallEvent,
)
from backend.modules.llm._adapters._types import ResolvedConnection
from shared.dtos.inference import CompletionMessage, CompletionRequest
from shared.dtos.llm import (
    ModelMetaDto,
    ReasoningCapability,
    ReasoningEffortSpec,
    ToolCapability,
)

_log = logging.getLogger(__name__)

_TRACE_PAYLOADS = os.environ.get("LLM_TRACE_PAYLOADS") == "1"

GUTTER_SLOW_SECONDS: float = 30.0
GUTTER_ABORT_SECONDS: float = float(
    os.environ.get("LLM_STREAM_ABORT_SECONDS", "120"),
)

_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=15.0)
_PROBE_TIMEOUT = httpx.Timeout(10.0)
_REFUSAL_REASONS: frozenset[str] = frozenset({"content_filter", "refusal"})

_SSE_DONE = object()  # sentinel — distinct from any JSON-decodable value


@dataclass(frozen=True)
class _TensorixModelEntry:
    model_id: str            # user-facing internal ID, e.g. "deepseek-v4-flash"
    upstream_slug: str       # what we send to Tensorix, e.g. "deepseek/deepseek-v4-flash"
    display_name: str
    context_window: int
    max_output_tokens: int
    supports_tool_calls: bool
    supports_vision: bool
    # ``binary`` -> on/off toggle (sends ``reasoning_effort="high"`` when on).
    # ``stepped`` -> low/medium/high selector with explicit off.
    # ``None`` -> the model has no reasoning surface.
    reasoning_mode: Literal["binary", "stepped"] | None
    first_class_support: bool


_TENSORIX_MODELS: tuple[_TensorixModelEntry, ...] = (
    _TensorixModelEntry(
        model_id="deepseek-v4-flash",
        upstream_slug="deepseek/deepseek-v4-flash",
        display_name="DeepSeek V4 Flash",
        context_window=1_048_576,
        max_output_tokens=384_000,
        supports_tool_calls=True,
        supports_vision=False,
        reasoning_mode="binary",
        first_class_support=True,
    ),
    _TensorixModelEntry(
        model_id="deepseek-v4-pro",
        upstream_slug="deepseek/deepseek-v4-pro",
        display_name="DeepSeek V4 Pro",
        context_window=1_048_576,
        max_output_tokens=384_000,
        supports_tool_calls=True,
        supports_vision=False,
        reasoning_mode="stepped",
        first_class_support=True,
    ),
    _TensorixModelEntry(
        model_id="kimi-k2-6",
        upstream_slug="moonshotai/Kimi-K2.6",
        display_name="Kimi K2.6",
        context_window=262_144,
        max_output_tokens=262_144,
        supports_tool_calls=True,
        supports_vision=True,
        reasoning_mode="binary",
        first_class_support=True,
    ),
    _TensorixModelEntry(
        model_id="glm-5-1",
        upstream_slug="z-ai/glm-5.1",
        display_name="GLM 5.1",
        context_window=202_752,
        max_output_tokens=202_752,
        supports_tool_calls=True,
        supports_vision=False,
        reasoning_mode="stepped",
        first_class_support=True,
    ),
    _TensorixModelEntry(
        model_id="glm-5",
        upstream_slug="z-ai/glm-5",
        display_name="GLM 5",
        context_window=202_752,
        max_output_tokens=202_752,
        supports_tool_calls=True,
        supports_vision=False,
        reasoning_mode="stepped",
        first_class_support=True,
    ),
    _TensorixModelEntry(
        model_id="deepseek-v3-2",
        upstream_slug="deepseek/deepseek-v3.2",
        display_name="DeepSeek V3.2",
        context_window=163_840,
        max_output_tokens=163_840,
        supports_tool_calls=True,
        supports_vision=False,
        reasoning_mode="binary",
        first_class_support=True,
    ),
    _TensorixModelEntry(
        model_id="glm-4-6",
        upstream_slug="z-ai/glm-4.6",
        display_name="GLM 4.6",
        context_window=203_000,
        max_output_tokens=131_000,
        supports_tool_calls=True,
        supports_vision=False,
        reasoning_mode="binary",
        first_class_support=True,
    ),
)

_TENSORIX_MODELS_BY_ID: dict[str, _TensorixModelEntry] = {
    m.model_id: m for m in _TENSORIX_MODELS
}
```

- [ ] **Step 4: Run — confirm PASS**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_tensorix_http.py -v`
Expected: all seven tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_tensorix_http.py backend/tests/modules/llm/adapters/test_tensorix_http.py
git commit -m "Add Tensorix adapter skeleton with curated seven-model table"
```

---

## Task 6: Capability hint — binary vs. stepped via `ReasoningEffortSpec`

**Files:**
- Modify: `backend/modules/llm/_adapters/_tensorix_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_tensorix_http.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/modules/llm/adapters/test_tensorix_http.py`:

```python
from backend.modules.llm._adapters._tensorix_http import TensorixHttpAdapter
from backend.modules.llm._capabilities import CapabilityHint


def test_capability_hint_binary_model_has_no_effort_buckets():
    hint = TensorixHttpAdapter().capability_hint("deepseek-v4-flash")
    assert hint is not None
    assert hint.reasoning.kind == "optional"
    assert hint.reasoning.effort is None  # binary -> no bucket selector
    assert hint.reasoning.default_on is False
    assert hint.tools.supported is True
    assert hint.first_class_support is True


def test_capability_hint_stepped_model_has_three_effort_buckets():
    hint = TensorixHttpAdapter().capability_hint("deepseek-v4-pro")
    assert hint is not None
    assert hint.reasoning.kind == "optional"
    assert hint.reasoning.effort is not None
    assert hint.reasoning.effort.buckets == ["low", "medium", "high"]
    assert hint.reasoning.effort.default_bucket == "medium"
    assert hint.reasoning.default_on is False


def test_capability_hint_unknown_model_returns_none():
    assert TensorixHttpAdapter().capability_hint("not-a-tensorix-model") is None


def test_capability_hint_kimi_advertises_vision_via_meta_not_hint():
    # The vision flag rides on ModelMetaDto.supports_vision, not on
    # CapabilityHint — confirm capability_hint still returns the
    # expected reasoning/tools shape for Kimi.
    hint = TensorixHttpAdapter().capability_hint("kimi-k2-6")
    assert hint is not None
    assert hint.reasoning.kind == "optional"
    assert hint.reasoning.effort is None  # Kimi is binary
```

- [ ] **Step 2: Run — confirm FAIL**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_tensorix_http.py::test_capability_hint_binary_model_has_no_effort_buckets -v`
Expected: ImportError — `TensorixHttpAdapter` not defined.

- [ ] **Step 3: Add the adapter class with `capability_hint`**

Append to `backend/modules/llm/_adapters/_tensorix_http.py`:

```python
class TensorixHttpAdapter(BaseAdapter):
    adapter_type = "tensorix_http"
    display_name = "Tensorix"
    view_id = "tensorix_http"
    secret_fields = frozenset({"api_key"})

    @classmethod
    def router(cls) -> APIRouter:
        return _build_adapter_router()

    def capability_hint(self, model_id: str):
        from backend.modules.llm._capabilities import CapabilityHint

        entry = _TENSORIX_MODELS_BY_ID.get(model_id)
        if entry is None:
            return None

        if entry.reasoning_mode is None:
            reasoning = ReasoningCapability(
                kind="no_reasoning", default_on=False,
            )
        elif entry.reasoning_mode == "binary":
            reasoning = ReasoningCapability(
                kind="optional",
                effort=None,
                default_on=False,
            )
        else:  # "stepped"
            reasoning = ReasoningCapability(
                kind="optional",
                effort=ReasoningEffortSpec(
                    buckets=["low", "medium", "high"],
                    default_bucket="medium",
                ),
                default_on=False,
            )

        return CapabilityHint(
            reasoning=reasoning,
            tools=ToolCapability(
                supported=entry.supports_tool_calls,
                exclusive_with_reasoning=False,
            ),
            first_class_support=entry.first_class_support,
        )
```

Also add a placeholder `_build_adapter_router` so import doesn't break (the real implementation lands in Task 11):

```python
def _build_adapter_router() -> APIRouter:
    """Placeholder; real implementation in Task 11."""
    return APIRouter()
```

- [ ] **Step 4: Run — confirm PASS**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_tensorix_http.py -v`
Expected: all tests PASS (eleven so far).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_tensorix_http.py backend/tests/modules/llm/adapters/test_tensorix_http.py
git commit -m "Add Tensorix capability_hint with binary/stepped reasoning"
```

---

## Task 7: `fetch_models` — surface the curated list as `ModelMetaDto`s

**Files:**
- Modify: `backend/modules/llm/_adapters/_tensorix_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_tensorix_http.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/modules/llm/adapters/test_tensorix_http.py`:

```python
from datetime import UTC, datetime

from backend.modules.llm._adapters._types import ResolvedConnection


def _make_resolved_connection() -> ResolvedConnection:
    now = datetime.now(UTC)
    return ResolvedConnection(
        id="premium:tensorix",
        user_id="user-1",
        adapter_type="tensorix_http",
        display_name="Tensorix",
        slug="tensorix",
        config={
            "url": "https://api.tensorix.ai/v1",
            "api_key": "sk-test",
        },
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_fetch_models_returns_seven_curated_entries():
    metas = await TensorixHttpAdapter().fetch_models(_make_resolved_connection())
    assert len(metas) == 7
    ids = {m.model_id for m in metas}
    assert "deepseek-v4-flash" in ids
    assert "glm-4-6" in ids


@pytest.mark.asyncio
async def test_fetch_models_propagates_connection_metadata():
    metas = await TensorixHttpAdapter().fetch_models(_make_resolved_connection())
    for m in metas:
        assert m.connection_id == "premium:tensorix"
        assert m.connection_slug == "tensorix"
        assert m.connection_display_name == "Tensorix"


@pytest.mark.asyncio
async def test_fetch_models_carries_first_class_and_billing():
    metas = await TensorixHttpAdapter().fetch_models(_make_resolved_connection())
    for m in metas:
        assert m.first_class_support is True
        assert m.billing_category == "pay_per_token"
        assert m.is_deprecated is False
```

- [ ] **Step 2: Run — confirm FAIL**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_tensorix_http.py::test_fetch_models_returns_seven_curated_entries -v`
Expected: FAIL — `fetch_models` not defined.

- [ ] **Step 3: Implement `fetch_models`**

Add to `TensorixHttpAdapter` class in `_tensorix_http.py`:

```python
    async def fetch_models(
        self, c: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        from backend.modules.llm._capabilities import resolve_capabilities

        metas: list[ModelMetaDto] = []
        for entry in _TENSORIX_MODELS:
            resolved = resolve_capabilities(
                adapter_type=self.adapter_type,
                model_id=entry.model_id,
                adapter=self,
            )
            metas.append(ModelMetaDto(
                connection_id=c.id,
                connection_display_name=c.display_name,
                connection_slug=c.slug,
                model_id=entry.model_id,
                display_name=entry.display_name,
                context_window=entry.context_window,
                reasoning=resolved.reasoning,
                tools=resolved.tools,
                first_class_support=resolved.first_class_support,
                supports_vision=entry.supports_vision,
                supports_tool_calls=entry.supports_tool_calls,
                is_deprecated=False,
                billing_category="pay_per_token",
            ))
        return metas
```

- [ ] **Step 4: Run — confirm PASS**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_tensorix_http.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_tensorix_http.py backend/tests/modules/llm/adapters/test_tensorix_http.py
git commit -m "Add Tensorix fetch_models returning seven curated entries"
```

---

## Task 8: `_build_chat_payload` with per-model reasoning injection

**Files:**
- Modify: `backend/modules/llm/_adapters/_tensorix_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_tensorix_http.py`

**Background:** `CompletionRequest.extras` is a `ChatSessionExtras` Pydantic model carrying `reasoning_mode: Literal["on","off"]` and `reasoning_effort: str | None`. We use both:
- For binary models: `reasoning_mode == "on"` → `reasoning_effort: "high"`.
- For stepped models: `reasoning_mode == "on"` AND `reasoning_effort in {"low","medium","high"}` → that effort; otherwise omit.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/modules/llm/adapters/test_tensorix_http.py`:

```python
from backend.modules.llm._adapters._tensorix_http import _build_chat_payload
from shared.dtos.chat import ChatSessionExtras
from shared.dtos.inference import (
    CompletionMessage,
    CompletionRequest,
    ContentPart,
)


def _make_request(
    *,
    model_id: str,
    reasoning_mode: str = "off",
    reasoning_effort: str | None = None,
) -> CompletionRequest:
    return CompletionRequest(
        model=model_id,
        messages=[
            CompletionMessage(
                role="user",
                content=[ContentPart(type="text", text="hello")],
            ),
        ],
        temperature=0.7,
        tools=[],
        extras=ChatSessionExtras(
            reasoning_mode=reasoning_mode,  # type: ignore[arg-type]
            reasoning_effort=reasoning_effort,
        ),
    )


def test_payload_maps_model_id_to_upstream_slug():
    payload = _build_chat_payload(_make_request(model_id="deepseek-v4-flash"))
    assert payload["model"] == "deepseek/deepseek-v4-flash"


def test_payload_sets_stream_and_include_usage():
    payload = _build_chat_payload(_make_request(model_id="kimi-k2-6"))
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}


def test_payload_binary_reasoning_off_omits_effort():
    payload = _build_chat_payload(
        _make_request(model_id="deepseek-v4-flash", reasoning_mode="off"),
    )
    assert "reasoning_effort" not in payload


def test_payload_binary_reasoning_on_sets_effort_high():
    payload = _build_chat_payload(
        _make_request(model_id="deepseek-v4-flash", reasoning_mode="on"),
    )
    assert payload["reasoning_effort"] == "high"


def test_payload_stepped_reasoning_off_omits_effort():
    payload = _build_chat_payload(
        _make_request(model_id="deepseek-v4-pro", reasoning_mode="off"),
    )
    assert "reasoning_effort" not in payload


def test_payload_stepped_reasoning_passes_through_low():
    payload = _build_chat_payload(_make_request(
        model_id="deepseek-v4-pro",
        reasoning_mode="on",
        reasoning_effort="low",
    ))
    assert payload["reasoning_effort"] == "low"


def test_payload_stepped_reasoning_passes_through_medium():
    payload = _build_chat_payload(_make_request(
        model_id="deepseek-v4-pro",
        reasoning_mode="on",
        reasoning_effort="medium",
    ))
    assert payload["reasoning_effort"] == "medium"


def test_payload_stepped_reasoning_passes_through_high():
    payload = _build_chat_payload(_make_request(
        model_id="deepseek-v4-pro",
        reasoning_mode="on",
        reasoning_effort="high",
    ))
    assert payload["reasoning_effort"] == "high"


def test_payload_stepped_with_no_effort_falls_back_to_default_bucket():
    # ``reasoning_mode=on`` with no explicit bucket -> use the model's
    # default_bucket ("medium").
    payload = _build_chat_payload(_make_request(
        model_id="deepseek-v4-pro",
        reasoning_mode="on",
        reasoning_effort=None,
    ))
    assert payload["reasoning_effort"] == "medium"


def test_payload_unknown_model_falls_back_to_deepseek_v3_2():
    payload = _build_chat_payload(_make_request(model_id="not-a-real-model"))
    assert payload["model"] == "deepseek/deepseek-v3.2"
```

- [ ] **Step 2: Run — confirm FAIL**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_tensorix_http.py -k "payload" -v`
Expected: all ten new tests FAIL on ImportError of `_build_chat_payload`.

- [ ] **Step 3: Implement payload builder and helpers**

Add these functions to `_tensorix_http.py` (above the adapter class):

```python
_STEPPED_BUCKETS: frozenset[str] = frozenset({"low", "medium", "high"})
_STEPPED_DEFAULT: str = "medium"


def _translate_message(msg: CompletionMessage) -> dict:
    """Translate our CompletionMessage into an OpenAI-compatible chat message."""
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


def _select_reasoning_effort(
    entry: _TensorixModelEntry, request: CompletionRequest,
) -> str | None:
    """Return the ``reasoning_effort`` value for this request, or ``None``.

    Rules (see spec §5.3):
      - ``reasoning_mode != "on"`` -> always None (field omitted).
      - ``binary`` model + on -> "high".
      - ``stepped`` model + on + valid bucket -> that bucket.
      - ``stepped`` model + on + missing/invalid bucket -> "medium" default.
      - Model with ``reasoning_mode is None`` -> None.
    """
    if request.extras.reasoning_mode != "on":
        return None
    if entry.reasoning_mode is None:
        return None
    if entry.reasoning_mode == "binary":
        return "high"
    # stepped
    bucket = request.extras.reasoning_effort
    if bucket in _STEPPED_BUCKETS:
        return bucket
    return _STEPPED_DEFAULT


def _build_chat_payload(request: CompletionRequest) -> dict:
    """Build a Tensorix chat/completions payload.

    Maps the user-facing ``model_id`` (e.g. "deepseek-v4-flash") to
    Tensorix's upstream slug (e.g. "deepseek/deepseek-v4-flash"), applies
    per-model reasoning rules, and falls back to ``deepseek-v3-2`` when a
    stale persona references a model we no longer expose.
    """
    entry = _TENSORIX_MODELS_BY_ID.get(request.model)
    if entry is None:
        _log.warning(
            "Tensorix: unknown model_id=%r in CompletionRequest; "
            "falling back to deepseek-v3-2",
            request.model,
        )
        entry = _TENSORIX_MODELS_BY_ID["deepseek-v3-2"]

    payload: dict = {
        "model": entry.upstream_slug,
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [_translate_message(m) for m in request.messages],
    }
    effort = _select_reasoning_effort(entry, request)
    if effort is not None:
        payload["reasoning_effort"] = effort
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in request.tools
        ]
    return payload
```

- [ ] **Step 4: Run — confirm PASS**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_tensorix_http.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_tensorix_http.py backend/tests/modules/llm/adapters/test_tensorix_http.py
git commit -m "Add Tensorix chat-payload builder with per-model reasoning rules"
```

---

## Task 9: SSE chunk parser — content, reasoning_content, tool_calls, usage

**Files:**
- Modify: `backend/modules/llm/_adapters/_tensorix_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_tensorix_http.py`

**Background:** Tensorix is fully OpenAI-compatible. Reasoning content arrives via `delta.reasoning_content` (string). Tool calls come as fragments in `delta.tool_calls` (index-keyed). The usage chunk is delivered separately at the end when `stream_options.include_usage=true`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/modules/llm/adapters/test_tensorix_http.py`:

```python
from backend.modules.llm._adapters._events import (
    ContentDelta,
    StreamDone,
    StreamRefused,
    ThinkingDelta,
    ToolCallEvent,
)
from backend.modules.llm._adapters._tensorix_http import (
    _chunk_to_events,
    _parse_sse_line,
    _SSE_DONE,
    _ToolCallAccumulator,
)


def test_parse_sse_line_data_json():
    parsed = _parse_sse_line('data: {"choices": []}')
    assert parsed == {"choices": []}


def test_parse_sse_line_done():
    assert _parse_sse_line("data: [DONE]") is _SSE_DONE


def test_parse_sse_line_blank_is_none():
    assert _parse_sse_line("") is None


def test_parse_sse_line_garbage_is_none():
    assert _parse_sse_line('data: {not json}') is None


def test_chunk_emits_content_delta():
    chunk = {
        "choices": [{"delta": {"content": "Hello"}, "finish_reason": None}],
    }
    events = _chunk_to_events(chunk, _ToolCallAccumulator())
    assert events == [ContentDelta(delta="Hello")]


def test_chunk_emits_thinking_delta_from_reasoning_content():
    chunk = {
        "choices": [{
            "delta": {"reasoning_content": "Let me think..."},
            "finish_reason": None,
        }],
    }
    events = _chunk_to_events(chunk, _ToolCallAccumulator())
    assert events == [ThinkingDelta(delta="Let me think...")]


def test_chunk_emits_both_thinking_and_visible_in_order():
    chunk = {
        "choices": [{
            "delta": {
                "reasoning_content": "thinking",
                "content": "answer",
            },
            "finish_reason": None,
        }],
    }
    events = _chunk_to_events(chunk, _ToolCallAccumulator())
    assert events == [
        ThinkingDelta(delta="thinking"),
        ContentDelta(delta="answer"),
    ]


def test_tool_call_accumulator_finalises_on_finish_reason():
    acc = _ToolCallAccumulator()
    # First chunk: id + name fragment.
    _chunk_to_events({
        "choices": [{
            "delta": {
                "tool_calls": [{
                    "index": 0,
                    "id": "call_abc",
                    "function": {"name": "get_weather", "arguments": '{"loc'},
                }],
            },
            "finish_reason": None,
        }],
    }, acc)
    # Second chunk: rest of arguments + finish.
    events = _chunk_to_events({
        "choices": [{
            "delta": {
                "tool_calls": [{
                    "index": 0,
                    "function": {"arguments": '":"Tokyo"}'},
                }],
            },
            "finish_reason": "tool_calls",
        }],
    }, acc)
    assert events == [ToolCallEvent(
        id="call_abc",
        name="get_weather",
        arguments='{"loc":"Tokyo"}',
    )]


def test_chunk_emits_stream_done_on_usage_chunk():
    chunk = {
        "choices": [],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 34,
            "completion_tokens_details": {"reasoning_tokens": 5},
        },
    }
    events = _chunk_to_events(chunk, _ToolCallAccumulator())
    assert events == [StreamDone(
        input_tokens=12,
        output_tokens=34,
        reasoning_tokens=5,
    )]


def test_chunk_emits_refused_on_content_filter():
    chunk = {
        "choices": [{
            "delta": {"refusal": "I cannot help with that."},
            "finish_reason": "content_filter",
        }],
    }
    events = _chunk_to_events(chunk, _ToolCallAccumulator())
    assert any(isinstance(e, StreamRefused) for e in events)
```

- [ ] **Step 2: Run — confirm FAIL**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_tensorix_http.py -k "chunk or parse_sse or tool_call_accumulator" -v`
Expected: all FAIL on ImportError.

- [ ] **Step 3: Implement the helpers**

Add to `_tensorix_http.py` (above `_build_chat_payload`):

```python
class _ToolCallAccumulator:
    """Gathers OpenAI-style tool_call fragments across SSE chunks.

    Upstream providers stream tool calls in pieces, indexed by
    ``tool_calls[].index``. Each fragment may carry id, name, or an
    arguments string fragment. We accumulate by index and finalise once
    the upstream signals ``finish_reason="tool_calls"``.
    """

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


def _parse_sse_line(line: str) -> dict | object | None:
    """Parse a single SSE line.

    Returns:
        - a ``dict`` when the line is a valid ``data: {json}`` frame,
        - ``_SSE_DONE`` for ``data: [DONE]`` (stream terminator),
        - ``None`` for empty lines, non-data lines, or malformed JSON.
    """
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


def _chunk_to_events(
    chunk: dict,
    acc: _ToolCallAccumulator,
) -> list[ProviderStreamEvent]:
    """Map one parsed SSE chunk into zero or more provider events.

    Tensorix is OpenAI-compatible: reasoning_content carries thinking
    (string), content carries visible output (string), tool_calls arrive
    index-keyed in fragments, and the usage chunk arrives separately at
    the tail of the stream because we set stream_options.include_usage.
    """
    events: list[ProviderStreamEvent] = []
    choices = chunk.get("choices") or []
    usage = chunk.get("usage") or {}

    if usage and not choices:
        details = usage.get("completion_tokens_details") or {}
        events.append(StreamDone(
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            reasoning_tokens=details.get("reasoning_tokens"),
        ))
        return events

    if not choices:
        return events

    choice = choices[0]
    delta = choice.get("delta") or {}

    reasoning_text = delta.get("reasoning_content") or ""
    if reasoning_text:
        events.append(ThinkingDelta(delta=reasoning_text))

    visible_text = delta.get("content")
    if isinstance(visible_text, str) and visible_text:
        events.append(ContentDelta(delta=visible_text))

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
```

- [ ] **Step 4: Run — confirm PASS**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_tensorix_http.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_tensorix_http.py backend/tests/modules/llm/adapters/test_tensorix_http.py
git commit -m "Add Tensorix SSE chunk parser with tool-call accumulator"
```

---

## Task 10: `stream_completion` — full streaming integration with retry + gutter

**Files:**
- Modify: `backend/modules/llm/_adapters/_tensorix_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_tensorix_http.py`

**Note:** This is a near-copy of Mistral's `stream_completion`. The shape is identical because both providers are OpenAI-compatible.

- [ ] **Step 1: Write the failing integration test**

Append to `backend/tests/modules/llm/adapters/test_tensorix_http.py`:

```python
from backend.modules.llm._adapters._events import StreamError


class _MockAsyncStream:
    """Mimics httpx.Response under ``client.stream(...)``."""
    def __init__(self, lines: list[str], status_code: int = 200, headers: dict | None = None):
        self._lines = lines
        self.status_code = status_code
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def aiter_lines(self):
        async def _gen():
            for line in self._lines:
                yield line
        return _gen()

    async def aread(self):
        return b""


class _MockClient:
    def __init__(self, response: _MockAsyncStream):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def stream(self, method, url, json=None, headers=None):
        return self._response


@pytest.mark.asyncio
async def test_stream_completion_yields_content_then_done(monkeypatch):
    lines = [
        'data: {"choices":[{"delta":{"content":"Hi"},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":1}}',
        'data: [DONE]',
    ]
    mock_response = _MockAsyncStream(lines)
    monkeypatch.setattr(
        "backend.modules.llm._adapters._tensorix_http.httpx.AsyncClient",
        lambda *a, **kw: _MockClient(mock_response),
    )

    adapter = TensorixHttpAdapter()
    events = []
    async for ev in adapter.stream_completion(
        _make_resolved_connection(),
        _make_request(model_id="deepseek-v4-flash"),
    ):
        events.append(ev)

    assert any(isinstance(e, ContentDelta) and e.delta == "Hi" for e in events)
    assert any(isinstance(e, StreamDone) for e in events)


@pytest.mark.asyncio
async def test_stream_completion_401_emits_invalid_api_key(monkeypatch):
    mock_response = _MockAsyncStream(lines=[], status_code=401)
    monkeypatch.setattr(
        "backend.modules.llm._adapters._tensorix_http.httpx.AsyncClient",
        lambda *a, **kw: _MockClient(mock_response),
    )
    adapter = TensorixHttpAdapter()
    events = []
    async for ev in adapter.stream_completion(
        _make_resolved_connection(),
        _make_request(model_id="deepseek-v4-flash"),
    ):
        events.append(ev)
    assert len(events) == 1
    assert isinstance(events[0], StreamError)
    assert events[0].error_code == "invalid_api_key"
```

- [ ] **Step 2: Run — confirm FAIL**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_tensorix_http.py::test_stream_completion_yields_content_then_done -v`
Expected: FAIL on AttributeError (`stream_completion` not yet defined).

- [ ] **Step 3: Implement `stream_completion`**

Add to the `TensorixHttpAdapter` class:

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
        }

        seen_done = False
        pending_next: asyncio.Task | None = None

        if _TRACE_PAYLOADS:
            _log.info(
                "LLM_TRACE path=tensorix-out url=%s payload=%s",
                url,
                json.dumps(payload, default=str, sort_keys=True),
            )

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for attempt in range(MAX_RETRY_ATTEMPTS + 1):
                acc = _ToolCallAccumulator()
                retry_delay: float | None = None
                try:
                    async with client.stream(
                        "POST", f"{url}/chat/completions",
                        json=payload, headers=headers,
                    ) as resp:
                        if (
                            should_retry_status(resp.status_code)
                            and attempt < MAX_RETRY_ATTEMPTS
                        ):
                            retry_delay = compute_retry_delay(
                                attempt,
                                parse_retry_after(resp.headers),
                            )
                            log_retry(
                                _log,
                                operation="tensorix_http",
                                attempt=attempt,
                                delay_seconds=retry_delay,
                                status_code=resp.status_code,
                                extra={"model": payload.get("model")},
                            )
                        elif resp.status_code in (401, 403):
                            yield StreamError(
                                error_code="invalid_api_key",
                                message="Tensorix rejected the API key",
                            )
                            return
                        elif should_retry_status(resp.status_code):
                            yield StreamError(
                                error_code="provider_unavailable",
                                message=(
                                    f"Tensorix returned {resp.status_code}; "
                                    f"gave up after {MAX_RETRY_ATTEMPTS + 1} attempts"
                                ),
                            )
                            return
                        elif resp.status_code != 200:
                            body = await resp.aread()
                            detail = body.decode("utf-8", errors="replace")[:500]
                            _log.error("tensorix_http upstream %d: %s",
                                       resp.status_code, detail)
                            yield StreamError(
                                error_code="provider_unavailable",
                                message=f"Tensorix returned {resp.status_code}: {detail}",
                            )
                            return
                        else:
                            try:
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
                                                "tensorix_http.gutter_slow model=%s idle=%.1fs",
                                                payload.get("model"), elapsed,
                                            )
                                            yield StreamSlow()
                                            slow_fired = True
                                            continue
                                        _log.warning(
                                            "tensorix_http.gutter_abort model=%s idle=%.1fs",
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
                            if not seen_done:
                                yield StreamDone()
                            return
                except httpx.ConnectError:
                    yield StreamError(
                        error_code="provider_unavailable",
                        message="Cannot connect to Tensorix",
                    )
                    return

                assert retry_delay is not None
                await asyncio.sleep(retry_delay)
```

- [ ] **Step 4: Run — confirm PASS**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_tensorix_http.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_tensorix_http.py backend/tests/modules/llm/adapters/test_tensorix_http.py
git commit -m "Add Tensorix stream_completion with retry and gutter timer"
```

---

## Task 11: `/test` sub-router — capability-drift canary

**Files:**
- Modify: `backend/modules/llm/_adapters/_tensorix_http.py`
- Modify: `backend/tests/modules/llm/adapters/test_tensorix_http.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/modules/llm/adapters/test_tensorix_http.py`:

```python
import json as _json


class _MockProbeResponse:
    def __init__(self, status_code: int, body: dict | None = None):
        self.status_code = status_code
        self._body = body or {}

    async def aread(self):
        return _json.dumps(self._body).encode()

    def json(self):
        return self._body


class _MockProbeClient:
    def __init__(self, response: _MockProbeResponse):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, headers=None):
        return self._response


@pytest.mark.asyncio
async def test_adapter_test_endpoint_returns_valid_when_curated_slug_present(monkeypatch):
    body = {"data": [{"model_name": "deepseek/deepseek-v4-flash"}]}
    response = _MockProbeResponse(200, body)
    monkeypatch.setattr(
        "backend.modules.llm._adapters._tensorix_http.httpx.AsyncClient",
        lambda *a, **kw: _MockProbeClient(response),
    )

    from backend.modules.llm._adapters._tensorix_http import _probe_tensorix

    result = await _probe_tensorix(
        url="https://api.tensorix.ai/v1", api_key="sk-test",
    )
    assert result == {"valid": True, "error": None}


@pytest.mark.asyncio
async def test_adapter_test_endpoint_401_returns_rejected(monkeypatch):
    response = _MockProbeResponse(401, {})
    monkeypatch.setattr(
        "backend.modules.llm._adapters._tensorix_http.httpx.AsyncClient",
        lambda *a, **kw: _MockProbeClient(response),
    )
    from backend.modules.llm._adapters._tensorix_http import _probe_tensorix

    result = await _probe_tensorix(
        url="https://api.tensorix.ai/v1", api_key="bad-key",
    )
    assert result["valid"] is False
    assert "rejected" in (result["error"] or "").lower()


@pytest.mark.asyncio
async def test_adapter_test_endpoint_zero_curated_slugs_returns_drift_error(monkeypatch):
    # 200 response that lists models, but none of ours -> drift canary fires.
    body = {"data": [{"model_name": "totally/different-model"}]}
    response = _MockProbeResponse(200, body)
    monkeypatch.setattr(
        "backend.modules.llm._adapters._tensorix_http.httpx.AsyncClient",
        lambda *a, **kw: _MockProbeClient(response),
    )
    from backend.modules.llm._adapters._tensorix_http import _probe_tensorix

    result = await _probe_tensorix(
        url="https://api.tensorix.ai/v1", api_key="sk-test",
    )
    assert result["valid"] is False
    assert "curated" in (result["error"] or "").lower()
```

- [ ] **Step 2: Run — confirm FAIL**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_tensorix_http.py -k "probe or test_endpoint" -v`
Expected: ImportError of `_probe_tensorix`.

- [ ] **Step 3: Implement the probe helper and replace the stub router**

Replace the existing placeholder `_build_adapter_router` in `_tensorix_http.py` with the helper + full router:

```python
_CURATED_UPSTREAM_SLUGS: frozenset[str] = frozenset(
    m.upstream_slug for m in _TENSORIX_MODELS
)


async def _probe_tensorix(*, url: str, api_key: str) -> dict:
    """Validate the URL + key against Tensorix's /model/info endpoint.

    Returns ``{"valid": bool, "error": str | None}``. Fails closed when
    none of the curated upstream slugs are present in the response — a
    cheap canary against Tensorix renaming or retiring a model behind
    our back.
    """
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            resp = await client.get(
                f"{url}/model/info",
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except Exception as exc:  # noqa: BLE001 — surface to frontend
        return {"valid": False, "error": str(exc) or exc.__class__.__name__}

    if resp.status_code in (401, 403):
        return {"valid": False, "error": "API key rejected by Tensorix"}
    if resp.status_code != 200:
        return {
            "valid": False,
            "error": f"Tensorix returned {resp.status_code}",
        }

    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        return {"valid": False, "error": "Tensorix returned non-JSON body"}

    items = body.get("data") or []
    seen_upstream = {
        item.get("model_name") for item in items if isinstance(item, dict)
    }
    intersection = _CURATED_UPSTREAM_SLUGS & {s for s in seen_upstream if s}
    if not intersection:
        return {
            "valid": False,
            "error": (
                "No curated Tensorix models present in /model/info "
                "— capability drift detected"
            ),
        }
    return {"valid": True, "error": None}


def _tensorix_repo_factory():
    """Default factory — returns a ConnectionRepository backed by the live DB.

    Defined at module level so tests can monkeypatch it.
    """
    from backend.database import get_db
    from backend.modules.llm._connections import ConnectionRepository
    return ConnectionRepository(get_db())


def _build_adapter_router() -> APIRouter:
    from datetime import UTC, datetime

    import backend.modules.llm._adapters._tensorix_http as _self
    from backend.modules.llm._connections import ConnectionRepository
    from backend.modules.llm._resolver import resolve_connection_for_user
    from backend.ws.event_bus import EventBus, get_event_bus
    from shared.events.llm import LlmConnectionUpdatedEvent
    from shared.topics import Topics

    router = APIRouter()

    @router.post("/test")
    async def test_connection(
        c: ResolvedConnection = Depends(resolve_connection_for_user),
        event_bus: EventBus = Depends(get_event_bus),
        repo=Depends(lambda: _self._tensorix_repo_factory()),
    ) -> dict:
        url = c.config["url"].rstrip("/")
        api_key = c.config.get("api_key") or ""
        result = await _probe_tensorix(url=url, api_key=api_key)
        valid = result["valid"]
        error = result["error"]

        updated = await repo.update_test_status(
            c.user_id, c.id,
            status="valid" if valid else "failed",
            error=error,
        )
        if updated is not None:
            await event_bus.publish(
                Topics.LLM_CONNECTION_UPDATED,
                LlmConnectionUpdatedEvent(
                    connection=ConnectionRepository.to_dto(updated),
                    timestamp=datetime.now(UTC),
                ),
            )
        return {"valid": valid, "error": error}

    return router
```

- [ ] **Step 4: Run — confirm PASS**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_tensorix_http.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_tensorix_http.py backend/tests/modules/llm/adapters/test_tensorix_http.py
git commit -m "Add Tensorix /test sub-router with curated-slug drift canary"
```

---

## Task 12: Wire Tensorix into registry and resolver

**Files:**
- Modify: `backend/modules/llm/_registry.py`
- Modify: `backend/modules/llm/_resolver.py`

- [ ] **Step 1: Write a registry sanity test**

Create `backend/tests/modules/llm/test_tensorix_wiring.py`:

```python
"""End-to-end wiring tests for Tensorix in the LLM registry + resolver."""
from __future__ import annotations

import pytest

from backend.modules.llm._registry import (
    _PREMIUM_ONLY_ADAPTERS,
    ADAPTER_REGISTRY,
    get_adapter_class,
)


def test_tensorix_is_premium_only_not_user_creatable():
    assert "tensorix_http" not in ADAPTER_REGISTRY
    assert "tensorix_http" in _PREMIUM_ONLY_ADAPTERS


def test_get_adapter_class_resolves_tensorix():
    cls = get_adapter_class("tensorix_http")
    assert cls is not None
    assert cls.__name__ == "TensorixHttpAdapter"


def test_resolver_premium_map_includes_tensorix():
    from backend.modules.llm._resolver import _PREMIUM_ADAPTER_TYPE
    assert _PREMIUM_ADAPTER_TYPE["tensorix"] == "tensorix_http"
```

- [ ] **Step 2: Run — confirm FAIL**

Run: `uv run pytest backend/tests/modules/llm/test_tensorix_wiring.py -v`
Expected: all three FAIL — not yet registered.

- [ ] **Step 3: Register in the LLM registry**

Edit `backend/modules/llm/_registry.py` — add the import and the dict entry:

```python
from backend.modules.llm._adapters._tensorix_http import TensorixHttpAdapter
```

Then update `_PREMIUM_ONLY_ADAPTERS` to:

```python
_PREMIUM_ONLY_ADAPTERS: dict[str, type[BaseAdapter]] = {
    "xai_http": XaiHttpAdapter,
    "mistral_http": MistralHttpAdapter,
    "tensorix_http": TensorixHttpAdapter,
    "nano_gpt_http": NanoGptHttpAdapter,
    "openrouter_http": OpenRouterHttpAdapter,
    "novita_http": NovitaHttpAdapter,
}
```

- [ ] **Step 4: Wire the resolver map**

Edit `backend/modules/llm/_resolver.py`. Update `_PREMIUM_ADAPTER_TYPE` to:

```python
_PREMIUM_ADAPTER_TYPE: dict[str, str] = {
    "xai": "xai_http",
    "mistral": "mistral_http",
    "tensorix": "tensorix_http",
    "ollama_cloud": "ollama_http",
    "nano_gpt": "nano_gpt_http",
    "openrouter": "openrouter_http",
    "novita": "novita_http",
}
```

- [ ] **Step 5: Run — confirm PASS**

Run: `uv run pytest backend/tests/modules/llm/test_tensorix_wiring.py -v`
Expected: all three PASS.

- [ ] **Step 6: Run the full adapter + provider + wiring test suite**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_tensorix_http.py backend/tests/modules/llm/test_tensorix_wiring.py backend/tests/modules/providers/ -v`
Expected: every test PASSES, no regressions.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/llm/_registry.py backend/modules/llm/_resolver.py backend/tests/modules/llm/test_tensorix_wiring.py
git commit -m "Register Tensorix adapter in LLM registry and premium resolver"
```

---

## Task 13: LLM harness scenarios for smoke verification

**Files:**
- Create: `tests/llm_scenarios/tensorix_deepseek_v4_flash_simple.json`
- Create: `tests/llm_scenarios/tensorix_deepseek_v4_pro_stepped_reasoning.json`
- Create: `tests/llm_scenarios/tensorix_kimi_k2_6_tools.json`

**Note:** These are not automated tests — they're reproducible scenarios for `backend/llm_harness/`. Use them manually with `uv run python -m backend.llm_harness --from <file>` to verify the live integration after deploy.

- [ ] **Step 1: Create the simple-prompt scenario**

Create `tests/llm_scenarios/tensorix_deepseek_v4_flash_simple.json`:

```json
{
  "model": "deepseek-v4-flash",
  "system": "You are a concise assistant. Answer in one sentence.",
  "messages": [
    {"role": "user", "content": "What is the capital of France?"}
  ],
  "reasoning": false
}
```

- [ ] **Step 2: Create the stepped-reasoning scenario**

Create `tests/llm_scenarios/tensorix_deepseek_v4_pro_stepped_reasoning.json`:

```json
{
  "model": "deepseek-v4-pro",
  "system": "Think before you answer.",
  "messages": [
    {"role": "user", "content": "Estimate how many tennis balls fit in a school bus. Show working."}
  ],
  "reasoning": true,
  "reasoning_effort": "medium"
}
```

- [ ] **Step 3: Create the tool-call scenario**

Create `tests/llm_scenarios/tensorix_kimi_k2_6_tools.json`:

```json
{
  "model": "kimi-k2-6",
  "system": "Use tools when they're appropriate.",
  "messages": [
    {"role": "user", "content": "What is the weather in Tokyo right now?"}
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Return the current weather for a location.",
        "parameters": {
          "type": "object",
          "properties": {
            "location": {"type": "string"}
          },
          "required": ["location"]
        }
      }
    }
  ]
}
```

- [ ] **Step 4: Commit**

```bash
git add tests/llm_scenarios/tensorix_deepseek_v4_flash_simple.json \
        tests/llm_scenarios/tensorix_deepseek_v4_pro_stepped_reasoning.json \
        tests/llm_scenarios/tensorix_kimi_k2_6_tools.json
git commit -m "Add Tensorix LLM harness scenarios for smoke verification"
```

---

## Task 14: Final verification — compile, full test suite, end-to-end checklist

**Files:** none modified — verification only.

- [ ] **Step 1: Compile every touched Python file**

Run:
```bash
uv run python -m py_compile \
  backend/modules/providers/_models.py \
  backend/modules/providers/_registry.py \
  backend/modules/providers/__init__.py \
  backend/modules/llm/_adapters/_tensorix_http.py \
  backend/modules/llm/_registry.py \
  backend/modules/llm/_resolver.py \
  shared/dtos/providers.py
```
Expected: exit code 0 for every file, no output.

- [ ] **Step 2: Run the full test suite for the touched modules**

Run:
```bash
uv run pytest \
  backend/tests/modules/llm/adapters/test_tensorix_http.py \
  backend/tests/modules/llm/test_tensorix_wiring.py \
  backend/tests/modules/providers/ \
  -v
```
Expected: all PASS, zero failures.

- [ ] **Step 3: Run the broader providers / llm test suites for regression check**

Run:
```bash
uv run pytest backend/tests/modules/providers/ backend/tests/modules/llm/ -v --tb=short
```
Expected: pre-existing tests stay green; only the new ones are added.

- [ ] **Step 4: Run the frontend type-check**

Run:
```bash
cd frontend && pnpm tsc --noEmit
```
Expected: zero TS errors. (No frontend code was modified — this confirms the new `sort_priority` field hasn't broken any frontend type expectations. If the frontend has a TS type for `PremiumProviderDefinitionDto`, add `sort_priority?: number` to it before this step — search `frontend/src/core/types/` and `frontend/src/core/api/providers.ts` for `PremiumProviderDefinition`.)

- [ ] **Step 5: Manual smoke (post-deploy, optional but recommended)**

After deploying:
1. Open the app, go to Premium Providers, click "Add Tensorix".
2. Confirm Tensorix appears between Ollama Cloud and xAI in the list.
3. Paste the Tensorix test key from `.tensorix-test-key`, save.
4. Click "Test" — confirm green check.
5. Pick `DeepSeek V4 Flash`, send "Hello" — confirm streaming response, no thinking pill (binary off).
6. Toggle reasoning on, send a prompt — confirm thinking content appears.
7. Switch to `DeepSeek V4 Pro` — confirm the thinking button shows three buckets (Low/Medium/High) in its pop-out, plus Off.
8. Pick `Kimi K2.6` and craft a tool-call prompt; confirm round trip.

- [ ] **Step 6: Final commit (if any cleanup happened) and push**

If everything passes with no further edits, no extra commit. Otherwise commit any cleanup fixes with a clear message.

---

## Self-Review Summary

**Spec coverage check:**
- §3.1 / §3.2 file map → Tasks 1–12 cover every "create" and "modify" item except the `ReasoningEffortDropdown` and `reasoning_mode` DTO field, which are intentionally dropped (see "Important Architecture Insight" above — the existing `effort` field handles both shapes).
- §4 curated schema → Task 5 (table) + Task 6 (capability hint).
- §5 data flow → Task 8 (payload) + Task 9 (parser) + Task 10 (stream loop).
- §6 sort_priority → Tasks 1–4.
- §7 reasoning UI → no work needed; verified by Task 14 step 5.
- §8 sub-router → Task 11.
- §9 error handling → Task 10 (401/403 paths) + Task 11 (probe-side errors).
- §10 testing → Tasks 5–12 (unit), Task 13 (harness), Task 14 (verification).
- §11 resolved questions → encoded in the curated table (Task 5) + capability hint (Task 6).
- §12 dependency hygiene → no new deps; verified in Task 14.

**Placeholders:** scanned — none. Every code step has full code, every command has expected output.

**Type consistency:** `_TensorixModelEntry.model_id` is referenced consistently in Tasks 5/6/7/8/11; `reasoning_mode` literal `"binary"|"stepped"|None` is consistent everywhere; `_TENSORIX_MODELS` and `_TENSORIX_MODELS_BY_ID` are introduced together in Task 5 and referenced from every subsequent task.

**Open delta from spec:**
The spec called for `ReasoningEffortDropdown` and a new `reasoning_mode` DTO field. This plan does not add those because the existing `ReasoningCapability.effort: ReasoningEffortSpec | None` + `ThinkingButton.tsx` already render the exact UX described in spec §7 (Off / Low / Medium / High pop-out). The spec should be updated to reflect that the existing machinery is the implementation — flagged in the cover note above. No code-quality cost from the change; the integration is strictly smaller than the spec suggested.

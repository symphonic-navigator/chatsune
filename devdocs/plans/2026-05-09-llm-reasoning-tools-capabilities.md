# LLM Reasoning & Tools Capabilities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single `supports_reasoning` boolean with a capability-rich model that distinguishes reasoning kind, tool support, tool×reasoning mutex, and effort buckets — wired through four adapters (ollama, nano-gpt, novita, openrouter), a hand-curated YAML, a session-scoped cockpit, and a model browser badge.

**Architecture:** Three orthogonal capability axes on `ModelMetaDto` (reasoning kind, tools, mutex), populated by a resolver that consults YAML → adapter heuristic → universal default. Per-adapter translation layer maps internal vocabulary (`reasoning_mode`, `reasoning_effort`) to provider-specific request shapes with "always explicit" semantics. Settings live on the chat session document, sticky per session, mapped on model switch with "tools win on conflict". Frontend cockpit always renders both buttons with disabled-with-tooltip states; effort-capable models get a pop-out that includes "Off" as a first-class choice.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, MongoDB, React + TS + Vite, pnpm, pytest, Vitest. xAI and Mistral adapters are out of scope for this plan and get conservative-default updates only.

**Spec:** `devdocs/specs/2026-05-09-llm-reasoning-tools-capabilities-design.md`

---

## File Structure

**Backend — new files:**
- `backend/modules/llm/data/model_capabilities.yaml` — hand-curated capability overrides
- `backend/modules/llm/_capabilities.py` — YAML loader + `resolve_capabilities()` + types

**Backend — modified files:**
- `shared/dtos/llm.py` — `ReasoningEffortSpec`, `ReasoningCapability`, `ToolCapability`; `ModelMetaDto` extension
- `shared/dtos/inference.py` — `CompletionRequest` swap `reasoning_enabled`+`supports_reasoning` for `extras`
- `shared/dtos/chat.py` — `ChatSessionExtras` + `ChatSessionDto.extras`
- `shared/events/chat.py` — `ChatSessionExtrasUpdatedEvent`
- `shared/topics.py` — `CHAT_SESSION_EXTRAS_UPDATED`
- `backend/modules/llm/_adapters/_base.py` — `capability_hint()` interface
- `backend/modules/llm/_adapters/_ollama_http.py` — translation + capability_hint
- `backend/modules/llm/_adapters/_nano_gpt_http.py` — translation + capability_hint (preserve `_pair_map.py`)
- `backend/modules/llm/_adapters/_novita_http.py` — translation + capability_hint
- `backend/modules/llm/_adapters/_openrouter_http.py` — translation + capability_hint
- `backend/modules/llm/_adapters/_xai_http.py` — minimal-impact: emit new fields with conservative defaults
- `backend/modules/llm/_adapters/_mistral_http.py` — minimal-impact: emit new fields with conservative defaults
- `backend/modules/chat/_models.py` — `ChatSessionDocument.extras`
- `backend/modules/chat/_repository.py` — read/write extras, remap on model change
- `backend/modules/chat/_handlers.py` — `PATCH /api/chat/sessions/{id}/extras`
- `backend/modules/chat/_handlers_ws.py` — read extras instead of `persona.reasoning_enabled`
- `backend/modules/chat/_orchestrator.py` — pass extras to adapter
- `backend/modules/chat/_prompt_assembler.py` — replace `reasoning_enabled_for_call` with extras
- `backend/modules/chat/_soft_cot.py` — same
- `backend/modules/chat/_vision_fallback.py` — same

**Frontend — modified files:**
- `frontend/src/core/types/llm.ts` — capability types mirror DTOs
- `frontend/src/core/types/chat.ts` (or chat-specific types file) — `ChatSessionExtras` type
- `frontend/src/core/api/chat.ts` — PATCH `/extras` call
- `frontend/src/features/chat/cockpit/cockpitStore.ts` — extras-based state
- `frontend/src/features/chat/cockpit/buttons/ThinkingButton.tsx` — 5 capability states + pop-out
- `frontend/src/features/chat/cockpit/buttons/ToolsButton.tsx` — disabled state, mutex-aware
- `frontend/src/features/chat/cockpit/CockpitBar.tsx` — mutex coordination layer
- `frontend/src/app/components/persona-overlay/EditTab.tsx` — remove reasoning toggle
- `frontend/src/app/components/model-browser/ModelBrowser.tsx` — first-class badge + filter
- `frontend/src/app/components/model-browser/modelBrowserStore.ts` — filter state

**Tests — new files:**
- `backend/modules/llm/tests/test_capabilities.py`
- `backend/modules/llm/tests/test_translation_ollama.py`
- `backend/modules/llm/tests/test_translation_nano_gpt.py`
- `backend/modules/llm/tests/test_translation_novita.py`
- `backend/modules/llm/tests/test_translation_openrouter.py`
- `backend/modules/chat/tests/test_session_extras.py`
- `backend/modules/chat/tests/test_model_switch_remap.py`
- `frontend/src/features/chat/cockpit/__tests__/ThinkingButton.test.tsx`
- `frontend/src/features/chat/cockpit/__tests__/CockpitBar.test.tsx`
- `frontend/src/app/components/model-browser/__tests__/ModelBrowser.test.tsx`

---

## Test Execution Notes

- **Backend tests on host:** prepend `PYTHONPATH=$(pwd)` (per the `pyproject.toml` quirk in this repo).
- **Backend tests requiring MongoDB:** run inside Docker (per CLAUDE.md). For host runs of the rest, exclude the four MongoDB-using files explicitly. New tests in this plan should be unit-pure (no live DB).
- **Frontend build verification:** use `pnpm run build` after every frontend change. `pnpm tsc --noEmit` is insufficient — `tsc -b` (in `pnpm run build`) catches stricter type errors that CI fails on.

---

## Task 1: Capability DTOs in `shared/dtos/llm.py`

**Files:**
- Modify: `shared/dtos/llm.py`
- Test: `backend/modules/llm/tests/test_capability_dtos.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# backend/modules/llm/tests/test_capability_dtos.py
from shared.dtos.llm import (
    ReasoningEffortSpec,
    ReasoningCapability,
    ToolCapability,
)


def test_reasoning_effort_spec_requires_default_in_buckets():
    spec = ReasoningEffortSpec(buckets=["low", "medium", "high"], default_bucket="medium")
    assert spec.default_bucket in spec.buckets


def test_reasoning_capability_optional_with_effort():
    cap = ReasoningCapability(
        kind="optional",
        effort=ReasoningEffortSpec(buckets=["low", "medium", "high"], default_bucket="medium"),
        default_on=True,
    )
    assert cap.kind == "optional"
    assert cap.effort.default_bucket == "medium"


def test_reasoning_capability_no_reasoning_omits_effort():
    cap = ReasoningCapability(kind="no_reasoning")
    assert cap.effort is None


def test_tool_capability_default_no_mutex():
    cap = ToolCapability(supported=True)
    assert cap.exclusive_with_reasoning is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$(pwd) pytest backend/modules/llm/tests/test_capability_dtos.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Add the DTOs**

Add to `shared/dtos/llm.py` (near the top, before `ModelMetaDto`):

```python
class ReasoningEffortSpec(BaseModel):
    """When non-None on a ReasoningCapability, the model has an effort selector."""
    buckets: list[str]
    default_bucket: str

    @field_validator("default_bucket")
    @classmethod
    def _default_in_buckets(cls, v: str, info) -> str:
        buckets = info.data.get("buckets") or []
        if buckets and v not in buckets:
            raise ValueError(f"default_bucket {v!r} not in buckets {buckets!r}")
        return v


class ReasoningCapability(BaseModel):
    kind: Literal["no_reasoning", "optional", "always_on"]
    effort: ReasoningEffortSpec | None = None
    default_on: bool = True


class ToolCapability(BaseModel):
    supported: bool
    exclusive_with_reasoning: bool = False
```

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=$(pwd) pytest backend/modules/llm/tests/test_capability_dtos.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add shared/dtos/llm.py backend/modules/llm/tests/test_capability_dtos.py
git commit -m "Add reasoning and tool capability DTOs"
```

---

## Task 2: Extend `ModelMetaDto` with capability fields

**Files:**
- Modify: `shared/dtos/llm.py:12-52`
- Test: `backend/modules/llm/tests/test_capability_dtos.py`

- [ ] **Step 1: Add tests for the new fields**

Append to `backend/modules/llm/tests/test_capability_dtos.py`:

```python
from shared.dtos.llm import ModelMetaDto


def _meta(**overrides):
    base = dict(
        connection_id="c1",
        connection_slug="conn",
        model_id="m1",
        display_name="M1",
        context_window=8000,
        supports_vision=False,
        supports_tool_calls=True,
        reasoning=ReasoningCapability(kind="optional"),
        tools=ToolCapability(supported=True),
    )
    base.update(overrides)
    return ModelMetaDto(**base)


def test_model_meta_supports_reasoning_computed_true_when_optional():
    m = _meta()
    assert m.supports_reasoning is True


def test_model_meta_supports_reasoning_computed_false_when_no_reasoning():
    m = _meta(reasoning=ReasoningCapability(kind="no_reasoning"))
    assert m.supports_reasoning is False


def test_model_meta_first_class_default_false():
    m = _meta()
    assert m.first_class_support is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=$(pwd) pytest backend/modules/llm/tests/test_capability_dtos.py -v`
Expected: 3 new tests FAIL (`reasoning`/`tools`/`first_class_support` not on `ModelMetaDto`).

- [ ] **Step 3: Extend `ModelMetaDto`**

Edit `shared/dtos/llm.py`. In `ModelMetaDto` (around line 12):
- Replace the line `supports_reasoning: bool` with `reasoning: ReasoningCapability` plus a `tools: ToolCapability` field plus `first_class_support: bool = False`, AND a computed `supports_reasoning` for backwards compat.

Final shape:

```python
class ModelMetaDto(BaseModel):
    connection_id: str
    connection_slug: str = ""
    connection_display_name: str = ""
    model_id: str
    display_name: str
    context_window: int
    reasoning: ReasoningCapability
    supports_vision: bool
    supports_tool_calls: bool   # legacy field, kept for callers; tools.supported is canonical
    tools: ToolCapability
    first_class_support: bool = False
    parameter_count: str | None = None
    raw_parameter_count: int | None = None
    quantisation_level: str | None = None
    is_deprecated: bool = False
    billing_category: Literal["free", "subscription", "pay_per_token"] | None = None
    is_moderated: bool | None = None
    remarks: str | None = None

    @computed_field
    @property
    def supports_reasoning(self) -> bool:
        return self.reasoning.kind != "no_reasoning"

    @computed_field
    @property
    def unique_id(self) -> str:
        return f"{self.connection_slug}:{self.model_id}"
```

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=$(pwd) pytest backend/modules/llm/tests/test_capability_dtos.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add shared/dtos/llm.py backend/modules/llm/tests/test_capability_dtos.py
git commit -m "Extend ModelMetaDto with reasoning/tools capabilities and first_class_support"
```

---

## Task 3: `ChatSessionExtras` DTO

**Files:**
- Modify: `shared/dtos/chat.py`
- Test: `backend/modules/chat/tests/test_session_extras_dto.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# backend/modules/chat/tests/test_session_extras_dto.py
import pytest
from pydantic import ValidationError
from shared.dtos.chat import ChatSessionExtras


def test_chat_session_extras_requires_all_three_fields():
    extras = ChatSessionExtras(
        tools_enabled=True, reasoning_mode="off", reasoning_effort=None
    )
    assert extras.tools_enabled is True
    assert extras.reasoning_mode == "off"
    assert extras.reasoning_effort is None


def test_chat_session_extras_rejects_invalid_mode():
    with pytest.raises(ValidationError):
        ChatSessionExtras(
            tools_enabled=True, reasoning_mode="maybe", reasoning_effort=None
        )


def test_chat_session_extras_effort_can_be_set():
    extras = ChatSessionExtras(
        tools_enabled=False, reasoning_mode="on", reasoning_effort="medium"
    )
    assert extras.reasoning_effort == "medium"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$(pwd) pytest backend/modules/chat/tests/test_session_extras_dto.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Add the DTO to `shared/dtos/chat.py`**

```python
from typing import Literal
from pydantic import BaseModel


class ChatSessionExtras(BaseModel):
    tools_enabled: bool
    reasoning_mode: Literal["off", "on"]
    reasoning_effort: str | None = None
```

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=$(pwd) pytest backend/modules/chat/tests/test_session_extras_dto.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add shared/dtos/chat.py backend/modules/chat/tests/test_session_extras_dto.py
git commit -m "Add ChatSessionExtras DTO"
```

---

## Task 4: Refactor `CompletionRequest` to use extras

**Files:**
- Modify: `shared/dtos/inference.py:33-48`
- Test: `backend/modules/llm/tests/test_completion_request.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# backend/modules/llm/tests/test_completion_request.py
from shared.dtos.inference import CompletionRequest, CompletionMessage
from shared.dtos.chat import ChatSessionExtras
from shared.dtos.llm import ReasoningCapability, ToolCapability


def test_completion_request_carries_extras_and_capability():
    req = CompletionRequest(
        model="x:y",
        messages=[CompletionMessage(role="user", content="hi")],
        extras=ChatSessionExtras(
            tools_enabled=True, reasoning_mode="on", reasoning_effort="medium"
        ),
        reasoning=ReasoningCapability(kind="optional"),
        tools=ToolCapability(supported=True),
    )
    assert req.extras.reasoning_mode == "on"
    assert req.reasoning.kind == "optional"


def test_completion_request_default_extras_off_no_tools():
    req = CompletionRequest(
        model="x:y",
        messages=[CompletionMessage(role="user", content="hi")],
        reasoning=ReasoningCapability(kind="no_reasoning"),
        tools=ToolCapability(supported=False),
    )
    # Default extras: tools off, reasoning off
    assert req.extras.tools_enabled is False
    assert req.extras.reasoning_mode == "off"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$(pwd) pytest backend/modules/llm/tests/test_completion_request.py -v`
Expected: FAIL.

- [ ] **Step 3: Refactor `CompletionRequest`**

In `shared/dtos/inference.py`, replace lines 33–48 with:

```python
from shared.dtos.chat import ChatSessionExtras
from shared.dtos.llm import ReasoningCapability, ToolCapability


class CompletionRequest(BaseModel):
    model: str
    messages: list[CompletionMessage]
    temperature: float | None = None
    tools: list[ToolDefinition] | None = None
    # New capability + extras model. Replaces reasoning_enabled and
    # supports_reasoning. Adapter reads (capability, extras) and translates
    # to provider-specific request shapes.
    reasoning: ReasoningCapability
    tools_capability: ToolCapability
    extras: ChatSessionExtras = Field(
        default_factory=lambda: ChatSessionExtras(
            tools_enabled=False, reasoning_mode="off", reasoning_effort=None
        )
    )
    cache_hint: str | None = None
    anthropic_cache_ttl: Literal["off", "5m", "1h"] = "5m"
```

Note: kept the field name `tools` for the list of tool definitions (existing meaning, unrelated to capability), and renamed the capability field to `tools_capability` to avoid collision. Update the test accordingly:

```python
# in the test, change:
tools=ToolCapability(supported=True),
# to:
tools_capability=ToolCapability(supported=True),
```

(Re-edit the test file to match.)

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=$(pwd) pytest backend/modules/llm/tests/test_completion_request.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add shared/dtos/inference.py backend/modules/llm/tests/test_completion_request.py
git commit -m "Refactor CompletionRequest to carry capability and extras"
```

---

## Task 5: Add `ChatSessionExtrasUpdatedEvent` and topic

**Files:**
- Modify: `shared/topics.py`
- Modify: `shared/events/chat.py`
- Test: `backend/modules/chat/tests/test_session_extras_event.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# backend/modules/chat/tests/test_session_extras_event.py
from shared.events.chat import ChatSessionExtrasUpdatedEvent
from shared.dtos.chat import ChatSessionExtras
from shared.topics import Topics


def test_topic_constant_present():
    assert Topics.CHAT_SESSION_EXTRAS_UPDATED == "chat.session.extras.updated"


def test_event_carries_session_id_and_extras():
    extras = ChatSessionExtras(
        tools_enabled=True, reasoning_mode="off", reasoning_effort=None
    )
    ev = ChatSessionExtrasUpdatedEvent(
        id="evt1",
        type="chat.session.extras.updated",
        sequence=1,
        scope="session:s1",
        correlation_id="c1",
        timestamp="2026-05-09T10:00:00Z",
        payload={"session_id": "s1", "extras": extras.model_dump()},
        session_id="s1",
        extras=extras,
    )
    assert ev.session_id == "s1"
    assert ev.extras.tools_enabled is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$(pwd) pytest backend/modules/chat/tests/test_session_extras_event.py -v`
Expected: FAIL.

- [ ] **Step 3: Add topic and event**

In `shared/topics.py`, add `CHAT_SESSION_EXTRAS_UPDATED = "chat.session.extras.updated"` to the `Topics` class.

In `shared/events/chat.py`:

```python
from shared.dtos.chat import ChatSessionExtras
from shared.events.base import BaseEvent  # adjust import to your existing base

class ChatSessionExtrasUpdatedEvent(BaseEvent):
    session_id: str
    extras: ChatSessionExtras
```

(If `BaseEvent` lives elsewhere, adapt the import. Inspect `shared/events/` for the existing pattern and follow it.)

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=$(pwd) pytest backend/modules/chat/tests/test_session_extras_event.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add shared/topics.py shared/events/chat.py backend/modules/chat/tests/test_session_extras_event.py
git commit -m "Add ChatSessionExtrasUpdatedEvent and topic"
```

---

## Task 6: `model_capabilities.yaml` with day-1 entries

**Files:**
- Create: `backend/modules/llm/data/model_capabilities.yaml`

- [ ] **Step 1: Create the YAML directory and file**

```bash
mkdir -p backend/modules/llm/data
```

Write `backend/modules/llm/data/model_capabilities.yaml`:

```yaml
# Capability overrides per (adapter_type, model_id pattern).
# Matched in order; first match wins. Patterns use fnmatch semantics.
# Adapter heuristics are consulted only when no entry matches.

models:
  # Anthropic Claude family via OpenRouter
  - adapter: openrouter
    pattern: "anthropic/claude-sonnet-4-6*"
    reasoning:
      kind: optional
      effort: { buckets: [low, medium, high], default_bucket: medium }
      default_on: true
    tools: { supported: true, exclusive_with_reasoning: false }

  - adapter: openrouter
    pattern: "anthropic/claude-opus-4-7*"
    reasoning:
      kind: optional
      effort: { buckets: [low, medium, high], default_bucket: medium }
      default_on: true
    tools: { supported: true, exclusive_with_reasoning: false }

  # Same family via nano-gpt
  - adapter: nano_gpt
    pattern: "claude-sonnet-4-6*"
    reasoning:
      kind: optional
      effort: { buckets: [low, medium, high], default_bucket: medium }
      default_on: true
    tools: { supported: true, exclusive_with_reasoning: false }

  - adapter: nano_gpt
    pattern: "claude-opus-4-7*"
    reasoning:
      kind: optional
      effort: { buckets: [low, medium, high], default_bucket: medium }
      default_on: true
    tools: { supported: true, exclusive_with_reasoning: false }

  # OpenAI GPT-5 via OpenRouter
  - adapter: openrouter
    pattern: "openai/gpt-5*"
    reasoning:
      kind: optional
      effort: { buckets: [minimal, low, medium, high], default_bucket: medium }
      default_on: true
    tools: { supported: true, exclusive_with_reasoning: false }

  # GPT-5 via nano-gpt
  - adapter: nano_gpt
    pattern: "gpt-5*"
    reasoning:
      kind: optional
      effort: { buckets: [minimal, low, medium, high], default_bucket: medium }
      default_on: true
    tools: { supported: true, exclusive_with_reasoning: false }

  # DeepSeek V4 via OpenRouter
  - adapter: openrouter
    pattern: "deepseek/deepseek-v4*"
    reasoning:
      kind: optional
      effort: { buckets: [low, medium, high], default_bucket: medium }
      default_on: true
    tools: { supported: true, exclusive_with_reasoning: false }

  # DeepSeek V4 via nano-gpt
  - adapter: nano_gpt
    pattern: "deepseek-v4*"
    reasoning:
      kind: optional
      effort: { buckets: [low, medium, high], default_bucket: medium }
      default_on: true
    tools: { supported: true, exclusive_with_reasoning: false }
```

- [ ] **Step 2: Commit**

```bash
git add backend/modules/llm/data/model_capabilities.yaml
git commit -m "Add day-1 model capability overrides for Claude, GPT-5, DeepSeek V4"
```

---

## Task 7: `_capabilities.py` resolver module

**Files:**
- Create: `backend/modules/llm/_capabilities.py`
- Test: `backend/modules/llm/tests/test_capabilities.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# backend/modules/llm/tests/test_capabilities.py
from backend.modules.llm._capabilities import (
    resolve_capabilities,
    ResolvedCapabilities,
    CapabilityHint,
    DEFAULT_CAPABILITIES,
)
from shared.dtos.llm import ReasoningCapability, ToolCapability


class _StubAdapter:
    def __init__(self, hint=None):
        self._hint = hint

    def capability_hint(self, model_id):
        return self._hint


def test_yaml_match_returns_first_class():
    res = resolve_capabilities(
        adapter_type="openrouter",
        model_id="anthropic/claude-sonnet-4-6",
        adapter=_StubAdapter(),
    )
    assert isinstance(res, ResolvedCapabilities)
    assert res.first_class_support is True
    assert res.reasoning.kind == "optional"
    assert res.reasoning.effort.default_bucket == "medium"
    assert res.tools.supported is True


def test_adapter_hint_used_when_no_yaml_match():
    hint = CapabilityHint(
        reasoning=ReasoningCapability(kind="always_on"),
        tools=ToolCapability(supported=True),
        first_class_support=True,
    )
    res = resolve_capabilities(
        adapter_type="someadapter",
        model_id="some-unknown-model",
        adapter=_StubAdapter(hint=hint),
    )
    assert res.reasoning.kind == "always_on"
    assert res.first_class_support is True


def test_universal_fallback_when_nothing_matches():
    res = resolve_capabilities(
        adapter_type="someadapter",
        model_id="some-unknown-model",
        adapter=_StubAdapter(),
    )
    assert res.reasoning.kind == "optional"
    assert res.reasoning.effort is None
    assert res.tools.supported is True
    assert res.tools.exclusive_with_reasoning is False
    assert res.first_class_support is False


def test_wildcard_pattern_matches():
    # "anthropic/claude-sonnet-4-6*" should match the suffixed slug too
    res = resolve_capabilities(
        adapter_type="openrouter",
        model_id="anthropic/claude-sonnet-4-6:beta",
        adapter=_StubAdapter(),
    )
    assert res.first_class_support is True


def test_default_capabilities_constant_is_optional_no_effort():
    assert DEFAULT_CAPABILITIES.reasoning.kind == "optional"
    assert DEFAULT_CAPABILITIES.reasoning.effort is None
    assert DEFAULT_CAPABILITIES.tools.supported is True
    assert DEFAULT_CAPABILITIES.tools.exclusive_with_reasoning is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$(pwd) pytest backend/modules/llm/tests/test_capabilities.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write the resolver module**

Create `backend/modules/llm/_capabilities.py`:

```python
"""Capability resolution: YAML override → adapter heuristic → universal fallback.

See devdocs/specs/2026-05-09-llm-reasoning-tools-capabilities-design.md §5.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import yaml

from shared.dtos.llm import (
    ReasoningCapability,
    ReasoningEffortSpec,
    ToolCapability,
)


@dataclass(frozen=True)
class CapabilityHint:
    reasoning: ReasoningCapability
    tools: ToolCapability
    first_class_support: bool = False


@dataclass(frozen=True)
class ResolvedCapabilities:
    reasoning: ReasoningCapability
    tools: ToolCapability
    first_class_support: bool


class _AdapterCapabilityProvider(Protocol):
    def capability_hint(self, model_id: str) -> CapabilityHint | None: ...


_YAML_PATH = Path(__file__).parent / "data" / "model_capabilities.yaml"


@lru_cache(maxsize=1)
def _load_yaml() -> list[dict]:
    if not _YAML_PATH.exists():
        return []
    with _YAML_PATH.open() as f:
        data = yaml.safe_load(f) or {}
    return data.get("models", []) or []


def _yaml_lookup(adapter_type: str, model_id: str) -> CapabilityHint | None:
    for entry in _load_yaml():
        if entry.get("adapter") != adapter_type:
            continue
        pattern = entry.get("pattern", "")
        if not fnmatch.fnmatch(model_id, pattern):
            continue
        r = entry["reasoning"]
        effort = None
        if r.get("effort"):
            effort = ReasoningEffortSpec(
                buckets=r["effort"]["buckets"],
                default_bucket=r["effort"]["default_bucket"],
            )
        reasoning = ReasoningCapability(
            kind=r["kind"],
            effort=effort,
            default_on=r.get("default_on", True),
        )
        t = entry.get("tools", {})
        tools = ToolCapability(
            supported=t.get("supported", True),
            exclusive_with_reasoning=t.get("exclusive_with_reasoning", False),
        )
        return CapabilityHint(
            reasoning=reasoning, tools=tools, first_class_support=True
        )
    return None


DEFAULT_CAPABILITIES = ResolvedCapabilities(
    reasoning=ReasoningCapability(kind="optional"),
    tools=ToolCapability(supported=True, exclusive_with_reasoning=False),
    first_class_support=False,
)


def resolve_capabilities(
    *,
    adapter_type: str,
    model_id: str,
    adapter: _AdapterCapabilityProvider,
) -> ResolvedCapabilities:
    if hint := _yaml_lookup(adapter_type, model_id):
        return ResolvedCapabilities(
            reasoning=hint.reasoning,
            tools=hint.tools,
            first_class_support=True,
        )
    if hint := adapter.capability_hint(model_id):
        return ResolvedCapabilities(
            reasoning=hint.reasoning,
            tools=hint.tools,
            first_class_support=hint.first_class_support,
        )
    return DEFAULT_CAPABILITIES
```

Add `pyyaml` to both `pyproject.toml` (root) AND `backend/pyproject.toml` (Docker) per CLAUDE.md if not already pinned:

```toml
"pyyaml>=6.0",
```

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=$(pwd) pytest backend/modules/llm/tests/test_capabilities.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_capabilities.py backend/modules/llm/tests/test_capabilities.py pyproject.toml backend/pyproject.toml
git commit -m "Add capability resolver: YAML override > adapter hint > universal default"
```

---

## Task 8: `BaseAdapter.capability_hint()` interface

**Files:**
- Modify: `backend/modules/llm/_adapters/_base.py`
- Test: `backend/modules/llm/tests/test_base_adapter_capability_hint.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# backend/modules/llm/tests/test_base_adapter_capability_hint.py
from backend.modules.llm._adapters._base import BaseAdapter


def test_base_adapter_capability_hint_default_returns_none():
    # Concrete subclasses opt in. Default = None means "fall through to
    # universal default capabilities".
    class _Adapter(BaseAdapter):
        async def fetch_models(self): ...
        async def stream_completion(self, request, *, on_event): ...

    a = _Adapter.__new__(_Adapter)  # bypass init for unit test
    assert a.capability_hint("anything") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$(pwd) pytest backend/modules/llm/tests/test_base_adapter_capability_hint.py -v`
Expected: FAIL.

- [ ] **Step 3: Add the method to `BaseAdapter`**

Edit `backend/modules/llm/_adapters/_base.py`. Add:

```python
def capability_hint(self, model_id: str):
    """Adapter-specific capability override.

    Default returns None — the resolver falls through to the universal
    default. Adapters that hand-curate model handling (xAI slug-pair table,
    future Mistral baked-in variants) override this to return a CapabilityHint
    with first_class_support=True.

    Adapters using only generic heuristics (OpenRouter supported_parameters
    inspection, Novita features array) may return a CapabilityHint with
    first_class_support=False — heuristic guidance, not curated.
    """
    return None
```

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=$(pwd) pytest backend/modules/llm/tests/test_base_adapter_capability_hint.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_base.py backend/modules/llm/tests/test_base_adapter_capability_hint.py
git commit -m "Add BaseAdapter.capability_hint() default returning None"
```

---

## Task 9: `ollama_http` translation + capability_hint + ModelMetaDto build

**Files:**
- Modify: `backend/modules/llm/_adapters/_ollama_http.py`
- Test: `backend/modules/llm/tests/test_translation_ollama.py` (new)

- [ ] **Step 1: Write the failing translation tests**

```python
# backend/modules/llm/tests/test_translation_ollama.py
from shared.dtos.inference import CompletionRequest, CompletionMessage
from shared.dtos.chat import ChatSessionExtras
from shared.dtos.llm import ReasoningCapability, ToolCapability
from backend.modules.llm._adapters._ollama_http import build_request_body


def _req(extras: ChatSessionExtras, reasoning: ReasoningCapability) -> CompletionRequest:
    return CompletionRequest(
        model="llama3.3:70b",
        messages=[CompletionMessage(role="user", content="hi")],
        reasoning=reasoning,
        tools_capability=ToolCapability(supported=True),
        extras=extras,
    )


def test_ollama_no_reasoning_model_omits_thinking_field():
    req = _req(
        ChatSessionExtras(tools_enabled=True, reasoning_mode="off", reasoning_effort=None),
        ReasoningCapability(kind="no_reasoning"),
    )
    body = build_request_body(req)
    assert "think" not in body  # ollama uses 'think' for thinking models


def test_ollama_optional_reasoning_on_sets_think_true():
    req = _req(
        ChatSessionExtras(tools_enabled=True, reasoning_mode="on", reasoning_effort=None),
        ReasoningCapability(kind="optional"),
    )
    body = build_request_body(req)
    assert body.get("think") is True


def test_ollama_optional_reasoning_off_sets_think_false_explicitly():
    req = _req(
        ChatSessionExtras(tools_enabled=True, reasoning_mode="off", reasoning_effort=None),
        ReasoningCapability(kind="optional"),
    )
    body = build_request_body(req)
    assert body.get("think") is False  # always-explicit rule
```

- [ ] **Step 2: Run tests to verify fail**

Run: `PYTHONPATH=$(pwd) pytest backend/modules/llm/tests/test_translation_ollama.py -v`
Expected: FAIL (`build_request_body` missing or wrong shape).

- [ ] **Step 3: Update the ollama adapter**

In `backend/modules/llm/_adapters/_ollama_http.py`:

1. Find the existing function/method that constructs the request body. Refactor (or extract) into a `build_request_body(request: CompletionRequest) -> dict` pure function so it can be unit-tested.
2. Replace the old `request.reasoning_enabled` / `request.supports_reasoning` logic with:

```python
def build_request_body(request: CompletionRequest) -> dict:
    body = {
        "model": request.model,
        "messages": [m.model_dump() for m in request.messages],
        "stream": True,
    }
    if request.temperature is not None:
        body["options"] = {"temperature": request.temperature}
    if request.tools and request.extras.tools_enabled:
        body["tools"] = [t.model_dump() for t in request.tools]
    # Reasoning translation — always explicit when capability is "optional".
    if request.reasoning.kind == "optional":
        body["think"] = (request.extras.reasoning_mode == "on")
    # no_reasoning: don't send think; always_on: ollama models that always
    # think don't need a flag either (they think regardless).
    return body
```

3. Update the existing send-path to call `build_request_body(request)`.

4. Update the model fetch path: when assembling `ModelMetaDto`, call `resolve_capabilities(adapter_type="ollama", model_id=..., adapter=self)` and populate `reasoning`, `tools`, `first_class_support` from the result.

5. (Optional, for now) `capability_hint` may return `None` — let YAML / heuristic / default handle it.

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=$(pwd) pytest backend/modules/llm/tests/test_translation_ollama.py -v`
Expected: 3 passed.

Also run the existing ollama tests to confirm no regressions:
Run: `PYTHONPATH=$(pwd) pytest backend/modules/llm/tests/ -v -k "ollama" --ignore=backend/modules/llm/tests/test_capabilities.py`

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_ollama_http.py backend/modules/llm/tests/test_translation_ollama.py
git commit -m "ollama_http: integrate capability resolver and extras-based translation"
```

---

## Task 10: `nano_gpt_http` translation + capability_hint

**Files:**
- Modify: `backend/modules/llm/_adapters/_nano_gpt_http.py`
- Test: `backend/modules/llm/tests/test_translation_nano_gpt.py` (new)

The nano-gpt adapter has three dispatch modes (`slug` / `flag` / `none`) handled via `_pair_map.py`. Preserve that mapping; the translation layer only changes how `reasoning_mode` and `reasoning_effort` flow into the dispatch decision and body fields.

- [ ] **Step 1: Write the failing translation tests**

```python
# backend/modules/llm/tests/test_translation_nano_gpt.py
from shared.dtos.inference import CompletionRequest, CompletionMessage
from shared.dtos.chat import ChatSessionExtras
from shared.dtos.llm import (
    ReasoningCapability, ReasoningEffortSpec, ToolCapability,
)
from backend.modules.llm._adapters._nano_gpt_http import build_request_body


def _req(model, extras, reasoning, tool_supported=True):
    return CompletionRequest(
        model=model,
        messages=[CompletionMessage(role="user", content="hi")],
        reasoning=reasoning,
        tools_capability=ToolCapability(supported=tool_supported),
        extras=extras,
    )


def test_nano_gpt_flag_mode_reasoning_on_sends_enabled_true():
    # Use a model that's in flag-mode pair_map, e.g. an OpenRouter-style slug
    req = _req(
        "claude-sonnet-4-6",
        ChatSessionExtras(tools_enabled=True, reasoning_mode="on", reasoning_effort="medium"),
        ReasoningCapability(
            kind="optional",
            effort=ReasoningEffortSpec(buckets=["low", "medium", "high"], default_bucket="medium"),
        ),
    )
    body, slug = build_request_body(req)
    assert body.get("reasoning", {}).get("enabled") is True


def test_nano_gpt_flag_mode_reasoning_off_sends_enabled_false_explicit():
    req = _req(
        "claude-sonnet-4-6",
        ChatSessionExtras(tools_enabled=True, reasoning_mode="off", reasoning_effort=None),
        ReasoningCapability(kind="optional"),
    )
    body, slug = build_request_body(req)
    assert body.get("reasoning", {}).get("enabled") is False


def test_nano_gpt_effort_passed_when_set():
    req = _req(
        "gpt-5",
        ChatSessionExtras(tools_enabled=False, reasoning_mode="on", reasoning_effort="high"),
        ReasoningCapability(
            kind="optional",
            effort=ReasoningEffortSpec(
                buckets=["minimal", "low", "medium", "high"], default_bucket="medium",
            ),
        ),
    )
    body, slug = build_request_body(req)
    assert body.get("reasoning", {}).get("effort") == "high"
```

- [ ] **Step 2: Run tests to verify fail**

Run: `PYTHONPATH=$(pwd) pytest backend/modules/llm/tests/test_translation_nano_gpt.py -v`
Expected: FAIL.

- [ ] **Step 3: Update the nano-gpt adapter**

In `backend/modules/llm/_adapters/_nano_gpt_http.py`:

1. Refactor request-body assembly into `build_request_body(request: CompletionRequest) -> tuple[dict, str]` returning `(body, dispatched_slug)`. Slug-mode dispatches return the swapped slug; flag/none return the original.
2. Read `request.extras.reasoning_mode` and `request.extras.reasoning_effort`. Slug-mode picks the slug variant from `_pair_map`. Flag-mode emits `body["reasoning"] = {"enabled": <bool>, ...}` plus `"effort"` when `reasoning_effort` is set. None-mode drops the field.
3. Update model fetch path: assemble `ModelMetaDto` with `resolve_capabilities(adapter_type="nano_gpt", ...)`. The adapter's `capability_hint(model_id)` consults `_pair_map.py` — when a model is in `slug`/`flag` mode and **not** YAML-covered, return a `CapabilityHint(kind="optional", first_class_support=False)`. This preserves "best-effort" recognition without claiming first-class.

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=$(pwd) pytest backend/modules/llm/tests/test_translation_nano_gpt.py -v`
Expected: 3 passed.

Run existing nano-gpt tests for regressions:
`PYTHONPATH=$(pwd) pytest backend/modules/llm/tests/ -v -k "nano_gpt" --ignore=backend/modules/llm/tests/test_capabilities.py`

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_nano_gpt_http.py backend/modules/llm/tests/test_translation_nano_gpt.py
git commit -m "nano_gpt_http: integrate capability resolver and extras-based translation"
```

---

## Task 11: `novita_http` translation + capability_hint

**Files:**
- Modify: `backend/modules/llm/_adapters/_novita_http.py`
- Test: `backend/modules/llm/tests/test_translation_novita.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
# backend/modules/llm/tests/test_translation_novita.py
from shared.dtos.inference import CompletionRequest, CompletionMessage
from shared.dtos.chat import ChatSessionExtras
from shared.dtos.llm import ReasoningCapability, ReasoningEffortSpec, ToolCapability
from backend.modules.llm._adapters._novita_http import build_request_body


def _req(extras, reasoning):
    return CompletionRequest(
        model="some/model",
        messages=[CompletionMessage(role="user", content="hi")],
        reasoning=reasoning,
        tools_capability=ToolCapability(supported=True),
        extras=extras,
    )


def test_novita_optional_reasoning_off_sends_enabled_false_explicit():
    req = _req(
        ChatSessionExtras(tools_enabled=False, reasoning_mode="off", reasoning_effort=None),
        ReasoningCapability(kind="optional"),
    )
    body = build_request_body(req)
    assert body.get("reasoning", {}).get("enabled") is False


def test_novita_optional_reasoning_on_with_effort():
    req = _req(
        ChatSessionExtras(tools_enabled=True, reasoning_mode="on", reasoning_effort="medium"),
        ReasoningCapability(
            kind="optional",
            effort=ReasoningEffortSpec(buckets=["low", "medium", "high"], default_bucket="medium"),
        ),
    )
    body = build_request_body(req)
    assert body["reasoning"]["effort"] == "medium"


def test_novita_no_reasoning_model_no_reasoning_field():
    req = _req(
        ChatSessionExtras(tools_enabled=True, reasoning_mode="off", reasoning_effort=None),
        ReasoningCapability(kind="no_reasoning"),
    )
    body = build_request_body(req)
    assert "reasoning" not in body
```

- [ ] **Step 2: Run tests to verify fail**

Run: `PYTHONPATH=$(pwd) pytest backend/modules/llm/tests/test_translation_novita.py -v`

- [ ] **Step 3: Update the novita adapter**

Mirror Task 10's pattern: extract `build_request_body`, replace the old `request.supports_reasoning and not request.reasoning_enabled` block (currently around `_novita_http.py:294`) with:

```python
def build_request_body(request: CompletionRequest) -> dict:
    body = {
        "model": request.model,
        "messages": [m.model_dump() for m in request.messages],
        "stream": True,
    }
    if request.temperature is not None:
        body["temperature"] = request.temperature
    if request.tools and request.extras.tools_enabled:
        body["tools"] = [t.model_dump() for t in request.tools]
    if request.reasoning.kind == "optional":
        reasoning_obj = {"enabled": request.extras.reasoning_mode == "on"}
        if request.extras.reasoning_effort:
            reasoning_obj["effort"] = request.extras.reasoning_effort
        body["reasoning"] = reasoning_obj
    return body
```

Update the model fetch path to call `resolve_capabilities` and populate the new `ModelMetaDto` fields. Keep the existing `_features` parsing as `capability_hint` body (returning `CapabilityHint(first_class_support=False)`).

- [ ] **Step 4: Run tests**

`PYTHONPATH=$(pwd) pytest backend/modules/llm/tests/test_translation_novita.py -v`
Plus regressions: `pytest backend/modules/llm/tests/ -v -k "novita"`

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_novita_http.py backend/modules/llm/tests/test_translation_novita.py
git commit -m "novita_http: integrate capability resolver and extras-based translation"
```

---

## Task 12: `openrouter_http` translation + capability_hint

**Files:**
- Modify: `backend/modules/llm/_adapters/_openrouter_http.py`
- Test: `backend/modules/llm/tests/test_translation_openrouter.py` (new)

Mirror Task 11. Key difference for OpenRouter: also supports `reasoning.exclude` upstream, but per spec §2 non-goals, **we do not use `exclude` to fake an off state**. Off means `enabled: false`.

- [ ] **Step 1: Write tests** — same shape as Novita, model `"anthropic/claude-sonnet-4-6"`, assert `body["reasoning"]` has `enabled` and (when set) `effort`.

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Update adapter.** Replace the `if request.supports_reasoning and not request.reasoning_enabled` block at `_openrouter_http.py:353` with the same pattern as Novita. Update model fetch path to call resolver. Existing `_supports(params, "reasoning", "include_reasoning")` heuristic logic moves into `capability_hint` returning `CapabilityHint(first_class_support=False)`.

- [ ] **Step 4: Run tests + regressions.**

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_openrouter_http.py backend/modules/llm/tests/test_translation_openrouter.py
git commit -m "openrouter_http: integrate capability resolver and extras-based translation"
```

---

## Task 13: xAI + Mistral conservative-default updates (out-of-scope adapters)

**Files:**
- Modify: `backend/modules/llm/_adapters/_xai_http.py`
- Modify: `backend/modules/llm/_adapters/_mistral_http.py`
- Test: `backend/modules/llm/tests/test_xai_mistral_minimal_compat.py` (new)

These adapters get a follow-up spec for premium handling. For this iteration: just emit the new `ModelMetaDto` fields with conservative defaults so the rest of the system works. Keep their existing reasoning logic as-is.

- [ ] **Step 1: Write the failing test**

```python
# backend/modules/llm/tests/test_xai_mistral_minimal_compat.py
from shared.dtos.llm import ReasoningCapability, ToolCapability


def test_xai_meta_carries_new_capability_fields(monkeypatch):
    # Build a ModelMetaDto via the xAI adapter's existing model meta path,
    # mocking only the upstream HTTP. Assert reasoning + tools are present.
    from backend.modules.llm._adapters._xai_http import _build_model_meta
    meta = _build_model_meta(
        connection_id="c1",
        connection_slug="xai",
        model_id="grok-4-1-fast",
    )
    assert isinstance(meta.reasoning, ReasoningCapability)
    assert isinstance(meta.tools, ToolCapability)


def test_mistral_meta_carries_new_capability_fields():
    from backend.modules.llm._adapters._mistral_http import _build_model_meta
    meta = _build_model_meta(
        connection_id="c1",
        connection_slug="mistral",
        model_id="magistral-medium",
    )
    assert isinstance(meta.reasoning, ReasoningCapability)
    assert isinstance(meta.tools, ToolCapability)
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Update the two adapters**

In `_xai_http.py`: where `ModelMetaDto(...)` is constructed (search for `supports_reasoning=True` around line 409 and similar sites), add:
```python
reasoning=ReasoningCapability(
    kind="optional",  # current xAI behaviour: slug-pair gives optional toggle
    default_on=True,
),
tools=ToolCapability(supported=True, exclusive_with_reasoning=False),
first_class_support=False,  # follow-up spec promotes this to True
```

Keep the existing `reasoning_slug` / `non_reasoning_slug` dispatch logic untouched. Translation: when the adapter receives a `CompletionRequest`, translate via `request.extras.reasoning_mode == "on"` instead of the old `request.reasoning_enabled`.

In `_mistral_http.py`: where `ModelMetaDto(...)` is constructed, similar change. Translation: read `request.extras.reasoning_mode` instead of `request.reasoning_enabled`. Magistral has reasoning baked-in — emit `kind="optional"` with `default_on=True`. Non-reasoning Mistral models emit `kind="no_reasoning"`.

- [ ] **Step 4: Run tests + xai/mistral regressions**

`PYTHONPATH=$(pwd) pytest backend/modules/llm/tests/ -v -k "xai or mistral"`

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_xai_http.py backend/modules/llm/_adapters/_mistral_http.py backend/modules/llm/tests/test_xai_mistral_minimal_compat.py
git commit -m "xAI + Mistral: emit new capability fields with conservative defaults (premium follow-up pending)"
```

---

## Task 14: `ChatSessionDocument.extras` storage + repository

**Files:**
- Modify: `backend/modules/chat/_models.py:7+`
- Modify: `backend/modules/chat/_repository.py`
- Test: `backend/modules/chat/tests/test_session_extras_storage.py` (new — pure-Pydantic, no live DB)

- [ ] **Step 1: Write the failing test**

```python
# backend/modules/chat/tests/test_session_extras_storage.py
from backend.modules.chat._models import ChatSessionDocument
from shared.dtos.chat import ChatSessionExtras


def test_chat_session_document_extras_default_none():
    # Default None means "compute from model capability on first read"
    doc = ChatSessionDocument(
        _id="s1", user_id="u1", title=None, created_at="2026-05-09T10:00:00Z",
        updated_at="2026-05-09T10:00:00Z",
        # ... whatever existing required fields the model has — fill with minimums
    )
    assert doc.extras is None


def test_chat_session_document_extras_round_trips():
    extras = ChatSessionExtras(
        tools_enabled=True, reasoning_mode="on", reasoning_effort="medium"
    )
    doc = ChatSessionDocument(
        _id="s1", user_id="u1", title=None, created_at="2026-05-09T10:00:00Z",
        updated_at="2026-05-09T10:00:00Z",
        extras=extras,
    )
    payload = doc.model_dump()
    assert payload["extras"]["reasoning_mode"] == "on"
```

(Adapt the `ChatSessionDocument(...)` construction to whatever required fields the existing model has — read `backend/modules/chat/_models.py:7` first.)

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Add `extras` to `ChatSessionDocument`**

In `backend/modules/chat/_models.py`:

```python
from shared.dtos.chat import ChatSessionExtras

class ChatSessionDocument(BaseModel):
    # ... existing fields ...
    extras: ChatSessionExtras | None = None
```

- [ ] **Step 4: Add repository helpers**

In `backend/modules/chat/_repository.py` (near `update_session_title` around line 424), add:

```python
async def update_session_extras(
    self, session_id: str, user_id: str, extras: ChatSessionExtras
) -> dict | None:
    now = datetime.now(timezone.utc)
    await self._sessions.update_one(
        {"_id": session_id, "user_id": user_id},
        {"$set": {"extras": extras.model_dump(), "updated_at": now}},
    )
    return await self._sessions.find_one({"_id": session_id, "user_id": user_id})
```

- [ ] **Step 5: Run tests + commit**

`PYTHONPATH=$(pwd) pytest backend/modules/chat/tests/test_session_extras_storage.py -v`

```bash
git add backend/modules/chat/_models.py backend/modules/chat/_repository.py backend/modules/chat/tests/test_session_extras_storage.py
git commit -m "ChatSession: add extras field + repository update method"
```

---

## Task 15: REST endpoint + model-switch remap function

**Files:**
- Create: `backend/modules/chat/_extras_remap.py`
- Modify: `backend/modules/chat/_handlers.py`
- Test: `backend/modules/chat/tests/test_extras_remap.py` (new)
- Test: `backend/modules/chat/tests/test_extras_endpoint.py` (new — uses TestClient, no live DB)

- [ ] **Step 1: Write the failing remap tests**

```python
# backend/modules/chat/tests/test_extras_remap.py
from shared.dtos.chat import ChatSessionExtras
from shared.dtos.llm import (
    ReasoningCapability, ReasoningEffortSpec, ToolCapability,
)
from backend.modules.chat._extras_remap import remap_extras_for_capability


def _cap(kind, effort_buckets=None, tool_supported=True, mutex=False):
    effort = (
        ReasoningEffortSpec(buckets=effort_buckets, default_bucket=effort_buckets[len(effort_buckets) // 2])
        if effort_buckets else None
    )
    return (
        ReasoningCapability(kind=kind, effort=effort),
        ToolCapability(supported=tool_supported, exclusive_with_reasoning=mutex),
    )


def test_remap_preserves_tools_when_supported():
    old = ChatSessionExtras(tools_enabled=True, reasoning_mode="on", reasoning_effort="high")
    new_r, new_t = _cap("optional", ["low", "medium", "high"])
    out = remap_extras_for_capability(old, new_r, new_t)
    assert out.tools_enabled is True
    assert out.reasoning_mode == "on"
    assert out.reasoning_effort == "high"


def test_remap_drops_tools_when_unsupported():
    old = ChatSessionExtras(tools_enabled=True, reasoning_mode="off", reasoning_effort=None)
    new_r, new_t = _cap("optional", tool_supported=False)
    out = remap_extras_for_capability(old, new_r, new_t)
    assert out.tools_enabled is False


def test_remap_forces_reasoning_on_for_always_on():
    old = ChatSessionExtras(tools_enabled=True, reasoning_mode="off", reasoning_effort=None)
    new_r, new_t = _cap("always_on")
    out = remap_extras_for_capability(old, new_r, new_t)
    assert out.reasoning_mode == "on"


def test_remap_forces_reasoning_off_for_no_reasoning():
    old = ChatSessionExtras(tools_enabled=True, reasoning_mode="on", reasoning_effort="medium")
    new_r, new_t = _cap("no_reasoning")
    out = remap_extras_for_capability(old, new_r, new_t)
    assert out.reasoning_mode == "off"
    assert out.reasoning_effort is None


def test_remap_resets_effort_when_bucket_not_in_new_capability():
    old = ChatSessionExtras(tools_enabled=False, reasoning_mode="on", reasoning_effort="minimal")
    new_r, new_t = _cap("optional", ["low", "medium", "high"])  # no "minimal"
    out = remap_extras_for_capability(old, new_r, new_t)
    assert out.reasoning_effort == "medium"  # default_bucket of new spec


def test_remap_tools_win_when_mutex_violated():
    old = ChatSessionExtras(tools_enabled=True, reasoning_mode="on", reasoning_effort="medium")
    new_r, new_t = _cap("optional", ["low", "medium", "high"], mutex=True)
    out = remap_extras_for_capability(old, new_r, new_t)
    assert out.tools_enabled is True
    assert out.reasoning_mode == "off"  # tools win on conflict
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement `_extras_remap.py`**

```python
# backend/modules/chat/_extras_remap.py
from shared.dtos.chat import ChatSessionExtras
from shared.dtos.llm import ReasoningCapability, ToolCapability


def remap_extras_for_capability(
    old: ChatSessionExtras,
    reasoning: ReasoningCapability,
    tools: ToolCapability,
) -> ChatSessionExtras:
    """Apply spec §6.5 mapping: preserve where possible, tools win on conflict."""
    # Tools: preserve if new model supports; else False
    tools_enabled = old.tools_enabled if tools.supported else False

    # Reasoning mode
    if reasoning.kind == "always_on":
        mode = "on"
    elif reasoning.kind == "no_reasoning":
        mode = "off"
    else:
        mode = old.reasoning_mode

    # Effort: preserve if bucket exists in new spec; else default; else None
    if reasoning.effort and old.reasoning_effort in reasoning.effort.buckets:
        effort = old.reasoning_effort
    elif reasoning.effort:
        effort = reasoning.effort.default_bucket
    else:
        effort = None

    # No effort when reasoning is off
    if mode == "off":
        effort = None

    # Mutex: tools win
    if tools.exclusive_with_reasoning and tools_enabled and mode == "on":
        mode = "off"
        effort = None

    return ChatSessionExtras(
        tools_enabled=tools_enabled, reasoning_mode=mode, reasoning_effort=effort,
    )
```

- [ ] **Step 4: Add the REST endpoint**

In `backend/modules/chat/_handlers.py`, add a new route:

```python
from shared.dtos.chat import ChatSessionExtras
from backend.modules.llm._capabilities import resolve_capabilities

@router.patch("/sessions/{session_id}/extras")
async def patch_session_extras(
    session_id: str,
    extras: ChatSessionExtras,
    user=Depends(current_user),  # use existing auth dep
):
    # 1. Load the session, look up its current model
    session = await chat_repo.get_session(session_id, user["id"])
    if not session:
        raise HTTPException(404)
    # 2. Resolve capability for current model
    model_unique_id = session.get("model_unique_id")  # or wherever it lives
    # adapter+model_id parse from unique_id (slug:model_id)
    ...  # split logic per existing pattern; reuse helper if available
    capability = resolve_capabilities(adapter_type=..., model_id=..., adapter=...)
    # 3. Validate
    if extras.reasoning_mode == "on" and capability.reasoning.kind == "no_reasoning":
        raise HTTPException(400, "model does not support reasoning")
    if extras.tools_enabled and not capability.tools.supported:
        raise HTTPException(400, "model does not support tools")
    if (extras.tools_enabled and extras.reasoning_mode == "on"
            and capability.tools.exclusive_with_reasoning):
        raise HTTPException(400, "tools and reasoning are mutually exclusive for this model")
    if (extras.reasoning_effort is not None and capability.reasoning.effort is not None
            and extras.reasoning_effort not in capability.reasoning.effort.buckets):
        raise HTTPException(400, "invalid reasoning_effort bucket")
    # 4. Persist
    updated = await chat_repo.update_session_extras(session_id, user["id"], extras)
    # 5. Broadcast event (Task 18)
    await _broadcast_extras_updated(session_id, extras, user["id"])
    return {"extras": extras.model_dump()}
```

(Inspect the existing handler patterns in `_handlers.py` for the actual auth dep, repo wiring, error helpers, etc., and follow them.)

- [ ] **Step 5: Run tests + commit**

```bash
PYTHONPATH=$(pwd) pytest backend/modules/chat/tests/test_extras_remap.py -v
```

```bash
git add backend/modules/chat/_extras_remap.py backend/modules/chat/_handlers.py backend/modules/chat/tests/test_extras_remap.py
git commit -m "Add session-extras remap function and PATCH endpoint with validation"
```

---

## Task 16: Wire extras through chat orchestrator + WS handlers

**Files:**
- Modify: `backend/modules/chat/_orchestrator.py:661-884`
- Modify: `backend/modules/chat/_handlers_ws.py:662-701`
- Modify: `backend/modules/chat/_prompt_assembler.py:78`
- Modify: `backend/modules/chat/_soft_cot.py:42`
- Modify: `backend/modules/chat/_vision_fallback.py:82`

This task migrates internal call-sites from `persona.reasoning_enabled` to `session.extras`.

- [ ] **Step 1: Add `_default_extras_for_capability` helper**

Create or extend `backend/modules/chat/_extras_remap.py`:

```python
from backend.modules.llm._capabilities import ResolvedCapabilities


def default_extras_for_capability(cap: ResolvedCapabilities) -> ChatSessionExtras:
    """Spec §4.5 — initial defaults for a fresh chat session given the model's capability."""
    has_mutex = cap.tools.exclusive_with_reasoning
    tools_supported = cap.tools.supported
    kind = cap.reasoning.kind

    # Defaults table from spec §4.5:
    if kind == "no_reasoning":
        return ChatSessionExtras(
            tools_enabled=tools_supported, reasoning_mode="off", reasoning_effort=None,
        )
    if kind == "always_on":
        effort = cap.reasoning.effort.default_bucket if cap.reasoning.effort else None
        return ChatSessionExtras(
            tools_enabled=tools_supported and not has_mutex,
            reasoning_mode="on",
            reasoning_effort=effort,
        )
    # optional
    if has_mutex:
        # Mutex default: tools on, reasoning off
        return ChatSessionExtras(
            tools_enabled=tools_supported, reasoning_mode="off", reasoning_effort=None,
        )
    # No mutex: both on, effort = default bucket if any
    effort = cap.reasoning.effort.default_bucket if cap.reasoning.effort else None
    return ChatSessionExtras(
        tools_enabled=tools_supported, reasoning_mode="on", reasoning_effort=effort,
    )
```

Add corresponding tests in `backend/modules/chat/tests/test_extras_remap.py`:

```python
from backend.modules.chat._extras_remap import default_extras_for_capability
from backend.modules.llm._capabilities import ResolvedCapabilities


def test_defaults_optional_no_mutex_both_on():
    cap = ResolvedCapabilities(
        reasoning=ReasoningCapability(kind="optional", effort=ReasoningEffortSpec(buckets=["low","medium","high"], default_bucket="medium")),
        tools=ToolCapability(supported=True),
        first_class_support=True,
    )
    e = default_extras_for_capability(cap)
    assert e.tools_enabled is True
    assert e.reasoning_mode == "on"
    assert e.reasoning_effort == "medium"


def test_defaults_optional_with_mutex_tools_on_reasoning_off():
    cap = ResolvedCapabilities(
        reasoning=ReasoningCapability(kind="optional"),
        tools=ToolCapability(supported=True, exclusive_with_reasoning=True),
        first_class_support=True,
    )
    e = default_extras_for_capability(cap)
    assert e.tools_enabled is True
    assert e.reasoning_mode == "off"


def test_defaults_always_on_no_mutex():
    cap = ResolvedCapabilities(
        reasoning=ReasoningCapability(kind="always_on"),
        tools=ToolCapability(supported=True),
        first_class_support=True,
    )
    e = default_extras_for_capability(cap)
    assert e.reasoning_mode == "on"
    assert e.tools_enabled is True
```

Run: `PYTHONPATH=$(pwd) pytest backend/modules/chat/tests/test_extras_remap.py -v`. Expected: 9 passed (6 from Task 15 + 3 new).

- [ ] **Step 2: Update the orchestrator**

In `_orchestrator.py:661-674`:

Replace the existing reasoning_enabled resolution (lines 661-664) with:

```python
from backend.modules.chat._extras_remap import default_extras_for_capability
from backend.modules.llm._capabilities import resolve_capabilities

# resolve capability for the session's current model
adapter_type, model_id = session["model_unique_id"].split(":", 1)
adapter = llm_module.get_adapter_by_slug(adapter_type)  # use existing helper
capability = resolve_capabilities(
    adapter_type=adapter_type, model_id=model_id, adapter=adapter,
)

# read extras from session, fall back to defaults if None (legacy session)
raw = session.get("extras")
extras = (
    ChatSessionExtras(**raw) if raw else default_extras_for_capability(capability)
)
```

And in the `CompletionRequest` build (around line 884), pass:
```python
extras=extras,
reasoning=capability.reasoning,
tools_capability=capability.tools,
```

instead of `reasoning_enabled=reasoning_enabled`.

- [ ] **Step 3: Update the WS handler**

In `_handlers_ws.py:662`:

Replace:
```python
reasoning_enabled_for_call = persona.get("reasoning_enabled", False)
```

With:
```python
from backend.modules.chat._extras_remap import default_extras_for_capability

raw = session.get("extras")
extras = ChatSessionExtras(**raw) if raw else default_extras_for_capability(capability)
reasoning_enabled_for_call = extras.reasoning_mode == "on"  # for any callers still expecting bool
```

Then pass `extras` into the orchestrator/prompt-assembler/vision-fallback calls.

- [ ] **Step 4: Update the prompt assembler / soft-cot / vision-fallback**

These three files take `reasoning_enabled_for_call` (or `reasoning_enabled`). Update their signatures to accept `extras: ChatSessionExtras` and derive the bool internally:

```python
def is_soft_cot_active(soft_cot_enabled, supports_reasoning, extras):
    return soft_cot_enabled and supports_reasoning and extras.reasoning_mode == "off"
```

(Adapt to the actual signatures — read each file first.)

- [ ] **Step 5: Run all chat-module tests**

```bash
PYTHONPATH=$(pwd) pytest backend/modules/chat/tests/ -v --ignore=backend/modules/chat/tests/test_<mongo>.py
```

(Replace `<mongo>` with the actual MongoDB-using test files; check the four-file exclusion list.)

- [ ] **Step 6: Commit**

```bash
git add backend/modules/chat/_orchestrator.py backend/modules/chat/_handlers_ws.py backend/modules/chat/_prompt_assembler.py backend/modules/chat/_soft_cot.py backend/modules/chat/_vision_fallback.py
git commit -m "Wire ChatSessionExtras through orchestrator, handlers, prompt assembler"
```

---

## Task 17: Persona backend cleanup — remove `reasoning_enabled` from active reads

**Files:**
- Modify: `shared/dtos/persona.py:65,112` (keep field as `default=False` for backwards-read of legacy DB documents; remove from active write paths)

- [ ] **Step 1: Verify the field is no longer read in code**

Run: `rg "persona.*reasoning_enabled|reasoning_enabled.*persona" backend/ --type py`
Expected: only `shared/dtos/persona.py` references should remain after Task 16.

- [ ] **Step 2: Mark the field as deprecated in the DTO**

In `shared/dtos/persona.py`:

```python
# DEPRECATED 2026-05-09: per-persona reasoning_enabled removed in favour of
# per-session ChatSessionExtras. Field kept for backwards-compatible reads
# of existing persona documents (CLAUDE.md §Data-Model Migrations); no
# new writes from the editor or backend code paths.
reasoning_enabled: bool = False  # was previously required; default added for legacy reads
```

- [ ] **Step 3: Run any persona-related tests**

```bash
PYTHONPATH=$(pwd) pytest backend/modules/persona/tests/ -v
```

- [ ] **Step 4: Commit**

```bash
git add shared/dtos/persona.py
git commit -m "Persona DTO: deprecate reasoning_enabled field (kept for legacy reads only)"
```

---

## Task 18: WebSocket broadcast for `ChatSessionExtrasUpdatedEvent`

**Files:**
- Modify: `backend/modules/chat/_handlers.py` (the PATCH endpoint from Task 15)
- Modify: wherever the existing chat-event broadcaster lives (search `event_bus.publish` in chat module)

- [ ] **Step 1: Find the existing publish pattern**

```bash
rg -n "event_bus.publish.*chat" backend/modules/chat/ | head
```

Identify the helper used by other chat events (e.g. `ChatSessionStartedEvent`).

- [ ] **Step 2: Implement `_broadcast_extras_updated`**

Add to `_handlers.py` (or the appropriate helper module if your codebase has one):

```python
import uuid
from datetime import datetime, timezone
from shared.events.chat import ChatSessionExtrasUpdatedEvent
from shared.topics import Topics


async def _broadcast_extras_updated(session_id: str, extras: ChatSessionExtras, user_id: str):
    event = ChatSessionExtrasUpdatedEvent(
        id=str(uuid.uuid4()),
        type=Topics.CHAT_SESSION_EXTRAS_UPDATED,
        sequence=...,  # next sequence per session scope (use existing helper)
        scope=f"session:{session_id}",
        correlation_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc),
        payload={"session_id": session_id, "extras": extras.model_dump()},
        session_id=session_id,
        extras=extras,
    )
    await event_bus.publish(Topics.CHAT_SESSION_EXTRAS_UPDATED, event, target_user=user_id)
```

(Match the actual `event_bus.publish` signature in this repo — inspect existing chat events first.)

- [ ] **Step 3: Wire the call into the PATCH handler from Task 15**

(Already added a stub `await _broadcast_extras_updated(...)` in Task 15; now point it at the real function.)

- [ ] **Step 4: Add a smoke test**

```python
# backend/modules/chat/tests/test_extras_broadcast.py
def test_extras_event_dto_serialises():
    # End-to-end broadcast needs the bus + WS infra; smoke-test the event shape.
    from shared.events.chat import ChatSessionExtrasUpdatedEvent
    from shared.dtos.chat import ChatSessionExtras
    from datetime import datetime, timezone
    extras = ChatSessionExtras(
        tools_enabled=True, reasoning_mode="off", reasoning_effort=None
    )
    ev = ChatSessionExtrasUpdatedEvent(
        id="e1", type="chat.session.extras.updated", sequence=1,
        scope="session:s1", correlation_id="c1",
        timestamp=datetime.now(timezone.utc),
        payload={"session_id": "s1", "extras": extras.model_dump()},
        session_id="s1", extras=extras,
    )
    payload = ev.model_dump()
    assert payload["extras"]["tools_enabled"] is True
```

Run: `PYTHONPATH=$(pwd) pytest backend/modules/chat/tests/test_extras_broadcast.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/_handlers.py backend/modules/chat/tests/test_extras_broadcast.py
git commit -m "Broadcast ChatSessionExtrasUpdatedEvent on PATCH"
```

---

## Task 19: Frontend — types, API client, and cockpit store update

**Files:**
- Modify: `frontend/src/core/types/llm.ts`
- Modify: `frontend/src/core/types/chat.ts` (or wherever ChatSession types live)
- Modify: `frontend/src/core/api/chat.ts`
- Modify: `frontend/src/features/chat/cockpit/cockpitStore.ts`

- [ ] **Step 1: Update `frontend/src/core/types/llm.ts`**

Add (or update):

```typescript
export type ReasoningEffortSpec = {
  buckets: string[]
  default_bucket: string
}

export type ReasoningCapability = {
  kind: 'no_reasoning' | 'optional' | 'always_on'
  effort: ReasoningEffortSpec | null
  default_on: boolean
}

export type ToolCapability = {
  supported: boolean
  exclusive_with_reasoning: boolean
}

export type ResolvedCapabilities = {
  reasoning: ReasoningCapability
  tools: ToolCapability
  first_class_support: boolean
}

// Extend ModelMeta type:
export type ModelMeta = {
  // ... existing fields ...
  reasoning: ReasoningCapability
  tools: ToolCapability
  first_class_support: boolean
  supports_reasoning: boolean  // computed on backend, kept for legacy consumers
}
```

- [ ] **Step 2: Add `ChatSessionExtras` type**

In `frontend/src/core/types/chat.ts`:

```typescript
export type ChatSessionExtras = {
  tools_enabled: boolean
  reasoning_mode: 'off' | 'on'
  reasoning_effort: string | null
}
```

- [ ] **Step 3: Update `chatApi`**

In `frontend/src/core/api/chat.ts`, replace `updateSessionReasoning` and `updateSessionToggles` with:

```typescript
async updateSessionExtras(sessionId: string, extras: ChatSessionExtras): Promise<ChatSessionExtras> {
  const res = await apiFetch(`/api/chat/sessions/${sessionId}/extras`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(extras),
  })
  if (!res.ok) throw new Error(await res.text())
  const json = await res.json()
  return json.extras
}
```

- [ ] **Step 4: Refactor `cockpitStore.ts`**

Replace the boolean-based state with extras-based:

```typescript
import { ChatSessionExtras } from '@/core/types/chat'
import { chatApi } from '@/core/api/chat'

type CockpitStoreShape = {
  bySession: Record<string, ChatSessionExtras>
  pendingAutoReadMessageId: string | null
  hydrateFromServer: (sessionId: string, extras: ChatSessionExtras) => void
  updateExtras: (sessionId: string, patch: Partial<ChatSessionExtras>) => Promise<void>
  // ... auto-read methods unchanged ...
}

updateExtras: async (sessionId, patch) => {
  const prev = get().bySession[sessionId]
  if (!prev) return
  const next = { ...prev, ...patch }
  set((s) => ({ bySession: { ...s.bySession, [sessionId]: next } }))
  try {
    await chatApi.updateSessionExtras(sessionId, next)
  } catch (e) {
    set((s) => ({ bySession: { ...s.bySession, [sessionId]: prev } }))
    throw e
  }
},
```

- [ ] **Step 5: Subscribe to the new event**

Wherever the WebSocket event bus dispatches chat events (search `chat.session.` in `frontend/src`), add a handler that calls `cockpitStore.hydrateFromServer(session_id, extras)` on `chat.session.extras.updated`.

- [ ] **Step 6: Build to verify**

```bash
cd frontend && pnpm run build
```

Expected: build passes with no TS errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/core/types frontend/src/core/api frontend/src/features/chat/cockpit/cockpitStore.ts
git commit -m "Frontend: capability/extras types, API client, cockpit store rewrite"
```

---

## Task 20: ThinkingButton refactor — capability-aware UI with pop-out

**Files:**
- Modify: `frontend/src/features/chat/cockpit/buttons/ThinkingButton.tsx`
- Test: `frontend/src/features/chat/cockpit/__tests__/ThinkingButton.test.tsx` (new)

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/features/chat/cockpit/__tests__/ThinkingButton.test.tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { ThinkingButton } from '../buttons/ThinkingButton'

const optional = { kind: 'optional' as const, effort: null, default_on: true }
const optionalWithEffort = {
  kind: 'optional' as const,
  effort: { buckets: ['low', 'medium', 'high'], default_bucket: 'medium' },
  default_on: true,
}
const alwaysOn = { kind: 'always_on' as const, effort: null, default_on: true }
const noReasoning = { kind: 'no_reasoning' as const, effort: null, default_on: true }

const noop = async () => {}

describe('ThinkingButton', () => {
  it('disabled-inactive for no_reasoning', () => {
    render(<ThinkingButton reasoning={noReasoning} mode="off" effort={null} onChange={noop} />)
    expect(screen.getByRole('button')).toBeDisabled()
  })

  it('disabled-active for always_on', () => {
    render(<ThinkingButton reasoning={alwaysOn} mode="on" effort={null} onChange={noop} />)
    const btn = screen.getByRole('button')
    expect(btn).toBeDisabled()
    expect(btn).toHaveAttribute('data-state', 'active')
  })

  it('toggle for optional without effort', () => {
    let captured: any = null
    render(
      <ThinkingButton
        reasoning={optional}
        mode="off"
        effort={null}
        onChange={async (m, e) => { captured = { m, e } }}
      />,
    )
    fireEvent.click(screen.getByRole('button'))
    expect(captured).toEqual({ m: 'on', e: null })
  })

  it('opens pop-out for optional with effort', () => {
    render(
      <ThinkingButton
        reasoning={optionalWithEffort}
        mode="on"
        effort="medium"
        onChange={noop}
      />,
    )
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByText(/Off/i)).toBeInTheDocument()
    expect(screen.getByText(/Low/i)).toBeInTheDocument()
    expect(screen.getByText(/Medium/i)).toBeInTheDocument()
    expect(screen.getByText(/High/i)).toBeInTheDocument()
  })

  it('selecting Off in pop-out commits mode=off', () => {
    let captured: any = null
    render(
      <ThinkingButton
        reasoning={optionalWithEffort}
        mode="on"
        effort="medium"
        onChange={async (m, e) => { captured = { m, e } }}
      />,
    )
    fireEvent.click(screen.getByRole('button'))
    fireEvent.click(screen.getByText(/Off/i))
    expect(captured).toEqual({ m: 'off', e: null })
  })
})
```

- [ ] **Step 2: Run, verify fail**

```bash
cd frontend && pnpm vitest run src/features/chat/cockpit/__tests__/ThinkingButton.test.tsx
```

- [ ] **Step 3: Rewrite `ThinkingButton.tsx`**

```tsx
import { useState } from 'react'
import { ReasoningCapability } from '@/core/types/llm'
import { CockpitButton } from '../CockpitButton'

type Props = {
  reasoning: ReasoningCapability
  mode: 'off' | 'on'
  effort: string | null
  onChange: (mode: 'off' | 'on', effort: string | null) => Promise<void>
}

export function ThinkingButton({ reasoning, mode, effort, onChange }: Props) {
  const [popOpen, setPopOpen] = useState(false)

  if (reasoning.kind === 'no_reasoning') {
    return (
      <CockpitButton
        icon="💡"
        state="disabled"
        accent="gold"
        label="Thinking · n/a"
        data-state="inactive"
        title="Model does not support reasoning"
      />
    )
  }

  if (reasoning.kind === 'always_on' && !reasoning.effort) {
    return (
      <CockpitButton
        icon="💡"
        state="disabled"
        accent="gold"
        label="Thinking · always on"
        data-state="active"
        title="Model always reasons"
      />
    )
  }

  // optional or always_on with effort: pop-out OR direct toggle
  const hasEffort = reasoning.effort !== null
  const active = mode === 'on'

  const handleClick = () => {
    if (!hasEffort) {
      void onChange(active ? 'off' : 'on', null)
      return
    }
    setPopOpen((v) => !v)
  }

  return (
    <div className="relative">
      <CockpitButton
        icon="💡"
        state={active ? 'active' : 'idle'}
        accent="gold"
        label={
          active
            ? hasEffort
              ? `Thinking · ${effort?.[0]?.toUpperCase()}`
              : 'Thinking · on'
            : 'Thinking · off'
        }
        onClick={handleClick}
        data-state={active ? 'active' : 'inactive'}
      />
      {popOpen && hasEffort && (
        <ul className="absolute z-10 ...">
          <li>
            <button
              disabled={reasoning.kind === 'always_on'}
              onClick={() => { void onChange('off', null); setPopOpen(false) }}
            >Off</button>
          </li>
          {reasoning.effort!.buckets.map((b) => (
            <li key={b}>
              <button onClick={() => { void onChange('on', b); setPopOpen(false) }}>
                {b[0].toUpperCase() + b.slice(1)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
```

(Style with Tailwind to match existing cockpit aesthetic; pop-out container needs `absolute` positioning + z-index. Use the Chatsune body-transform-gotcha memory if positioning misbehaves at non-1 UI scale.)

- [ ] **Step 4: Run tests + build**

```bash
cd frontend && pnpm vitest run src/features/chat/cockpit/__tests__/ThinkingButton.test.tsx
pnpm run build
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/chat/cockpit/buttons/ThinkingButton.tsx frontend/src/features/chat/cockpit/__tests__/ThinkingButton.test.tsx
git commit -m "ThinkingButton: capability-aware states with effort pop-out"
```

---

## Task 21: ToolsButton refactor + CockpitBar mutex coordination

**Files:**
- Modify: `frontend/src/features/chat/cockpit/buttons/ToolsButton.tsx`
- Modify: `frontend/src/features/chat/cockpit/CockpitBar.tsx`
- Test: `frontend/src/features/chat/cockpit/__tests__/CockpitBar.test.tsx` (new)

- [ ] **Step 1: Write the failing CockpitBar test for mutex behaviour**

```tsx
// frontend/src/features/chat/cockpit/__tests__/CockpitBar.test.tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { CockpitBar } from '../CockpitBar'

const mutexOptionalCap = {
  reasoning: { kind: 'optional', effort: null, default_on: true },
  tools: { supported: true, exclusive_with_reasoning: true },
  first_class_support: true,
}

it('clicking Tools deactivates Reasoning when mutex', async () => {
  const updates: any[] = []
  render(
    <CockpitBar
      sessionId="s1"
      capability={mutexOptionalCap}
      extras={{ tools_enabled: false, reasoning_mode: 'on', reasoning_effort: null }}
      onUpdate={async (patch) => { updates.push(patch) }}
    />,
  )
  fireEvent.click(screen.getByRole('button', { name: /tools/i }))
  expect(updates[0]).toEqual({ tools_enabled: true, reasoning_mode: 'off', reasoning_effort: null })
})

it('clicking active Tools turns both off when mutex', async () => {
  const updates: any[] = []
  render(
    <CockpitBar
      sessionId="s1"
      capability={mutexOptionalCap}
      extras={{ tools_enabled: true, reasoning_mode: 'off', reasoning_effort: null }}
      onUpdate={async (patch) => { updates.push(patch) }}
    />,
  )
  fireEvent.click(screen.getByRole('button', { name: /tools/i }))
  expect(updates[0]).toEqual({ tools_enabled: false })
})
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Refactor `ToolsButton.tsx`**

```tsx
import { ToolCapability } from '@/core/types/llm'
import { CockpitButton } from '../CockpitButton'

type Props = {
  tools: ToolCapability
  enabled: boolean
  onChange: (enabled: boolean) => Promise<void>
}

export function ToolsButton({ tools, enabled, onChange }: Props) {
  if (!tools.supported) {
    return (
      <CockpitButton
        icon="🔧"
        state="disabled"
        accent="silver"
        label="Tools · n/a"
        title={
          tools.exclusive_with_reasoning
            ? 'Tools and reasoning cannot run together for this model'
            : 'Model does not support tools'
        }
      />
    )
  }
  return (
    <CockpitButton
      icon="🔧"
      state={enabled ? 'active' : 'idle'}
      accent="silver"
      label={enabled ? 'Tools · on' : 'Tools · off'}
      onClick={() => { void onChange(!enabled) }}
    />
  )
}
```

- [ ] **Step 4: Refactor `CockpitBar.tsx` to coordinate mutex**

Add a wrapper that funnels both buttons' onChange through one handler that applies the mutex rule:

```tsx
import { ResolvedCapabilities } from '@/core/types/llm'  // shape: { reasoning, tools, first_class_support }
import { ChatSessionExtras } from '@/core/types/chat'
import { ThinkingButton } from './buttons/ThinkingButton'
import { ToolsButton } from './buttons/ToolsButton'

type Props = {
  sessionId: string
  capability: ResolvedCapabilities
  extras: ChatSessionExtras
  onUpdate: (patch: Partial<ChatSessionExtras>) => Promise<void>
}

export function CockpitBar({ sessionId, capability, extras, onUpdate }: Props) {
  const handleReasoning = async (mode: 'off' | 'on', effort: string | null) => {
    const patch: Partial<ChatSessionExtras> = { reasoning_mode: mode, reasoning_effort: effort }
    if (mode === 'on' && capability.tools.exclusive_with_reasoning && extras.tools_enabled) {
      patch.tools_enabled = false
    }
    await onUpdate(patch)
  }
  const handleTools = async (next: boolean) => {
    const patch: Partial<ChatSessionExtras> = { tools_enabled: next }
    if (next && capability.tools.exclusive_with_reasoning && extras.reasoning_mode === 'on') {
      patch.reasoning_mode = 'off'
      patch.reasoning_effort = null
    }
    await onUpdate(patch)
  }

  return (
    <div className="flex gap-2">
      <ThinkingButton
        reasoning={capability.reasoning}
        mode={extras.reasoning_mode}
        effort={extras.reasoning_effort}
        onChange={handleReasoning}
      />
      <ToolsButton
        tools={capability.tools}
        enabled={extras.tools_enabled}
        onChange={handleTools}
      />
      {/* Auto-read button etc. unchanged — re-add from previous version */}
    </div>
  )
}
```

(Inspect the existing `CockpitBar.tsx` for what other buttons it renders — autoRead, etc. — and preserve them.)

- [ ] **Step 5: Run tests + build**

```bash
cd frontend && pnpm vitest run src/features/chat/cockpit/__tests__/
pnpm run build
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/chat/cockpit
git commit -m "ToolsButton + CockpitBar: capability-aware UI with mutex coordination"
```

---

## Task 22: Model browser — first-class badge + filter

**Files:**
- Modify: `frontend/src/app/components/model-browser/ModelBrowser.tsx`
- Modify: `frontend/src/app/components/model-browser/modelBrowserStore.ts`
- Test: `frontend/src/app/components/model-browser/__tests__/ModelBrowser.test.tsx` (new)

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/app/components/model-browser/__tests__/ModelBrowser.test.tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { ModelBrowser } from '../ModelBrowser'

const models = [
  { unique_id: 'a:m1', display_name: 'M1', first_class_support: true,  /* fill required fields */ },
  { unique_id: 'a:m2', display_name: 'M2', first_class_support: false, /* fill required fields */ },
]

it('renders first-class badge on first-class rows', () => {
  render(<ModelBrowser models={models as any} />)
  // M1 has the badge, M2 does not
  const m1Row = screen.getByText('M1').closest('[data-testid="model-row"]')
  expect(m1Row?.querySelector('[data-testid="first-class-badge"]')).not.toBeNull()
  const m2Row = screen.getByText('M2').closest('[data-testid="model-row"]')
  expect(m2Row?.querySelector('[data-testid="first-class-badge"]')).toBeNull()
})

it('filter "first-class only" hides best-effort rows', () => {
  render(<ModelBrowser models={models as any} />)
  fireEvent.click(screen.getByLabelText(/first-class only/i))
  expect(screen.queryByText('M2')).toBeNull()
  expect(screen.getByText('M1')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Update `ModelBrowser.tsx`**

Add the badge rendering inline with each model row:

```tsx
{model.first_class_support && (
  <span
    data-testid="first-class-badge"
    className="ml-2 text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-gold-500/20 text-gold-300"
    title="Fully curated capabilities — Reasoning, Tools, Effort all properly wired"
  >
    ★ first-class
  </span>
)}
```

Add the filter toggle to the toolbar:

```tsx
<label className="flex items-center gap-2 text-sm">
  <input
    type="checkbox"
    checked={firstClassOnly}
    onChange={(e) => setFirstClassOnly(e.target.checked)}
  />
  First-class only
</label>
```

In `modelBrowserStore.ts`, add `firstClassOnly: boolean` and `setFirstClassOnly(value: boolean)`. Apply the filter where the model list is computed.

- [ ] **Step 4: Run tests + build**

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/model-browser
git commit -m "Model browser: first-class badge and filter toggle"
```

---

## Task 23: Persona editor — remove reasoning toggle from UI

**Files:**
- Modify: `frontend/src/app/components/persona-overlay/EditTab.tsx`
- Modify: `frontend/src/core/types/persona.ts` (mark `reasoning_enabled` deprecated comment, do not remove)

- [ ] **Step 1: Find and remove the reasoning toggle JSX in EditTab.tsx**

```bash
rg -n "reasoning_enabled" frontend/src/app/components/persona-overlay/EditTab.tsx
```

Locate the relevant `<input type="checkbox">` / `<label>` block and the corresponding form-state variable. Remove the JSX block + form-state binding + any prop forwarding for that field.

- [ ] **Step 2: Update `frontend/src/core/types/persona.ts`**

```typescript
export type Persona = {
  // ... existing fields ...
  /**
   * @deprecated 2026-05-09 — replaced by per-session ChatSessionExtras.
   * Field still present on legacy persona documents; not surfaced in UI.
   */
  reasoning_enabled?: boolean
}
```

- [ ] **Step 3: Build to verify nothing imports the removed UI**

```bash
cd frontend && pnpm run build
```

Expected: build passes. If anything still imports the old toggle handler, fix it.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/persona-overlay/EditTab.tsx frontend/src/core/types/persona.ts
git commit -m "Persona editor: remove reasoning toggle (replaced by per-session extras)"
```

---

## Task 24: Wire model-switch remap into the change-model flow

**Files:**
- Modify: wherever the chat module handles model change for an existing session (search target below)
- Test: `backend/modules/chat/tests/test_model_switch_wiring.py` (new)

When the user picks a different model on an existing chat session, the backend must (a) resolve capabilities of the new model, (b) call `remap_extras_for_capability` against the existing session extras, (c) persist the remapped extras, (d) broadcast `ChatSessionExtrasUpdatedEvent`.

- [ ] **Step 1: Locate the model-change site**

Run:
```bash
rg -n "model_unique_id|model_id" backend/modules/chat/_handlers.py backend/modules/chat/_handlers_ws.py | grep -i -E "update|patch|set|change"
```

Identify the endpoint or WS-handler that updates the session's model.

- [ ] **Step 2: Write the failing test**

```python
# backend/modules/chat/tests/test_model_switch_wiring.py
from shared.dtos.chat import ChatSessionExtras
from shared.dtos.llm import ReasoningCapability, ToolCapability
from backend.modules.chat._extras_remap import remap_extras_for_capability


def test_model_switch_drops_tools_when_new_model_does_not_support():
    old = ChatSessionExtras(tools_enabled=True, reasoning_mode="on", reasoning_effort="medium")
    new_reasoning = ReasoningCapability(kind="optional")
    new_tools = ToolCapability(supported=False)
    out = remap_extras_for_capability(old, new_reasoning, new_tools)
    assert out.tools_enabled is False
    assert out.reasoning_mode == "on"  # reasoning preserved


def test_model_switch_forces_reasoning_off_for_no_reasoning_target():
    old = ChatSessionExtras(tools_enabled=True, reasoning_mode="on", reasoning_effort="high")
    new_reasoning = ReasoningCapability(kind="no_reasoning")
    new_tools = ToolCapability(supported=True)
    out = remap_extras_for_capability(old, new_reasoning, new_tools)
    assert out.reasoning_mode == "off"
    assert out.tools_enabled is True
```

(These exercise the same `remap_extras_for_capability` from Task 15 but document the model-switch usage explicitly.)

- [ ] **Step 3: Add wiring in the model-change handler**

In the located handler, around the persistence call:

```python
from backend.modules.chat._extras_remap import remap_extras_for_capability
from backend.modules.llm._capabilities import resolve_capabilities

# Before persisting the new model:
old_session = await chat_repo.get_session(session_id, user["id"])
old_extras_raw = old_session.get("extras") if old_session else None

# Resolve new model's capability
new_adapter_type, new_model_id = new_model_unique_id.split(":", 1)
adapter = llm_module.get_adapter_by_slug(new_adapter_type)
new_capability = resolve_capabilities(
    adapter_type=new_adapter_type, model_id=new_model_id, adapter=adapter,
)

# Remap (or default if no extras yet)
if old_extras_raw:
    old_extras = ChatSessionExtras(**old_extras_raw)
    new_extras = remap_extras_for_capability(
        old_extras, new_capability.reasoning, new_capability.tools,
    )
else:
    new_extras = default_extras_for_capability(new_capability)

# Persist both model and extras
await chat_repo.update_session_model_and_extras(
    session_id, user["id"], new_model_unique_id, new_extras,
)
# Broadcast remapped extras
await _broadcast_extras_updated(session_id, new_extras, user["id"])
```

Add a new repository method `update_session_model_and_extras` (one DB write, atomic) in `_repository.py`:

```python
async def update_session_model_and_extras(
    self, session_id: str, user_id: str, model_unique_id: str, extras: ChatSessionExtras,
) -> dict | None:
    now = datetime.now(timezone.utc)
    await self._sessions.update_one(
        {"_id": session_id, "user_id": user_id},
        {"$set": {
            "model_unique_id": model_unique_id,
            "extras": extras.model_dump(),
            "updated_at": now,
        }},
    )
    return await self._sessions.find_one({"_id": session_id, "user_id": user_id})
```

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=$(pwd) pytest backend/modules/chat/tests/test_model_switch_wiring.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/_handlers.py backend/modules/chat/_handlers_ws.py backend/modules/chat/_repository.py backend/modules/chat/tests/test_model_switch_wiring.py
git commit -m "Wire extras remap into model-switch flow + atomic repo write"
```

---

## Task 25: Manual verification on dev environment

**Files:** none (verification only)

- [ ] **Step 1: Bring up dev environment**

```bash
docker compose up -d
# verify backend started
curl -s http://localhost:8000/health | head
```

If frontend dev server isn't part of compose, start it separately:
```bash
cd frontend && pnpm run dev
```

- [ ] **Step 2: Walk through the spec §8.3 checklist on desktop**

Per `devdocs/specs/2026-05-09-llm-reasoning-tools-capabilities-design.md` §8.3, run all 9 verification steps. Tick each in this checklist:

- [ ] **2a.** Llama 3.3 (`no_reasoning` via Ollama): Reasoning button disabled with tooltip; Tools toggle works; web-search request triggers tools.
- [ ] **2b.** Magistral (`optional, no effort` via OpenRouter or Mistral pass-through): Reasoning toggle direct, no pop-out; both switches independent.
- [ ] **2c.** GPT-5 (`optional, effort=4-bucket` via OpenRouter): pop-out has 5 entries including Off; choose Off → button white; submit Off → no `reasoning_content` in stream.
- [ ] **2d.** Claude Sonnet 4.6 (`optional, effort=3-bucket` via OpenRouter): pop-out has 4 entries including Off; effort=high visibly longer than medium.
- [ ] **2e.** Grok 4.3 via xAI direct (`optional, simulated`): toggle works (slug-pair switch under the hood).
- [ ] **2f.** DeepSeek V4 (`optional, effort` via OpenRouter): pop-out works.
- [ ] **2g.** Model switch flow: GPT-5 (Tools+Reasoning=high) → Claude (effort stays high) → back to GPT-5 (settings reflect intermediate, not original).
- [ ] **2h.** Persona editor for any persona: reasoning toggle absent.
- [ ] **2i.** Multi-device: open same chat on two clients, change a setting on one, second reflects within one round-trip.

- [ ] **Step 3: Run on mobile (lg breakpoint)**

Open the app on a phone (or use browser device emulation < 1024px). Verify cockpit buttons render and pop-out positioning is sane (mind the body-transform-gotcha for fixed overlays at non-1 UI scale).

- [ ] **Step 4: Confirm model browser filter**

Open the model browser. Confirm the day-1 first-class entries (Claude Sonnet 4.6, Claude Opus 4.7, GPT-5, DeepSeek V4 — each via OpenRouter and nano-gpt) show the ★ badge. Toggle "first-class only" — confirm filter behaviour.

- [ ] **Step 5: LLM harness scenarios for translation correctness**

Per CLAUDE.md §LLM Test Harness, exercise representative requests directly against each upstream — bypassing chat orchestrator — to confirm the translation table from spec §6.3 produces the expected upstream behaviour.

Create scenarios under `tests/llm_scenarios/capabilities/`:

```bash
mkdir -p tests/llm_scenarios/capabilities
```

For each (adapter, model, mode, effort) combination that matters:

```bash
# Example: GPT-5 effort=low via OpenRouter
uv run python -m backend.llm_harness \
  --model openai/gpt-5 \
  --connection openrouter \
  --reasoning on --effort low \
  --message '{"role":"user","content":"Compute 2+2 step by step"}'
```

Save each invocation as a JSON scenario file for reproducibility. Run for at least:
- Claude Sonnet 4.6 via OR — `mode=on, effort=low|medium|high` and `mode=off`
- GPT-5 via OR — `mode=on, effort=minimal|medium|high` and `mode=off`
- DeepSeek V4 via OR — `mode=on, effort=medium` and `mode=off`
- Llama 3.3 via Ollama — `mode=off` (no_reasoning model — confirm no `think` field on wire)

Confirm: the upstream returns `reasoning_content` (or its equivalent) iff we asked for reasoning, and the effort is honoured (high produces visibly longer thinking spans).

- [ ] **Step 6: Backwards-compat verification on legacy data**

Per CLAUDE.md §Data-Model Migrations, exercise the upgrade path against legacy documents:

1. Find a chat session in the dev DB that predates this work (no `extras` field):
```bash
docker compose exec mongo mongosh --quiet --eval '
  db = db.getSiblingDB("chatsune");
  db.chat_sessions.findOne({extras: {$exists: false}});
'
```

2. Open it in the UI. Verify cockpit shows defaults computed from the current model's capability (per §4.5). Verify after first cockpit click, `extras` field gets persisted.

3. Find a persona document with `reasoning_enabled: true` set:
```bash
docker compose exec mongo mongosh --quiet --eval '
  db = db.getSiblingDB("chatsune");
  db.personas.findOne({reasoning_enabled: true});
'
```

4. Open the persona editor. Confirm the field does not appear in UI. Confirm save does not strip the field from the document (lazy-read preserves it).

- [ ] **Step 7: Document any defects in a follow-up**

If any verification step fails, do **not** mark the plan complete. Open issues / follow-up tasks for each. If all pass, mark this task complete.

---

## Final cleanup (no separate task — do as part of Task 25 commit)

After verification, ensure no stale code references remain:

```bash
rg "reasoning_enabled" backend/ shared/ frontend/src/ --type-add 'frontend:*.{ts,tsx}' --type py --type frontend
```

Remaining references should only be in deprecation comments or in legacy DB-document-deserialisation defaults. Any active call site is a regression — fix before closing.

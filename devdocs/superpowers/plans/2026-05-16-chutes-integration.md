# Chutes AI Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Chutes AI as a BYOK LLM provider, exposing only TEE (Trusted Execution Environment) models with ≥80k context as Chatsune's "ultra privacy" inference option.

**Architecture:** New `chutes_http` adapter under `backend/modules/llm/_adapters/`, structurally a slim clone of the OpenRouter adapter (OpenAI-compatible SSE, tool-call accumulator, gutter timers, retry policy via `backend._retry`). TEE-only hard filter (`confidential_compute == true` + `context_length >= 80_000` + text output). New single-field frontend adapter view (`api_key` only). Drift-resistant request body that filters non-mandatory keys against the per-model `supported_sampling_parameters` whitelist before sending.

**Tech Stack:** Python (FastAPI, httpx, Pydantic v2), React (TSX, Tailwind). No new dependencies.

**Spec:** `devdocs/superpowers/specs/2026-05-16-chutes-integration-design.md`

---

## File Structure

**Backend (create):**
- `backend/modules/llm/_adapters/_chutes_http.py` — adapter module (filter, request body, whitelist, SSE pipeline, adapter class, sub-router)
- `backend/modules/llm/tests/test_chutes_filter.py` — unit tests for catalogue-entry filter and `ModelMetaDto` mapping
- `backend/modules/llm/tests/test_chutes_request_body.py` — unit tests for `build_request_body` and whitelist filter

**Backend (modify):**
- `backend/modules/llm/_registry.py` — register `ChutesHttpAdapter` in `ADAPTER_REGISTRY`

**Frontend (create):**
- `frontend/src/app/components/llm-providers/adapter-views/ChutesHttpView.tsx` — single-field (`api_key`) connection-config view

**Frontend (modify):**
- `frontend/src/core/adapters/AdapterViewRegistry.tsx` — register `ChutesHttpView` under `chutes_http`

---

## Task 1: Adapter scaffolding — class, registry, template

**Files:**
- Create: `backend/modules/llm/_adapters/_chutes_http.py` (skeleton only)
- Modify: `backend/modules/llm/_registry.py`

This task only stands up the empty adapter class with class-level attributes and a wizard template, plus the registry wire-up. No filter, no request building, no streaming yet — those land in subsequent tasks. Goal is to be able to `import` the adapter and have `ADAPTER_REGISTRY["chutes_http"]` resolve correctly.

- [ ] **Step 1: Create the skeleton adapter file**

Create `backend/modules/llm/_adapters/_chutes_http.py`:

```python
"""Chutes AI HTTP adapter — OpenAI-compatible Chat Completions, TEE-only.

BYOK adapter: users supply their own ``cpk_...`` API key per Connection.
Surfaces only models with ``confidential_compute == true`` and
``context_length >= 80_000`` so the connection is a pure "ultra privacy"
inference option. Structurally a slim clone of OpenRouter — same SSE
parser, tool-call accumulator, gutter timer, and retry policy — but
without Anthropic cache markers or driver hooks (no first-class model
curating in MVP).

Drift-resistance: Chutes' catalogue exposes per-model
``supported_sampling_parameters``. The adapter filters the final request
body against this whitelist immediately before sending so that engine /
quantisation drift drops fields silently rather than returning 400.

See ``devdocs/superpowers/specs/2026-05-16-chutes-integration-design.md``.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._events import ProviderStreamEvent
from backend.modules.llm._adapters._types import (
    AdapterTemplate,
    ConfigFieldHint,
    ResolvedConnection,
)
from shared.dtos.inference import CompletionRequest
from shared.dtos.llm import ModelMetaDto

_log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=15.0)
_PROBE_TIMEOUT = httpx.Timeout(10.0)
_TRACE_PAYLOADS = os.environ.get("LLM_TRACE_PAYLOADS") == "1"

GUTTER_SLOW_SECONDS: float = 30.0
GUTTER_ABORT_SECONDS: float = float(
    os.environ.get("LLM_STREAM_ABORT_SECONDS", "120"),
)

# Floor mirrors OpenRouter / nano-gpt — sub-80k models leave no
# headroom once history and tool definitions stack up.
MIN_CONTEXT_TOKENS = 80_000

# Hardcoded endpoints — Chutes runs a single public managed endpoint.
# Adapter does not expose a ``url`` config field.
_INFERENCE_BASE_URL = "https://llm.chutes.ai/v1"
_MANAGEMENT_BASE_URL = "https://api.chutes.ai"


class ChutesHttpAdapter(BaseAdapter):
    adapter_type = "chutes_http"
    display_name = "Chutes AI"
    view_id = "chutes_http"
    secret_fields = frozenset({"api_key"})

    def __init__(self) -> None:
        # Populated per ``fetch_models`` call. Both maps are consulted at
        # request-build time (capability_hint and whitelist filter).
        self._features_by_model_id: dict[str, list[str]] = {}
        self._sampling_params_by_model_id: dict[str, list[str]] = {}

    @classmethod
    def templates(cls) -> list[AdapterTemplate]:
        return [
            AdapterTemplate(
                id="chutes_ai",
                display_name="Chutes AI (TEE-only)",
                slug_prefix="chutes",
                config_defaults={"api_key": ""},
                required_config_fields=("api_key",),
            ),
        ]

    @classmethod
    def config_schema(cls) -> list[ConfigFieldHint]:
        return [
            ConfigFieldHint(
                name="api_key", type="secret", label="API Key",
                required=True, placeholder="cpk_...",
            ),
        ]

    @classmethod
    def router(cls) -> APIRouter | None:
        # Sub-router lands in Task 6.
        return None

    async def fetch_models(
        self, c: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        # Implemented in Task 5.
        return []

    async def stream_completion(
        self, c: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        # Implemented in Task 5. Trailing yield after raise makes Python
        # recognise this as an async generator so the AsyncIterator
        # return type matches the BaseAdapter signature.
        raise NotImplementedError("stream_completion lands in Task 5")
        yield  # pragma: no cover
```

- [ ] **Step 2: Register the adapter**

Modify `backend/modules/llm/_registry.py` — add the import and the registry entry:

```python
from backend.modules.llm._adapters._chutes_http import ChutesHttpAdapter
# ... existing imports ...

ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = {
    "ollama_http": OllamaHttpAdapter,
    "community": CommunityAdapter,
    "chutes_http": ChutesHttpAdapter,
}
```

- [ ] **Step 3: Verify syntax and registry resolution**

Run: `uv run python -m py_compile backend/modules/llm/_adapters/_chutes_http.py backend/modules/llm/_registry.py`
Expected: exits 0, no output.

Run: `uv run python -c "from backend.modules.llm._registry import get_adapter_class; cls = get_adapter_class('chutes_http'); assert cls is not None and cls.adapter_type == 'chutes_http' and cls.display_name == 'Chutes AI'; print('OK')"`
Expected: prints `OK`.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/llm/_adapters/_chutes_http.py backend/modules/llm/_registry.py
git commit -m "$(cat <<'EOF'
Scaffold chutes_http adapter — class, template, registry entry

Stands up the BYOK Chutes adapter skeleton and registers it in
ADAPTER_REGISTRY. Catalogue filter, request body, streaming and
sub-router land in follow-up tasks; this commit keeps the registry
import path passing and the wizard template selectable.
EOF
)"
```

---

## Task 2: Catalogue filter + ModelMetaDto mapping (TDD)

**Files:**
- Test: `backend/modules/llm/tests/test_chutes_filter.py` (create)
- Modify: `backend/modules/llm/_adapters/_chutes_http.py`

Implements the catalogue-entry filter and `_entry_to_meta` mapping. Hard-gates: `confidential_compute == True`, `context_length >= 80_000`, `output_modalities == ["text"]`. Maps catalogue fields onto `ModelMetaDto` and stashes `supported_features` + `supported_sampling_parameters` for later request-build use.

- [ ] **Step 1: Write the failing test file**

Create `backend/modules/llm/tests/test_chutes_filter.py`:

```python
"""Unit tests for the chutes_http catalogue filter and entry mapping."""
from __future__ import annotations

from datetime import datetime

import pytest

from backend.modules.llm._adapters._chutes_http import (
    ChutesHttpAdapter,
    _entry_to_meta,
)
from backend.modules.llm._adapters._types import ResolvedConnection


def _conn() -> ResolvedConnection:
    return ResolvedConnection(
        id="conn-1",
        user_id="user-1",
        adapter_type="chutes_http",
        display_name="My Chutes",
        slug="chutes-byok",
        config={"api_key": "cpk_test"},
        created_at=datetime(2026, 5, 16),
        updated_at=datetime(2026, 5, 16),
    )


def _entry(**overrides: object) -> dict:
    base: dict = {
        "id": "deepseek-ai/DeepSeek-V3.2-TEE",
        "context_length": 131_072,
        "max_output_length": 8192,
        "confidential_compute": True,
        "output_modalities": ["text"],
        "input_modalities": ["text"],
        "supported_features": ["tools", "json_mode"],
        "supported_sampling_parameters": ["temperature", "top_p"],
        "pricing": {"prompt": "0.28", "completion": "0.42"},
    }
    base.update(overrides)
    return base


def test_tee_false_is_dropped():
    adapter = ChutesHttpAdapter()
    assert _entry_to_meta(_entry(confidential_compute=False), _conn(), adapter=adapter) is None


def test_tee_missing_is_dropped():
    adapter = ChutesHttpAdapter()
    e = _entry()
    del e["confidential_compute"]
    assert _entry_to_meta(e, _conn(), adapter=adapter) is None


def test_below_context_floor_is_dropped():
    adapter = ChutesHttpAdapter()
    assert _entry_to_meta(_entry(context_length=32_000), _conn(), adapter=adapter) is None


def test_at_context_floor_is_kept():
    adapter = ChutesHttpAdapter()
    meta = _entry_to_meta(_entry(context_length=80_000), _conn(), adapter=adapter)
    assert meta is not None
    assert meta.context_window == 80_000


def test_image_only_output_is_dropped():
    adapter = ChutesHttpAdapter()
    assert _entry_to_meta(_entry(output_modalities=["image"]), _conn(), adapter=adapter) is None


def test_mixed_output_is_dropped():
    adapter = ChutesHttpAdapter()
    assert _entry_to_meta(
        _entry(output_modalities=["text", "image"]), _conn(), adapter=adapter,
    ) is None


def test_missing_output_modalities_is_dropped():
    adapter = ChutesHttpAdapter()
    e = _entry()
    del e["output_modalities"]
    assert _entry_to_meta(e, _conn(), adapter=adapter) is None


def test_valid_entry_maps_to_meta():
    adapter = ChutesHttpAdapter()
    meta = _entry_to_meta(_entry(), _conn(), adapter=adapter)
    assert meta is not None
    assert meta.model_id == "deepseek-ai/DeepSeek-V3.2-TEE"
    assert meta.display_name == "deepseek-ai/DeepSeek-V3.2-TEE"
    assert meta.context_window == 131_072
    assert meta.connection_id == "conn-1"
    assert meta.connection_slug == "chutes-byok"
    assert meta.connection_display_name == "My Chutes"
    assert meta.supports_tool_calls is True
    assert meta.supports_vision is False
    assert meta.billing_category == "pay_per_token"


def test_vision_model_sets_supports_vision():
    adapter = ChutesHttpAdapter()
    meta = _entry_to_meta(
        _entry(input_modalities=["text", "image"]), _conn(), adapter=adapter,
    )
    assert meta is not None
    assert meta.supports_vision is True


def test_free_model_billing_category():
    adapter = ChutesHttpAdapter()
    meta = _entry_to_meta(
        _entry(pricing={"prompt": "0", "completion": "0"}), _conn(), adapter=adapter,
    )
    assert meta is not None
    assert meta.billing_category == "free"


def test_features_and_sampling_params_stashed_on_adapter():
    adapter = ChutesHttpAdapter()
    _entry_to_meta(_entry(), _conn(), adapter=adapter)
    assert adapter._features_by_model_id["deepseek-ai/DeepSeek-V3.2-TEE"] == [
        "tools", "json_mode",
    ]
    assert adapter._sampling_params_by_model_id["deepseek-ai/DeepSeek-V3.2-TEE"] == [
        "temperature", "top_p",
    ]


def test_reasoning_feature_yields_optional_reasoning():
    adapter = ChutesHttpAdapter()
    meta = _entry_to_meta(
        _entry(
            id="deepseek-ai/DeepSeek-R1-0528-TEE",
            supported_features=["tools", "reasoning"],
        ),
        _conn(), adapter=adapter,
    )
    assert meta is not None
    assert meta.reasoning.kind == "optional"


def test_no_reasoning_feature_yields_no_reasoning():
    adapter = ChutesHttpAdapter()
    meta = _entry_to_meta(_entry(), _conn(), adapter=adapter)  # default features = [tools, json_mode]
    assert meta is not None
    assert meta.reasoning.kind == "no_reasoning"
```

- [ ] **Step 2: Run the test file to verify it fails**

Run: `uv run pytest backend/modules/llm/tests/test_chutes_filter.py -v`
Expected: ImportError for `_entry_to_meta` (the symbol does not exist yet).

- [ ] **Step 3: Add `_entry_to_meta` and the `capability_hint` helper**

First, replace the existing import line `from shared.dtos.llm import ModelMetaDto` at the top of `backend/modules/llm/_adapters/_chutes_http.py` with:

```python
from shared.dtos.llm import ModelMetaDto, ReasoningCapability, ToolCapability
```

Then add the helpers and `_entry_to_meta` to `backend/modules/llm/_adapters/_chutes_http.py`, immediately after the constants block and before the `ChutesHttpAdapter` class:

```python
def _supports(features: list[str], *names: str) -> bool:
    return any(n in features for n in names)


def _billing_category(pricing: dict) -> str:
    """Map Chutes pricing into Chatsune billing_category.

    Chutes serves prices as strings ("0.28") or numeric. Treat 0 / "0"
    as free; anything else as pay_per_token. Subscription is not a
    Chutes concept (no platform plan tier exposed via the catalogue).
    """
    if not isinstance(pricing, dict):
        return "pay_per_token"
    prompt = pricing.get("prompt")
    completion = pricing.get("completion")
    free_values: frozenset = frozenset({0, 0.0, "0", "0.0"})
    if prompt in free_values and completion in free_values:
        return "free"
    return "pay_per_token"


def _entry_to_meta(
    entry: dict, c: ResolvedConnection, *, adapter: "ChutesHttpAdapter",
) -> ModelMetaDto | None:
    """Map one Chutes catalogue entry to a ``ModelMetaDto`` or ``None``.

    Hard filter — all three must hold:
    1. ``confidential_compute is True`` (TEE-only; trust the flag, not the suffix)
    2. ``context_length >= 80_000`` (mirrors OpenRouter / nano-gpt floor)
    3. ``output_modalities == ["text"]`` (Phase 1 text-output only)
    """
    from backend.modules.llm._capabilities import resolve_capabilities

    if entry.get("confidential_compute") is not True:
        return None

    context_length = int(entry.get("context_length") or 0)
    if context_length < MIN_CONTEXT_TOKENS:
        return None

    if entry.get("output_modalities") != ["text"]:
        return None

    features = list(entry.get("supported_features") or [])
    sampling_params = list(entry.get("supported_sampling_parameters") or [])
    input_mods = entry.get("input_modalities") or []
    pricing = entry.get("pricing") or {}

    # Stash per-model heuristic inputs for later request-build steps.
    adapter._features_by_model_id[entry["id"]] = features
    adapter._sampling_params_by_model_id[entry["id"]] = sampling_params

    resolved = resolve_capabilities(
        adapter_type=adapter.adapter_type,
        model_id=entry["id"],
        adapter=adapter,
    )

    return ModelMetaDto(
        connection_id=c.id,
        connection_slug=c.slug,
        connection_display_name=c.display_name,
        model_id=entry["id"],
        display_name=entry.get("name") or entry["id"],
        context_window=context_length,
        reasoning=resolved.reasoning,
        tools=resolved.tools,
        first_class_support=resolved.first_class_support,
        supports_vision="image" in input_mods,
        supports_tool_calls=_supports(features, "tools"),
        is_deprecated=False,
        billing_category=_billing_category(pricing),
        is_moderated=None,
    )
```

Also add the `capability_hint` method to `ChutesHttpAdapter` (insert immediately after `__init__`):

```python
    def capability_hint(self, model_id: str):
        """Heuristic capability hint from cached ``supported_features``.

        Returns ``first_class_support=False`` — Chutes integration is
        catalogue-driven, not curated. Falls through to the universal
        default if ``fetch_models`` has not populated the features map
        for this model_id yet.
        """
        from backend.modules.llm._capabilities import CapabilityHint

        features = self._features_by_model_id.get(model_id)
        if features is None:
            return None
        if _supports(features, "reasoning"):
            reasoning = ReasoningCapability(kind="optional")
        else:
            reasoning = ReasoningCapability(kind="no_reasoning")
        tools = ToolCapability(supported=_supports(features, "tools"))
        return CapabilityHint(
            reasoning=reasoning,
            tools=tools,
            first_class_support=False,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/modules/llm/tests/test_chutes_filter.py -v`
Expected: all 12 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_chutes_http.py backend/modules/llm/tests/test_chutes_filter.py
git commit -m "$(cat <<'EOF'
Add chutes_http catalogue filter and entry mapping

TEE-only hard filter: confidential_compute=true, context_length>=80k,
output_modalities==['text']. Map catalogue fields onto ModelMetaDto and
stash per-model supported_features + supported_sampling_parameters for
later request-build use. Capability hint emits first_class_support=False
(heuristic, not curated).
EOF
)"
```

---

## Task 3: `build_request_body` + message translation (TDD)

**Files:**
- Test: `backend/modules/llm/tests/test_chutes_request_body.py` (create)
- Modify: `backend/modules/llm/_adapters/_chutes_http.py`

Implements `_translate_message` (plain-string text content, image parts as `data:` URLs, tool calls preserved) and `build_request_body` (OpenAI-compat shape, optional `temperature` / `tools` / `reasoning_effort` per the spec rules).

- [ ] **Step 1: Write the failing test file**

Create `backend/modules/llm/tests/test_chutes_request_body.py`:

```python
"""Unit tests for chutes_http build_request_body and message translation."""
from __future__ import annotations

from backend.modules.llm._adapters._chutes_http import (
    _translate_message,
    build_request_body,
)
from shared.dtos.chat import ChatSessionExtras
from shared.dtos.inference import (
    CompletionMessage,
    CompletionRequest,
    ContentPart,
    ToolDefinition,
)
from shared.dtos.llm import ReasoningCapability, ToolCapability


def _user_msg(text: str) -> CompletionMessage:
    return CompletionMessage(role="user", content=[ContentPart(type="text", text=text)])


def _request(
    *,
    reasoning: ReasoningCapability | None = None,
    tools: list[ToolDefinition] | None = None,
    extras: ChatSessionExtras | None = None,
    temperature: float | None = None,
) -> CompletionRequest:
    return CompletionRequest(
        model="deepseek-ai/DeepSeek-V3.2-TEE",
        messages=[_user_msg("hi")],
        temperature=temperature,
        tools=tools,
        reasoning=reasoning or ReasoningCapability(kind="no_reasoning"),
        tools_capability=ToolCapability(supported=bool(tools)),
        extras=extras or ChatSessionExtras(
            tools_enabled=False, reasoning_mode="off", reasoning_effort=None,
        ),
    )


def test_minimal_body_has_only_required_keys():
    body = build_request_body(_request())
    assert body["model"] == "deepseek-ai/DeepSeek-V3.2-TEE"
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert "temperature" not in body
    assert "tools" not in body
    assert "reasoning_effort" not in body


def test_temperature_when_set():
    body = build_request_body(_request(temperature=0.4))
    assert body["temperature"] == 0.4


def test_tools_omitted_when_session_disables_them():
    tool = ToolDefinition(name="t", description="d", parameters={})
    body = build_request_body(_request(
        tools=[tool],
        extras=ChatSessionExtras(
            tools_enabled=False, reasoning_mode="off", reasoning_effort=None,
        ),
    ))
    assert "tools" not in body


def test_tools_present_when_session_enables_them():
    tool = ToolDefinition(name="search", description="search the web", parameters={"type": "object"})
    body = build_request_body(_request(
        tools=[tool],
        extras=ChatSessionExtras(
            tools_enabled=True, reasoning_mode="off", reasoning_effort=None,
        ),
    ))
    assert body["tools"] == [{
        "type": "function",
        "function": {
            "name": "search",
            "description": "search the web",
            "parameters": {"type": "object"},
        },
    }]


def test_reasoning_effort_when_optional_and_on():
    body = build_request_body(_request(
        reasoning=ReasoningCapability(kind="optional"),
        extras=ChatSessionExtras(
            tools_enabled=False, reasoning_mode="on", reasoning_effort="high",
        ),
    ))
    assert body["reasoning_effort"] == "high"


def test_reasoning_effort_omitted_when_optional_and_off():
    body = build_request_body(_request(
        reasoning=ReasoningCapability(kind="optional"),
        extras=ChatSessionExtras(
            tools_enabled=False, reasoning_mode="off", reasoning_effort="high",
        ),
    ))
    assert "reasoning_effort" not in body


def test_reasoning_effort_omitted_when_no_reasoning_kind():
    body = build_request_body(_request(
        reasoning=ReasoningCapability(kind="no_reasoning"),
        extras=ChatSessionExtras(
            tools_enabled=False, reasoning_mode="on", reasoning_effort="high",
        ),
    ))
    assert "reasoning_effort" not in body


def test_image_message_uses_image_url_data_url():
    msg = CompletionMessage(
        role="user",
        content=[
            ContentPart(type="text", text="describe"),
            ContentPart(type="image", media_type="image/png", data="aGVsbG8="),
        ],
    )
    translated = _translate_message(msg)
    assert translated["role"] == "user"
    assert translated["content"] == [
        {"type": "text", "text": "describe"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}},
    ]


def test_text_only_message_uses_plain_string():
    msg = CompletionMessage(role="user", content=[ContentPart(type="text", text="hi")])
    translated = _translate_message(msg)
    assert translated == {"role": "user", "content": "hi"}


def test_tool_call_message_preserves_calls():
    from shared.dtos.inference import ToolCallResult
    msg = CompletionMessage(
        role="assistant",
        content=[ContentPart(type="text", text="")],
        tool_calls=[ToolCallResult(id="c1", name="search", arguments='{"q":"x"}')],
    )
    translated = _translate_message(msg)
    assert translated["tool_calls"] == [{
        "id": "c1",
        "type": "function",
        "function": {"name": "search", "arguments": '{"q":"x"}'},
    }]


def test_tool_result_message_preserves_tool_call_id():
    msg = CompletionMessage(
        role="tool",
        content=[ContentPart(type="text", text='{"result": 42}')],
        tool_call_id="c1",
    )
    translated = _translate_message(msg)
    assert translated["tool_call_id"] == "c1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/modules/llm/tests/test_chutes_request_body.py -v`
Expected: ImportError for `_translate_message` / `build_request_body`.

- [ ] **Step 3: Add `_translate_message` and `build_request_body`**

First, replace the existing import line `from shared.dtos.inference import CompletionRequest` at the top of `backend/modules/llm/_adapters/_chutes_http.py` with:

```python
from shared.dtos.inference import CompletionMessage, CompletionRequest
```

Then append the helpers to `backend/modules/llm/_adapters/_chutes_http.py` (before the `ChutesHttpAdapter` class):

```python
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
                "image_url": {"url": f"data:{p.media_type};base64,{p.data}"},
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


def build_request_body(request: CompletionRequest) -> dict:
    """Translate a CompletionRequest into the Chutes ``/chat/completions`` body.

    Whitelist filtering against ``supported_sampling_parameters`` happens in
    a separate step (see ``_filter_to_whitelist``), invoked by
    ``stream_completion`` immediately before sending. This function emits
    the common-case body shape only.
    """
    payload: dict = {
        "model": request.model,
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [_translate_message(m) for m in request.messages],
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.tools and request.extras.tools_enabled:
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
    if (
        request.reasoning.kind == "optional"
        and request.extras.reasoning_mode == "on"
        and request.extras.reasoning_effort
    ):
        payload["reasoning_effort"] = request.extras.reasoning_effort
    return payload
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/modules/llm/tests/test_chutes_request_body.py -v`
Expected: all 10 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_chutes_http.py backend/modules/llm/tests/test_chutes_request_body.py
git commit -m "$(cat <<'EOF'
Add chutes_http build_request_body and message translation

OpenAI-compat body shape with optional temperature / tools /
reasoning_effort. Text-only messages serialise as plain strings
(cache-friendly); image parts embed as data:base64 URLs in the
image_url shape. Tool calls and tool_call_id round-trip unchanged.
EOF
)"
```

---

## Task 4: Whitelist filter against `supported_sampling_parameters` (TDD)

**Files:**
- Modify: `backend/modules/llm/tests/test_chutes_request_body.py`
- Modify: `backend/modules/llm/_adapters/_chutes_http.py`

Implements `_filter_to_whitelist(payload, whitelist)` — drops any key not in the per-model whitelist except for a fixed set of always-allowed structural keys (`model`, `messages`, `stream`, `stream_options`, `tools`).

- [ ] **Step 1: Append the whitelist tests**

Append to `backend/modules/llm/tests/test_chutes_request_body.py`:

```python
from backend.modules.llm._adapters._chutes_http import _filter_to_whitelist


def _full_body() -> dict:
    return {
        "model": "deepseek-ai/DeepSeek-V3.2-TEE",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
        "stream_options": {"include_usage": True},
        "tools": [{"type": "function", "function": {"name": "t"}}],
        "temperature": 0.5,
        "reasoning_effort": "high",
        "top_p": 0.9,
    }


def test_whitelist_drops_disallowed_sampling_params():
    body = _filter_to_whitelist(_full_body(), ["temperature"])
    # temperature stays (in whitelist), reasoning_effort and top_p go.
    assert body["temperature"] == 0.5
    assert "reasoning_effort" not in body
    assert "top_p" not in body


def test_whitelist_preserves_structural_keys_even_if_absent():
    body = _filter_to_whitelist(_full_body(), [])
    # No sampling param survives, but structural keys always do.
    assert body["model"] == "deepseek-ai/DeepSeek-V3.2-TEE"
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}
    assert body["tools"] == [{"type": "function", "function": {"name": "t"}}]
    assert "temperature" not in body
    assert "reasoning_effort" not in body
    assert "top_p" not in body


def test_whitelist_none_means_no_filtering():
    body = _filter_to_whitelist(_full_body(), None)
    assert body == _full_body()


def test_whitelist_keeps_reasoning_effort_when_listed():
    body = _filter_to_whitelist(_full_body(), ["reasoning_effort"])
    assert body["reasoning_effort"] == "high"
    assert "temperature" not in body


def test_whitelist_filter_does_not_mutate_input():
    original = _full_body()
    snapshot = dict(original)
    _filter_to_whitelist(original, [])
    assert original == snapshot
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/modules/llm/tests/test_chutes_request_body.py -v`
Expected: ImportError for `_filter_to_whitelist`. The previously-passing tests stay green; only the new ones fail at collection.

- [ ] **Step 3: Implement `_filter_to_whitelist`**

Append to `backend/modules/llm/_adapters/_chutes_http.py` (immediately after `build_request_body`):

```python
# Keys always preserved regardless of the per-model sampling whitelist —
# these are structural (request envelope) not sampling parameters.
_ALWAYS_KEEP: frozenset[str] = frozenset({
    "model", "messages", "stream", "stream_options", "tools",
})


def _filter_to_whitelist(
    payload: dict, whitelist: list[str] | None,
) -> dict:
    """Drop sampling parameters not in the per-model whitelist.

    Returns a new dict — does not mutate the input. ``whitelist=None``
    means "no catalogue data, send everything" — the adapter has not yet
    seen this model_id (e.g. cache miss with a transient catalogue
    glitch); better to attempt the request than to fabricate a hard
    filter.
    """
    if whitelist is None:
        return dict(payload)
    allowed = _ALWAYS_KEEP | set(whitelist)
    return {k: v for k, v in payload.items() if k in allowed}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/modules/llm/tests/test_chutes_request_body.py -v`
Expected: all 15 tests pass (10 original + 5 new).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_chutes_http.py backend/modules/llm/tests/test_chutes_request_body.py
git commit -m "$(cat <<'EOF'
Add per-model whitelist filter for chutes_http request bodies

_filter_to_whitelist drops sampling parameters that the chosen Chutes
model does not list in supported_sampling_parameters. Structural keys
(model, messages, stream, stream_options, tools) always pass through.
Whitelist=None disables filtering (catalogue cache miss). Pure
function — does not mutate the input.
EOF
)"
```

---

## Task 5: `fetch_models` + `stream_completion` (HTTP-level)

**Files:**
- Modify: `backend/modules/llm/_adapters/_chutes_http.py`

This task wires the HTTP pieces. We do not write automated tests for the streaming/SSE path (they would require an httpx mock stack we don't have here, and the OpenRouter adapter's SSE pipeline has historically been verified manually). The smoke checklist in Task 8 exercises both.

The streaming pipeline copies OpenRouter's structure verbatim, dropping the Anthropic-cache branches and the OpenRouter-specific app-attribution headers.

- [ ] **Step 1: Add SSE helpers, ToolCallAccumulator, and chunk-to-events**

First, extend the import block at the top of `backend/modules/llm/_adapters/_chutes_http.py`. Add these imports (the `ProviderStreamEvent` import line from Task 1 needs to be replaced with the longer one below):

```python
import asyncio
import json
import time
from uuid import uuid4

from backend._retry import (
    MAX_RETRY_ATTEMPTS,
    compute_retry_delay,
    log_retry,
    parse_retry_after,
    should_retry_status,
)
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
```

Then append the SSE helpers to the same file (after the existing functions, before the `ChutesHttpAdapter` class — or wherever placement keeps definitions before first use):

```python
_SSE_DONE = object()
_REFUSAL_REASONS: frozenset[str] = frozenset({"content_filter", "refusal"})


class _ToolCallAccumulator:
    """Gathers OpenAI-style tool_call fragments across SSE chunks.

    ``finalised()`` is idempotent: subsequent calls return an empty list.
    Mirrors OpenRouter's implementation — kept as a separate copy because
    the shared-helper extract refactor is tracked separately.
    """

    def __init__(self) -> None:
        self._by_index: dict[int, dict] = {}
        self._finalised = False

    def ingest(self, fragments: list[dict]) -> None:
        for frag in fragments:
            idx = frag.get("index")
            if idx is None:
                continue
            slot = self._by_index.setdefault(idx, {"id": None, "name": "", "args": ""})
            if frag.get("id"):
                slot["id"] = frag["id"]
            fn = frag.get("function") or {}
            if fn.get("name"):
                slot["name"] = fn["name"]
            if fn.get("arguments"):
                slot["args"] += fn["arguments"]

    def finalised(self) -> list[dict]:
        if self._finalised:
            return []
        self._finalised = True
        out: list[dict] = []
        for idx, slot in sorted(self._by_index.items()):
            out.append({
                "id": slot["id"] or f"call_{uuid4().hex[:12]}",
                "name": slot["name"],
                "arguments": slot["args"] or "{}",
                "index": idx,
            })
        return out


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


def _chunk_to_events(
    chunk: dict, acc: _ToolCallAccumulator,
) -> list[ProviderStreamEvent]:
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

    # Some upstreams stream thinking under reasoning_content, others
    # under bare ``reasoning``. Emit ThinkingDelta for whichever appears.
    reasoning_content = delta.get("reasoning_content") or ""
    if reasoning_content:
        events.append(ThinkingDelta(delta=reasoning_content))
    reasoning = delta.get("reasoning") or ""
    if reasoning:
        events.append(ThinkingDelta(delta=reasoning))

    content = delta.get("content") or ""
    if content:
        events.append(ContentDelta(delta=content))

    tool_frags = delta.get("tool_calls") or []
    if tool_frags:
        from backend.modules.llm._adapters._tool_call_streaming import (
            fragments_to_delta_events,
        )
        events.extend(fragments_to_delta_events(tool_frags, acc))

    finish = choice.get("finish_reason")
    if finish is None:
        return events

    if finish == "tool_calls":
        for call in acc.finalised():
            events.append(ToolCallEvent(
                id=call["id"], name=call["name"],
                arguments=call["arguments"], index=call["index"],
            ))
    elif finish in _REFUSAL_REASONS:
        events.append(StreamRefused(
            reason=finish,
            refusal_text=delta.get("refusal") or None,
        ))

    return events
```

- [ ] **Step 2: Implement `fetch_models`**

Replace the placeholder `fetch_models` body inside `ChutesHttpAdapter` with the real implementation:

```python
    async def fetch_models(
        self, c: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        api_key = c.config.get("api_key") or ""
        headers = {"Authorization": f"Bearer {api_key}"}
        metas: list[ModelMetaDto] = []
        page = 0
        limit = 100  # Chutes default is 25; bump to reduce round-trips.

        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            while True:
                try:
                    resp = await client.get(
                        f"{_INFERENCE_BASE_URL}/models",
                        params={"page": page, "limit": limit},
                        headers=headers,
                    )
                except httpx.HTTPError as exc:
                    _log.warning("chutes_http.fetch_models transport: %s", exc)
                    return metas

                if resp.status_code in (401, 403):
                    _log.warning(
                        "chutes_http.fetch_models auth failure: status=%d",
                        resp.status_code,
                    )
                    return metas
                if resp.status_code != 200:
                    _log.warning(
                        "chutes_http.fetch_models upstream %d: %s",
                        resp.status_code, resp.text[:200],
                    )
                    return metas

                try:
                    body = resp.json()
                except ValueError:
                    _log.warning("chutes_http.fetch_models malformed JSON")
                    return metas

                entries = body.get("data") or []
                if not isinstance(entries, list):
                    return metas

                for entry in entries:
                    if not isinstance(entry, dict) or not entry.get("id"):
                        continue
                    meta = _entry_to_meta(entry, c, adapter=self)
                    if meta is not None:
                        metas.append(meta)

                if len(entries) < limit:
                    return metas
                page += 1
```

- [ ] **Step 3: Implement `stream_completion`**

Replace the placeholder `stream_completion` body inside `ChutesHttpAdapter` with the real implementation:

```python
    async def stream_completion(
        self, c: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        api_key = c.config.get("api_key") or ""

        payload = build_request_body(request)
        whitelist = self._sampling_params_by_model_id.get(request.model)
        payload = _filter_to_whitelist(payload, whitelist)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        if _TRACE_PAYLOADS:
            _log.info(
                "LLM_TRACE path=chutes-out url=%s payload=%s",
                _INFERENCE_BASE_URL,
                json.dumps(payload, default=str, sort_keys=True),
            )

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for attempt in range(MAX_RETRY_ATTEMPTS + 1):
                retry_delay: float | None = None
                try:
                    async with client.stream(
                        "POST", f"{_INFERENCE_BASE_URL}/chat/completions",
                        json=payload, headers=headers,
                    ) as resp:
                        if (
                            should_retry_status(resp.status_code)
                            and attempt < MAX_RETRY_ATTEMPTS
                        ):
                            retry_delay = compute_retry_delay(
                                attempt, parse_retry_after(resp.headers),
                            )
                            log_retry(
                                _log,
                                operation="chutes_http",
                                attempt=attempt,
                                delay_seconds=retry_delay,
                                status_code=resp.status_code,
                                extra={"model": payload.get("model")},
                            )
                        elif resp.status_code in (401, 403):
                            yield StreamError(
                                error_code="invalid_api_key",
                                message="Chutes rejected the API key",
                            )
                            return
                        elif should_retry_status(resp.status_code):
                            yield StreamError(
                                error_code="provider_unavailable",
                                message=(
                                    f"Chutes returned {resp.status_code}; "
                                    f"gave up after {MAX_RETRY_ATTEMPTS + 1} attempts"
                                ),
                            )
                            return
                        elif resp.status_code != 200:
                            body = await resp.aread()
                            detail = body.decode("utf-8", errors="replace")[:500]
                            _log.error(
                                "chutes_http upstream %d: %s",
                                resp.status_code, detail,
                            )
                            yield StreamError(
                                error_code="provider_unavailable",
                                message=f"Chutes returned {resp.status_code}: {detail}",
                            )
                            return
                        else:
                            acc = _ToolCallAccumulator()
                            seen_done = False
                            last_usage: dict = {}
                            pending_next: asyncio.Task | None = None
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
                                                "chutes_http.gutter_slow "
                                                "model=%s idle=%.1fs",
                                                payload.get("model"), elapsed,
                                            )
                                            yield StreamSlow()
                                            slow_fired = True
                                            continue
                                        _log.warning(
                                            "chutes_http.gutter_abort "
                                            "model=%s idle=%.1fs",
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
                                    if (
                                        isinstance(parsed, dict)
                                        and parsed.get("usage")
                                    ):
                                        last_usage = parsed["usage"]

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
                                _details = (
                                    last_usage.get("completion_tokens_details") or {}
                                )
                                yield StreamDone(
                                    input_tokens=last_usage.get("prompt_tokens"),
                                    output_tokens=last_usage.get("completion_tokens"),
                                    reasoning_tokens=_details.get("reasoning_tokens"),
                                )
                            return
                except httpx.ConnectError:
                    yield StreamError(
                        error_code="provider_unavailable",
                        message="Cannot connect to Chutes",
                    )
                    return

                # Retry path — sleep with the stream context closed.
                assert retry_delay is not None
                await asyncio.sleep(retry_delay)
```

- [ ] **Step 4: Syntax-check the file**

Run: `uv run python -m py_compile backend/modules/llm/_adapters/_chutes_http.py`
Expected: exits 0.

- [ ] **Step 5: Run the existing chutes test suite to confirm we did not break anything**

Run: `uv run pytest backend/modules/llm/tests/test_chutes_filter.py backend/modules/llm/tests/test_chutes_request_body.py -v`
Expected: all 27 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_adapters/_chutes_http.py
git commit -m "$(cat <<'EOF'
Implement chutes_http fetch_models and stream_completion

fetch_models paginates GET /v1/models and applies the TEE+context+text
filter. stream_completion runs the OpenRouter-style SSE pipeline:
tool-call accumulator, gutter timers (30s slow / 120s abort),
backend._retry for 429/503 before first token, terminal events for
auth / refusal / abort / done. content_filter and refusal both map to
StreamRefused. Authorization: Bearer cpk_... is the only auth header —
X-API-Key would silently fall back to anonymous rate limiting.
EOF
)"
```

---

## Task 6: `/test` sub-router for key validation

**Files:**
- Modify: `backend/modules/llm/_adapters/_chutes_http.py`

The Chutes `/v1/models` endpoint is public, so it cannot validate a key. The sub-router hits `https://api.chutes.ai/users/me` with the user's `cpk_...` bearer token — 200 means valid, 401/403 means rejected.

- [ ] **Step 1: Replace the `router()` placeholder and add the builder**

Replace the placeholder `router()` method inside `ChutesHttpAdapter`:

```python
    @classmethod
    def router(cls) -> APIRouter:
        return _build_adapter_router()
```

Then append at the very end of `backend/modules/llm/_adapters/_chutes_http.py`:

```python
def _build_adapter_router() -> APIRouter:
    from fastapi import Depends

    from backend.modules.llm._resolver import resolve_connection_for_user

    router = APIRouter()

    @router.post("/test")
    async def test_connection(
        c: ResolvedConnection = Depends(resolve_connection_for_user),
    ) -> dict:
        api_key = c.config.get("api_key") or ""
        if not api_key:
            return {"valid": False, "error": "No API key configured."}

        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            try:
                resp = await client.get(
                    f"{_MANAGEMENT_BASE_URL}/users/me",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            except httpx.HTTPError as exc:
                return {"valid": False, "error": f"Cannot reach Chutes: {exc}"}

        if resp.status_code == 200:
            return {"valid": True, "error": None}
        if resp.status_code in (401, 403):
            return {"valid": False, "error": "Chutes rejected the API key."}
        return {
            "valid": False,
            "error": f"Chutes management API returned {resp.status_code}.",
        }

    return router
```

- [ ] **Step 2: Syntax-check and confirm router resolves**

Run: `uv run python -m py_compile backend/modules/llm/_adapters/_chutes_http.py`
Expected: exits 0.

Run: `uv run python -c "from backend.modules.llm._adapters._chutes_http import ChutesHttpAdapter; r = ChutesHttpAdapter.router(); assert r is not None; routes = [getattr(rt, 'path', None) for rt in r.routes]; assert '/test' in routes, routes; print('OK', routes)"`
Expected: prints something like `OK ['/test']`.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/llm/_adapters/_chutes_http.py
git commit -m "$(cat <<'EOF'
Add chutes_http /test sub-router for key validation

Hits https://api.chutes.ai/users/me with the user's cpk_... bearer
token: 200 => valid, 401/403 => rejected, anything else => surface the
status. Cannot use /v1/models for this — it is public and answers 200
without auth.
EOF
)"
```

---

## Task 7: Frontend adapter view + registry wire-up

**Files:**
- Create: `frontend/src/app/components/llm-providers/adapter-views/ChutesHttpView.tsx`
- Modify: `frontend/src/core/adapters/AdapterViewRegistry.tsx`

Single-field view (only `api_key`). Structurally derived from `CommunityView`, reduced.

- [ ] **Step 1: Create the view**

Create `frontend/src/app/components/llm-providers/adapter-views/ChutesHttpView.tsx`:

```tsx
import { useEffect, useId, useState } from 'react'
import type { AdapterViewProps } from '../../../../core/adapters/AdapterViewRegistry'
import type { SecretFieldView } from '../../../../core/types/llm'
import { SECRET_INPUT_STYLE, SECRET_INPUT_NO_AUTOFILL } from '../../../../core/utils/secretInputStyle'

function isSecretFieldView(value: unknown): value is SecretFieldView {
  return (
    typeof value === 'object' &&
    value !== null &&
    'is_set' in (value as Record<string, unknown>) &&
    typeof (value as SecretFieldView).is_set === 'boolean'
  )
}

/**
 * Connection-config view for Chutes AI. A single api_key field — Chutes
 * runs a single managed endpoint and we never let users override the
 * URL. Only TEE-flagged models with >=80k context are surfaced in the
 * picker; the explanatory text below the field reflects that.
 */
export function ChutesHttpView({
  connection,
  requiredConfigFields: _requiredConfigFields,
  onConfigChange,
}: AdapterViewProps) {
  const apiKeyInputId = useId()

  const cfg = connection.config
  const apiKeyState = isSecretFieldView(cfg.api_key) ? cfg.api_key : null

  const [apiKey, setApiKey] = useState<string>('')
  const [clearApiKey, setClearApiKey] = useState<boolean>(false)

  useEffect(() => {
    const next: Record<string, unknown> = {}
    if (apiKey.length > 0) {
      next.api_key = apiKey
    } else if (clearApiKey) {
      next.api_key = null
    }
    onConfigChange(next)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKey, clearApiKey])

  useEffect(() => {
    if (apiKeyState?.is_set && apiKey !== '' && !clearApiKey) {
      setApiKey('')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKeyState?.is_set])

  return (
    <div className="space-y-4 text-sm text-white/80">
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <label
            htmlFor={apiKeyInputId}
            className="block text-[11px] font-mono uppercase tracking-wider text-white/50"
          >
            API-Key<span className="text-red-400"> *</span>
          </label>
          {apiKeyState?.is_set && !clearApiKey && (
            <span className="text-[10px] font-mono uppercase tracking-wider text-green-400/80">
              saved
            </span>
          )}
        </div>
        <input
          id={apiKeyInputId}
          type="text"
          value={apiKey}
          onChange={(e) => {
            setApiKey(e.target.value)
            if (e.target.value.length > 0) setClearApiKey(false)
          }}
          placeholder={
            apiKeyState?.is_set
              ? '••••••••  (leave empty to keep)'
              : 'cpk_…'
          }
          style={SECRET_INPUT_STYLE}
          {...SECRET_INPUT_NO_AUTOFILL}
          className="w-full rounded border border-white/10 bg-black/30 px-2 py-1.5 font-mono text-sm text-white outline-none focus:border-purple/60"
        />
        {apiKeyState?.is_set && (
          <label className="inline-flex items-center gap-1.5 text-[11px] text-white/50">
            <input
              type="checkbox"
              checked={clearApiKey}
              onChange={(e) => {
                setClearApiKey(e.target.checked)
                if (e.target.checked) setApiKey('')
              }}
              className="h-3 w-3"
            />
            Remove saved key
          </label>
        )}
        <p className="text-[11px] text-white/40">
          Get a Chutes API-Key from chutes.ai. Only models running in a
          Trusted Execution Environment (TEE) appear in the picker —
          your prompts are hardware-isolated and even Chutes operators
          cannot read them.
        </p>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Register the view**

Modify `frontend/src/core/adapters/AdapterViewRegistry.tsx`:

Add the import next to the existing ones:

```tsx
import { ChutesHttpView } from '../../app/components/llm-providers/adapter-views/ChutesHttpView'
```

Extend the registry object:

```tsx
export const ADAPTER_VIEW_REGISTRY: Record<string, ComponentType<AdapterViewProps>> = {
  ollama_http: OllamaHttpView,
  community: CommunityView,
  xai_http: XaiHttpView,
  chutes_http: ChutesHttpView,
}
```

- [ ] **Step 3: Type-check the frontend**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: exits 0, no type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/llm-providers/adapter-views/ChutesHttpView.tsx frontend/src/core/adapters/AdapterViewRegistry.tsx
git commit -m "$(cat <<'EOF'
Add ChutesHttpView and register it in the AdapterViewRegistry

Single-field view (api_key only) for the Chutes AI connection wizard.
Explanatory copy makes the TEE-only stance explicit so users understand
why the picker will be smaller than chutes.ai/models implies.
EOF
)"
```

---

## Task 8: Build verification and manual smoke test

**Files:** none — verification only.

- [ ] **Step 1: Run the full chutes test suite once more**

Run: `uv run pytest backend/modules/llm/tests/test_chutes_filter.py backend/modules/llm/tests/test_chutes_request_body.py -v`
Expected: all 27 tests pass.

- [ ] **Step 2: Run any sibling test files that exercise the adapter registry / model browser**

Run: `uv run pytest backend/modules/llm/tests/ -v`
Expected: all tests pass; no chutes-related regressions in the wider suite.

- [ ] **Step 3: Build the frontend**

Run: `cd frontend && pnpm run build`
Expected: build completes, no type errors, no missing-module errors.

- [ ] **Step 4: Manual smoke test (interactive — needs running stack and the test key)**

The key is at `.chutes-test-key` (already gitignored). Use it for these steps. Mark each PASS / FAIL as you go.

1. Start the dev stack (`docker compose up -d` and `pnpm dev` or however the local convention is).
2. In the UI: create a new Connection, pick the "Chutes AI (TEE-only)" template, paste the test key from `.chutes-test-key`, save.
3. Click "Test connection." Expect `valid: true`.
4. Edit the connection, replace the saved key with `cpk_invalid_xyz`, save, test again. Expect `valid: false` with message "Chutes rejected the API key."
5. Restore the real key. Open the model browser: expect a list of 16+ TEE models, including `deepseek-ai/DeepSeek-V3.2-TEE`. None of the listed models should have `-TEE` missing from `confidential_compute` (we trust the flag, but visually all of them should follow the convention).
6. Start a chat with `deepseek-ai/DeepSeek-V3.2-TEE`, no tools. Send a short message. Expect a streamed response that completes cleanly.
7. Start a chat with `deepseek-ai/DeepSeek-R1-0528-TEE`, reasoning toggled on. Expect `ThinkingDelta` events to render before content.
8. With a model that lists `tools` in `supported_features` and one Chatsune tool enabled in the session, ask for something that should trigger the tool. Expect the tool call to round-trip cleanly.

- [ ] **Step 5: Final commit (only if anything changed during smoke testing)**

If the smoke test surfaced a fix, commit it as a follow-up. Otherwise, no commit.

- [ ] **Step 6: Merge to master**

Per `CLAUDE.md` "Implementation defaults": always merge to master after implementation.

```bash
git log --oneline master..HEAD   # confirm what we're about to merge
# if on a feature branch:
git checkout master && git merge --ff-only -   # or non-ff if appropriate
```

If working directly on master (acceptable given the project pattern), this step is a no-op.

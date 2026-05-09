"""Minimal compatibility tests for xAI and Mistral adapters under the new
ModelMetaDto / CompletionRequest contracts. Premium handling will land in
follow-up specs (per devdocs/specs/2026-05-09 §2 Scope of adapter changes)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.modules.llm._adapters._mistral_http import (
    MistralHttpAdapter,
    _build_chat_payload as _mistral_build_chat_payload,
    _dedup_models,
)
from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._adapters._xai_http import (
    XaiHttpAdapter,
    _build_chat_payload as _xai_build_chat_payload,
)
from shared.dtos.chat import ChatSessionExtras
from shared.dtos.inference import (
    CompletionMessage,
    CompletionRequest,
    ContentPart,
)
from shared.dtos.llm import ReasoningCapability, ToolCapability


def _xai_conn() -> ResolvedConnection:
    now = datetime.now(UTC)
    return ResolvedConnection(
        id="conn-xai-1",
        user_id="u1",
        adapter_type="xai_http",
        display_name="Chris's xAI",
        slug="chris-xai",
        config={
            "url": "https://api.x.ai/v1",
            "api_key": "xai-test-key",
            "max_parallel": 4,
        },
        created_at=now,
        updated_at=now,
    )


def _mistral_conn() -> ResolvedConnection:
    now = datetime.now(UTC)
    return ResolvedConnection(
        id="premium:mistral",
        user_id="u1",
        adapter_type="mistral_http",
        display_name="Mistral",
        slug="mistral",
        config={
            "url": "https://api.mistral.ai/v1",
            "api_key": "mistral-test-key",
        },
        created_at=now,
        updated_at=now,
    )


def _completion_request(
    *,
    model: str,
    reasoning_kind: str = "optional",
    reasoning_mode: str = "off",
    tools_enabled: bool = False,
) -> CompletionRequest:
    return CompletionRequest(
        model=model,
        messages=[
            CompletionMessage(
                role="user",
                content=[ContentPart(type="text", text="hi")],
            ),
        ],
        reasoning=ReasoningCapability(kind=reasoning_kind),
        tools_capability=ToolCapability(supported=True),
        extras=ChatSessionExtras(
            tools_enabled=tools_enabled,
            reasoning_mode=reasoning_mode,
            reasoning_effort=None,
        ),
    )


# ---------------------------------------------------------------------------
# xAI — ModelMetaDto carries the new capability fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_xai_meta_carries_new_capability_fields() -> None:
    """The xAI adapter must build ModelMetaDtos with the new required fields.

    The xAI adapter's ``fetch_models`` returns its hard-coded static list
    without making HTTP calls, so we can call it directly.
    """
    adapter = XaiHttpAdapter()
    metas = await adapter.fetch_models(_xai_conn())
    assert metas, "expected xAI adapter to return at least one ModelMetaDto"
    for meta in metas:
        # Conservative defaults: every Grok entry currently exposes a
        # reasoning toggle via the slug-pair table, so reasoning is
        # ``optional``. The legacy ``supports_reasoning`` computed field
        # should derive ``True`` from this.
        assert isinstance(meta.reasoning, ReasoningCapability)
        assert meta.reasoning.kind == "optional"
        assert meta.reasoning.default_on is True
        assert isinstance(meta.tools, ToolCapability)
        assert meta.tools.supported is True
        assert meta.tools.exclusive_with_reasoning is False
        assert meta.first_class_support is False
        assert meta.supports_reasoning is True


# ---------------------------------------------------------------------------
# xAI — request translation reads extras.reasoning_mode
# ---------------------------------------------------------------------------


def test_xai_request_translation_reads_reasoning_mode_on() -> None:
    """Build payload picks the reasoning slug when extras.reasoning_mode == 'on'."""
    req = _completion_request(model="grok-4.1-fast", reasoning_mode="on")
    payload = _xai_build_chat_payload(req)
    assert payload["model"] == "grok-4-1-fast-reasoning"


def test_xai_request_translation_reads_reasoning_mode_off() -> None:
    """Build payload picks the non-reasoning slug when extras.reasoning_mode == 'off'."""
    req = _completion_request(model="grok-4.1-fast", reasoning_mode="off")
    payload = _xai_build_chat_payload(req)
    assert payload["model"] == "grok-4-1-fast-non-reasoning"


# ---------------------------------------------------------------------------
# Mistral — ModelMetaDto carries the new capability fields
# ---------------------------------------------------------------------------


def _mistral_caps(**overrides) -> dict:
    base = {
        "completion_chat": True,
        "completion_fim": False,
        "function_calling": False,
        "fine_tuning": False,
        "vision": False,
        "reasoning": False,
    }
    base.update(overrides)
    return base


def test_mistral_meta_carries_new_capability_fields_for_reasoning_model() -> None:
    """Mistral entries with ``capabilities.reasoning=True`` must emit
    a ``ReasoningCapability(kind="optional")`` plus ``ToolCapability``."""
    entries = [
        {
            "id": "magistral-medium-latest",
            "name": "magistral-medium-2509",
            "max_context_length": 131_072,
            "capabilities": _mistral_caps(function_calling=True, reasoning=True),
            "deprecation": None,
        },
    ]
    metas = _dedup_models(entries, _mistral_conn())
    assert len(metas) == 1
    m = metas[0]
    assert isinstance(m.reasoning, ReasoningCapability)
    assert m.reasoning.kind == "optional"
    assert m.reasoning.default_on is True
    assert isinstance(m.tools, ToolCapability)
    assert m.tools.supported is True
    assert m.tools.exclusive_with_reasoning is False
    assert m.first_class_support is False
    assert m.supports_reasoning is True


def test_mistral_meta_carries_new_capability_fields_for_non_reasoning_model() -> None:
    """Mistral entries with ``capabilities.reasoning=False`` must emit
    ``ReasoningCapability(kind="no_reasoning")`` and the legacy
    ``supports_reasoning`` computed field must be ``False``."""
    entries = [
        {
            "id": "mistral-medium-latest",
            "name": "mistral-medium-2508",
            "max_context_length": 131_072,
            "capabilities": _mistral_caps(function_calling=True, vision=True),
            "deprecation": None,
        },
    ]
    metas = _dedup_models(entries, _mistral_conn())
    assert len(metas) == 1
    m = metas[0]
    assert m.reasoning.kind == "no_reasoning"
    assert m.tools.supported is True
    assert m.tools.exclusive_with_reasoning is False
    assert m.first_class_support is False
    assert m.supports_reasoning is False


def test_mistral_meta_tools_supported_defaults_to_true_when_capability_missing() -> None:
    """If upstream omits ``function_calling`` we conservatively default to
    True (the safer side: tools may be silently ignored, but we don't
    falsely block tool calls on models that do support them)."""
    caps = _mistral_caps()
    caps.pop("function_calling")
    entries = [
        {
            "id": "mistral-small-latest",
            "name": "mistral-small-2506",
            "max_context_length": 32_768,
            "capabilities": caps,
            "deprecation": None,
        },
    ]
    metas = _dedup_models(entries, _mistral_conn())
    assert len(metas) == 1
    assert metas[0].tools.supported is True


# ---------------------------------------------------------------------------
# Mistral — request translation passes the model through unchanged
# ---------------------------------------------------------------------------


def test_mistral_request_translation_passes_model_through_with_extras() -> None:
    """Mistral's reasoning is baked into the model id; ``_build_chat_payload``
    must accept the new request shape without touching the model slug."""
    req = _completion_request(model="magistral-medium-latest", reasoning_mode="on")
    payload = _mistral_build_chat_payload(req)
    assert payload["model"] == "magistral-medium-latest"
    assert payload["stream"] is True

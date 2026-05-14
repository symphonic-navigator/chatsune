"""Minimal compatibility tests for xAI and Mistral adapters under the new
ModelMetaDto / CompletionRequest contracts. Premium handling will land in
follow-up specs (per devdocs/specs/2026-05-09 §2 Scope of adapter changes)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.modules.llm._adapters._mistral_http import (
    _build_chat_payload as _mistral_build_chat_payload,
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
        # Only grok-4.3 is first-class (per 2026-05-11 spec). The deprecated
        # grok-4.1-fast and grok-4.20 entries stay non-first-class.
        assert meta.first_class_support is (meta.model_id == "grok-4.3")
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
# Mistral — request translation passes the model through unchanged
# ---------------------------------------------------------------------------


def test_mistral_request_translation_passes_model_through_with_extras() -> None:
    """Mistral's reasoning is baked into the model id; ``_build_chat_payload``
    must accept the new request shape without touching the model slug."""
    req = _completion_request(model="magistral-medium-latest", reasoning_mode="on")
    payload = _mistral_build_chat_payload(req)
    assert payload["model"] == "magistral-medium-latest"
    assert payload["stream"] is True

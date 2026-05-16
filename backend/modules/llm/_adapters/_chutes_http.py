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
from shared.dtos.inference import CompletionMessage, CompletionRequest
from shared.dtos.llm import ModelMetaDto, ReasoningCapability, ToolCapability

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

    try:
        context_length = int(entry.get("context_length") or 0)
    except (ValueError, TypeError):
        _log.warning(
            "chutes_http.entry_to_meta: non-numeric context_length on %s",
            entry.get("id"),
        )
        return None
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
    a separate step (see ``_filter_to_whitelist`` in Task 4), invoked by
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

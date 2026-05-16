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

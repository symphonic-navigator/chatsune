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

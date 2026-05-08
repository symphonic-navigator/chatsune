"""Novita AI HTTP adapter — OpenAI-compatible Chat Completions.

Premium-only adapter: not user-creatable. Instantiated exclusively via
the Premium Provider resolver (see ``backend.modules.llm._resolver``).
Routes to Novita's open-source inference platform; we filter to text-
output, serverless, chat-typed models with a >=80k context window.

Structurally a slimmed-down clone of ``_openrouter_http.py``. The diff
vs OR is: no Anthropic-cache logic (Novita is open-source-only, not a
router), no OR-specific app-attribution headers, and a different model-
list schema. The shared OpenAI-compat SSE-helper extraction remains
deferred to its own session — helpers stay cloned per adapter for now.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._events import ProviderStreamEvent
from backend.modules.llm._adapters._types import ResolvedConnection
from shared.dtos.inference import CompletionRequest
from shared.dtos.llm import ModelMetaDto


class NovitaHttpAdapter(BaseAdapter):
    adapter_type = "novita_http"
    display_name = "Novita AI"
    view_id = "novita_http"
    secret_fields = frozenset({"api_key"})

    async def fetch_models(
        self, c: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        raise NotImplementedError

    async def stream_completion(
        self, c: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        raise NotImplementedError
        yield  # pragma: no cover  # makes the body an async generator

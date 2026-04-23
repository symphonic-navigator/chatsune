"""Nano-GPT HTTP adapter.

Implements the model catalogue (filter / pair / map via
``_nano_gpt_catalog``) and persists the pair map to Redis
(``_nano_gpt_pair_map``). ``stream_completion`` is deliberately a
Phase-2 stub — the upstream routing logic lives in a follow-up
session alongside the full SSE loop.

Key design note — **do not** send ``reasoning`` or ``thinking`` flags
in the request body. Nano-GPT does not honour them; thinking is
switched exclusively by picking the ``thinking_slug`` from the pair
map as the upstream model. This differs from the Ollama adapter's
``"think"`` payload attachment and must not be copied here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._events import ProviderStreamEvent
from backend.modules.llm._adapters._types import (
    AdapterTemplate,
    ConfigFieldHint,
    ResolvedConnection,
)
from shared.dtos.inference import CompletionRequest
from shared.dtos.llm import ModelMetaDto


class NanoGptHttpAdapter(BaseAdapter):
    adapter_type = "nano_gpt_http"
    display_name = "Nano-GPT"
    view_id = "nano_gpt_http"
    secret_fields = frozenset({"api_key"})

    @classmethod
    def templates(cls) -> list[AdapterTemplate]:
        return [
            AdapterTemplate(
                id="nano_gpt_default",
                display_name="Nano-GPT",
                slug_prefix="nano",
                config_defaults={
                    "base_url": "https://api.nano-gpt.com/v1",
                    "api_key": "",
                    "max_parallel": 3,
                },
                required_config_fields=("api_key",),
            ),
        ]

    @classmethod
    def config_schema(cls) -> list[ConfigFieldHint]:
        return [
            ConfigFieldHint(
                name="base_url",
                type="url",
                label="Base URL",
                required=False,
                placeholder="https://api.nano-gpt.com/v1",
            ),
            ConfigFieldHint(
                name="api_key",
                type="secret",
                label="API Key",
                required=True,
            ),
            ConfigFieldHint(
                name="max_parallel",
                type="integer",
                label="Max parallel inferences",
                min=1,
                max=32,
            ),
        ]

    async def fetch_models(
        self, connection: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        raise NotImplementedError(
            "wired in Task 8 of the nano-gpt port plan",
        )

    async def stream_completion(
        self, connection: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        raise NotImplementedError(
            "Nano-GPT stream_completion is Phase 2 — see "
            "devdocs/superpowers/plans/2026-04-23-nano-gpt-adapter-port.md",
        )
        yield  # pragma: no cover — makes the function an async generator

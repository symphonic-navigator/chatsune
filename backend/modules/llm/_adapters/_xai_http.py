"""xAI HTTP adapter — Chat Completions (legacy) for Grok 4.1 Fast."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._events import ProviderStreamEvent, StreamError
from backend.modules.llm._adapters._types import (
    AdapterTemplate,
    ConfigFieldHint,
    ResolvedConnection,
)
from shared.dtos.inference import CompletionRequest
from shared.dtos.llm import ModelMetaDto

_log = logging.getLogger(__name__)


class XaiHttpAdapter(BaseAdapter):
    adapter_type = "xai_http"
    display_name = "xAI / Grok"
    view_id = "xai_http"
    secret_fields = frozenset({"api_key"})

    @classmethod
    def templates(cls) -> list[AdapterTemplate]:
        return [
            AdapterTemplate(
                id="xai_cloud",
                display_name="xAI Cloud",
                slug_prefix="xai",
                config_defaults={
                    "url": "https://api.x.ai/v1",
                    "api_key": "",
                    "max_parallel": 4,
                },
                required_config_fields=("api_key",),
            ),
        ]

    @classmethod
    def config_schema(cls) -> list[ConfigFieldHint]:
        return [
            ConfigFieldHint(
                name="url", type="url", label="URL",
                placeholder="https://api.x.ai/v1",
            ),
            ConfigFieldHint(
                name="api_key", type="secret", label="API Key",
            ),
            ConfigFieldHint(
                name="max_parallel", type="integer",
                label="Max parallel inferences",
                min=1, max=32,
            ),
        ]

    async def fetch_models(
        self, c: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        return [
            ModelMetaDto(
                connection_id=c.id,
                connection_display_name=c.display_name,
                connection_slug=c.slug,
                model_id="grok-4.1-fast",
                display_name="Grok 4.1 Fast",
                context_window=200_000,
                supports_reasoning=True,
                supports_vision=True,
                supports_tool_calls=True,
            ),
        ]

    async def stream_completion(
        self, c: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        # Stub — real implementation lands in Task 9.
        yield StreamError(
            error_code="provider_unavailable",
            message="xai_http stream_completion not implemented yet",
        )

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

import httpx
from redis.asyncio import Redis

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._events import ProviderStreamEvent
from backend.modules.llm._adapters._nano_gpt_catalog import build_catalogue
from backend.modules.llm._adapters._nano_gpt_pair_map import save_pair_map
from backend.modules.llm._adapters._types import (
    AdapterTemplate,
    ConfigFieldHint,
    ResolvedConnection,
)
from shared.dtos.inference import CompletionRequest
from shared.dtos.llm import ModelMetaDto

_DEFAULT_BASE_URL = "https://api.nano-gpt.com/v1"
_TIMEOUT = 30.0


async def _http_get_models(
    *, base_url: str, api_key: str, timeout: float = _TIMEOUT,
) -> list[dict]:
    """Fetch the raw nano-gpt model list.

    Nano-GPT exposes ``/v1/models?detailed=true`` in the OpenAI-compatible
    envelope ``{"data": [...]}``. Returns the ``data`` list verbatim.
    """
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            f"{base_url.rstrip('/')}/models",
            params={"detailed": "true"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()
        payload = resp.json()
    return payload.get("data", [])


class NanoGptHttpAdapter(BaseAdapter):
    adapter_type = "nano_gpt_http"
    display_name = "Nano-GPT"
    view_id = "nano_gpt_http"
    secret_fields = frozenset({"api_key"})

    def __init__(self, *, redis: Redis | None = None) -> None:
        self._redis = redis

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
        if self._redis is None:
            raise RuntimeError(
                "NanoGptHttpAdapter requires a Redis client for pair-map "
                "persistence — construct with redis= kwarg",
            )
        base_url = connection.config.get("base_url") or _DEFAULT_BASE_URL
        api_key = connection.config["api_key"]

        raw = await _http_get_models(base_url=base_url, api_key=api_key)
        result = build_catalogue(raw)

        # ``build_catalogue`` returns adapter-internal "block" dicts, not
        # ``ModelMetaDto`` instances — the adapter rehydrates them into
        # DTOs and overlays the connection fields. ``billing_category``
        # is set by ``to_model_meta`` and passed through via ``_block``,
        # so no derivation happens here.
        dtos: list[ModelMetaDto] = []
        for block in result.canonical:
            dtos.append(
                ModelMetaDto(
                    connection_id=connection.id,
                    connection_slug=connection.slug,
                    connection_display_name=connection.display_name,
                    model_id=block["model_id"],
                    display_name=block["display_name"],
                    context_window=block["context_window"],
                    supports_reasoning=block["supports_reasoning"],
                    supports_vision=block["supports_vision"],
                    supports_tool_calls=block["supports_tool_calls"],
                    billing_category=block["billing_category"],
                )
            )

        await save_pair_map(
            self._redis,
            connection_id=connection.id,
            pair_map=result.pair_map,
        )
        return dtos

    async def stream_completion(
        self, connection: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        raise NotImplementedError(
            "Nano-GPT stream_completion is Phase 2 — see "
            "devdocs/superpowers/plans/2026-04-23-nano-gpt-adapter-port.md",
        )
        yield  # pragma: no cover — makes the function an async generator

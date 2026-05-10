"""DeepSeek V4 driver (Pro and Flash). Plan 1: OpenRouter only.

See devdocs/specs/driver-layer.md and devdocs/research/deepseek-v4-wire-shapes.md.
"""
from __future__ import annotations

from typing import Any

from backend.modules.llm._adapters._events import ProviderStreamEvent
from backend.modules.llm._capabilities import ResolvedCapabilities
from backend.modules.llm._drivers.deepseek_v4._builders import (
    build_request_for_ollama_cloud,
    build_request_for_openrouter,
)
from backend.modules.llm._drivers.deepseek_v4._capability import (
    deepseek_v4_capability_spec,
)
from backend.modules.llm._drivers.deepseek_v4._parsers import (
    parse_chunk_ollama_cloud,
    parse_chunk_openrouter,
)
from shared.dtos.inference import CompletionRequest


class DeepSeekV4Driver:
    """Driver for DeepSeek V4 Pro and DeepSeek V4 Flash.

    Plan 1: OpenRouter. Plan 2: + Ollama Cloud (this class). Plans 3-4 add
    Novita and nano-gpt.
    """

    PATTERNS: list[str] = [
        "deepseek-v4-pro*",
        "deepseek-v4-flash*",
    ]

    def capability_spec(
        self, *, adapter_type: str, slug: str,
    ) -> ResolvedCapabilities:
        return deepseek_v4_capability_spec(adapter_type=adapter_type, slug=slug)

    def build_request(
        self, *, adapter_type: str, slug: str, request: CompletionRequest,
    ) -> dict[str, Any]:
        if adapter_type == "openrouter_http":
            return build_request_for_openrouter(slug=slug, request=request)
        if adapter_type == "ollama_http":
            return build_request_for_ollama_cloud(slug=slug, request=request)
        raise NotImplementedError(
            f"DeepSeekV4Driver: adapter_type={adapter_type!r} not supported "
            f"yet (Plan 2 covers openrouter_http + ollama_http; Plans 3-4 "
            f"add novita_http and nano_gpt_http)."
        )

    def parse_chunk(
        self, *, adapter_type: str, slug: str, chunk: dict[str, Any],
    ) -> list[ProviderStreamEvent]:
        if adapter_type == "openrouter_http":
            return parse_chunk_openrouter(chunk=chunk)
        if adapter_type == "ollama_http":
            return parse_chunk_ollama_cloud(chunk=chunk)
        raise NotImplementedError(
            f"DeepSeekV4Driver: adapter_type={adapter_type!r} not supported "
            f"yet (Plan 2 covers openrouter_http + ollama_http; Plans 3-4 "
            f"add novita_http and nano_gpt_http)."
        )

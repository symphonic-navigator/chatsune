"""DeepSeek V4 driver (Pro and Flash).

Wire support: OpenRouter, Ollama Cloud, Novita.
Capability-only: nano-gpt (see INSIGHTS.md INS-043).

See devdocs/specs/driver-layer.md and devdocs/research/deepseek-v4-wire-shapes.md.
"""
from __future__ import annotations

from typing import Any

from backend.modules.llm._adapters._events import ProviderStreamEvent
from backend.modules.llm._capabilities import ResolvedCapabilities
from backend.modules.llm._drivers._tool_call_accumulator import (
    ToolCallAccumulator,
)
from backend.modules.llm._drivers.deepseek_v4._builders import (
    build_request_for_novita,
    build_request_for_ollama_cloud,
    build_request_for_openrouter,
)
from backend.modules.llm._drivers.deepseek_v4._capability import (
    deepseek_v4_capability_spec,
)
from backend.modules.llm._drivers.deepseek_v4._parsers import (
    parse_chunk_novita,
    parse_chunk_ollama_cloud,
    parse_chunk_openrouter,
)
from shared.dtos.inference import CompletionRequest


class DeepSeekV4Driver:
    """Driver for DeepSeek V4 Pro and DeepSeek V4 Flash.

    Wire support: OpenRouter, Ollama Cloud, Novita (per-adapter
    builders + parsers). Capability-only support: nano-gpt — the
    driver supplies the canonical DSv4 capability spec while the
    nano-gpt adapter retains full ownership of wire-shape translation
    (slug-pair switching, OR-style reasoning parsing, atomic
    tool-call delivery).
    """

    PATTERNS: list[str] = [
        "deepseek-v4-pro*",
        "deepseek-v4-flash*",
    ]

    # nano-gpt is capability-only: the driver provides the canonical
    # DSv4 capability spec for nano-gpt listings, but the nano-gpt
    # adapter retains full ownership of wire-shape translation and
    # never calls ``match_driver``. Listing on the other three is
    # full wire + capability support.
    SUPPORTED_ADAPTERS: frozenset[str] = frozenset({
        "openrouter_http",
        "novita_http",
        "ollama_http",
        "nano_gpt_http",
    })

    def __init__(self) -> None:
        # Per-stream state: a fresh driver instance is created in each
        # adapter's ``stream_completion`` (``driver = driver_cls()``), so
        # the accumulator is naturally scoped to one inference iteration.
        # OpenRouter and Novita both stream OpenAI-fragmented tool-calls
        # and need their own accumulators; the Ollama parser is stateless.
        self._or_tool_acc = ToolCallAccumulator()
        self._novita_tool_acc = ToolCallAccumulator()

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
        if adapter_type == "novita_http":
            return build_request_for_novita(slug=slug, request=request)
        raise NotImplementedError(
            f"DeepSeekV4Driver: adapter_type={adapter_type!r} has no driver-level "
            f"wire support. nano_gpt_http is capability-only by design — the "
            f"adapter's own slug-pair switching and OR-style chunk parser are "
            f"sufficient. Other adapter_types: not yet integrated."
        )

    def parse_chunk(
        self, *, adapter_type: str, slug: str, chunk: dict[str, Any],
    ) -> list[ProviderStreamEvent]:
        if adapter_type == "openrouter_http":
            return parse_chunk_openrouter(
                chunk=chunk, tool_acc=self._or_tool_acc,
            )
        if adapter_type == "ollama_http":
            return parse_chunk_ollama_cloud(chunk=chunk)
        if adapter_type == "novita_http":
            return parse_chunk_novita(
                chunk=chunk, tool_acc=self._novita_tool_acc,
            )
        raise NotImplementedError(
            f"DeepSeekV4Driver: adapter_type={adapter_type!r} has no driver-level "
            f"wire support. nano_gpt_http is capability-only by design — the "
            f"adapter's own slug-pair switching and OR-style chunk parser are "
            f"sufficient. Other adapter_types: not yet integrated."
        )

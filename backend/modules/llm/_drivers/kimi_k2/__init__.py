"""Kimi K2 driver (K2.5 + K2.6) on Ollama Cloud and Novita.

Wire support: ``ollama_http``, ``novita_http``. Other adapter_types
raise ``NotImplementedError`` — Kimi is not exposed elsewhere today.

Capability matrix (probed 2026-05-12):

| Slug basename | adapter_type    | reasoning.kind | tools |
|---------------|-----------------|----------------|-------|
| kimi-k2.5*    | ollama_http     | optional       | true  |
| kimi-k2.6*    | ollama_http     | optional       | true  |
| kimi-k2.5*    | novita_http     | no_reasoning   | true  |
| kimi-k2.6*    | novita_http     | always_on      | true  |

Kimi does NOT exhibit the MiMo-on-Novita chat-template bug; tool-call
roundtrip succeeds on every cell.

See devdocs/specs/driver-layer.md and
devdocs/research/kimi-k2-wire-shapes.md.
"""
from __future__ import annotations

from typing import Any

from backend.modules.llm._adapters._events import ProviderStreamEvent
from backend.modules.llm._capabilities import ResolvedCapabilities
from backend.modules.llm._drivers._tool_call_accumulator import (
    ToolCallAccumulator,
)
from backend.modules.llm._drivers.kimi_k2._builders import (
    build_request_for_novita,
    build_request_for_ollama_cloud,
)
from backend.modules.llm._drivers.kimi_k2._helpers import (
    _SUPPORTED_ADAPTERS,
    _unsupported_adapter,
)
from backend.modules.llm._drivers.kimi_k2._capability import (
    kimi_k2_capability_spec,
)
from backend.modules.llm._drivers.kimi_k2._parsers import (
    parse_chunk_novita,
    parse_chunk_ollama_cloud,
)
from shared.dtos.inference import CompletionRequest


class KimiK2Driver:
    """Driver for Kimi K2.5 and K2.6 on Ollama Cloud and Novita.

    Wire support: ``ollama_http``, ``novita_http``. Other adapter_types
    raise ``NotImplementedError`` from all three driver methods.
    """

    PATTERNS: list[str] = [
        "kimi-k2.5*",
        "kimi-k2.6*",
    ]

    # Adapter-aware ``match_driver`` consults this set; the helper
    # module ``_helpers.py`` remains the single source of truth so the
    # internal ``_unsupported_adapter`` defence-in-depth guard cannot
    # drift from the class attribute.
    SUPPORTED_ADAPTERS: frozenset[str] = _SUPPORTED_ADAPTERS

    def __init__(self) -> None:
        # Per-stream state: a fresh driver instance is created in the
        # adapter's ``stream_completion`` (``driver = driver_cls()``), so
        # the accumulator is naturally scoped to one inference iteration.
        # Novita streams OpenAI-fragmented tool-calls and needs its own
        # accumulator. The Ollama parser is stateless (atomic tool_calls).
        self._novita_tool_acc = ToolCallAccumulator()

    def capability_spec(
        self, *, adapter_type: str, slug: str,
    ) -> ResolvedCapabilities:
        if adapter_type not in _SUPPORTED_ADAPTERS:
            raise _unsupported_adapter(adapter_type)
        return kimi_k2_capability_spec(adapter_type=adapter_type, slug=slug)

    def build_request(
        self, *, adapter_type: str, slug: str, request: CompletionRequest,
    ) -> dict[str, Any]:
        if adapter_type == "ollama_http":
            return build_request_for_ollama_cloud(slug=slug, request=request)
        if adapter_type == "novita_http":
            return build_request_for_novita(slug=slug, request=request)
        raise _unsupported_adapter(adapter_type)

    def parse_chunk(
        self, *, adapter_type: str, slug: str, chunk: dict[str, Any],
    ) -> list[ProviderStreamEvent]:
        if adapter_type == "ollama_http":
            return parse_chunk_ollama_cloud(chunk=chunk)
        if adapter_type == "novita_http":
            return parse_chunk_novita(
                chunk=chunk, tool_acc=self._novita_tool_acc,
            )
        raise _unsupported_adapter(adapter_type)

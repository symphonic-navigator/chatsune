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
from backend.modules.llm._drivers.kimi_k2._capability import (
    kimi_k2_capability_spec,
)
from backend.modules.llm._drivers.kimi_k2._parsers import (
    parse_chunk_novita,
    parse_chunk_ollama_cloud,
)
from shared.dtos.inference import CompletionRequest


_SUPPORTED_ADAPTERS: frozenset[str] = frozenset({"ollama_http", "novita_http"})


def _unsupported_adapter(adapter_type: str) -> NotImplementedError:
    """Build the canonical 'adapter not supported' error.

    Re-used across the three driver methods so the message stays in sync.
    """
    return NotImplementedError(
        f"KimiK2Driver: adapter_type={adapter_type!r} has no driver-level "
        f"support. Kimi K2.5/K2.6 is wired for ollama_http and novita_http "
        f"only; other adapter_types are intentionally unsupported to avoid "
        f"silent capability/wire-shape drift."
    )


def _kimi_version(slug: str) -> str:
    """Return ``'k2.5'`` or ``'k2.6'`` for a Kimi slug, regardless of prefix.

    PATTERNS has already matched ``kimi-k2.5*`` or ``kimi-k2.6*`` against
    the slug basename before this is called, so the slug is guaranteed to
    contain one of those substrings. The publisher prefix
    (``moonshotai/...``) is stripped first for safety.
    """
    basename = slug.rsplit("/", 1)[-1]
    if basename.startswith("kimi-k2.6"):
        return "k2.6"
    if basename.startswith("kimi-k2.5"):
        return "k2.5"
    raise ValueError(
        f"_kimi_version: slug {slug!r} did not start with a known Kimi K2 "
        f"prefix; PATTERNS should have prevented this."
    )


class KimiK2Driver:
    """Driver for Kimi K2.5 and K2.6 on Ollama Cloud and Novita.

    Wire support: ``ollama_http``, ``novita_http``. Other adapter_types
    raise ``NotImplementedError`` from all three driver methods.
    """

    PATTERNS: list[str] = [
        "kimi-k2.5*",
        "kimi-k2.6*",
    ]

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

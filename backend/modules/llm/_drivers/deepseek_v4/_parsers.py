"""Response-chunk parsers for DeepSeek V4.

Plan 1 ships only the OpenRouter parser, which reads the OR-canonical
CoT key ``delta.reasoning`` (often paired with ``delta.reasoning_details``).
Plans 3-4 add the DeepSeek-native parser for Novita
(``delta.reasoning_content``) and the Ollama-native parser for Ollama
Cloud (``message.thinking`` over NDJSON).

This parser is a thin specialisation: the existing
``_openrouter_http._chunk_to_events`` covers most of what we need; we
duplicate the logic here so the driver fully owns the response shape
without touching the adapter's internal helper. Tool-call accumulation
is intentionally out of scope for Plan 1 — DSv4 + tools is a Plan 2+
concern (covered in the spec's worked example) but not yet wired here.
"""
from __future__ import annotations

from typing import Any

from backend.modules.llm._adapters._events import (
    ContentDelta,
    ProviderStreamEvent,
    StreamDone,
    ThinkingDelta,
)


def parse_chunk_openrouter(*, chunk: dict[str, Any]) -> list[ProviderStreamEvent]:
    """Translate one OR SSE chunk dict into ProviderStreamEvents."""
    events: list[ProviderStreamEvent] = []

    choices = chunk.get("choices") or []
    if choices:
        delta = choices[0].get("delta") or {}

        # Visible content fragment
        content = delta.get("content")
        if content:
            events.append(ContentDelta(delta=content))

        # OR-canonical reasoning fragment (mapped to ThinkingDelta —
        # "reasoning" and "thinking" are used interchangeably in the
        # codebase per INS-038).
        reasoning = delta.get("reasoning")
        if reasoning:
            events.append(ThinkingDelta(delta=reasoning))

    # Terminal usage block (chunk with finish_reason or final usage info)
    usage = chunk.get("usage")
    if usage is not None:
        details = usage.get("completion_tokens_details") or {}
        events.append(StreamDone(
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            reasoning_tokens=details.get("reasoning_tokens"),
        ))

    return events

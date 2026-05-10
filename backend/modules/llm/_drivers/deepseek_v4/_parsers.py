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
    StreamRefused,
    ThinkingDelta,
)


# Mirrors _ollama_http._REFUSAL_REASONS — keeping a local copy avoids
# importing adapter internals from the driver layer.
_REFUSAL_REASONS: frozenset[str] = frozenset({"content_filter", "refusal"})


def parse_chunk_openrouter(*, chunk: dict[str, Any]) -> list[ProviderStreamEvent]:
    """Translate one OR SSE chunk dict into ProviderStreamEvents."""
    events: list[ProviderStreamEvent] = []

    choices = chunk.get("choices") or []
    if choices:
        choice = choices[0]
        delta = choice.get("delta") or {}

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

        # Refusal: parity with _openrouter_http._chunk_to_events. Without
        # this the driver path silently drops refusals; the legacy path
        # surfaces them as StreamRefused.
        finish = choice.get("finish_reason")
        if finish and finish.lower() in _REFUSAL_REASONS:
            events.append(StreamRefused(
                reason=finish,
                refusal_text=delta.get("refusal") or None,
            ))

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


def parse_chunk_ollama_cloud(*, chunk: dict[str, Any]) -> list[ProviderStreamEvent]:
    """Translate one Ollama Cloud NDJSON-decoded chunk into ProviderStreamEvents.

    Ollama Cloud uses the native Ollama envelope (no OpenAI ``choices``
    list). Each chunk contains a ``message`` block with ``content`` and
    optional ``thinking``; the final chunk has ``done=True`` plus
    ``prompt_eval_count`` and ``eval_count``. Refusals are signalled via
    ``done_reason in {content_filter, refusal}`` — emit ``StreamRefused``
    instead of ``StreamDone``.
    """
    events: list[ProviderStreamEvent] = []

    message = chunk.get("message") or {}

    # Visible content fragment
    content = message.get("content")
    if content:
        events.append(ContentDelta(delta=content))

    # Ollama-native CoT key. Mapped to ThinkingDelta (per INS-038, "thinking"
    # and "reasoning" are interchangeable in this codebase).
    thinking = message.get("thinking")
    if thinking:
        events.append(ThinkingDelta(delta=thinking))

    # Terminal handling
    if chunk.get("done"):
        done_reason = chunk.get("done_reason")
        if done_reason and done_reason.lower() in _REFUSAL_REASONS:
            events.append(StreamRefused(
                reason=done_reason,
                refusal_text=message.get("refusal") or None,
            ))
        else:
            events.append(StreamDone(
                input_tokens=chunk.get("prompt_eval_count"),
                output_tokens=chunk.get("eval_count"),
                # Ollama Cloud bundles reasoning into eval_count — no separate
                # reasoning_tokens field. Leave it as None.
            ))

    return events

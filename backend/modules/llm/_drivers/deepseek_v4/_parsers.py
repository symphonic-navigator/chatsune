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

import json
from typing import Any
from uuid import uuid4

from backend.modules.llm._adapters._events import (
    ContentDelta,
    ProviderStreamEvent,
    StreamDone,
    StreamRefused,
    ThinkingDelta,
    ToolCallEvent,
)
from backend.modules.llm._drivers._tool_call_accumulator import (
    ToolCallAccumulator,
)


# Mirrors _ollama_http._REFUSAL_REASONS — keeping a local copy avoids
# importing adapter internals from the driver layer.
_REFUSAL_REASONS: frozenset[str] = frozenset({"content_filter", "refusal"})


def parse_chunk_openrouter(
    *,
    chunk: dict[str, Any],
    tool_acc: ToolCallAccumulator | None = None,
) -> list[ProviderStreamEvent]:
    """Translate one OR SSE chunk dict into ProviderStreamEvents.

    When ``tool_acc`` is supplied, OpenAI-style streaming tool-call
    fragments in ``delta.tool_calls`` are accumulated; on
    ``finish_reason="tool_calls"`` the accumulator is finalised and one
    ``ToolCallEvent`` per accumulated call is appended in index order.
    Without ``tool_acc`` (or when no fragments arrive) tool-calls are
    silently skipped — defensive default for callers that don't need
    tool-call handling. The current production caller (DeepSeekV4Driver)
    always supplies an accumulator.
    """
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

        # Tool-call fragments — OR streams them incrementally
        # (OpenAI-style). Accumulator state is owned by the driver-class
        # instance (one per stream); the parser stays pure-by-arg.
        tool_frags = delta.get("tool_calls") or []
        if tool_frags and tool_acc is not None:
            tool_acc.ingest(tool_frags)

        # Refusal: parity with _openrouter_http._chunk_to_events. Without
        # this the driver path silently drops refusals; the legacy path
        # surfaces them as StreamRefused.
        finish = choice.get("finish_reason")
        if finish and finish.lower() in _REFUSAL_REASONS:
            events.append(StreamRefused(
                reason=finish,
                refusal_text=delta.get("refusal") or None,
            ))
        elif finish == "tool_calls" and tool_acc is not None:
            for call in tool_acc.finalised():
                events.append(ToolCallEvent(
                    id=call["id"],
                    name=call["name"],
                    arguments=call["arguments"],
                ))

    # Terminal usage block (chunk with finish_reason or final usage info).
    # Guard against co-emitting StreamDone when StreamRefused was already
    # appended — the two events are mutually exclusive terminal states.
    # Note: ToolCallEvent + StreamDone CAN co-occur on the same chunk —
    # OR delivers usage in the same chunk as ``finish_reason="tool_calls"``
    # (verified by probe; see deepseek-v4-wire-shapes.md). This is a
    # deliberate behavioural improvement over the legacy _chunk_to_events
    # path, which drops StreamDone in that case (latent token-accounting
    # gap on tool-call iterations); the driver path captures the usage so
    # iter_input_tokens/iter_output_tokens are populated for tool-call
    # iterations too.
    usage = chunk.get("usage")
    if usage is not None and not any(isinstance(e, StreamRefused) for e in events):
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

    # Tool-calls — Ollama Cloud delivers these atomically per chunk
    # (one chunk holds the complete list of tool-calls; no incremental
    # accumulation across chunks). See
    # devdocs/research/ollama-cloud-tool-calls.md.
    for tc in message.get("tool_calls") or []:
        fn = tc.get("function") or {}
        events.append(ToolCallEvent(
            id=tc.get("id") or f"call_{uuid4().hex[:12]}",
            name=fn.get("name", ""),
            arguments=json.dumps(fn.get("arguments") or {}),
        ))

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


def parse_chunk_novita(
    *,
    chunk: dict[str, Any],
    tool_acc: ToolCallAccumulator | None = None,
) -> list[ProviderStreamEvent]:
    """Translate one Novita SSE chunk dict into ProviderStreamEvents.

    Wire-shape mirrors the OpenAI-compat pattern (same as OR), with two
    differences:
    - CoT key is ``delta.reasoning_content`` (DeepSeek-native), NOT OR's
      ``delta.reasoning``. Probed 2026-05-10; Novita never emits the
      OR-legacy key, so this parser does not look at it.
    - Tool-call streaming is OpenAI-fragmented and indexed; the
      ``ToolCallAccumulator`` (shared with OR) handles accumulation.

    See ``parse_chunk_openrouter`` for the symmetric implementation;
    duplication is intentional so each driver fully owns its chunk
    semantics. ``StreamRefused`` and ``StreamDone`` are mutually
    exclusive terminal states (same guard as OR).
    """
    events: list[ProviderStreamEvent] = []

    choices = chunk.get("choices") or []
    if choices:
        choice = choices[0]
        delta = choice.get("delta") or {}

        # Visible content fragment
        content = delta.get("content")
        if content:
            events.append(ContentDelta(delta=content))

        # DeepSeek-native CoT key. Mapped to ThinkingDelta per INS-038.
        reasoning_content = delta.get("reasoning_content")
        if reasoning_content:
            events.append(ThinkingDelta(delta=reasoning_content))

        # Tool-call fragments — OpenAI-style streaming, accumulator owned
        # by the driver-class instance (one per stream); parser stays
        # pure-by-arg.
        tool_frags = delta.get("tool_calls") or []
        if tool_frags and tool_acc is not None:
            tool_acc.ingest(tool_frags)

        # Refusal: parity with parse_chunk_openrouter.
        finish = choice.get("finish_reason")
        if finish and finish.lower() in _REFUSAL_REASONS:
            events.append(StreamRefused(
                reason=finish,
                refusal_text=delta.get("refusal") or None,
            ))
        elif finish == "tool_calls" and tool_acc is not None:
            for call in tool_acc.finalised():
                events.append(ToolCallEvent(
                    id=call["id"],
                    name=call["name"],
                    arguments=call["arguments"],
                ))

    # Terminal usage block. Same StreamRefused-co-emit guard as OR.
    # ToolCallEvent + StreamDone CAN co-occur on the same chunk —
    # Novita delivers usage in the same chunk as
    # ``finish_reason="tool_calls"`` (verified 2026-05-10).
    usage = chunk.get("usage")
    if usage is not None and not any(isinstance(e, StreamRefused) for e in events):
        details = usage.get("completion_tokens_details") or {}
        events.append(StreamDone(
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            reasoning_tokens=details.get("reasoning_tokens"),
        ))

    return events

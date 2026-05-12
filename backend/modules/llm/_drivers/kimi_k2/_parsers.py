"""Response-chunk parsers for Kimi K2.5 / K2.6.

Per the driver-layer spec, each driver fully owns its chunk semantics —
the logic in this file is structurally identical to DSv4's Ollama and
Novita parsers but is intentionally NOT imported from there. Duplication
prevents a Kimi change from accidentally affecting DSv4 (and vice versa).
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


# Local copy of refusal markers — keeps the driver free of adapter
# internals (per the Driver-Layer spec boundary). Same set as MiMo/DSv4.
_REFUSAL_REASONS: frozenset[str] = frozenset({"content_filter", "refusal"})


def parse_chunk_ollama_cloud(*, chunk: dict[str, Any]) -> list[ProviderStreamEvent]:
    """Translate one Ollama Cloud NDJSON-decoded chunk into events.

    Ollama Cloud uses the native Ollama envelope (no OpenAI ``choices``
    list). Each chunk contains a ``message`` block with ``content`` and
    optional ``thinking``; the final chunk has ``done=True`` plus
    ``prompt_eval_count`` and ``eval_count``. Refusals are signalled via
    ``done_reason in {content_filter, refusal}`` — emit ``StreamRefused``
    instead of ``StreamDone``.

    Tool-calls arrive atomically: a single chunk holds the complete list
    of calls with object-valued ``arguments`` that must be JSON-stringified
    to match ``ToolCallEvent.arguments: str``.

    Logic is structurally identical to ``deepseek_v4._parsers.parse_chunk_ollama_cloud``
    but is intentionally NOT imported from there (per driver-layer spec).
    """
    events: list[ProviderStreamEvent] = []

    message = chunk.get("message") or {}

    # Visible content fragment
    content = message.get("content")
    if content:
        events.append(ContentDelta(delta=content))

    # Ollama-native CoT key. Mapped to ThinkingDelta per INS-038.
    thinking = message.get("thinking")
    if thinking:
        events.append(ThinkingDelta(delta=thinking))

    # Atomic tool-calls (no incremental accumulation across chunks).
    for tc in message.get("tool_calls") or []:
        fn = tc.get("function") or {}
        events.append(ToolCallEvent(
            id=tc.get("id") or f"call_{uuid4().hex[:12]}",
            name=fn.get("name", ""),
            arguments=json.dumps(fn.get("arguments") or {}),
        ))

    # Terminal handling: StreamRefused / StreamDone are mutually exclusive.
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
                # Ollama Cloud bundles reasoning into eval_count — no
                # separate reasoning_tokens field. Leave as None.
            ))

    return events


def parse_chunk_novita(
    *, chunk: dict[str, Any], tool_acc: ToolCallAccumulator,
) -> list[ProviderStreamEvent]:
    """Translate one Novita SSE chunk dict into ProviderStreamEvents.

    Wire-shape is OpenAI-compat with the DeepSeek-native CoT key
    ``delta.reasoning_content`` (probe 2026-05-12: K2.6 emits this key;
    K2.5 omits it, which is fine — the .get() returns None). Tool-call
    streaming is OpenAI-fragmented (id+name first, then arguments string
    fragments under the same index); the accumulator handles assembly.

    Logic is structurally identical to ``deepseek_v4._parsers.parse_chunk_novita``
    but is intentionally NOT imported from there (per driver-layer spec).

    ``StreamRefused`` and ``StreamDone`` are mutually exclusive terminal
    states. ``ToolCallEvent`` + ``StreamDone`` CAN co-occur — Novita
    delivers usage in the same chunk as ``finish_reason='tool_calls'``.
    """
    events: list[ProviderStreamEvent] = []

    choices = chunk.get("choices") or []
    if choices:
        choice = choices[0]
        delta = choice.get("delta") or {}

        content = delta.get("content")
        if content:
            events.append(ContentDelta(delta=content))

        reasoning_content = delta.get("reasoning_content")
        if reasoning_content:
            events.append(ThinkingDelta(delta=reasoning_content))

        tool_frags = delta.get("tool_calls") or []
        if tool_frags:
            tool_acc.ingest(tool_frags)

        finish = choice.get("finish_reason")
        if finish and finish.lower() in _REFUSAL_REASONS:
            events.append(StreamRefused(
                reason=finish,
                refusal_text=delta.get("refusal") or None,
            ))
        elif finish == "tool_calls":
            for call in tool_acc.finalised():
                events.append(ToolCallEvent(
                    id=call["id"],
                    name=call["name"],
                    arguments=call["arguments"],
                ))

    usage = chunk.get("usage")
    if usage is not None and not any(isinstance(e, StreamRefused) for e in events):
        details = usage.get("completion_tokens_details") or {}
        events.append(StreamDone(
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            reasoning_tokens=details.get("reasoning_tokens"),
        ))

    return events

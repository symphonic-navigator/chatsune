"""MiMo v2.5 Pro driver (Novita-only).

Single-file driver: MiMo v2.5 Pro is only supported on Novita Premium and
exposes a single off-knob (no effort buckets), so the scope is much
narrower than DSv4 and a directory layout would add structure without
content.

Wire support: Novita.
Capability-only / unsupported elsewhere: openrouter_http, nano_gpt_http,
ollama_http all raise ``NotImplementedError`` from ``capability_spec``,
``build_request`` and ``parse_chunk`` — MiMo is not exposed via any other
adapter today and silently falling back to a generic capability would
mask an unsupported route.

Probe summary (2026-05-12, slug ``xiaomimimo/mimo-v2.5-pro``):
- Default: reasoning_content is emitted (reasoning_tokens > 0).
- ``reasoning: {enabled: false}`` does NOT suppress reasoning at Novita.
- Top-level ``enable_thinking: false`` cleanly suppresses reasoning
  (reasoning_content: null, reasoning_tokens: 0).
- Tool calls work with reasoning on AND with reasoning off via
  ``enable_thinking: false``.

The off-path wire shape mirrors DSv4-on-Novita's off-path (drop the
``reasoning`` block, set top-level ``enable_thinking: false``).

See devdocs/specs/driver-layer.md.
"""
from __future__ import annotations

from typing import Any

from backend.modules.llm._adapters._events import (
    ContentDelta,
    ProviderStreamEvent,
    StreamDone,
    StreamRefused,
    ThinkingDelta,
    ToolCallEvent,
)
from backend.modules.llm._capabilities import ResolvedCapabilities
from backend.modules.llm._drivers._tool_call_accumulator import (
    ToolCallAccumulator,
)
from shared.dtos.inference import CompletionRequest
from shared.dtos.llm import (
    ReasoningCapability,
    ToolCapability,
)


# Local copy of refusal markers — keeps the driver free of adapter
# internals (per the Driver-Layer spec boundary).
_REFUSAL_REASONS: frozenset[str] = frozenset({"content_filter", "refusal"})


def _unsupported_adapter(adapter_type: str) -> NotImplementedError:
    """Build the canonical 'adapter not supported' error.

    Re-used across the three driver methods so the message stays in sync.
    """
    return NotImplementedError(
        f"MiMoV25Driver: adapter_type={adapter_type!r} has no driver-level "
        f"support. MiMo v2.5 Pro is a Novita-only integration today; other "
        f"adapter_types are intentionally unsupported to avoid silent "
        f"capability/wire-shape drift."
    )


def _build_request_for_novita(
    *, request: CompletionRequest,
) -> dict[str, Any]:
    """Build the Novita request body for MiMo v2.5 Pro.

    Strategy: delegate to the existing ``_novita_http.build_request_body``
    so message translation, tools-gating, and the base reasoning block
    are inherited. Then, when reasoning is off, drop the ineffective
    ``reasoning: {enabled: false}`` and write the wire-signal Novita
    actually honours for MiMo (``enable_thinking: false``).

    The reasoning-on path needs no mutation — Novita defaults the
    ``reasoning: {enabled: true}`` shape to the model's standard thinking
    mode, which matches probe results.
    """
    # Local import to avoid a circular dependency at module load time
    # (drivers depend on adapter helpers; the adapter consults drivers
    # at call time).
    from backend.modules.llm._adapters._novita_http import (
        build_request_body as _novita_build_request_body,
    )

    base = _novita_build_request_body(request)

    if request.extras.reasoning_mode == "off":
        # Same fix pattern as DSv4-on-Novita off-path: the unified
        # OpenRouter shape ``reasoning: {enabled: false}`` is silently
        # ignored by Novita for this model; only the vLLM-style top-level
        # ``enable_thinking: false`` suppresses CoT cleanly.
        base.pop("reasoning", None)
        base["enable_thinking"] = False

    return base


def _parse_chunk_novita(
    *,
    chunk: dict[str, Any],
    tool_acc: ToolCallAccumulator,
) -> list[ProviderStreamEvent]:
    """Translate one Novita SSE chunk dict into ProviderStreamEvents.

    Wire-shape mirrors DSv4-on-Novita: OpenAI-compat with the DeepSeek-
    native CoT key ``delta.reasoning_content`` and OpenAI-fragmented
    tool-call streaming. Logic is duplicated by design (per the
    driver-layer spec) so each driver fully owns its chunk semantics —
    do NOT import DSv4's parser.

    ``StreamRefused`` and ``StreamDone`` are mutually exclusive terminal
    states; ``ToolCallEvent`` + ``StreamDone`` CAN co-occur on the same
    chunk (Novita emits the usage block alongside ``finish_reason="tool_calls"``).
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

        # DeepSeek-native CoT key — mapped to ThinkingDelta per INS-038
        # (thinking and reasoning are used interchangeably in this
        # codebase). MiMo does not emit OR's ``delta.reasoning`` key,
        # so we deliberately don't look at it (avoids any future
        # double-counting if Novita ever mirrored both keys).
        reasoning_content = delta.get("reasoning_content")
        if reasoning_content:
            events.append(ThinkingDelta(delta=reasoning_content))

        # OpenAI-fragmented tool-call streaming — accumulator state is
        # owned by the driver-class instance (one per stream); the
        # parser stays pure-by-arg.
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

    # Terminal usage block; skip when a StreamRefused was already
    # appended (refusal is the terminal event in that case).
    usage = chunk.get("usage")
    if usage is not None and not any(isinstance(e, StreamRefused) for e in events):
        details = usage.get("completion_tokens_details") or {}
        events.append(StreamDone(
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            reasoning_tokens=details.get("reasoning_tokens"),
        ))

    return events


class MiMoV25Driver:
    """Driver for MiMo v2.5 Pro on Novita Premium.

    Wire support: ``novita_http`` only. Other adapter_types raise
    ``NotImplementedError`` across all three methods — MiMo is not
    exposed via any other Chatsune adapter today and silently degrading
    to a generic capability would mask an unsupported route (the same
    failure mode the driver layer exists to prevent).
    """

    PATTERNS: list[str] = [
        "mimo-v2.5-pro*",
    ]

    # MiMo is a Novita-only integration today; the adapter-aware
    # ``match_driver`` will skip this driver entirely when listing
    # OR / nano-gpt / Ollama catalogues so the defensive
    # ``NotImplementedError`` in ``capability_spec`` cannot bubble up
    # through ``resolve_capabilities`` and break listing.
    SUPPORTED_ADAPTERS: frozenset[str] = frozenset({"novita_http"})

    def __init__(self) -> None:
        # Per-stream state: a fresh driver instance is created in the
        # adapter's ``stream_completion`` (``driver = driver_cls()``),
        # so the accumulator is naturally scoped to one inference
        # iteration. Novita streams OpenAI-fragmented tool-calls and
        # needs its own accumulator.
        self._novita_tool_acc = ToolCallAccumulator()

    def capability_spec(
        self, *, adapter_type: str, slug: str,
    ) -> ResolvedCapabilities:
        if adapter_type != "novita_http":
            raise _unsupported_adapter(adapter_type)
        # Probe 2026-05-12: Novita does not document or honour an
        # effort spec for MiMo, so we expose on/off only. Default-on
        # matches probe-observed default behaviour.
        return ResolvedCapabilities(
            reasoning=ReasoningCapability(
                kind="optional",
                effort=None,
                default_on=True,
            ),
            tools=ToolCapability(
                supported=True,
                exclusive_with_reasoning=False,
            ),
            first_class_support=True,
        )

    def build_request(
        self, *, adapter_type: str, slug: str, request: CompletionRequest,
    ) -> dict[str, Any]:
        if adapter_type != "novita_http":
            raise _unsupported_adapter(adapter_type)
        return _build_request_for_novita(request=request)

    def parse_chunk(
        self, *, adapter_type: str, slug: str, chunk: dict[str, Any],
    ) -> list[ProviderStreamEvent]:
        if adapter_type != "novita_http":
            raise _unsupported_adapter(adapter_type)
        return _parse_chunk_novita(
            chunk=chunk, tool_acc=self._novita_tool_acc,
        )

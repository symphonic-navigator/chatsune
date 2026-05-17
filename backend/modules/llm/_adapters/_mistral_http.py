"""Mistral HTTP adapter — OpenAI-compatible Chat Completions.

Hosts a curated three-model list (Mistral Small 4, Medium 3.5, Large 3)
against the official Mistral Cloud API. Reasoning is a binary toggle
because Mistral only accepts ``reasoning_effort`` values ``high`` and
``none`` for Small 4 / Medium 3.5; Large 3 has no reasoning. Mistral's
SSE stream uses a proprietary ``thinking``-block format inside
``delta.content`` (polymorphic: string or typed-item array) — see
``_translate_delta_content`` for the parser.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends

from backend._retry import (
    MAX_RETRY_ATTEMPTS,
    compute_retry_delay,
    log_retry,
    parse_retry_after,
    should_retry_status,
)
from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._events import (
    ContentDelta,
    ProviderStreamEvent,
    StreamAborted,
    StreamDone,
    StreamError,
    StreamRefused,
    StreamSlow,
    ThinkingDelta,
    ToolCallEvent,
)
from backend.modules.llm._adapters._types import ResolvedConnection
from shared.dtos.inference import CompletionMessage, CompletionRequest
from shared.dtos.llm import ModelMetaDto, ReasoningCapability, ToolCapability

_log = logging.getLogger(__name__)

# Opt-in payload tracing for cache-miss debugging. Enable via
# LLM_TRACE_PAYLOADS=1 in the environment; keep off in production.
_TRACE_PAYLOADS = os.environ.get("LLM_TRACE_PAYLOADS") == "1"

GUTTER_SLOW_SECONDS: float = 30.0
GUTTER_ABORT_SECONDS: float = float(
    os.environ.get("LLM_STREAM_ABORT_SECONDS", "120"),
)

_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=15.0)
_PROBE_TIMEOUT = httpx.Timeout(10.0)
_REFUSAL_REASONS: frozenset[str] = frozenset({"content_filter", "refusal"})

_SSE_DONE = object()  # sentinel — distinct from any JSON-decodable value


@dataclass(frozen=True)
class _MistralModelEntry:
    model_id: str            # persona-stable internal ID
    upstream_slug: str       # the slug we send to Mistral
    display_name: str
    context_window: int
    has_reasoning: bool      # True -> reasoning_effort toggle (high/none)
    supports_vision: bool
    supports_tool_calls: bool
    first_class_support: bool


_MISTRAL_MODELS: tuple[_MistralModelEntry, ...] = (
    _MistralModelEntry(
        model_id="mistral-small-4",
        upstream_slug="mistral-small-latest",
        display_name="Mistral Small 4",
        context_window=262_144,
        has_reasoning=True,
        supports_vision=True,
        supports_tool_calls=True,
        first_class_support=True,
    ),
    _MistralModelEntry(
        model_id="mistral-medium-3-5",
        upstream_slug="mistral-medium-3-5",
        display_name="Mistral Medium 3.5",
        context_window=262_144,
        has_reasoning=True,
        supports_vision=True,
        supports_tool_calls=True,
        first_class_support=True,
    ),
    _MistralModelEntry(
        model_id="mistral-large-3",
        upstream_slug="mistral-large-latest",
        display_name="Mistral Large 3",
        context_window=262_144,
        has_reasoning=False,
        supports_vision=True,
        supports_tool_calls=True,
        first_class_support=False,
    ),
)

_MISTRAL_MODELS_BY_ID: dict[str, _MistralModelEntry] = {
    m.model_id: m for m in _MISTRAL_MODELS
}


class _ToolCallAccumulator:
    """Gathers OpenAI-style tool_call fragments across SSE chunks.

    Upstream providers stream tool calls in pieces, indexed by
    ``tool_calls[].index``. Each fragment may carry id, name, or an
    arguments string fragment. We accumulate by index and finalise once
    the upstream signals ``finish_reason="tool_calls"``.
    """

    def __init__(self) -> None:
        self._by_index: dict[int, dict] = {}

    def ingest(self, fragments: list[dict]) -> None:
        for frag in fragments:
            idx = frag.get("index")
            if idx is None:
                continue
            slot = self._by_index.setdefault(idx, {
                "id": None, "name": "", "args": "",
            })
            if frag.get("id"):
                slot["id"] = frag["id"]
            fn = frag.get("function") or {}
            if fn.get("name"):
                slot["name"] = fn["name"]
            if fn.get("arguments"):
                slot["args"] += fn["arguments"]

    def finalised(self) -> list[dict]:
        """Return accumulated calls as [{id, name, arguments, index}, ...]."""
        calls: list[dict] = []
        for idx, slot in sorted(self._by_index.items()):
            calls.append({
                "id": slot["id"] or f"call_{uuid4().hex[:12]}",
                "name": slot["name"],
                "arguments": slot["args"] or "{}",
                "index": idx,
            })
        return calls


def _translate_delta_content(content: object) -> tuple[str, str]:
    """Return (visible_text, thinking_text) from Mistral's polymorphic delta.content.

    Mistral breaks from OpenAI's schema when reasoning is active: delta.content
    becomes a list of typed items {"type": "thinking" | "text", ...} rather
    than a plain string. We fold visible-text fragments and thinking-text
    fragments separately so _chunk_to_events can emit ContentDelta and
    ThinkingDelta cleanly.

    When reasoning_effort="none" (or for models without reasoning) Mistral
    keeps delta.content as a plain string — handled identically to the
    OpenAI path.
    """
    if isinstance(content, str):
        return content, ""
    if not isinstance(content, list):
        return "", ""
    visible: list[str] = []
    thinking: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "text":
            text = item.get("text")
            if isinstance(text, str):
                visible.append(text)
        elif kind == "thinking":
            for inner in item.get("thinking") or []:
                if not isinstance(inner, dict):
                    continue
                if inner.get("type") == "text":
                    text = inner.get("text")
                    if isinstance(text, str):
                        thinking.append(text)
        # other item types (e.g. future tool-call representation) are
        # ignored intentionally — tool_calls arrive on delta.tool_calls,
        # not inline in content.
    return "".join(visible), "".join(thinking)


def _chunk_to_events(
    chunk: dict,
    acc: _ToolCallAccumulator,
) -> list[ProviderStreamEvent]:
    """Map one parsed SSE chunk into zero or more provider events.

    ``acc`` is mutated in-place for tool-call fragment accumulation.

    OpenAI-compatible SSE flow:
        delta chunks -> finish_reason chunk (choices present, no usage)
        -> usage chunk (choices empty, usage present) -> [DONE]
    We emit StreamDone on the usage chunk, not on finish_reason, so tokens
    are captured. Tool calls and refusals are still emitted on finish_reason.
    """
    events: list[ProviderStreamEvent] = []
    choices = chunk.get("choices") or []
    usage = chunk.get("usage") or {}

    # Terminal usage-only chunk: emit StreamDone with token counts.
    if usage and not choices:
        details = usage.get("completion_tokens_details") or {}
        events.append(StreamDone(
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            reasoning_tokens=details.get("reasoning_tokens"),
        ))
        return events

    if not choices:
        return events

    choice = choices[0]
    delta = choice.get("delta") or {}

    # Mistral packs thinking blocks inside delta.content (polymorphic:
    # string or typed-item list). The OpenAI-style reasoning_content
    # field is kept as a fallback in case Mistral converges to OpenAI's
    # schema in a future API revision.
    visible, thinking_from_content = _translate_delta_content(delta.get("content"))
    if thinking_from_content:
        events.append(ThinkingDelta(delta=thinking_from_content))
    if visible:
        events.append(ContentDelta(delta=visible))

    # Only fall back to OAI-style reasoning_content if the content array
    # carried no thinking — prevents double ThinkingDelta in a hybrid chunk
    # (e.g. during a future Mistral schema transition).
    if not thinking_from_content:
        oai_reasoning = delta.get("reasoning_content") or ""
        if oai_reasoning:
            events.append(ThinkingDelta(delta=oai_reasoning))

    tool_frags = delta.get("tool_calls") or []
    if tool_frags:
        from backend.modules.llm._adapters._tool_call_streaming import (
            fragments_to_delta_events,
        )
        events.extend(fragments_to_delta_events(tool_frags, acc))

    finish = choice.get("finish_reason")
    if finish is None:
        return events

    # finish_reason arrives before the usage chunk. Emit tool calls or refusal
    # here; leave StreamDone to the usage chunk (or the outer safety net).
    if finish == "tool_calls":
        for call in acc.finalised():
            events.append(ToolCallEvent(
                id=call["id"], name=call["name"],
                arguments=call["arguments"],
                index=call["index"],
            ))
    elif finish in _REFUSAL_REASONS:
        events.append(StreamRefused(
            reason=finish,
            refusal_text=delta.get("refusal") or None,
        ))
    # Otherwise (stop, length, etc): wait for usage chunk to emit StreamDone.

    return events


def _parse_sse_line(line: str) -> dict | object | None:
    """Parse a single SSE line.

    Returns:
        - a ``dict`` when the line is a valid ``data: {json}`` frame,
        - ``_SSE_DONE`` for ``data: [DONE]`` (stream terminator),
        - ``None`` for empty lines, non-data lines, or malformed JSON.
    """
    line = line.strip()
    if not line or not line.startswith("data:"):
        return None
    payload = line[len("data:"):].strip()
    if payload == "[DONE]":
        return _SSE_DONE
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        _log.warning("Skipping malformed SSE JSON: %s", payload[:200])
        return None


def _translate_message(msg: CompletionMessage) -> dict:
    """Translate our CompletionMessage into an OpenAI-compatible chat message."""
    text_parts = [p for p in msg.content if p.type == "text" and p.text]
    image_parts = [p for p in msg.content if p.type == "image" and p.data]

    # Hard-CoT replay path: Mistral Magistral accepts structured
    # thinking objects on assistant messages. Force the typed-array
    # content shape when any thinking blocks are present and prepend
    # ``{"type": "thinking", "text": ...}`` items per block.
    thinking_parts: list[dict] = []
    if msg.role == "assistant" and msg.thinking_blocks:
        for b in msg.thinking_blocks:
            if b.text:
                thinking_parts.append({"type": "thinking", "text": b.text})

    # When there are no images and no thinking blocks, a plain string
    # is more cache-friendly.
    if not image_parts and not thinking_parts:
        content: str | list[dict] = "".join(p.text or "" for p in text_parts)
    else:
        content = []
        content.extend(thinking_parts)
        for p in text_parts:
            content.append({"type": "text", "text": p.text or ""})
        for p in image_parts:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{p.media_type};base64,{p.data}",
                },
            })

    result: dict = {"role": msg.role, "content": content}

    if msg.tool_calls:
        result["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": tc.arguments},
            }
            for tc in msg.tool_calls
        ]

    if msg.tool_call_id is not None:
        result["tool_call_id"] = msg.tool_call_id

    return result


def _build_chat_payload(request: CompletionRequest) -> dict:
    """Build a Mistral chat/completions payload.

    Maps our internal model_id to Mistral's upstream slug, applies the
    binary reasoning toggle (on -> "high", off -> "none") for reasoning
    models, and falls back to mistral-medium-3-5 when a stale persona
    references a model we no longer expose.
    """
    entry = _MISTRAL_MODELS_BY_ID.get(request.model)
    if entry is None:
        _log.warning(
            "Mistral: unknown model_id=%r in CompletionRequest; "
            "falling back to mistral-medium-3-5",
            request.model,
        )
        entry = _MISTRAL_MODELS_BY_ID["mistral-medium-3-5"]

    payload: dict = {
        "model": entry.upstream_slug,
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [_translate_message(m) for m in request.messages],
    }
    if entry.has_reasoning:
        payload["reasoning_effort"] = (
            "high" if request.extras.reasoning_mode == "on" else "none"
        )
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in request.tools
        ]
    return payload


def _mistral_repo_factory():
    """Default factory — returns a ConnectionRepository backed by the live DB.

    Defined at module level so tests can monkeypatch it:
        monkeypatch.setattr(_mistral_http, "_mistral_repo_factory", lambda: _FakeRepo())
    """
    from backend.database import get_db
    from backend.modules.llm._connections import ConnectionRepository
    return ConnectionRepository(get_db())


class MistralHttpAdapter(BaseAdapter):
    adapter_type = "mistral_http"
    display_name = "Mistral"
    view_id = "mistral_http"
    secret_fields = frozenset({"api_key"})

    @classmethod
    def router(cls) -> APIRouter:
        return _build_adapter_router()

    def capability_hint(self, model_id: str):
        from backend.modules.llm._capabilities import CapabilityHint

        entry = _MISTRAL_MODELS_BY_ID.get(model_id)
        if entry is None:
            return None
        reasoning_kind: Literal["no_reasoning", "optional"] = (
            "optional" if entry.has_reasoning else "no_reasoning"
        )
        return CapabilityHint(
            reasoning=ReasoningCapability(
                kind=reasoning_kind,
                default_on=entry.has_reasoning,
            ),
            tools=ToolCapability(
                supported=entry.supports_tool_calls,
                exclusive_with_reasoning=False,
            ),
            first_class_support=entry.first_class_support,
        )

    async def fetch_models(
        self, c: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        from backend.modules.llm._capabilities import resolve_capabilities

        metas: list[ModelMetaDto] = []
        for entry in _MISTRAL_MODELS:
            resolved = resolve_capabilities(
                adapter_type=self.adapter_type,
                model_id=entry.model_id,
                adapter=self,
            )
            metas.append(ModelMetaDto(
                connection_id=c.id,
                connection_display_name=c.display_name,
                connection_slug=c.slug,
                model_id=entry.model_id,
                display_name=entry.display_name,
                context_window=entry.context_window,
                reasoning=resolved.reasoning,
                tools=resolved.tools,
                first_class_support=resolved.first_class_support,
                supports_vision=entry.supports_vision,
                supports_tool_calls=entry.supports_tool_calls,
                is_deprecated=False,
                billing_category="pay_per_token",
            ))
        return metas

    async def stream_completion(
        self, c: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        url = c.config["url"].rstrip("/")
        api_key = c.config.get("api_key") or ""
        payload = _build_chat_payload(request)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        seen_done = False
        pending_next: asyncio.Task | None = None

        if _TRACE_PAYLOADS:
            _log.info(
                "LLM_TRACE path=mistral-out url=%s payload=%s",
                url,
                json.dumps(payload, default=str, sort_keys=True),
            )

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for attempt in range(MAX_RETRY_ATTEMPTS + 1):
                # Re-init per attempt — retries only happen before any
                # stream event has been yielded, so it is safe to reset.
                acc = _ToolCallAccumulator()
                retry_delay: float | None = None
                try:
                    async with client.stream(
                        "POST", f"{url}/chat/completions",
                        json=payload, headers=headers,
                    ) as resp:
                        if (
                            should_retry_status(resp.status_code)
                            and attempt < MAX_RETRY_ATTEMPTS
                        ):
                            retry_delay = compute_retry_delay(
                                attempt,
                                parse_retry_after(resp.headers),
                            )
                            log_retry(
                                _log,
                                operation="mistral_http",
                                attempt=attempt,
                                delay_seconds=retry_delay,
                                status_code=resp.status_code,
                                extra={"model": payload.get("model")},
                            )
                            # Fall through to outer ``await sleep``.
                        elif resp.status_code in (401, 403):
                            yield StreamError(
                                error_code="invalid_api_key",
                                message="Mistral rejected the API key",
                            )
                            return
                        elif should_retry_status(resp.status_code):
                            yield StreamError(
                                error_code="provider_unavailable",
                                message=(
                                    f"Mistral returned {resp.status_code}; "
                                    f"gave up after {MAX_RETRY_ATTEMPTS + 1} attempts"
                                ),
                            )
                            return
                        elif resp.status_code != 200:
                            body = await resp.aread()
                            detail = body.decode("utf-8", errors="replace")[:500]
                            _log.error("mistral_http upstream %d: %s",
                                       resp.status_code, detail)
                            yield StreamError(
                                error_code="provider_unavailable",
                                message=f"Mistral returned {resp.status_code}: {detail}",
                            )
                            return
                        else:
                            # 200 — process the SSE body. Once we begin
                            # yielding stream events, no further retry is
                            # safe (partial tokens may already be in the
                            # user's UI).
                            try:
                                stream_iter = resp.aiter_lines().__aiter__()
                                line_start = time.monotonic()
                                slow_fired = False

                                while True:
                                    elapsed = time.monotonic() - line_start
                                    budget = (
                                        GUTTER_ABORT_SECONDS - elapsed if slow_fired
                                        else GUTTER_SLOW_SECONDS - elapsed
                                    )
                                    if budget <= 0:
                                        if not slow_fired:
                                            _log.info(
                                                "mistral_http.gutter_slow model=%s idle=%.1fs",
                                                payload.get("model"), elapsed,
                                            )
                                            yield StreamSlow()
                                            slow_fired = True
                                            continue
                                        _log.warning(
                                            "mistral_http.gutter_abort model=%s idle=%.1fs",
                                            payload.get("model"), elapsed,
                                        )
                                        if pending_next is not None:
                                            pending_next.cancel()
                                        yield StreamAborted(reason="gutter_timeout")
                                        return
                                    if pending_next is None:
                                        pending_next = asyncio.ensure_future(
                                            stream_iter.__anext__(),
                                        )
                                    done, _ = await asyncio.wait(
                                        {pending_next}, timeout=budget,
                                    )
                                    if not done:
                                        continue
                                    task = done.pop()
                                    pending_next = None
                                    try:
                                        line = task.result()
                                    except StopAsyncIteration:
                                        break
                                    line_start = time.monotonic()
                                    slow_fired = False

                                    parsed = _parse_sse_line(line)
                                    if parsed is None:
                                        continue
                                    if parsed is _SSE_DONE:
                                        break

                                    for event in _chunk_to_events(parsed, acc):
                                        if isinstance(event, StreamDone):
                                            seen_done = True
                                        yield event
                                        if isinstance(event, (StreamDone,
                                                               StreamRefused,
                                                               StreamError)):
                                            return
                            except asyncio.CancelledError:
                                if pending_next is not None and not pending_next.done():
                                    pending_next.cancel()
                                raise
                            if not seen_done:
                                yield StreamDone()
                            return
                except httpx.ConnectError:
                    yield StreamError(
                        error_code="provider_unavailable",
                        message="Cannot connect to Mistral",
                    )
                    return

                # Retry path: 429/503 with attempts remaining set retry_delay.
                # Sleep with the stream context closed.
                assert retry_delay is not None
                await asyncio.sleep(retry_delay)


def _build_adapter_router() -> APIRouter:
    from datetime import UTC, datetime

    import backend.modules.llm._adapters._mistral_http as _self
    from backend.modules.llm._connections import ConnectionRepository
    from backend.modules.llm._resolver import resolve_connection_for_user
    from backend.ws.event_bus import EventBus, get_event_bus
    from shared.events.llm import LlmConnectionUpdatedEvent
    from shared.topics import Topics

    router = APIRouter()

    @router.post("/test")
    async def test_connection(
        c: ResolvedConnection = Depends(resolve_connection_for_user),
        event_bus: EventBus = Depends(get_event_bus),
        repo=Depends(lambda: _self._mistral_repo_factory()),
    ) -> dict:
        url = c.config["url"].rstrip("/")
        api_key = c.config.get("api_key") or ""
        valid = False
        error: str | None = None
        try:
            async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
                resp = await client.get(
                    f"{url}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                if resp.status_code in (401, 403):
                    error = "API key rejected by Mistral"
                elif resp.status_code != 200:
                    error = f"Mistral returned {resp.status_code}"
                else:
                    valid = True
        except Exception as exc:  # noqa: BLE001 — surface to frontend
            error = str(exc)

        updated = await repo.update_test_status(
            c.user_id, c.id,
            status="valid" if valid else "failed",
            error=error,
        )
        if updated is not None:
            await event_bus.publish(
                Topics.LLM_CONNECTION_UPDATED,
                LlmConnectionUpdatedEvent(
                    connection=ConnectionRepository.to_dto(updated),
                    timestamp=datetime.now(UTC),
                ),
            )
        return {"valid": valid, "error": error}

    return router

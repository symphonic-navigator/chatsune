"""Mistral HTTP adapter — OpenAI-compatible Chat Completions.

Premium-only adapter: not user-creatable. Instantiated exclusively via the
Premium Provider resolver (see :mod:`backend.modules.llm._resolver`).
Because Mistral's API is OpenAI-compatible, the SSE parser, tool-call
accumulator, and gutter-timer logic are structurally identical to the xAI
adapter. They are intentionally copied here (not imported) so each adapter
remains independent — extracting shared helpers is out of scope for Phase 1.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from uuid import uuid4

import httpx

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
from shared.dtos.llm import ModelMetaDto

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
        """Return accumulated calls as [{id, name, arguments}, ...]."""
        calls: list[dict] = []
        for _, slot in sorted(self._by_index.items()):
            calls.append({
                "id": slot["id"] or f"call_{uuid4().hex[:12]}",
                "name": slot["name"],
                "arguments": slot["args"] or "{}",
            })
        return calls


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
        events.append(StreamDone(
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        ))
        return events

    if not choices:
        return events

    choice = choices[0]
    delta = choice.get("delta") or {}

    reasoning = delta.get("reasoning_content") or ""
    if reasoning:
        events.append(ThinkingDelta(delta=reasoning))

    content = delta.get("content") or ""
    if content:
        events.append(ContentDelta(delta=content))

    tool_frags = delta.get("tool_calls") or []
    if tool_frags:
        acc.ingest(tool_frags)

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

    # When there are no images, a plain string is more cache-friendly.
    if not image_parts:
        content: str | list[dict] = "".join(p.text or "" for p in text_parts)
    else:
        content = []
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

    Unlike xAI (which special-cases grok-4-1-fast-reasoning vs
    -non-reasoning), Mistral's reasoning capability is baked into specific
    models (e.g. magistral-*, mistral-medium-latest) — so we simply pass
    ``request.model`` through unchanged.
    """
    payload: dict = {
        "model": request.model,
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [_translate_message(m) for m in request.messages],
    }
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


def _dedup_models(
    entries: list[dict],
    c: ResolvedConnection,
) -> list[ModelMetaDto]:
    """Apply Mistral-specific dedup + filter pipeline.

    Pipeline:
      1. Filter out entries without ``capabilities.completion_chat`` — we
         only list chat-completion models (no embeddings, moderation,
         classification, FIM-only, audio-only, …).
      2. Group entries by their ``name`` field — Mistral's canonical id
         (distinct from the ``id`` field, which may be an alias like
         ``-latest`` or a dated variant).
      3. For each group pick a preferred ``id``: prefer a ``-latest``
         alias if present, otherwise fall back to the group's canonical
         ``name`` (which is the dated id).
      4. Emit one :class:`ModelMetaDto` per group.
    """
    groups: dict[str, list[dict]] = {}
    for entry in entries:
        caps = entry.get("capabilities") or {}
        if not caps.get("completion_chat"):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        groups.setdefault(name, []).append(entry)

    metas: list[ModelMetaDto] = []
    for canonical_name, group in groups.items():
        preferred_id = canonical_name
        for entry in group:
            entry_id = entry.get("id")
            if isinstance(entry_id, str) and entry_id.endswith("-latest"):
                preferred_id = entry_id
                break

        # All entries in the group describe the same underlying model —
        # pick any one for capability/context fields. Prefer the entry
        # whose id matches preferred_id for display consistency.
        source = next(
            (e for e in group if e.get("id") == preferred_id),
            group[0],
        )
        caps = source.get("capabilities") or {}
        context_window = source.get("max_context_length") or 0
        deprecation = source.get("deprecation")
        metas.append(ModelMetaDto(
            connection_id=c.id,
            connection_display_name=c.display_name,
            connection_slug=c.slug,
            model_id=preferred_id,
            display_name=preferred_id,
            context_window=context_window if isinstance(context_window, int) else 0,
            supports_reasoning=bool(caps.get("reasoning")),
            supports_vision=bool(caps.get("vision")),
            supports_tool_calls=bool(caps.get("function_calling")),
            is_deprecated=deprecation is not None,
            billing_category="pay_per_token",
        ))
    return metas


class MistralHttpAdapter(BaseAdapter):
    adapter_type = "mistral_http"
    display_name = "Mistral"
    view_id = "mistral_http"
    secret_fields = frozenset({"api_key"})

    async def fetch_models(
        self, c: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        url = c.config["url"].rstrip("/")
        api_key = c.config.get("api_key") or ""
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
                resp = await client.get(f"{url}/models", headers=headers)
        except httpx.HTTPError as exc:
            _log.warning("mistral_http.fetch_models transport error: %s", exc)
            return []

        if resp.status_code in (401, 403):
            _log.warning(
                "mistral_http.fetch_models auth failure: status=%d",
                resp.status_code,
            )
            return []
        if resp.status_code != 200:
            _log.warning(
                "mistral_http.fetch_models upstream %d: %s",
                resp.status_code,
                resp.text[:200],
            )
            return []

        try:
            data = resp.json()
        except ValueError:
            _log.warning("mistral_http.fetch_models malformed JSON response")
            return []

        entries = data.get("data") or []
        if not isinstance(entries, list):
            return []
        return _dedup_models(entries, c)

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

        acc = _ToolCallAccumulator()
        seen_done = False
        pending_next: asyncio.Task | None = None

        if _TRACE_PAYLOADS:
            _log.info(
                "LLM_TRACE path=mistral-out url=%s payload=%s",
                url,
                json.dumps(payload, default=str, sort_keys=True),
            )

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                async with client.stream(
                    "POST", f"{url}/chat/completions",
                    json=payload, headers=headers,
                ) as resp:
                    if resp.status_code in (401, 403):
                        yield StreamError(
                            error_code="invalid_api_key",
                            message="Mistral rejected the API key",
                        )
                        return
                    if resp.status_code == 429:
                        yield StreamError(
                            error_code="provider_unavailable",
                            message="Mistral rate limit hit",
                        )
                        return
                    if resp.status_code != 200:
                        body = await resp.aread()
                        detail = body.decode("utf-8", errors="replace")[:500]
                        _log.error("mistral_http upstream %d: %s",
                                   resp.status_code, detail)
                        yield StreamError(
                            error_code="provider_unavailable",
                            message=f"Mistral returned {resp.status_code}: {detail}",
                        )
                        return

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
            except httpx.ConnectError:
                yield StreamError(
                    error_code="provider_unavailable",
                    message="Cannot connect to Mistral",
                )
                return

        if not seen_done:
            yield StreamDone()

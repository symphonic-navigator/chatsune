"""Nano-GPT HTTP adapter.

Implements the model catalogue (filter / pair / map via
``_nano_gpt_catalog``), persists the pair map to Redis
(``_nano_gpt_pair_map``), and drives an OpenAI-compatible SSE
streaming loop in ``stream_completion`` that picks the correct
upstream slug (thinking vs non-thinking) from the pair map at
request time.

Key design note — **do not** send ``reasoning`` or ``thinking`` flags
in the request body. Nano-GPT does not honour them; thinking is
switched exclusively by picking the ``thinking_slug`` from the pair
map as the upstream model. This differs from the Ollama adapter's
``"think"`` payload attachment and must not be copied here.
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
from redis.asyncio import Redis

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
from backend.modules.llm._adapters._nano_gpt_catalog import build_catalogue
from backend.modules.llm._adapters._nano_gpt_pair_map import save_pair_map
from backend.modules.llm._adapters._types import (
    AdapterTemplate,
    ConfigFieldHint,
    ResolvedConnection,
)
from shared.dtos.inference import CompletionMessage, CompletionRequest
from shared.dtos.llm import ModelMetaDto

_DEFAULT_BASE_URL = "https://api.nano-gpt.com/v1"
_TIMEOUT = 30.0

_log = logging.getLogger(__name__)

# Opt-in payload tracing for cache-miss debugging. Enable via
# LLM_TRACE_PAYLOADS=1 in the environment; keep off in production.
_TRACE_PAYLOADS = os.environ.get("LLM_TRACE_PAYLOADS") == "1"

GUTTER_SLOW_SECONDS: float = 30.0
GUTTER_ABORT_SECONDS: float = float(
    os.environ.get("LLM_STREAM_ABORT_SECONDS", "120"),
)

_STREAM_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=15.0)
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


def _build_chat_payload(request: CompletionRequest, upstream_slug: str) -> dict:
    """Build an OpenAI-compatible chat-completions request body.

    Thinking capability is expressed *exclusively* via ``upstream_slug`` —
    nano-gpt does not honour any ``reasoning`` / ``thinking`` flag in the
    body. Do not add one here; see the module docstring.
    """
    payload: dict = {
        "model": upstream_slug,
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


def _pick_upstream_slug(
    pair_map: dict[str, dict[str, str | None]],
    *, model_id: str, reasoning_enabled: bool,
) -> str | None:
    """Return the upstream slug to dispatch to, or ``None`` if unknown.

    When ``reasoning_enabled`` is true but the model has no thinking
    variant, fall back to the non-thinking slug. This matches the
    frontend's capability-gated UI: if the user toggles reasoning on a
    model that lacks it, we continue rather than refuse.
    """
    pair = pair_map.get(model_id)
    if pair is None:
        return None
    if reasoning_enabled and pair.get("thinking_slug"):
        return pair["thinking_slug"]
    return pair["non_thinking_slug"]


async def _http_get_models(
    *, base_url: str, api_key: str, timeout: float = _TIMEOUT,
) -> list[dict]:
    """Fetch the raw nano-gpt model list.

    Nano-GPT exposes ``/v1/models?detailed=true`` in the OpenAI-compatible
    envelope ``{"data": [...]}``. Returns the ``data`` list verbatim.
    """
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            f"{base_url.rstrip('/')}/models",
            params={"detailed": "true"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()
        payload = resp.json()
    return payload.get("data", [])


class NanoGptHttpAdapter(BaseAdapter):
    adapter_type = "nano_gpt_http"
    display_name = "Nano-GPT"
    view_id = "nano_gpt_http"
    secret_fields = frozenset({"api_key"})

    def __init__(self, *, redis: Redis | None = None) -> None:
        self._redis = redis

    @classmethod
    def templates(cls) -> list[AdapterTemplate]:
        return [
            AdapterTemplate(
                id="nano_gpt_default",
                display_name="Nano-GPT",
                slug_prefix="nano",
                config_defaults={
                    "base_url": "https://api.nano-gpt.com/v1",
                    "api_key": "",
                    "max_parallel": 3,
                },
                required_config_fields=("api_key",),
            ),
        ]

    @classmethod
    def config_schema(cls) -> list[ConfigFieldHint]:
        return [
            ConfigFieldHint(
                name="base_url",
                type="url",
                label="Base URL",
                required=False,
                placeholder="https://api.nano-gpt.com/v1",
            ),
            ConfigFieldHint(
                name="api_key",
                type="secret",
                label="API Key",
                required=True,
            ),
            ConfigFieldHint(
                name="max_parallel",
                type="integer",
                label="Max parallel inferences",
                min=1,
                max=32,
            ),
        ]

    async def fetch_models(
        self, connection: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        if self._redis is None:
            raise RuntimeError(
                "NanoGptHttpAdapter requires a Redis client for pair-map "
                "persistence — construct with redis= kwarg",
            )
        base_url = connection.config.get("base_url") or _DEFAULT_BASE_URL
        api_key = connection.config["api_key"]

        raw = await _http_get_models(base_url=base_url, api_key=api_key)
        result = build_catalogue(raw)

        # ``build_catalogue`` returns adapter-internal "block" dicts, not
        # ``ModelMetaDto`` instances — the adapter rehydrates them into
        # DTOs and overlays the connection fields. ``billing_category``
        # is set by ``to_model_meta`` and passed through via ``_block``,
        # so no derivation happens here.
        dtos: list[ModelMetaDto] = []
        for block in result.canonical:
            dtos.append(
                ModelMetaDto(
                    connection_id=connection.id,
                    connection_slug=connection.slug,
                    connection_display_name=connection.display_name,
                    model_id=block["model_id"],
                    display_name=block["display_name"],
                    context_window=block["context_window"],
                    supports_reasoning=block["supports_reasoning"],
                    supports_vision=block["supports_vision"],
                    supports_tool_calls=block["supports_tool_calls"],
                    billing_category=block["billing_category"],
                )
            )

        await save_pair_map(
            self._redis,
            connection_id=connection.id,
            pair_map=result.pair_map,
        )
        return dtos

    async def stream_completion(
        self, connection: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        if self._redis is None:
            raise RuntimeError(
                "NanoGptHttpAdapter requires a Redis client for pair-map "
                "lookup — construct with redis= kwarg",
            )

        base_url = (connection.config.get("base_url") or _DEFAULT_BASE_URL).rstrip("/")
        api_key = connection.config.get("api_key") or ""

        # Load the pair map. ``fetch_models`` populates this; if the user has
        # never fetched models for this connection, the map is empty and we
        # signal model_not_found rather than attempting a blind upstream call.
        from backend.modules.llm._adapters._nano_gpt_pair_map import load_pair_map
        pair_map = await load_pair_map(self._redis, connection_id=connection.id)

        upstream_slug = _pick_upstream_slug(
            pair_map, model_id=request.model,
            reasoning_enabled=request.reasoning_enabled,
        )
        if upstream_slug is None:
            yield StreamError(
                error_code="model_not_found",
                message=(
                    f"Model {request.model!r} is not in the nano-gpt pair map "
                    f"for connection {connection.id}. Refresh the model list "
                    f"and retry."
                ),
            )
            return

        payload = _build_chat_payload(request, upstream_slug)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        acc = _ToolCallAccumulator()
        seen_done = False
        pending_next: asyncio.Task | None = None

        if _TRACE_PAYLOADS:
            _log.info(
                "LLM_TRACE path=nano-gpt-out url=%s payload=%s",
                base_url, json.dumps(payload, default=str, sort_keys=True),
            )

        async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as client:
            try:
                async with client.stream(
                    "POST", f"{base_url}/chat/completions",
                    json=payload, headers=headers,
                ) as resp:
                    if resp.status_code in (401, 403):
                        yield StreamError(
                            error_code="invalid_api_key",
                            message="Nano-GPT rejected the API key",
                        )
                        return
                    if resp.status_code == 429:
                        yield StreamError(
                            error_code="provider_unavailable",
                            message="Nano-GPT rate limit hit",
                        )
                        return
                    if resp.status_code != 200:
                        body = await resp.aread()
                        detail = body.decode("utf-8", errors="replace")[:500]
                        _log.error(
                            "nano_gpt_http upstream %d: %s",
                            resp.status_code, detail,
                        )
                        yield StreamError(
                            error_code="provider_unavailable",
                            message=f"Nano-GPT returned {resp.status_code}: {detail}",
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
                                    "nano_gpt_http.gutter_slow model=%s idle=%.1fs",
                                    upstream_slug, elapsed,
                                )
                                yield StreamSlow()
                                slow_fired = True
                                continue
                            _log.warning(
                                "nano_gpt_http.gutter_abort model=%s idle=%.1fs",
                                upstream_slug, elapsed,
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
                    message="Cannot connect to Nano-GPT",
                )
                return

        if not seen_done:
            yield StreamDone()

"""OpenRouter HTTP adapter — OpenAI-compatible Chat Completions.

Premium-only adapter: not user-creatable. Instantiated exclusively via
the Premium Provider resolver (see ``backend.modules.llm._resolver``).
Routes to OpenRouter's unified API which fans out to 50+ upstream
providers; we apply ``output_modalities=text`` at the model-listing
endpoint so only text-output models reach the Model Browser.

Cache control: pass-through. OpenRouter performs automatic prefix
caching for OpenAI / Gemini / DeepSeek; Anthropic-style explicit
``cache_control`` markers are deferred — see INS-032 in INSIGHTS.md.

Structurally a Mistral clone. The OpenAI-compatible SSE parser,
tool-call accumulator, and gutter-timer logic are intentionally copied
in (not imported); the shared-helper extract refactor is tracked
separately.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends

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
_PROBE_TIMEOUT = httpx.Timeout(10.0)

GUTTER_SLOW_SECONDS: float = 30.0
GUTTER_ABORT_SECONDS: float = float(
    os.environ.get("LLM_STREAM_ABORT_SECONDS", "120"),
)
_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=15.0)
_TRACE_PAYLOADS = os.environ.get("LLM_TRACE_PAYLOADS") == "1"

# Retry policy for transient 429s. OpenRouter routes between many
# upstream providers; an individual provider can briefly rate-limit
# even when the user's account has no global ceiling. Total worst-case
# back-off across four attempts is roughly 1+2+4+8 ≈ 15s, capped per
# step at ``_RETRY_MAX_DELAY_SECONDS``.
_MAX_RETRY_ATTEMPTS = 4
_RETRY_BASE_DELAY_SECONDS = 1.0
_RETRY_MAX_DELAY_SECONDS = 16.0
_RETRY_JITTER_FRACTION = 0.25

_OPENROUTER_REFERER = "https://chatsune.app"
_OPENROUTER_X_TITLE = "Chatsune"

# Minimum context window we accept, in tokens. Mirrors nano-gpt's
# 80k floor — Chatsune builds long-running journals/memory loops
# that need real headroom once history accumulates.
MIN_CONTEXT_TOKENS = 80_000


def _supports(parameters: list[str], *names: str) -> bool:
    return any(n in parameters for n in names)


def _billing_category(pricing: dict) -> str:
    prompt = pricing.get("prompt") if isinstance(pricing, dict) else None
    completion = pricing.get("completion") if isinstance(pricing, dict) else None
    if prompt == "0" and completion == "0":
        return "free"
    return "pay_per_token"


def _entry_to_meta(entry: dict, c: ResolvedConnection) -> ModelMetaDto | None:
    arch = entry.get("architecture") or {}
    output_mods = arch.get("output_modalities")
    # Strict: exactly ["text"]. Image-only, audio-only, and mixed
    # output (e.g. text+image) are out of scope for Phase 1.
    if output_mods != ["text"]:
        return None

    context_length = int(entry.get("context_length") or 0)
    # Mirrors nano-gpt's MIN_CONTEXT — sub-80k models leave no
    # breathing room once chat history and tool definitions stack up.
    if context_length < MIN_CONTEXT_TOKENS:
        return None

    input_mods = arch.get("input_modalities") or []
    params = entry.get("supported_parameters") or []
    pricing = entry.get("pricing") or {}
    top = entry.get("top_provider") or {}

    raw_moderated = top.get("is_moderated")
    is_moderated: bool | None
    if isinstance(raw_moderated, bool):
        is_moderated = raw_moderated
    else:
        is_moderated = None

    return ModelMetaDto(
        connection_id=c.id,
        connection_slug=c.slug,
        connection_display_name=c.display_name,
        model_id=entry["id"],
        display_name=entry.get("name") or entry["id"],
        context_window=context_length,
        supports_reasoning=_supports(params, "reasoning", "include_reasoning"),
        supports_vision="image" in input_mods,
        supports_tool_calls=_supports(params, "tools"),
        is_deprecated=entry.get("expiration_date") is not None,
        billing_category=_billing_category(pricing),
        is_moderated=is_moderated,
    )


_REFUSAL_REASONS: frozenset[str] = frozenset({"content_filter", "refusal"})

_SSE_DONE = object()


class _ToolCallAccumulator:
    """Gathers OpenAI-style tool_call fragments across SSE chunks.

    ``finalised()`` is idempotent: subsequent calls return an empty list.
    Some upstream providers (notably DeepSeek via OpenRouter) emit two
    chunks with ``finish_reason="tool_calls"`` for the same call, which
    used to surface as a duplicate ToolCallStarted event downstream.
    """

    def __init__(self) -> None:
        self._by_index: dict[int, dict] = {}
        self._finalised = False

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
        if self._finalised:
            return []
        self._finalised = True
        calls: list[dict] = []
        for _, slot in sorted(self._by_index.items()):
            calls.append({
                "id": slot["id"] or f"call_{uuid4().hex[:12]}",
                "name": slot["name"],
                "arguments": slot["args"] or "{}",
            })
        return calls


def _chunk_to_events(
    chunk: dict, acc: _ToolCallAccumulator,
) -> list[ProviderStreamEvent]:
    events: list[ProviderStreamEvent] = []
    choices = chunk.get("choices") or []
    usage = chunk.get("usage") or {}

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

    # OpenAI convention: reasoning_content
    reasoning_content = delta.get("reasoning_content") or ""
    if reasoning_content:
        events.append(ThinkingDelta(delta=reasoning_content))

    # OpenRouter normalisation: plain reasoning key.
    # Some upstream providers stream their thinking under the bare
    # ``reasoning`` field; emit ThinkingDelta for both.
    reasoning = delta.get("reasoning") or ""
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

    return events


def _parse_sse_line(line: str) -> dict | object | None:
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
    text_parts = [p for p in msg.content if p.type == "text" and p.text]
    image_parts = [p for p in msg.content if p.type == "image" and p.data]

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
                    "name": t.name, "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in request.tools
        ]
    # Reasoning: only emit when meaningful. We do not expose effort
    # levels in this iteration. ``exclude: true`` controls visibility,
    # not whether the model reasons; built-in reasoners ignore it.
    if request.supports_reasoning and not request.reasoning_enabled:
        payload["reasoning"] = {"exclude": True}
    return payload


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    """Parse a numeric ``Retry-After`` response header into seconds.

    HTTP allows the header to be either an integer (or float) second
    count or an HTTP date. We honour the numeric form; date form is
    rare on OpenRouter and falls back to the exponential delay below.
    """
    raw = resp.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        seconds = float(raw.strip())
    except (ValueError, AttributeError):
        return None
    if seconds < 0:
        return None
    return min(seconds, _RETRY_MAX_DELAY_SECONDS)


def _retry_delay_seconds(resp: httpx.Response, attempt: int) -> float:
    """Pick a delay before the next retry.

    Honours upstream ``Retry-After`` if present, otherwise falls back to
    ``base * 2**attempt`` with ±jitter, hard-capped at the maximum.
    """
    retry_after = _retry_after_seconds(resp)
    if retry_after is not None:
        return retry_after
    base = _RETRY_BASE_DELAY_SECONDS * (2 ** attempt)
    jitter = base * _RETRY_JITTER_FRACTION * (random.random() * 2 - 1)
    return max(0.1, min(base + jitter, _RETRY_MAX_DELAY_SECONDS))


class OpenRouterHttpAdapter(BaseAdapter):
    adapter_type = "openrouter_http"
    display_name = "OpenRouter"
    view_id = "openrouter_http"
    secret_fields = frozenset({"api_key"})

    @classmethod
    def router(cls) -> APIRouter:
        return _build_adapter_router()

    async def fetch_models(
        self, c: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        url = c.config["url"].rstrip("/")
        api_key = c.config.get("api_key") or ""
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
                resp = await client.get(
                    f"{url}/models/user?output_modalities=text",
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            _log.warning("openrouter_http.fetch_models transport: %s", exc)
            return []

        if resp.status_code in (401, 403):
            _log.warning(
                "openrouter_http.fetch_models auth failure: status=%d",
                resp.status_code,
            )
            return []
        if resp.status_code != 200:
            _log.warning(
                "openrouter_http.fetch_models upstream %d: %s",
                resp.status_code, resp.text[:200],
            )
            return []

        try:
            data = resp.json()
        except ValueError:
            _log.warning("openrouter_http.fetch_models malformed JSON")
            return []

        entries = data.get("data") or []
        if not isinstance(entries, list):
            return []

        metas: list[ModelMetaDto] = []
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("id"):
                continue
            meta = _entry_to_meta(entry, c)
            if meta is not None:
                metas.append(meta)
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
            "HTTP-Referer": _OPENROUTER_REFERER,
            "X-Title": _OPENROUTER_X_TITLE,
        }

        if _TRACE_PAYLOADS:
            _log.info(
                "LLM_TRACE path=openrouter-out url=%s payload=%s",
                url, json.dumps(payload, default=str, sort_keys=True),
            )

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for attempt in range(_MAX_RETRY_ATTEMPTS):
                # Set inside the inner block when we decide to retry.
                # Read after the inner ``async with`` exits so we can
                # sleep with the connection already closed.
                retry_delay: float | None = None
                try:
                    async with client.stream(
                        "POST", f"{url}/chat/completions",
                        json=payload, headers=headers,
                    ) as resp:
                        if resp.status_code == 429 and attempt < _MAX_RETRY_ATTEMPTS - 1:
                            retry_delay = _retry_delay_seconds(resp, attempt)
                            _log.info(
                                "openrouter_http.rate_limit_retry "
                                "attempt=%d/%d delay=%.1fs model=%s",
                                attempt + 1, _MAX_RETRY_ATTEMPTS,
                                retry_delay, payload.get("model"),
                            )
                            # Fall through to the outer ``await sleep``.
                        elif resp.status_code in (401, 403):
                            yield StreamError(
                                error_code="invalid_api_key",
                                message="OpenRouter rejected the API key",
                            )
                            return
                        elif resp.status_code == 429:
                            yield StreamError(
                                error_code="provider_unavailable",
                                message=(
                                    f"OpenRouter rate limit hit; "
                                    f"gave up after {_MAX_RETRY_ATTEMPTS} attempts"
                                ),
                            )
                            return
                        elif resp.status_code != 200:
                            body = await resp.aread()
                            detail = body.decode("utf-8", errors="replace")[:500]
                            _log.error(
                                "openrouter_http upstream %d: %s",
                                resp.status_code, detail,
                            )
                            yield StreamError(
                                error_code="provider_unavailable",
                                message=f"OpenRouter returned {resp.status_code}: {detail}",
                            )
                            return
                        else:
                            # 200 — process the SSE body. Once we begin
                            # yielding stream events, no further retry
                            # is safe (partial tokens may already be in
                            # the user's UI).
                            acc = _ToolCallAccumulator()
                            seen_done = False
                            pending_next: asyncio.Task | None = None
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
                                                "openrouter_http.gutter_slow "
                                                "model=%s idle=%.1fs",
                                                payload.get("model"), elapsed,
                                            )
                                            yield StreamSlow()
                                            slow_fired = True
                                            continue
                                        _log.warning(
                                            "openrouter_http.gutter_abort "
                                            "model=%s idle=%.1fs",
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
                                    done, _pending = await asyncio.wait(
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
                        message="Cannot connect to OpenRouter",
                    )
                    return

                # Retry path: a 429 with attempts remaining set retry_delay.
                # Sleep with the stream context closed.
                assert retry_delay is not None
                await asyncio.sleep(retry_delay)


def _build_adapter_router() -> APIRouter:
    from backend.modules.llm._resolver import resolve_connection_for_user

    router = APIRouter()

    @router.post("/test")
    async def test_connection(
        c: ResolvedConnection = Depends(resolve_connection_for_user),
    ) -> dict:
        adapter = OpenRouterHttpAdapter()
        models = await adapter.fetch_models(c)
        if models:
            return {"valid": True, "error": None}
        return {
            "valid": False,
            "error": (
                "OpenRouter returned no models — check the API key, "
                "your OpenRouter privacy guardrails, or upstream availability."
            ),
        }

    return router

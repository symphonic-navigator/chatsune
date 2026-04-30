"""xAI HTTP adapter — Chat Completions (legacy) for Grok 4.1 Fast."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import time
import uuid
from collections.abc import AsyncIterator
from typing import ClassVar
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException
from PIL import Image
from pydantic import BaseModel

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
from backend.modules.llm._adapters._types import (
    AdapterTemplate,
    ConfigFieldHint,
    ResolvedConnection,
)
from backend.modules.llm._adapters._xai_image_groups import (
    GROUP_ID as XAI_IMAGINE_GROUP_ID,
    aspect_to_payload,
    model_id_for_tier,
    resolution_to_payload,
)
from shared.dtos.images import (
    GeneratedImageResult,
    ImageGenItem,
    ImageGroupConfig,
    ModeratedRejection,
    XaiImagineConfig,
)
from shared.dtos.inference import CompletionMessage, CompletionRequest
from shared.dtos.llm import ModelMetaDto

_log = logging.getLogger(__name__)

# Module-level temporary buffer keyed by generated image_id, drained
# by the caller (ImageService) immediately after generate_images returns.
# Single-process only; do not rely on cross-request persistence.
_LAST_BATCH_BUFFERS: dict[str, tuple[bytes, str]] = {}


def _new_image_id() -> str:
    return f"img_{uuid.uuid4().hex[:12]}"


def _probe_dimensions(image_bytes: bytes) -> tuple[int, int] | None:
    """Return (width, height) from image bytes, or None if unparseable."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            return im.size  # (w, h)
    except Exception:
        return None


def drain_image_buffer(image_id: str) -> tuple[bytes, str] | None:
    """Caller (ImageService) drains the bytes once and discards them."""
    return _LAST_BATCH_BUFFERS.pop(image_id, None)

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

    xAI's SSE flow:
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


_XAI_MODEL_REASONING = "grok-4-1-fast-reasoning"
_XAI_MODEL_NON_REASONING = "grok-4-1-fast-non-reasoning"


def _build_chat_payload(request: CompletionRequest) -> dict:
    model_slug = (
        _XAI_MODEL_REASONING if request.reasoning_enabled
        else _XAI_MODEL_NON_REASONING
    )
    payload: dict = {
        "model": model_slug,
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


class XaiHttpAdapter(BaseAdapter):
    adapter_type = "xai_http"
    display_name = "xAI / Grok"
    view_id = "xai_http"
    secret_fields = frozenset({"api_key"})
    supports_image_generation: ClassVar[bool] = True

    @classmethod
    def templates(cls) -> list[AdapterTemplate]:
        return [
            AdapterTemplate(
                id="xai_cloud",
                display_name="xAI Cloud",
                slug_prefix="xai",
                config_defaults={
                    "url": "https://api.x.ai/v1",
                    "api_key": "",
                    "max_parallel": 4,
                },
                required_config_fields=("api_key",),
            ),
        ]

    @classmethod
    def config_schema(cls) -> list[ConfigFieldHint]:
        return [
            ConfigFieldHint(
                name="url", type="url", label="URL",
                placeholder="https://api.x.ai/v1",
            ),
            ConfigFieldHint(
                name="api_key", type="secret", label="API Key",
            ),
            ConfigFieldHint(
                name="max_parallel", type="integer",
                label="Max parallel inferences",
                min=1, max=32,
            ),
        ]

    @classmethod
    def router(cls) -> APIRouter:
        return _build_adapter_router()

    async def fetch_models(
        self, c: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        return [
            ModelMetaDto(
                connection_id=c.id,
                connection_display_name=c.display_name,
                connection_slug=c.slug,
                model_id="grok-4.1-fast",
                display_name="Grok 4.1 Fast",
                context_window=200_000,
                supports_reasoning=True,
                supports_vision=True,
                supports_tool_calls=True,
                billing_category="pay_per_token",
            ),
        ]

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
        if request.cache_hint:
            headers["x-grok-conv-id"] = request.cache_hint

        seen_done = False
        pending_next: asyncio.Task | None = None

        if _TRACE_PAYLOADS:
            _log.info(
                "LLM_TRACE path=xai-out url=%s cache_hint=%s payload=%s",
                url, request.cache_hint or "",
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
                                operation="xai_http",
                                attempt=attempt,
                                delay_seconds=retry_delay,
                                status_code=resp.status_code,
                                extra={"model": payload.get("model")},
                            )
                            # Fall through to outer ``await sleep``.
                        elif resp.status_code in (401, 403):
                            yield StreamError(
                                error_code="invalid_api_key",
                                message="xAI rejected the API key",
                            )
                            return
                        elif should_retry_status(resp.status_code):
                            yield StreamError(
                                error_code="provider_unavailable",
                                message=(
                                    f"xAI returned {resp.status_code}; "
                                    f"gave up after {MAX_RETRY_ATTEMPTS + 1} attempts"
                                ),
                            )
                            return
                        elif resp.status_code != 200:
                            body = await resp.aread()
                            detail = body.decode("utf-8", errors="replace")[:500]
                            _log.error("xai_http upstream %d: %s",
                                       resp.status_code, detail)
                            yield StreamError(
                                error_code="provider_unavailable",
                                message=f"xAI returned {resp.status_code}: {detail}",
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
                                                "xai_http.gutter_slow model=%s idle=%.1fs",
                                                payload.get("model"), elapsed,
                                            )
                                            yield StreamSlow()
                                            slow_fired = True
                                            continue
                                        _log.warning(
                                            "xai_http.gutter_abort model=%s idle=%.1fs",
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
                        message="Cannot connect to xAI",
                    )
                    return

                # Retry path: 429/503 with attempts remaining set retry_delay.
                # Sleep with the stream context closed.
                assert retry_delay is not None
                await asyncio.sleep(retry_delay)

    async def image_groups(self, connection: ResolvedConnection) -> list[str]:
        # xAI offers exactly one image group today.
        return [XAI_IMAGINE_GROUP_ID]

    async def generate_images(
        self,
        connection: ResolvedConnection,
        group_id: str,
        config: ImageGroupConfig,
        prompt: str,
    ) -> list[ImageGenItem]:
        if group_id != XAI_IMAGINE_GROUP_ID:
            raise ValueError(f"unknown image group {group_id!r} for xAI adapter")
        if not isinstance(config, XaiImagineConfig):
            raise ValueError(
                f"expected XaiImagineConfig, got {type(config).__name__}"
            )

        model_id = model_id_for_tier(config.tier)
        _log.debug(
            "xai_http.generate_images model=%s n=%d aspect=%s resolution=%s",
            model_id, config.n, config.aspect, config.resolution,
        )

        body = {
            "model": model_id,
            "prompt": prompt,
            "n": config.n,
            "response_format": "url",
            "aspect_ratio": aspect_to_payload(config.aspect),
            "resolution": resolution_to_payload(config.resolution),
        }

        base_url = connection.config["url"].rstrip("/")
        url = f"{base_url}/images/generations"
        api_key = connection.config.get("api_key") or ""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=body)
            if resp.status_code >= 400:
                _log.error(
                    "xai_http.generate_images failed status=%d body=%s",
                    resp.status_code, resp.text[:500],
                )
                raise RuntimeError(
                    f"xAI image generation failed: {resp.status_code} {resp.text}"
                )
            payload = resp.json()

            cost = (payload.get("usage") or {}).get("cost_in_usd_ticks")
            _log.debug("xai_http.generate_images done cost_in_usd_ticks=%s", cost)

            items: list[ImageGenItem] = []
            for entry in payload.get("data", []):
                if entry.get("respect_moderation") is False:
                    items.append(ModeratedRejection(reason=entry.get("reason")))
                    continue

                image_url = entry.get("url")
                if not image_url:
                    items.append(ModeratedRejection(reason="no_url"))
                    continue

                blob_resp = await client.get(image_url)
                if blob_resp.status_code >= 400:
                    items.append(ModeratedRejection(reason="fetch_failed"))
                    continue

                content_type = entry.get("mime_type") or blob_resp.headers.get(
                    "content-type", "image/jpeg"
                )
                dims = _probe_dimensions(blob_resp.content)
                width, height = dims if dims else (0, 0)
                image_id = _new_image_id()

                items.append(GeneratedImageResult(
                    id=image_id,
                    width=width,
                    height=height,
                    model_id=model_id,
                ))
                _LAST_BATCH_BUFFERS[image_id] = (blob_resp.content, content_type)

        return items


class _ImagineTestRequest(BaseModel):
    group_id: str
    config: dict
    prompt: str = "a serene mountain landscape at dawn"


class _ImagineTestResponse(BaseModel):
    items: list[ImageGenItem]


def _xai_repo_factory():
    """Default factory — returns a ConnectionRepository backed by the live DB.

    Defined at module level so tests can monkeypatch it:
        monkeypatch.setattr(_xai_http, "_xai_repo_factory", lambda: _FakeRepo())
    """
    from backend.database import get_db
    from backend.modules.llm._connections import ConnectionRepository
    return ConnectionRepository(get_db())


def _build_adapter_router() -> APIRouter:
    from datetime import UTC, datetime

    import backend.modules.llm._adapters._xai_http as _self
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
        repo=Depends(lambda: _self._xai_repo_factory()),
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
                    error = "API key rejected by xAI"
                elif resp.status_code != 200:
                    error = f"xAI returned {resp.status_code}"
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

    @router.post("/imagine/test", response_model=_ImagineTestResponse)
    async def imagine_test(
        body: _ImagineTestRequest,
        c: ResolvedConnection = Depends(resolve_connection_for_user),
    ) -> _ImagineTestResponse:
        from pydantic import TypeAdapter
        from shared.dtos.images import ImageGroupConfig

        _log.info(
            "xai_http.imagine_test connection_id=%s group_id=%s n=%d",
            c.id, body.group_id,
            body.config.get("n", -1),
        )

        try:
            cfg = TypeAdapter(ImageGroupConfig).validate_python(
                {**body.config, "group_id": body.group_id}
            )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"invalid config: {exc}")

        adapter = XaiHttpAdapter()
        items = await adapter.generate_images(
            connection=c,
            group_id=body.group_id,
            config=cfg,
            prompt=body.prompt,
        )
        # Drain buffers immediately — bytes are not persisted in the test path.
        for item in items:
            if item.kind == "image":
                drain_image_buffer(item.id)
        return _ImagineTestResponse(items=items)

    return router

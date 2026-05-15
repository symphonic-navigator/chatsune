"""Tensorix HTTP adapter — OpenAI-compatible Chat Completions.

Hosts a curated seven-model list (DeepSeek V4 Flash/Pro/V3.2, Kimi K2.6,
GLM 4.6/5/5.1) against the Tensorix Cloud API. Tensorix is OpenAI-
compatible (litellm-backed) and offers GDPR/ZDR/EU-compute guarantees.

Reasoning surface is per-model and was decided empirically against
the live API (see INSIGHTS.md INS-046). Tensorix routes models through two
heterogeneous internal backends — an OpenRouter proxy and a set of
direct in-house engines — and the two don't honour reasoning controls
uniformly. The classification therefore is:

- ``off_on_toggle`` — exactly one model (deepseek-v3.2) exposes a
  working on/off toggle. ON sends ``reasoning_effort="high"``; OFF
  sends ``reasoning_effort="none"``.
- ``always_on`` — six models. Tensorix either ignores the field or
  thinks anyway; we omit ``reasoning_effort`` entirely and surface a
  disabled-but-visible "always on" toggle in the UI.

See devdocs/specs/2026-05-15-tensorix-provider-design.md.
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
from shared.dtos.llm import (
    ModelMetaDto,
    ReasoningCapability,
    ToolCapability,
)

_log = logging.getLogger(__name__)

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
class _TensorixModelEntry:
    model_id: str            # user-facing internal ID, e.g. "deepseek-v4-flash"
    upstream_slug: str       # what we send to Tensorix, e.g. "deepseek/deepseek-v4-flash"
    display_name: str
    context_window: int
    max_output_tokens: int
    supports_tool_calls: bool
    supports_vision: bool
    # ``off_on_toggle`` -> the user toggles reasoning. ON sends
    # ``reasoning_effort="high"``; OFF sends ``reasoning_effort="none"``.
    # ``always_on``     -> Tensorix reasons unconditionally for this
    # model; we omit ``reasoning_effort`` on the wire and show a
    # disabled "always on" toggle in the UI.
    reasoning_mode: Literal["off_on_toggle", "always_on"]
    first_class_support: bool


_TENSORIX_MODELS: tuple[_TensorixModelEntry, ...] = (
    _TensorixModelEntry(
        model_id="deepseek-v4-flash",
        upstream_slug="deepseek/deepseek-v4-flash",
        display_name="DeepSeek V4 Flash",
        context_window=1_048_576,
        max_output_tokens=384_000,
        supports_tool_calls=True,
        supports_vision=False,
        reasoning_mode="always_on",
        first_class_support=True,
    ),
    _TensorixModelEntry(
        model_id="deepseek-v4-pro",
        upstream_slug="deepseek/deepseek-v4-pro",
        display_name="DeepSeek V4 Pro",
        context_window=1_048_576,
        max_output_tokens=384_000,
        supports_tool_calls=True,
        supports_vision=False,
        reasoning_mode="always_on",
        first_class_support=True,
    ),
    _TensorixModelEntry(
        model_id="kimi-k2-6",
        upstream_slug="moonshotai/Kimi-K2.6",
        display_name="Kimi K2.6",
        context_window=262_144,
        max_output_tokens=262_144,
        supports_tool_calls=True,
        supports_vision=True,
        reasoning_mode="always_on",
        first_class_support=True,
    ),
    _TensorixModelEntry(
        model_id="glm-5-1",
        upstream_slug="z-ai/glm-5.1",
        display_name="GLM 5.1",
        context_window=202_752,
        max_output_tokens=202_752,
        supports_tool_calls=True,
        supports_vision=False,
        reasoning_mode="always_on",
        first_class_support=True,
    ),
    _TensorixModelEntry(
        model_id="glm-5",
        upstream_slug="z-ai/glm-5",
        display_name="GLM 5",
        context_window=202_752,
        max_output_tokens=202_752,
        supports_tool_calls=True,
        supports_vision=False,
        reasoning_mode="always_on",
        first_class_support=True,
    ),
    _TensorixModelEntry(
        model_id="deepseek-v3-2",
        upstream_slug="deepseek/deepseek-v3.2",
        display_name="DeepSeek V3.2",
        context_window=163_840,
        max_output_tokens=163_840,
        supports_tool_calls=True,
        supports_vision=False,
        reasoning_mode="off_on_toggle",
        first_class_support=True,
    ),
    _TensorixModelEntry(
        model_id="glm-4-6",
        upstream_slug="z-ai/glm-4.6",
        display_name="GLM 4.6",
        context_window=203_000,
        max_output_tokens=131_000,
        supports_tool_calls=True,
        supports_vision=False,
        reasoning_mode="always_on",
        first_class_support=True,
    ),
)

_TENSORIX_MODELS_BY_ID: dict[str, _TensorixModelEntry] = {
    m.model_id: m for m in _TENSORIX_MODELS
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


def _chunk_to_events(
    chunk: dict,
    acc: _ToolCallAccumulator,
) -> list[ProviderStreamEvent]:
    """Map one parsed SSE chunk into zero or more provider events.

    Tensorix is OpenAI-compatible: reasoning_content carries thinking
    (string), content carries visible output (string), tool_calls arrive
    index-keyed in fragments, and the usage chunk arrives separately at
    the tail of the stream because we set stream_options.include_usage.
    """
    events: list[ProviderStreamEvent] = []
    choices = chunk.get("choices") or []
    usage = chunk.get("usage") or {}

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

    reasoning_text = delta.get("reasoning_content") or ""
    if reasoning_text:
        events.append(ThinkingDelta(delta=reasoning_text))

    visible_text = delta.get("content")
    if isinstance(visible_text, str) and visible_text:
        events.append(ContentDelta(delta=visible_text))

    tool_frags = delta.get("tool_calls") or []
    if tool_frags:
        from backend.modules.llm._adapters._tool_call_streaming import (
            fragments_to_delta_events,
        )
        events.extend(fragments_to_delta_events(tool_frags, acc))

    finish = choice.get("finish_reason")
    if finish is None:
        return events

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
    return events


def _translate_message(msg: CompletionMessage) -> dict:
    """Translate our CompletionMessage into an OpenAI-compatible chat message."""
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


def _select_reasoning_effort(
    entry: _TensorixModelEntry, request: CompletionRequest,
) -> str | None:
    """Return the ``reasoning_effort`` value for this request, or ``None``.

    Rules (see spec §5.3, revision 2026-05-15):
      - ``always_on`` model -> always None (field omitted; Tensorix
        either ignores ``reasoning_effort`` on this route or thinks
        regardless, so we don't pretend to control it).
      - ``off_on_toggle`` model + toggle on  -> ``"high"``.
      - ``off_on_toggle`` model + toggle off -> ``"none"``.
    """
    if entry.reasoning_mode == "always_on":
        return None
    return "high" if request.extras.reasoning_mode == "on" else "none"


def _build_chat_payload(request: CompletionRequest) -> dict:
    """Build a Tensorix chat/completions payload.

    Maps the user-facing ``model_id`` (e.g. "deepseek-v4-flash") to
    Tensorix's upstream slug (e.g. "deepseek/deepseek-v4-flash"), applies
    per-model reasoning rules, and falls back to ``deepseek-v3-2`` when a
    stale persona references a model we no longer expose.
    """
    entry = _TENSORIX_MODELS_BY_ID.get(request.model)
    if entry is None:
        _log.warning(
            "Tensorix: unknown model_id=%r in CompletionRequest; "
            "falling back to deepseek-v3-2",
            request.model,
        )
        entry = _TENSORIX_MODELS_BY_ID["deepseek-v3-2"]

    payload: dict = {
        "model": entry.upstream_slug,
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [_translate_message(m) for m in request.messages],
    }
    effort = _select_reasoning_effort(entry, request)
    if effort is not None:
        payload["reasoning_effort"] = effort
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


_CURATED_UPSTREAM_SLUGS: frozenset[str] = frozenset(
    m.upstream_slug for m in _TENSORIX_MODELS
)


async def _probe_tensorix(*, url: str, api_key: str) -> dict:
    """Validate the URL + key against Tensorix's /model/info endpoint.

    Returns ``{"valid": bool, "error": str | None}``. Fails closed when
    none of the curated upstream slugs are present in the response — a
    cheap canary against Tensorix renaming or retiring a model behind
    our back.
    """
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            resp = await client.get(
                f"{url}/model/info",
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except Exception as exc:  # noqa: BLE001 — surface to frontend
        return {"valid": False, "error": str(exc) or exc.__class__.__name__}

    if resp.status_code in (401, 403):
        return {"valid": False, "error": "API key rejected by Tensorix"}
    if resp.status_code != 200:
        return {
            "valid": False,
            "error": f"Tensorix returned {resp.status_code}",
        }

    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        return {"valid": False, "error": "Tensorix returned non-JSON body"}

    items = body.get("data") or []
    seen_upstream = {
        item.get("model_name") for item in items if isinstance(item, dict)
    }
    intersection = _CURATED_UPSTREAM_SLUGS & {s for s in seen_upstream if s}
    if not intersection:
        return {
            "valid": False,
            "error": (
                "No curated Tensorix models present in /model/info "
                "— capability drift detected"
            ),
        }
    return {"valid": True, "error": None}


def _tensorix_repo_factory():
    """Default factory — returns a ConnectionRepository backed by the live DB.

    Defined at module level so tests can monkeypatch it.
    """
    from backend.database import get_db
    from backend.modules.llm._connections import ConnectionRepository
    return ConnectionRepository(get_db())


class TensorixHttpAdapter(BaseAdapter):
    adapter_type = "tensorix_http"
    display_name = "Tensorix"
    view_id = "tensorix_http"
    secret_fields = frozenset({"api_key"})

    @classmethod
    def router(cls) -> APIRouter:
        return _build_adapter_router()

    def capability_hint(self, model_id: str):
        from backend.modules.llm._capabilities import CapabilityHint

        entry = _TENSORIX_MODELS_BY_ID.get(model_id)
        if entry is None:
            return None

        if entry.reasoning_mode == "always_on":
            reasoning = ReasoningCapability(
                kind="always_on",
                effort=None,
                default_on=True,
            )
        else:  # "off_on_toggle" — only deepseek-v3.2 today
            reasoning = ReasoningCapability(
                kind="optional",
                effort=None,
                default_on=False,
            )

        return CapabilityHint(
            reasoning=reasoning,
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
        for entry in _TENSORIX_MODELS:
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
                "LLM_TRACE path=tensorix-out url=%s payload=%s",
                url,
                json.dumps(payload, default=str, sort_keys=True),
            )

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for attempt in range(MAX_RETRY_ATTEMPTS + 1):
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
                                operation="tensorix_http",
                                attempt=attempt,
                                delay_seconds=retry_delay,
                                status_code=resp.status_code,
                                extra={"model": payload.get("model")},
                            )
                        elif resp.status_code in (401, 403):
                            yield StreamError(
                                error_code="invalid_api_key",
                                message="Tensorix rejected the API key",
                            )
                            return
                        elif should_retry_status(resp.status_code):
                            yield StreamError(
                                error_code="provider_unavailable",
                                message=(
                                    f"Tensorix returned {resp.status_code}; "
                                    f"gave up after {MAX_RETRY_ATTEMPTS + 1} attempts"
                                ),
                            )
                            return
                        elif resp.status_code != 200:
                            body = await resp.aread()
                            detail = body.decode("utf-8", errors="replace")[:500]
                            _log.error("tensorix_http upstream %d: %s",
                                       resp.status_code, detail)
                            yield StreamError(
                                error_code="provider_unavailable",
                                message=f"Tensorix returned {resp.status_code}: {detail}",
                            )
                            return
                        else:
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
                                                "tensorix_http.gutter_slow model=%s idle=%.1fs",
                                                payload.get("model"), elapsed,
                                            )
                                            yield StreamSlow()
                                            slow_fired = True
                                            continue
                                        _log.warning(
                                            "tensorix_http.gutter_abort model=%s idle=%.1fs",
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
                        message="Cannot connect to Tensorix",
                    )
                    return

                assert retry_delay is not None
                await asyncio.sleep(retry_delay)


def _build_adapter_router() -> APIRouter:
    from datetime import UTC, datetime

    import backend.modules.llm._adapters._tensorix_http as _self
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
        repo=Depends(lambda: _self._tensorix_repo_factory()),
    ) -> dict:
        url = c.config["url"].rstrip("/")
        api_key = c.config.get("api_key") or ""
        result = await _probe_tensorix(url=url, api_key=api_key)
        valid = result["valid"]
        error = result["error"]

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

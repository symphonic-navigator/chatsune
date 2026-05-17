"""Nano-GPT HTTP adapter.

Implements the model catalogue (filter / pair / map via
``_nano_gpt_catalog``), persists the pair map to Redis
(``_nano_gpt_pair_map``), and drives an OpenAI-compatible SSE
streaming loop in ``stream_completion`` that picks the correct
upstream call (slug + body flag) from the pair map at request time.

Thinking activation — nano-gpt has three switching modes captured by
``switching_mode`` in the pair map:

* ``slug``: classic dual-slug pair (``:thinking`` / ``-thinking`` or
  inverted ``-nothinking``). Pick the matching half. Body MUST NOT
  carry any reasoning flag — empirically the body flag wins over the
  slug, which would silently invert the user's intent.
* ``flag``: switchable singleton — same slug regardless, the toggle
  lives in the request body as ``{"reasoning": {"enabled": …}}`` (the
  OpenRouter unified reasoning object). Always send the field, even
  with ``enabled: false`` — vendors disagree on the default direction.
* ``none``: plain singleton with no reasoning option. Slug stays the
  same, body never carries a reasoning flag. If the user toggles
  reasoning on regardless, the request still proceeds (matches the
  capability-gated UI behaviour).

The contract surfaced to chatsune's frontend via ``ModelMetaDto``
collapses ``slug`` and ``flag`` into ``supports_reasoning=True`` —
both mean "this model has a reasoning toggle" from the UI's
perspective. ``none`` maps to ``supports_reasoning=False``.

SSE field names — the default ``/api/v1/chat/completions`` endpoint
streams reasoning in ``delta.reasoning``; the legacy
``/api/v1legacy/chat/completions`` endpoint uses
``delta.reasoning_content``. ``_chunk_to_events`` reads both (modern
field takes precedence) so the adapter works against either.
"""

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
from redis.asyncio import Redis

from backend._retry import (
    MAX_RETRY_ATTEMPTS,
    compute_retry_delay,
    log_retry,
    parse_retry_after,
    should_retry_status,
)
from backend.modules.llm._adapters._anthropic_cache import (
    extract_cache_metrics,
    is_anthropic_model,
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
    StreamWarning,
    ThinkingDelta,
    ToolCallEvent,
)
from backend.modules.llm._adapters._nano_gpt_catalog import build_catalogue
from backend.modules.llm._adapters._nano_gpt_image_groups import (
    SEEDREAM_GROUP_ID,
    ZIMAGE_GROUP_ID,
    seedream_payload,
    zimage_payload,
)
from backend.modules.llm._adapters._nano_gpt_pair_map import save_pair_map
from backend.modules.llm._adapters._types import (
    AdapterTemplate,
    ConfigFieldHint,
    ResolvedConnection,
)
from shared.dtos.images import (
    GeneratedImageResult,
    ImageGenItem,
    ImageGroupConfig,
    ModeratedRejection,
    SeedreamConfig,
    ZImageConfig,
)
from shared.dtos.inference import CompletionMessage, CompletionRequest
from shared.dtos.llm import ModelMetaDto, ReasoningCapability, ToolCapability

_DEFAULT_BASE_URL = "https://nano-gpt.com/api/v1"
_TIMEOUT = 30.0

_log = logging.getLogger(__name__)

# Opt-in payload tracing for cache-miss debugging. Enable via
# LLM_TRACE_PAYLOADS=1 in the environment; keep off in production.
_TRACE_PAYLOADS = os.environ.get("LLM_TRACE_PAYLOADS") == "1"

# Opt-in per-chunk delta tracing. Enable via LLM_TRACE_DELTAS=1 in the
# environment. Logs every reasoning / content delta seen on the wire
# with length and a short preview. Temporary — intended for
# diagnosing "TTFT then long pause" issues; keep off in production.
_TRACE_DELTAS = os.environ.get("LLM_TRACE_DELTAS") == "1"

GUTTER_SLOW_SECONDS: float = 30.0
GUTTER_ABORT_SECONDS: float = float(
    os.environ.get("LLM_STREAM_ABORT_SECONDS", "120"),
)

_STREAM_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=15.0)
_REFUSAL_REASONS: frozenset[str] = frozenset({"content_filter", "refusal"})

_SSE_DONE = object()  # sentinel — distinct from any JSON-decodable value


def _probe_dimensions(image_bytes: bytes) -> tuple[int, int] | None:
    """Return (width, height) from image bytes, or None if unparseable."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            return im.size
    except Exception:
        return None


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

    # Default endpoint streams reasoning in ``delta.reasoning``; the legacy
    # endpoint (``/v1legacy``) uses ``delta.reasoning_content``. We treat
    # the default as authoritative and fall back to the legacy field so
    # the adapter keeps working if the endpoint ever switches. They never
    # arrive together in a single chunk in practice.
    reasoning = delta.get("reasoning") or delta.get("reasoning_content") or ""
    if reasoning:
        if _TRACE_DELTAS:
            _log.info(
                "LLM_TRACE path=nano-gpt-in kind=reasoning len=%d preview=%r",
                len(reasoning), reasoning[:40],
            )
        events.append(ThinkingDelta(delta=reasoning))

    # Anthropic-specific: ``reasoning_details`` is a list of typed
    # blocks, each carrying its own ``signature`` token. See the
    # OpenRouter adapter for the rationale — nano-gpt forwards the
    # same Anthropic-shape content blocks.
    details = delta.get("reasoning_details") or []
    if isinstance(details, list):
        for d in details:
            if not isinstance(d, dict):
                continue
            if d.get("type") == "thinking":
                events.append(ThinkingDelta(
                    delta=d.get("thinking") or "",
                    signature=d.get("signature"),
                    raw=d,
                ))

    content = delta.get("content") or ""
    if content:
        if _TRACE_DELTAS:
            _log.info(
                "LLM_TRACE path=nano-gpt-in kind=content len=%d preview=%r",
                len(content), content[:40],
            )
        events.append(ContentDelta(delta=content))

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


def _translate_message(
    msg: CompletionMessage,
    *,
    cache_control: dict | None = None,
    model_id: str | None = None,
) -> dict:
    """Translate our CompletionMessage into an OpenAI-compatible chat message."""
    text_parts = [p for p in msg.content if p.type == "text" and p.text]
    image_parts = [p for p in msg.content if p.type == "image" and p.data]

    # Hard-CoT replay path: for Anthropic models on the nano-gpt route
    # we pre-pend ``{"type": "thinking", "thinking": ..., "signature":
    # ...}`` parts. Non-Anthropic routes get a concatenated
    # ``reasoning_content`` field on the assistant message instead.
    anthropic_thinking_parts: list[dict] = []
    non_anthropic_reasoning_concat = ""
    is_anthropic = bool(model_id and is_anthropic_model(model_id))
    if msg.role == "assistant" and msg.thinking_blocks:
        if is_anthropic:
            for b in msg.thinking_blocks:
                block: dict = {"type": "thinking", "thinking": b.text or ""}
                if b.signature:
                    block["signature"] = b.signature
                anthropic_thinking_parts.append(block)
        else:
            non_anthropic_reasoning_concat = "".join(
                (b.text or "") for b in msg.thinking_blocks
            )

    if (
        cache_control is None
        and not image_parts
        and not anthropic_thinking_parts
    ):
        content: str | list[dict] = "".join(p.text or "" for p in text_parts)
    else:
        content = []
        content.extend(anthropic_thinking_parts)
        for p in text_parts:
            content.append({"type": "text", "text": p.text or ""})
        for p in image_parts:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{p.media_type};base64,{p.data}",
                },
            })
        if cache_control and content:
            content[-1]["cache_control"] = cache_control

    result: dict = {"role": msg.role, "content": content}
    if non_anthropic_reasoning_concat:
        result["reasoning_content"] = non_anthropic_reasoning_concat
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


def _build_chat_payload(
    request: CompletionRequest,
    upstream_slug: str,
    *,
    send_reasoning_flag: bool,
    reasoning_enabled: bool,
    reasoning_effort: str | None = None,
) -> dict:
    """Build an OpenAI-compatible chat-completions request body.

    When ``send_reasoning_flag`` is True (flag-mode dispatch), the body
    carries ``{"reasoning": {"enabled": reasoning_enabled}}`` — the
    OpenRouter unified reasoning object — plus ``"effort"`` when
    ``reasoning_effort`` is provided. The flag is always sent for
    flag-mode requests, including with ``enabled: false``: vendors
    disagree on the default direction (gpt-5 default OFF, claude-sonnet
    default ON, mimo default ON), so omitting the flag would surrender
    control of the toggle.

    For slug-mode and none-mode dispatch, ``send_reasoning_flag`` is
    False and the body must not carry any reasoning-related field.

    Tool gating: ``request.tools`` are only included when both the
    request carries them AND the session has tools enabled (via
    ``request.extras.tools_enabled``). The session toggle is the
    ground truth — adapters never second-guess it.

    See module docstring for reasoning-mode / cache-control rules.
    """
    from backend.modules.llm._adapters._anthropic_cache import (
        compute_cache_markers,
        is_anthropic_model,
    )

    cc_by_index: dict[int, dict] = {}
    if (
        request.anthropic_cache_ttl != "off"
        and is_anthropic_model(request.model)
    ):
        for marker in compute_cache_markers(
            request.messages,
            request.anthropic_cache_ttl,
            compact_anchor_index=request.compact_anchor_index,
        ):
            cc_by_index[marker.message_index] = _to_cache_control(marker.ttl)

    payload: dict = {
        "model": upstream_slug,
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [
            _translate_message(
                m,
                cache_control=cc_by_index.get(i),
                model_id=request.model,
            )
            for i, m in enumerate(request.messages)
        ],
    }
    if send_reasoning_flag:
        reasoning_obj: dict = {"enabled": reasoning_enabled}
        # Effort buckets are NOT sent for Anthropic models — see INS-037.
        # Mirrors openrouter_http: cache survival beats effort control on
        # router-mediated paths. Other vendors keep effort as before.
        if reasoning_enabled and reasoning_effort and not is_anthropic_model(request.model):
            reasoning_obj["effort"] = reasoning_effort
        payload["reasoning"] = reasoning_obj
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.tools and request.extras.tools_enabled:
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


def _is_anthropic_signature_rejection(status_code: int, body: str) -> bool:
    """Detect Anthropic 400 invalid_request_error for thinking signature.

    Mirrors the OpenRouter helper — nano-gpt forwards Anthropic
    rejections with the same shape (400 + mention of ``signature`` or
    ``thinking`` / ``thinking_block``). Match permissively; we only
    flip into strip-and-retry on a clear signal.
    """
    if status_code != 400:
        return False
    low = body.lower()
    if "invalid_request_error" not in low and "invalid request" not in low:
        return False
    return "signature" in low or "thinking" in low


def _strip_thinking_from_payload(payload: dict) -> None:
    """In-place strip of thinking content blocks on assistant messages.

    Used by the Anthropic strip-and-retry path; see the OpenRouter
    adapter for the rationale. Symmetrical with that implementation
    so behaviour matches across both Anthropic-bearing premium routes.
    """
    for msg in payload.get("messages") or []:
        if msg.get("role") != "assistant":
            continue
        msg.pop("reasoning_content", None)
        content = msg.get("content")
        if isinstance(content, list):
            filtered = [
                c for c in content
                if not (isinstance(c, dict) and c.get("type") == "thinking")
            ]
            if not filtered:
                filtered = [{"type": "text", "text": ""}]
            msg["content"] = filtered


def build_request_body(
    request: CompletionRequest,
    pair: dict[str, str | None] | None = None,
) -> tuple[dict, str]:
    """Translate a CompletionRequest into the nano-gpt request body.

    Returns ``(body, dispatched_slug)``. Caller uses the slug to log /
    trace which upstream variant was dispatched; for slug-mode pairs
    this differs from ``request.model``. For flag-mode and none-mode
    (and the no-pair default), the slug equals ``request.model``.

    Translation rules — read together with the module docstring:

    * ``pair`` carries ``switching_mode`` ∈ {``slug``, ``flag``,
      ``none``}. The dispatch mode determines how reasoning is
      surfaced upstream.
    * ``slug`` mode: pick the slug variant from the pair; the body
      must NOT carry ``reasoning`` (an extra body flag would
      empirically invert the user's intent).
    * ``flag`` mode: same slug; the body carries
      ``{"reasoning": {"enabled": <bool>}}`` plus ``"effort"`` when
      ``request.extras.reasoning_effort`` is set. Always present —
      vendors disagree on the default direction.
    * ``none`` mode: same slug; no reasoning field on the body — even
      if the user toggles reasoning ON via the UI (capability-gated
      fallback for plain singletons).
    * Without an explicit pair (``pair=None``) we treat the model as
      flag-mode when ``request.reasoning.kind == "optional"``, and
      none-mode otherwise. This keeps the public translation function
      stand-alone for tests and callers without a Redis pair_map.
    """
    reasoning_mode_on = request.extras.reasoning_mode == "on"
    reasoning_effort = request.extras.reasoning_effort
    slug = request.model
    send_reasoning_flag = False
    reasoning_enabled = reasoning_mode_on

    if pair is None:
        # No upstream pair info: behave as flag-mode for optional
        # reasoning, none-mode otherwise.
        send_reasoning_flag = request.reasoning.kind == "optional"
    else:
        mode = pair.get("switching_mode", "none")
        if mode == "slug":
            slug = (
                pair["thinking_slug"]
                if reasoning_mode_on and pair.get("thinking_slug")
                else pair["non_thinking_slug"]
            )
        elif mode == "flag":
            slug = pair.get("non_thinking_slug") or request.model
            send_reasoning_flag = True
        else:  # "none" or unknown
            slug = pair.get("non_thinking_slug") or request.model

    body = _build_chat_payload(
        request,
        slug,
        send_reasoning_flag=send_reasoning_flag,
        reasoning_enabled=reasoning_enabled,
        reasoning_effort=reasoning_effort if send_reasoning_flag else None,
    )
    return body, slug


def _to_cache_control(ttl: str) -> dict:
    if ttl == "1h":
        return {"type": "ephemeral", "ttl": "1h"}
    return {"type": "ephemeral"}


def _log_anthropic_cache(
    request: CompletionRequest, upstream_slug: str, last_usage: dict,
) -> None:
    """Emit the ``anthropic_cache`` observability line for Claude completions.

    Called on every successful end-of-stream path (both the
    ``_chunk_to_events``-emitted ``StreamDone`` and the safety-net
    ``StreamDone`` after the SSE loop). Gated on ``is_anthropic_model``
    so non-Claude completions stay quiet.
    """
    if not is_anthropic_model(request.model):
        return
    cache_read, cache_creation = extract_cache_metrics(last_usage)
    _log.info(
        "anthropic_cache adapter=nano-gpt model=%s ttl=%s "
        "cache_read=%d cache_creation=%d input=%d",
        upstream_slug,
        request.anthropic_cache_ttl,
        cache_read,
        cache_creation,
        last_usage.get("prompt_tokens", 0),
    )


def _resolve_call(
    pair: dict[str, str | None] | None,
    model_id: str,
    reasoning_enabled: bool,
) -> dict:
    """Resolve the upstream slug and whether to send the reasoning flag.

    Returns ``{"slug": str, "send_reasoning_flag": bool}``.

    * ``mode='slug'``: pick the matching half of the pair, never send
      the flag (the slug already selects; an extra body flag would
      empirically invert the user's choice).
    * ``mode='flag'``: slug stays the same, ALWAYS send the flag —
      including with ``reasoning_enabled=False`` — because vendors
      disagree on the default direction. The caller mirrors
      ``reasoning_enabled`` into the body.
    * ``mode='none'`` or unknown model: pass ``model_id`` through, no
      flag (capability-gated fallback when the user toggles reasoning
      on a model that doesn't support it).
    """
    if pair is None:
        return {"slug": model_id, "send_reasoning_flag": False}

    mode = pair.get("switching_mode", "none")
    if mode == "slug":
        slug = (
            pair["thinking_slug"]
            if reasoning_enabled and pair.get("thinking_slug")
            else pair["non_thinking_slug"]
        )
        return {"slug": slug, "send_reasoning_flag": False}
    if mode == "flag":
        return {
            "slug": pair["non_thinking_slug"],
            "send_reasoning_flag": True,
        }
    return {"slug": pair["non_thinking_slug"], "send_reasoning_flag": False}


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
    supports_image_generation: ClassVar[bool] = True

    def __init__(self, *, redis: Redis | None = None) -> None:
        self._redis = redis
        # Populated by ``fetch_models`` per call. Consulted by
        # ``capability_hint`` when ``resolve_capabilities`` falls
        # through past the YAML overrides. Per-instance state — and
        # the adapter is constructed fresh per request, so there is
        # no cross-request contamination.
        self._dispatch_mode_by_model_id: dict[str, str] = {}

    @classmethod
    def templates(cls) -> list[AdapterTemplate]:
        return [
            AdapterTemplate(
                id="nano_gpt_default",
                display_name="Nano-GPT",
                slug_prefix="nano",
                config_defaults={
                    "base_url": "https://nano-gpt.com/api/v1",
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
                placeholder="https://nano-gpt.com/api/v1",
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

    @classmethod
    def router(cls) -> APIRouter:
        return _build_adapter_router()

    async def fetch_models(
        self, connection: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        from backend.modules.llm._capabilities import resolve_capabilities

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
        # DTOs, overlays the connection fields, and resolves
        # reasoning/tools capabilities (YAML override → adapter hint →
        # universal default). ``billing_category`` is set by
        # ``to_model_meta`` and passed through via ``_block``.
        dtos: list[ModelMetaDto] = []
        for block in result.canonical:
            # Stash the catalogue-derived dispatch mode on the adapter
            # so ``capability_hint`` can consult it without re-running
            # the catalogue. The hint is consulted exactly once per
            # model_id during ``resolve_capabilities`` below.
            self._dispatch_mode_by_model_id[block["model_id"]] = (
                block["switching_mode"]
            )
            resolved = resolve_capabilities(
                adapter_type=self.adapter_type,
                model_id=block["model_id"],
                adapter=self,
            )
            dtos.append(
                ModelMetaDto(
                    connection_id=connection.id,
                    connection_slug=connection.slug,
                    connection_display_name=connection.display_name,
                    model_id=block["model_id"],
                    display_name=block["display_name"],
                    context_window=block["context_window"],
                    reasoning=resolved.reasoning,
                    tools=resolved.tools,
                    first_class_support=resolved.first_class_support,
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

    def capability_hint(self, model_id: str):
        """Best-effort capability hint based on the dispatch mode the
        catalogue derived for this model.

        Slug- or flag-mode means the catalogue saw evidence the model
        supports a reasoning toggle (paired upstream slug or
        ``capabilities.reasoning=True``). We emit ``optional`` reasoning
        with ``first_class_support=False`` — heuristic guidance, not
        curated. None-mode means no reasoning toggle was detected.

        ``ToolCapability(supported=True)`` mirrors the universal
        default — nano-gpt's ``capabilities.tool_calling`` is consulted
        separately for the legacy ``supports_tool_calls`` field.
        """
        from backend.modules.llm._capabilities import CapabilityHint

        mode = self._dispatch_mode_by_model_id.get(model_id)
        if mode in ("slug", "flag"):
            return CapabilityHint(
                reasoning=ReasoningCapability(kind="optional"),
                tools=ToolCapability(supported=True),
                first_class_support=False,
            )
        if mode == "none":
            return CapabilityHint(
                reasoning=ReasoningCapability(kind="no_reasoning"),
                tools=ToolCapability(supported=True),
                first_class_support=False,
            )
        # Mode unknown (capability_hint called outside fetch_models): defer
        # to the universal default.
        return None

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

        pair = pair_map.get(request.model)
        if pair is None:
            yield StreamError(
                error_code="model_not_found",
                message=(
                    f"Model {request.model!r} is not in the nano-gpt pair map "
                    f"for connection {connection.id}. Refresh the model list "
                    f"and retry."
                ),
            )
            return

        payload, upstream_slug = build_request_body(request, pair)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        seen_done = False
        # Track usage across chunks. Some upstreams that route Claude
        # via OpenAI-compat send ``usage`` in the same chunk as
        # ``finish_reason="stop"`` rather than the OpenAI-standard
        # separate usage chunk; capturing on every chunk keeps token
        # tracking and the ``anthropic_cache`` log line robust to that.
        last_usage: dict = {}
        pending_next: asyncio.Task | None = None

        if _TRACE_PAYLOADS:
            _log.info(
                "LLM_TRACE path=nano-gpt-out url=%s payload=%s",
                base_url, json.dumps(payload, default=str, sort_keys=True),
            )

        # Anthropic signature-replay strip-and-retry guard. See the
        # OpenRouter adapter for the rationale.
        anthropic_strip_attempted = False

        async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as client:
            for attempt in range(MAX_RETRY_ATTEMPTS + 1):
                # Re-init per attempt — retries only happen before any
                # stream event has been yielded, so it is safe to reset.
                acc = _ToolCallAccumulator()
                retry_delay: float | None = None
                anthropic_retry_now = False
                try:
                    async with client.stream(
                        "POST", f"{base_url}/chat/completions",
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
                                operation="nano_gpt_http",
                                attempt=attempt,
                                delay_seconds=retry_delay,
                                status_code=resp.status_code,
                                extra={"model": upstream_slug},
                            )
                            # Fall through to outer ``await sleep``.
                        elif resp.status_code in (401, 403):
                            yield StreamError(
                                error_code="invalid_api_key",
                                message="Nano-GPT rejected the API key",
                            )
                            return
                        elif should_retry_status(resp.status_code):
                            yield StreamError(
                                error_code="provider_unavailable",
                                message=(
                                    f"Nano-GPT returned {resp.status_code}; "
                                    f"gave up after {MAX_RETRY_ATTEMPTS + 1} attempts"
                                ),
                            )
                            return
                        elif resp.status_code != 200:
                            body = await resp.aread()
                            detail = body.decode("utf-8", errors="replace")[:500]
                            # Anthropic strip-and-retry: see the
                            # OpenRouter adapter for the rationale.
                            if (
                                not anthropic_strip_attempted
                                and is_anthropic_model(request.model)
                                and _is_anthropic_signature_rejection(
                                    resp.status_code, detail,
                                )
                            ):
                                _log.warning(
                                    "nano_gpt_http.thinking_signature_stripped "
                                    "model=%s status=%d body_snippet=%s",
                                    upstream_slug,
                                    resp.status_code,
                                    detail[:200],
                                )
                                _strip_thinking_from_payload(payload)
                                anthropic_strip_attempted = True
                                anthropic_retry_now = True
                                yield StreamWarning(
                                    code="thinking_signature_stripped",
                                    detail=(
                                        "Anthropic rejected the prior "
                                        "thinking trace; retrying without "
                                        "reasoning replay."
                                    ),
                                )
                            else:
                                _log.error(
                                    "nano_gpt_http upstream %d: %s",
                                    resp.status_code, detail,
                                )
                                yield StreamError(
                                    error_code="provider_unavailable",
                                    message=f"Nano-GPT returned {resp.status_code}: {detail}",
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

                                    if (
                                        isinstance(parsed, dict)
                                        and parsed.get("usage")
                                    ):
                                        last_usage = parsed["usage"]

                                    for event in _chunk_to_events(parsed, acc):
                                        if isinstance(event, StreamDone):
                                            seen_done = True
                                            _log_anthropic_cache(
                                                request, upstream_slug, last_usage,
                                            )
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
                                _details = (
                                    last_usage.get("completion_tokens_details")
                                    or {}
                                )
                                yield StreamDone(
                                    input_tokens=last_usage.get("prompt_tokens"),
                                    output_tokens=last_usage.get("completion_tokens"),
                                    reasoning_tokens=_details.get("reasoning_tokens"),
                                )
                                _log_anthropic_cache(
                                    request, upstream_slug, last_usage,
                                )
                            return
                except httpx.ConnectError:
                    yield StreamError(
                        error_code="provider_unavailable",
                        message="Cannot connect to Nano-GPT",
                    )
                    return

                # Anthropic strip-and-retry: re-issue immediately with
                # the stripped payload. Does not consume an attempt;
                # ``anthropic_strip_attempted`` is the one-shot guard.
                if anthropic_retry_now:
                    continue

                # Retry path: 429/503 with attempts remaining set retry_delay.
                # Sleep with the stream context closed.
                assert retry_delay is not None
                await asyncio.sleep(retry_delay)

    async def image_groups(self, connection: ResolvedConnection) -> list[str]:
        return [ZIMAGE_GROUP_ID, SEEDREAM_GROUP_ID]

    async def generate_images(
        self,
        connection: ResolvedConnection,
        group_id: str,
        config: ImageGroupConfig,
        prompt: str,
    ) -> list[ImageGenItem]:
        if group_id == ZIMAGE_GROUP_ID:
            if not isinstance(config, ZImageConfig):
                raise ValueError(
                    f"expected ZImageConfig, got {type(config).__name__}"
                )
            body = zimage_payload(config, prompt)
            model_id = body["model"]
        elif group_id == SEEDREAM_GROUP_ID:
            if not isinstance(config, SeedreamConfig):
                raise ValueError(
                    f"expected SeedreamConfig, got {type(config).__name__}"
                )
            body = seedream_payload(config, prompt)
            model_id = body["model"]
        else:
            raise ValueError(
                f"unknown image group {group_id!r} for nano-gpt adapter"
            )

        base_url = (connection.config.get("base_url") or _DEFAULT_BASE_URL).rstrip("/")
        api_key = connection.config.get("api_key") or ""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # Z-Image-Base at n=4 can take ~3 minutes (the validator's worst-case
        # cap). 300 s read covers that with a margin; connect/write/pool stay
        # short so genuine networking issues fail fast.
        _gen_timeout = httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=15.0)
        async with httpx.AsyncClient(timeout=_gen_timeout) as client:
            resp = await client.post(
                f"{base_url}/images/generations",
                headers=headers, json=body,
            )
            if resp.status_code >= 400:
                _log.error(
                    "nano_gpt.generate_images failed status=%d body=%s",
                    resp.status_code, resp.text[:500],
                )
                raise RuntimeError(
                    f"nano-gpt image generation failed: "
                    f"{resp.status_code} {resp.text[:200]}"
                )
            payload = resp.json()
            cost = payload.get("cost")
            if cost is not None:
                _log.debug("nano_gpt.generate_images cost_usd=%s", cost)

            items: list[ImageGenItem] = []
            for entry in payload.get("data", []):
                image_url = entry.get("url") if isinstance(entry, dict) else None
                if not image_url:
                    items.append(ModeratedRejection(reason="no_url"))
                    continue

                # IMPORTANT: nano-gpt returns Cloudflare R2 signed URLs;
                # sending the Bearer header collides with the AWS-V4
                # signature, so we issue a bare GET on a fresh client.
                async with httpx.AsyncClient(timeout=60.0) as blob_client:
                    blob_resp = await blob_client.get(image_url)
                    if blob_resp.status_code >= 400:
                        items.append(ModeratedRejection(reason="fetch_failed"))
                        continue
                    content_type = blob_resp.headers.get(
                        "content-type", "image/jpeg",
                    )
                    dims = _probe_dimensions(blob_resp.content)
                    width, height = dims if dims else (0, 0)
                    image_id = f"img_{uuid.uuid4().hex[:12]}"
                    items.append(GeneratedImageResult(
                        id=image_id,
                        width=width,
                        height=height,
                        model_id=model_id,
                        data=blob_resp.content,
                        content_type=content_type,
                    ))
        return items


# ---------------------------------------------------------------------------
# Adapter sub-router — mounted under /api/llm/connections/{id}/adapter/
# ---------------------------------------------------------------------------

class _ImagineTestRequest(BaseModel):
    group_id: str
    config: dict
    prompt: str = "a serene mountain landscape at dawn"


class _ImagineTestResponse(BaseModel):
    items: list[ImageGenItem]


def _build_adapter_router() -> APIRouter:
    from pydantic import TypeAdapter
    from backend.modules.llm._resolver import resolve_connection_for_user

    router = APIRouter()

    @router.post("/imagine/test", response_model=_ImagineTestResponse)
    async def imagine_test(
        body: _ImagineTestRequest,
        c: ResolvedConnection = Depends(resolve_connection_for_user),
    ) -> _ImagineTestResponse:
        _log.info(
            "nano_gpt.imagine_test connection_id=%s group_id=%s",
            c.id, body.group_id,
        )
        try:
            cfg = TypeAdapter(ImageGroupConfig).validate_python(
                {**body.config, "group_id": body.group_id}
            )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"invalid config: {exc}")

        adapter = NanoGptHttpAdapter()
        items = await adapter.generate_images(
            connection=c,
            group_id=body.group_id,
            config=cfg,
            prompt=body.prompt,
        )
        return _ImagineTestResponse(items=items)

    return router

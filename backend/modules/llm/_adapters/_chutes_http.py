"""Chutes AI HTTP adapter — OpenAI-compatible Chat Completions, TEE-only.

Premium-Provider adapter: instantiated by the Premium Provider resolver
when a user has configured a Chutes account (encrypted ``cpk_...`` key
in :class:`PremiumProviderAccountRepository`). Surfaces only models
with ``confidential_compute == true`` and ``context_length >= 80_000``
so the integration is a pure "ultra privacy" inference option.
Structurally a slim clone of OpenRouter — same SSE parser, tool-call
accumulator, gutter timer, and retry policy — but without Anthropic
cache markers or driver hooks (no first-class model curating in MVP).

Drift-resistance: Chutes' catalogue exposes per-model
``supported_sampling_parameters``. The adapter filters the final request
body against this whitelist immediately before sending so that engine /
quantisation drift drops fields silently rather than returning 400.

See ``devdocs/superpowers/specs/2026-05-16-chutes-integration-design.md``.
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
from fastapi import APIRouter

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

_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=15.0)
_PROBE_TIMEOUT = httpx.Timeout(10.0)
_TRACE_PAYLOADS = os.environ.get("LLM_TRACE_PAYLOADS") == "1"

GUTTER_SLOW_SECONDS: float = 30.0
GUTTER_ABORT_SECONDS: float = float(
    os.environ.get("LLM_STREAM_ABORT_SECONDS", "120"),
)

# Floor mirrors OpenRouter / nano-gpt — sub-80k models leave no
# headroom once history and tool definitions stack up.
MIN_CONTEXT_TOKENS = 80_000

# Hardcoded endpoints — Chutes runs a single public managed endpoint.
# Adapter does not expose a ``url`` config field.
_INFERENCE_BASE_URL = "https://llm.chutes.ai/v1"
_MANAGEMENT_BASE_URL = "https://api.chutes.ai"


def _supports(features: list[str], *names: str) -> bool:
    return any(n in features for n in names)


def _billing_category(pricing: dict) -> str:
    """Map Chutes pricing into Chatsune billing_category.

    Chutes serves prices as strings ("0.28") or numeric. Treat 0 / "0"
    as free; anything else as pay_per_token. Subscription is not a
    Chutes concept (no platform plan tier exposed via the catalogue).
    """
    if not isinstance(pricing, dict):
        return "pay_per_token"
    prompt = pricing.get("prompt")
    completion = pricing.get("completion")
    free_values: frozenset = frozenset({0, 0.0, "0", "0.0"})
    if prompt in free_values and completion in free_values:
        return "free"
    return "pay_per_token"


def _entry_to_meta(
    entry: dict, c: ResolvedConnection, *, adapter: "ChutesHttpAdapter",
) -> ModelMetaDto | None:
    """Map one Chutes catalogue entry to a ``ModelMetaDto`` or ``None``.

    Hard filter — all three must hold:
    1. ``confidential_compute is True`` (TEE-only; trust the flag, not the suffix)
    2. ``context_length >= 80_000`` (mirrors OpenRouter / nano-gpt floor)
    3. ``output_modalities == ["text"]`` (Phase 1 text-output only)
    """
    from backend.modules.llm._capabilities import resolve_capabilities

    if entry.get("confidential_compute") is not True:
        return None

    try:
        context_length = int(entry.get("context_length") or 0)
    except (ValueError, TypeError):
        _log.warning(
            "chutes_http.entry_to_meta: non-numeric context_length on %s",
            entry.get("id"),
        )
        return None
    if context_length < MIN_CONTEXT_TOKENS:
        return None

    if entry.get("output_modalities") != ["text"]:
        return None

    features = list(entry.get("supported_features") or [])
    sampling_params = list(entry.get("supported_sampling_parameters") or [])
    input_mods = entry.get("input_modalities") or []
    pricing = entry.get("pricing") or {}

    # Stash per-model heuristic inputs for later request-build steps.
    adapter._features_by_model_id[entry["id"]] = features
    adapter._sampling_params_by_model_id[entry["id"]] = sampling_params

    resolved = resolve_capabilities(
        adapter_type=adapter.adapter_type,
        model_id=entry["id"],
        adapter=adapter,
    )

    return ModelMetaDto(
        connection_id=c.id,
        connection_slug=c.slug,
        connection_display_name=c.display_name,
        model_id=entry["id"],
        display_name=entry.get("name") or entry["id"],
        context_window=context_length,
        reasoning=resolved.reasoning,
        tools=resolved.tools,
        first_class_support=resolved.first_class_support,
        supports_vision="image" in input_mods,
        supports_tool_calls=_supports(features, "tools"),
        is_deprecated=False,
        billing_category=_billing_category(pricing),
        is_moderated=None,
    )


def _translate_message(msg: CompletionMessage) -> dict:
    text_parts = [p for p in msg.content if p.type == "text" and p.text]
    image_parts = [
        p for p in msg.content if p.type == "image" and p.data and p.media_type
    ]

    if not image_parts:
        content: str | list[dict] = "".join(p.text or "" for p in text_parts)
    else:
        content = []
        for p in text_parts:
            content.append({"type": "text", "text": p.text or ""})
        for p in image_parts:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{p.media_type};base64,{p.data}"},
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


def build_request_body(request: CompletionRequest) -> dict:
    """Translate a CompletionRequest into the Chutes ``/chat/completions`` body.

    Whitelist filtering against ``supported_sampling_parameters`` happens in
    a separate step (see ``_filter_to_whitelist`` in Task 4), invoked by
    ``stream_completion`` immediately before sending. This function emits
    the common-case body shape only.
    """
    payload: dict = {
        "model": request.model,
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [_translate_message(m) for m in request.messages],
    }
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
    if (
        request.reasoning.kind == "optional"
        and request.extras.reasoning_mode == "on"
        and request.extras.reasoning_effort
    ):
        payload["reasoning_effort"] = request.extras.reasoning_effort
    return payload


# Keys always preserved regardless of the per-model sampling whitelist —
# these are structural (request envelope) not sampling parameters.
_ALWAYS_KEEP: frozenset[str] = frozenset({
    "model", "messages", "stream", "stream_options", "tools",
})


def _filter_to_whitelist(
    payload: dict, whitelist: list[str] | None,
) -> dict:
    """Drop sampling parameters not in the per-model whitelist.

    Returns a new dict — does not mutate the input. ``whitelist=None``
    means "no catalogue data, send everything" — the adapter has not yet
    seen this model_id (e.g. cache miss with a transient catalogue
    glitch); better to attempt the request than to fabricate a hard
    filter.
    """
    if whitelist is None:
        return dict(payload)
    allowed = _ALWAYS_KEEP | set(whitelist)
    return {k: v for k, v in payload.items() if k in allowed}


_SSE_DONE = object()
_REFUSAL_REASONS: frozenset[str] = frozenset({"content_filter", "refusal"})


class _ToolCallAccumulator:
    """Gathers OpenAI-style tool_call fragments across SSE chunks.

    ``finalised()`` is idempotent: subsequent calls return an empty list.
    Mirrors OpenRouter's implementation — kept as a separate copy because
    the shared-helper extract refactor is tracked separately.
    """

    def __init__(self) -> None:
        self._by_index: dict[int, dict] = {}
        self._finalised = False

    def ingest(self, fragments: list[dict]) -> None:
        for frag in fragments:
            idx = frag.get("index")
            if idx is None:
                continue
            slot = self._by_index.setdefault(idx, {"id": None, "name": "", "args": ""})
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
        out: list[dict] = []
        for idx, slot in sorted(self._by_index.items()):
            out.append({
                "id": slot["id"] or f"call_{uuid4().hex[:12]}",
                "name": slot["name"],
                "arguments": slot["args"] or "{}",
                "index": idx,
            })
        return out


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


def _chunk_to_events(
    chunk: dict, acc: _ToolCallAccumulator,
) -> list[ProviderStreamEvent]:
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

    # Some upstreams stream thinking under reasoning_content, others
    # under bare ``reasoning``. Emit ThinkingDelta for whichever appears.
    reasoning_content = delta.get("reasoning_content") or ""
    if reasoning_content:
        events.append(ThinkingDelta(delta=reasoning_content))
    reasoning = delta.get("reasoning") or ""
    if reasoning:
        events.append(ThinkingDelta(delta=reasoning))

    content = delta.get("content") or ""
    if content:
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

    if finish == "tool_calls":
        for call in acc.finalised():
            events.append(ToolCallEvent(
                id=call["id"], name=call["name"],
                arguments=call["arguments"], index=call["index"],
            ))
    elif finish in _REFUSAL_REASONS:
        events.append(StreamRefused(
            reason=finish,
            refusal_text=delta.get("refusal") or None,
        ))

    return events


class ChutesHttpAdapter(BaseAdapter):
    adapter_type = "chutes_http"
    display_name = "Chutes AI"
    view_id = "chutes_http"
    secret_fields = frozenset({"api_key"})

    def __init__(self) -> None:
        # Populated per ``fetch_models`` call. Both maps are consulted at
        # request-build time (capability_hint and whitelist filter).
        self._features_by_model_id: dict[str, list[str]] = {}
        self._sampling_params_by_model_id: dict[str, list[str]] = {}

    def capability_hint(self, model_id: str):
        """Heuristic capability hint from cached ``supported_features``.

        Returns ``first_class_support=False`` — Chutes integration is
        catalogue-driven, not curated. Falls through to the universal
        default if ``fetch_models`` has not populated the features map
        for this model_id yet.
        """
        from backend.modules.llm._capabilities import CapabilityHint

        features = self._features_by_model_id.get(model_id)
        if features is None:
            return None
        if _supports(features, "reasoning"):
            reasoning = ReasoningCapability(kind="optional")
        else:
            reasoning = ReasoningCapability(kind="no_reasoning")
        tools = ToolCapability(supported=_supports(features, "tools"))
        return CapabilityHint(
            reasoning=reasoning,
            tools=tools,
            first_class_support=False,
        )

    @classmethod
    def router(cls) -> APIRouter | None:
        # Premium-Provider connections do not expose adapter sub-routes:
        # key validation runs through the generic /api/providers/accounts
        # probe endpoint (see backend.modules.providers._probe).
        return None

    async def fetch_models(
        self, c: ResolvedConnection,
    ) -> list[ModelMetaDto]:
        api_key = c.config.get("api_key") or ""
        headers = {"Authorization": f"Bearer {api_key}"}
        metas: list[ModelMetaDto] = []
        page = 0
        limit = 100  # Chutes default is 25; bump to reduce round-trips.

        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            while True:
                try:
                    resp = await client.get(
                        f"{_INFERENCE_BASE_URL}/models",
                        params={"page": page, "limit": limit},
                        headers=headers,
                    )
                except httpx.HTTPError as exc:
                    _log.warning("chutes_http.fetch_models transport: %s", exc)
                    return metas

                if resp.status_code in (401, 403):
                    _log.warning(
                        "chutes_http.fetch_models auth failure: status=%d",
                        resp.status_code,
                    )
                    return metas
                if resp.status_code != 200:
                    _log.warning(
                        "chutes_http.fetch_models upstream %d: %s",
                        resp.status_code, resp.text[:200],
                    )
                    return metas

                try:
                    body = resp.json()
                except ValueError:
                    _log.warning("chutes_http.fetch_models malformed JSON")
                    return metas

                entries = body.get("data") or []
                if not isinstance(entries, list):
                    return metas

                for entry in entries:
                    if not isinstance(entry, dict) or not entry.get("id"):
                        continue
                    meta = _entry_to_meta(entry, c, adapter=self)
                    if meta is not None:
                        metas.append(meta)

                if len(entries) < limit:
                    return metas
                page += 1

    async def stream_completion(
        self, c: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        api_key = c.config.get("api_key") or ""

        payload = build_request_body(request)
        whitelist = self._sampling_params_by_model_id.get(request.model)
        payload = _filter_to_whitelist(payload, whitelist)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        if _TRACE_PAYLOADS:
            _log.info(
                "LLM_TRACE path=chutes-out url=%s payload=%s",
                _INFERENCE_BASE_URL,
                json.dumps(payload, default=str, sort_keys=True),
            )

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for attempt in range(MAX_RETRY_ATTEMPTS + 1):
                retry_delay: float | None = None
                try:
                    async with client.stream(
                        "POST", f"{_INFERENCE_BASE_URL}/chat/completions",
                        json=payload, headers=headers,
                    ) as resp:
                        if (
                            should_retry_status(resp.status_code)
                            and attempt < MAX_RETRY_ATTEMPTS
                        ):
                            retry_delay = compute_retry_delay(
                                attempt, parse_retry_after(resp.headers),
                            )
                            log_retry(
                                _log,
                                operation="chutes_http",
                                attempt=attempt,
                                delay_seconds=retry_delay,
                                status_code=resp.status_code,
                                extra={"model": payload.get("model")},
                            )
                        elif resp.status_code in (401, 403):
                            yield StreamError(
                                error_code="invalid_api_key",
                                message="Chutes rejected the API key",
                            )
                            return
                        elif should_retry_status(resp.status_code):
                            yield StreamError(
                                error_code="provider_unavailable",
                                message=(
                                    f"Chutes returned {resp.status_code}; "
                                    f"gave up after {MAX_RETRY_ATTEMPTS + 1} attempts"
                                ),
                            )
                            return
                        elif resp.status_code != 200:
                            body = await resp.aread()
                            detail = body.decode("utf-8", errors="replace")[:500]
                            _log.error(
                                "chutes_http upstream %d: %s",
                                resp.status_code, detail,
                            )
                            yield StreamError(
                                error_code="provider_unavailable",
                                message=f"Chutes returned {resp.status_code}: {detail}",
                            )
                            return
                        else:
                            acc = _ToolCallAccumulator()
                            seen_done = False
                            last_usage: dict = {}
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
                                                "chutes_http.gutter_slow "
                                                "model=%s idle=%.1fs",
                                                payload.get("model"), elapsed,
                                            )
                                            yield StreamSlow()
                                            slow_fired = True
                                            continue
                                        _log.warning(
                                            "chutes_http.gutter_abort "
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
                                    if (
                                        isinstance(parsed, dict)
                                        and parsed.get("usage")
                                    ):
                                        last_usage = parsed["usage"]

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
                                _details = (
                                    last_usage.get("completion_tokens_details") or {}
                                )
                                yield StreamDone(
                                    input_tokens=last_usage.get("prompt_tokens"),
                                    output_tokens=last_usage.get("completion_tokens"),
                                    reasoning_tokens=_details.get("reasoning_tokens"),
                                )
                            return
                except httpx.ConnectError:
                    yield StreamError(
                        error_code="provider_unavailable",
                        message="Cannot connect to Chutes",
                    )
                    return

                # Retry path — sleep with the stream context closed.
                assert retry_delay is not None
                await asyncio.sleep(retry_delay)

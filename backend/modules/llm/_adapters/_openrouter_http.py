"""OpenRouter HTTP adapter — OpenAI-compatible Chat Completions.

Premium-only adapter: not user-creatable. Instantiated exclusively via
the Premium Provider resolver (see ``backend.modules.llm._resolver``).
Routes to OpenRouter's unified API which fans out to 50+ upstream
providers; we apply ``output_modalities=text`` at the model-listing
endpoint so only text-output models reach the Model Browser.

Cache control: OpenRouter performs automatic prefix caching for
OpenAI / Gemini / DeepSeek (transparent, no markers). For Anthropic
(Claude) models, explicit ``cache_control`` markers are emitted by
``build_request_body`` when the persona has opted in via
``anthropic_cache_ttl``. The marker placement strategy lives in
``_anthropic_cache.py`` (system + block-boundary + rolling tail); see
``devdocs/specs/2026-05-08-claude-router-cache-breakpoints-design.md``.
This reverses the Phase-1 pass-through decision recorded in INS-032.

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
import time
from collections.abc import AsyncIterator
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
_PROBE_TIMEOUT = httpx.Timeout(10.0)

GUTTER_SLOW_SECONDS: float = 30.0
GUTTER_ABORT_SECONDS: float = float(
    os.environ.get("LLM_STREAM_ABORT_SECONDS", "120"),
)
_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=15.0)
_TRACE_PAYLOADS = os.environ.get("LLM_TRACE_PAYLOADS") == "1"

# Retry policy for transient 429 / 503s lives in ``backend._retry``.
# OpenRouter routes between many upstream providers; an individual
# provider can briefly rate-limit (429) or be momentarily unavailable
# (503) even when the user's account has no global ceiling.

# OpenRouter app-attribution headers. ``HTTP-Referer`` is the primary
# identifier; the others surface us in the OpenRouter leaderboards and
# marketplace categorisation. Categories must come from OpenRouter's
# fixed vocabulary (unrecognised values are silently dropped).
_OPENROUTER_REFERER = "https://github.com/symphonic-navigator/chatsune"
_OPENROUTER_TITLE = "Chatsune"
_OPENROUTER_CATEGORIES = "general-chat,roleplay"

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


def _entry_to_meta(
    entry: dict, c: ResolvedConnection, *, adapter: BaseAdapter,
) -> ModelMetaDto | None:
    """Map one OpenRouter catalogue entry to a ``ModelMetaDto`` or ``None``.

    The reasoning/tools capabilities go through ``resolve_capabilities``
    (YAML override → adapter heuristic → universal default). The adapter
    heuristic lives in ``OpenRouterHttpAdapter.capability_hint`` and
    consults the catalogue ``supported_parameters`` list for this entry —
    see that method.
    """
    from backend.modules.llm._capabilities import resolve_capabilities

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

    # Stash the catalogue-derived parameter list on the adapter so
    # ``capability_hint`` can consult it without re-running the
    # catalogue. ``resolve_capabilities`` calls ``capability_hint``
    # exactly once per model_id below.
    adapter._params_by_model_id[entry["id"]] = list(params)
    resolved = resolve_capabilities(
        adapter_type="openrouter",
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


def _translate_message(
    msg: CompletionMessage,
    *,
    cache_control: dict | None = None,
) -> dict:
    text_parts = [p for p in msg.content if p.type == "text" and p.text]
    image_parts = [p for p in msg.content if p.type == "image" and p.data]

    if cache_control is None and not image_parts:
        # Plain string content — more cache-friendly for non-Anthropic
        # routes that perform automatic prefix caching.
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
        if cache_control and content:
            # Anthropic convention: cache_control on the LAST content
            # block of the marked message — that block's index defines
            # the prefix endpoint that gets cached.
            content[-1]["cache_control"] = cache_control

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
    """Translate a CompletionRequest into the OpenRouter ``/chat/completions`` body.

    Translation rules — read together with spec §6.3:

    * ``model``, ``messages``, ``stream=True``, and ``stream_options``
      (for usage piggybacking) are always present.
    * ``temperature`` only when explicitly set on the request.
    * ``tools`` only when the request carries them AND the session has
      tools enabled. The session toggle is the ground truth — adapters
      never second-guess it.
    * ``reasoning`` block only when ``request.reasoning.kind ==
      "optional"``. The body carries OpenRouter's unified shape
      ``{"enabled": <bool>}`` plus ``"effort"`` when
      ``request.extras.reasoning_effort`` is set. Always written
      explicitly (true or false) — vendors disagree on the default
      direction (gpt-5 default OFF, claude-sonnet default ON), so
      omitting it would surrender control of the toggle. For
      ``no_reasoning`` and ``always_on`` kinds the field is omitted
      entirely. Per spec §2 non-goals we do NOT use the legacy
      ``reasoning: {exclude: true}`` shape to fake an off-state —
      ``exclude`` controls visibility, not whether the model reasons.
    * Anthropic ``cache_control`` markers are applied to messages when
      ``anthropic_cache_ttl != "off"`` and the model is in the Anthropic
      family. See ``_anthropic_cache.py`` for the placement strategy.
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
            request.messages, request.anthropic_cache_ttl,
        ):
            cc_by_index[marker.message_index] = _to_cache_control(marker.ttl)

    payload: dict = {
        "model": request.model,
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [
            _translate_message(m, cache_control=cc_by_index.get(i))
            for i, m in enumerate(request.messages)
        ],
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.tools and request.extras.tools_enabled:
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
    if request.reasoning.kind == "optional":
        reasoning_on = request.extras.reasoning_mode == "on"
        # For Anthropic models routed via OpenRouter (typically through
        # Google Vertex), the universal ``effort`` shorthand is interpreted
        # as a percentage of response max_tokens — so ``low`` becomes ~12k
        # thinking tokens. Per OR docs, ``reasoning.max_tokens`` is the
        # numeric override Anthropic-style models prefer. Critically, OR's
        # docs say "setting max_tokens automatically enables reasoning",
        # and field-testing suggests that ``enabled: true`` AND
        # ``max_tokens`` together can leave OR using upstream defaults
        # rather than honouring the explicit budget. So for Anthropic we
        # send ONLY max_tokens when on, and ONLY ``enabled: false`` when
        # off — never mixed.
        if is_anthropic_model(request.model) and reasoning_on:
            bucket = request.extras.reasoning_effort or "medium"
            payload["reasoning"] = {
                "max_tokens": _ANTHROPIC_REASONING_BUDGET.get(
                    bucket, _ANTHROPIC_REASONING_BUDGET["medium"],
                ),
            }
        else:
            reasoning_obj: dict = {"enabled": reasoning_on}
            if reasoning_on and request.extras.reasoning_effort:
                reasoning_obj["effort"] = request.extras.reasoning_effort
            payload["reasoning"] = reasoning_obj
    return payload


# Bucket-to-token-budget translation for Anthropic models routed via
# OpenRouter (spec §6.4). The raw thinking budget that Anthropic sees,
# NOT a percentage. ``minimal`` is included for symmetry with the GPT-5
# bucket vocabulary; for Anthropic's effort spec we expect only
# low/medium/high in practice.
#
# Calibration note (2026-05-09): ``low`` deliberately set to 128 for
# field-test observation — well below Anthropic's documented thinking
# minimum (~1024), so we expect the upstream to either reject, clamp,
# or skip reasoning entirely. Keep an eye on real responses; raise
# back to 1024–2048 once the behaviour at the floor is understood.
_ANTHROPIC_REASONING_BUDGET: dict[str, int] = {
    "minimal":   128,
    "low":       128,
    "medium":   8192,
    "high":    16384,
}


def _to_cache_control(ttl: str) -> dict:
    # OpenAI-compat → Anthropic translation: 5m is the implicit
    # default when ``ttl`` is omitted; 1h must be set explicitly.
    if ttl == "1h":
        return {"type": "ephemeral", "ttl": "1h"}
    return {"type": "ephemeral"}


def _log_anthropic_cache(
    request: CompletionRequest, payload: dict, last_usage: dict,
) -> None:
    """Emit the ``anthropic_cache`` observability line for Claude completions.

    Called on every successful end-of-stream path (both the
    ``_chunk_to_events``-emitted ``StreamDone`` and the safety-net
    ``StreamDone`` after the SSE loop). Gated on ``is_anthropic_model``
    so non-Claude completions stay quiet — keeps ``grep anthropic_cache``
    precise.
    """
    if not is_anthropic_model(request.model):
        return
    cache_read, cache_creation = extract_cache_metrics(last_usage)
    _log.info(
        "anthropic_cache adapter=openrouter model=%s ttl=%s "
        "cache_read=%d cache_creation=%d input=%d",
        payload.get("model"),
        request.anthropic_cache_ttl,
        cache_read,
        cache_creation,
        last_usage.get("prompt_tokens", 0),
    )


class OpenRouterHttpAdapter(BaseAdapter):
    adapter_type = "openrouter_http"
    display_name = "OpenRouter"
    view_id = "openrouter_http"
    secret_fields = frozenset({"api_key"})

    def __init__(self) -> None:
        # Populated by ``_entry_to_meta`` per call. Consulted by
        # ``capability_hint`` when ``resolve_capabilities`` falls
        # through past the YAML overrides. Per-instance state — and
        # the adapter is constructed fresh per request, so there is
        # no cross-request contamination.
        self._params_by_model_id: dict[str, list[str]] = {}

    def capability_hint(self, model_id: str):
        """Best-effort capability hint based on the catalogue
        ``supported_parameters`` list for this model.

        OpenRouter normalises the heterogeneous reasoning surface across
        50+ upstream providers via the unified ``reasoning`` parameter.
        Presence of either ``"reasoning"`` or ``"include_reasoning"`` in
        ``supported_parameters`` indicates the model accepts the
        reasoning toggle. We emit ``optional`` reasoning without an
        ``effort`` spec — OpenRouter does not publish per-model effort
        buckets in the catalogue, so we fall through to YAML overrides
        for first-class effort support. Returns ``None`` (resolver falls
        through to the universal default) when the catalogue did not
        populate parameters for this model_id, e.g. when
        ``capability_hint`` is invoked outside ``fetch_models``.
        """
        from backend.modules.llm._capabilities import CapabilityHint

        params = self._params_by_model_id.get(model_id)
        if params is None:
            return None
        if _supports(params, "reasoning", "include_reasoning"):
            reasoning = ReasoningCapability(kind="optional")
        else:
            reasoning = ReasoningCapability(kind="no_reasoning")
        tools = ToolCapability(supported=_supports(params, "tools"))
        return CapabilityHint(
            reasoning=reasoning,
            tools=tools,
            first_class_support=False,
        )

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
            meta = _entry_to_meta(entry, c, adapter=self)
            if meta is not None:
                metas.append(meta)
        return metas

    async def stream_completion(
        self, c: ResolvedConnection, request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        url = c.config["url"].rstrip("/")
        api_key = c.config.get("api_key") or ""
        payload = build_request_body(request)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": _OPENROUTER_REFERER,
            "X-OpenRouter-Title": _OPENROUTER_TITLE,
            "X-OpenRouter-Categories": _OPENROUTER_CATEGORIES,
        }

        if _TRACE_PAYLOADS:
            _log.info(
                "LLM_TRACE path=openrouter-out url=%s payload=%s",
                url, json.dumps(payload, default=str, sort_keys=True),
            )

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for attempt in range(MAX_RETRY_ATTEMPTS + 1):
                # Set inside the inner block when we decide to retry.
                # Read after the inner ``async with`` exits so we can
                # sleep with the connection already closed.
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
                                operation="openrouter_http",
                                attempt=attempt,
                                delay_seconds=retry_delay,
                                status_code=resp.status_code,
                                extra={"model": payload.get("model")},
                            )
                            # Fall through to the outer ``await sleep``.
                        elif resp.status_code in (401, 403):
                            yield StreamError(
                                error_code="invalid_api_key",
                                message="OpenRouter rejected the API key",
                            )
                            return
                        elif should_retry_status(resp.status_code):
                            yield StreamError(
                                error_code="provider_unavailable",
                                message=(
                                    f"OpenRouter returned "
                                    f"{resp.status_code}; gave up after "
                                    f"{MAX_RETRY_ATTEMPTS + 1} attempts"
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
                            # Track usage across chunks. OR-routed Anthropic
                            # responses sometimes deliver ``usage`` in the
                            # same chunk as ``finish_reason="stop"`` (rather
                            # than the OpenAI-standard separate usage chunk),
                            # which would otherwise hide it from
                            # ``_chunk_to_events`` and from the
                            # ``anthropic_cache`` log line. Capturing usage
                            # whenever it appears, on any chunk, makes both
                            # token tracking and the log robust to that.
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

                                    if (
                                        isinstance(parsed, dict)
                                        and parsed.get("usage")
                                    ):
                                        last_usage = parsed["usage"]

                                    for event in _chunk_to_events(parsed, acc):
                                        if isinstance(event, StreamDone):
                                            seen_done = True
                                            _log_anthropic_cache(
                                                request, payload, last_usage,
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
                                yield StreamDone(
                                    input_tokens=last_usage.get("prompt_tokens"),
                                    output_tokens=last_usage.get("completion_tokens"),
                                )
                                _log_anthropic_cache(
                                    request, payload, last_usage,
                                )
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

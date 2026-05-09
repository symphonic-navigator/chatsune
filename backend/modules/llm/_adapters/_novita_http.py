"""Novita AI HTTP adapter — OpenAI-compatible Chat Completions.

Premium-only adapter: not user-creatable. Instantiated exclusively via
the Premium Provider resolver (see ``backend.modules.llm._resolver``).
Routes to Novita's open-source inference platform; we filter to text-
output, serverless, chat-typed models with a >=80k context window.

Structurally a slimmed-down clone of ``_openrouter_http.py``. The diff
vs OR is: no Anthropic-cache logic (Novita is open-source-only, not a
router), no OR-specific app-attribution headers, and a different model-
list schema. The shared OpenAI-compat SSE-helper extraction remains
deferred to its own session — helpers stay cloned per adapter for now.
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

_REFUSAL_REASONS: frozenset[str] = frozenset({"content_filter", "refusal"})

_PROBE_TIMEOUT = httpx.Timeout(10.0)

GUTTER_SLOW_SECONDS: float = 30.0
GUTTER_ABORT_SECONDS: float = float(
    os.environ.get("LLM_STREAM_ABORT_SECONDS", "120"),
)
_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=15.0)
_TRACE_PAYLOADS = os.environ.get("LLM_TRACE_PAYLOADS") == "1"

_SSE_DONE = object()  # sentinel — distinct from any JSON-decodable value


class _ToolCallAccumulator:
    """Gathers OpenAI-style tool_call fragments across SSE chunks.

    ``finalised()`` is idempotent: subsequent calls return an empty list.
    Some upstream providers emit two chunks with
    ``finish_reason="tool_calls"`` for the same call.
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


# Mirrors nano-gpt / OpenRouter — sub-80k models leave no breathing
# room once chat history and tool definitions stack up. Spec §"Filter
# Rules".
MIN_CONTEXT_TOKENS = 80_000


def _entry_to_meta(
    entry: dict, c: ResolvedConnection, *, adapter: BaseAdapter,
) -> ModelMetaDto | None:
    """Map one Novita catalogue entry to a ``ModelMetaDto`` or ``None``.

    Filter rules — all must pass; see spec §"Model Filter Rules":
    1. ``output_modalities == ["text"]``
    2. ``context_size >= MIN_CONTEXT_TOKENS``
    3. ``"chat/completions" in endpoints``
    4. ``"serverless" in features``
    5. ``model_type == "chat"``
    6. ``status == 1``

    The reasoning/tools capabilities go through ``resolve_capabilities``
    (YAML override → adapter heuristic → universal default). The adapter
    heuristic lives in ``NovitaHttpAdapter.capability_hint`` and consults
    the catalogue ``features`` list for this entry — see that method.
    """
    from backend.modules.llm._capabilities import resolve_capabilities

    output_mods = entry.get("output_modalities") or []
    if output_mods != ["text"]:
        return None

    context_size = int(entry.get("context_size") or 0)
    if context_size < MIN_CONTEXT_TOKENS:
        return None

    endpoints = entry.get("endpoints") or []
    if "chat/completions" not in endpoints:
        return None

    features = entry.get("features") or []
    if "serverless" not in features:
        return None

    if entry.get("model_type") != "chat":
        return None

    if entry.get("status") != 1:
        return None

    input_mods = entry.get("input_modalities") or []
    in_price = entry.get("input_token_price_per_m") or 0
    out_price = entry.get("output_token_price_per_m") or 0
    billing = "free" if in_price == 0 and out_price == 0 else "pay_per_token"

    # Stash the catalogue-derived feature list on the adapter so
    # ``capability_hint`` can consult it without re-running the
    # catalogue. ``resolve_capabilities`` calls ``capability_hint``
    # exactly once per model_id below.
    adapter._features_by_model_id[entry["id"]] = list(features)
    resolved = resolve_capabilities(
        adapter_type="novita",
        model_id=entry["id"],
        adapter=adapter,
    )

    return ModelMetaDto(
        connection_id=c.id,
        connection_slug=c.slug,
        connection_display_name=c.display_name,
        model_id=entry["id"],
        display_name=entry.get("display_name") or entry["id"],
        context_window=context_size,
        reasoning=resolved.reasoning,
        tools=resolved.tools,
        first_class_support=resolved.first_class_support,
        supports_vision="image" in input_mods,
        supports_tool_calls="function-calling" in features,
        is_deprecated=False,
        billing_category=billing,
        is_moderated=None,
    )


def _translate_message(msg: CompletionMessage) -> dict:
    """Translate our CompletionMessage into an OpenAI-compatible chat
    message. Plain text collapses to a string; images force the array
    form. No cache_control markers — Novita does not route to Anthropic."""
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
    """Translate a CompletionRequest into the Novita ``/chat/completions`` body.

    Translation rules — read together with spec §6.3:

    * ``model``, ``messages``, ``stream=True``, and ``stream_options``
      (for usage piggybacking) are always present.
    * ``temperature`` only when explicitly set on the request.
    * ``tools`` only when the request carries them AND the session has
      tools enabled. The session toggle is the ground truth — adapters
      never second-guess it.
    * ``reasoning`` block only when ``request.reasoning.kind ==
      "optional"``. The body carries the OpenRouter unified shape
      ``{"enabled": <bool>}`` plus ``"effort"`` when
      ``request.extras.reasoning_effort`` is set. Always written
      explicitly (true or false) — Novita's default direction is
      per-model so omitting it would surrender control of the toggle.
      For ``no_reasoning`` and ``always_on`` kinds the field is
      omitted entirely. Per spec §6.3 we do NOT use the legacy
      ``reasoning: {exclude: true}`` shape to fake an off-state.
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
                    "name": t.name, "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in request.tools
        ]
    if request.reasoning.kind == "optional":
        reasoning_obj: dict = {
            "enabled": request.extras.reasoning_mode == "on",
        }
        if request.extras.reasoning_effort:
            reasoning_obj["effort"] = request.extras.reasoning_effort
        payload["reasoning"] = reasoning_obj
    return payload


class NovitaHttpAdapter(BaseAdapter):
    adapter_type = "novita_http"
    display_name = "Novita AI"
    view_id = "novita_http"
    secret_fields = frozenset({"api_key"})

    def __init__(self) -> None:
        # Populated by ``_entry_to_meta`` per call. Consulted by
        # ``capability_hint`` when ``resolve_capabilities`` falls
        # through past the YAML overrides. Per-instance state — and
        # the adapter is constructed fresh per request, so there is
        # no cross-request contamination.
        self._features_by_model_id: dict[str, list[str]] = {}

    def capability_hint(self, model_id: str):
        """Best-effort capability hint based on the catalogue ``features``
        list for this model.

        The hint is heuristic — Novita's ``"reasoning"`` feature flag
        signals the model has a reasoning toggle, but Novita does not
        publish per-model effort buckets, so we emit ``optional``
        without an ``effort`` spec. Returns ``None`` (resolver falls
        through to the universal default) when the catalogue did not
        populate features for this model_id, e.g. when ``capability_hint``
        is invoked outside ``fetch_models``.
        """
        from backend.modules.llm._capabilities import CapabilityHint

        features = self._features_by_model_id.get(model_id)
        if features is None:
            return None
        if "reasoning" in features:
            reasoning = ReasoningCapability(kind="optional")
        else:
            reasoning = ReasoningCapability(kind="no_reasoning")
        tools = ToolCapability(supported="function-calling" in features)
        return CapabilityHint(
            reasoning=reasoning,
            tools=tools,
            first_class_support=False,
        )

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
            _log.warning("novita_http.fetch_models transport: %s", exc)
            return []

        if resp.status_code in (401, 403):
            _log.warning(
                "novita_http.fetch_models auth failure: status=%d",
                resp.status_code,
            )
            return []
        if resp.status_code != 200:
            _log.warning(
                "novita_http.fetch_models upstream %d: %s",
                resp.status_code, resp.text[:200],
            )
            return []

        try:
            data = resp.json()
        except ValueError:
            _log.warning("novita_http.fetch_models malformed JSON")
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
        }

        if _TRACE_PAYLOADS:
            _log.info(
                "LLM_TRACE path=novita-out url=%s payload=%s",
                url, json.dumps(payload, default=str, sort_keys=True),
            )

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for attempt in range(MAX_RETRY_ATTEMPTS + 1):
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
                                operation="novita_http",
                                attempt=attempt,
                                delay_seconds=retry_delay,
                                status_code=resp.status_code,
                                extra={"model": payload.get("model")},
                            )
                        elif resp.status_code in (401, 403):
                            yield StreamError(
                                error_code="invalid_api_key",
                                message="Novita rejected the API key",
                            )
                            return
                        elif should_retry_status(resp.status_code):
                            yield StreamError(
                                error_code="provider_unavailable",
                                message=(
                                    f"Novita returned {resp.status_code}; "
                                    f"gave up after {MAX_RETRY_ATTEMPTS + 1} "
                                    f"attempts"
                                ),
                            )
                            return
                        elif resp.status_code != 200:
                            body = await resp.aread()
                            detail = body.decode(
                                "utf-8", errors="replace",
                            )[:500]
                            _log.error(
                                "novita_http upstream %d: %s",
                                resp.status_code, detail,
                            )
                            yield StreamError(
                                error_code="provider_unavailable",
                                message=(
                                    f"Novita returned {resp.status_code}: "
                                    f"{detail}"
                                ),
                            )
                            return
                        else:
                            # 200 — process the SSE body. Once we begin
                            # yielding stream events no further retry is
                            # safe (partial tokens may already be in the
                            # user's UI).
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
                                        GUTTER_ABORT_SECONDS - elapsed
                                        if slow_fired
                                        else GUTTER_SLOW_SECONDS - elapsed
                                    )
                                    if budget <= 0:
                                        if not slow_fired:
                                            _log.info(
                                                "novita_http.gutter_slow "
                                                "model=%s idle=%.1fs",
                                                payload.get("model"),
                                                elapsed,
                                            )
                                            yield StreamSlow()
                                            slow_fired = True
                                            continue
                                        _log.warning(
                                            "novita_http.gutter_abort "
                                            "model=%s idle=%.1fs",
                                            payload.get("model"), elapsed,
                                        )
                                        if pending_next is not None:
                                            pending_next.cancel()
                                        yield StreamAborted(
                                            reason="gutter_timeout",
                                        )
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
                                        if isinstance(event, (
                                            StreamDone, StreamRefused,
                                            StreamError,
                                        )):
                                            return
                            except asyncio.CancelledError:
                                if (
                                    pending_next is not None
                                    and not pending_next.done()
                                ):
                                    pending_next.cancel()
                                raise
                            if not seen_done:
                                yield StreamDone(
                                    input_tokens=last_usage.get("prompt_tokens"),
                                    output_tokens=last_usage.get(
                                        "completion_tokens",
                                    ),
                                )
                            return
                except httpx.ConnectError:
                    yield StreamError(
                        error_code="provider_unavailable",
                        message="Cannot connect to Novita",
                    )
                    return

                # Retry path: a 429 with attempts remaining set retry_delay.
                # Sleep with the stream context closed.
                assert retry_delay is not None
                await asyncio.sleep(retry_delay)

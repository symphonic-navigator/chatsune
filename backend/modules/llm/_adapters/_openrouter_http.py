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

import json
import logging
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
from shared.dtos.inference import CompletionRequest
from shared.dtos.llm import ModelMetaDto

_log = logging.getLogger(__name__)
_PROBE_TIMEOUT = httpx.Timeout(10.0)


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
        context_window=int(entry.get("context_length") or 0),
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
    """Gathers OpenAI-style tool_call fragments across SSE chunks."""

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


class OpenRouterHttpAdapter(BaseAdapter):
    adapter_type = "openrouter_http"
    display_name = "OpenRouter"
    view_id = "openrouter_http"
    secret_fields = frozenset({"api_key"})

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
        raise NotImplementedError  # filled in Task 10
        yield  # pragma: no cover  # makes the type checker accept the signature

import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from uuid import uuid4

import httpx

from backend.config import settings
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
from shared.dtos.inference import CompletionMessage, CompletionRequest
from shared.dtos.llm import ModelMetaDto

_log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=15.0)

_REFUSAL_REASONS: frozenset[str] = frozenset({"content_filter", "refusal"})


def _is_refusal_reason(reason: str | None) -> bool:
    """Return True if the Ollama done_reason value marks a refusal.

    Case-insensitive. Extension point: when new upstream providers are
    observed in production logs emitting other refusal markers, add
    them to _REFUSAL_REASONS.
    """
    if not reason:
        return False
    return reason.lower() in _REFUSAL_REASONS

# Two-stage NDJSON idle thresholds. At GUTTER_SLOW_SECONDS of silence we
# emit a StreamSlow (informational); at GUTTER_ABORT_SECONDS we give up
# and emit StreamAborted. Module-level so tests can monkey-patch them.
# The abort threshold is sourced from LLM_STREAM_ABORT_SECONDS so that
# operators can extend it without a code change.
GUTTER_SLOW_SECONDS: float = 30.0
GUTTER_ABORT_SECONDS: float = float(os.environ.get("LLM_STREAM_ABORT_SECONDS", "120"))


def _parse_parameter_size(value: str) -> int | None:
    """Parse a parameter_size string like '7.6B', '405M', '1.2T' into a raw integer."""
    value = value.strip().upper()
    suffixes = {"T": 1_000_000_000_000, "B": 1_000_000_000, "M": 1_000_000, "K": 1_000}
    for suffix, multiplier in suffixes.items():
        if value.endswith(suffix):
            try:
                return int(float(value[:-1]) * multiplier)
            except (ValueError, TypeError):
                return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _format_parameter_count(value: int | None) -> str | None:
    """Convert raw parameter count to human-readable form (e.g. 675B, 7.5B, 405M)."""
    if not value:
        return None
    if value >= 1_000_000_000_000:
        n = value / 1_000_000_000_000
        return f"{int(n)}T" if n == int(n) else f"{n:.1f}T"
    if value >= 1_000_000_000:
        n = value / 1_000_000_000
        return f"{int(n)}B" if n == int(n) else f"{n:.1f}B"
    if value >= 1_000_000:
        n = value / 1_000_000
        return f"{int(n)}M" if n == int(n) else f"{n:.1f}M"
    return None


def _build_display_name(model_name: str) -> str:
    """Convert 'mistral-large-3:675b' to 'Mistral Large 3 (675B)'."""
    colon_idx = model_name.find(":")
    if colon_idx >= 0:
        name_part = model_name[:colon_idx]
        tag = model_name[colon_idx + 1:]
    else:
        name_part = model_name
        tag = None
    title = " ".join(word.capitalize() for word in name_part.split("-"))
    if not tag or tag.lower() == "latest":
        return title
    return f"{title} ({tag.upper()})"


def _translate_message(msg: CompletionMessage) -> dict:
    """Convert a CompletionMessage to Ollama's message format."""
    text_parts = [p.text for p in msg.content if p.type == "text" and p.text]
    images = [p.data for p in msg.content if p.type == "image" and p.data]
    result: dict = {
        "role": msg.role,
        "content": "".join(text_parts) if text_parts else "",
    }
    if images:
        result["images"] = images
    if msg.tool_calls:
        result["tool_calls"] = [
            {"function": {"name": tc.name, "arguments": json.loads(tc.arguments)}}
            for tc in msg.tool_calls
        ]
    return result


class OllamaBaseAdapter(BaseAdapter):
    """Shared logic for Ollama-compatible HTTP backends.

    Subclasses set ``provider_id`` / ``provider_display_name`` and override
    ``_auth_headers`` (and, where applicable, ``validate_key``).
    """

    # Subclasses MUST override
    provider_id: str = ""
    provider_display_name: str = ""

    def __init__(self, base_url: str) -> None:
        super().__init__(base_url=base_url)
        self._client = httpx.AsyncClient(timeout=_TIMEOUT)

    async def aclose(self) -> None:
        await self._client.aclose()

    # ----- subclass hooks -----

    def _auth_headers(self, api_key: str | None) -> dict:
        """Return per-request HTTP headers for upstream auth. Default: none."""
        return {}

    async def validate_key(self, api_key: str | None) -> bool:
        """Default no-op validation. Subclasses with real auth override."""
        return True

    # ----- shared implementation -----

    async def fetch_models(self) -> list[ModelMetaDto]:
        tags_resp = await self._client.get(
            f"{self.base_url}/api/tags",
            headers=self._auth_headers(None),
        )
        tags_resp.raise_for_status()
        tag_entries = tags_resp.json().get("models", [])

        sem = asyncio.Semaphore(5)

        async def _fetch_one(name: str) -> tuple[str, dict | None]:
            async with sem:
                try:
                    show_resp = await self._client.post(
                        f"{self.base_url}/api/show",
                        json={"model": name},
                        headers=self._auth_headers(None),
                    )
                    show_resp.raise_for_status()
                    return name, show_resp.json()
                except Exception:
                    _log.warning("Failed to fetch details for model '%s'; skipping.", name)
                    return name, None

        results = await asyncio.gather(
            *(_fetch_one(entry["name"]) for entry in tag_entries),
        )
        return [self._map_to_dto(name, detail) for name, detail in results if detail is not None]

    async def stream_completion(
        self,
        api_key: str | None,
        request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        payload = self._build_chat_payload(request)
        seen_done = False
        pending_next: asyncio.Task | None = None
        try:
            async with self._client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
                headers=self._auth_headers(api_key),
            ) as resp:
                if resp.status_code in (401, 403):
                    yield StreamError(error_code="invalid_api_key", message="Invalid API key")
                    return
                if resp.status_code != 200:
                    body = await resp.aread()
                    detail = body.decode("utf-8", errors="replace")[:500]
                    _log.error(
                        "Upstream returned %d for model %s: %s",
                        resp.status_code, payload.get("model"), detail,
                    )
                    yield StreamError(
                        error_code="provider_unavailable",
                        message=f"Upstream returned {resp.status_code}: {detail}",
                    )
                    return

                stream_iter = resp.aiter_lines().__aiter__()
                line_start = time.monotonic()
                slow_fired = False

                while True:
                    elapsed = time.monotonic() - line_start
                    if slow_fired:
                        budget = GUTTER_ABORT_SECONDS - elapsed
                    else:
                        budget = GUTTER_SLOW_SECONDS - elapsed

                    if budget <= 0:
                        if not slow_fired:
                            _log.info(
                                "ollama_base.gutter_slow model=%s idle=%.1fs",
                                payload.get("model"), elapsed,
                            )
                            yield StreamSlow()
                            slow_fired = True
                            continue  # re-evaluate against the abort deadline
                        _log.warning(
                            "ollama_base.gutter_abort model=%s idle=%.1fs",
                            payload.get("model"), elapsed,
                        )
                        if pending_next is not None:
                            pending_next.cancel()
                        yield StreamAborted(reason="gutter_timeout")
                        return

                    # Reuse the in-flight __anext__ task across timeout retries.
                    # asyncio.wait_for would cancel the wrapped coroutine on
                    # timeout, which interrupts the underlying httpx read mid-
                    # buffer; the next __anext__ call would then either skip
                    # data or fail on a partially consumed read state. Holding
                    # a single task across iterations and observing it via
                    # asyncio.wait avoids that hazard entirely.
                    if pending_next is None:
                        pending_next = asyncio.ensure_future(stream_iter.__anext__())

                    done, _ = await asyncio.wait({pending_next}, timeout=budget)

                    if not done:
                        continue  # timed out — loop back, recompute budget

                    task = done.pop()
                    pending_next = None
                    try:
                        line = task.result()
                    except StopAsyncIteration:
                        break

                    # Successful line — reset the window. slow_fired is
                    # cleared so a subsequent silence phase will re-announce.
                    # The frontend also clears its slow flag implicitly on
                    # any subsequent content/thinking delta.
                    line_start = time.monotonic()
                    slow_fired = False

                    line = line.strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        _log.warning("Skipping malformed NDJSON line: %s", line)
                        continue

                    if settings.inference_logging:
                        msg = chunk.get("message") or {}
                        tcs = msg.get("tool_calls") or []
                        _log.info(
                            "ollama_base.chunk model=%s done=%s done_reason=%s "
                            "content_chars=%d thinking_chars=%d tool_calls=%d",
                            payload.get("model"),
                            bool(chunk.get("done")),
                            chunk.get("done_reason"),
                            len(msg.get("content") or ""),
                            len(msg.get("thinking") or ""),
                            len(tcs),
                        )
                        if tcs:
                            for _tc in tcs:
                                _fn = _tc.get("function") or {}
                                _log.info(
                                    "ollama_base.chunk.tool_call model=%s name=%s "
                                    "args_chars=%d",
                                    payload.get("model"),
                                    _fn.get("name"),
                                    len(json.dumps(_fn.get("arguments") or {})),
                                )

                    if chunk.get("done"):
                        seen_done = True
                        done_reason = chunk.get("done_reason")

                        # Observability: surface any non-vanilla done_reason value so we
                        # can discover new refusal markers from production logs.
                        if done_reason and done_reason not in ("stop", "length"):
                            _log.info(
                                "ollama_base.done_reason model=%s reason=%s",
                                payload.get("model"), done_reason,
                            )

                        if _is_refusal_reason(done_reason):
                            msg = chunk.get("message", {})
                            refusal_body = msg.get("refusal") or None
                            yield StreamRefused(
                                reason=done_reason,
                                refusal_text=refusal_body,
                            )
                            return  # Refusal is terminal; no StreamDone after this.

                        yield StreamDone(
                            input_tokens=chunk.get("prompt_eval_count"),
                            output_tokens=chunk.get("eval_count"),
                        )
                        break

                    message = chunk.get("message", {})
                    thinking = message.get("thinking", "")
                    if thinking:
                        yield ThinkingDelta(delta=thinking)
                    content = message.get("content", "")
                    if content:
                        yield ContentDelta(delta=content)
                    for tc in message.get("tool_calls", []):
                        fn = tc.get("function", {})
                        yield ToolCallEvent(
                            id=f"call_{uuid4().hex[:12]}",
                            name=fn.get("name", ""),
                            arguments=json.dumps(fn.get("arguments", {})),
                        )
        except asyncio.CancelledError:
            # Audit trail for H-002: when a job timeout cancels us mid-stream,
            # the enclosing ``async with`` will close the socket and abort the
            # billable upstream inference. Log it so we can correlate cost.
            # Also cancel the pending NDJSON read task explicitly so it does
            # not linger and produce "Task exception was never retrieved"
            # warnings as the socket closes underneath it.
            if pending_next is not None and not pending_next.done():
                pending_next.cancel()
            _log.warning(
                "Upstream stream cancelled mid-flight (model=%s) — closing socket",
                payload.get("model"),
            )
            raise
        except httpx.ConnectError:
            yield StreamError(error_code="provider_unavailable", message="Connection failed")
            return

        if not seen_done:
            yield StreamDone()

    @staticmethod
    def _build_chat_payload(request: CompletionRequest) -> dict:
        """Translate a CompletionRequest into Ollama's /api/chat JSON format."""
        messages = [_translate_message(m) for m in request.messages]
        payload: dict = {
            "model": request.model,
            "messages": messages,
            "stream": True,
        }
        # Only send think when the model actually supports it — models
        # without thinking capability reject the parameter with HTTP 400.
        if request.supports_reasoning:
            payload["think"] = request.reasoning_enabled
        if request.temperature is not None:
            payload["options"] = {"temperature": request.temperature}
        if request.tools:
            payload["tools"] = [
                {
                    "type": t.type,
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in request.tools
            ]
        return payload

    def _map_to_dto(self, model_name: str, detail: dict) -> ModelMetaDto:
        capabilities = detail.get("capabilities", [])
        model_info = detail.get("model_info", {})
        details = detail.get("details", {})

        context_window = 0
        for key, value in model_info.items():
            if key.endswith(".context_length") and isinstance(value, int):
                context_window = value
                break

        raw_params = None
        param_str = details.get("parameter_size")
        if param_str is not None:
            raw_params = _parse_parameter_size(param_str)
        if raw_params is None:
            raw_params = model_info.get("general.parameter_count")
            if raw_params is not None and not isinstance(raw_params, int):
                try:
                    raw_params = int(raw_params)
                except (ValueError, TypeError):
                    raw_params = None

        return ModelMetaDto(
            provider_id=self.provider_id,
            provider_display_name=self.provider_display_name,
            model_id=model_name,
            display_name=_build_display_name(model_name),
            context_window=context_window,
            supports_reasoning="thinking" in capabilities,
            supports_vision="vision" in capabilities,
            supports_tool_calls="tools" in capabilities,
            parameter_count=_format_parameter_count(raw_params),
            raw_parameter_count=raw_params,
            quantisation_level=details.get("quantization_level"),
        )

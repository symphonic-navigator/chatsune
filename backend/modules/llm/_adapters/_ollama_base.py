import asyncio
import json
import logging
from collections.abc import AsyncIterator
from uuid import uuid4

import httpx

from backend.modules.llm._adapters._base import BaseAdapter
from backend.modules.llm._adapters._events import (
    ContentDelta,
    ProviderStreamEvent,
    StreamDone,
    StreamError,
    ThinkingDelta,
    ToolCallEvent,
)
from shared.dtos.inference import CompletionMessage, CompletionRequest
from shared.dtos.llm import ModelMetaDto

_log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=15.0)

# H-004: if the upstream stalls mid-stream (no new NDJSON chunk arrives for this
# long), abort rather than wait on the enclosing job-level timeout. Module-level
# so tests can monkeypatch it to a short value.
GUTTER_TIMEOUT_SECONDS = 30.0


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
                while True:
                    try:
                        line = await asyncio.wait_for(
                            stream_iter.__anext__(),
                            timeout=GUTTER_TIMEOUT_SECONDS,
                        )
                    except asyncio.TimeoutError:
                        _log.warning(
                            "ollama_base.gutter_timeout model=%s aborting stream after %.1fs idle",
                            payload.get("model"), GUTTER_TIMEOUT_SECONDS,
                        )
                        if not seen_done:
                            # H-004: yielding on gutter timeout; no detail field on StreamDone
                            yield StreamDone()
                            seen_done = True
                        break
                    except StopAsyncIteration:
                        break

                    line = line.strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        _log.warning("Skipping malformed NDJSON line: %s", line)
                        continue

                    if chunk.get("done"):
                        seen_done = True
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

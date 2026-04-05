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

_TIMEOUT = 15.0


def _format_parameter_count(value: int | None) -> str | None:
    """Convert raw parameter count to human-readable form (e.g. 675B, 7.5B, 405M)."""
    if not value:
        return None
    if value >= 1_000_000_000_000:
        n = value / 1_000_000_000_000
        if n == int(n):
            return f"{int(n)}T"
        return f"{n:.1f}T"
    if value >= 1_000_000_000:
        n = value / 1_000_000_000
        if n == int(n):
            return f"{int(n)}B"
        return f"{n:.1f}B"
    if value >= 1_000_000:
        n = value / 1_000_000
        if n == int(n):
            return f"{int(n)}M"
        return f"{n:.1f}M"
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
        "content": " ".join(text_parts) if text_parts else "",
    }

    if images:
        result["images"] = images

    if msg.tool_calls:
        result["tool_calls"] = [
            {
                "function": {
                    "name": tc.name,
                    "arguments": json.loads(tc.arguments),
                },
            }
            for tc in msg.tool_calls
        ]

    # tool_call_id is dropped — Ollama uses positional matching

    return result


class OllamaCloudAdapter(BaseAdapter):
    """Ollama Cloud inference adapter."""

    requires_key_for_listing: bool = False

    async def validate_key(self, api_key: str) -> bool:
        """Validate key via POST /api/me. Returns True on 200, False on 401/403, raises otherwise."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{self.base_url}/api/me",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if resp.status_code == 200:
            return True
        if resp.status_code in (401, 403):
            return False
        resp.raise_for_status()

    async def fetch_models(self) -> list[ModelMetaDto]:
        """Fetch model list from /api/tags, then details from /api/show per model."""
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            tags_resp = await client.get(f"{self.base_url}/api/tags")
            tags_resp.raise_for_status()
            tag_entries = tags_resp.json().get("models", [])

            models: list[ModelMetaDto] = []
            for entry in tag_entries:
                name = entry["name"]
                try:
                    show_resp = await client.post(
                        f"{self.base_url}/api/show",
                        json={"model": name},
                    )
                    show_resp.raise_for_status()
                    detail = show_resp.json()
                except Exception:
                    _log.warning("Failed to fetch details for model '%s'; skipping.", name)
                    continue

                models.append(self._map_to_dto(name, detail))

        return models

    async def stream_completion(
        self,
        api_key: str,
        request: CompletionRequest,
    ) -> AsyncIterator[ProviderStreamEvent]:
        payload = self._build_chat_payload(request)

        try:
            client = httpx.AsyncClient(timeout=_TIMEOUT)
        except Exception:
            yield StreamError(error_code="provider_unavailable", message="Failed to create HTTP client")
            return

        seen_done = False
        try:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
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

                async for line in resp.aiter_lines():
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

                    # Thinking deltas
                    thinking = message.get("thinking", "")
                    if thinking:
                        yield ThinkingDelta(delta=thinking)

                    # Content deltas
                    content = message.get("content", "")
                    if content:
                        yield ContentDelta(delta=content)

                    # Tool calls
                    for tc in message.get("tool_calls", []):
                        fn = tc.get("function", {})
                        yield ToolCallEvent(
                            id=f"call_{uuid4().hex[:12]}",
                            name=fn.get("name", ""),
                            arguments=json.dumps(fn.get("arguments", {})),
                        )
        except httpx.ConnectError:
            yield StreamError(error_code="provider_unavailable", message="Connection failed")
            return
        finally:
            await client.aclose()

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

        # Extract context window from model_info (key ends with .context_length)
        context_window = 0
        for key, value in model_info.items():
            if key.endswith(".context_length") and isinstance(value, int):
                context_window = value
                break

        # Extract parameter count — prefer details.parameter_size, fall back to model_info
        raw_params = None
        param_str = details.get("parameter_size")
        if param_str is not None:
            try:
                raw_params = int(param_str)
            except (ValueError, TypeError):
                pass
        if raw_params is None:
            raw_params = model_info.get("general.parameter_count")

        return ModelMetaDto(
            provider_id="ollama_cloud",
            provider_display_name="Ollama Cloud",
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

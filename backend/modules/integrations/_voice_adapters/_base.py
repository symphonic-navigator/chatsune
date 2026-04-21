"""Voice provider adapter interface + error classes.

Adapters implement this interface for integrations that are proxied through
the Chatsune backend (hydrate_secrets=False). See
devdocs/superpowers/specs/2026-04-19-xai-voice-integration-design.md §5.1.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Literal

import httpx
from pydantic import BaseModel

# Response body excerpts are capped so that a stray HTML error page does not
# flood the logs. 500 characters is enough to identify the upstream problem
# (xAI / Mistral plaintext 5xx bodies sit comfortably under this) while
# keeping log volume predictable.
_BODY_EXCERPT_MAX_CHARS = 500


class VoiceInfo(BaseModel):
    id: str
    name: str
    language: str | None = None
    gender: Literal["male", "female", "neutral"] | None = None


class VoiceAdapterError(Exception):
    """Base error. Raised by adapters, mapped to HTTP by the proxy route."""
    http_status: int = 502
    user_message: str = "Voice provider error"

    def __init__(self, user_message: str | None = None) -> None:
        if user_message is not None:
            self.user_message = user_message
        super().__init__(self.user_message)


class VoiceAuthError(VoiceAdapterError):
    http_status = 401
    user_message = "Voice provider rejected your API key"


class VoiceRateLimitError(VoiceAdapterError):
    http_status = 429
    user_message = "Voice provider rate-limited — try again shortly"


class VoiceUnavailableError(VoiceAdapterError):
    http_status = 502
    user_message = "Voice provider unreachable"


class VoiceBadRequestError(VoiceAdapterError):
    http_status = 400
    user_message = "Voice provider rejected the request"


class VoiceAdapter(ABC):
    """Backend-proxied voice provider. One instance per provider type."""

    @abstractmethod
    async def transcribe(
        self,
        audio: bytes,
        content_type: str,
        api_key: str,
        language: str | None,
    ) -> str: ...

    @abstractmethod
    async def synthesise(
        self, text: str, voice_id: str, api_key: str,
    ) -> tuple[bytes, str]:
        """Returns (audio_bytes, content_type)."""

    @abstractmethod
    async def list_voices(self, api_key: str) -> list[VoiceInfo]: ...

    async def validate_credentials(self, api_key: str) -> None:
        """Default: list_voices round-trip as a liveness probe.

        Adapters may override with a cheaper endpoint if available.
        """
        await self.list_voices(api_key)

    async def clone_voice(
        self,
        audio: bytes,
        content_type: str,
        name: str,
        api_key: str,
    ) -> VoiceInfo:
        """Create a cloned voice from a user-supplied audio sample.

        Default: adapter doesn't support cloning. Override in subclasses
        that do. Handlers must capability-check before calling.
        """
        raise NotImplementedError("Voice cloning not supported by this adapter")

    async def delete_voice(self, voice_id: str, api_key: str) -> None:
        """Delete a previously cloned voice.

        Default: adapter doesn't support cloning. Override in subclasses.
        """
        raise NotImplementedError("Voice cloning not supported by this adapter")


def log_upstream_failure(
    logger: logging.Logger,
    adapter: str,
    operation: str,
    response: httpx.Response,
    request_context: dict[str, Any],
) -> None:
    """Emit a structured WARN log for a 5xx voice-upstream response.

    Shape mirrors the existing ``voice.transient_retry`` log in
    ``_handlers.py`` (key=value pairs, grep-friendly) so both log lines
    can be correlated in Grafana / Loki by ``integration_id`` /
    ``adapter`` + ``operation``.

    Only metadata is logged — never audio bytes or transcript text.
    Caller is responsible for only calling this on a 5xx response; there
    is no extra status check here.
    """
    headers = response.headers
    request_id = headers.get("x-request-id")
    retry_after = headers.get("retry-after")
    content_type = headers.get("content-type")

    # Response body may be non-text (audio/*, application/octet-stream) or
    # already consumed (streamed). Guard both cases and always emit *some*
    # excerpt value so log parsers see a stable field set.
    try:
        body_text = response.text
    except Exception:
        body_text = ""
    body_excerpt = (body_text or "")[:_BODY_EXCERPT_MAX_CHARS]

    # Serialise the request context as key=value pairs, in insertion order,
    # so the full log line stays grep-able without needing JSON parsing.
    ctx_fragment = " ".join(f"{k}={v!r}" for k, v in request_context.items())

    logger.warning(
        "voice.upstream_5xx adapter=%s operation=%s status=%d "
        "request_id=%r retry_after=%r content_type=%r "
        "body_excerpt=%r %s",
        adapter,
        operation,
        response.status_code,
        request_id,
        retry_after,
        content_type,
        body_excerpt,
        ctx_fragment,
    )

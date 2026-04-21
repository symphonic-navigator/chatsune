"""Voice provider adapter interface + error classes.

Adapters implement this interface for integrations that are proxied through
the Chatsune backend (hydrate_secrets=False). See
devdocs/superpowers/specs/2026-04-19-xai-voice-integration-design.md §5.1.
"""

from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel


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

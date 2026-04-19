"""Voice-adapter registry.

Backend-proxied voice integrations register their adapter instance here at
module import time. The voice proxy routes look adapters up by integration id.
"""

from backend.modules.integrations._voice_adapters._base import (
    VoiceAdapter,
    VoiceAdapterError,
    VoiceAuthError,
    VoiceBadRequestError,
    VoiceInfo,
    VoiceRateLimitError,
    VoiceUnavailableError,
)

_registry: dict[str, VoiceAdapter] = {}


def register_adapter(integration_id: str, adapter: VoiceAdapter) -> None:
    if integration_id in _registry:
        raise ValueError(f"Voice adapter '{integration_id}' already registered")
    _registry[integration_id] = adapter


def get_adapter(integration_id: str) -> VoiceAdapter | None:
    return _registry.get(integration_id)


__all__ = [
    "VoiceAdapter",
    "VoiceAdapterError",
    "VoiceAuthError",
    "VoiceBadRequestError",
    "VoiceInfo",
    "VoiceRateLimitError",
    "VoiceUnavailableError",
    "register_adapter",
    "get_adapter",
]

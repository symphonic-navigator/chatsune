"""Voice-adapter registry — register/get/duplicate."""
import pytest

from backend.modules.integrations._voice_adapters import (
    register_adapter,
    get_adapter,
    _registry,  # used only to reset state between tests
)
from backend.modules.integrations._voice_adapters._base import VoiceAdapter


class _DummyAdapter(VoiceAdapter):
    async def list_voices(self, api_key): return []
    async def transcribe(self, audio, content_type, api_key, language): return ""
    async def synthesise(self, text, voice_id, api_key): return b"", "audio/mpeg"


def _reset():
    _registry.clear()


def test_register_and_get():
    _reset()
    a = _DummyAdapter()
    register_adapter("x", a)
    assert get_adapter("x") is a


def test_unknown_returns_none():
    _reset()
    assert get_adapter("nope") is None


def test_duplicate_raises():
    _reset()
    register_adapter("x", _DummyAdapter())
    with pytest.raises(ValueError):
        register_adapter("x", _DummyAdapter())

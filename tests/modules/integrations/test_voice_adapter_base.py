"""VoiceAdapter base + error hierarchy."""
import pytest

from backend.modules.integrations._voice_adapters._base import (
    VoiceAdapter,
    VoiceAdapterError,
    VoiceAuthError,
    VoiceRateLimitError,
    VoiceUnavailableError,
    VoiceBadRequestError,
    VoiceInfo,
)


def test_error_hierarchy_and_defaults():
    assert issubclass(VoiceAuthError, VoiceAdapterError)
    assert issubclass(VoiceRateLimitError, VoiceAdapterError)
    assert issubclass(VoiceUnavailableError, VoiceAdapterError)
    assert issubclass(VoiceBadRequestError, VoiceAdapterError)

    assert VoiceAuthError().http_status == 401
    assert VoiceRateLimitError().http_status == 429
    assert VoiceUnavailableError().http_status == 502
    assert VoiceBadRequestError().http_status == 400


def test_voice_info_shape():
    v = VoiceInfo(id="abc", name="Voice A")
    assert v.id == "abc"
    assert v.name == "Voice A"
    assert v.language is None
    assert v.gender is None


def test_voice_adapter_is_abstract():
    with pytest.raises(TypeError):
        VoiceAdapter()

from backend.modules.integrations._registry import _registry  # noqa: F401 - force registration
from backend.modules.integrations import get_integration
from shared.dtos.integrations import IntegrationCapability


def test_xai_voice_advertises_expressive_markup_capability() -> None:
    defn = get_integration("xai_voice")
    assert defn is not None
    assert IntegrationCapability.TTS_EXPRESSIVE_MARKUP in defn.capabilities


def test_mistral_voice_does_not_advertise_expressive_markup() -> None:
    defn = get_integration("mistral_voice")
    assert defn is not None
    assert IntegrationCapability.TTS_EXPRESSIVE_MARKUP not in defn.capabilities

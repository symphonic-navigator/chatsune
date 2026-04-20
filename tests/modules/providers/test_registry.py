from shared.dtos.providers import Capability
from backend.modules.providers._registry import get, get_all
from backend.modules.providers._models import PremiumProviderDefinition


def test_xai_registered():
    defn = get("xai")
    assert isinstance(defn, PremiumProviderDefinition)
    assert defn.display_name == "xAI"
    assert set(defn.capabilities) == {
        Capability.LLM, Capability.TTS, Capability.STT,
        Capability.TTI, Capability.ITI,
    }
    assert defn.base_url == "https://api.x.ai"
    assert "xai_voice" in defn.linked_integrations


def test_mistral_registered_as_voice_only():
    defn = get("mistral")
    assert set(defn.capabilities) == {Capability.TTS, Capability.STT}
    assert "mistral_voice" in defn.linked_integrations


def test_ollama_cloud_registered():
    defn = get("ollama_cloud")
    assert set(defn.capabilities) == {Capability.LLM, Capability.WEBSEARCH}
    assert defn.base_url == "https://ollama.com"
    assert defn.linked_integrations == []


def test_get_all_returns_three_providers():
    assert set(get_all().keys()) == {"xai", "mistral", "ollama_cloud"}


def test_unknown_provider_returns_none():
    assert get("bogus") is None

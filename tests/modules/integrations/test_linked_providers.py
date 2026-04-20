"""Tests for IntegrationDefinition.linked_premium_provider field."""

from backend.modules.integrations._registry import get


def test_xai_voice_linked_to_xai():
    defn = get("xai_voice")
    assert defn is not None
    assert defn.linked_premium_provider == "xai"
    assert all(f["key"] != "api_key" for f in defn.config_fields)


def test_mistral_voice_linked_to_mistral():
    defn = get("mistral_voice")
    assert defn is not None
    assert defn.linked_premium_provider == "mistral"
    assert all(f["key"] != "api_key" for f in defn.config_fields)


def test_lovense_is_not_linked():
    defn = get("lovense")
    assert defn is not None
    assert defn.linked_premium_provider is None

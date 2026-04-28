"""Verifies the openrouter provider is registered with the right shape."""

from backend.modules.providers._registry import get
from shared.dtos.providers import Capability


def test_openrouter_provider_is_registered():
    defn = get("openrouter")
    assert defn is not None


def test_openrouter_capabilities_are_llm_only():
    defn = get("openrouter")
    assert defn.capabilities == [Capability.LLM]


def test_openrouter_probe_url_targets_user_endpoint():
    defn = get("openrouter")
    # /models/user (authenticated) — not /models (public) — so an
    # invalid key actually fails the probe.
    assert defn.probe_url == (
        "https://openrouter.ai/api/v1/models/user?output_modalities=text"
    )
    assert defn.probe_method == "GET"


def test_openrouter_base_url():
    defn = get("openrouter")
    assert defn.base_url == "https://openrouter.ai/api/v1"


def test_openrouter_has_api_key_field():
    defn = get("openrouter")
    keys = [f["key"] for f in defn.config_fields]
    assert keys == ["api_key"]


def test_openrouter_has_no_linked_integrations():
    defn = get("openrouter")
    assert defn.linked_integrations == []

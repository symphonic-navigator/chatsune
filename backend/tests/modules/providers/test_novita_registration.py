"""Verifies the novita provider is registered with the right shape."""

from backend.modules.providers._registry import get
from shared.dtos.providers import Capability


def test_novita_provider_is_registered():
    defn = get("novita")
    assert defn is not None


def test_novita_capabilities_are_llm_only():
    defn = get("novita")
    assert defn.capabilities == [Capability.LLM]


def test_novita_base_url_is_openai_compat_path():
    # Chat-completions and model listing live under /openai/v1.
    defn = get("novita")
    assert defn.base_url == "https://api.novita.ai/openai/v1"


def test_novita_probe_url_targets_billing_balance():
    # /openai/v1/models is unauthenticated and would falsely accept any
    # key; the billing endpoint requires auth so it is the only valid
    # probe target. See spec §"Endpoints".
    defn = get("novita")
    assert defn.probe_url == (
        "https://api.novita.ai/openapi/v1/billing/balance/detail"
    )
    assert defn.probe_method == "GET"


def test_novita_has_api_key_field():
    defn = get("novita")
    keys = [f["key"] for f in defn.config_fields]
    assert keys == ["api_key"]


def test_novita_has_no_linked_integrations():
    defn = get("novita")
    assert defn.linked_integrations == []


def test_novita_display_name_and_icon():
    defn = get("novita")
    assert defn.display_name == "Novita AI"
    assert defn.icon == "novita"

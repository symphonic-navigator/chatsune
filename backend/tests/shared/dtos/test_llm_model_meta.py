import pytest
from pydantic import ValidationError

from shared.dtos.llm import ModelMetaDto


def _base_kwargs() -> dict:
    return {
        "connection_id": "c1",
        "model_id": "m1",
        "display_name": "M 1",
        "context_window": 128000,
        "supports_reasoning": False,
        "supports_vision": False,
        "supports_tool_calls": False,
    }


def test_billing_category_defaults_to_none():
    dto = ModelMetaDto(**_base_kwargs())
    assert dto.billing_category is None


def test_billing_category_accepts_free():
    dto = ModelMetaDto(**_base_kwargs(), billing_category="free")
    assert dto.billing_category == "free"


def test_billing_category_accepts_subscription():
    dto = ModelMetaDto(**_base_kwargs(), billing_category="subscription")
    assert dto.billing_category == "subscription"


def test_billing_category_accepts_pay_per_token():
    dto = ModelMetaDto(**_base_kwargs(), billing_category="pay_per_token")
    assert dto.billing_category == "pay_per_token"


def test_billing_category_rejects_unknown_value():
    with pytest.raises(ValidationError):
        ModelMetaDto(**_base_kwargs(), billing_category="enterprise")

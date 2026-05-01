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


def test_remarks_defaults_to_none():
    dto = ModelMetaDto(**_base_kwargs())
    assert dto.remarks is None


def test_remarks_accepts_arbitrary_string():
    dto = ModelMetaDto(
        **_base_kwargs(),
        remarks="Falls back to Grok 4.20 (non-reasoning) when thinking is off.",
    )
    assert dto.remarks == (
        "Falls back to Grok 4.20 (non-reasoning) when thinking is off."
    )

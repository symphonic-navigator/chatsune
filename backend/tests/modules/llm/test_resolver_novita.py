"""Verifies the novita slug is wired into resolver and reserved-slug paths."""

from backend.modules.llm._connections import RESERVED_SLUGS
from backend.modules.llm._resolver import _PREMIUM_ADAPTER_TYPE


def test_novita_maps_to_novita_http_adapter():
    assert _PREMIUM_ADAPTER_TYPE["novita"] == "novita_http"


def test_novita_is_a_reserved_slug():
    # RESERVED_SLUGS gates two things: rejecting user-created Connections
    # whose slug would shadow the Premium Provider, and routing the
    # persona model_unique_id validator through the Premium Account
    # check rather than the Connection repository. Both must include
    # novita, otherwise saving a persona with a Novita model fails with
    # "Unknown or unowned connection 'novita'".
    assert "novita" in RESERVED_SLUGS

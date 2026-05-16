"""Verifies the chutes slug is wired into resolver, reserved-slug,
and persona-validation paths."""

from backend.modules.llm._connections import RESERVED_SLUGS
from backend.modules.llm._resolver import _PREMIUM_ADAPTER_TYPE


def test_chutes_maps_to_chutes_http_adapter():
    assert _PREMIUM_ADAPTER_TYPE["chutes"] == "chutes_http"


def test_chutes_is_a_reserved_slug():
    # RESERVED_SLUGS gates two things: rejecting user-created Connections
    # whose slug would shadow the Premium Provider, and routing the
    # persona model_unique_id validator through the Premium Account
    # check rather than the Connection repository. Both must include
    # chutes, otherwise saving a persona with a Chutes model fails
    # with "Unknown or unowned connection 'chutes'".
    assert "chutes" in RESERVED_SLUGS

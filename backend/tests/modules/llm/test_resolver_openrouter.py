"""Verifies the openrouter slug is wired into resolver, reserved-slug,
and persona-validation paths."""

from backend.modules.llm._connections import RESERVED_SLUGS
from backend.modules.llm._resolver import _PREMIUM_ADAPTER_TYPE


def test_openrouter_maps_to_openrouter_http_adapter():
    assert _PREMIUM_ADAPTER_TYPE["openrouter"] == "openrouter_http"


def test_openrouter_is_a_reserved_slug():
    # RESERVED_SLUGS gates two things: rejecting user-created Connections
    # whose slug would shadow the Premium Provider, and routing the
    # persona model_unique_id validator through the Premium Account
    # check rather than the Connection repository. Both must include
    # openrouter, otherwise saving a persona with an OpenRouter model
    # fails with "Unknown or unowned connection 'openrouter'".
    assert "openrouter" in RESERVED_SLUGS

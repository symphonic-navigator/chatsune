"""Tests for the xAI imagine image-group slug map."""

from backend.modules.llm._adapters._xai_image_groups import (
    GROUP_ID,
    aspect_to_payload,
    model_id_for_tier,
    resolution_to_payload,
)


def test_group_id_is_xai_imagine():
    assert GROUP_ID == "xai_imagine"


def test_model_id_for_tier_quality_returns_quality_slug():
    assert model_id_for_tier("quality") == "grok-imagine-image-quality"


def test_model_id_for_tier_normal_returns_base_slug():
    assert model_id_for_tier("normal") == "grok-imagine-image"


def test_model_id_for_tier_unknown_falls_back_to_base():
    assert model_id_for_tier("something-else") == "grok-imagine-image"


def test_aspect_passthrough():
    assert aspect_to_payload("16:9") == "16:9"


def test_resolution_passthrough():
    assert resolution_to_payload("2k") == "2k"

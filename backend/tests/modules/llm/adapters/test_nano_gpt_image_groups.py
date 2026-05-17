"""Tests for the nano-gpt image groups helper module."""

import pytest

from backend.modules.llm._adapters._nano_gpt_image_groups import (
    SEEDREAM_GROUP_ID,
    SEEDREAM_RESOLUTIONS,
    ZIMAGE_GROUP_ID,
    seedream_payload,
    seedream_resolution,
    zimage_payload,
)
from shared.dtos.images import SeedreamConfig, ZImageConfig


def test_group_id_constants():
    assert ZIMAGE_GROUP_ID == "nano_gpt_zimage"
    assert SEEDREAM_GROUP_ID == "nano_gpt_seedream"


def test_zimage_payload_turbo_1024():
    body = zimage_payload(
        ZImageConfig(model="turbo", size="1024x1024", n=2),
        prompt="a serene landscape",
    )
    assert body == {
        "model": "z-image-turbo",
        "prompt": "a serene landscape",
        "n": 2,
        "size": "1024x1024",
        "response_format": "url",
    }


def test_zimage_payload_base_1536():
    body = zimage_payload(
        ZImageConfig(model="base", size="1536x1536", n=1),
        prompt="x",
    )
    assert body["model"] == "z-image-base"
    assert body["size"] == "1536x1536"


def test_seedream_payload_aspect_to_size():
    body = seedream_payload(
        SeedreamConfig(aspect="16:9", quality="standard", n=1),
        prompt="x",
    )
    assert body["model"] == "seedream-v4.5"
    assert body["size"] == "2560x1440"
    assert body["prompt"] == "x"
    assert body["n"] == 1
    assert body["response_format"] == "url"


def test_seedream_resolution_table_covers_all_cells():
    """Every aspect × quality cell must be present and satisfy constraints."""
    aspects = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"]
    qualities = ["standard", "high", "ultra"]
    assert len(SEEDREAM_RESOLUTIONS) == len(aspects) * len(qualities)
    for aspect in aspects:
        for quality in qualities:
            w, h = seedream_resolution(aspect, quality)
            # Nano-gpt's documented minimum.
            assert w * h >= 3_686_400, f"{aspect}/{quality} = {w}x{h} below min"
            # Diffusion models prefer multiples of 32.
            assert w % 32 == 0, f"{aspect}/{quality}: width {w} not /32"
            assert h % 32 == 0, f"{aspect}/{quality}: height {h} not /32"
            # Aspect roughly preserved (±5 %).
            expected_w, expected_h = aspect.split(":")
            ideal_ratio = int(expected_w) / int(expected_h)
            actual_ratio = w / h
            assert abs(actual_ratio - ideal_ratio) / ideal_ratio < 0.05, \
                f"{aspect}/{quality}: ratio {actual_ratio:.3f} vs ideal {ideal_ratio:.3f}"


def test_seedream_resolution_unknown_aspect_raises():
    with pytest.raises(KeyError):
        seedream_resolution("21:9", "standard")

"""Tests for LlmService image-generation methods.

The validate_image_config tests bypass __init__ via LlmService.__new__ so
they can run without a live database connection.
"""

import pytest

from backend.modules.llm import LlmService
from shared.dtos.images import XaiImagineConfig


@pytest.mark.asyncio
async def test_validate_image_config_accepts_valid_xai():
    """Pure validation — no state needed; bypass __init__."""
    svc = LlmService.__new__(LlmService)
    cfg = await svc.validate_image_config(
        group_id="xai_imagine",
        config={"tier": "pro", "resolution": "2k", "aspect": "16:9", "n": 6},
    )
    assert isinstance(cfg, XaiImagineConfig)
    assert cfg.tier == "pro"
    assert cfg.resolution == "2k"
    assert cfg.aspect == "16:9"
    assert cfg.n == 6


@pytest.mark.asyncio
async def test_validate_image_config_rejects_bad_tier():
    """Invalid tier literal must raise ValueError."""
    svc = LlmService.__new__(LlmService)
    with pytest.raises(ValueError):
        await svc.validate_image_config(
            group_id="xai_imagine",
            config={"tier": "fancy"},
        )


@pytest.mark.asyncio
async def test_validate_image_config_rejects_unknown_group():
    """Unknown group_id must raise ValueError (no discriminator match)."""
    svc = LlmService.__new__(LlmService)
    with pytest.raises(ValueError):
        await svc.validate_image_config(
            group_id="nonexistent_group",
            config={"tier": "normal"},
        )


@pytest.mark.asyncio
async def test_validate_image_config_n_out_of_range():
    """n must be between 1 and 10 inclusive."""
    svc = LlmService.__new__(LlmService)
    with pytest.raises(ValueError):
        await svc.validate_image_config(
            group_id="xai_imagine",
            config={"n": 99},
        )

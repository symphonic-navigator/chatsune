import pytest
from pydantic import TypeAdapter, ValidationError

from shared.dtos.images import (
    GeneratedImageResult,
    ImageGenItem,
    ImageGroupConfig,
    ImageRefDto,
    ModeratedRejection,
    SeedreamConfig,
    XaiImagineConfig,
    ZImageConfig,
)


def test_xai_imagine_config_defaults():
    cfg = XaiImagineConfig()
    assert cfg.group_id == "xai_imagine"
    assert cfg.tier == "normal"
    assert cfg.resolution == "1k"
    assert cfg.aspect == "1:1"
    assert cfg.n == 4


def test_xai_imagine_config_validation_n_range():
    XaiImagineConfig(n=1)
    XaiImagineConfig(n=10)
    with pytest.raises(ValidationError):
        XaiImagineConfig(n=0)
    with pytest.raises(ValidationError):
        XaiImagineConfig(n=11)


def test_image_group_config_discriminated_union_parses_xai():
    adapter = TypeAdapter(ImageGroupConfig)
    parsed = adapter.validate_python({
        "group_id": "xai_imagine",
        "tier": "quality",
        "resolution": "2k",
        "aspect": "16:9",
        "n": 2,
    })
    assert isinstance(parsed, XaiImagineConfig)
    assert parsed.tier == "quality"


def test_image_group_config_discriminated_union_rejects_unknown():
    adapter = TypeAdapter(ImageGroupConfig)
    with pytest.raises(ValidationError):
        adapter.validate_python({"group_id": "unknown_group", "n": 1})


def test_image_gen_item_discriminated_union():
    adapter = TypeAdapter(ImageGenItem)
    img = adapter.validate_python({
        "kind": "image",
        "id": "img_a",
        "width": 1024,
        "height": 1024,
        "model_id": "grok-imagine",
    })
    assert isinstance(img, GeneratedImageResult)

    moderated = adapter.validate_python({"kind": "moderated"})
    assert isinstance(moderated, ModeratedRejection)
    assert moderated.reason is None


def test_image_ref_dto_required_fields():
    ref = ImageRefDto(
        id="img_a",
        blob_url="/api/images/img_a/blob",
        thumb_url="/api/images/img_a/thumb",
        width=1024,
        height=1024,
        prompt="a cat",
        model_id="grok-imagine",
        tool_call_id="tc_a",
    )
    assert ref.id == "img_a"


def test_xai_imagine_config_accepts_quality_tier():
    cfg = XaiImagineConfig(tier="quality")
    assert cfg.tier == "quality"


def test_xai_imagine_config_pro_tier_alias_to_quality():
    """Backwards-compat: legacy 'pro' input deserialises as 'quality'."""
    cfg = XaiImagineConfig(tier="pro")
    assert cfg.tier == "quality"


def test_xai_imagine_config_rejects_unknown_tier():
    with pytest.raises(ValidationError):
        XaiImagineConfig(tier="ultra")


def test_generated_image_result_data_fields_default_none():
    """The in-process handoff fields default to None."""
    r = GeneratedImageResult(id="img_a", width=64, height=32, model_id="m")
    assert r.data is None
    assert r.content_type is None


def test_generated_image_result_excludes_data_from_dump():
    """Bytes never leak through Pydantic serialisation."""
    r = GeneratedImageResult(
        id="img_a", width=64, height=32, model_id="m",
        data=b"raw_bytes", content_type="image/jpeg",
    )
    dumped = r.model_dump()
    assert "data" not in dumped
    assert "content_type" not in dumped
    # Sanity: the existing visible fields are still present.
    assert dumped["id"] == "img_a"
    assert dumped["model_id"] == "m"


# ---------------------------------------------------------------------------
# ZImageConfig
# ---------------------------------------------------------------------------

def test_zimage_config_defaults():
    cfg = ZImageConfig()
    assert cfg.group_id == "nano_gpt_zimage"
    assert cfg.model == "turbo"
    assert cfg.size == "1024x1024"
    assert cfg.n == 4


def test_zimage_config_size_must_be_known_literal():
    with pytest.raises(ValidationError):
        ZImageConfig(size="999x999")


def test_zimage_config_caps_n_for_base_model():
    """Z-Image-Base is 10x slower; the validator caps n at 4 for Base."""
    cfg = ZImageConfig(model="base", n=10)
    assert cfg.n == 4
    # Turbo keeps its n=10 cap.
    cfg = ZImageConfig(model="turbo", n=10)
    assert cfg.n == 10


# ---------------------------------------------------------------------------
# SeedreamConfig
# ---------------------------------------------------------------------------

def test_seedream_config_defaults():
    cfg = SeedreamConfig()
    assert cfg.group_id == "nano_gpt_seedream"
    assert cfg.aspect == "1:1"
    assert cfg.quality == "standard"
    assert cfg.n == 1


def test_seedream_config_n_capped_at_4():
    with pytest.raises(ValidationError):
        SeedreamConfig(n=5)


# ---------------------------------------------------------------------------
# ImageGroupConfig union routing
# ---------------------------------------------------------------------------

def test_image_group_config_union_routes_to_zimage():
    adapter = TypeAdapter(ImageGroupConfig)
    parsed = adapter.validate_python({
        "group_id": "nano_gpt_zimage",
        "model": "base",
        "size": "1536x1536",
        "n": 2,
    })
    assert isinstance(parsed, ZImageConfig)
    assert parsed.size == "1536x1536"


def test_image_group_config_union_routes_to_seedream():
    adapter = TypeAdapter(ImageGroupConfig)
    parsed = adapter.validate_python({
        "group_id": "nano_gpt_seedream",
        "aspect": "16:9",
        "quality": "high",
        "n": 2,
    })
    assert isinstance(parsed, SeedreamConfig)
    assert parsed.aspect == "16:9"

import pytest
from pydantic import TypeAdapter, ValidationError

from shared.dtos.images import (
    GeneratedImageResult,
    ImageGenItem,
    ImageGroupConfig,
    ImageRefDto,
    ModeratedRejection,
    XaiImagineConfig,
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
        "tier": "pro",
        "resolution": "2k",
        "aspect": "16:9",
        "n": 2,
    })
    assert isinstance(parsed, XaiImagineConfig)
    assert parsed.tier == "pro"


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

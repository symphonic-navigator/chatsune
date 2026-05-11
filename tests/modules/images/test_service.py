"""Unit tests for ImageService.

All dependencies are mocked — no database, filesystem, or network required.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import UTC, datetime

from backend.modules.images._service import ImageGenerationOutcome, ImageService
from backend.modules.images._models import UserImageConfigDocument
from shared.dtos.images import (
    GeneratedImageResult,
    ModeratedRejection,
    XaiImagineConfig,
)


def _active_cfg() -> UserImageConfigDocument:
    return UserImageConfigDocument(
        id="u1:conn_a:xai_imagine",
        user_id="u1",
        connection_id="conn_a",
        group_id="xai_imagine",
        config={"tier": "normal", "n": 2},
        selected=True,
        updated_at=datetime.now(UTC),
    )


def _make_service():
    llm = MagicMock()
    llm.validate_image_config = AsyncMock()
    llm.generate_images = AsyncMock()
    llm.list_image_groups = AsyncMock(return_value=[])

    blob = MagicMock()
    blob.save = MagicMock(return_value="ok")
    blob.delete = MagicMock(return_value=None)
    blob.load = MagicMock(return_value=b"\xff\xd8raw")

    gen = MagicMock()
    gen.insert_many = AsyncMock()
    gen.find_for_user = AsyncMock()
    gen.list_for_user = AsyncMock(return_value=[])
    gen.delete_for_user = AsyncMock(return_value=True)
    gen.delete_all_for_user = AsyncMock(return_value=0)

    cfg = MagicMock()
    cfg.get_active = AsyncMock()
    cfg.upsert = AsyncMock()
    cfg.set_active = AsyncMock()
    cfg.delete_all_for_user = AsyncMock(return_value=0)

    svc = ImageService(llm_service=llm, blob_store=blob, gen_repo=gen, cfg_repo=cfg)
    return svc, llm, blob, gen, cfg


# --- generate_for_chat ---------------------------------------------------

@pytest.mark.asyncio
async def test_generate_for_chat_no_active_config_raises():
    svc, _, _, _, cfg = _make_service()
    cfg.get_active.return_value = None
    with pytest.raises(LookupError, match="no active image configuration"):
        await svc.generate_for_chat(user_id="u1", prompt="x", tool_call_id="tc1")


@pytest.mark.asyncio
async def test_generate_for_chat_partial_moderation_outcome(monkeypatch):
    svc, llm, _, _, cfg = _make_service()
    cfg.get_active.return_value = _active_cfg()
    llm.validate_image_config.return_value = XaiImagineConfig(n=2)
    success = GeneratedImageResult(id="img_a", width=1024, height=1024, model_id="grok-imagine-image")
    moderated = ModeratedRejection(reason=None)
    llm.generate_images.return_value = [success, moderated]

    monkeypatch.setattr(
        "backend.modules.images._service.drain_image_buffer",
        lambda iid: (b"raw_bytes", "image/jpeg") if iid == "img_a" else None,
    )
    monkeypatch.setattr(
        "backend.modules.images._service.generate_thumbnail_jpeg",
        lambda b, max_edge=256: b"thumb_bytes",
    )

    outcome = await svc.generate_for_chat(user_id="u1", prompt="prompt-text", tool_call_id="tc1")

    assert isinstance(outcome, ImageGenerationOutcome)
    assert len(outcome.image_refs) == 1
    assert outcome.image_refs[0].id == "img_a"
    assert outcome.image_refs[0].tool_call_id == "tc1"
    assert outcome.moderated_count == 1
    assert outcome.successful_count == 1
    assert outcome.all_moderated is False
    assert "img_a" in outcome.llm_text_result
    assert "1 were filtered" in outcome.llm_text_result.lower() or "1 image was filtered" in outcome.llm_text_result.lower()


@pytest.mark.asyncio
async def test_generate_for_chat_all_moderated_sets_flag(monkeypatch):
    svc, llm, _, _, cfg = _make_service()
    cfg.get_active.return_value = _active_cfg()
    llm.validate_image_config.return_value = XaiImagineConfig(n=2)
    llm.generate_images.return_value = [ModeratedRejection(), ModeratedRejection()]
    monkeypatch.setattr(
        "backend.modules.images._service.drain_image_buffer",
        lambda iid: None,
    )
    outcome = await svc.generate_for_chat(user_id="u1", prompt="x", tool_call_id="tc1")
    assert outcome.successful_count == 0
    assert outcome.moderated_count == 2
    assert outcome.all_moderated is True
    assert "all" in outcome.llm_text_result.lower()


# --- set_active_config ---------------------------------------------------

@pytest.mark.asyncio
async def test_set_active_config_validates_then_persists():
    svc, llm, _, _, cfg = _make_service()
    llm.validate_image_config.return_value = XaiImagineConfig()
    out = await svc.set_active_config(
        user_id="u1",
        connection_id="conn_a",
        group_id="xai_imagine",
        config={"tier": "quality", "n": 4},
    )
    llm.validate_image_config.assert_awaited_once()
    cfg.upsert.assert_awaited_once()
    cfg.set_active.assert_awaited_once()
    assert out.connection_id == "conn_a"
    assert out.group_id == "xai_imagine"


@pytest.mark.asyncio
async def test_set_active_config_normalises_legacy_pro_to_quality():
    """Setting a legacy ``tier='pro'`` config must persist and return ``tier='quality'``.

    Without this, the FE could keep round-tripping the deprecated tier
    indefinitely: validator runs but the validated output is thrown away
    and the raw input is persisted unchanged.
    """
    svc, llm, _, _, cfg = _make_service()
    # Real validator behaviour: "pro" gets aliased to "quality".
    llm.validate_image_config.return_value = XaiImagineConfig(tier="pro", n=4)

    out = await svc.set_active_config(
        user_id="u1",
        connection_id="conn_a",
        group_id="xai_imagine",
        config={"tier": "pro", "n": 4},
    )

    # DTO returned to the caller must carry the normalised value.
    assert out.config["tier"] == "quality"

    # And the value persisted to the repository must also be normalised —
    # otherwise the MongoDB document stays "dirty" forever.
    cfg.upsert.assert_awaited_once()
    persisted_config = cfg.upsert.await_args.kwargs["config"]
    assert persisted_config["tier"] == "quality"


# --- get_active_config ---------------------------------------------------

@pytest.mark.asyncio
async def test_get_active_config_returns_none_when_no_active():
    svc, _, _, _, cfg = _make_service()
    cfg.get_active.return_value = None
    assert await svc.get_active_config(user_id="u1") is None


@pytest.mark.asyncio
async def test_get_active_config_aliases_legacy_pro_to_quality():
    """A persisted ``tier='pro'`` document must surface as ``tier='quality'``.

    The FE TIERS array is ``['normal', 'quality']``; without aliasing the
    SegRow would show no selected button for legacy docs.
    """
    svc, llm, _, _, cfg = _make_service()
    cfg.get_active.return_value = UserImageConfigDocument(
        id="u1:conn_a:xai_imagine",
        user_id="u1",
        connection_id="conn_a",
        group_id="xai_imagine",
        config={"tier": "pro", "n": 4},
        selected=True,
        updated_at=datetime.now(UTC),
    )
    llm.validate_image_config.return_value = XaiImagineConfig(tier="pro", n=4)

    out = await svc.get_active_config(user_id="u1")

    assert out is not None
    assert out.connection_id == "conn_a"
    assert out.group_id == "xai_imagine"
    assert out.config["tier"] == "quality"


@pytest.mark.asyncio
async def test_get_active_config_passes_through_already_quality():
    """An already-normalised ``tier='quality'`` doc round-trips unchanged."""
    svc, llm, _, _, cfg = _make_service()
    cfg.get_active.return_value = UserImageConfigDocument(
        id="u1:conn_a:xai_imagine",
        user_id="u1",
        connection_id="conn_a",
        group_id="xai_imagine",
        config={"tier": "quality", "n": 2},
        selected=True,
        updated_at=datetime.now(UTC),
    )
    llm.validate_image_config.return_value = XaiImagineConfig(tier="quality", n=2)

    out = await svc.get_active_config(user_id="u1")

    assert out is not None
    assert out.config["tier"] == "quality"
    assert out.config["n"] == 2


# --- get_image -----------------------------------------------------------

@pytest.mark.asyncio
async def test_get_image_returns_none_for_moderated_stub():
    from backend.modules.images._models import GeneratedImageDocument
    svc, _, _, gen, _ = _make_service()
    gen.find_for_user.return_value = GeneratedImageDocument(
        id="img_a",
        user_id="u1",
        prompt="x",
        model_id="(moderated)",
        group_id="xai_imagine",
        connection_id="c",
        config_snapshot={},
        moderated=True,
        generated_at=datetime.now(UTC),
    )
    result = await svc.get_image(user_id="u1", image_id="img_a")
    assert result is None


# --- delete_image --------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_image_removes_blobs_and_doc():
    from backend.modules.images._models import GeneratedImageDocument
    svc, _, blob, gen, _ = _make_service()
    gen.find_for_user.return_value = GeneratedImageDocument(
        id="img_a",
        user_id="u1",
        blob_id="blob-uuid-1",
        thumb_blob_id="blob-uuid-2",
        prompt="x",
        model_id="grok-imagine-image",
        group_id="xai_imagine",
        connection_id="c",
        config_snapshot={},
        width=1024,
        height=1024,
        content_type="image/jpeg",
        generated_at=datetime.now(UTC),
    )
    deleted = await svc.delete_image(user_id="u1", image_id="img_a")
    assert deleted is True
    assert blob.delete.call_count == 2

"""Verify the chat attachment resolver accepts generated_images.id as a
valid attachment_id and falls back to ImageService when storage lookup fails."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import UTC, datetime

from shared.dtos.images import GeneratedImageDetailDto
from backend.modules.chat._handlers_ws import _resolve_attachment_ids


def _make_detail(image_id: str = "img_a") -> GeneratedImageDetailDto:
    return GeneratedImageDetailDto(
        id=image_id,
        thumb_url=f"/api/images/{image_id}/thumb",
        blob_url=f"/api/images/{image_id}/blob",
        width=1024,
        height=1024,
        prompt="a dragon in the rain",
        model_id="grok-imagine-image",
        generated_at=datetime.now(UTC),
        config_snapshot={},
        connection_id="conn_a",
        group_id="xai_imagine",
    )


def _make_storage_file(file_id: str = "file_1") -> dict:
    return {
        "_id": file_id,
        "display_name": "document.pdf",
        "media_type": "application/pdf",
        "size_bytes": 12345,
        "thumbnail_b64": None,
        "text_preview": None,
        "data": b"",
        "user_id": "user_1",
    }


@pytest.mark.asyncio
async def test_resolver_falls_back_to_image_service_when_storage_misses():
    """Storage returns nothing; image service returns a detail → ref is built."""
    detail = _make_detail("img_a")

    fake_image_service = MagicMock()
    fake_image_service.get_image = AsyncMock(return_value=detail)

    with (
        patch("backend.modules.storage.get_files_by_ids", AsyncMock(return_value=[])),
        patch("backend.modules.images.get_image_service", return_value=fake_image_service),
    ):
        refs = await _resolve_attachment_ids(["img_a"], user_id="user_1")

    assert len(refs) == 1
    ref = refs[0]
    assert ref["file_id"] == "img_a"
    assert ref["media_type"] == "image/jpeg"
    assert ref["size_bytes"] == 0
    assert ref["display_name"] == "a dragon in the rain"
    assert ref["thumbnail_b64"] is None
    assert ref["text_preview"] is None


@pytest.mark.asyncio
async def test_resolver_returns_empty_for_truly_unknown_id():
    """Both storage and image service return nothing → resolver returns empty list."""
    fake_image_service = MagicMock()
    fake_image_service.get_image = AsyncMock(return_value=None)

    with (
        patch("backend.modules.storage.get_files_by_ids", AsyncMock(return_value=[])),
        patch("backend.modules.images.get_image_service", return_value=fake_image_service),
    ):
        refs = await _resolve_attachment_ids(["unknown_id"], user_id="user_1")

    assert refs == []


@pytest.mark.asyncio
async def test_resolver_silent_when_image_service_not_initialised():
    """If get_image_service() raises RuntimeError the resolver returns empty list silently."""
    with (
        patch("backend.modules.storage.get_files_by_ids", AsyncMock(return_value=[])),
        patch(
            "backend.modules.images.get_image_service",
            side_effect=RuntimeError("ImageService not initialised"),
        ),
    ):
        refs = await _resolve_attachment_ids(["img_x"], user_id="user_1")

    # Must not raise; must return an empty list.
    assert refs == []


@pytest.mark.asyncio
async def test_resolver_storage_hit_takes_priority():
    """An ID found in storage is returned directly; image service is never consulted."""
    storage_file = _make_storage_file("file_1")
    fake_image_service = MagicMock()
    fake_image_service.get_image = AsyncMock(return_value=_make_detail("file_1"))

    with (
        patch("backend.modules.storage.get_files_by_ids", AsyncMock(return_value=[storage_file])),
        patch("backend.modules.images.get_image_service", return_value=fake_image_service),
    ):
        refs = await _resolve_attachment_ids(["file_1"], user_id="user_1")

    assert len(refs) == 1
    assert refs[0]["file_id"] == "file_1"
    assert refs[0]["media_type"] == "application/pdf"
    # Image service must NOT have been consulted for an ID already in storage.
    fake_image_service.get_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolver_mixed_ids():
    """Storage returns one file; the other ID falls back to image service."""
    storage_file = _make_storage_file("file_1")
    detail = _make_detail("img_b")
    fake_image_service = MagicMock()
    fake_image_service.get_image = AsyncMock(return_value=detail)

    with (
        patch(
            "backend.modules.storage.get_files_by_ids",
            AsyncMock(return_value=[storage_file]),
        ),
        patch("backend.modules.images.get_image_service", return_value=fake_image_service),
    ):
        refs = await _resolve_attachment_ids(["file_1", "img_b"], user_id="user_1")

    assert len(refs) == 2
    file_ids = {r["file_id"] for r in refs}
    assert "file_1" in file_ids
    assert "img_b" in file_ids

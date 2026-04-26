"""Tests for /api/images/* HTTP routes."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.modules.images._http import router, _service
from backend.modules.images._service import ImageService
from backend.dependencies import require_active_session
from shared.dtos.images import (
    ActiveImageConfigDto,
    ConnectionImageGroupsDto,
    GeneratedImageDetailDto,
    GeneratedImageSummaryDto,
)


def _build_app(svc: ImageService, user_id: str = "u1") -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    # Stub out session auth: return a minimal user dict matching the real shape
    app.dependency_overrides[require_active_session] = lambda: {"sub": user_id, "role": "user"}
    # Stub out the service resolver
    app.dependency_overrides[_service] = lambda: svc
    return app


def _make_summary() -> GeneratedImageSummaryDto:
    return GeneratedImageSummaryDto(
        id="img_a",
        thumb_url="/api/images/img_a/thumb",
        width=1024,
        height=1024,
        prompt="x",
        model_id="grok-imagine-image",
        generated_at=datetime.now(UTC),
    )


def _make_detail() -> GeneratedImageDetailDto:
    return GeneratedImageDetailDto(
        id="img_a",
        thumb_url="/api/images/img_a/thumb",
        blob_url="/api/images/img_a/blob",
        width=1024,
        height=1024,
        prompt="x",
        model_id="grok-imagine-image",
        generated_at=datetime.now(UTC),
        config_snapshot={"tier": "normal"},
        connection_id="conn_a",
        group_id="xai_imagine",
    )


def test_list_images_returns_user_images():
    svc = MagicMock(spec=ImageService)
    svc.list_user_images = AsyncMock(return_value=[_make_summary()])
    client = TestClient(_build_app(svc))
    r = client.get("/api/images")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_list_images_passes_pagination_params():
    svc = MagicMock(spec=ImageService)
    svc.list_user_images = AsyncMock(return_value=[])
    client = TestClient(_build_app(svc))
    r = client.get("/api/images?limit=20")
    assert r.status_code == 200
    svc.list_user_images.assert_awaited_once()
    kw = svc.list_user_images.await_args.kwargs
    assert kw["limit"] == 20


def test_get_image_returns_detail():
    svc = MagicMock(spec=ImageService)
    svc.get_image = AsyncMock(return_value=_make_detail())
    client = TestClient(_build_app(svc))
    r = client.get("/api/images/img_a")
    assert r.status_code == 200
    assert r.json()["id"] == "img_a"


def test_get_image_404_when_missing():
    svc = MagicMock(spec=ImageService)
    svc.get_image = AsyncMock(return_value=None)
    client = TestClient(_build_app(svc))
    r = client.get("/api/images/img_x")
    assert r.status_code == 404


def test_get_blob_streams_bytes():
    svc = MagicMock(spec=ImageService)
    svc.stream_blob = AsyncMock(return_value=(b"\xff\xd8raw", "image/jpeg"))
    client = TestClient(_build_app(svc))
    r = client.get("/api/images/img_a/blob")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content == b"\xff\xd8raw"


def test_get_blob_404_when_missing():
    svc = MagicMock(spec=ImageService)
    svc.stream_blob = AsyncMock(return_value=None)
    client = TestClient(_build_app(svc))
    r = client.get("/api/images/img_x/blob")
    assert r.status_code == 404


def test_get_thumb_streams_jpeg():
    svc = MagicMock(spec=ImageService)
    svc.stream_blob = AsyncMock(return_value=(b"\xff\xd8thumb", "image/jpeg"))
    client = TestClient(_build_app(svc))
    r = client.get("/api/images/img_a/thumb")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content == b"\xff\xd8thumb"


def test_get_thumb_404_when_missing():
    svc = MagicMock(spec=ImageService)
    svc.stream_blob = AsyncMock(return_value=None)
    client = TestClient(_build_app(svc))
    r = client.get("/api/images/img_x/thumb")
    assert r.status_code == 404


def test_delete_image_204_on_success():
    svc = MagicMock(spec=ImageService)
    svc.delete_image = AsyncMock(return_value=True)
    client = TestClient(_build_app(svc))
    r = client.delete("/api/images/img_a")
    assert r.status_code == 204


def test_delete_image_404_when_missing():
    svc = MagicMock(spec=ImageService)
    svc.delete_image = AsyncMock(return_value=False)
    client = TestClient(_build_app(svc))
    r = client.delete("/api/images/img_x")
    assert r.status_code == 404


def test_get_config_returns_available_and_active():
    svc = MagicMock(spec=ImageService)
    svc.list_available_groups = AsyncMock(return_value=[
        ConnectionImageGroupsDto(
            connection_id="conn_a",
            connection_display_name="My xAI",
            group_ids=["xai_imagine"],
        )
    ])
    svc.get_active_config = AsyncMock(return_value=None)
    client = TestClient(_build_app(svc))
    r = client.get("/api/images/config")
    assert r.status_code == 200
    body = r.json()
    assert len(body["available"]) == 1
    assert body["active"] is None


def test_get_config_returns_active_when_set():
    svc = MagicMock(spec=ImageService)
    svc.list_available_groups = AsyncMock(return_value=[])
    svc.get_active_config = AsyncMock(return_value=ActiveImageConfigDto(
        connection_id="conn_a", group_id="xai_imagine", config={"tier": "pro"},
    ))
    client = TestClient(_build_app(svc))
    r = client.get("/api/images/config")
    assert r.status_code == 200
    body = r.json()
    assert body["active"]["connection_id"] == "conn_a"


def test_set_config_422_on_validation_error():
    svc = MagicMock(spec=ImageService)
    svc.set_active_config = AsyncMock(side_effect=ValueError("bad group"))
    client = TestClient(_build_app(svc))
    r = client.post("/api/images/config", json={
        "connection_id": "conn_a",
        "group_id": "xai_imagine",
        "config": {"tier": "fancy"},
    })
    assert r.status_code == 422


def test_set_config_200_on_success():
    svc = MagicMock(spec=ImageService)
    svc.set_active_config = AsyncMock(return_value=ActiveImageConfigDto(
        connection_id="conn_a", group_id="xai_imagine", config={"tier": "pro"},
    ))
    client = TestClient(_build_app(svc))
    r = client.post("/api/images/config", json={
        "connection_id": "conn_a",
        "group_id": "xai_imagine",
        "config": {"tier": "pro"},
    })
    assert r.status_code == 200
    assert r.json()["connection_id"] == "conn_a"

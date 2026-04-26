"""HTTP routes for the images module.

All routes require an authenticated user. Image bytes and thumbnails
are session-authenticated (no signed URLs in Phase I).
"""

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from backend.dependencies import require_active_session
from backend.modules.images._service import ImageService
from shared.dtos.images import (
    ActiveImageConfigDto,
    ConnectionImageGroupsDto,
    GeneratedImageDetailDto,
    GeneratedImageSummaryDto,
)

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/images", tags=["images"])


class _SetActiveConfigRequest(BaseModel):
    connection_id: str
    group_id: str
    config: dict


class _ImageConfigDiscoveryDto(BaseModel):
    available: list[ConnectionImageGroupsDto]
    active: ActiveImageConfigDto | None


def _service() -> ImageService:
    """Resolver for the ImageService singleton (wired in main.py)."""
    from backend.modules.images import get_image_service
    return get_image_service()


@router.get("", response_model=list[GeneratedImageSummaryDto])
async def list_images(
    user: Annotated[dict, Depends(require_active_session)],
    limit: int = Query(50, ge=1, le=200),
    before: datetime | None = None,
    svc: ImageService = Depends(_service),
):
    return await svc.list_user_images(user_id=user["sub"], limit=limit, before=before)


@router.get("/config", response_model=_ImageConfigDiscoveryDto)
async def get_config(
    user: Annotated[dict, Depends(require_active_session)],
    svc: ImageService = Depends(_service),
):
    available = await svc.list_available_groups(user_id=user["sub"])
    active = await svc.get_active_config(user_id=user["sub"])
    return _ImageConfigDiscoveryDto(available=available, active=active)


@router.post("/config", response_model=ActiveImageConfigDto)
async def set_config(
    body: _SetActiveConfigRequest,
    user: Annotated[dict, Depends(require_active_session)],
    svc: ImageService = Depends(_service),
):
    try:
        return await svc.set_active_config(
            user_id=user["sub"],
            connection_id=body.connection_id,
            group_id=body.group_id,
            config=body.config,
        )
    except ValueError as exc:
        _log.warning(
            "set_config rejected: user=%s group=%s reason=%s",
            user["sub"], body.group_id, exc,
        )
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{image_id}", response_model=GeneratedImageDetailDto)
async def get_image(
    image_id: str,
    user: Annotated[dict, Depends(require_active_session)],
    svc: ImageService = Depends(_service),
):
    detail = await svc.get_image(user_id=user["sub"], image_id=image_id)
    if detail is None:
        _log.debug("get_image 404: user=%s image_id=%s", user["sub"], image_id)
        raise HTTPException(status_code=404, detail="image not found")
    return detail


@router.get("/{image_id}/blob")
async def get_blob(
    image_id: str,
    user: Annotated[dict, Depends(require_active_session)],
    svc: ImageService = Depends(_service),
):
    result = await svc.stream_blob(user_id=user["sub"], image_id=image_id, kind="full")
    if result is None:
        _log.debug("get_blob 404: user=%s image_id=%s", user["sub"], image_id)
        raise HTTPException(status_code=404, detail="image not found")
    data, content_type = result
    return Response(content=data, media_type=content_type)


@router.get("/{image_id}/thumb")
async def get_thumb(
    image_id: str,
    user: Annotated[dict, Depends(require_active_session)],
    svc: ImageService = Depends(_service),
):
    result = await svc.stream_blob(user_id=user["sub"], image_id=image_id, kind="thumb")
    if result is None:
        _log.debug("get_thumb 404: user=%s image_id=%s", user["sub"], image_id)
        raise HTTPException(status_code=404, detail="image not found")
    data, content_type = result
    return Response(content=data, media_type=content_type)


@router.delete("/{image_id}", status_code=204)
async def delete_image(
    image_id: str,
    user: Annotated[dict, Depends(require_active_session)],
    svc: ImageService = Depends(_service),
):
    deleted = await svc.delete_image(user_id=user["sub"], image_id=image_id)
    if not deleted:
        _log.debug("delete_image 404: user=%s image_id=%s", user["sub"], image_id)
        raise HTTPException(status_code=404, detail="image not found")

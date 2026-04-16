"""REST endpoints for host-side community provisioning."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from backend.database import get_db
from backend.dependencies import require_active_session
from backend.modules.llm._homelabs import (
    ApiKeyNotFoundError,
    HomelabNotFoundError,
    HomelabService,
    TooManyApiKeysError,
    TooManyHomelabsError,
)
from backend.ws.event_bus import EventBus, get_event_bus
from shared.dtos.llm import (
    ApiKeyCreatedDto,
    ApiKeyDto,
    CreateApiKeyDto,
    CreateHomelabDto,
    HomelabCreatedDto,
    HomelabDto,
    HomelabHostKeyRegeneratedDto,
    UpdateApiKeyDto,
    UpdateHomelabDto,
)

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm/homelabs")


def _service(bus: EventBus = Depends(get_event_bus)) -> HomelabService:
    return HomelabService(get_db(), bus)


def _online_ids() -> set[str]:
    """Best-effort fetch of the SidecarRegistry online set.

    The registry lives in Plan 3 (CSP). Until that lands this returns an
    empty set so the ``is_online`` flag is always ``False``.
    """
    try:
        from backend.modules.llm._csp._registry import (  # type: ignore[import-not-found]
            get_sidecar_registry,
        )

        return set(get_sidecar_registry().online_homelab_ids())
    except Exception:
        return set()


# --- Homelab CRUD ---


@router.post("", status_code=status.HTTP_201_CREATED, response_model=HomelabCreatedDto)
async def create_homelab(
    body: CreateHomelabDto,
    user: dict = Depends(require_active_session),
    svc: HomelabService = Depends(_service),
):
    try:
        result = await svc.create_homelab(
            user_id=user["sub"], display_name=body.display_name
        )
    except TooManyHomelabsError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return HomelabCreatedDto(
        plaintext_host_key=result["plaintext_host_key"], **result["homelab"]
    )


@router.get("", response_model=list[HomelabDto])
async def list_homelabs(
    user: dict = Depends(require_active_session),
    svc: HomelabService = Depends(_service),
):
    return await svc.list_homelabs(user["sub"], online_ids=_online_ids())


@router.get("/{homelab_id}", response_model=HomelabDto)
async def get_homelab(
    homelab_id: str,
    user: dict = Depends(require_active_session),
    svc: HomelabService = Depends(_service),
):
    try:
        return await svc.get_homelab(
            user["sub"], homelab_id, is_online=homelab_id in _online_ids()
        )
    except HomelabNotFoundError:
        raise HTTPException(status_code=404, detail="homelab not found")


@router.patch("/{homelab_id}", response_model=HomelabDto)
async def update_homelab(
    homelab_id: str,
    body: UpdateHomelabDto,
    user: dict = Depends(require_active_session),
    svc: HomelabService = Depends(_service),
):
    if body.display_name is None:
        raise HTTPException(status_code=400, detail="nothing to update")
    try:
        return await svc.rename_homelab(
            user["sub"], homelab_id, body.display_name
        )
    except HomelabNotFoundError:
        raise HTTPException(status_code=404, detail="homelab not found")


@router.delete("/{homelab_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_homelab(
    homelab_id: str,
    user: dict = Depends(require_active_session),
    svc: HomelabService = Depends(_service),
):
    try:
        await svc.delete_homelab(user["sub"], homelab_id)
    except HomelabNotFoundError:
        raise HTTPException(status_code=404, detail="homelab not found")


@router.post(
    "/{homelab_id}/regenerate-host-key",
    response_model=HomelabHostKeyRegeneratedDto,
)
async def regenerate_host_key(
    homelab_id: str,
    user: dict = Depends(require_active_session),
    svc: HomelabService = Depends(_service),
):
    try:
        result = await svc.regenerate_host_key(user["sub"], homelab_id)
    except HomelabNotFoundError:
        raise HTTPException(status_code=404, detail="homelab not found")
    return HomelabHostKeyRegeneratedDto(
        plaintext_host_key=result["plaintext_host_key"], **result["homelab"]
    )


# --- API-keys ---


@router.get("/{homelab_id}/api-keys", response_model=list[ApiKeyDto])
async def list_api_keys(
    homelab_id: str,
    user: dict = Depends(require_active_session),
    svc: HomelabService = Depends(_service),
):
    try:
        return await svc.list_api_keys(user["sub"], homelab_id)
    except HomelabNotFoundError:
        raise HTTPException(status_code=404, detail="homelab not found")


@router.post(
    "/{homelab_id}/api-keys",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiKeyCreatedDto,
)
async def create_api_key(
    homelab_id: str,
    body: CreateApiKeyDto,
    user: dict = Depends(require_active_session),
    svc: HomelabService = Depends(_service),
):
    try:
        result = await svc.create_api_key(
            user_id=user["sub"],
            homelab_id=homelab_id,
            display_name=body.display_name,
            allowed_model_slugs=body.allowed_model_slugs,
        )
    except HomelabNotFoundError:
        raise HTTPException(status_code=404, detail="homelab not found")
    except TooManyApiKeysError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return ApiKeyCreatedDto(
        plaintext_api_key=result["plaintext_api_key"], **result["api_key"]
    )


@router.patch("/{homelab_id}/api-keys/{api_key_id}", response_model=ApiKeyDto)
async def update_api_key(
    homelab_id: str,
    api_key_id: str,
    body: UpdateApiKeyDto,
    user: dict = Depends(require_active_session),
    svc: HomelabService = Depends(_service),
):
    if body.display_name is None and body.allowed_model_slugs is None:
        raise HTTPException(status_code=400, detail="nothing to update")
    try:
        return await svc.update_api_key(
            user_id=user["sub"],
            homelab_id=homelab_id,
            api_key_id=api_key_id,
            display_name=body.display_name,
            allowed_model_slugs=body.allowed_model_slugs,
        )
    except (HomelabNotFoundError, ApiKeyNotFoundError):
        raise HTTPException(status_code=404, detail="not found")


@router.delete(
    "/{homelab_id}/api-keys/{api_key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_api_key(
    homelab_id: str,
    api_key_id: str,
    user: dict = Depends(require_active_session),
    svc: HomelabService = Depends(_service),
):
    try:
        await svc.revoke_api_key(user["sub"], homelab_id, api_key_id)
    except (HomelabNotFoundError, ApiKeyNotFoundError):
        raise HTTPException(status_code=404, detail="not found")


@router.post(
    "/{homelab_id}/api-keys/{api_key_id}/regenerate",
    response_model=ApiKeyCreatedDto,
)
async def regenerate_api_key(
    homelab_id: str,
    api_key_id: str,
    user: dict = Depends(require_active_session),
    svc: HomelabService = Depends(_service),
):
    try:
        result = await svc.regenerate_api_key(
            user["sub"], homelab_id, api_key_id
        )
    except (HomelabNotFoundError, ApiKeyNotFoundError):
        raise HTTPException(status_code=404, detail="not found")
    return ApiKeyCreatedDto(
        plaintext_api_key=result["plaintext_api_key"], **result["api_key"]
    )

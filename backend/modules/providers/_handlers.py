"""FastAPI routes for /api/providers — Premium Provider Accounts."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from backend.database import get_db
from backend.dependencies import require_active_session
from shared.dtos.providers import (
    PremiumProviderAccountDto,
    PremiumProviderDefinitionDto,
    PremiumProviderUpsertRequest,
)

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/providers", tags=["providers"])


def _service():
    # Deferred import to avoid importing the module's __init__ (which pulls in
    # _handlers itself) while this file is still being loaded.
    from backend.modules.providers import PremiumProviderService
    from backend.modules.providers._repository import (
        PremiumProviderAccountRepository,
    )
    return PremiumProviderService(PremiumProviderAccountRepository(get_db()))


@router.get("/catalogue", response_model=list[PremiumProviderDefinitionDto])
async def catalogue(_user: dict = Depends(require_active_session)):
    return await _service().catalogue()


@router.get("/accounts", response_model=list[PremiumProviderAccountDto])
async def list_accounts(user: dict = Depends(require_active_session)):
    return await _service().list_for_user(user["sub"])


@router.put(
    "/accounts/{provider_id}", response_model=PremiumProviderAccountDto,
)
async def upsert_account(
    provider_id: str,
    body: PremiumProviderUpsertRequest,
    user: dict = Depends(require_active_session),
):
    from backend.modules.providers import PremiumProviderNotFoundError
    try:
        return await _service().upsert(user["sub"], provider_id, body.config)
    except PremiumProviderNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown provider: {provider_id}",
        )


@router.delete(
    "/accounts/{provider_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_account(
    provider_id: str,
    user: dict = Depends(require_active_session),
):
    await _service().delete(user["sub"], provider_id)
    return None

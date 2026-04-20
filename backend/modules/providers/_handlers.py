"""FastAPI routes for /api/providers — Premium Provider Accounts."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from backend.database import get_db
from backend.dependencies import require_active_session
from shared.dtos.llm import ModelMetaDto
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
    from backend.modules.providers import (
        PremiumProviderAccountNotFoundError,
    )
    from backend.modules.providers._registry import get as get_definition
    if get_definition(provider_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown provider",
        )
    try:
        await _service().delete(user["sub"], provider_id)
    except PremiumProviderAccountNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account configured",
        )
    return None


@router.get(
    "/accounts/{provider_id}/models",
    response_model=list[ModelMetaDto],
)
async def list_provider_models(
    provider_id: str,
    user: dict = Depends(require_active_session),
):
    """Return the user's Premium-Provider model list (cached-or-fresh).

    Mirrors ``GET /api/llm/connections/{id}/models`` but for the Premium
    path. Business logic lives in the LLM module — this handler is just a
    thin HTTP adaptor that maps domain errors onto the right status codes.
    """
    # Local import — avoids import-time cycles (providers → llm → providers).
    from backend.modules.llm import (
        PremiumProviderAccountMissingError,
        PremiumProviderUnknownError,
        list_premium_provider_models,
    )

    try:
        return await list_premium_provider_models(user["sub"], provider_id)
    except PremiumProviderUnknownError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown provider",
        )
    except PremiumProviderAccountMissingError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account configured",
        )


@router.post(
    "/accounts/{provider_id}/refresh",
    status_code=status.HTTP_202_ACCEPTED,
)
async def refresh_provider_models(
    provider_id: str,
    user: dict = Depends(require_active_session),
):
    """Drop the user-scoped cache, re-fetch, and publish a refresh event.

    On upstream failure the handler returns 502, and the event carries
    ``success=False`` + the error string — same contract as
    ``POST /api/llm/connections/{id}/refresh``.
    """
    from backend.modules.llm import (
        PremiumProviderAccountMissingError,
        PremiumProviderUnknownError,
        refresh_premium_provider_models,
    )
    from backend.ws.event_bus import get_event_bus
    from shared.events.llm import PremiumProviderModelsRefreshedEvent
    from shared.topics import Topics

    error_msg: str | None = None
    try:
        await refresh_premium_provider_models(user["sub"], provider_id)
    except PremiumProviderUnknownError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown provider",
        )
    except PremiumProviderAccountMissingError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account configured",
        )
    except Exception as exc:  # noqa: BLE001 — surface to FE
        error_msg = str(exc)
        _log.warning(
            "premium refresh failed for provider=%s user=%s: %s",
            provider_id, user["sub"], exc,
        )

    bus = get_event_bus()
    await bus.publish(
        Topics.PREMIUM_PROVIDER_MODELS_REFRESHED,
        PremiumProviderModelsRefreshedEvent(
            provider_id=provider_id,
            success=error_msg is None,
            error=error_msg,
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[user["sub"]],
    )
    if error_msg is not None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=error_msg,
        )
    return {"status": "ok"}


@router.post(
    "/accounts/{provider_id}/test",
    response_model=None,  # response shape handled manually for clarity
)
async def test_account(
    provider_id: str,
    user: dict = Depends(require_active_session),
):
    """Probe the configured upstream with the stored API key.

    Returns ``PremiumProviderTestResultDto`` with ``status="ok"`` on
    a ``200`` response, ``status="error"`` for 401/403 ("API key
    rejected …"), other non-200 statuses, timeouts, and network
    errors. Always HTTP 200 unless the provider or account is
    unknown (then 404).
    """
    import httpx

    from backend.modules.providers._registry import get as get_definition
    from backend.modules.providers._repository import (
        PremiumProviderAccountRepository,
    )
    from backend.ws.event_bus import get_event_bus
    from shared.dtos.providers import PremiumProviderTestResultDto
    from shared.events.providers import PremiumProviderAccountTestedEvent
    from shared.topics import Topics

    defn = get_definition(provider_id)
    if defn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown provider",
        )

    repo = PremiumProviderAccountRepository(get_db())
    doc = await repo.find(user["sub"], provider_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account configured",
        )
    api_key = repo.get_decrypted_secret(doc, "api_key")
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No API key stored",
        )

    probe_status: str = "error"
    probe_error: str | None = None
    timeout = httpx.Timeout(10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            resp = await c.request(
                defn.probe_method,
                defn.probe_url,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if resp.status_code == 200:
            probe_status = "ok"
            probe_error = None
        elif resp.status_code in (401, 403):
            probe_error = f"API key rejected by {defn.display_name}"
        else:
            probe_error = (
                f"{defn.display_name} returned {resp.status_code}"
            )
    except Exception as exc:  # noqa: BLE001 — surface to the frontend
        probe_error = str(exc) or exc.__class__.__name__

    await repo.update_test_status(
        user["sub"], provider_id,
        status=probe_status, error=probe_error,
    )

    bus = get_event_bus()
    await bus.publish(
        Topics.PREMIUM_PROVIDER_ACCOUNT_TESTED,
        PremiumProviderAccountTestedEvent(
            provider_id=provider_id,
            status=probe_status,  # type: ignore[arg-type]
            error=probe_error,
        ),
        target_user_ids=[user["sub"]],
    )
    _log.info(
        "premium probe provider=%s user=%s status=%s",
        provider_id, user["sub"], probe_status,
    )

    return PremiumProviderTestResultDto(
        status=probe_status, error=probe_error,
    ).model_dump()

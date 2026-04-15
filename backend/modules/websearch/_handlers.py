"""HTTP handlers for web-search provider credentials."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from backend.database import get_db
from backend.dependencies import require_active_session
from backend.modules.websearch._credentials import WebSearchCredentialRepository
from backend.modules.websearch._registry import (
    SEARCH_ADAPTER_REGISTRY,
    SEARCH_PROVIDER_BASE_URLS,
    SEARCH_PROVIDER_DISPLAY_NAMES,
)
from backend.ws.event_bus import EventBus, get_event_bus
from shared.dtos.websearch import (
    SetWebSearchKeyDto,
    WebSearchCredentialDto,
    WebSearchProviderDto,
    WebSearchTestRequestDto,
)
from shared.events.websearch import (
    WebSearchCredentialRemovedEvent,
    WebSearchCredentialSetEvent,
    WebSearchCredentialTestedEvent,
)
from shared.topics import Topics

router = APIRouter(prefix="/api/websearch")


def _repo() -> WebSearchCredentialRepository:
    return WebSearchCredentialRepository(get_db())


@router.get("/providers")
async def list_providers(
    user: dict = Depends(require_active_session),
) -> list[WebSearchProviderDto]:
    repo = _repo()
    out: list[WebSearchProviderDto] = []
    for pid in SEARCH_ADAPTER_REGISTRY:
        doc = await repo.find(user["sub"], pid)
        out.append(
            WebSearchProviderDto(
                provider_id=pid,
                display_name=SEARCH_PROVIDER_DISPLAY_NAMES.get(pid, pid),
                is_configured=doc is not None,
                last_test_status=doc.get("last_test_status") if doc else None,
                last_test_error=doc.get("last_test_error") if doc else None,
            )
        )
    return out


@router.get("/providers/{provider_id}/credential")
async def get_credential(
    provider_id: str,
    user: dict = Depends(require_active_session),
) -> WebSearchCredentialDto:
    if provider_id not in SEARCH_ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")
    doc = await _repo().find(user["sub"], provider_id)
    return WebSearchCredentialRepository.to_dto(doc, provider_id)


@router.put("/providers/{provider_id}/credential")
async def set_credential(
    provider_id: str,
    body: SetWebSearchKeyDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
) -> WebSearchCredentialDto:
    if provider_id not in SEARCH_ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")
    doc = await _repo().upsert(user["sub"], provider_id, body.api_key)
    dto = WebSearchCredentialRepository.to_dto(doc, provider_id)
    await event_bus.publish(
        Topics.WEBSEARCH_CREDENTIAL_SET,
        WebSearchCredentialSetEvent(
            provider_id=provider_id,
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[user["sub"]],
    )
    return dto


@router.delete("/providers/{provider_id}/credential", status_code=204)
async def delete_credential(
    provider_id: str,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
) -> None:
    if provider_id not in SEARCH_ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")
    deleted = await _repo().delete(user["sub"], provider_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="No credential configured")
    await event_bus.publish(
        Topics.WEBSEARCH_CREDENTIAL_REMOVED,
        WebSearchCredentialRemovedEvent(
            provider_id=provider_id,
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[user["sub"]],
    )


@router.post("/providers/{provider_id}/test")
async def test_credential(
    provider_id: str,
    body: WebSearchTestRequestDto | None = None,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
) -> dict:
    if provider_id not in SEARCH_ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    body_key = body.api_key if body else None
    api_key = body_key or await _repo().get_key(user["sub"], provider_id)
    if not api_key:
        raise HTTPException(
            status_code=400, detail="No API key provided and none stored"
        )

    adapter = SEARCH_ADAPTER_REGISTRY[provider_id](
        base_url=SEARCH_PROVIDER_BASE_URLS[provider_id],
    )
    valid = False
    error: str | None = None
    try:
        await adapter.search(api_key, "capital of paris", 1)
        valid = True
    except Exception as exc:
        error = str(exc)
    await _repo().update_test(
        user["sub"],
        provider_id,
        status="valid" if valid else "failed",
        error=error,
    )
    await event_bus.publish(
        Topics.WEBSEARCH_CREDENTIAL_TESTED,
        WebSearchCredentialTestedEvent(
            provider_id=provider_id,
            valid=valid,
            error=error,
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[user["sub"]],
    )
    return {"valid": valid, "error": error}

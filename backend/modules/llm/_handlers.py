from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from backend.database import get_db, get_redis
from backend.dependencies import require_active_session
from backend.modules.llm._credentials import CredentialRepository
from backend.modules.llm._metadata import get_models
from backend.modules.llm._registry import ADAPTER_REGISTRY, PROVIDER_DISPLAY_NAMES
from backend.ws.event_bus import EventBus, get_event_bus
from shared.dtos.llm import ProviderCredentialDto, SetProviderKeyDto
from shared.events.llm import (
    LlmCredentialRemovedEvent,
    LlmCredentialSetEvent,
    LlmCredentialTestedEvent,
)
from shared.topics import Topics

router = APIRouter(prefix="/api/llm")


def _credential_repo() -> CredentialRepository:
    return CredentialRepository(get_db())


@router.get("/providers")
async def list_providers(user: dict = Depends(require_active_session)):
    repo = _credential_repo()
    configured = {
        doc["provider_id"]: doc
        for doc in await repo.list_for_user(user["sub"])
    }
    result = []
    for provider_id in ADAPTER_REGISTRY:
        doc = configured.get(provider_id)
        if doc:
            result.append(CredentialRepository.to_dto(doc, PROVIDER_DISPLAY_NAMES[provider_id]))
        else:
            result.append(
                ProviderCredentialDto(
                    provider_id=provider_id,
                    display_name=PROVIDER_DISPLAY_NAMES[provider_id],
                    is_configured=False,
                )
            )
    return result


@router.put("/providers/{provider_id}/key", status_code=200)
async def set_provider_key(
    provider_id: str,
    body: SetProviderKeyDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    if provider_id not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    repo = _credential_repo()
    doc = await repo.upsert(user["sub"], provider_id, body.api_key)

    await event_bus.publish(
        Topics.LLM_CREDENTIAL_SET,
        LlmCredentialSetEvent(
            provider_id=provider_id,
            user_id=user["sub"],
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[user["sub"]],
    )

    return CredentialRepository.to_dto(doc, PROVIDER_DISPLAY_NAMES[provider_id])


@router.delete("/providers/{provider_id}/key", status_code=200)
async def remove_provider_key(
    provider_id: str,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    if provider_id not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    repo = _credential_repo()
    deleted = await repo.delete(user["sub"], provider_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="No key configured for this provider")

    await event_bus.publish(
        Topics.LLM_CREDENTIAL_REMOVED,
        LlmCredentialRemovedEvent(
            provider_id=provider_id,
            user_id=user["sub"],
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[user["sub"]],
    )

    return {"status": "ok"}


@router.post("/providers/{provider_id}/test", status_code=200)
async def test_provider_key(
    provider_id: str,
    body: SetProviderKeyDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    if provider_id not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    adapter = ADAPTER_REGISTRY[provider_id]()
    try:
        valid = await adapter.validate_key(body.api_key)
    except NotImplementedError:
        raise HTTPException(
            status_code=501,
            detail=f"Provider '{provider_id}' is not yet fully implemented",
        )

    await event_bus.publish(
        Topics.LLM_CREDENTIAL_TESTED,
        LlmCredentialTestedEvent(
            provider_id=provider_id,
            user_id=user["sub"],
            valid=valid,
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[user["sub"]],
    )

    return {"valid": valid}


@router.get("/providers/{provider_id}/models")
async def list_models(
    provider_id: str,
    user: dict = Depends(require_active_session),
):
    if provider_id not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    adapter = ADAPTER_REGISTRY[provider_id]()
    redis = get_redis()
    return await get_models(provider_id, redis, adapter)

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from backend.database import get_db, get_redis
from backend.dependencies import require_active_session, require_admin
from backend.modules.llm._credentials import CredentialRepository
from backend.modules.llm._curation import CurationRepository
from backend.modules.llm._metadata import get_models
from backend.modules.llm._registry import ADAPTER_REGISTRY, PROVIDER_BASE_URLS, PROVIDER_DISPLAY_NAMES
from backend.modules.llm._user_config import UserModelConfigRepository
from backend.ws.event_bus import EventBus, get_event_bus
from shared.dtos.llm import ModelCurationDto, ModelMetaDto, ProviderCredentialDto, SetModelCurationDto, SetProviderKeyDto, SetUserModelConfigDto, UserModelConfigDto
from shared.events.llm import (
    LlmCredentialRemovedEvent,
    LlmCredentialSetEvent,
    LlmCredentialTestedEvent,
    LlmModelCuratedEvent,
    LlmUserModelConfigUpdatedEvent,
)
from shared.topics import Topics

router = APIRouter(prefix="/api/llm")


def _credential_repo() -> CredentialRepository:
    return CredentialRepository(get_db())


def _curation_repo() -> CurationRepository:
    return CurationRepository(get_db())


def _user_config_repo() -> UserModelConfigRepository:
    return UserModelConfigRepository(get_db())


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

    adapter = ADAPTER_REGISTRY[provider_id](base_url=PROVIDER_BASE_URLS[provider_id])
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
    event_bus: EventBus = Depends(get_event_bus),
):
    if provider_id not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    adapter = ADAPTER_REGISTRY[provider_id](base_url=PROVIDER_BASE_URLS[provider_id])
    redis = get_redis()
    models = await get_models(provider_id, redis, adapter, event_bus=event_bus)

    # Merge curation data
    curation_repo = _curation_repo()
    curations = await curation_repo.list_for_provider(provider_id)
    curation_map = {doc["model_slug"]: doc for doc in curations}

    result = []
    for model in models:
        curation_doc = curation_map.get(model.model_id)
        if curation_doc:
            model = model.model_copy(
                update={"curation": CurationRepository.to_dto(curation_doc)}
            )
        result.append(model)

    return result


@router.put("/providers/{provider_id}/models/{model_slug:path}/curation", status_code=200)
async def set_model_curation(
    provider_id: str,
    model_slug: str,
    body: SetModelCurationDto,
    user: dict = Depends(require_admin),
    event_bus: EventBus = Depends(get_event_bus),
):
    if provider_id not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    repo = _curation_repo()
    doc = await repo.upsert(
        provider_id=provider_id,
        model_slug=model_slug,
        overall_rating=body.overall_rating.value,
        hidden=body.hidden,
        admin_description=body.admin_description,
        admin_user_id=user["sub"],
    )

    curation_dto = CurationRepository.to_dto(doc)

    # Build a minimal model DTO for the event payload
    model_dto = ModelMetaDto(
        provider_id=provider_id,
        model_id=model_slug,
        display_name=model_slug,
        context_window=0,
        supports_reasoning=False,
        supports_vision=False,
        supports_tool_calls=False,
        curation=curation_dto,
    )

    # Try to enrich from cache
    redis = get_redis()
    adapter = ADAPTER_REGISTRY[provider_id](base_url=PROVIDER_BASE_URLS[provider_id])
    cached_models = await get_models(provider_id, redis, adapter)
    for cached in cached_models:
        if cached.model_id == model_slug:
            model_dto = cached.model_copy(update={"curation": curation_dto})
            break

    await event_bus.publish(
        Topics.LLM_MODEL_CURATED,
        LlmModelCuratedEvent(
            provider_id=provider_id,
            model_slug=model_slug,
            model=model_dto,
            curated_by=user["sub"],
            timestamp=datetime.now(timezone.utc),
        ),
    )

    return curation_dto


@router.delete("/providers/{provider_id}/models/{model_slug:path}/curation", status_code=200)
async def remove_model_curation(
    provider_id: str,
    model_slug: str,
    user: dict = Depends(require_admin),
    event_bus: EventBus = Depends(get_event_bus),
):
    if provider_id not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    repo = _curation_repo()
    deleted = await repo.delete(provider_id, model_slug)
    if not deleted:
        raise HTTPException(status_code=404, detail="No curation exists for this model")

    model_dto = ModelMetaDto(
        provider_id=provider_id,
        model_id=model_slug,
        display_name=model_slug,
        context_window=0,
        supports_reasoning=False,
        supports_vision=False,
        supports_tool_calls=False,
        curation=None,
    )

    redis = get_redis()
    adapter = ADAPTER_REGISTRY[provider_id](base_url=PROVIDER_BASE_URLS[provider_id])
    cached_models = await get_models(provider_id, redis, adapter)
    for cached in cached_models:
        if cached.model_id == model_slug:
            model_dto = cached.model_copy(update={"curation": None})
            break

    await event_bus.publish(
        Topics.LLM_MODEL_CURATED,
        LlmModelCuratedEvent(
            provider_id=provider_id,
            model_slug=model_slug,
            model=model_dto,
            curated_by=user["sub"],
            timestamp=datetime.now(timezone.utc),
        ),
    )

    return {"status": "ok"}


@router.get("/user-model-configs")
async def list_user_model_configs(user: dict = Depends(require_active_session)):
    repo = _user_config_repo()
    docs = await repo.list_for_user(user["sub"])
    return [UserModelConfigRepository.to_dto(doc) for doc in docs]


@router.get("/providers/{provider_id}/models/{model_slug:path}/user-config")
async def get_user_model_config(
    provider_id: str,
    model_slug: str,
    user: dict = Depends(require_active_session),
):
    if provider_id not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    model_unique_id = f"{provider_id}:{model_slug}"
    repo = _user_config_repo()
    doc = await repo.find(user["sub"], model_unique_id)
    if doc:
        return UserModelConfigRepository.to_dto(doc)
    return UserModelConfigRepository.default_dto(model_unique_id)


@router.put("/providers/{provider_id}/models/{model_slug:path}/user-config", status_code=200)
async def set_user_model_config(
    provider_id: str,
    model_slug: str,
    body: SetUserModelConfigDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    if provider_id not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    model_unique_id = f"{provider_id}:{model_slug}"
    repo = _user_config_repo()
    doc = await repo.upsert(
        user_id=user["sub"],
        model_unique_id=model_unique_id,
        is_favourite=body.is_favourite,
        is_hidden=body.is_hidden,
        notes=body.notes,
        system_prompt_addition=body.system_prompt_addition,
    )
    config_dto = UserModelConfigRepository.to_dto(doc)

    await event_bus.publish(
        Topics.LLM_USER_MODEL_CONFIG_UPDATED,
        LlmUserModelConfigUpdatedEvent(
            model_unique_id=model_unique_id,
            config=config_dto,
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[user["sub"]],
    )

    return config_dto


@router.delete("/providers/{provider_id}/models/{model_slug:path}/user-config", status_code=200)
async def delete_user_model_config(
    provider_id: str,
    model_slug: str,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    if provider_id not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    model_unique_id = f"{provider_id}:{model_slug}"
    repo = _user_config_repo()
    await repo.delete(user["sub"], model_unique_id)

    default_config = UserModelConfigRepository.default_dto(model_unique_id)

    await event_bus.publish(
        Topics.LLM_USER_MODEL_CONFIG_UPDATED,
        LlmUserModelConfigUpdatedEvent(
            model_unique_id=model_unique_id,
            config=default_config,
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[user["sub"]],
    )

    return default_config

from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException

from backend.database import get_db, get_redis
from backend.dependencies import require_active_session, require_admin
from backend.modules.llm._credentials import CredentialRepository
from backend.modules.llm._curation import CurationRepository
from backend.modules.llm._metadata import get_models, refresh_all_providers
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
    for provider_id, adapter_cls in ADAPTER_REGISTRY.items():
        requires_key = adapter_cls.requires_key_for_listing
        requires_setup = adapter_cls.requires_setup
        doc = configured.get(provider_id)
        if doc:
            dto = CredentialRepository.to_dto(doc, PROVIDER_DISPLAY_NAMES[provider_id])
            dto = dto.model_copy(update={"requires_key_for_listing": requires_key, "requires_setup": requires_setup})
            result.append(dto)
        else:
            result.append(
                ProviderCredentialDto(
                    provider_id=provider_id,
                    display_name=PROVIDER_DISPLAY_NAMES[provider_id],
                    is_configured=adapter_cls.is_global,
                    requires_key_for_listing=requires_key,
                    requires_setup=requires_setup,
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


async def _validate_and_persist(
    provider_id: str, api_key: str, user_id: str, event_bus: EventBus,
) -> dict:
    """Validate an API key against the provider and persist the test result."""
    adapter = ADAPTER_REGISTRY[provider_id](base_url=PROVIDER_BASE_URLS[provider_id])
    error_message = None
    try:
        valid = await adapter.validate_key(api_key)
        if not valid:
            error_message = "Key rejected by provider"
    except NotImplementedError:
        raise HTTPException(
            status_code=501,
            detail=f"Provider '{provider_id}' is not yet fully implemented",
        )
    except Exception as exc:
        valid = False
        error_message = str(exc)

    repo = _credential_repo()
    test_status = "valid" if valid else "failed"
    await repo.update_test_status(user_id, provider_id, test_status, error_message)

    await event_bus.publish(
        Topics.LLM_CREDENTIAL_TESTED,
        LlmCredentialTestedEvent(
            provider_id=provider_id,
            user_id=user_id,
            valid=valid,
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[user_id],
    )

    return {"valid": valid, "error": error_message}


@router.post("/providers/{provider_id}/test", status_code=200)
async def test_provider_key(
    provider_id: str,
    body: SetProviderKeyDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    if provider_id not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    return await _validate_and_persist(provider_id, body.api_key, user["sub"], event_bus)


@router.post("/providers/{provider_id}/test-stored", status_code=200)
async def test_stored_provider_key(
    provider_id: str,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    """Test the stored (encrypted) API key for this provider without requiring the key in the request."""
    if provider_id not in ADAPTER_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown provider")

    repo = _credential_repo()
    doc = await repo.find(user["sub"], provider_id)
    if not doc:
        raise HTTPException(status_code=404, detail="No key configured for this provider")

    raw_key = repo.get_raw_key(doc)
    return await _validate_and_persist(provider_id, raw_key, user["sub"], event_bus)


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
        provider_display_name=PROVIDER_DISPLAY_NAMES.get(provider_id, provider_id),
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
        provider_display_name=PROVIDER_DISPLAY_NAMES.get(provider_id, provider_id),
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
    # Only pass fields that were explicitly sent in the request so that
    # nullable fields (e.g. custom_display_name) can be reset to None.
    fields = {k: getattr(body, k) for k in body.model_fields_set}
    doc = await repo.upsert(
        user_id=user["sub"],
        model_unique_id=model_unique_id,
        fields=fields,
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


@router.get("/admin/credential-status")
async def admin_credential_status(user: dict = Depends(require_admin)):
    repo = _credential_repo()
    all_creds = await repo.list_all()

    by_user: dict[str, list[dict]] = {}
    for cred in all_creds:
        uid = cred["user_id"]
        if uid not in by_user:
            by_user[uid] = []
        by_user[uid].append({
            "provider_id": cred["provider_id"],
            "is_configured": True,
        })

    return [
        {"user_id": uid, "providers": providers}
        for uid, providers in by_user.items()
    ]


@router.post("/admin/refresh-providers", status_code=200)
async def refresh_providers_handler(
    user: dict = Depends(require_admin),
    event_bus: EventBus = Depends(get_event_bus),
):
    """Wipe model caches for all providers and trigger a fresh fetch."""
    redis = get_redis()
    for provider_id in ADAPTER_REGISTRY.keys():
        await redis.delete(f"llm:models:{provider_id}")

    models = await refresh_all_providers(
        redis=redis,
        registry=ADAPTER_REGISTRY,
        base_urls=PROVIDER_BASE_URLS,
        display_names=PROVIDER_DISPLAY_NAMES,
        event_bus=event_bus,
    )
    return {"status": "ok", "total_models": len(models)}


@router.get("/provider-status")
async def get_provider_status(user: dict = Depends(require_active_session)):
    """Return current per-provider reachability snapshot.

    Reachability is derived directly from the model cache: a provider is
    considered available iff its cached model list exists and is non-empty.
    This avoids drift between the model-fetch path (``get_models``) and the
    refresh-all path (``refresh_all_providers``) — both populate the same
    cache, so both feed the same snapshot.
    """
    import json as _json

    redis = get_redis()
    statuses: dict[str, bool] = {}
    for provider_id in ADAPTER_REGISTRY.keys():
        cached = await redis.get(f"llm:models:{provider_id}")
        if not cached:
            statuses[provider_id] = False
            continue
        try:
            statuses[provider_id] = len(_json.loads(cached)) > 0
        except (ValueError, TypeError):
            statuses[provider_id] = False
    return {"statuses": statuses}


async def _proxy_ollama_local(path: str) -> dict:
    """Forward a GET request to the local Ollama instance."""
    base_url = PROVIDER_BASE_URLS.get("ollama_local")
    if not base_url:
        raise HTTPException(status_code=404, detail="ollama_local provider not configured")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.get(f"{base_url}{path}")
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Cannot connect to Ollama Local")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Ollama returned {exc.response.status_code}")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Ollama Local request timed out")


@router.get("/admin/ollama-local/ps")
async def ollama_local_ps(user: dict = Depends(require_admin)):
    """Proxy to Ollama Local /api/ps — returns currently running models."""
    return await _proxy_ollama_local("/api/ps")


@router.get("/admin/ollama-local/tags")
async def ollama_local_tags(user: dict = Depends(require_admin)):
    """Proxy to Ollama Local /api/tags — returns all available models."""
    return await _proxy_ollama_local("/api/tags")

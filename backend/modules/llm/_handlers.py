from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from backend.database import get_db, get_redis
from backend.dependencies import require_active_session
from backend.modules.llm._adapters._types import ResolvedConnection
from backend.modules.llm._connections import (
    ConnectionNotFoundError,
    ConnectionRepository,
    InvalidAdapterTypeError,
    InvalidSlugError,
    SlugAlreadyExistsError,
)
from backend.modules.llm._metadata import (
    get_models_for_connection,
    refresh_connection_models,
)
from backend.modules.llm._registry import ADAPTER_REGISTRY
from backend.modules.llm._resolver import resolve_connection_for_user
from backend.modules.llm._semaphores import get_semaphore_registry
from backend.modules.llm._user_config import UserModelConfigRepository
from backend.modules.persona import unwire_personas_for_connection
from backend.ws.event_bus import EventBus, get_event_bus
from shared.dtos.llm import (
    AdapterDto,
    AdapterTemplateDto,
    ConnectionDto,
    CreateConnectionDto,
    SetUserModelConfigDto,
    UpdateConnectionDto,
    UserModelConfigDto,
)
from shared.events.llm import (
    LlmConnectionCreatedEvent,
    LlmConnectionModelsRefreshedEvent,
    LlmConnectionRemovedEvent,
    LlmConnectionUpdatedEvent,
    LlmUserModelConfigUpdatedEvent,
)
from shared.topics import Topics

router = APIRouter(prefix="/api/llm")


def _repo() -> ConnectionRepository:
    return ConnectionRepository(get_db())


def _user_config_repo() -> UserModelConfigRepository:
    return UserModelConfigRepository(get_db())


@router.get("/adapters")
async def list_adapters(
    user: dict = Depends(require_active_session),
) -> list[AdapterDto]:
    out: list[AdapterDto] = []
    for adapter_type, cls in ADAPTER_REGISTRY.items():
        templates = [
            AdapterTemplateDto(
                id=t.id,
                display_name=t.display_name,
                slug_prefix=t.slug_prefix,
                config_defaults=t.config_defaults,
            )
            for t in cls.templates()
        ]
        schema = [
            {
                "name": h.name,
                "type": h.type,
                "label": h.label,
                "required": h.required,
                "min": h.min,
                "max": h.max,
                "placeholder": h.placeholder,
            }
            for h in cls.config_schema()
        ]
        out.append(
            AdapterDto(
                adapter_type=adapter_type,
                display_name=cls.display_name,
                view_id=cls.view_id,
                templates=templates,
                config_schema=schema,
                secret_fields=sorted(cls.secret_fields),
            )
        )
    return out


@router.get("/connections")
async def list_connections(
    user: dict = Depends(require_active_session),
) -> list[ConnectionDto]:
    docs = await _repo().list_for_user(user["sub"])
    return [ConnectionRepository.to_dto(d) for d in docs]


@router.post("/connections", status_code=201)
async def create_connection(
    body: CreateConnectionDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
) -> ConnectionDto:
    try:
        doc = await _repo().create(
            user["sub"],
            body.adapter_type,
            body.display_name,
            body.slug,
            body.config,
        )
    except InvalidAdapterTypeError:
        raise HTTPException(status_code=400, detail="Unknown adapter_type")
    except InvalidSlugError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SlugAlreadyExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "slug_exists", "suggested_slug": exc.suggested},
        )
    dto = ConnectionRepository.to_dto(doc)
    await event_bus.publish(
        Topics.LLM_CONNECTION_CREATED,
        LlmConnectionCreatedEvent(
            connection=dto,
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[user["sub"]],
    )
    return dto


@router.get("/connections/{connection_id}")
async def get_connection(
    connection_id: str,
    user: dict = Depends(require_active_session),
) -> ConnectionDto:
    doc = await _repo().find(user["sub"], connection_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Not found")
    return ConnectionRepository.to_dto(doc)


@router.patch("/connections/{connection_id}")
async def update_connection(
    connection_id: str,
    body: UpdateConnectionDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
) -> ConnectionDto:
    try:
        doc = await _repo().update(
            user["sub"],
            connection_id,
            display_name=body.display_name,
            slug=body.slug,
            config=body.config,
        )
    except ConnectionNotFoundError:
        raise HTTPException(status_code=404, detail="Not found")
    except InvalidSlugError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SlugAlreadyExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "slug_exists", "suggested_slug": exc.suggested},
        )
    # Config change may have altered max_parallel — evict the semaphore so the
    # next request rebuilds it from the fresh config.
    get_semaphore_registry().evict(connection_id)
    dto = ConnectionRepository.to_dto(doc)
    await event_bus.publish(
        Topics.LLM_CONNECTION_UPDATED,
        LlmConnectionUpdatedEvent(
            connection=dto,
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[user["sub"]],
    )
    return dto


@router.delete("/connections/{connection_id}", status_code=204)
async def delete_connection(
    connection_id: str,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    # Unwire dependent personas BEFORE deleting the connection. Crossing a
    # module boundary so the persona module owns the actual DB write.
    affected = await unwire_personas_for_connection(user["sub"], connection_id)
    deleted = await _repo().delete(user["sub"], connection_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Not found")
    get_semaphore_registry().evict(connection_id)
    redis = get_redis()
    await redis.delete(f"llm:models:{connection_id}")
    await event_bus.publish(
        Topics.LLM_CONNECTION_REMOVED,
        LlmConnectionRemovedEvent(
            connection_id=connection_id,
            affected_persona_ids=affected,
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[user["sub"]],
    )


@router.get("/connections/{connection_id}/models")
async def list_models(
    c: ResolvedConnection = Depends(resolve_connection_for_user),
):
    adapter_cls = ADAPTER_REGISTRY[c.adapter_type]
    redis = get_redis()
    return await get_models_for_connection(c, adapter_cls, redis)


@router.post("/connections/{connection_id}/refresh", status_code=202)
async def refresh_models(
    c: ResolvedConnection = Depends(resolve_connection_for_user),
    event_bus: EventBus = Depends(get_event_bus),
):
    adapter_cls = ADAPTER_REGISTRY[c.adapter_type]
    redis = get_redis()
    await refresh_connection_models(c, adapter_cls, redis)
    await event_bus.publish(
        Topics.LLM_CONNECTION_MODELS_REFRESHED,
        LlmConnectionModelsRefreshedEvent(
            connection_id=c.id,
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[c.user_id],
    )
    return {"status": "ok"}


# ----- User model config endpoints -----


@router.get("/user-model-configs")
async def list_user_model_configs(
    user: dict = Depends(require_active_session),
) -> list[UserModelConfigDto]:
    docs = await _user_config_repo().list_for_user(user["sub"])
    return [UserModelConfigRepository.to_dto(d) for d in docs]


@router.get("/connections/{connection_id}/models/{model_slug:path}/user-config")
async def get_user_model_config(
    model_slug: str,
    c: ResolvedConnection = Depends(resolve_connection_for_user),
) -> UserModelConfigDto:
    mid = f"{c.id}:{model_slug}"
    repo = _user_config_repo()
    doc = await repo.find(c.user_id, mid)
    if doc:
        return UserModelConfigRepository.to_dto(doc)
    return UserModelConfigRepository.default_dto(mid)


@router.put("/connections/{connection_id}/models/{model_slug:path}/user-config")
async def set_user_model_config(
    model_slug: str,
    body: SetUserModelConfigDto,
    c: ResolvedConnection = Depends(resolve_connection_for_user),
    event_bus: EventBus = Depends(get_event_bus),
) -> UserModelConfigDto:
    mid = f"{c.id}:{model_slug}"
    repo = _user_config_repo()
    # Only pass fields explicitly sent, so nullable fields can be cleared.
    fields = {k: getattr(body, k) for k in body.model_fields_set}
    doc = await repo.upsert(user_id=c.user_id, model_unique_id=mid, fields=fields)
    dto = UserModelConfigRepository.to_dto(doc)
    await event_bus.publish(
        Topics.LLM_USER_MODEL_CONFIG_UPDATED,
        LlmUserModelConfigUpdatedEvent(
            model_unique_id=mid,
            config=dto,
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[c.user_id],
    )
    return dto


@router.delete("/connections/{connection_id}/models/{model_slug:path}/user-config")
async def delete_user_model_config(
    model_slug: str,
    c: ResolvedConnection = Depends(resolve_connection_for_user),
    event_bus: EventBus = Depends(get_event_bus),
) -> UserModelConfigDto:
    mid = f"{c.id}:{model_slug}"
    await _user_config_repo().delete(c.user_id, mid)
    default = UserModelConfigRepository.default_dto(mid)
    await event_bus.publish(
        Topics.LLM_USER_MODEL_CONFIG_UPDATED,
        LlmUserModelConfigUpdatedEvent(
            model_unique_id=mid,
            config=default,
            timestamp=datetime.now(timezone.utc),
        ),
        target_user_ids=[c.user_id],
    )
    return default


# ----- Adapter-specific sub-routers (Task 13) -----


from backend.modules.llm._registry import ADAPTER_REGISTRY as _AR


def _mount_adapter_routers() -> None:
    for adapter_type, cls in _AR.items():
        sub = cls.router()
        if sub is None:
            continue
        router.include_router(
            sub,
            prefix="/connections/{connection_id}/adapter",
            tags=[f"adapter:{adapter_type}"],
        )


_mount_adapter_routers()

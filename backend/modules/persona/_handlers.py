from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response

from backend.database import get_db
from backend.dependencies import require_active_session
from backend.modules.llm import is_valid_provider
from backend.modules.persona._avatar_store import AvatarStore
from backend.modules.persona._monogram import generate_monogram
from backend.modules.persona._repository import PersonaRepository
from backend.ws.event_bus import EventBus, get_event_bus
from shared.dtos.persona import CreatePersonaDto, UpdatePersonaDto
from shared.events.persona import (
    PersonaCreatedEvent,
    PersonaDeletedEvent,
    PersonaUpdatedEvent,
)
from shared.topics import Topics

_ALLOWED_IMAGE_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}
_MAX_AVATAR_SIZE = 5 * 1024 * 1024  # 5 MB

router = APIRouter(prefix="/api/personas")


def _persona_repo() -> PersonaRepository:
    return PersonaRepository(get_db())


def _validate_model_unique_id(model_unique_id: str) -> None:
    """Validate format and that the provider is registered."""
    if ":" not in model_unique_id:
        raise HTTPException(
            status_code=400,
            detail="model_unique_id must be in format 'provider_id:model_slug'",
        )
    provider_id = model_unique_id.split(":", 1)[0]
    if not is_valid_provider(provider_id):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider '{provider_id}' in model_unique_id",
        )


@router.get("")
async def list_personas(user: dict = Depends(require_active_session)):
    repo = _persona_repo()
    docs = await repo.list_for_user(user["sub"])
    return [PersonaRepository.to_dto(d) for d in docs]


@router.post("", status_code=201)
async def create_persona(
    body: CreatePersonaDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    _validate_model_unique_id(body.model_unique_id)

    repo = _persona_repo()
    doc = await repo.create(
        user_id=user["sub"],
        name=body.name,
        tagline=body.tagline,
        model_unique_id=body.model_unique_id,
        system_prompt=body.system_prompt,
        temperature=body.temperature,
        reasoning_enabled=body.reasoning_enabled,
        nsfw=body.nsfw,
        colour_scheme=body.colour_scheme,
        display_order=body.display_order,
    )

    user_id = user["sub"]
    existing_monograms = await repo.list_monograms_for_user(user_id)
    monogram = generate_monogram(body.name, existing_monograms)
    await repo.update(doc["_id"], user_id, {"monogram": monogram})
    doc["monogram"] = monogram

    dto = PersonaRepository.to_dto(doc)
    await event_bus.publish(
        Topics.PERSONA_CREATED,
        PersonaCreatedEvent(
            persona_id=doc["_id"],
            user_id=user["sub"],
            persona=dto,
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"persona:{doc['_id']}",
        target_user_ids=[user["sub"]],
    )

    return dto


@router.patch("/reorder")
async def reorder_personas(
    body: dict,
    user: dict = Depends(require_active_session),
):
    repo = _persona_repo()
    ordered_ids: list[str] = body.get("ordered_ids", [])
    for index, persona_id in enumerate(ordered_ids):
        await repo.update(persona_id, user["sub"], {"display_order": index})
    return {"status": "ok"}


@router.get("/{persona_id}")
async def get_persona(
    persona_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _persona_repo()
    doc = await repo.find_by_id(persona_id, user["sub"])
    if not doc:
        raise HTTPException(status_code=404, detail="Persona not found")
    return PersonaRepository.to_dto(doc)


@router.get("/{persona_id}/system-prompt-preview")
async def get_system_prompt_preview(
    persona_id: str,
    user: dict = Depends(require_active_session),
):
    from backend.modules.chat import assemble_preview  # deferred to avoid circular import

    repo = _persona_repo()
    doc = await repo.find_by_id(persona_id, user["sub"])
    if not doc:
        raise HTTPException(status_code=404, detail="Persona not found")

    preview = await assemble_preview(
        user_id=user["sub"],
        persona_id=persona_id,
        model_unique_id=doc["model_unique_id"],
    )
    return {"preview": preview}


@router.put("/{persona_id}")
async def replace_persona(
    persona_id: str,
    body: CreatePersonaDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    _validate_model_unique_id(body.model_unique_id)

    repo = _persona_repo()
    updated = await repo.update(
        persona_id,
        user["sub"],
        body.model_dump(),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Persona not found")

    existing_monograms = await repo.list_monograms_for_user(
        user["sub"], exclude_persona_id=persona_id,
    )
    monogram = generate_monogram(body.name, existing_monograms)
    await repo.update(persona_id, user["sub"], {"monogram": monogram})
    updated = await repo.find_by_id(persona_id, user["sub"])

    dto = PersonaRepository.to_dto(updated)
    await event_bus.publish(
        Topics.PERSONA_UPDATED,
        PersonaUpdatedEvent(
            persona_id=persona_id,
            user_id=user["sub"],
            persona=dto,
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"persona:{persona_id}",
        target_user_ids=[user["sub"]],
    )

    return dto


@router.patch("/{persona_id}")
async def update_persona(
    persona_id: str,
    body: UpdatePersonaDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    if "model_unique_id" in fields:
        _validate_model_unique_id(fields["model_unique_id"])

    repo = _persona_repo()
    updated = await repo.update(persona_id, user["sub"], fields)
    if not updated:
        raise HTTPException(status_code=404, detail="Persona not found")

    if body.name is not None:
        existing_monograms = await repo.list_monograms_for_user(
            user["sub"], exclude_persona_id=persona_id,
        )
        monogram = generate_monogram(body.name, existing_monograms)
        await repo.update(persona_id, user["sub"], {"monogram": monogram})
        updated["monogram"] = monogram

    dto = PersonaRepository.to_dto(updated)
    await event_bus.publish(
        Topics.PERSONA_UPDATED,
        PersonaUpdatedEvent(
            persona_id=persona_id,
            user_id=user["sub"],
            persona=dto,
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"persona:{persona_id}",
        target_user_ids=[user["sub"]],
    )

    return dto


@router.delete("/{persona_id}")
async def delete_persona(
    persona_id: str,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    repo = _persona_repo()
    deleted = await repo.delete(persona_id, user["sub"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Persona not found")

    await event_bus.publish(
        Topics.PERSONA_DELETED,
        PersonaDeletedEvent(
            persona_id=persona_id,
            user_id=user["sub"],
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"persona:{persona_id}",
        target_user_ids=[user["sub"]],
    )

    return {"status": "ok"}


def _avatar_store() -> AvatarStore:
    return AvatarStore()


@router.post("/{persona_id}/avatar")
async def upload_avatar(
    persona_id: str,
    file: UploadFile,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    content_type = file.content_type or ""
    if content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image type: {content_type}. "
                   f"Allowed: {', '.join(_ALLOWED_IMAGE_TYPES)}",
        )

    data = await file.read()
    if len(data) > _MAX_AVATAR_SIZE:
        raise HTTPException(status_code=400, detail="Avatar must be under 5 MB")

    repo = _persona_repo()
    doc = await repo.find_by_id(persona_id, user["sub"])
    if not doc:
        raise HTTPException(status_code=404, detail="Persona not found")

    store = _avatar_store()

    # Delete old avatar if one exists
    old_image = doc.get("profile_image")
    if old_image:
        store.delete(old_image)

    extension = _ALLOWED_IMAGE_TYPES[content_type]
    filename = store.save(data, extension)

    updated = await repo.update_profile_image(persona_id, user["sub"], filename)
    dto = PersonaRepository.to_dto(updated)

    await event_bus.publish(
        Topics.PERSONA_UPDATED,
        PersonaUpdatedEvent(
            persona_id=persona_id,
            user_id=user["sub"],
            persona=dto,
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"persona:{persona_id}",
        target_user_ids=[user["sub"]],
    )

    return dto


@router.get("/{persona_id}/avatar")
async def get_avatar(
    persona_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _persona_repo()
    doc = await repo.find_by_id(persona_id, user["sub"])
    if not doc:
        raise HTTPException(status_code=404, detail="Persona not found")

    filename = doc.get("profile_image")
    if not filename:
        raise HTTPException(status_code=404, detail="No avatar set")

    store = _avatar_store()
    data = store.load(filename)
    if data is None:
        raise HTTPException(status_code=404, detail="Avatar file not found")

    # Derive content type from file extension
    ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
    ext_to_mime = {v: k for k, v in _ALLOWED_IMAGE_TYPES.items()}
    media_type = ext_to_mime.get(ext, "application/octet-stream")

    return Response(content=data, media_type=media_type)


@router.delete("/{persona_id}/avatar")
async def delete_avatar(
    persona_id: str,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    repo = _persona_repo()
    doc = await repo.find_by_id(persona_id, user["sub"])
    if not doc:
        raise HTTPException(status_code=404, detail="Persona not found")

    filename = doc.get("profile_image")
    if filename:
        store = _avatar_store()
        store.delete(filename)

    updated = await repo.update_profile_image(persona_id, user["sub"], None)
    dto = PersonaRepository.to_dto(updated)

    await event_bus.publish(
        Topics.PERSONA_UPDATED,
        PersonaUpdatedEvent(
            persona_id=persona_id,
            user_id=user["sub"],
            persona=dto,
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"persona:{persona_id}",
        target_user_ids=[user["sub"]],
    )

    return dto

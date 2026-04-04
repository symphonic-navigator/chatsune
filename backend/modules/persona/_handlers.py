from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from backend.database import get_db
from backend.dependencies import require_active_session
from backend.modules.llm import is_valid_provider
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

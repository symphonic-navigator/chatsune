import json
import logging
from datetime import datetime, timezone

_log = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from backend.database import get_db
from backend.dependencies import get_optional_user, require_active_session
from backend.modules.persona._avatar_store import AvatarStore
from backend.modules.persona._cascade import cascade_delete_persona
from backend.modules.persona._export import export_persona_archive
from backend.modules.persona._import import import_persona_archive
from backend.modules.persona._monogram import generate_monogram
from backend.modules.persona._repository import PersonaRepository
from backend.ws.event_bus import EventBus, get_event_bus
from shared.dtos.knowledge import SetKnowledgeLibrariesRequest
from shared.dtos.mcp import PersonaMcpConfig
from shared.dtos.persona import (
    CreatePersonaDto,
    PersonaDto,
    ReorderPersonasDto,
    UpdatePersonaDto,
)
from shared.events.persona import (
    PersonaCreatedEvent,
    PersonaDeletedEvent,
    PersonaReorderedEvent,
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


async def _validate_model_unique_id(user_id: str, model_unique_id: str) -> None:
    """Validate format and that the connection exists and belongs to the user."""
    # Deferred import to avoid circular dependency (llm._handlers -> persona -> llm).
    from backend.modules.llm import resolve_owned_connection

    if ":" not in model_unique_id:
        raise HTTPException(
            status_code=400,
            detail="model_unique_id must be in format 'connection_slug:model_slug'",
        )
    connection_slug = model_unique_id.split(":", 1)[0]
    c = await resolve_owned_connection(user_id, connection_slug)
    if c is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown or unowned connection '{connection_slug}' in model_unique_id",
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
    await _validate_model_unique_id(user["sub"], body.model_unique_id)

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
        soft_cot_enabled=body.soft_cot_enabled,
        vision_fallback_model=body.vision_fallback_model,
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
    body: ReorderPersonasDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    repo = _persona_repo()
    await repo.bulk_reorder(user["sub"], body.ordered_ids)
    await event_bus.publish(
        Topics.PERSONA_REORDERED,
        PersonaReorderedEvent(
            user_id=user["sub"],
            ordered_ids=body.ordered_ids,
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"user:{user['sub']}",
        target_user_ids=[user["sub"]],
    )
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


@router.get("/{persona_id}/knowledge")
async def get_persona_knowledge(
    persona_id: str,
    user: dict = Depends(require_active_session),
):
    repo = _persona_repo()
    doc = await repo.find_by_id(persona_id, user["sub"])
    if not doc:
        raise HTTPException(status_code=404, detail="Persona not found")
    return {"library_ids": doc.get("knowledge_library_ids", [])}


@router.put("/{persona_id}/knowledge")
async def set_persona_knowledge(
    persona_id: str,
    body: SetKnowledgeLibrariesRequest,
    user: dict = Depends(require_active_session),
):
    repo = _persona_repo()
    updated = await repo.update(
        persona_id, user["sub"], {"knowledge_library_ids": body.library_ids},
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Persona not found")
    return {"status": "ok"}


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
    await _validate_model_unique_id(user["sub"], body.model_unique_id)

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
    # vision_fallback_model is explicitly clearable — if the client set it
    # to null, exclude_none would drop it, so we re-include it here.
    if "vision_fallback_model" in body.model_fields_set:
        fields["vision_fallback_model"] = body.vision_fallback_model
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    if "model_unique_id" in fields:
        await _validate_model_unique_id(user["sub"], fields["model_unique_id"])

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


@router.patch("/{persona_id}/mcp")
async def update_persona_mcp(
    persona_id: str,
    body: PersonaMcpConfig,
    user: dict = Depends(require_active_session),
):
    repo = _persona_repo()
    existing = await repo.find_by_id(persona_id, user["sub"])
    if not existing:
        raise HTTPException(status_code=404, detail="Persona not found")

    config_dict = body.model_dump()
    is_empty = (
        not config_dict["excluded_gateways"]
        and not config_dict["excluded_servers"]
        and not config_dict["excluded_tools"]
    )
    await repo.update_mcp_config(persona_id, user["sub"], None if is_empty else config_dict)

    updated = await repo.find_by_id(persona_id, user["sub"])
    return repo.to_dto(updated)


# --- Persona export / import ---------------------------------------------
#
# Archive format is documented in ``_export.py``. The routes live here so the
# module's full HTTP surface is in one place. Orchestration logic is in the
# `_export` / `_import` / `_cascade` helper modules.

# 200 MB hard cap on uploads — mirrors the uncompressed cap inside _import.
_MAX_IMPORT_ARCHIVE_BYTES = 200 * 1024 * 1024


@router.get("/{persona_id}/export")
async def export_persona(
    persona_id: str,
    include_content: bool = Query(
        default=False,
        description=(
            "When true include journal/memory, artefacts and storage files "
            "in the archive. When false only personality + chat history ship."
        ),
    ),
    user: dict = Depends(require_active_session),
):
    """Stream a ``.chatsune-persona.tar.gz`` download for the given persona."""
    archive_bytes, filename = await export_persona_archive(
        user_id=user["sub"],
        persona_id=persona_id,
        include_content=include_content,
    )
    return StreamingResponse(
        iter([archive_bytes]),
        media_type="application/gzip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(archive_bytes)),
        },
    )


@router.post("/import", status_code=201)
async def import_persona(
    file: UploadFile,
    user: dict = Depends(require_active_session),
) -> PersonaDto:
    """Accept a ``.chatsune-persona.tar.gz`` upload and create a new persona."""
    data = await file.read()
    if len(data) > _MAX_IMPORT_ARCHIVE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Archive exceeds 200 MB upload limit",
        )

    return await import_persona_archive(user_id=user["sub"], archive_bytes=data)


@router.delete("/{persona_id}")
async def delete_persona(
    persona_id: str,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    user_id = user["sub"]
    repo = _persona_repo()

    # Verify persona exists and belongs to user
    persona = await repo.find_by_id(persona_id, user_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    # Delegate cascade to the shared helper so the DELETE handler and the
    # import rollback path run the exact same cleanup sequence.
    _deleted, report = await cascade_delete_persona(user_id, persona_id)

    await event_bus.publish(
        Topics.PERSONA_DELETED,
        PersonaDeletedEvent(
            persona_id=persona_id,
            user_id=user_id,
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"persona:{persona_id}",
        target_user_ids=[user_id],
    )

    return report


def _avatar_store() -> AvatarStore:
    return AvatarStore()


@router.post("/{persona_id}/avatar")
async def upload_avatar(
    persona_id: str,
    file: UploadFile,
    crop: str | None = Form(default=None),
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

    # Parse and store crop parameters if provided. The form field is a JSON
    # string because multipart/form-data has no native object type; the same
    # shape is used by the dedicated PATCH /crop endpoint via UpdateAvatarCropRequest.
    crop_dict = None
    if crop:
        try:
            crop_dto = UpdateAvatarCropRequest.model_validate_json(crop)
            crop_dict = crop_dto.model_dump()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid crop payload")
    await repo.update_profile_crop(persona_id, user["sub"], crop_dict)
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


@router.get("/{persona_id}/avatar")
async def get_avatar(
    persona_id: str,
    expires: str | None = None,
    uid: str | None = None,
    sig: str | None = None,
    user: dict | None = Depends(get_optional_user),
):
    # Prefer header auth; fall back to signed URL for <img src>
    if user is None and expires and uid and sig:
        from backend.modules.persona._avatar_url import verify_avatar_signature
        if not verify_avatar_signature(persona_id, uid, expires, sig):
            raise HTTPException(status_code=401, detail="Invalid or expired signature")
        user = {"sub": uid}
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

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


@router.get("/{persona_id}/avatar-url")
async def get_avatar_url(persona_id: str, user: dict = Depends(require_active_session)):
    """Return a short-lived signed URL for embedding the avatar in <img src>."""
    from backend.modules.persona._avatar_url import sign_avatar_url
    params = sign_avatar_url(persona_id, user["sub"])
    return {
        "url": f"/api/personas/{persona_id}/avatar?expires={params['expires']}&uid={params['uid']}&sig={params['sig']}"
    }


class ClonePersonaRequest(BaseModel):
    name: str | None = None
    clone_memory: bool = False


@router.post("/{persona_id}/clone")
async def clone_persona_endpoint(
    persona_id: str,
    body: ClonePersonaRequest,
    user: dict = Depends(require_active_session),
) -> PersonaDto:
    from backend.modules.persona import clone_persona

    return await clone_persona(
        user_id=user["sub"],
        source_id=persona_id,
        name=body.name,
        clone_memory=body.clone_memory,
    )


class UpdateAvatarCropRequest(BaseModel):
    x: float = 0
    y: float = 0
    zoom: float = 1.0
    width: int = 0
    height: int = 0


@router.patch("/{persona_id}/avatar/crop")
async def update_avatar_crop(
    persona_id: str,
    body: UpdateAvatarCropRequest,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    repo = _persona_repo()
    doc = await repo.find_by_id(persona_id, user["sub"])
    if not doc:
        raise HTTPException(status_code=404, detail="Persona not found")

    crop_dict = body.model_dump()
    updated = await repo.update_profile_crop(persona_id, user["sub"], crop_dict)
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
    await repo.update_profile_crop(persona_id, user["sub"], None)
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

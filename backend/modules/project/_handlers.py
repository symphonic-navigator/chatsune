import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from backend.database import get_db
from backend.dependencies import require_active_session
from backend.modules.project._repository import ProjectRepository
from backend.modules.project._service import (
    cascade_delete_project,
    get_usage_counts,
)
from backend.ws.event_bus import EventBus, get_event_bus
from shared.dtos.project import (
    ProjectCreateDto,
    ProjectPinnedDto,
    ProjectUpdateDto,
    _Unset,
)
from shared.events.project import (
    ProjectCreatedEvent,
    ProjectPinnedUpdatedEvent,
    ProjectUpdatedEvent,
)
from shared.topics import Topics

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects")


def _repo() -> ProjectRepository:
    return ProjectRepository(get_db())


@router.get("")
async def list_projects(user: dict = Depends(require_active_session)):
    docs = await _repo().list_for_user(user["sub"])
    return [ProjectRepository.to_dto(d) for d in docs]


@router.get("/{project_id}")
async def get_project(
    project_id: str,
    include_usage: bool = False,
    user: dict = Depends(require_active_session),
):
    """Return a single project. Mindspace: ``include_usage=true`` adds
    a ``usage`` block (``chat_count``, ``upload_count``,
    ``artefact_count``, ``image_count``) used by the delete modal to
    show what a full-purge would remove.
    """
    doc = await _repo().find_by_id(project_id, user["sub"])
    if not doc:
        raise HTTPException(status_code=404, detail="Project not found")
    dto = ProjectRepository.to_dto(doc)
    if not include_usage:
        return dto
    usage = await get_usage_counts(project_id, user["sub"])
    return {**dto.model_dump(mode="json"), "usage": usage.model_dump()}


@router.post("", status_code=201)
async def create_project(
    body: ProjectCreateDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    repo = _repo()
    doc = await repo.create(
        user_id=user["sub"],
        title=body.title,
        emoji=body.emoji,
        description=body.description,
        nsfw=body.nsfw,
        knowledge_library_ids=body.knowledge_library_ids,
        system_prompt=body.system_prompt,
    )
    dto = ProjectRepository.to_dto(doc)
    await event_bus.publish(
        Topics.PROJECT_CREATED,
        ProjectCreatedEvent(
            project_id=doc["_id"],
            user_id=user["sub"],
            project=dto,
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"user:{user['sub']}",
        target_user_ids=[user["sub"]],
    )
    return dto


@router.patch("/{project_id}")
async def update_project(
    project_id: str,
    body: ProjectUpdateDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    fields: dict = {}
    if body.title is not None:
        fields["title"] = body.title
    # Sentinel-aware description handling: UNSET → don't touch; None →
    # clear; str → set. Mindspace aligns this field with the emoji
    # pattern so PATCH callers can explicitly null the description.
    if not isinstance(body.description, _Unset):
        fields["description"] = body.description
    if body.nsfw is not None:
        fields["nsfw"] = body.nsfw
    # Sentinel-aware emoji handling: UNSET → don't touch; None → clear; str → set.
    if not isinstance(body.emoji, _Unset):
        fields["emoji"] = body.emoji
    # Mindspace knowledge libraries: UNSET means leave untouched, an
    # explicit list (including empty) replaces the current value.
    if not isinstance(body.knowledge_library_ids, _Unset):
        fields["knowledge_library_ids"] = list(body.knowledge_library_ids)
    # Sentinel-aware system_prompt handling: UNSET → don't touch;
    # None → clear; str → set. Mirrors the description / emoji pattern.
    if not isinstance(body.system_prompt, _Unset):
        fields["system_prompt"] = body.system_prompt

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    repo = _repo()
    updated = await repo.update(project_id, user["sub"], fields)
    if not updated:
        raise HTTPException(status_code=404, detail="Project not found")

    dto = ProjectRepository.to_dto(updated)
    await event_bus.publish(
        Topics.PROJECT_UPDATED,
        ProjectUpdatedEvent(
            project_id=project_id,
            user_id=user["sub"],
            project=dto,
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"user:{user['sub']}",
        target_user_ids=[user["sub"]],
    )
    return dto


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    purge_data: bool = False,
    user: dict = Depends(require_active_session),
):
    """Cascade-delete a project. Default mode is safe-delete.

    Mindspace spec section 9: ``purge_data=false`` detaches sessions back
    into the global history; ``purge_data=true`` soft-deletes them so the
    existing chat-cleanup job hard-deletes the rest of the per-session
    graph an hour later. PROJECT_DELETED is published by the cascade
    service itself.
    """
    deleted = await cascade_delete_project(
        project_id, user["sub"], purge_data=purge_data,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    return None


@router.patch("/{project_id}/pinned")
async def set_project_pinned(
    project_id: str,
    body: ProjectPinnedDto,
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    """Toggle pinned on a project. Dedicated endpoint per spec section 5.4.

    Fires ``PROJECT_PINNED_UPDATED`` carrying the new boolean so the
    sidebar can re-sort immediately without a full project refresh.
    """
    repo = _repo()
    ok = await repo.set_pinned(project_id, user["sub"], body.pinned)
    if not ok:
        # Either the project does not exist for this user, or its pinned
        # state already matches the requested value (Mongo's
        # ``modified_count`` is 0 in both cases). Disambiguate so the
        # frontend treats a no-op idempotent retry the same as success.
        existing = await repo.find_by_id(project_id, user["sub"])
        if existing is None:
            raise HTTPException(status_code=404, detail="Project not found")

    await event_bus.publish(
        Topics.PROJECT_PINNED_UPDATED,
        ProjectPinnedUpdatedEvent(
            project_id=project_id,
            user_id=user["sub"],
            pinned=body.pinned,
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"user:{user['sub']}",
        target_user_ids=[user["sub"]],
    )
    return {"ok": True}

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from backend.database import get_db
from backend.dependencies import require_active_session
from backend.modules.project._repository import ProjectRepository
from backend.ws.event_bus import EventBus, get_event_bus
from shared.dtos.project import ProjectCreateDto, ProjectUpdateDto, _Unset
from shared.events.project import ProjectCreatedEvent, ProjectDeletedEvent, ProjectUpdatedEvent
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
    user: dict = Depends(require_active_session),
):
    doc = await _repo().find_by_id(project_id, user["sub"])
    if not doc:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectRepository.to_dto(doc)


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
    user: dict = Depends(require_active_session),
    event_bus: EventBus = Depends(get_event_bus),
):
    repo = _repo()
    deleted = await repo.delete(project_id, user["sub"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")

    await event_bus.publish(
        Topics.PROJECT_DELETED,
        ProjectDeletedEvent(
            project_id=project_id,
            user_id=user["sub"],
            timestamp=datetime.now(timezone.utc),
        ),
        scope=f"user:{user['sub']}",
        target_user_ids=[user["sub"]],
    )
    return None

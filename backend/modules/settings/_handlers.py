from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from backend.database import get_db
from backend.dependencies import require_admin
from backend.modules.settings._repository import SettingsRepository
from backend.ws.event_bus import EventBus, get_event_bus
from shared.dtos.settings import SetSettingDto
from shared.events.settings import SettingDeletedEvent, SettingUpdatedEvent
from shared.topics import Topics

router = APIRouter(prefix="/api/settings")


def _repo() -> SettingsRepository:
    return SettingsRepository(get_db())


@router.get("")
async def list_settings(user: dict = Depends(require_admin)):
    repo = _repo()
    docs = await repo.list_all()
    return [SettingsRepository.to_dto(doc) for doc in docs]


@router.get("/{key}")
async def get_setting(key: str, user: dict = Depends(require_admin)):
    repo = _repo()
    doc = await repo.find(key)
    if not doc:
        raise HTTPException(status_code=404, detail="Setting not found")
    return SettingsRepository.to_dto(doc)


@router.put("/{key}", status_code=200)
async def set_setting(
    key: str,
    body: SetSettingDto,
    user: dict = Depends(require_admin),
    event_bus: EventBus = Depends(get_event_bus),
):
    repo = _repo()
    doc = await repo.upsert(key, body.value, user["sub"])

    await event_bus.publish(
        Topics.SETTING_UPDATED,
        SettingUpdatedEvent(
            key=key,
            value=body.value,
            updated_by=user["sub"],
            timestamp=datetime.now(timezone.utc),
        ),
    )

    return SettingsRepository.to_dto(doc)


@router.delete("/{key}", status_code=200)
async def delete_setting(
    key: str,
    user: dict = Depends(require_admin),
    event_bus: EventBus = Depends(get_event_bus),
):
    repo = _repo()
    deleted = await repo.delete(key)
    if not deleted:
        raise HTTPException(status_code=404, detail="Setting not found")

    await event_bus.publish(
        Topics.SETTING_DELETED,
        SettingDeletedEvent(
            key=key,
            deleted_by=user["sub"],
            timestamp=datetime.now(timezone.utc),
        ),
    )

    return {"status": "ok"}

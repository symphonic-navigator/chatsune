import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from shared.dtos.settings import AppSettingDto, SetSettingDto
from shared.events.settings import SettingDeletedEvent, SettingUpdatedEvent
from shared.topics import Topics


def test_app_setting_dto_construction():
    dto = AppSettingDto(
        key="global_system_prompt",
        value="Be helpful and harmless.",
        updated_at="2026-04-03T12:00:00Z",
        updated_by="admin-user-id",
    )
    assert dto.key == "global_system_prompt"
    assert dto.value == "Be helpful and harmless."
    assert dto.updated_by == "admin-user-id"


def test_set_setting_dto_requires_value():
    with pytest.raises(ValidationError):
        SetSettingDto()


def test_set_setting_dto_accepts_value():
    dto = SetSettingDto(value="Be safe.")
    assert dto.value == "Be safe."


def test_setting_updated_event():
    event = SettingUpdatedEvent(
        key="global_system_prompt",
        value="Be helpful.",
        updated_by="admin-id",
        timestamp=datetime.now(timezone.utc),
    )
    assert event.type == "setting.updated"
    assert event.key == "global_system_prompt"


def test_setting_deleted_event():
    event = SettingDeletedEvent(
        key="global_system_prompt",
        deleted_by="admin-id",
        timestamp=datetime.now(timezone.utc),
    )
    assert event.type == "setting.deleted"
    assert event.key == "global_system_prompt"


def test_topics_setting_constants():
    assert Topics.SETTING_UPDATED == "setting.updated"
    assert Topics.SETTING_DELETED == "setting.deleted"

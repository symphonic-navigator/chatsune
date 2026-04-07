from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from shared.topics import Topics


def test_project_topics_exist():
    assert Topics.PROJECT_CREATED == "project.created"
    assert Topics.PROJECT_UPDATED == "project.updated"
    assert Topics.PROJECT_DELETED == "project.deleted"


from shared.dtos.project import (
    UNSET,
    ProjectCreateDto,
    ProjectDto,
    ProjectUpdateDto,
)


def test_project_dto_round_trip():
    now = datetime.now(timezone.utc)
    dto = ProjectDto(
        id="p1",
        user_id="u1",
        title="My Project",
        emoji="🔥",
        description="notes",
        nsfw=False,
        pinned=False,
        sort_order=0,
        created_at=now,
        updated_at=now,
    )
    assert dto.title == "My Project"
    assert dto.emoji == "🔥"


def test_create_dto_defaults():
    dto = ProjectCreateDto(title="Hi")
    assert dto.emoji is None
    assert dto.description == ""
    assert dto.nsfw is False


def test_create_dto_rejects_blank_title():
    with pytest.raises(ValidationError):
        ProjectCreateDto(title="   ")


def test_create_dto_rejects_long_title():
    with pytest.raises(ValidationError):
        ProjectCreateDto(title="x" * 81)


def test_create_dto_rejects_multi_grapheme_emoji():
    with pytest.raises(ValidationError):
        ProjectCreateDto(title="ok", emoji="🔥🔥")


def test_create_dto_accepts_compound_grapheme_emoji():
    # Family emoji is multiple codepoints but a single grapheme.
    dto = ProjectCreateDto(title="ok", emoji="👨‍👩‍👧")
    assert dto.emoji == "👨‍👩‍👧"


def test_create_dto_rejects_long_description():
    with pytest.raises(ValidationError):
        ProjectCreateDto(title="ok", description="x" * 2001)


def test_update_dto_emoji_unset_by_default():
    dto = ProjectUpdateDto()
    assert dto.emoji is UNSET


def test_update_dto_emoji_explicit_none_means_clear():
    dto = ProjectUpdateDto.model_validate({"emoji": None})
    assert dto.emoji is None


def test_update_dto_emoji_string_value():
    dto = ProjectUpdateDto.model_validate({"emoji": "✏️"})
    assert dto.emoji == "✏️"


from shared.events.project import (
    ProjectCreatedEvent,
    ProjectDeletedEvent,
    ProjectUpdatedEvent,
)


def _sample_dto() -> ProjectDto:
    now = datetime.now(timezone.utc)
    return ProjectDto(
        id="p1",
        user_id="u1",
        title="x",
        emoji=None,
        description="",
        nsfw=False,
        pinned=False,
        sort_order=0,
        created_at=now,
        updated_at=now,
    )


def test_project_created_event():
    ev = ProjectCreatedEvent(
        project_id="p1",
        user_id="u1",
        project=_sample_dto(),
        timestamp=datetime.now(timezone.utc),
    )
    assert ev.type == "project.created"
    assert ev.project.id == "p1"


def test_project_updated_event():
    ev = ProjectUpdatedEvent(
        project_id="p1",
        user_id="u1",
        project=_sample_dto(),
        timestamp=datetime.now(timezone.utc),
    )
    assert ev.type == "project.updated"


def test_project_deleted_event():
    ev = ProjectDeletedEvent(
        project_id="p1",
        user_id="u1",
        timestamp=datetime.now(timezone.utc),
    )
    assert ev.type == "project.deleted"

"""Mindspace Phase 1 — additive fields on the ProjectDocument.

These tests cover the new ``knowledge_library_ids`` and ``description``
fields added for the Mindspace (Projects) feature. Both must default
sensibly so that pre-Mindspace project documents continue to deserialise
without the database needing a migration.
"""

from datetime import datetime, timezone

import pytest
import pytest_asyncio

from backend.database import connect_db, disconnect_db, get_db
from backend.modules.project import ProjectRepository
from shared.dtos.project import (
    ProjectCreateDto,
    ProjectDto,
    ProjectUpdateDto,
    UNSET,
)


@pytest_asyncio.fixture
async def repo(clean_db):
    await connect_db()
    r = ProjectRepository(get_db())
    # Drop the projects collection up front: clean_db cleans the URI's
    # default database whereas get_db resolves to ``settings.mongo_db_name``,
    # so leftover state from earlier runs/tests can contaminate the
    # collection. This guard is local to the new tests.
    await r._collection.drop()  # noqa: SLF001 — test setup
    await r.create_indexes()
    yield r
    await r._collection.drop()  # noqa: SLF001 — test teardown
    await disconnect_db()


# ---------------------------------------------------------------------------
# DTO defaults — pure-Pydantic, no DB.
# ---------------------------------------------------------------------------


def test_project_dto_defaults_for_new_fields():
    dto = ProjectDto(
        id="p1",
        user_id="u1",
        title="P",
        emoji=None,
        description=None,
        nsfw=False,
        pinned=False,
        sort_order=0,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    # New field defaults to empty list.
    assert dto.knowledge_library_ids == []
    # Description is now optional / nullable.
    assert dto.description is None


def test_project_create_dto_accepts_knowledge_library_ids():
    dto = ProjectCreateDto(title="P", knowledge_library_ids=["L1", "L2"])
    assert dto.knowledge_library_ids == ["L1", "L2"]
    # Default when omitted.
    dto2 = ProjectCreateDto(title="P")
    assert dto2.knowledge_library_ids == []


def test_project_update_dto_unset_default_for_new_fields():
    dto = ProjectUpdateDto()
    # Both fields use the UNSET sentinel by default so a PATCH that
    # omits them is distinguishable from one that explicitly clears
    # them.
    assert dto.knowledge_library_ids is UNSET
    assert dto.description is UNSET


def test_project_update_dto_can_set_knowledge_library_ids():
    dto = ProjectUpdateDto(knowledge_library_ids=["A", "B"])
    assert dto.knowledge_library_ids == ["A", "B"]


def test_project_update_dto_description_explicit_none_clears():
    dto = ProjectUpdateDto(description=None)
    # Explicit None means "clear", not "unset".
    assert dto.description is None
    assert dto.description is not UNSET


# ---------------------------------------------------------------------------
# Repository — write + read + legacy-doc tolerance.
# ---------------------------------------------------------------------------


async def test_repo_persists_and_reads_knowledge_library_ids(
    repo: ProjectRepository,
):
    doc = await repo.create(
        user_id="u1",
        title="P",
        emoji=None,
        description="hi",
        nsfw=False,
        knowledge_library_ids=["L1", "L2"],
    )
    fetched = await repo.find_by_id(doc["_id"], "u1")
    assert fetched is not None
    assert fetched.get("knowledge_library_ids") == ["L1", "L2"]
    assert fetched.get("description") == "hi"


async def test_repo_create_defaults_knowledge_library_ids_empty(
    repo: ProjectRepository,
):
    doc = await repo.create(
        user_id="u1",
        title="P",
        emoji=None,
        description="",
        nsfw=False,
    )
    assert doc.get("knowledge_library_ids") == []


async def test_legacy_project_doc_reads_with_defaults(
    repo: ProjectRepository,
):
    """Pre-Mindspace project documents lack the new fields and may carry
    a legacy ``display_order`` field. The to_dto mapper must tolerate
    both: missing new fields fall back to defaults, legacy fields are
    silently ignored."""
    from uuid import uuid4

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    legacy_id = f"legacy-{uuid4().hex[:8]}"
    legacy_doc = {
        "_id": legacy_id,
        "user_id": "u1",
        "title": "old",
        "emoji": None,
        "nsfw": False,
        "pinned": False,
        # legacy field — must not break anything; spec §4.1 ignores it.
        "display_order": 7,
        # ``description`` is intentionally absent on legacy docs.
        "created_at": now,
        "updated_at": now,
    }
    await repo._collection.insert_one(legacy_doc)  # noqa: SLF001 — test inspects internals

    fetched = await repo.find_by_id(legacy_id, "u1")
    assert fetched is not None
    dto = ProjectRepository.to_dto(fetched)
    # New field defaults.
    assert dto.knowledge_library_ids == []
    # Mindspace contract: ``description`` is now nullable, and a legacy
    # doc that lacks the field must read as ``None`` (the new model
    # default), not ``""``. Pin the assertion exactly so a future change
    # that silently coerces missing → ``""`` would fail loudly.
    assert dto.description is None

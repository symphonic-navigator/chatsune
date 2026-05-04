"""Mindspace Phase 1 — additive ``default_project_id`` field on personas.

A persona may carry a single optional default project. ``None`` is the
legacy / unassigned state; pre-Mindspace persona documents lack the
field entirely and must deserialise as ``None``.

The corresponding update DTO carries the field as ``str | None = None``
and the existing persona PATCH handler distinguishes 'omitted' from
'explicit null' via ``model_fields_set`` — same idiom that already
covers ``vision_fallback_model``.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest_asyncio

from backend.database import connect_db, disconnect_db, get_db
from backend.modules.persona._models import PersonaDocument
from backend.modules.persona._repository import PersonaRepository
from shared.dtos.persona import PersonaDto, UpdatePersonaDto


@pytest_asyncio.fixture
async def repo(clean_db):
    await connect_db()
    r = PersonaRepository(get_db())
    await r._collection.drop()  # noqa: SLF001 — test setup
    await r.create_indexes()
    yield r
    await r._collection.drop()  # noqa: SLF001 — test teardown
    await disconnect_db()


# ---------------------------------------------------------------------------
# DTO / model defaults — pure-Pydantic, no DB.
# ---------------------------------------------------------------------------


def _persona_dto_payload(**overrides):
    base = dict(
        id="p1",
        user_id="u1",
        name="Worf",
        tagline="Klingon security officer",
        model_unique_id=None,
        system_prompt="...",
        temperature=0.8,
        reasoning_enabled=False,
        nsfw=False,
        colour_scheme="solar",
        display_order=0,
        monogram="WF",
        pinned=False,
        profile_image=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return base


def test_persona_dto_default_project_id_is_none():
    dto = PersonaDto(**_persona_dto_payload())
    assert dto.default_project_id is None


def test_persona_dto_accepts_default_project_id():
    dto = PersonaDto(**_persona_dto_payload(default_project_id="proj-9"))
    assert dto.default_project_id == "proj-9"


def test_persona_document_default_project_id_is_none():
    now = datetime.now(timezone.utc)
    doc = PersonaDocument(
        _id="p1",
        user_id="u1",
        name="Worf",
        tagline="x",
        system_prompt="...",
        temperature=0.8,
        reasoning_enabled=False,
        nsfw=False,
        colour_scheme="solar",
        display_order=0,
        monogram="WF",
        pinned=False,
        profile_image=None,
        created_at=now,
        updated_at=now,
    )
    assert doc.default_project_id is None


def test_update_persona_dto_default_project_id_omitted_means_unset():
    """Caller did not include the field at all; ``model_fields_set`` must
    not contain it so the handler leaves the persistent value alone."""
    dto = UpdatePersonaDto()
    assert "default_project_id" not in dto.model_fields_set


def test_update_persona_dto_default_project_id_explicit_none_is_set():
    """Explicit ``null`` clears the persona's default project. The
    handler distinguishes this from 'omitted' via ``model_fields_set``,
    mirroring the existing ``vision_fallback_model`` idiom."""
    dto = UpdatePersonaDto(default_project_id=None)
    assert "default_project_id" in dto.model_fields_set
    assert dto.default_project_id is None


def test_update_persona_dto_default_project_id_set_to_value():
    dto = UpdatePersonaDto(default_project_id="proj-42")
    assert "default_project_id" in dto.model_fields_set
    assert dto.default_project_id == "proj-42"


# ---------------------------------------------------------------------------
# Repository — legacy (pre-Mindspace) persona docs deserialise with None.
# ---------------------------------------------------------------------------


async def test_legacy_persona_default_project_id_is_none(repo: PersonaRepository):
    """Insert a raw pre-Mindspace persona document (no
    ``default_project_id``) and verify ``to_dto`` defaults to ``None``."""
    pid = f"legacy-{uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    legacy_doc = {
        "_id": pid,
        "user_id": "u1",
        "name": "Old",
        "tagline": "x",
        "model_unique_id": None,
        "system_prompt": "...",
        "temperature": 0.8,
        "reasoning_enabled": False,
        "nsfw": False,
        "use_memory": True,
        "colour_scheme": "solar",
        "display_order": 0,
        "monogram": "OL",
        "pinned": False,
        "profile_image": None,
        "created_at": now,
        "updated_at": now,
    }
    await repo._collection.insert_one(legacy_doc)  # noqa: SLF001 — test seed
    fetched = await repo.find_by_id(pid, "u1")
    assert fetched is not None
    dto = PersonaRepository.to_dto(fetched)
    assert dto.default_project_id is None


async def test_persona_with_default_project_round_trips(repo: PersonaRepository):
    pid = f"new-{uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    new_doc = {
        "_id": pid,
        "user_id": "u1",
        "name": "New",
        "tagline": "x",
        "model_unique_id": None,
        "system_prompt": "...",
        "temperature": 0.8,
        "reasoning_enabled": False,
        "nsfw": False,
        "use_memory": True,
        "colour_scheme": "solar",
        "display_order": 0,
        "monogram": "NW",
        "pinned": False,
        "profile_image": None,
        "default_project_id": "proj-77",
        "created_at": now,
        "updated_at": now,
    }
    await repo._collection.insert_one(new_doc)  # noqa: SLF001 — test seed
    fetched = await repo.find_by_id(pid, "u1")
    assert fetched is not None
    dto = PersonaRepository.to_dto(fetched)
    assert dto.default_project_id == "proj-77"

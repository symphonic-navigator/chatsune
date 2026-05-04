"""Mindspace Phase 1 — additive ``project_id`` field on chat sessions.

A chat session may belong to at most one project. The field defaults
to ``None`` so pre-Mindspace sessions deserialise without a migration.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest_asyncio

from backend.database import connect_db, disconnect_db, get_db
from backend.modules.chat._models import ChatSessionDocument
from backend.modules.chat._repository import ChatRepository
from shared.dtos.chat import ChatSessionDto


@pytest_asyncio.fixture
async def repo(clean_db):
    await connect_db()
    r = ChatRepository(get_db())
    # Local cleanup — see notes in test_project_mindspace_fields.py
    # (the repo-level fixture targets a different DB than clean_db
    # touches, so we drop the session collection ourselves).
    await r._sessions.drop()  # noqa: SLF001 — test setup
    await r.create_indexes()
    yield r
    await r._sessions.drop()  # noqa: SLF001 — test teardown
    await disconnect_db()


# ---------------------------------------------------------------------------
# Pure-DTO / model assertions — no DB.
# ---------------------------------------------------------------------------


def test_chat_session_dto_default_project_id_is_none():
    dto = ChatSessionDto(
        id="s1",
        user_id="u1",
        persona_id="p1",
        state="idle",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    assert dto.project_id is None


def test_chat_session_dto_accepts_project_id():
    dto = ChatSessionDto(
        id="s1",
        user_id="u1",
        persona_id="p1",
        state="idle",
        project_id="proj-42",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    assert dto.project_id == "proj-42"


def test_chat_session_document_default_project_id_is_none():
    now = datetime.now(timezone.utc)
    doc = ChatSessionDocument(
        _id="s1",
        user_id="u1",
        persona_id="p1",
        created_at=now,
        updated_at=now,
    )
    assert doc.project_id is None


# ---------------------------------------------------------------------------
# Repository — legacy (pre-Mindspace) docs deserialise as project_id=None.
# ---------------------------------------------------------------------------


async def test_legacy_session_reads_project_id_as_none(repo: ChatRepository):
    """Insert a raw pre-Mindspace session document (no ``project_id``
    field at all) and verify the to-DTO mapper defaults to ``None``."""
    sid = f"legacy-{uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    await repo._sessions.insert_one(  # noqa: SLF001 — test seed
        {
            "_id": sid,
            "user_id": "u1",
            "persona_id": "per1",
            "state": "idle",
            "created_at": now,
            "updated_at": now,
            "deleted_at": None,
        },
    )
    fetched = await repo.get_session(sid, "u1")
    assert fetched is not None
    dto = ChatRepository.session_to_dto(fetched)
    assert dto.project_id is None


async def test_session_with_project_id_round_trips(repo: ChatRepository):
    sid = f"new-{uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    await repo._sessions.insert_one(  # noqa: SLF001 — test seed
        {
            "_id": sid,
            "user_id": "u1",
            "persona_id": "per1",
            "state": "idle",
            "project_id": "proj-77",
            "created_at": now,
            "updated_at": now,
            "deleted_at": None,
        },
    )
    fetched = await repo.get_session(sid, "u1")
    assert fetched is not None
    assert fetched.get("project_id") == "proj-77"
    dto = ChatRepository.session_to_dto(fetched)
    assert dto.project_id == "proj-77"

"""Mindspace Phase 1 — additive ``recent_project_emojis`` field on users.

The Mindspace project emoji-picker uses an LRU separate from the
chat-message emoji LRU (``recent_emojis``). The new field defaults to
empty so legacy user documents read back without a migration.

Phase 1 only introduces the field on the document, the DTO and the
to-DTO mapper. The endpoint that mutates it is wired up in a later
phase.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest_asyncio

from backend.database import connect_db, disconnect_db, get_db
from backend.modules.user._models import UserDocument
from backend.modules.user._repository import UserRepository
from shared.dtos.auth import UserDto


@pytest_asyncio.fixture
async def repo(clean_db):
    await connect_db()
    r = UserRepository(get_db())
    await r._collection.drop()  # noqa: SLF001 — test setup
    await r.create_indexes()
    yield r
    await r._collection.drop()  # noqa: SLF001 — test teardown
    await disconnect_db()


# ---------------------------------------------------------------------------
# DTO defaults — pure-Pydantic, no DB.
# ---------------------------------------------------------------------------


def test_user_dto_default_recent_project_emojis_is_empty():
    dto = UserDto(
        id="u1",
        username="alice",
        email="a@example.com",
        display_name="Alice",
        role="user",
        is_active=True,
        must_change_password=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    assert dto.recent_project_emojis == []


def test_user_dto_accepts_recent_project_emojis():
    dto = UserDto(
        id="u1",
        username="alice",
        email="a@example.com",
        display_name="Alice",
        role="user",
        is_active=True,
        must_change_password=False,
        recent_project_emojis=["✨", "🎼", "🪐"],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    assert dto.recent_project_emojis == ["✨", "🎼", "🪐"]


def test_user_document_default_recent_project_emojis_is_empty():
    doc = UserDocument(
        _id="u1",
        username="alice",
        email="a@example.com",
        display_name="Alice",
        password_hash="x",
        role="user",
    )
    # Default factory yields an empty list — distinct from
    # ``recent_emojis`` which seeds with the chat-message defaults.
    assert doc.recent_project_emojis == []


# ---------------------------------------------------------------------------
# Repository — legacy user docs deserialise as empty list.
# ---------------------------------------------------------------------------


async def test_legacy_user_recent_project_emojis_defaults_empty(
    repo: UserRepository,
):
    """Insert a raw pre-Mindspace user document (no
    ``recent_project_emojis``) and verify ``to_dto`` defaults to ``[]``."""
    uid = f"legacy-{uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    await repo._collection.insert_one(  # noqa: SLF001 — test seed
        {
            "_id": uid,
            "username": f"u-{uid[-8:]}",
            "email": f"{uid[-8:]}@example.com",
            "display_name": "Legacy",
            "password_hash": "x",
            "role": "user",
            "is_active": True,
            "must_change_password": False,
            "created_at": now,
            "updated_at": now,
        },
    )
    fetched = await repo._collection.find_one({"_id": uid})  # noqa: SLF001
    assert fetched is not None
    dto = UserRepository.to_dto(fetched)
    assert dto.recent_project_emojis == []


async def test_user_with_recent_project_emojis_round_trips(repo: UserRepository):
    uid = f"new-{uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    await repo._collection.insert_one(  # noqa: SLF001 — test seed
        {
            "_id": uid,
            "username": f"u-{uid[-8:]}",
            "email": f"{uid[-8:]}@example.com",
            "display_name": "Alice",
            "password_hash": "x",
            "role": "user",
            "is_active": True,
            "must_change_password": False,
            "recent_project_emojis": ["✨", "🎼"],
            "created_at": now,
            "updated_at": now,
        },
    )
    fetched = await repo._collection.find_one({"_id": uid})  # noqa: SLF001
    dto = UserRepository.to_dto(fetched)
    assert dto.recent_project_emojis == ["✨", "🎼"]

"""Mindspace Phase 1 — three new compound indexes (spec §4.5).

| Collection      | Index                                          |
|-----------------|------------------------------------------------|
| chat_sessions   | [user_id, project_id, updated_at desc]         |
| projects        | [user_id, pinned desc, updated_at desc]        |
| personas        | sparse [user_id, default_project_id]           |

The new indexes are added to each module's existing
``create_indexes`` async method (declarative + idempotent — calling
twice must not raise).
"""

import pytest_asyncio

from backend.database import connect_db, disconnect_db, get_db
from backend.modules.chat._repository import ChatRepository
from backend.modules.persona._repository import PersonaRepository
from backend.modules.project._repository import ProjectRepository


def _index_keys(info: dict) -> list[tuple[str, int]]:
    """Return the index keys as a list of (field, direction) tuples
    that match how pymongo records compound indexes. ``key`` may be a
    list of tuples (compound) or a dict-like (simple) — normalise."""
    raw = info["key"]
    if isinstance(raw, dict):
        return list(raw.items())
    return [tuple(pair) for pair in raw]


def _has_index_with_keys(
    indexes: dict, keys: list[tuple[str, int]],
) -> bool:
    target = list(keys)
    for info in indexes.values():
        if _index_keys(info) == target:
            return True
    return False


def _find_index_by_keys(
    indexes: dict, keys: list[tuple[str, int]],
) -> dict | None:
    target = list(keys)
    for info in indexes.values():
        if _index_keys(info) == target:
            return info
    return None


# ---------------------------------------------------------------------------
# chat_sessions: [user_id asc, project_id asc, updated_at desc]
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def chat_repo(clean_db):
    await connect_db()
    r = ChatRepository(get_db())
    await r._sessions.drop()  # noqa: SLF001
    await r._messages.drop()  # noqa: SLF001
    await r.create_indexes()
    yield r
    await disconnect_db()


async def test_chat_sessions_user_project_updated_index_present(chat_repo):
    indexes = await chat_repo._sessions.index_information()  # noqa: SLF001
    assert _has_index_with_keys(
        indexes, [("user_id", 1), ("project_id", 1), ("updated_at", -1)],
    ), f"missing index, got: {indexes}"


async def test_chat_create_indexes_is_idempotent(chat_repo):
    # Calling twice must not raise (Mongo's create_index is idempotent
    # when the spec matches; this guards against accidental duplicate
    # named indexes).
    await chat_repo.create_indexes()
    await chat_repo.create_indexes()


# ---------------------------------------------------------------------------
# projects: [user_id asc, pinned desc, updated_at desc]
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def project_repo(clean_db):
    await connect_db()
    r = ProjectRepository(get_db())
    await r._collection.drop()  # noqa: SLF001
    await r.create_indexes()
    yield r
    await disconnect_db()


async def test_projects_user_pinned_updated_index_present(project_repo):
    indexes = await project_repo._collection.index_information()  # noqa: SLF001
    assert _has_index_with_keys(
        indexes, [("user_id", 1), ("pinned", -1), ("updated_at", -1)],
    ), f"missing index, got: {indexes}"


async def test_projects_create_indexes_is_idempotent(project_repo):
    await project_repo.create_indexes()
    await project_repo.create_indexes()


# ---------------------------------------------------------------------------
# personas: sparse [user_id asc, default_project_id asc]
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def persona_repo(clean_db):
    await connect_db()
    r = PersonaRepository(get_db())
    await r._collection.drop()  # noqa: SLF001
    await r.create_indexes()
    yield r
    await disconnect_db()


async def test_personas_user_default_project_index_present_and_sparse(persona_repo):
    indexes = await persona_repo._collection.index_information()  # noqa: SLF001
    info = _find_index_by_keys(
        indexes, [("user_id", 1), ("default_project_id", 1)],
    )
    assert info is not None, f"missing index, got: {indexes}"
    # Sparse — only documents that carry ``default_project_id`` are
    # indexed. Saves space on the (likely majority) personas with no
    # default project assigned.
    assert info.get("sparse") is True, f"expected sparse=True, got: {info}"


async def test_personas_create_indexes_is_idempotent(persona_repo):
    await persona_repo.create_indexes()
    await persona_repo.create_indexes()

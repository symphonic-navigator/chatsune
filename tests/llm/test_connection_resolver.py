"""Regression tests for ``resolve_connection_for_user``.

Per INS-019 the path parameter on ``/api/llm/connections/{connection_id}/...``
may carry either the Connection ``_id`` (UUID, used by the Model Browser /
favourites flow) or the Connection ``slug`` (used when the Frontend splits a
``model_unique_id`` of the form ``<connection_slug>:<model_slug>``). Both
must resolve, both must respect per-user scoping, and a non-matching value
must produce a 404.
"""

import pytest
from fastapi import HTTPException

from backend.modules.llm import _resolver as resolver_mod
from backend.modules.llm._connections import ConnectionRepository


@pytest.mark.asyncio
async def test_resolves_by_id(mock_db, monkeypatch):
    monkeypatch.setattr(resolver_mod, "get_db", lambda: mock_db)
    repo = ConnectionRepository(mock_db)
    await repo.create_indexes()
    conn = await repo.create("u1", "ollama_http", "Ollama", "ollama-local", {"url": "http://x"})

    resolved = await resolver_mod.resolve_connection_for_user(
        connection_id=conn["_id"], user={"sub": "u1"},
    )
    assert resolved.id == conn["_id"]
    assert resolved.slug == "ollama-local"


@pytest.mark.asyncio
async def test_resolves_by_slug(mock_db, monkeypatch):
    monkeypatch.setattr(resolver_mod, "get_db", lambda: mock_db)
    repo = ConnectionRepository(mock_db)
    await repo.create_indexes()
    conn = await repo.create("u1", "ollama_http", "Ollama", "ollama-local", {"url": "http://x"})

    resolved = await resolver_mod.resolve_connection_for_user(
        connection_id="ollama-local", user={"sub": "u1"},
    )
    assert resolved.id == conn["_id"]
    assert resolved.slug == "ollama-local"


@pytest.mark.asyncio
async def test_unknown_value_raises_404(mock_db, monkeypatch):
    monkeypatch.setattr(resolver_mod, "get_db", lambda: mock_db)
    repo = ConnectionRepository(mock_db)
    await repo.create_indexes()
    await repo.create("u1", "ollama_http", "Ollama", "ollama-local", {"url": "http://x"})

    with pytest.raises(HTTPException) as exc:
        await resolver_mod.resolve_connection_for_user(
            connection_id="does-not-exist", user={"sub": "u1"},
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_slug_of_other_user_does_not_resolve(mock_db, monkeypatch):
    """Slug uniqueness is per-user — a slug owned by user B must not be
    resolvable for user A even though the value happens to match."""
    monkeypatch.setattr(resolver_mod, "get_db", lambda: mock_db)
    repo = ConnectionRepository(mock_db)
    await repo.create_indexes()
    await repo.create("user-b", "ollama_http", "Ollama", "shared-name", {"url": "http://x"})

    with pytest.raises(HTTPException) as exc:
        await resolver_mod.resolve_connection_for_user(
            connection_id="shared-name", user={"sub": "user-a"},
        )
    assert exc.value.status_code == 404

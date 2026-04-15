"""Tests for ConnectionRepository.update slug-rename cascade.

When a connection slug is renamed, the model_unique_id field on both
``personas`` and ``llm_user_model_configs`` must be updated atomically
for the owning user only.
"""

import pytest
import pytest_asyncio

from backend.modules.llm._connections import ConnectionRepository


@pytest.mark.asyncio
async def test_slug_rename_cascades_to_personas_and_configs(mock_db):
    repo = ConnectionRepository(mock_db)
    await repo.create_indexes()
    user_id = "u1"
    conn = await repo.create(user_id, "ollama_http", "Ollama", "old-slug", {"url": "http://x"})

    await mock_db["personas"].insert_one({"_id": "p1", "user_id": user_id,
                                          "model_unique_id": "old-slug:llama3.3"})
    await mock_db["llm_user_model_configs"].insert_one({"_id": "c1", "user_id": user_id,
                                                        "model_unique_id": "old-slug:llama3.3",
                                                        "is_favourite": True})

    await repo.update(user_id, conn["_id"], slug="new-slug")

    p = await mock_db["personas"].find_one({"_id": "p1"})
    c = await mock_db["llm_user_model_configs"].find_one({"_id": "c1"})
    assert p["model_unique_id"] == "new-slug:llama3.3"
    assert c["model_unique_id"] == "new-slug:llama3.3"


@pytest.mark.asyncio
async def test_slug_rename_does_not_touch_other_users(mock_db):
    repo = ConnectionRepository(mock_db)
    await repo.create_indexes()
    my_uid, other_uid = "u1", "u2"
    conn = await repo.create(my_uid, "ollama_http", "Mine", "shared-name", {"url": "http://x"})
    await mock_db["personas"].insert_one({"_id": "p-other", "user_id": other_uid,
                                          "model_unique_id": "shared-name:llama3.3"})

    await repo.update(my_uid, conn["_id"], slug="renamed")

    other = await mock_db["personas"].find_one({"_id": "p-other"})
    assert other["model_unique_id"] == "shared-name:llama3.3"


@pytest.mark.asyncio
async def test_non_slug_update_does_not_cascade(mock_db):
    repo = ConnectionRepository(mock_db)
    await repo.create_indexes()
    user_id = "u1"
    conn = await repo.create(user_id, "ollama_http", "Ollama", "stable-slug", {"url": "http://x"})
    await mock_db["personas"].insert_one({"_id": "p1", "user_id": user_id,
                                          "model_unique_id": "stable-slug:llama3.3"})

    await repo.update(user_id, conn["_id"], display_name="Renamed Display")

    p = await mock_db["personas"].find_one({"_id": "p1"})
    assert p["model_unique_id"] == "stable-slug:llama3.3"


@pytest.mark.asyncio
async def test_same_slug_update_does_not_cascade(mock_db):
    """Passing the same slug as already set must not trigger cascade (no-op)."""
    repo = ConnectionRepository(mock_db)
    await repo.create_indexes()
    user_id = "u1"
    conn = await repo.create(user_id, "ollama_http", "Ollama", "stable-slug", {"url": "http://x"})
    await mock_db["personas"].insert_one({"_id": "p1", "user_id": user_id,
                                          "model_unique_id": "stable-slug:llama3.3"})

    await repo.update(user_id, conn["_id"], slug="stable-slug")

    p = await mock_db["personas"].find_one({"_id": "p1"})
    assert p["model_unique_id"] == "stable-slug:llama3.3"

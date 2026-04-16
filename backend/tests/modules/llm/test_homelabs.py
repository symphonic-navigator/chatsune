import pytest

from backend.modules.llm._homelab_tokens import (
    HOST_KEY_PREFIX,
    hash_token,
    hint_for,
)
from backend.modules.llm._homelabs import (
    HomelabNotFoundError,
    HomelabRepository,
    TooManyHomelabsError,
)


@pytest.mark.asyncio
async def test_create_homelab_returns_plaintext_key_once(test_db):
    repo = HomelabRepository(test_db)
    await repo.create_indexes()
    homelab, plaintext = await repo.create(user_id="u1", display_name="Wohnzimmer-GPU")
    assert plaintext.startswith(HOST_KEY_PREFIX)
    assert homelab["display_name"] == "Wohnzimmer-GPU"
    assert homelab["user_id"] == "u1"
    assert homelab["status"] == "active"
    assert homelab["host_key_hash"] == hash_token(plaintext)
    assert homelab["host_key_hint"] == hint_for(plaintext)
    assert "plaintext" not in homelab


@pytest.mark.asyncio
async def test_list_returns_only_owner_homelabs(test_db):
    repo = HomelabRepository(test_db)
    await repo.create_indexes()
    await repo.create(user_id="u1", display_name="A")
    await repo.create(user_id="u1", display_name="B")
    await repo.create(user_id="u2", display_name="C")
    out = await repo.list(user_id="u1")
    assert [h["display_name"] for h in out] == ["A", "B"]


@pytest.mark.asyncio
async def test_get_by_homelab_id_scoped_to_user(test_db):
    repo = HomelabRepository(test_db)
    await repo.create_indexes()
    homelab, _ = await repo.create(user_id="u1", display_name="A")
    got = await repo.get(user_id="u1", homelab_id=homelab["homelab_id"])
    assert got["display_name"] == "A"
    with pytest.raises(HomelabNotFoundError):
        await repo.get(user_id="u2", homelab_id=homelab["homelab_id"])


@pytest.mark.asyncio
async def test_rename(test_db):
    repo = HomelabRepository(test_db)
    await repo.create_indexes()
    homelab, _ = await repo.create(user_id="u1", display_name="A")
    updated = await repo.rename(
        user_id="u1", homelab_id=homelab["homelab_id"], display_name="B"
    )
    assert updated["display_name"] == "B"


@pytest.mark.asyncio
async def test_delete(test_db):
    repo = HomelabRepository(test_db)
    await repo.create_indexes()
    homelab, _ = await repo.create(user_id="u1", display_name="A")
    await repo.delete(user_id="u1", homelab_id=homelab["homelab_id"])
    with pytest.raises(HomelabNotFoundError):
        await repo.get(user_id="u1", homelab_id=homelab["homelab_id"])


@pytest.mark.asyncio
async def test_regenerate_host_key_updates_hash_and_returns_new_plaintext(test_db):
    repo = HomelabRepository(test_db)
    await repo.create_indexes()
    homelab, plaintext = await repo.create(user_id="u1", display_name="A")
    new_homelab, new_plaintext = await repo.regenerate_host_key(
        user_id="u1", homelab_id=homelab["homelab_id"]
    )
    assert new_plaintext != plaintext
    assert new_homelab["host_key_hash"] == hash_token(new_plaintext)


@pytest.mark.asyncio
async def test_find_by_host_key_hash(test_db):
    repo = HomelabRepository(test_db)
    await repo.create_indexes()
    homelab, plaintext = await repo.create(user_id="u1", display_name="A")
    found = await repo.find_by_host_key_hash(hash_token(plaintext))
    assert found["homelab_id"] == homelab["homelab_id"]
    assert await repo.find_by_host_key_hash("nope") is None


@pytest.mark.asyncio
async def test_sanity_cap_on_create(test_db):
    repo = HomelabRepository(test_db, max_per_user=2)
    await repo.create_indexes()
    await repo.create(user_id="u1", display_name="A")
    await repo.create(user_id="u1", display_name="B")
    with pytest.raises(TooManyHomelabsError):
        await repo.create(user_id="u1", display_name="C")

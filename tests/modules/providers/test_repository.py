import pytest

from backend.modules.providers._repository import PremiumProviderAccountRepository


@pytest.mark.asyncio
async def test_upsert_creates_document(mongo_db):
    repo = PremiumProviderAccountRepository(mongo_db)
    await repo.create_indexes()
    doc = await repo.upsert("user-1", "xai", {"api_key": "xai-abc"})
    assert doc["provider_id"] == "xai"
    assert "api_key" not in doc["config"]
    assert "api_key" in doc["config_encrypted"]


@pytest.mark.asyncio
async def test_upsert_is_idempotent_on_same_user_provider(mongo_db):
    repo = PremiumProviderAccountRepository(mongo_db)
    await repo.create_indexes()
    await repo.upsert("user-1", "xai", {"api_key": "xai-abc"})
    await repo.upsert("user-1", "xai", {"api_key": "xai-xyz"})
    docs = [d async for d in repo._col.find({"user_id": "user-1", "provider_id": "xai"})]
    assert len(docs) == 1
    assert repo.get_decrypted_secret(docs[0], "api_key") == "xai-xyz"


@pytest.mark.asyncio
async def test_empty_secret_on_update_preserves_existing(mongo_db):
    repo = PremiumProviderAccountRepository(mongo_db)
    await repo.create_indexes()
    await repo.upsert("user-1", "xai", {"api_key": "xai-abc"})
    await repo.upsert("user-1", "xai", {"api_key": ""})
    doc = await repo.find("user-1", "xai")
    assert repo.get_decrypted_secret(doc, "api_key") == "xai-abc"


@pytest.mark.asyncio
async def test_find_returns_none_for_absent(mongo_db):
    repo = PremiumProviderAccountRepository(mongo_db)
    assert await repo.find("user-1", "xai") is None


@pytest.mark.asyncio
async def test_delete_returns_true_if_present(mongo_db):
    repo = PremiumProviderAccountRepository(mongo_db)
    await repo.upsert("user-1", "xai", {"api_key": "xai-abc"})
    assert await repo.delete("user-1", "xai") is True
    assert await repo.delete("user-1", "xai") is False


@pytest.mark.asyncio
async def test_list_for_user(mongo_db):
    repo = PremiumProviderAccountRepository(mongo_db)
    await repo.upsert("user-1", "xai", {"api_key": "k1"})
    await repo.upsert("user-1", "mistral", {"api_key": "k2"})
    await repo.upsert("user-2", "xai", {"api_key": "k3"})
    docs = await repo.list_for_user("user-1")
    assert {d["provider_id"] for d in docs} == {"xai", "mistral"}


@pytest.mark.asyncio
async def test_delete_all_for_user(mongo_db):
    repo = PremiumProviderAccountRepository(mongo_db)
    await repo.upsert("user-1", "xai", {"api_key": "k1"})
    await repo.upsert("user-1", "mistral", {"api_key": "k2"})
    deleted = await repo.delete_all_for_user("user-1")
    assert deleted == 2


@pytest.mark.asyncio
async def test_to_dto_redacts(mongo_db):
    repo = PremiumProviderAccountRepository(mongo_db)
    doc = await repo.upsert("user-1", "xai", {"api_key": "xai-abc"})
    dto = repo.to_dto(doc)
    assert dto.config["api_key"] == {"is_set": True}

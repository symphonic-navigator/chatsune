import pytest
from datetime import datetime, UTC

from backend.modules.user._key_repository import UserKeysRepository
from backend.modules.user._models import UserKeysDocument, WrappedDekPair, Argon2Params


@pytest.fixture
def repo(db):
    return UserKeysRepository(db)


@pytest.fixture
def sample_doc():
    now = datetime.now(UTC)
    return UserKeysDocument(
        user_id="507f1f77bcf86cd799439011",
        kdf_salt=b"s" * 32,
        kdf_params=Argon2Params(),
        current_dek_version=1,
        deks={"1": WrappedDekPair(
            wrapped_by_password=b"\x00" * 60,
            wrapped_by_recovery=b"\x01" * 60,
            created_at=now,
        )},
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_insert_and_fetch_by_user_id(repo, sample_doc):
    await repo.ensure_indexes()
    await repo.insert(sample_doc)
    fetched = await repo.get_by_user_id(sample_doc.user_id)
    assert fetched is not None
    assert fetched.kdf_salt == sample_doc.kdf_salt
    assert fetched.deks["1"].wrapped_by_password == sample_doc.deks["1"].wrapped_by_password


@pytest.mark.asyncio
async def test_get_returns_none_for_missing(repo):
    assert await repo.get_by_user_id("507f1f77bcf86cd799439099") is None


@pytest.mark.asyncio
async def test_unique_index_on_user_id(repo, sample_doc):
    from pymongo.errors import DuplicateKeyError
    await repo.ensure_indexes()
    await repo.insert(sample_doc)
    with pytest.raises(DuplicateKeyError):
        await repo.insert(sample_doc)


@pytest.mark.asyncio
async def test_set_recovery_required(repo, sample_doc):
    await repo.ensure_indexes()
    await repo.insert(sample_doc)
    await repo.set_recovery_required(sample_doc.user_id, value=True)
    fetched = await repo.get_by_user_id(sample_doc.user_id)
    assert fetched.dek_recovery_required is True


@pytest.mark.asyncio
async def test_replace_wrapped_by_password(repo, sample_doc):
    await repo.ensure_indexes()
    await repo.insert(sample_doc)
    new_blob = b"\x02" * 60
    await repo.replace_wrapped_by_password(sample_doc.user_id, version=1, blob=new_blob)
    fetched = await repo.get_by_user_id(sample_doc.user_id)
    assert fetched.deks["1"].wrapped_by_password == new_blob
    assert fetched.deks["1"].wrapped_by_recovery == sample_doc.deks["1"].wrapped_by_recovery

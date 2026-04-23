import pytest
import pytest_asyncio
import secrets

from backend.modules.user._key_service import UserKeyService, DekUnlockError
from backend.modules.user._recovery_key import generate_recovery_key, decode_recovery_key


@pytest_asyncio.fixture
async def service(db, redis_client):
    svc = UserKeyService(db=db, redis=redis_client)
    await svc.ensure_indexes()
    return svc


@pytest.mark.asyncio
async def test_provision_creates_wraps_and_returns_recovery_key(service):
    user_id = "507f1f77bcf86cd799439001"
    h_kek = secrets.token_bytes(32)
    recovery_key = generate_recovery_key()
    await service.provision_for_new_user(user_id=user_id, h_kek=h_kek, recovery_key=recovery_key, kdf_salt=b"s" * 32)
    doc = await service.get_keys_doc(user_id)
    assert doc is not None
    assert doc.current_dek_version == 1
    assert "1" in doc.deks


@pytest.mark.asyncio
async def test_unlock_with_correct_h_kek_returns_dek(service):
    user_id = "507f1f77bcf86cd799439002"
    h_kek = secrets.token_bytes(32)
    recovery_key = generate_recovery_key()
    await service.provision_for_new_user(user_id=user_id, h_kek=h_kek, recovery_key=recovery_key, kdf_salt=b"s" * 32)
    dek = await service.unlock_with_password(user_id=user_id, h_kek=h_kek)
    assert len(dek) == 32


@pytest.mark.asyncio
async def test_unlock_with_wrong_h_kek_raises(service):
    user_id = "507f1f77bcf86cd799439003"
    await service.provision_for_new_user(
        user_id=user_id, h_kek=secrets.token_bytes(32), recovery_key=generate_recovery_key(), kdf_salt=b"s" * 32
    )
    with pytest.raises(DekUnlockError):
        await service.unlock_with_password(user_id=user_id, h_kek=secrets.token_bytes(32))


@pytest.mark.asyncio
async def test_unlock_with_recovery_key_and_rewrap(service):
    user_id = "507f1f77bcf86cd799439004"
    h_kek_old = secrets.token_bytes(32)
    h_kek_new = secrets.token_bytes(32)
    recovery_key = generate_recovery_key()
    await service.provision_for_new_user(
        user_id=user_id, h_kek=h_kek_old, recovery_key=recovery_key, kdf_salt=b"s" * 32
    )
    dek_via_recovery = await service.unlock_with_recovery_and_rewrap(
        user_id=user_id, recovery_key=recovery_key, new_h_kek=h_kek_new
    )
    dek_via_new_password = await service.unlock_with_password(user_id=user_id, h_kek=h_kek_new)
    assert dek_via_recovery == dek_via_new_password


@pytest.mark.asyncio
async def test_session_dek_store_roundtrip_and_ttl(service):
    session_id = "sess-1"
    dek = secrets.token_bytes(32)
    await service.store_session_dek(session_id=session_id, dek=dek, ttl_seconds=900)
    assert await service.fetch_session_dek(session_id) == dek
    await service.delete_session_dek(session_id)
    assert await service.fetch_session_dek(session_id) is None


@pytest.mark.asyncio
async def test_rewrap_password_updates_only_password_wrap(service):
    user_id = "507f1f77bcf86cd799439005"
    h_kek_old = secrets.token_bytes(32)
    h_kek_new = secrets.token_bytes(32)
    recovery_key = generate_recovery_key()
    await service.provision_for_new_user(user_id=user_id, h_kek=h_kek_old, recovery_key=recovery_key, kdf_salt=b"s" * 32)
    doc_before = await service.get_keys_doc(user_id)
    wrapped_rec_before = doc_before.deks["1"].wrapped_by_recovery
    await service.rewrap_password(user_id=user_id, h_kek_old=h_kek_old, h_kek_new=h_kek_new)
    doc_after = await service.get_keys_doc(user_id)
    assert doc_after.deks["1"].wrapped_by_password != doc_before.deks["1"].wrapped_by_password
    assert doc_after.deks["1"].wrapped_by_recovery == wrapped_rec_before
    await service.unlock_with_password(user_id=user_id, h_kek=h_kek_new)

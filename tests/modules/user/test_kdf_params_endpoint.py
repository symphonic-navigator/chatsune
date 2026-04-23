import base64
import secrets

import pytest
import pytest_asyncio
import httpx
from bson import ObjectId
from datetime import datetime, UTC


@pytest.mark.asyncio
async def test_kdf_params_returns_deterministic_pseudo_salt_for_unknown_user(client: httpx.AsyncClient):
    r1 = await client.post("/api/auth/kdf-params", json={"username": "ghost-user"})
    r2 = await client.post("/api/auth/kdf-params", json={"username": "ghost-user"})
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["kdf_salt"] == r2.json()["kdf_salt"]
    assert r1.json()["password_hash_version"] is None
    assert len(base64.urlsafe_b64decode(r1.json()["kdf_salt"])) == 32


@pytest.mark.asyncio
async def test_kdf_params_username_is_case_insensitive_for_ghost(client: httpx.AsyncClient):
    r1 = await client.post("/api/auth/kdf-params", json={"username": "Ghost"})
    r2 = await client.post("/api/auth/kdf-params", json={"username": "ghost"})
    assert r1.json()["kdf_salt"] == r2.json()["kdf_salt"]


@pytest.mark.asyncio
async def test_kdf_params_returns_real_salt_for_provisioned_user(
    client: httpx.AsyncClient, db, user_key_service_seeded
):
    from backend.modules.user._key_service import UserKeyService
    from backend.modules.user._recovery_key import generate_recovery_key

    svc = UserKeyService(db=db, redis=user_key_service_seeded["redis"])
    await svc.ensure_indexes()

    user_id = str(ObjectId())
    await db["users"].insert_one({
        "_id": user_id,
        "username": "provisioned-user",
        "email": "p@example.com",
        "display_name": "P",
        "password_hash": "$2b$12$placeholder",
        "password_hash_version": 1,
        "role": "user",
        "is_active": True,
        "must_change_password": False,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    })
    salt = secrets.token_bytes(32)
    await svc.provision_for_new_user(
        user_id=user_id,
        h_kek=secrets.token_bytes(32),
        recovery_key=generate_recovery_key(),
        kdf_salt=salt,
    )
    r = await client.post("/api/auth/kdf-params", json={"username": "provisioned-user"})
    assert r.status_code == 200
    body = r.json()
    assert body["password_hash_version"] == 1
    assert base64.urlsafe_b64decode(body["kdf_salt"]) == salt


@pytest_asyncio.fixture
def user_key_service_seeded(redis_client):
    return {"redis": redis_client}

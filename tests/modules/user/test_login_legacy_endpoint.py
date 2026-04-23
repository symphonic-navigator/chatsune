import base64
import secrets
import pytest
from uuid import uuid4
from datetime import datetime, UTC

from backend.modules.user._auth import hash_password  # legacy bcrypt over raw password


@pytest.mark.asyncio
async def test_legacy_login_upgrades_user_and_returns_recovery_key(client, db, user_key_service):
    # Seed a pre-migration user: password_hash over raw password, no user_keys, no password_hash_version.
    raw_password = "hunter2-legacy"
    user_id = str(uuid4())
    await db["users"].insert_one({
        "_id": user_id,
        "username": "legacy_chris",
        "email": "legacy@example.com",
        "display_name": "Legacy Chris",
        "password_hash": hash_password(raw_password),
        "role": "user",
        "is_active": True,
        "must_change_password": False,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    })

    h_auth = secrets.token_bytes(32)
    h_kek = secrets.token_bytes(32)
    body = {
        "username": "legacy_chris",
        "password": raw_password,
        "h_auth": base64.urlsafe_b64encode(h_auth).decode(),
        "h_kek": base64.urlsafe_b64encode(h_kek).decode(),
    }
    response = await client.post("/api/auth/login-legacy", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    assert "recovery_key" in data
    assert "access_token" in data

    upgraded = await db["users"].find_one({"username": "legacy_chris"})
    assert upgraded["password_hash_version"] == 1
    assert await user_key_service.get_keys_doc(user_id) is not None


@pytest.mark.asyncio
async def test_legacy_login_rejects_already_migrated_user(client, seeded_user):
    body = {
        "username": seeded_user.username,
        "password": "anything",
        "h_auth": "AA" * 44,  # just filler — endpoint rejects before deriving
        "h_kek": "AA" * 44,
    }
    response = await client.post("/api/auth/login-legacy", json=body)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_legacy_login_rejects_wrong_password(client, db):
    user_id = str(uuid4())
    await db["users"].insert_one({
        "_id": user_id,
        "username": "legacy2",
        "email": "l2@example.com",
        "display_name": "l2",
        "password_hash": hash_password("correct"),
        "role": "user",
        "is_active": True,
        "must_change_password": False,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    })
    h_auth = secrets.token_bytes(32)
    h_kek = secrets.token_bytes(32)
    body = {
        "username": "legacy2",
        "password": "wrong",
        "h_auth": base64.urlsafe_b64encode(h_auth).decode(),
        "h_kek": base64.urlsafe_b64encode(h_kek).decode(),
    }
    response = await client.post("/api/auth/login-legacy", json=body)
    assert response.status_code == 401

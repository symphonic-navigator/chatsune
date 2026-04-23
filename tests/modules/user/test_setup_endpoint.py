import base64
import secrets
import pytest

from backend.modules.user._recovery_key import generate_recovery_key


@pytest.mark.asyncio
async def test_setup_creates_user_with_provisioned_keys(client, db, user_key_service):
    from backend.config import settings
    pin = settings.master_admin_pin  # use the configured value directly
    h_auth = secrets.token_bytes(32)
    h_kek = secrets.token_bytes(32)
    recovery_key = generate_recovery_key()
    body = {
        "username": "founder",
        "email": "founder@example.com",
        "display_name": "Founder",
        "pin": pin,
        "h_auth": base64.urlsafe_b64encode(h_auth).decode(),
        "h_kek": base64.urlsafe_b64encode(h_kek).decode(),
        "recovery_key": recovery_key,
    }
    response = await client.post("/api/auth/setup", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    assert "access_token" in data
    # Recovery key is NOT echoed — the client generated and already has it
    assert "recovery_key" not in data

    row = await db["users"].find_one({"username": "founder"})
    assert row is not None
    assert row["password_hash_version"] == 1
    assert row["role"] == "master_admin"
    keys_doc = await user_key_service.get_keys_doc(str(row["_id"]))
    assert keys_doc is not None
    # The exact kdf_salt and recovery_key we supplied can unlock back to the same DEK
    await user_key_service.unlock_with_password(user_id=str(row["_id"]), h_kek=h_kek)


@pytest.mark.asyncio
async def test_setup_wrong_pin_rejected(client):
    body = {
        "username": "x",
        "email": "x@example.com",
        "display_name": "x",
        "pin": "wrong-pin",
        "h_auth": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "h_kek": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "recovery_key": generate_recovery_key(),
    }
    response = await client.post("/api/auth/setup", json=body)
    assert response.status_code in (401, 403), response.text


@pytest.mark.asyncio
async def test_setup_rejects_second_master_admin(client, db):
    from backend.config import settings
    from datetime import datetime, UTC
    from uuid import uuid4

    # Seed an existing master admin
    await db["users"].insert_one({
        "_id": str(uuid4()),
        "username": "existing-admin",
        "email": "a@example.com",
        "display_name": "Existing",
        "password_hash": "$2b$12$placeholder",
        "password_hash_version": 1,
        "role": "master_admin",
        "is_active": True,
        "must_change_password": False,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    })
    body = {
        "username": "second-admin",
        "email": "2@example.com",
        "display_name": "Two",
        "pin": settings.master_admin_pin,
        "h_auth": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "h_kek": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "recovery_key": generate_recovery_key(),
    }
    response = await client.post("/api/auth/setup", json=body)
    assert response.status_code in (409, 403), response.text

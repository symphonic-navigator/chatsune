import base64
import secrets
import pytest


@pytest.mark.asyncio
async def test_recover_dek_unlocks_and_allows_new_login(client, seeded_user, user_key_service):
    await user_key_service.mark_recovery_required(seeded_user.id)
    new_h_kek = secrets.token_bytes(32)
    body = {
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(seeded_user.h_auth_raw).decode(),
        "h_kek": base64.urlsafe_b64encode(new_h_kek).decode(),
        "recovery_key": seeded_user.recovery_key,
    }
    response = await client.post("/api/auth/recover-dek", json=body)
    assert response.status_code == 200, response.text
    assert "access_token" in response.json()

    # Subsequent login with old password + new h_kek should now succeed
    login = await client.post("/api/auth/login", json={
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(seeded_user.h_auth_raw).decode(),
        "h_kek": base64.urlsafe_b64encode(new_h_kek).decode(),
    })
    assert login.status_code == 200, login.text


@pytest.mark.asyncio
async def test_recover_dek_with_wrong_key_returns_401(client, seeded_user, user_key_service):
    await user_key_service.mark_recovery_required(seeded_user.id)
    body = {
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(seeded_user.h_auth_raw).decode(),
        "h_kek": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "recovery_key": "ABCD-ABCD-ABCD-ABCD-ABCD-ABCD-ABCD-ABCD",
    }
    response = await client.post("/api/auth/recover-dek", json=body)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_recover_dek_rate_limits_after_5_bad_attempts(client, seeded_user, user_key_service, redis_client):
    await user_key_service.mark_recovery_required(seeded_user.id)
    body = {
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(seeded_user.h_auth_raw).decode(),
        "h_kek": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "recovery_key": "ABCD-ABCD-ABCD-ABCD-ABCD-ABCD-ABCD-ABCD",
    }
    # 5 bad attempts — all 401
    for _ in range(5):
        r = await client.post("/api/auth/recover-dek", json=body)
        assert r.status_code == 401
    # 6th should be rate-limited
    r = await client.post("/api/auth/recover-dek", json=body)
    assert r.status_code == 429


@pytest.mark.asyncio
async def test_decline_recovery_deactivates_account(client, seeded_user, db, user_key_service):
    await user_key_service.mark_recovery_required(seeded_user.id)
    response = await client.post("/api/auth/decline-recovery", json={"username": seeded_user.username})
    assert response.status_code == 200
    row = await db["users"].find_one({"username": seeded_user.username})
    assert row["is_active"] is False


@pytest.mark.asyncio
async def test_decline_recovery_for_unknown_user_returns_200_without_side_effect(client, db):
    initial_count = await db["users"].count_documents({})
    response = await client.post("/api/auth/decline-recovery", json={"username": "does-not-exist"})
    assert response.status_code == 200
    # No user created or altered
    assert await db["users"].count_documents({}) == initial_count

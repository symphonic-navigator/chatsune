import base64
import secrets
import pytest


@pytest.mark.asyncio
async def test_change_password_rewraps_and_updates_bcrypt(client, seeded_user, user_key_service):
    # Log in
    login = await client.post("/api/auth/login", json={
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(seeded_user.h_auth_raw).decode(),
        "h_kek": base64.urlsafe_b64encode(seeded_user.h_kek_raw).decode(),
    })
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    new_h_auth = secrets.token_bytes(32)
    new_h_kek = secrets.token_bytes(32)
    body = {
        "h_auth_old": base64.urlsafe_b64encode(seeded_user.h_auth_raw).decode(),
        "h_kek_old": base64.urlsafe_b64encode(seeded_user.h_kek_raw).decode(),
        "h_auth_new": base64.urlsafe_b64encode(new_h_auth).decode(),
        "h_kek_new": base64.urlsafe_b64encode(new_h_kek).decode(),
    }
    response = await client.post(
        "/api/auth/change-password", json=body, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200, response.text

    # Old credentials fail
    r_old = await client.post("/api/auth/login", json={
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(seeded_user.h_auth_raw).decode(),
        "h_kek": base64.urlsafe_b64encode(seeded_user.h_kek_raw).decode(),
    })
    assert r_old.status_code == 401

    # New credentials succeed
    r_new = await client.post("/api/auth/login", json={
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(new_h_auth).decode(),
        "h_kek": base64.urlsafe_b64encode(new_h_kek).decode(),
    })
    assert r_new.status_code == 200

    # Recovery wrap preserved — reusing the recovery key unlocks to the same DEK.
    new_new_h_kek = secrets.token_bytes(32)
    await user_key_service.mark_recovery_required(seeded_user.id)
    dek_via_recovery = await user_key_service.unlock_with_recovery_and_rewrap(
        user_id=seeded_user.id, recovery_key=seeded_user.recovery_key, new_h_kek=new_new_h_kek
    )
    dek_via_new_pw = await user_key_service.unlock_with_password(user_id=seeded_user.id, h_kek=new_new_h_kek)
    assert dek_via_recovery == dek_via_new_pw


@pytest.mark.asyncio
async def test_change_password_wrong_old_h_auth_returns_401(client, seeded_user):
    login = await client.post("/api/auth/login", json={
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(seeded_user.h_auth_raw).decode(),
        "h_kek": base64.urlsafe_b64encode(seeded_user.h_kek_raw).decode(),
    })
    token = login.json()["access_token"]
    body = {
        "h_auth_old": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "h_kek_old": base64.urlsafe_b64encode(seeded_user.h_kek_raw).decode(),
        "h_auth_new": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "h_kek_new": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    }
    response = await client.post(
        "/api/auth/change-password", json=body, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401

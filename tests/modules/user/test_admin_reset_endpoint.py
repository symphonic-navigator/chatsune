import base64
import secrets
import pytest


@pytest.mark.asyncio
async def test_admin_reset_sets_recovery_required_and_sentinel_hash(
    client, seeded_admin_token, seeded_user, user_key_service, db
):
    admin_id, admin_token = seeded_admin_token
    response = await client.post(
        f"/api/admin/users/{seeded_user.id}/reset-password",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200, response.text
    doc = await user_key_service.get_keys_doc(seeded_user.id)
    assert doc.dek_recovery_required is True
    row = await db["users"].find_one({"username": seeded_user.username})
    assert row["password_hash"].startswith("$SENTINEL$")
    assert row["must_change_password"] is True


@pytest.mark.asyncio
async def test_post_reset_login_always_returns_recovery_required(
    client, seeded_admin_token, seeded_user
):
    admin_id, admin_token = seeded_admin_token
    await client.post(
        f"/api/admin/users/{seeded_user.id}/reset-password",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    # Any H_auth at all, since the stored hash is the sentinel
    body = {
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "h_kek": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    }
    response = await client.post("/api/auth/login", json=body)
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "recovery_required"}


@pytest.mark.asyncio
async def test_post_reset_recovery_flow_installs_real_hash(
    client, seeded_admin_token, seeded_user, db, user_key_service
):
    admin_id, admin_token = seeded_admin_token
    await client.post(
        f"/api/admin/users/{seeded_user.id}/reset-password",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    new_h_auth = secrets.token_bytes(32)
    new_h_kek = secrets.token_bytes(32)
    body = {
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(new_h_auth).decode(),
        "h_kek": base64.urlsafe_b64encode(new_h_kek).decode(),
        "recovery_key": seeded_user.recovery_key,
    }
    r = await client.post("/api/auth/recover-dek", json=body)
    assert r.status_code == 200, r.text

    # Sentinel replaced with real bcrypt, must_change_password cleared
    row = await db["users"].find_one({"username": seeded_user.username})
    assert not row["password_hash"].startswith("$SENTINEL$")
    assert row["must_change_password"] is False

    # Normal login with the new credentials now works
    login = await client.post("/api/auth/login", json={
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(new_h_auth).decode(),
        "h_kek": base64.urlsafe_b64encode(new_h_kek).decode(),
    })
    assert login.status_code == 200
    assert "access_token" in login.json()

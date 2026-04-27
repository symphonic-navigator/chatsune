import base64
import pytest


@pytest.mark.asyncio
async def test_create_invitation_returns_token_and_expiry(
    client, seeded_admin_token, user_key_service
):
    _, admin_token = seeded_admin_token
    resp = await client.post(
        "/api/admin/invitations",
        json={},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "token" in body and len(body["token"]) >= 32
    assert "expires_at" in body


@pytest.mark.asyncio
async def test_create_invitation_requires_admin(
    client, seeded_user, user_key_service
):
    # Log in as a regular user to get a token
    login = await client.post("/api/auth/login", json={
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(seeded_user.h_auth_raw).decode(),
        "h_kek": base64.urlsafe_b64encode(seeded_user.h_kek_raw).decode(),
    })
    assert login.status_code == 200, login.text
    user_token = login.json()["access_token"]

    resp = await client.post(
        "/api/admin/invitations",
        json={},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_create_invitation_unauthenticated(client, clean_db):
    resp = await client.post("/api/admin/invitations", json={})
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# POST /api/invitations/{token}/validate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_validate_returns_valid_for_fresh_token(client, seeded_admin_token, user_key_service):
    _, admin_token = seeded_admin_token
    create_resp = await client.post(
        "/api/admin/invitations",
        json={},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    token = create_resp.json()["token"]

    resp = await client.post(f"/api/invitations/{token}/validate")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"valid": True, "reason": None}


@pytest.mark.asyncio
async def test_validate_returns_not_found_for_unknown(client, clean_db):
    resp = await client.post("/api/invitations/garbage-token/validate")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"valid": False, "reason": "not_found"}


@pytest.mark.asyncio
async def test_validate_returns_expired(client, seeded_admin_token, user_key_service, db):
    _, admin_token = seeded_admin_token
    create_resp = await client.post(
        "/api/admin/invitations",
        json={},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    token = create_resp.json()["token"]

    from datetime import datetime, timezone
    await db["invitation_tokens"].update_one(
        {"token": token},
        {"$set": {"expires_at": datetime(2020, 1, 1, tzinfo=timezone.utc)}},
    )

    resp = await client.post(f"/api/invitations/{token}/validate")
    assert resp.status_code == 200
    assert resp.json() == {"valid": False, "reason": "expired"}


@pytest.mark.asyncio
async def test_validate_returns_used(client, seeded_admin_token, user_key_service, db):
    _, admin_token = seeded_admin_token
    create_resp = await client.post(
        "/api/admin/invitations",
        json={},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    token = create_resp.json()["token"]

    await db["invitation_tokens"].update_one(
        {"token": token}, {"$set": {"used": True}}
    )

    resp = await client.post(f"/api/invitations/{token}/validate")
    assert resp.status_code == 200
    assert resp.json() == {"valid": False, "reason": "used"}


@pytest.mark.asyncio
async def test_validate_status_always_200(client, seeded_admin_token, user_key_service, db):
    """No HTTP-code enumeration possible across not_found / used / expired."""
    from datetime import datetime, timezone

    r1 = await client.post("/api/invitations/never-existed/validate")
    _, admin_token = seeded_admin_token

    # used case
    create_resp = await client.post(
        "/api/admin/invitations",
        json={},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    token = create_resp.json()["token"]
    await db["invitation_tokens"].update_one({"token": token}, {"$set": {"used": True}})
    r2 = await client.post(f"/api/invitations/{token}/validate")

    # expired case
    create_resp_2 = await client.post(
        "/api/admin/invitations",
        json={},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    token_e = create_resp_2.json()["token"]
    await db["invitation_tokens"].update_one(
        {"token": token_e},
        {"$set": {"expires_at": datetime(2020, 1, 1, tzinfo=timezone.utc)}},
    )
    r3 = await client.post(f"/api/invitations/{token_e}/validate")

    assert r1.status_code == r2.status_code == r3.status_code == 200

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

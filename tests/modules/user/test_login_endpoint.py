import base64
import secrets

import pytest
import httpx


@pytest.mark.asyncio
async def test_login_with_correct_material_succeeds(client: httpx.AsyncClient, seeded_user):
    body = {
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(seeded_user.h_auth_raw).decode(),
        "h_kek": base64.urlsafe_b64encode(seeded_user.h_kek_raw).decode(),
    }
    response = await client.post("/api/auth/login", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    assert "access_token" in data
    assert "status" not in data


@pytest.mark.asyncio
async def test_login_with_wrong_h_auth_returns_401(client, seeded_user):
    body = {
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "h_kek": base64.urlsafe_b64encode(seeded_user.h_kek_raw).decode(),
    }
    response = await client.post("/api/auth/login", json=body)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_returns_recovery_required_when_flag_set(client, seeded_user, user_key_service):
    await user_key_service.mark_recovery_required(seeded_user.id)
    body = {
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(seeded_user.h_auth_raw).decode(),
        "h_kek": base64.urlsafe_b64encode(seeded_user.h_kek_raw).decode(),
    }
    response = await client.post("/api/auth/login", json=body)
    assert response.status_code == 200
    assert response.json() == {"status": "recovery_required"}


@pytest.mark.asyncio
async def test_login_populates_session_dek_in_redis(client, seeded_user, user_key_service):
    body = {
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(seeded_user.h_auth_raw).decode(),
        "h_kek": base64.urlsafe_b64encode(seeded_user.h_kek_raw).decode(),
    }
    response = await client.post("/api/auth/login", json=body)
    assert response.status_code == 200
    from backend.modules.user._auth import decode_access_token
    claims = decode_access_token(response.json()["access_token"])
    session_id = claims.get("session_id") or claims.get("sid")
    assert session_id, f"no session id in claims: {claims}"
    dek = await user_key_service.fetch_session_dek(session_id)
    assert dek is not None and len(dek) == 32

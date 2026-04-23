import base64

import pytest
import httpx


@pytest.mark.asyncio
async def test_logout_deletes_session_dek(
    client: httpx.AsyncClient, seeded_user, user_key_service
):
    login = await client.post("/api/auth/login", json={
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(seeded_user.h_auth_raw).decode(),
        "h_kek": base64.urlsafe_b64encode(seeded_user.h_kek_raw).decode(),
    })
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    from backend.modules.user._auth import decode_access_token
    claims = decode_access_token(token)
    session_id = claims.get("session_id") or claims.get("sid")
    assert session_id

    # DEK must be present immediately after login.
    assert await user_key_service.fetch_session_dek(session_id) is not None

    resp = await client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code in (200, 204), resp.text

    # DEK must be gone after logout.
    assert await user_key_service.fetch_session_dek(session_id) is None


@pytest.mark.asyncio
async def test_refresh_extends_session_dek_ttl(
    client: httpx.AsyncClient, seeded_user, user_key_service, redis_client
):
    login = await client.post("/api/auth/login", json={
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(seeded_user.h_auth_raw).decode(),
        "h_kek": base64.urlsafe_b64encode(seeded_user.h_kek_raw).decode(),
    })
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    from backend.modules.user._auth import decode_access_token
    claims = decode_access_token(token)
    session_id = claims.get("session_id") or claims.get("sid")
    assert session_id

    key = f"session_dek:{session_id}"

    # Artificially shorten the TTL so we can observe the extension.
    await redis_client.expire(key, 60)
    ttl_mid = await redis_client.ttl(key)
    assert 0 < ttl_mid <= 60

    # Extract the refresh_token cookie from the login response and send it
    # explicitly — httpx ASGI transport does not forward cookies automatically.
    refresh_cookie = login.cookies.get("refresh_token")
    assert refresh_cookie, "Login did not set a refresh_token cookie"

    refresh = await client.post(
        "/api/auth/refresh",
        cookies={"refresh_token": refresh_cookie},
    )
    assert refresh.status_code == 200, refresh.text

    ttl_after = await redis_client.ttl(key)
    assert ttl_after > ttl_mid, f"TTL did not extend: {ttl_mid} -> {ttl_after}"

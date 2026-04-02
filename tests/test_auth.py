import pytest
from httpx import AsyncClient


async def _setup_master_admin(client: AsyncClient) -> tuple[dict, dict]:
    """Helper: create master admin and return (response_data, cookies)."""
    resp = await client.post(
        "/api/setup",
        json={
            "pin": "change-me-1234",
            "username": "admin",
            "email": "admin@example.com",
            "password": "SecurePass123",
        },
    )
    return resp.json(), dict(resp.cookies)


async def test_login_success(client: AsyncClient):
    await _setup_master_admin(client)

    response = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "SecurePass123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert "refresh_token" in response.cookies


async def test_login_wrong_password(client: AsyncClient):
    await _setup_master_admin(client)

    response = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "WrongPass"},
    )
    assert response.status_code == 401


async def test_login_nonexistent_user(client: AsyncClient):
    response = await client.post(
        "/api/auth/login",
        json={"username": "nobody", "password": "whatever"},
    )
    assert response.status_code == 401


async def test_refresh_token_rotation(client: AsyncClient):
    await _setup_master_admin(client)

    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "SecurePass123"},
    )
    refresh_cookie = login_resp.cookies["refresh_token"]

    # Use refresh token
    refresh_resp = await client.post(
        "/api/auth/refresh",
        cookies={"refresh_token": refresh_cookie},
    )
    assert refresh_resp.status_code == 200
    assert "access_token" in refresh_resp.json()

    # Old refresh token should no longer work
    replay_resp = await client.post(
        "/api/auth/refresh",
        cookies={"refresh_token": refresh_cookie},
    )
    assert replay_resp.status_code == 401


async def test_logout_clears_refresh_token(client: AsyncClient):
    await _setup_master_admin(client)

    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "SecurePass123"},
    )
    token = login_resp.json()["access_token"]
    refresh_cookie = login_resp.cookies["refresh_token"]

    logout_resp = await client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
        cookies={"refresh_token": refresh_cookie},
    )
    assert logout_resp.status_code == 200

    # Refresh token no longer works
    refresh_resp = await client.post(
        "/api/auth/refresh",
        cookies={"refresh_token": refresh_cookie},
    )
    assert refresh_resp.status_code == 401


async def test_change_password(client: AsyncClient):
    data, _ = await _setup_master_admin(client)
    token = data["access_token"]

    response = await client.patch(
        "/api/auth/password",
        json={
            "current_password": "SecurePass123",
            "new_password": "NewSecurePass456",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()

    # Old password no longer works
    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "SecurePass123"},
    )
    assert login_resp.status_code == 401

    # New password works
    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "NewSecurePass456"},
    )
    assert login_resp.status_code == 200

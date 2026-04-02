import pytest
from httpx import AsyncClient


async def test_setup_creates_master_admin(client: AsyncClient):
    response = await client.post(
        "/api/setup",
        json={
            "pin": "change-me-1234",
            "username": "admin",
            "email": "admin@example.com",
            "password": "SecurePass123",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["user"]["role"] == "master_admin"
    assert data["user"]["username"] == "admin"
    assert data["user"]["is_active"] is True
    assert data["user"]["must_change_password"] is False
    assert "access_token" in data
    assert data["token_type"] == "bearer"

    # Refresh cookie should be set
    assert "refresh_token" in response.cookies


async def test_setup_rejects_wrong_pin(client: AsyncClient):
    response = await client.post(
        "/api/setup",
        json={
            "pin": "wrong-pin",
            "username": "admin",
            "email": "admin@example.com",
            "password": "SecurePass123",
        },
    )
    assert response.status_code == 403


async def test_setup_rejects_second_call(client: AsyncClient):
    # First call succeeds
    await client.post(
        "/api/setup",
        json={
            "pin": "change-me-1234",
            "username": "admin",
            "email": "admin@example.com",
            "password": "SecurePass123",
        },
    )
    # Second call is rejected
    response = await client.post(
        "/api/setup",
        json={
            "pin": "change-me-1234",
            "username": "admin2",
            "email": "admin2@example.com",
            "password": "SecurePass123",
        },
    )
    assert response.status_code == 409

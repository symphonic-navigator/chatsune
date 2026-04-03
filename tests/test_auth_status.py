import pytest
from httpx import AsyncClient


async def test_auth_status_no_admin_exists(client: AsyncClient):
    resp = await client.get("/api/auth/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_setup_complete"] is False


async def test_auth_status_after_setup(client: AsyncClient):
    await client.post(
        "/api/setup",
        json={
            "pin": "change-me-1234",
            "username": "admin",
            "email": "admin@example.com",
            "password": "SecurePass123",
        },
    )
    resp = await client.get("/api/auth/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_setup_complete"] is True


async def test_auth_status_requires_no_auth(client: AsyncClient):
    """Endpoint must be accessible without any auth token."""
    resp = await client.get("/api/auth/status")
    assert resp.status_code == 200

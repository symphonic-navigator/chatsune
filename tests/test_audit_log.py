import pytest
from httpx import AsyncClient


async def _setup_and_login(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/setup",
        json={
            "pin": "change-me-1234",
            "username": "admin",
            "email": "admin@example.com",
            "password": "SecurePass123",
        },
    )
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_audit_log_records_setup(client: AsyncClient):
    token = await _setup_and_login(client)

    response = await client.get(
        "/api/admin/audit-log", headers=_auth(token)
    )
    assert response.status_code == 200
    entries = response.json()["entries"]
    assert len(entries) >= 1
    assert entries[0]["action"] == "user.created"
    assert entries[0]["resource_type"] == "user"


async def test_audit_log_records_user_creation(client: AsyncClient):
    token = await _setup_and_login(client)

    await client.post(
        "/api/admin/users",
        json={
            "username": "testuser",
            "email": "test@example.com",
            "display_name": "Test",
        },
        headers=_auth(token),
    )

    response = await client.get(
        "/api/admin/audit-log", headers=_auth(token)
    )
    entries = response.json()["entries"]
    actions = [e["action"] for e in entries]
    assert "user.created" in actions


async def test_audit_log_filter_by_action(client: AsyncClient):
    token = await _setup_and_login(client)

    # Create and deactivate a user to generate different actions
    create_resp = await client.post(
        "/api/admin/users",
        json={
            "username": "filterme",
            "email": "filter@example.com",
            "display_name": "Filter Me",
        },
        headers=_auth(token),
    )
    user_id = create_resp.json()["user"]["id"]
    await client.delete(
        f"/api/admin/users/{user_id}", headers=_auth(token)
    )

    response = await client.get(
        "/api/admin/audit-log?action=user.deactivated",
        headers=_auth(token),
    )
    entries = response.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["action"] == "user.deactivated"


async def test_admin_sees_only_own_audit_entries(client: AsyncClient):
    master_token = await _setup_and_login(client)

    # Create an admin
    resp = await client.post(
        "/api/admin/users",
        json={
            "username": "auditor",
            "email": "audit@example.com",
            "display_name": "Auditor",
            "role": "admin",
        },
        headers=_auth(master_token),
    )
    admin_pw = resp.json()["generated_password"]
    admin_id = resp.json()["user"]["id"]

    # Login as admin, change password
    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "auditor", "password": admin_pw},
    )
    mcp_token = login_resp.json()["access_token"]
    pw_resp = await client.patch(
        "/api/auth/password",
        json={"current_password": admin_pw, "new_password": "AuditorPass1"},
        headers=_auth(mcp_token),
    )
    admin_token = pw_resp.json()["access_token"]

    # Admin creates a user (generates an audit entry with admin as actor)
    await client.post(
        "/api/admin/users",
        json={
            "username": "newguy",
            "email": "new@example.com",
            "display_name": "New Guy",
        },
        headers=_auth(admin_token),
    )

    # Admin queries audit log — should only see own entries
    response = await client.get(
        "/api/admin/audit-log", headers=_auth(admin_token)
    )
    entries = response.json()["entries"]
    for entry in entries:
        assert entry["actor_id"] == admin_id


async def test_regular_user_cannot_access_audit_log(client: AsyncClient):
    master_token = await _setup_and_login(client)

    create_resp = await client.post(
        "/api/admin/users",
        json={
            "username": "normie",
            "email": "normie@example.com",
            "display_name": "Normie",
        },
        headers=_auth(master_token),
    )
    user_pw = create_resp.json()["generated_password"]

    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "normie", "password": user_pw},
    )
    user_token = login_resp.json()["access_token"]

    # User with mcp token can't access audit log (not admin + mcp restriction)
    response = await client.get(
        "/api/admin/audit-log", headers=_auth(user_token)
    )
    assert response.status_code == 403

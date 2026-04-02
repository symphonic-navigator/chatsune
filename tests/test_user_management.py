import pytest
from httpx import AsyncClient


async def _setup_and_login(client: AsyncClient) -> str:
    """Create master admin and return access token."""
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


async def test_create_user(client: AsyncClient):
    token = await _setup_and_login(client)

    response = await client.post(
        "/api/admin/users",
        json={
            "username": "testuser",
            "email": "test@example.com",
            "display_name": "Test User",
        },
        headers=_auth(token),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["user"]["username"] == "testuser"
    assert data["user"]["role"] == "user"
    assert data["user"]["must_change_password"] is True
    assert len(data["generated_password"]) == 20
    assert data["generated_password"].isalnum()


async def test_create_admin_user_only_by_master(client: AsyncClient):
    master_token = await _setup_and_login(client)

    # Master admin creates an admin
    resp = await client.post(
        "/api/admin/users",
        json={
            "username": "newadmin",
            "email": "newadmin@example.com",
            "display_name": "New Admin",
            "role": "admin",
        },
        headers=_auth(master_token),
    )
    assert resp.status_code == 201
    admin_pw = resp.json()["generated_password"]

    # Login as the new admin
    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "newadmin", "password": admin_pw},
    )
    admin_token_mcp = login_resp.json()["access_token"]

    # Change password first (must_change_password)
    pw_resp = await client.patch(
        "/api/auth/password",
        json={"current_password": admin_pw, "new_password": "AdminPass123"},
        headers=_auth(admin_token_mcp),
    )
    admin_token = pw_resp.json()["access_token"]

    # Admin tries to create another admin — should fail
    resp2 = await client.post(
        "/api/admin/users",
        json={
            "username": "anotheradmin",
            "email": "another@example.com",
            "display_name": "Another Admin",
            "role": "admin",
        },
        headers=_auth(admin_token),
    )
    assert resp2.status_code == 403


async def test_list_users(client: AsyncClient):
    token = await _setup_and_login(client)

    # Create two users
    for i in range(2):
        await client.post(
            "/api/admin/users",
            json={
                "username": f"user{i}",
                "email": f"user{i}@example.com",
                "display_name": f"User {i}",
            },
            headers=_auth(token),
        )

    response = await client.get("/api/admin/users", headers=_auth(token))
    assert response.status_code == 200
    data = response.json()
    assert len(data["users"]) == 3  # master admin + 2 users
    assert "total" in data


async def test_get_single_user(client: AsyncClient):
    token = await _setup_and_login(client)

    create_resp = await client.post(
        "/api/admin/users",
        json={
            "username": "single",
            "email": "single@example.com",
            "display_name": "Single User",
        },
        headers=_auth(token),
    )
    user_id = create_resp.json()["user"]["id"]

    response = await client.get(
        f"/api/admin/users/{user_id}", headers=_auth(token)
    )
    assert response.status_code == 200
    assert response.json()["username"] == "single"


async def test_update_user(client: AsyncClient):
    token = await _setup_and_login(client)

    create_resp = await client.post(
        "/api/admin/users",
        json={
            "username": "updatable",
            "email": "up@example.com",
            "display_name": "Old Name",
        },
        headers=_auth(token),
    )
    user_id = create_resp.json()["user"]["id"]

    response = await client.patch(
        f"/api/admin/users/{user_id}",
        json={"display_name": "New Name", "email": "new@example.com"},
        headers=_auth(token),
    )
    assert response.status_code == 200
    assert response.json()["display_name"] == "New Name"
    assert response.json()["email"] == "new@example.com"


async def test_soft_delete_user(client: AsyncClient):
    token = await _setup_and_login(client)

    create_resp = await client.post(
        "/api/admin/users",
        json={
            "username": "deletable",
            "email": "del@example.com",
            "display_name": "Deletable",
        },
        headers=_auth(token),
    )
    user_id = create_resp.json()["user"]["id"]

    response = await client.delete(
        f"/api/admin/users/{user_id}", headers=_auth(token)
    )
    assert response.status_code == 200

    # Verify user is inactive
    get_resp = await client.get(
        f"/api/admin/users/{user_id}", headers=_auth(token)
    )
    assert get_resp.json()["is_active"] is False


async def test_reset_password(client: AsyncClient):
    token = await _setup_and_login(client)

    create_resp = await client.post(
        "/api/admin/users",
        json={
            "username": "resetme",
            "email": "reset@example.com",
            "display_name": "Reset Me",
        },
        headers=_auth(token),
    )
    user_id = create_resp.json()["user"]["id"]

    response = await client.post(
        f"/api/admin/users/{user_id}/reset-password",
        headers=_auth(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["generated_password"]) == 20
    assert data["user"]["must_change_password"] is True


async def test_cannot_delete_master_admin(client: AsyncClient):
    resp = await client.post(
        "/api/setup",
        json={
            "pin": "change-me-1234",
            "username": "admin",
            "email": "admin@example.com",
            "password": "SecurePass123",
        },
    )
    token = resp.json()["access_token"]
    master_id = resp.json()["user"]["id"]

    response = await client.delete(
        f"/api/admin/users/{master_id}", headers=_auth(token)
    )
    assert response.status_code == 403


async def test_cannot_deactivate_self(client: AsyncClient):
    resp = await client.post(
        "/api/setup",
        json={
            "pin": "change-me-1234",
            "username": "admin",
            "email": "admin@example.com",
            "password": "SecurePass123",
        },
    )
    token = resp.json()["access_token"]
    master_id = resp.json()["user"]["id"]

    response = await client.patch(
        f"/api/admin/users/{master_id}",
        json={"is_active": False},
        headers=_auth(token),
    )
    assert response.status_code == 403


async def test_admin_cannot_manage_other_admin(client: AsyncClient):
    master_token = await _setup_and_login(client)

    # Create two admins
    resp1 = await client.post(
        "/api/admin/users",
        json={
            "username": "admin1",
            "email": "a1@example.com",
            "display_name": "Admin 1",
            "role": "admin",
        },
        headers=_auth(master_token),
    )
    resp2 = await client.post(
        "/api/admin/users",
        json={
            "username": "admin2",
            "email": "a2@example.com",
            "display_name": "Admin 2",
            "role": "admin",
        },
        headers=_auth(master_token),
    )
    admin2_id = resp2.json()["user"]["id"]
    admin1_pw = resp1.json()["generated_password"]

    # Login as admin1 and change password
    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "admin1", "password": admin1_pw},
    )
    mcp_token = login_resp.json()["access_token"]
    pw_resp = await client.patch(
        "/api/auth/password",
        json={"current_password": admin1_pw, "new_password": "Admin1Pass"},
        headers=_auth(mcp_token),
    )
    admin1_token = pw_resp.json()["access_token"]

    # Admin1 tries to update Admin2 — should fail
    response = await client.patch(
        f"/api/admin/users/{admin2_id}",
        json={"display_name": "Hacked"},
        headers=_auth(admin1_token),
    )
    assert response.status_code == 403


async def test_login_inactive_user_rejected(client: AsyncClient):
    token = await _setup_and_login(client)

    # Create a user, then deactivate them
    create_resp = await client.post(
        "/api/admin/users",
        json={
            "username": "testuser",
            "email": "test@example.com",
            "display_name": "Test User",
        },
        headers=_auth(token),
    )
    user_id = create_resp.json()["user"]["id"]
    generated_pw = create_resp.json()["generated_password"]

    await client.delete(
        f"/api/admin/users/{user_id}",
        headers=_auth(token),
    )

    # Login as deactivated user should fail
    response = await client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": generated_pw},
    )
    assert response.status_code == 403


async def test_must_change_password_restricts_access(client: AsyncClient):
    admin_token = await _setup_and_login(client)

    # Create user (gets must_change_password=True)
    create_resp = await client.post(
        "/api/admin/users",
        json={
            "username": "newuser",
            "email": "new@example.com",
            "display_name": "New User",
        },
        headers=_auth(admin_token),
    )
    generated_pw = create_resp.json()["generated_password"]

    # Login as new user
    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "newuser", "password": generated_pw},
    )
    mcp_token = login_resp.json()["access_token"]

    # Trying to access admin endpoints should fail with 403
    list_resp = await client.get(
        "/api/admin/users",
        headers=_auth(mcp_token),
    )
    assert list_resp.status_code == 403

    # But password change should work
    pw_resp = await client.patch(
        "/api/auth/password",
        json={
            "current_password": generated_pw,
            "new_password": "MyNewPassword789",
        },
        headers=_auth(mcp_token),
    )
    assert pw_resp.status_code == 200

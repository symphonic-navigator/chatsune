import asyncio
import base64
import secrets

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


# ---------------------------------------------------------------------------
# POST /api/invitations/{token}/register
# ---------------------------------------------------------------------------


def _make_register_body(username: str = "alice", email: str = "alice@example.com"):
    """Test vectors mirroring what a real client would send.

    Real clients derive h_auth/h_kek from password+salt via Argon2; for
    backend-only tests we can use fixed strings. The recovery key MUST
    use the canonical 32-significant-character Crockford-base32 format —
    decode_recovery_key rejects anything else, so a plain
    ``secrets.token_urlsafe`` will not do.
    """
    from backend.modules.user._recovery_key import generate_recovery_key

    return {
        "username": username,
        "email": email,
        "display_name": "Alice",
        "h_auth": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "h_kek": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "recovery_key": generate_recovery_key(),
    }


@pytest.mark.asyncio
async def test_register_creates_user_and_marks_token_used(
    client, seeded_admin_token, user_key_service, db
):
    _, admin_token = seeded_admin_token
    create_resp = await client.post(
        "/api/admin/invitations",
        json={},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    token = create_resp.json()["token"]

    body = _make_register_body()
    resp = await client.post(f"/api/invitations/{token}/register", json=body)
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["success"] is True
    assert out["user_id"]

    # Token now used and points at the new user.
    doc = await db["invitation_tokens"].find_one({"token": token})
    assert doc["used"] is True
    assert doc["used_by_user_id"] == out["user_id"]

    # User created with role=user. User IDs are UUID strings (str(uuid4)),
    # not ObjectIds — see backend.modules.user._repository.UserRepository.create.
    user = await db["users"].find_one({"_id": out["user_id"]})
    assert user is not None
    assert user["role"] == "user"
    assert user["must_change_password"] is False


@pytest.mark.asyncio
async def test_register_with_used_token_returns_410(
    client, seeded_admin_token, user_key_service
):
    _, admin_token = seeded_admin_token
    create_resp = await client.post(
        "/api/admin/invitations",
        json={},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    token = create_resp.json()["token"]

    first = await client.post(
        f"/api/invitations/{token}/register",
        json=_make_register_body("bob1", "bob1@example.com"),
    )
    assert first.status_code == 200, first.text

    resp = await client.post(
        f"/api/invitations/{token}/register",
        json=_make_register_body("bob2", "bob2@example.com"),
    )
    assert resp.status_code == 410


@pytest.mark.asyncio
async def test_register_with_unknown_token_returns_410(client, clean_db):
    resp = await client.post(
        "/api/invitations/garbage-token/register",
        json=_make_register_body(),
    )
    assert resp.status_code == 410


@pytest.mark.asyncio
async def test_register_with_expired_token_returns_410(
    client, seeded_admin_token, user_key_service, db
):
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

    resp = await client.post(
        f"/api/invitations/{token}/register",
        json=_make_register_body(),
    )
    assert resp.status_code == 410


@pytest.mark.asyncio
async def test_register_username_collision_returns_409_and_token_unused(
    client, seeded_admin_token, user_key_service, db
):
    _, admin_token = seeded_admin_token

    # The test client fixture bypasses FastAPI's startup lifespan, so the
    # production unique-index on ``users.username`` is not auto-created.
    # The DuplicateKeyError path under test depends on that index, so we
    # build it explicitly here to mirror the production schema.
    from backend.modules.user import UserRepository
    await UserRepository(db).create_indexes()

    # Pre-create a user named "taken" via the existing admin endpoint.
    create_user_resp = await client.post(
        "/api/admin/users",
        json={
            "username": "taken",
            "email": "taken@example.com",
            "display_name": "T",
            "role": "user",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_user_resp.status_code == 201, create_user_resp.text

    create_resp = await client.post(
        "/api/admin/invitations",
        json={},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    token = create_resp.json()["token"]

    body = _make_register_body(username="taken", email="other@example.com")
    resp = await client.post(f"/api/invitations/{token}/register", json=body)
    assert resp.status_code == 409, resp.text

    doc = await db["invitation_tokens"].find_one({"token": token})
    assert doc["used"] is False, (
        "Token was marked used despite registration failing — rollback broken"
    )


@pytest.mark.asyncio
async def test_register_concurrent_same_token_only_one_succeeds(
    client, seeded_admin_token, user_key_service
):
    _, admin_token = seeded_admin_token
    create_resp = await client.post(
        "/api/admin/invitations",
        json={},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    token = create_resp.json()["token"]

    body_a = _make_register_body("conc-a", "a@example.com")
    body_b = _make_register_body("conc-b", "b@example.com")

    results = await asyncio.gather(
        client.post(f"/api/invitations/{token}/register", json=body_a),
        client.post(f"/api/invitations/{token}/register", json=body_b),
        return_exceptions=False,
    )
    statuses = sorted(r.status_code for r in results)
    assert statuses == [200, 410], (
        f"Expected exactly one 200 and one 410, got {statuses}"
    )


@pytest.mark.asyncio
async def test_register_creates_user_with_role_user_no_escalation(
    client, seeded_admin_token, user_key_service, db
):
    """An invitation token can NEVER create an admin or master_admin."""
    _, admin_token = seeded_admin_token
    create_resp = await client.post(
        "/api/admin/invitations",
        json={},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    token = create_resp.json()["token"]

    body = _make_register_body("regularalice", "regular@example.com")
    resp = await client.post(f"/api/invitations/{token}/register", json=body)
    assert resp.status_code == 200, resp.text
    user_id = resp.json()["user_id"]

    user = await db["users"].find_one({"_id": user_id})
    assert user["role"] == "user"
    assert user["role"] != "admin"
    assert user["role"] != "master_admin"

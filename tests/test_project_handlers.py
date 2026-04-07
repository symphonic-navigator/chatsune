import asyncio

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


async def test_list_projects_empty(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.get("/api/projects", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_projects_requires_auth(client: AsyncClient):
    resp = await client.get("/api/projects")
    assert resp.status_code == 401


async def test_create_project(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.post(
        "/api/projects",
        json={"title": "Writing", "emoji": "✏️", "description": "for writing"},
        headers=_auth(token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Writing"
    assert data["emoji"] == "✏️"
    assert data["description"] == "for writing"
    assert data["nsfw"] is False
    assert data["pinned"] is False
    assert data["sort_order"] == 0
    assert "id" in data
    assert "created_at" in data


async def test_create_project_minimal(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.post(
        "/api/projects", json={"title": "Hi"}, headers=_auth(token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Hi"
    assert data["emoji"] is None
    assert data["description"] == ""


async def test_create_project_blank_title_rejected(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.post(
        "/api/projects", json={"title": "   "}, headers=_auth(token),
    )
    assert resp.status_code == 422


async def test_create_project_multi_grapheme_emoji_rejected(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.post(
        "/api/projects",
        json={"title": "ok", "emoji": "🔥🔥"},
        headers=_auth(token),
    )
    assert resp.status_code == 422


async def test_get_project(client: AsyncClient):
    token = await _setup_and_login(client)
    create_resp = await client.post(
        "/api/projects", json={"title": "x"}, headers=_auth(token),
    )
    pid = create_resp.json()["id"]
    resp = await client.get(f"/api/projects/{pid}", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["id"] == pid


async def test_get_project_not_found(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.get("/api/projects/nonexistent", headers=_auth(token))
    assert resp.status_code == 404


async def test_list_orders_newest_first(client: AsyncClient):
    token = await _setup_and_login(client)
    for title in ["A", "B", "C"]:
        await client.post("/api/projects", json={"title": title}, headers=_auth(token))
        await asyncio.sleep(0.005)
    resp = await client.get("/api/projects", headers=_auth(token))
    titles = [p["title"] for p in resp.json()]
    assert titles == ["C", "B", "A"]


async def test_patch_title(client: AsyncClient):
    token = await _setup_and_login(client)
    pid = (await client.post(
        "/api/projects", json={"title": "Old"}, headers=_auth(token),
    )).json()["id"]

    resp = await client.patch(
        f"/api/projects/{pid}", json={"title": "New"}, headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "New"


async def test_patch_emoji_set(client: AsyncClient):
    token = await _setup_and_login(client)
    pid = (await client.post(
        "/api/projects", json={"title": "x"}, headers=_auth(token),
    )).json()["id"]

    resp = await client.patch(
        f"/api/projects/{pid}", json={"emoji": "🔥"}, headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["emoji"] == "🔥"


async def test_patch_emoji_explicit_null_clears(client: AsyncClient):
    token = await _setup_and_login(client)
    pid = (await client.post(
        "/api/projects",
        json={"title": "x", "emoji": "🔥"},
        headers=_auth(token),
    )).json()["id"]

    resp = await client.patch(
        f"/api/projects/{pid}", json={"emoji": None}, headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["emoji"] is None


async def test_patch_emoji_omitted_preserves(client: AsyncClient):
    token = await _setup_and_login(client)
    pid = (await client.post(
        "/api/projects",
        json={"title": "x", "emoji": "🔥"},
        headers=_auth(token),
    )).json()["id"]

    resp = await client.patch(
        f"/api/projects/{pid}", json={"title": "y"}, headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "y"
    assert body["emoji"] == "🔥"


async def test_patch_other_user_returns_404(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.patch(
        "/api/projects/nonexistent", json={"title": "x"}, headers=_auth(token),
    )
    assert resp.status_code == 404


async def test_patch_invalid_title_rejected(client: AsyncClient):
    token = await _setup_and_login(client)
    pid = (await client.post(
        "/api/projects", json={"title": "x"}, headers=_auth(token),
    )).json()["id"]
    resp = await client.patch(
        f"/api/projects/{pid}", json={"title": "   "}, headers=_auth(token),
    )
    assert resp.status_code == 422


async def test_delete_project(client: AsyncClient):
    token = await _setup_and_login(client)
    pid = (await client.post(
        "/api/projects", json={"title": "x"}, headers=_auth(token),
    )).json()["id"]

    resp = await client.delete(f"/api/projects/{pid}", headers=_auth(token))
    assert resp.status_code == 204

    get_resp = await client.get(f"/api/projects/{pid}", headers=_auth(token))
    assert get_resp.status_code == 404


async def test_delete_other_user_returns_404(client: AsyncClient):
    token = await _setup_and_login(client)
    resp = await client.delete("/api/projects/nonexistent", headers=_auth(token))
    assert resp.status_code == 404

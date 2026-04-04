from httpx import AsyncClient


async def _setup_admin(client: AsyncClient) -> str:
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


async def _setup_regular_user(client: AsyncClient, admin_token: str) -> str:
    create_resp = await client.post(
        "/api/admin/users",
        json={
            "username": "regular",
            "display_name": "Regular User",
            "email": "user@example.com",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    generated_pw = create_resp.json()["generated_password"]
    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "regular", "password": generated_pw},
    )
    mcp_token = login_resp.json()["access_token"]

    # Change password to clear must_change_password flag
    change_resp = await client.patch(
        "/api/auth/password",
        json={"current_password": generated_pw, "new_password": "NewSecurePass123"},
        headers={"Authorization": f"Bearer {mcp_token}"},
    )
    return change_resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_get_config_returns_defaults_when_none_exists(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.get(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["model_unique_id"] == "ollama_cloud:llama3"
    assert data["is_favourite"] is False
    assert data["is_hidden"] is False
    assert data["notes"] is None
    assert data["system_prompt_addition"] is None


async def test_set_user_model_config(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        json={
            "is_favourite": True,
            "notes": "Good for general chat",
            "system_prompt_addition": "Focus on the last message in context.",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_favourite"] is True
    assert data["is_hidden"] is False
    assert data["notes"] == "Good for general chat"
    assert data["system_prompt_addition"] == "Focus on the last message in context."


async def test_update_config_partial(client: AsyncClient):
    token = await _setup_admin(client)
    await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        json={"is_favourite": True, "notes": "Nice model"},
        headers=_auth(token),
    )
    resp = await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        json={"is_hidden": True},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_favourite"] is True
    assert data["notes"] == "Nice model"
    assert data["is_hidden"] is True


async def test_delete_config_resets_to_defaults(client: AsyncClient):
    token = await _setup_admin(client)
    await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        json={"is_favourite": True, "notes": "Great"},
        headers=_auth(token),
    )
    resp = await client.delete(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        headers=_auth(token),
    )
    assert resp.status_code == 200

    resp = await client.get(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_favourite"] is False
    assert data["is_hidden"] is False
    assert data["notes"] is None


async def test_delete_config_when_none_exists(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.delete(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_favourite"] is False


async def test_list_user_configs(client: AsyncClient):
    token = await _setup_admin(client)
    await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        json={"is_favourite": True},
        headers=_auth(token),
    )
    await client.put(
        "/api/llm/providers/ollama_cloud/models/mistral/user-config",
        json={"notes": "Fast"},
        headers=_auth(token),
    )
    resp = await client.get(
        "/api/llm/user-model-configs",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    unique_ids = [c["model_unique_id"] for c in data]
    assert "ollama_cloud:llama3" in unique_ids
    assert "ollama_cloud:mistral" in unique_ids


async def test_configs_are_user_scoped(client: AsyncClient):
    admin_token = await _setup_admin(client)
    user_token = await _setup_regular_user(client, admin_token)

    await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        json={"is_favourite": True},
        headers=_auth(admin_token),
    )

    resp = await client.get(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        headers=_auth(user_token),
    )
    assert resp.status_code == 200
    assert resp.json()["is_favourite"] is False


async def test_unknown_provider_returns_404(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.put(
        "/api/llm/providers/nonexistent/models/llama3/user-config",
        json={"is_favourite": True},
        headers=_auth(token),
    )
    assert resp.status_code == 404


async def test_set_custom_display_name(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        json={"custom_display_name": "My Llama"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["custom_display_name"] == "My Llama"
    assert data["custom_context_window"] is None


async def test_set_custom_context_window(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        json={"custom_context_window": 128_000},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["custom_context_window"] == 128_000


async def test_custom_display_name_too_long_rejected(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        json={"custom_display_name": "x" * 101},
        headers=_auth(token),
    )
    assert resp.status_code == 422


async def test_custom_context_window_below_minimum_rejected(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        json={"custom_context_window": 32_000},
        headers=_auth(token),
    )
    assert resp.status_code == 422


async def test_partial_update_preserves_new_fields(client: AsyncClient):
    token = await _setup_admin(client)
    await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        json={"custom_display_name": "My Llama", "custom_context_window": 128_000},
        headers=_auth(token),
    )
    resp = await client.put(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        json={"is_favourite": True},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["custom_display_name"] == "My Llama"
    assert data["custom_context_window"] == 128_000
    assert data["is_favourite"] is True


async def test_get_config_returns_new_field_defaults(client: AsyncClient):
    token = await _setup_admin(client)
    resp = await client.get(
        "/api/llm/providers/ollama_cloud/models/llama3/user-config",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["custom_display_name"] is None
    assert data["custom_context_window"] is None

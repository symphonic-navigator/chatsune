"""Mindspace Phase 1 — POST /api/projects must persist knowledge_library_ids.

The ``ProjectCreateDto`` already declares ``knowledge_library_ids`` and
the repo's ``create()`` accepts it, but the handler used to drop the
field on the floor — POST with a list of libraries silently created an
empty project. Spec §6.4 (Project-Create-Modal) explicitly lists
Knowledge Libraries as a create-form field.
"""

import pytest_asyncio
from httpx import AsyncClient

from backend.dependencies import require_active_session
from backend.main import app


@pytest_asyncio.fixture
async def auth_user_id():
    user_id = "u-project-create-test"
    app.dependency_overrides[require_active_session] = lambda: {
        "sub": user_id,
        "role": "user",
        "session_id": "sess-project-create-test",
    }
    yield user_id
    app.dependency_overrides.pop(require_active_session, None)


async def test_create_project_persists_knowledge_library_ids(
    client: AsyncClient, auth_user_id, db,
):
    resp = await client.post(
        "/api/projects",
        json={"title": "P", "knowledge_library_ids": ["L1", "L2"]},
    )
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    assert resp.json()["knowledge_library_ids"] == ["L1", "L2"]

    # Round-trip via GET to confirm the value reached MongoDB and the
    # to-DTO mapper preserves it.
    get_resp = await client.get(f"/api/projects/{pid}")
    assert get_resp.status_code == 200
    assert get_resp.json()["knowledge_library_ids"] == ["L1", "L2"]


async def test_create_project_defaults_libraries_empty_when_omitted(
    client: AsyncClient, auth_user_id, db,
):
    """Omitting the field still yields an empty list — the handler must
    not break the no-libraries default path."""
    resp = await client.post("/api/projects", json={"title": "P"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["knowledge_library_ids"] == []

"""Mindspace Phase 1 — PATCH /api/personas/{id} default_project_id.

The persona PATCH handler must distinguish three caller intents for
``default_project_id``:

1. field omitted → leave the persisted value alone
2. field set to a string → assign that project as the default
3. field set to ``null`` → clear the persisted default

The third case is the load-bearing one: ``model_dump(exclude_none=True)``
drops a null value before it reaches the repo, which would silently make
"clear the default project" a no-op. The handler re-includes the field
when ``model_fields_set`` shows the caller set it explicitly, mirroring
the existing ``vision_fallback_model`` idiom.
"""

from datetime import UTC, datetime

import pytest_asyncio
from httpx import AsyncClient

from backend.dependencies import require_active_session
from backend.main import app


@pytest_asyncio.fixture
async def auth_user_id():
    """Override session auth so the test calls land on a stable user."""
    user_id = "u-default-proj-test"
    app.dependency_overrides[require_active_session] = lambda: {
        "sub": user_id,
        "role": "user",
        "session_id": "sess-default-proj-test",
    }
    yield user_id
    app.dependency_overrides.pop(require_active_session, None)


async def _seed_persona(
    db, user_id: str, *, default_project_id: str | None,
) -> str:
    """Insert a minimal persona document directly. Returns the new ID."""
    from uuid import uuid4

    now = datetime.now(UTC).replace(tzinfo=None)
    pid = f"persona-{uuid4().hex[:8]}"
    doc = {
        "_id": pid,
        "user_id": user_id,
        "name": "Test",
        "tagline": "x",
        "model_unique_id": None,
        "system_prompt": "...",
        "temperature": 0.8,
        "reasoning_enabled": False,
        "soft_cot_enabled": False,
        "vision_fallback_model": None,
        "nsfw": False,
        "use_memory": True,
        "colour_scheme": "solar",
        "display_order": 0,
        "monogram": "TS",
        "pinned": False,
        "profile_image": None,
        "profile_crop": None,
        "mcp_config": None,
        "voice_config": None,
        "integration_configs": {},
        "integrations_config": None,
        "default_project_id": default_project_id,
        "created_at": now,
        "updated_at": now,
        "last_used_at": None,
    }
    await db["personas"].insert_one(doc)
    return pid


async def test_patch_omitting_default_project_id_leaves_field_alone(
    client: AsyncClient, auth_user_id, db,
):
    """A PATCH that omits ``default_project_id`` must not touch the
    persisted value. Bumps a different field to keep the body non-empty."""
    pid = await _seed_persona(db, auth_user_id, default_project_id="proj-orig")

    resp = await client.patch(
        f"/api/personas/{pid}",
        json={"tagline": "new tagline"},
    )
    assert resp.status_code == 200, resp.text

    fetched = await db["personas"].find_one({"_id": pid})
    assert fetched["default_project_id"] == "proj-orig"


async def test_patch_setting_default_project_id_assigns(
    client: AsyncClient, auth_user_id, db,
):
    pid = await _seed_persona(db, auth_user_id, default_project_id=None)

    resp = await client.patch(
        f"/api/personas/{pid}",
        json={"default_project_id": "proj-new"},
    )
    assert resp.status_code == 200, resp.text

    fetched = await db["personas"].find_one({"_id": pid})
    assert fetched["default_project_id"] == "proj-new"


async def test_patch_explicit_null_clears_default_project_id(
    client: AsyncClient, auth_user_id, db,
):
    """The headline regression: an explicit ``null`` must clear the
    persisted default. ``model_dump(exclude_none=True)`` drops the key,
    so the handler re-adds it via ``model_fields_set`` — same idiom as
    ``vision_fallback_model``."""
    pid = await _seed_persona(db, auth_user_id, default_project_id="proj-orig")

    resp = await client.patch(
        f"/api/personas/{pid}",
        json={"default_project_id": None},
    )
    assert resp.status_code == 200, resp.text

    fetched = await db["personas"].find_one({"_id": pid})
    assert fetched["default_project_id"] is None

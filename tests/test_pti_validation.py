"""Test trigger-phrase normalisation and size cap at the API layer."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import httpx


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_library(
    client: httpx.AsyncClient, token: str, name: str = "Lore", **extra
) -> str:
    res = await client.post(
        "/api/knowledge/libraries",
        json={"name": name, **extra},
        headers=_auth(token),
    )
    assert res.status_code == 201
    return res.json()["id"]


@pytest.mark.asyncio
async def test_create_document_with_triggers_within_limit_passes(
    client, seeded_admin_token,
):
    _admin_id, token = seeded_admin_token
    library_id = await _make_library(client, token)

    with patch(
        "backend.modules.embedding.embed_texts", new_callable=AsyncMock
    ):
        res = await client.post(
            f"/api/knowledge/libraries/{library_id}/documents",
            json={
                "title": "Small",
                "content": "x" * 100,
                "media_type": "text/markdown",
                "trigger_phrases": ["Andromedagalaxie!"],
            },
            headers=_auth(token),
        )
    assert res.status_code == 201
    body = res.json()
    # Phrase was normalised on save (casefolded + whitespace collapsed)
    assert body["trigger_phrases"] == ["andromedagalaxie!"]


@pytest.mark.asyncio
async def test_create_document_with_triggers_over_limit_rejected(
    client, seeded_admin_token,
):
    _admin_id, token = seeded_admin_token
    library_id = await _make_library(client, token)

    # No mock needed — validation fires before embedding is triggered
    res = await client.post(
        f"/api/knowledge/libraries/{library_id}/documents",
        json={
            "title": "Big",
            "content": "x" * 25_000,
            "media_type": "text/markdown",
            "trigger_phrases": ["foo"],
        },
        headers=_auth(token),
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_create_document_no_triggers_any_size_passes(
    client, seeded_admin_token,
):
    _admin_id, token = seeded_admin_token
    library_id = await _make_library(client, token)

    with patch(
        "backend.modules.embedding.embed_texts", new_callable=AsyncMock
    ):
        res = await client.post(
            f"/api/knowledge/libraries/{library_id}/documents",
            json={
                "title": "Reference",
                "content": "x" * 50_000,
                "media_type": "text/markdown",
                "trigger_phrases": [],
            },
            headers=_auth(token),
        )
    assert res.status_code == 201


@pytest.mark.asyncio
async def test_update_document_add_triggers_to_oversize_rejected(
    client, seeded_admin_token,
):
    _admin_id, token = seeded_admin_token
    library_id = await _make_library(client, token)

    with patch(
        "backend.modules.embedding.embed_texts", new_callable=AsyncMock
    ):
        create = await client.post(
            f"/api/knowledge/libraries/{library_id}/documents",
            json={
                "title": "Big",
                "content": "x" * 30_000,
                "media_type": "text/markdown",
                "trigger_phrases": [],
            },
            headers=_auth(token),
        )
    assert create.status_code == 201
    doc_id = create.json()["id"]

    # No mock needed — validation fires before any embedding
    res = await client.put(
        f"/api/knowledge/libraries/{library_id}/documents/{doc_id}",
        json={"trigger_phrases": ["foo"]},
        headers=_auth(token),
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_library_default_refresh_round_trip(client, seeded_admin_token):
    _admin_id, token = seeded_admin_token

    res = await client.post(
        "/api/knowledge/libraries",
        json={"name": "Lib2", "default_refresh": "often"},
        headers=_auth(token),
    )
    assert res.status_code == 201
    assert res.json()["default_refresh"] == "often"

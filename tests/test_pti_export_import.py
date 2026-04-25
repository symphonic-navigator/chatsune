"""Round-trip PTI fields through library export/import."""
from __future__ import annotations

import datetime
import gzip
import io
import json
import tarfile

import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_export_includes_pti_fields(client, db):
    """Export archive contains PTI fields from library and documents."""
    from backend.modules.knowledge._export import export_library_archive

    await db.knowledge_libraries.insert_one({
        "_id": "lib1", "user_id": "u1", "name": "Lore",
        "description": "d", "nsfw": False,
        "default_refresh": "often",
        "document_count": 1,
        "created_at": datetime.datetime.now(datetime.UTC),
        "updated_at": datetime.datetime.now(datetime.UTC),
    })
    await db.knowledge_documents.insert_one({
        "_id": "doc1", "library_id": "lib1", "user_id": "u1",
        "title": "Andromeda", "content": "c", "media_type": "text/markdown",
        "trigger_phrases": ["andromedagalaxie"], "refresh": "rarely",
        "size_bytes": 1, "chunk_count": 0,
        "embedding_status": "completed", "embedding_error": None,
        "retry_count": 0,
        "created_at": datetime.datetime.now(datetime.UTC),
        "updated_at": datetime.datetime.now(datetime.UTC),
    })

    # export_library_archive returns (bytes, filename)
    archive, _filename = await export_library_archive(user_id="u1", library_id="lib1")

    tar = tarfile.open(
        fileobj=gzip.GzipFile(fileobj=io.BytesIO(archive), mode="rb"),
    )
    lib = json.loads(tar.extractfile("library.json").read())
    docs = json.loads(tar.extractfile("documents.json").read())

    assert lib["default_refresh"] == "often"
    assert docs[0]["trigger_phrases"] == ["andromedagalaxie"]
    assert docs[0]["refresh"] == "rarely"


def _build_archive(manifest: dict, library: dict, documents: list) -> bytes:
    """Helper: package three dicts into a .chatsune-knowledge.tar.gz archive."""
    buf = io.BytesIO()
    mtime = int(datetime.datetime.now(datetime.UTC).timestamp())
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        with tarfile.open(fileobj=gz, mode="w") as tar:
            for name, body in [
                ("manifest.json", manifest),
                ("library.json", library),
                ("documents.json", documents),
            ]:
                data = json.dumps(body).encode()
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                info.mtime = mtime
                tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


_MANIFEST = {"format": "chatsune/knowledge", "version": 1}


@pytest.mark.asyncio
async def test_import_restores_pti_fields(client, seeded_admin_token):
    """Import restores trigger_phrases, refresh, default_refresh."""
    _user_id, token = seeded_admin_token
    headers = {"Authorization": f"Bearer {token}"}

    archive_bytes = _build_archive(
        manifest=_MANIFEST,
        library={
            "name": "Imported", "description": None, "nsfw": False,
            "default_refresh": "often",
        },
        documents=[{
            "title": "Andromeda", "content": "c",
            "media_type": "text/markdown",
            "trigger_phrases": ["andromedagalaxie"],
            "refresh": "rarely",
        }],
    )

    with patch("backend.modules.embedding.embed_texts", new_callable=AsyncMock):
        res = await client.post(
            "/api/knowledge/libraries/import",
            files={"file": ("lib.tar.gz", archive_bytes, "application/gzip")},
            headers=headers,
        )

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["default_refresh"] == "often"


@pytest.mark.asyncio
async def test_import_old_archive_without_pti_fields_uses_defaults(
    client, seeded_admin_token,
):
    """Old archives (pre-PTI) import cleanly with sensible defaults."""
    _user_id, token = seeded_admin_token
    headers = {"Authorization": f"Bearer {token}"}

    archive_bytes = _build_archive(
        manifest=_MANIFEST,
        library={"name": "Old Library", "description": None, "nsfw": False},
        documents=[{
            "title": "Old Doc", "content": "c", "media_type": "text/markdown",
        }],
    )

    with patch("backend.modules.embedding.embed_texts", new_callable=AsyncMock):
        res = await client.post(
            "/api/knowledge/libraries/import",
            files={"file": ("lib.tar.gz", archive_bytes, "application/gzip")},
            headers=headers,
        )

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["default_refresh"] == "standard"  # default

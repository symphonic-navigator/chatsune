"""Storage module -- file uploads, quota management.

Public API: import only from this file.
"""

from uuid import uuid4

from backend.modules.storage._handlers import router
from backend.modules.storage._repository import StorageRepository
from backend.modules.storage._blob_store import BlobStore
from backend.database import get_db
from shared.dtos.export import StorageBundleDto, StorageFileRecordDto


async def init_indexes(db) -> None:
    await StorageRepository(db).create_indexes()


async def get_file_metadata(file_id: str, user_id: str) -> dict | None:
    """Cross-module API: get a single file's metadata."""
    db = get_db()
    repo = StorageRepository(db)
    return await repo.find_by_id(file_id, user_id)


async def get_files_by_ids(file_ids: list[str], user_id: str) -> list[dict]:
    """Cross-module API: get multiple files' metadata + binary data for chat attachment injection."""
    db = get_db()
    repo = StorageRepository(db)
    blob_store = BlobStore()
    docs = await repo.find_by_ids(file_ids, user_id)
    results = []
    for doc in docs:
        data = blob_store.load(doc["user_id"], doc["_id"])
        results.append({**doc, "data": data})
    return results


async def count_for_sessions(session_ids: list[str], user_id: str) -> int:
    """Mindspace: count storage files referenced by the given chat sessions.

    Used by the project usage-counts endpoint and (indirectly) by the
    delete-modal counts row. Walks ``chat_messages.attachment_refs``
    and ``attachment_ids`` via the chat module's public API to find
    the file-ids; then counts those files in the storage collection.
    Empty input → 0 with no DB round-trip.
    """
    if not session_ids:
        return 0
    from backend.modules import chat as chat_service

    file_ids = await chat_service.list_attachment_ids_for_sessions(
        session_ids, user_id,
    )
    if not file_ids:
        return 0
    repo = StorageRepository(get_db())
    return await repo.count_by_ids(file_ids, user_id)


async def list_for_sessions(
    session_ids: list[str], user_id: str,
    *,
    sort_by: str = "date",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Mindspace: list storage files referenced by the given chat sessions.

    Same lookup as :func:`count_for_sessions` but returns full file
    documents sorted/paginated. Used by the project-filtered
    ``GET /api/storage/files?project_id=…`` endpoint.
    """
    if not session_ids:
        return []
    from backend.modules import chat as chat_service

    file_ids = await chat_service.list_attachment_ids_for_sessions(
        session_ids, user_id,
    )
    if not file_ids:
        return []
    repo = StorageRepository(get_db())
    return await repo.list_by_ids_sorted(
        file_ids, user_id,
        sort_by=sort_by, order=order, limit=limit, offset=offset,
    )


async def get_cached_vision_description(
    file_id: str, user_id: str, model_id: str,
) -> str | None:
    """Cross-module API: read a cached vision description, or None if missing."""
    db = get_db()
    repo = StorageRepository(db)
    return await repo.get_vision_description(file_id, user_id, model_id)


async def store_vision_description(
    file_id: str, user_id: str, model_id: str, text: str,
) -> None:
    """Cross-module API: persist a vision description for a (file, model) pair."""
    db = get_db()
    repo = StorageRepository(db)
    await repo.store_vision_description(file_id, user_id, model_id, text)


async def delete_by_persona(user_id: str, persona_id: str) -> int:
    """Delete all storage files (DB + physical) for a persona."""
    count, _ = await delete_by_persona_with_warnings(user_id, persona_id)
    return count


async def delete_by_persona_with_warnings(
    user_id: str, persona_id: str,
) -> tuple[int, list[str]]:
    """Delete all storage files (DB + physical) for a persona.

    Returns ``(deleted_count, warnings)`` where ``warnings`` lists any blobs
    that the BlobStore could not unlink due to a real I/O failure. A missing
    file is NOT a warning — the post-condition (file does not exist) is
    already met.

    Used by the persona cascade-delete report so users see exactly which
    physical files, if any, the system could not purge.
    """
    db = get_db()
    repo = StorageRepository(db)
    file_ids = await repo.delete_by_persona(user_id, persona_id)
    blob_store = BlobStore()
    warnings: list[str] = []
    for file_id in file_ids:
        warning = blob_store.delete(user_id, file_id)
        if warning:
            warnings.append(warning)
    return len(file_ids), warnings


async def delete_all_for_persona(user_id: str, persona_id: str) -> int:
    """Alias for ``delete_by_persona`` — named for symmetry with other modules
    so the Phase 2 import orchestrator can uniformly call
    ``delete_all_for_persona`` on failure.
    """
    return await delete_by_persona(user_id, persona_id)


async def bulk_export_for_persona(
    user_id: str, persona_id: str,
) -> tuple[StorageBundleDto, dict[str, bytes]]:
    """Return storage metadata + blob bytes for every file attached to a persona.

    The returned ``dict`` maps the newly-assigned ``export_id`` (a fresh UUID)
    to the file's raw bytes; the Phase 2 packager streams these into the
    archive using the ``export_id`` as the archive entry name. Files whose
    blob has vanished from disk are skipped with no error — metadata without
    a blob would not round-trip.
    """
    repo = StorageRepository(get_db())
    blob_store = BlobStore()
    docs = await repo.list_for_persona(user_id, persona_id)

    records: list[StorageFileRecordDto] = []
    blobs: dict[str, bytes] = {}

    for doc in docs:
        data = blob_store.load(doc["user_id"], doc["_id"])
        if data is None:
            # Orphaned DB row; skip to avoid an unresolvable import later.
            continue
        export_id = str(uuid4())
        records.append(StorageFileRecordDto(
            export_id=export_id,
            original_name=doc["original_name"],
            display_name=doc["display_name"],
            media_type=doc["media_type"],
            size_bytes=doc["size_bytes"],
            thumbnail_b64=doc.get("thumbnail_b64"),
            text_preview=doc.get("text_preview"),
            vision_descriptions=doc.get("vision_descriptions"),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        ))
        blobs[export_id] = data

    return StorageBundleDto(files=records), blobs


async def bulk_import_for_persona(
    user_id: str,
    persona_id: str,
    bundle: StorageBundleDto,
    blobs: dict[str, bytes],
) -> None:
    """Insert storage file records + blobs for a persona.

    Each file record receives a freshly-generated UUID for ``_id`` and its
    bytes are written to disk via ``BlobStore``. The ``export_id`` from the
    bundle is used only to look up bytes in ``blobs`` — it does not survive
    into the database.

    Files whose blob is missing from ``blobs`` are skipped.
    """
    repo = StorageRepository(get_db())
    blob_store = BlobStore()

    doc_inserts: list[dict] = []
    for rec in bundle.files:
        data = blobs.get(rec.export_id)
        if data is None:
            continue
        new_file_id = str(uuid4())
        rel_path = blob_store.save(user_id, new_file_id, data)
        doc_inserts.append({
            "_id": new_file_id,
            "user_id": user_id,
            "persona_id": persona_id,
            "original_name": rec.original_name,
            "display_name": rec.display_name,
            "media_type": rec.media_type,
            "size_bytes": rec.size_bytes,
            "file_path": rel_path,
            "thumbnail_b64": rec.thumbnail_b64,
            "text_preview": rec.text_preview,
            "vision_descriptions": rec.vision_descriptions,
            "created_at": rec.created_at,
            "updated_at": rec.updated_at,
        })

    await repo.bulk_insert_files(doc_inserts)


__all__ = [
    "router",
    "init_indexes",
    "get_file_metadata",
    "get_files_by_ids",
    "get_cached_vision_description",
    "store_vision_description",
    "delete_by_persona",
    "delete_by_persona_with_warnings",
    "delete_all_for_persona",
    "bulk_export_for_persona",
    "bulk_import_for_persona",
    "count_for_sessions",
    "list_for_sessions",
]

"""Storage module -- file uploads, quota management.

Public API: import only from this file.
"""

from backend.modules.storage._handlers import router
from backend.modules.storage._repository import StorageRepository
from backend.modules.storage._blob_store import BlobStore
from backend.database import get_db


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
    db = get_db()
    repo = StorageRepository(db)
    file_ids = await repo.delete_by_persona(user_id, persona_id)
    blob_store = BlobStore()
    for file_id in file_ids:
        blob_store.delete(user_id, file_id)
    return len(file_ids)


__all__ = [
    "router",
    "init_indexes",
    "get_file_metadata",
    "get_files_by_ids",
    "get_cached_vision_description",
    "store_vision_description",
    "delete_by_persona",
]

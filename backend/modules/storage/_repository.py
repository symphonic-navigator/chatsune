from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING

from shared.dtos.storage import StorageFileDto

_COLLECTION = "storage_files"


class StorageRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._col = db[_COLLECTION]

    async def create_indexes(self) -> None:
        await self._col.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
        await self._col.create_index([("user_id", ASCENDING), ("persona_id", ASCENDING)])

    async def create(self, doc: dict) -> dict:
        await self._col.insert_one(doc)
        return doc

    async def find_by_id(self, file_id: str, user_id: str) -> dict | None:
        return await self._col.find_one({"_id": file_id, "user_id": user_id})

    async def find_by_user(
        self,
        user_id: str,
        persona_id: str | None = None,
        sort_by: str = "date",
        order: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        query: dict = {"user_id": user_id}
        if persona_id:
            query["persona_id"] = persona_id

        sort_field = "created_at" if sort_by == "date" else "size_bytes"
        sort_dir = DESCENDING if order == "desc" else ASCENDING

        cursor = self._col.find(query).sort(sort_field, sort_dir).skip(offset).limit(limit)
        return await cursor.to_list(length=limit)

    async def update_display_name(
        self, file_id: str, user_id: str, display_name: str
    ) -> dict | None:
        result = await self._col.find_one_and_update(
            {"_id": file_id, "user_id": user_id},
            {"$set": {"display_name": display_name, "updated_at": datetime.now(timezone.utc)}},
            return_document=True,
        )
        return result

    async def delete(self, file_id: str, user_id: str) -> bool:
        result = await self._col.delete_one({"_id": file_id, "user_id": user_id})
        return result.deleted_count > 0

    async def delete_by_persona(self, user_id: str, persona_id: str) -> list[str]:
        """Return file IDs belonging to the persona and remove their DB records."""
        cursor = self._col.find(
            {"user_id": user_id, "persona_id": persona_id},
            projection={"_id": 1},
        )
        file_ids = [doc["_id"] async for doc in cursor]
        if not file_ids:
            return []
        await self._col.delete_many({"_id": {"$in": file_ids}})
        return file_ids

    async def list_for_persona(self, user_id: str, persona_id: str) -> list[dict]:
        """Return raw file docs for a persona, oldest first."""
        cursor = self._col.find(
            {"user_id": user_id, "persona_id": persona_id},
        ).sort("created_at", 1)
        return await cursor.to_list(length=100000)

    async def bulk_insert_files(self, docs: list[dict]) -> int:
        """Insert raw file docs (``_id`` already assigned)."""
        if not docs:
            return 0
        result = await self._col.insert_many(docs)
        return len(result.inserted_ids)

    async def get_quota_used(self, user_id: str) -> int:
        pipeline = [
            {"$match": {"user_id": user_id}},
            {"$group": {"_id": None, "total": {"$sum": "$size_bytes"}}},
        ]
        results = await self._col.aggregate(pipeline).to_list(length=1)
        if results:
            return results[0]["total"]
        return 0

    async def find_by_ids(self, file_ids: list[str], user_id: str) -> list[dict]:
        cursor = self._col.find({"_id": {"$in": file_ids}, "user_id": user_id})
        return await cursor.to_list(length=len(file_ids))

    async def list_by_ids_sorted(
        self,
        file_ids: list[str],
        user_id: str,
        *,
        sort_by: str = "date",
        order: str = "desc",
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        """Return a sorted/paginated slice of files by id, scoped to user.

        Mindspace: used by the project-filtered ``list_files`` endpoint
        which first asks chat for the project's session ids, then resolves
        them to the storage-file ids referenced by those sessions, and
        finally asks for a sorted page of those files. Empty input → empty
        list (skip the round-trip).
        """
        if not file_ids:
            return []
        sort_field = "created_at" if sort_by == "date" else "size_bytes"
        sort_dir = DESCENDING if order == "desc" else ASCENDING
        cursor = (
            self._col.find({"_id": {"$in": file_ids}, "user_id": user_id})
            .sort(sort_field, sort_dir)
            .skip(offset)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)

    async def count_by_ids(self, file_ids: list[str], user_id: str) -> int:
        """Count files in the supplied id set that belong to ``user_id``."""
        if not file_ids:
            return 0
        return await self._col.count_documents(
            {"_id": {"$in": file_ids}, "user_id": user_id},
        )

    async def get_vision_description(
        self, file_id: str, user_id: str, model_id: str,
    ) -> str | None:
        """Return cached vision description text for a (file, model) pair."""
        doc = await self._col.find_one(
            {"_id": file_id, "user_id": user_id},
            {f"vision_descriptions.{model_id}": 1},
        )
        if not doc:
            return None
        entry = (doc.get("vision_descriptions") or {}).get(model_id)
        if not entry:
            return None
        return entry.get("text")

    async def store_vision_description(
        self, file_id: str, user_id: str, model_id: str, text: str,
    ) -> None:
        """Persist a vision description for a (file, model) pair. No TTL."""
        await self._col.update_one(
            {"_id": file_id, "user_id": user_id},
            {"$set": {
                f"vision_descriptions.{model_id}": {
                    "text": text,
                    "model_id": model_id,
                    "created_at": datetime.now(timezone.utc),
                }
            }},
        )

    @staticmethod
    def file_to_dto(doc: dict) -> StorageFileDto:
        return StorageFileDto(
            id=doc["_id"],
            user_id=doc["user_id"],
            persona_id=doc.get("persona_id"),
            original_name=doc["original_name"],
            display_name=doc["display_name"],
            media_type=doc["media_type"],
            size_bytes=doc["size_bytes"],
            thumbnail_b64=doc.get("thumbnail_b64"),
            text_preview=doc.get("text_preview"),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )

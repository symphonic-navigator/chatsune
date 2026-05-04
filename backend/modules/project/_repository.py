from datetime import UTC, datetime
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from shared.dtos.project import ProjectDto


class ProjectRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db["projects"]

    async def create_indexes(self) -> None:
        await self._collection.create_index([("user_id", 1), ("created_at", -1)])
        await self._collection.create_index(
            [("user_id", 1), ("pinned", -1), ("sort_order", 1), ("created_at", -1)],
        )

    async def create(
        self,
        user_id: str,
        title: str,
        emoji: str | None,
        description: str | None,
        nsfw: bool,
        knowledge_library_ids: list[str] | None = None,
    ) -> dict:
        now = datetime.now(UTC).replace(tzinfo=None)
        doc = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "title": title,
            "emoji": emoji,
            "description": description,
            "nsfw": nsfw,
            "pinned": False,
            "sort_order": 0,
            # Mindspace: stored as a list so MongoDB can index / query it
            # directly. Defaults to empty when the caller doesn't supply
            # a list — keeps the create path additive.
            "knowledge_library_ids": list(knowledge_library_ids or []),
            "created_at": now,
            "updated_at": now,
        }
        await self._collection.insert_one(doc)
        return doc

    async def find_by_id(self, project_id: str, user_id: str) -> dict | None:
        return await self._collection.find_one(
            {"_id": project_id, "user_id": user_id},
        )

    async def list_for_user(self, user_id: str) -> list[dict]:
        cursor = self._collection.find({"user_id": user_id}).sort("created_at", -1)
        return await cursor.to_list(length=500)

    async def update(
        self, project_id: str, user_id: str, fields: dict,
    ) -> dict | None:
        if not fields:
            return await self.find_by_id(project_id, user_id)
        fields = {**fields, "updated_at": datetime.now(UTC).replace(tzinfo=None)}
        result = await self._collection.update_one(
            {"_id": project_id, "user_id": user_id},
            {"$set": fields},
        )
        if result.matched_count == 0:
            return None
        return await self.find_by_id(project_id, user_id)

    async def delete(self, project_id: str, user_id: str) -> bool:
        result = await self._collection.delete_one(
            {"_id": project_id, "user_id": user_id},
        )
        return result.deleted_count > 0

    async def delete_all_for_user(self, user_id: str) -> int:
        """Delete every project owned by ``user_id``. Returns deleted count.

        Used by the user self-delete cascade (right-to-be-forgotten).
        """
        result = await self._collection.delete_many({"user_id": user_id})
        return result.deleted_count

    @staticmethod
    def to_dto(doc: dict) -> ProjectDto:
        return ProjectDto(
            id=doc["_id"],
            user_id=doc["user_id"],
            title=doc["title"],
            emoji=doc.get("emoji"),
            # Mindspace: ``description`` is now nullable. Pre-Mindspace
            # documents always carried a string (often ``""``); even
            # older legacy fixtures may omit the field entirely. ``get``
            # returns ``None`` in the latter case, matching the new DTO
            # default.
            description=doc.get("description"),
            nsfw=doc.get("nsfw", False),
            pinned=doc.get("pinned", False),
            sort_order=doc.get("sort_order", 0),
            # Mindspace: legacy documents lack this field entirely; the
            # ``[]`` default keeps reads working without a migration.
            knowledge_library_ids=list(doc.get("knowledge_library_ids", []) or []),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )

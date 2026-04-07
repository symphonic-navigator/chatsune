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
        description: str,
        nsfw: bool,
    ) -> dict:
        now = datetime.now(UTC)
        doc = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "title": title,
            "emoji": emoji,
            "description": description,
            "nsfw": nsfw,
            "pinned": False,
            "sort_order": 0,
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

    @staticmethod
    def to_dto(doc: dict) -> ProjectDto:
        return ProjectDto(
            id=doc["_id"],
            user_id=doc["user_id"],
            title=doc["title"],
            emoji=doc.get("emoji"),
            description=doc.get("description", ""),
            nsfw=doc.get("nsfw", False),
            pinned=doc.get("pinned", False),
            sort_order=doc.get("sort_order", 0),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )

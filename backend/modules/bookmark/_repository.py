from datetime import UTC, datetime
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from shared.dtos.bookmark import BookmarkDto


class BookmarkRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._bookmarks = db["bookmarks"]

    async def create_indexes(self) -> None:
        await self._bookmarks.create_index("user_id")
        await self._bookmarks.create_index([("user_id", 1), ("session_id", 1)])
        await self._bookmarks.create_index([("user_id", 1), ("message_id", 1)])

    async def create(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
        persona_id: str,
        title: str,
        scope: str,
    ) -> dict:
        now = datetime.now(UTC)
        count = await self._bookmarks.count_documents({"user_id": user_id, "session_id": session_id})
        doc = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "session_id": session_id,
            "message_id": message_id,
            "persona_id": persona_id,
            "title": title,
            "scope": scope,
            "display_order": count,
            "created_at": now,
        }
        await self._bookmarks.insert_one(doc)
        return doc

    async def find_by_id(self, bookmark_id: str, user_id: str) -> dict | None:
        return await self._bookmarks.find_one({"_id": bookmark_id, "user_id": user_id})

    async def list_by_user(self, user_id: str) -> list[dict]:
        cursor = self._bookmarks.find({"user_id": user_id}).sort("display_order", 1)
        return await cursor.to_list(length=1000)

    async def list_by_session(self, session_id: str, user_id: str) -> list[dict]:
        cursor = self._bookmarks.find(
            {"user_id": user_id, "session_id": session_id},
        ).sort("display_order", 1)
        return await cursor.to_list(length=1000)

    async def update(self, bookmark_id: str, user_id: str, updates: dict) -> dict | None:
        result = await self._bookmarks.find_one_and_update(
            {"_id": bookmark_id, "user_id": user_id},
            {"$set": updates},
            return_document=True,
        )
        return result

    async def reorder(self, user_id: str, ordered_ids: list[str]) -> None:
        from pymongo import UpdateOne
        operations = [
            UpdateOne(
                {"_id": bid, "user_id": user_id},
                {"$set": {"display_order": i}},
            )
            for i, bid in enumerate(ordered_ids)
        ]
        if operations:
            await self._bookmarks.bulk_write(operations, ordered=False)

    async def delete(self, bookmark_id: str, user_id: str) -> bool:
        result = await self._bookmarks.delete_one({"_id": bookmark_id, "user_id": user_id})
        return result.deleted_count > 0

    async def delete_by_message(self, message_id: str) -> int:
        """Delete all bookmarks for a message (cascade on message delete)."""
        result = await self._bookmarks.delete_many({"message_id": message_id})
        return result.deleted_count

    async def delete_by_session(self, session_id: str) -> int:
        """Delete all bookmarks for a session (cascade on session delete)."""
        result = await self._bookmarks.delete_many({"session_id": session_id})
        return result.deleted_count

    @staticmethod
    def to_dto(doc: dict) -> BookmarkDto:
        return BookmarkDto(
            id=doc["_id"],
            user_id=doc["user_id"],
            session_id=doc["session_id"],
            message_id=doc["message_id"],
            persona_id=doc["persona_id"],
            title=doc["title"],
            scope=doc["scope"],
            display_order=doc.get("display_order", 0),
            created_at=doc["created_at"],
        )

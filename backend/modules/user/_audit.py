from datetime import datetime
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from shared.dtos.auth import AuditLogEntryDto


class AuditRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db["audit_log"]

    async def create_indexes(self) -> None:
        await self._collection.create_index("actor_id")
        await self._collection.create_index("action")
        await self._collection.create_index("resource_type")
        await self._collection.create_index("timestamp")

    async def log(
        self,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        detail: dict | None = None,
    ) -> dict:
        doc = {
            "_id": str(uuid4()),
            "timestamp": datetime.utcnow(),
            "actor_id": actor_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "detail": detail,
        }
        await self._collection.insert_one(doc)
        return doc

    async def list_entries(
        self,
        skip: int = 0,
        limit: int = 50,
        actor_id: str | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> list[dict]:
        query: dict = {}
        if actor_id:
            query["actor_id"] = actor_id
        if action:
            query["action"] = action
        if resource_type:
            query["resource_type"] = resource_type
        if resource_id:
            query["resource_id"] = resource_id

        cursor = (
            self._collection.find(query)
            .sort("timestamp", -1)
            .skip(skip)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)

    @staticmethod
    def to_dto(doc: dict) -> AuditLogEntryDto:
        return AuditLogEntryDto(
            id=doc["_id"],
            timestamp=doc["timestamp"],
            actor_id=doc["actor_id"],
            action=doc["action"],
            resource_type=doc["resource_type"],
            resource_id=doc.get("resource_id"),
            detail=doc.get("detail"),
        )

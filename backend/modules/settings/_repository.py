from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

from shared.dtos.settings import AppSettingDto


class SettingsRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db["app_settings"]

    async def create_indexes(self) -> None:
        pass  # _id is the key, no extra indexes needed

    async def find(self, key: str) -> dict | None:
        return await self._collection.find_one({"_id": key})

    async def upsert(self, key: str, value: str, updated_by: str) -> dict:
        now = datetime.now(UTC)
        await self._collection.update_one(
            {"_id": key},
            {
                "$set": {
                    "value": value,
                    "updated_at": now,
                    "updated_by": updated_by,
                }
            },
            upsert=True,
        )
        return await self.find(key)

    async def delete(self, key: str) -> bool:
        result = await self._collection.delete_one({"_id": key})
        return result.deleted_count > 0

    async def list_all(self) -> list[dict]:
        cursor = self._collection.find()
        return await cursor.to_list(length=1000)

    @staticmethod
    def to_dto(doc: dict) -> AppSettingDto:
        return AppSettingDto(
            key=doc["_id"],
            value=doc["value"],
            updated_at=doc["updated_at"],
            updated_by=doc["updated_by"],
        )

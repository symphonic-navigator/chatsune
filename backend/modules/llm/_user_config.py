from datetime import UTC, datetime
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from shared.dtos.llm import UserModelConfigDto


class UserModelConfigRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db["llm_user_model_configs"]

    async def create_indexes(self) -> None:
        await self._collection.create_index(
            [("user_id", 1), ("model_unique_id", 1)], unique=True
        )

    async def find(self, user_id: str, model_unique_id: str) -> dict | None:
        return await self._collection.find_one(
            {"user_id": user_id, "model_unique_id": model_unique_id}
        )

    async def upsert(
        self,
        user_id: str,
        model_unique_id: str,
        is_favourite: bool | None = None,
        is_hidden: bool | None = None,
        custom_display_name: str | None = None,
        custom_context_window: int | None = None,
        notes: str | None = None,
        system_prompt_addition: str | None = None,
    ) -> dict:
        now = datetime.now(UTC)
        existing = await self.find(user_id, model_unique_id)

        if existing:
            update_fields: dict = {"updated_at": now}
            if is_favourite is not None:
                update_fields["is_favourite"] = is_favourite
            if is_hidden is not None:
                update_fields["is_hidden"] = is_hidden
            if custom_display_name is not None:
                update_fields["custom_display_name"] = custom_display_name
            if custom_context_window is not None:
                update_fields["custom_context_window"] = custom_context_window
            if notes is not None:
                update_fields["notes"] = notes
            if system_prompt_addition is not None:
                update_fields["system_prompt_addition"] = system_prompt_addition
            await self._collection.update_one(
                {"_id": existing["_id"]},
                {"$set": update_fields},
            )
            return await self.find(user_id, model_unique_id)

        doc = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "model_unique_id": model_unique_id,
            "is_favourite": is_favourite if is_favourite is not None else False,
            "is_hidden": is_hidden if is_hidden is not None else False,
            "custom_display_name": custom_display_name,
            "custom_context_window": custom_context_window,
            "notes": notes,
            "system_prompt_addition": system_prompt_addition,
            "created_at": now,
            "updated_at": now,
        }
        await self._collection.insert_one(doc)
        return doc

    async def delete(self, user_id: str, model_unique_id: str) -> bool:
        result = await self._collection.delete_one(
            {"user_id": user_id, "model_unique_id": model_unique_id}
        )
        return result.deleted_count > 0

    async def list_for_user(self, user_id: str) -> list[dict]:
        cursor = self._collection.find({"user_id": user_id})
        return await cursor.to_list(length=1000)

    @staticmethod
    def to_dto(doc: dict) -> UserModelConfigDto:
        return UserModelConfigDto(
            model_unique_id=doc["model_unique_id"],
            is_favourite=doc.get("is_favourite", False),
            is_hidden=doc.get("is_hidden", False),
            custom_display_name=doc.get("custom_display_name"),
            custom_context_window=doc.get("custom_context_window"),
            notes=doc.get("notes"),
            system_prompt_addition=doc.get("system_prompt_addition"),
        )

    @staticmethod
    def default_dto(model_unique_id: str) -> UserModelConfigDto:
        return UserModelConfigDto(model_unique_id=model_unique_id)

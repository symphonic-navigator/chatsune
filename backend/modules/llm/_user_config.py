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
        fields: dict,
    ) -> dict:
        """Create or update a user model config.

        ``fields`` contains only the keys that were explicitly sent in the
        request (determined via Pydantic ``model_fields_set``).  This allows
        nullable fields to be reset to ``None`` -- a bare ``None`` default
        would be indistinguishable from "not sent".

        Uses atomic find_one_and_update with upsert=True to avoid TOCTOU races.
        """
        now = datetime.now(UTC)
        defaults = {
            "is_favourite": False,
            "is_hidden": False,
            "custom_display_name": None,
            "custom_context_window": None,
            "custom_supports_reasoning": None,
            "notes": None,
            "system_prompt_addition": None,
        }
        # Remove keys that are explicitly set in fields from defaults
        set_on_insert = {k: v for k, v in defaults.items() if k not in fields}
        set_on_insert["_id"] = str(uuid4())
        set_on_insert["user_id"] = user_id
        set_on_insert["model_unique_id"] = model_unique_id
        set_on_insert["created_at"] = now

        result = await self._collection.find_one_and_update(
            {"user_id": user_id, "model_unique_id": model_unique_id},
            {
                "$set": {"updated_at": now, **fields},
                "$setOnInsert": set_on_insert,
            },
            upsert=True,
            return_document=True,
        )
        return result

    async def delete(self, user_id: str, model_unique_id: str) -> bool:
        result = await self._collection.delete_one(
            {"user_id": user_id, "model_unique_id": model_unique_id}
        )
        return result.deleted_count > 0

    async def delete_all_for_user(self, user_id: str) -> int:
        """Delete every user_model_config owned by ``user_id``.

        Used by the user self-delete cascade (right-to-be-forgotten).
        """
        result = await self._collection.delete_many({"user_id": user_id})
        return result.deleted_count

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
            custom_supports_reasoning=doc.get("custom_supports_reasoning"),
            notes=doc.get("notes"),
            system_prompt_addition=doc.get("system_prompt_addition"),
        )

    @staticmethod
    def default_dto(model_unique_id: str) -> UserModelConfigDto:
        return UserModelConfigDto(model_unique_id=model_unique_id)

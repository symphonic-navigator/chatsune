from datetime import UTC, datetime
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from shared.dtos.llm import ModelCurationDto, ModelRating


class CurationRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db["llm_model_curations"]

    async def create_indexes(self) -> None:
        await self._collection.create_index(
            [("provider_id", 1), ("model_slug", 1)], unique=True
        )

    async def find(self, provider_id: str, model_slug: str) -> dict | None:
        return await self._collection.find_one(
            {"provider_id": provider_id, "model_slug": model_slug}
        )

    async def upsert(
        self,
        provider_id: str,
        model_slug: str,
        overall_rating: str,
        hidden: bool,
        admin_description: str | None,
        admin_user_id: str,
    ) -> dict:
        now = datetime.now(UTC)
        existing = await self.find(provider_id, model_slug)
        if existing:
            await self._collection.update_one(
                {"_id": existing["_id"]},
                {
                    "$set": {
                        "overall_rating": overall_rating,
                        "hidden": hidden,
                        "admin_description": admin_description,
                        "last_curated_at": now,
                        "last_curated_by": admin_user_id,
                    }
                },
            )
            return await self.find(provider_id, model_slug)
        doc = {
            "_id": str(uuid4()),
            "provider_id": provider_id,
            "model_slug": model_slug,
            "overall_rating": overall_rating,
            "hidden": hidden,
            "admin_description": admin_description,
            "last_curated_at": now,
            "last_curated_by": admin_user_id,
        }
        await self._collection.insert_one(doc)
        return doc

    async def delete(self, provider_id: str, model_slug: str) -> bool:
        result = await self._collection.delete_one(
            {"provider_id": provider_id, "model_slug": model_slug}
        )
        return result.deleted_count > 0

    async def list_for_provider(self, provider_id: str) -> list[dict]:
        cursor = self._collection.find({"provider_id": provider_id})
        return await cursor.to_list(length=1000)

    @staticmethod
    def to_dto(doc: dict) -> ModelCurationDto:
        return ModelCurationDto(
            overall_rating=ModelRating(doc["overall_rating"]),
            hidden=doc["hidden"],
            admin_description=doc.get("admin_description"),
            last_curated_at=doc["last_curated_at"],
            last_curated_by=doc["last_curated_by"],
        )

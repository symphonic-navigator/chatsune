from datetime import UTC, datetime
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from shared.dtos.persona import PersonaDto


class PersonaRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db["personas"]

    async def create_indexes(self) -> None:
        await self._collection.create_index("user_id")
        await self._collection.create_index([("user_id", 1), ("display_order", 1)])

    async def create(
        self,
        user_id: str,
        name: str,
        tagline: str,
        model_unique_id: str,
        system_prompt: str,
        temperature: float,
        reasoning_enabled: bool,
        colour_scheme: str,
        display_order: int,
    ) -> dict:
        now = datetime.now(UTC)
        doc = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "name": name,
            "tagline": tagline,
            "model_unique_id": model_unique_id,
            "system_prompt": system_prompt,
            "temperature": temperature,
            "reasoning_enabled": reasoning_enabled,
            "colour_scheme": colour_scheme,
            "display_order": display_order,
            "created_at": now,
            "updated_at": now,
        }
        await self._collection.insert_one(doc)
        return doc

    async def find_by_id(self, persona_id: str, user_id: str) -> dict | None:
        """Find persona by ID, scoped to the owning user."""
        return await self._collection.find_one(
            {"_id": persona_id, "user_id": user_id}
        )

    async def list_for_user(self, user_id: str) -> list[dict]:
        cursor = self._collection.find(
            {"user_id": user_id}
        ).sort("display_order", 1)
        return await cursor.to_list(length=500)

    async def update(self, persona_id: str, user_id: str, fields: dict) -> dict | None:
        fields["updated_at"] = datetime.now(UTC)
        result = await self._collection.update_one(
            {"_id": persona_id, "user_id": user_id}, {"$set": fields}
        )
        if result.matched_count == 0:
            return None
        return await self.find_by_id(persona_id, user_id)

    async def delete(self, persona_id: str, user_id: str) -> bool:
        result = await self._collection.delete_one(
            {"_id": persona_id, "user_id": user_id}
        )
        return result.deleted_count > 0

    @staticmethod
    def to_dto(doc: dict) -> PersonaDto:
        return PersonaDto(
            id=doc["_id"],
            user_id=doc["user_id"],
            name=doc["name"],
            tagline=doc["tagline"],
            model_unique_id=doc["model_unique_id"],
            system_prompt=doc["system_prompt"],
            temperature=doc["temperature"],
            reasoning_enabled=doc["reasoning_enabled"],
            colour_scheme=doc["colour_scheme"],
            display_order=doc["display_order"],
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )

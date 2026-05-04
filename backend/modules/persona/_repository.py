from datetime import UTC, datetime
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from shared.dtos.integrations import PersonaIntegrationConfigDto
from shared.dtos.mcp import PersonaMcpConfig
from shared.dtos.persona import PersonaDto, ProfileCropDto, VoiceConfigDto


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
        nsfw: bool,
        colour_scheme: str,
        display_order: int,
        pinned: bool = False,
        profile_image: str | None = None,
        soft_cot_enabled: bool = False,
        vision_fallback_model: str | None = None,
        use_memory: bool = True,
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
            "soft_cot_enabled": soft_cot_enabled,
            "vision_fallback_model": vision_fallback_model,
            "use_memory": use_memory,
            "nsfw": nsfw,
            "colour_scheme": colour_scheme,
            "display_order": display_order,
            "monogram": "",
            "pinned": pinned,
            "profile_image": profile_image,
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

    async def update_profile_image(
        self, persona_id: str, user_id: str, profile_image: str | None,
    ) -> dict | None:
        now = datetime.now(UTC)
        result = await self._collection.find_one_and_update(
            {"_id": persona_id, "user_id": user_id},
            {"$set": {"profile_image": profile_image, "updated_at": now}},
            return_document=True,
        )
        return result

    async def update_profile_crop(
        self, persona_id: str, user_id: str, crop: dict | None,
    ) -> dict | None:
        now = datetime.now(UTC)
        result = await self._collection.find_one_and_update(
            {"_id": persona_id, "user_id": user_id},
            {"$set": {"profile_crop": crop, "updated_at": now}},
            return_document=True,
        )
        return result

    async def update_mcp_config(
        self, persona_id: str, user_id: str, mcp_config: dict | None,
    ) -> bool:
        result = await self._collection.update_one(
            {"_id": persona_id, "user_id": user_id},
            {"$set": {"mcp_config": mcp_config, "updated_at": datetime.now(UTC)}},
        )
        return result.modified_count > 0

    async def bulk_reorder(self, user_id: str, ordered_ids: list[str]) -> None:
        """Reorder personas using a single bulk_write operation."""
        from pymongo import UpdateOne
        operations = [
            UpdateOne(
                {"_id": pid, "user_id": user_id},
                {"$set": {"display_order": i, "updated_at": datetime.now(UTC)}},
            )
            for i, pid in enumerate(ordered_ids)
        ]
        if operations:
            await self._collection.bulk_write(operations, ordered=False)

    async def bump_last_used(self, persona_id: str, user_id: str) -> None:
        """Stamp last_used_at = now on this persona. No-op if not found.

        Called when a chat session is created or resumed for the persona.
        Errors are swallowed by the public API wrapper — sidebar LRU
        ordering is not load-bearing enough to break the chat write path.
        """
        await self._collection.update_one(
            {"_id": persona_id, "user_id": user_id},
            {"$set": {"last_used_at": datetime.now(UTC)}},
        )

    async def delete(self, persona_id: str, user_id: str) -> bool:
        result = await self._collection.delete_one(
            {"_id": persona_id, "user_id": user_id}
        )
        return result.deleted_count > 0

    async def remove_library_from_all_personas(
        self, user_id: str, library_id: str,
    ) -> int:
        """Pull a deleted library id from every persona that referenced it.

        Returns the number of persona documents that were updated. Used by
        the knowledge-library cascade to maintain bidirectional consistency.
        """
        result = await self._collection.update_many(
            {"user_id": user_id, "knowledge_library_ids": library_id},
            {"$pull": {"knowledge_library_ids": library_id}},
        )
        return result.modified_count

    async def list_monograms_for_user(
        self, user_id: str, exclude_persona_id: str | None = None,
    ) -> set[str]:
        query: dict = {"user_id": user_id, "monogram": {"$exists": True, "$ne": ""}}
        if exclude_persona_id:
            query["_id"] = {"$ne": exclude_persona_id}
        cursor = self._collection.find(query, {"monogram": 1})
        docs = await cursor.to_list(length=500)
        return {doc["monogram"] for doc in docs}

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
            soft_cot_enabled=doc.get("soft_cot_enabled", False),
            vision_fallback_model=doc.get("vision_fallback_model"),
            nsfw=doc.get("nsfw", False),
            use_memory=doc.get("use_memory", True),
            colour_scheme=doc["colour_scheme"],
            display_order=doc["display_order"],
            monogram=doc.get("monogram", "??"),
            pinned=doc.get("pinned", False),
            profile_image=doc.get("profile_image"),
            profile_crop=ProfileCropDto(**doc["profile_crop"]) if doc.get("profile_crop") else None,
            mcp_config=PersonaMcpConfig(**doc["mcp_config"]) if doc.get("mcp_config") else None,
            integration_configs=doc.get("integration_configs", {}),
            integrations_config=(
                PersonaIntegrationConfigDto(**doc["integrations_config"])
                if doc.get("integrations_config") else None
            ),
            voice_config=VoiceConfigDto(**doc["voice_config"]) if doc.get("voice_config") else None,
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
            last_used_at=doc.get("last_used_at"),
            # Mindspace: legacy personas lack ``default_project_id``;
            # ``doc.get`` defaults to ``None`` matching the DTO.
            default_project_id=doc.get("default_project_id"),
        )

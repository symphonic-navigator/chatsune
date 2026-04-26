"""Repositories for the images module."""

from datetime import datetime
from typing import Iterable

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.modules.images._models import GeneratedImageDocument


class GeneratedImagesRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db["generated_images"]

    async def create_indexes(self) -> None:
        await self._collection.create_index([("user_id", 1), ("generated_at", -1)])
        await self._collection.create_index([("user_id", 1), ("id", 1)], unique=True)

    async def insert(self, doc: GeneratedImageDocument) -> None:
        payload = doc.model_dump()
        # Use the document's id as the Mongo _id to make ownership-checked
        # finds simple and idempotent. Composite (user_id, id) unique index
        # provides the actual safety net.
        payload["_id"] = doc.id
        await self._collection.insert_one(payload)

    async def insert_many(self, docs: Iterable[GeneratedImageDocument]) -> None:
        payloads = []
        for d in docs:
            p = d.model_dump()
            p["_id"] = d.id
            payloads.append(p)
        if payloads:
            await self._collection.insert_many(payloads)

    async def find_for_user(
        self, *, user_id: str, image_id: str
    ) -> GeneratedImageDocument | None:
        raw = await self._collection.find_one({"user_id": user_id, "id": image_id})
        if raw is None:
            return None
        raw.pop("_id", None)
        return GeneratedImageDocument.model_validate(raw)

    async def list_for_user(
        self,
        *,
        user_id: str,
        limit: int,
        before: datetime | None,
    ) -> list[GeneratedImageDocument]:
        query: dict = {"user_id": user_id}
        if before is not None:
            query["generated_at"] = {"$lt": before}
        cursor = self._collection.find(query).sort("generated_at", -1).limit(limit)
        rows = await cursor.to_list(length=limit)
        out: list[GeneratedImageDocument] = []
        for r in rows:
            r.pop("_id", None)
            out.append(GeneratedImageDocument.model_validate(r))
        return out

    async def delete_for_user(self, *, user_id: str, image_id: str) -> bool:
        result = await self._collection.delete_one(
            {"user_id": user_id, "id": image_id}
        )
        return result.deleted_count > 0

    async def delete_all_for_user(self, *, user_id: str) -> int:
        """Delete every generated image owned by ``user_id``.

        Used by the user self-delete cascade (right-to-be-forgotten).
        """
        result = await self._collection.delete_many({"user_id": user_id})
        return result.deleted_count
